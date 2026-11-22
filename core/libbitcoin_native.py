"""Libbitcoin-Abfrage auf dem eigenen Indexer.

Nur wenn der Electrum-Handshake dieses Sockets ``libbitcoin`` sagt und der
Host ``FULCRUM_HOST`` oder ``FULCRUM_TOR`` ist. Öffentliche Server bleiben
beim Electrum-Protokoll. Ein fehlender Adressindex oder eine abweichende
Skript-Hash-Reihenfolge schaltet die Sitzung auf Electrum zurück.
Der Index steht an der Wurzel (``address``) oder, in der neueren
Fassung, unter ``store.address``.

Erlaubte Pfade: ``configuration``, ``address/<hash>`` (+ ``/confirmed``,
``/unconfirmed``), ``output/<txid>/<index>``, ``tx/<txid>`` als
``format=data``, ``tx/<txid>/header``. Kein Core-RPC, keine Weiterleitung.

Die Diagnose nach ``logs/libbitcoin-native.log`` ist aus. Sie läuft nur
mit ``LIBBITCOIN_NATIVE_DEBUG=1``. Skript-Hashes werden gekürzt,
Transaktions-Hashes bleiben. Adressen stehen nicht drin.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import time
from typing import Any

from core.fulcrum_client import address_to_scripthash
from core.outbound_policy import ensure_resolves_to_allowed_host, normalize_host

# libbitcoin-server bindet die Abfrage je nach Fassung auf 8181 oder 8180.
# Ohne LIBBITCOIN_NATIVE_PORT gelten beide; die Antwort mit Adress-Flag gewinnt.
# Der Port, der in diesem Prozess antwortet, bleibt es. Der andere wird
# nicht erneut verbunden.
_KANDIDATEN_PORTS = (8181, 8180)
_port_merker: dict[tuple[str, tuple[int, ...]], int] = {}
_port_sperre = threading.Lock()
_MAX_ANTWORT = 8_000_000
_LEER = object()

_PFAD = re.compile(
    r"^(configuration"
    r"|address/[0-9a-fA-F]{64}(?:/(?:confirmed|unconfirmed))?"
    r"|output/[0-9a-fA-F]{64}/[0-9]{1,8}"
    r"|tx/[0-9a-fA-F]{64}(?:/header)?)$"
)

_OP: dict[str, int] = {
    "0": 0x00,
    "zero": 0x00,
    "false": 0x00,
    "dup": 0x76,
    "op_dup": 0x76,
    "hash160": 0xA9,
    "op_hash160": 0xA9,
    "equal": 0x87,
    "op_equal": 0x87,
    "equalverify": 0x88,
    "op_equalverify": 0x88,
    "checksig": 0xAC,
    "op_checksig": 0xAC,
    "checksigverify": 0xAD,
    "op_checksigverify": 0xAD,
    "checkmultisig": 0xAE,
    "op_checkmultisig": 0xAE,
    "return": 0x6A,
    "op_return": 0x6A,
    "drop": 0x75,
    "op_drop": 0x75,
    "verify": 0x69,
    "nop": 0x61,
}
for _n in range(1, 17):
    _OP[str(_n)] = 0x50 + _n
    _OP[f"op_{_n}"] = 0x50 + _n


class NativeFehler(Exception):
    """Eine native Antwort, die nicht als leere Menge gilt."""

    def __init__(
        self,
        text: str,
        *,
        index_aus: bool = False,
        unbrauchbar: bool = False,
        roh: bytes = b"",
    ) -> None:
        super().__init__(text)
        self.index_aus = index_aus
        self.unbrauchbar = unbrauchbar
        self.roh = roh


def _nicht_implementiert(daten: bytes | None) -> bool:
    if not daten:
        return False
    klein = daten.lower()
    return b"not implemented" in klein or b"not_implemented" in klein


def _routenart(pfad: str) -> str:
    """Gleiche Art für jede Adresse: ein abgelehnter Pfad gilt für den Scan."""
    teile = [teil for teil in pfad.split("/") if teil]
    if not teile:
        return pfad
    if teile[0] == "address" and len(teile) >= 3:
        return f"address/{teile[2]}"
    if teile[0] == "tx" and len(teile) >= 3:
        return f"tx/{teile[2]}"
    return teile[0]


def _host_aus_env(raw: str) -> str:
    text = str(raw or "").strip()
    for prefix in ("https://", "http://"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    if "/" in text:
        text = text.split("/", 1)[0]
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    return normalize_host(text)


def _werte_lesen(werte: dict[str, str] | None) -> dict[str, str]:
    if werte is not None:
        return werte
    try:
        from core.env_bootstrap import _load_dotenv

        geladen = _load_dotenv()
    except Exception:
        geladen = {}
    return geladen if isinstance(geladen, dict) else {}


def _enge_ports(host: str, ports: tuple[int, ...]) -> tuple[int, ...]:
    """Port, der in diesem Prozess schon geantwortet hat. Sonst die Kandidaten."""
    if len(ports) <= 1:
        return ports
    with _port_sperre:
        gemerkt = _port_merker.get((host, ports))
    if gemerkt in ports:
        return (gemerkt,)
    return ports


def _merke_antwort_port(host: str, ports: tuple[int, ...], port: int) -> None:
    if len(ports) <= 1 or port not in ports:
        return
    with _port_sperre:
        _port_merker.setdefault((host, ports), port)


def _ports_aus(werte: dict[str, str]) -> tuple[int, ...]:
    """Gesetzter Port bleibt allein. Sonst 8181, danach 8180."""
    roh = str(werte.get("LIBBITCOIN_NATIVE_PORT") or os.environ.get("LIBBITCOIN_NATIVE_PORT") or "")
    roh = roh.strip()
    if not roh:
        return _KANDIDATEN_PORTS
    try:
        port = int(roh)
    except ValueError:
        return _KANDIDATEN_PORTS
    if 1 <= port <= 65535:
        return (port,)
    return _KANDIDATEN_PORTS


def _address_flag(daten: Any) -> Any:
    """Adressindex. Alte Fassung an der Wurzel, neue unter ``store``.

    ``network.address`` ist ein anderes Feld und zählt nicht.
    """
    if not isinstance(daten, dict):
        return None
    if "address" in daten:
        return daten.get("address")
    store = daten.get("store")
    if isinstance(store, dict) and "address" in store:
        return store.get("address")
    return None


def _flag_an(flag: Any) -> bool:
    if flag is True:
        return True
    return isinstance(flag, str) and flag.strip().lower() == "true"


def _libbitcoin_antwortet(daten: Any) -> bool:
    """Die native Konfiguration trägt den Adressindex, Wurzel oder ``store``."""
    if not isinstance(daten, dict):
        return False
    if "address" in daten:
        return True
    store = daten.get("store")
    return isinstance(store, dict) and "address" in store


def _eigene_hosts(werte: dict[str, str]) -> set[str]:
    hosts: set[str] = set()
    for schluessel in ("FULCRUM_HOST", "FULCRUM_TOR"):
        name = _host_aus_env(werte.get(schluessel, ""))
        if name:
            hosts.add(name)
    return hosts


def _address_index_an(daten: Any) -> bool:
    return _flag_an(_address_flag(daten))


def _address_lage(daten: Any) -> str:
    """Wo das Feld ``address`` steht. Die neuere Doku legt es unter ``store``."""
    if not isinstance(daten, dict):
        return type(daten).__name__
    if "address" in daten:
        return "wurzel"
    store = daten.get("store")
    if isinstance(store, dict) and "address" in store:
        return "store"
    return "fehlt"


def _form(daten: Any) -> str:
    """Schlüsselnamen, keine Werte. Reicht, um eine geänderte Antwort zu sehen."""
    if isinstance(daten, dict):
        return "dict:" + ",".join(sorted(str(k) for k in list(daten)[:12]))
    if isinstance(daten, list):
        if not daten:
            return "list:0"
        erste = daten[0]
        if isinstance(erste, dict):
            namen = ",".join(sorted(str(k) for k in list(erste)[:8]))
            return f"list:{len(daten)}:{namen}"
        return f"list:{len(daten)}:{type(erste).__name__}"
    if isinstance(daten, (bytes, bytearray)):
        return f"bytes:{len(daten)}"
    return type(daten).__name__


def _pfad_fuer_log(pfad: str) -> str:
    """Skript-Hash kürzen. Transaktions-Hashes bleiben, die Diagnose braucht sie."""
    teile = pfad.split("/")
    if (
        teile
        and teile[0] == "address"
        and len(teile) > 1
        and re.fullmatch(r"[0-9a-fA-F]{64}", teile[1])
    ):
        teile[1] = teile[1][:8].lower()
    return "/".join(teile)


_DIAGNOSE_DATEI = "libbitcoin-native.log"
_DIAGNOSE_MAX = 64 * 1024 * 1024
_DIAGNOSE_SPERRE = threading.Lock()
_DIAGNOSE_FRISCH = False
_LAUF = 0


def _diagnose_an() -> bool:
    """Aus, solange ``LIBBITCOIN_NATIVE_DEBUG`` nicht ausdrücklich an ist."""
    roh = os.environ.get("LIBBITCOIN_NATIVE_DEBUG", "").strip().lower()
    return roh in ("1", "true", "ja", "yes", "on", "an")


def _diagnose_pfad():
    from core.paths import log_dir
    return log_dir() / _DIAGNOSE_DATEI


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _diagnose(lauf: int, text: str) -> None:
    """Eine Zeile nach ``logs/libbitcoin-native.log``. Fehler hier stoppen nichts."""
    if not _diagnose_an():
        return
    zeile = " ".join(str(text or "").split())
    if not zeile:
        return
    global _DIAGNOSE_FRISCH
    kopf = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        with _DIAGNOSE_SPERRE:
            datei = _diagnose_pfad()
            datei.parent.mkdir(parents=True, exist_ok=True)
            if not _DIAGNOSE_FRISCH:
                datei.write_text("", encoding="utf-8")
                _DIAGNOSE_FRISCH = True
            if datei.is_file() and datei.stat().st_size > _DIAGNOSE_MAX:
                return
            with datei.open("a", encoding="utf-8") as aus:
                aus.write(f"{kopf} lauf={lauf} {zeile}\n")
                aus.flush()
    except OSError:
        return


def _neuer_lauf() -> int:
    global _LAUF
    with _DIAGNOSE_SPERRE:
        _LAUF += 1
        return _LAUF


def _push(daten: bytes) -> bytes:
    laenge = len(daten)
    if laenge < 0x4C:
        return bytes([laenge]) + daten
    if laenge <= 0xFF:
        return bytes([0x4C, laenge]) + daten
    if laenge <= 0xFFFF:
        return b"\x4d" + laenge.to_bytes(2, "little") + daten
    return b"\x4e" + laenge.to_bytes(4, "little") + daten


def skript_aus_nativ(script: Any) -> bytes | None:
    """Hex, ``{"hex": ...}`` oder libbitcoin-Mnemonik (``0 [hash]``)."""
    if isinstance(script, dict):
        script = script.get("hex") or script.get("script")
    if not isinstance(script, str):
        return None
    text = script.strip()
    if not text:
        return None
    if re.fullmatch(r"[0-9a-fA-F]{2,}", text) and len(text) % 2 == 0:
        try:
            return bytes.fromhex(text)
        except ValueError:
            return None
    teile: list[bytes] = []
    for token in text.split():
        klammer = re.fullmatch(r"[\[<]([0-9a-fA-F]*)[\]>]", token)
        if klammer:
            roh = klammer.group(1)
            if len(roh) % 2 != 0:
                return None
            try:
                teile.append(_push(bytes.fromhex(roh)))
            except ValueError:
                return None
            continue
        opcode = _OP.get(token.lower())
        if opcode is None:
            return None
        teile.append(bytes([opcode]))
    if not teile:
        return None
    return b"".join(teile)


def _json_bytes(roh: bytes) -> Any:
    try:
        return json.loads(roh.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise NativeFehler("JSON", unbrauchbar=True) from exc


def _als_liste(daten: Any) -> list:
    if daten is None:
        return []
    if isinstance(daten, list):
        return daten
    if isinstance(daten, dict):
        for schluessel in ("outpoints", "points", "result"):
            nested = daten.get(schluessel)
            if isinstance(nested, list):
                return nested
            if isinstance(nested, dict):
                return [nested]
        return [daten]
    raise NativeFehler("Outpoints", unbrauchbar=True)


def _punkt(eintrag: Any) -> tuple[str, int, int | None] | None:
    if not isinstance(eintrag, dict):
        return None
    quelle = eintrag.get("point") if isinstance(eintrag.get("point"), dict) else eintrag
    if not isinstance(quelle, dict):
        return None
    roh_hash = quelle.get("hash") or quelle.get("txid") or quelle.get("tx_hash")
    index = quelle.get("index", quelle.get("vout", quelle.get("tx_pos")))
    if not isinstance(roh_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", roh_hash):
        return None
    try:
        vout = int(index)
    except (TypeError, ValueError):
        return None
    if vout < 0:
        return None
    wert = eintrag.get("value", quelle.get("value"))
    sats: int | None
    try:
        sats = int(wert) if wert is not None else None
    except (TypeError, ValueError):
        sats = None
    return roh_hash.lower(), vout, sats


def _outpoints(daten: Any) -> list[tuple[str, int, int | None]]:
    punkte: list[tuple[str, int, int | None]] = []
    for eintrag in _als_liste(daten):
        punkt = _punkt(eintrag)
        if punkt is None:
            raise NativeFehler("Outpoint", unbrauchbar=True)
        punkte.append(punkt)
    return punkte


def _header_felder(daten: Any) -> tuple[int | None, int | None]:
    if not isinstance(daten, dict):
        raise NativeFehler("Header")
    kopf = daten.get("header") if isinstance(daten.get("header"), dict) else daten
    if not isinstance(kopf, dict):
        raise NativeFehler("Header")
    hoehe_roh = kopf.get("height", kopf.get("block_height"))
    zeit_roh = kopf.get("timestamp", kopf.get("time", kopf.get("blocktime")))
    try:
        hoehe = int(hoehe_roh) if hoehe_roh is not None else None
    except (TypeError, ValueError):
        hoehe = None
    try:
        zeit = int(zeit_roh) if zeit_roh is not None else None
    except (TypeError, ValueError):
        zeit = None
    return hoehe, zeit


def _tx_hex(roh: bytes) -> str:
    try:
        text = roh.decode("ascii").strip()
    except UnicodeError:
        return roh.hex()
    if re.fullmatch(r"[0-9a-fA-F]{20,}", text) and len(text) % 2 == 0:
        return text.lower()
    return roh.hex()


class _Leser:
    """Socket-Puffer, damit ein vorgezogener Chunk-Rest nicht verloren geht."""

    def __init__(self, sock: socket.socket, vorab: bytes) -> None:
        self.sock = sock
        self.rest = vorab

    def lies(self, laenge: int) -> bytes:
        if laenge < 0 or laenge > _MAX_ANTWORT:
            raise NativeFehler("Antwort zu groß")
        while len(self.rest) < laenge:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise NativeFehler("Verbindung zu")
            self.rest += chunk
            if len(self.rest) > _MAX_ANTWORT + laenge:
                raise NativeFehler("Antwort zu groß")
        daten, self.rest = self.rest[:laenge], self.rest[laenge:]
        return daten

    def zeile(self) -> bytes:
        while b"\r\n" not in self.rest:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise NativeFehler("Chunk")
            self.rest += chunk
            if len(self.rest) > _MAX_ANTWORT:
                raise NativeFehler("Antwort zu groß")
        zeile, self.rest = self.rest.split(b"\r\n", 1)
        return zeile

    def bis_ende(self) -> bytes:
        while len(self.rest) <= _MAX_ANTWORT:
            try:
                chunk = self.sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            self.rest += chunk
        if len(self.rest) > _MAX_ANTWORT:
            raise NativeFehler("Antwort zu groß")
        daten, self.rest = self.rest, b""
        return daten


def _lies_chunked(leser: _Leser) -> bytes:
    teile: list[bytes] = []
    gesamt = 0
    while True:
        zeile = leser.zeile()
        try:
            laenge = int(zeile.strip().split(b";", 1)[0], 16)
        except ValueError as exc:
            raise NativeFehler("Chunk") from exc
        if laenge == 0:
            leser.lies(0)
            return b"".join(teile)
        gesamt += laenge
        if gesamt > _MAX_ANTWORT:
            raise NativeFehler("Antwort zu groß")
        teile.append(leser.lies(laenge))
        trenner = leser.lies(2)
        if trenner != b"\r\n":
            raise NativeFehler("Chunk")


def _lies_http(sock: socket.socket) -> tuple[int, bytes]:
    puffer = b""
    while b"\r\n\r\n" not in puffer:
        chunk = sock.recv(65536)
        if not chunk:
            raise NativeFehler("Verbindung zu", roh=puffer)
        puffer += chunk
        if len(puffer) > _MAX_ANTWORT:
            raise NativeFehler("Antwort zu groß")
    kopf_roh, rest = puffer.split(b"\r\n\r\n", 1)
    zeilen = kopf_roh.decode("iso-8859-1", errors="replace").split("\r\n")
    if not zeilen or len(zeilen[0].split()) < 2:
        raise NativeFehler("Status")
    try:
        status = int(zeilen[0].split()[1])
    except ValueError as exc:
        raise NativeFehler("Status") from exc
    koepfe: dict[str, str] = {}
    for zeile in zeilen[1:]:
        if ":" not in zeile:
            continue
        name, wert = zeile.split(":", 1)
        koepfe[name.strip().lower()] = wert.strip()
    if 300 <= status < 400:
        raise NativeFehler("Weiterleitung")
    leser = _Leser(sock, rest)
    if "chunked" in koepfe.get("transfer-encoding", "").lower():
        return status, _lies_chunked(leser)
    if "content-length" in koepfe:
        try:
            laenge = int(koepfe["content-length"])
        except ValueError as exc:
            raise NativeFehler("Länge") from exc
        return status, leser.lies(laenge)
    return status, leser.bis_ende()


class NativeSitzung:
    """Eine Entscheidung je Electrum-Client, nicht je Adresse."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float,
        tor_proxy: tuple[str, int] | None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.tor_proxy = tor_proxy
        self.aktiv = False
        self.unterdrueckt = False
        self.hash_bestaetigt = False
        self.hash_intern = False
        self.hydrate_aus_cache = True
        self.grund = ""
        self.anfragen = 0
        self.antwort_bytes = 0
        self.pfade: list[str] = []
        self.ports: tuple[int, ...] = ()
        self._tot: set[str] = set()
        self._tot_gemeldet: set[str] = set()
        self._lock = threading.Lock()
        self._karte_fertig = False
        self._bekannt: dict[tuple[str, int], dict] = {}
        self.lauf = _neuer_lauf()
        self.log = None
        self._formen: set[str] = set()
        self._luecke_gemeldet = False
        self._utxo_warte_gemeldet = False
        self._tx_warte_gemeldet = False

    def nutzbar(self) -> bool:
        return self.aktiv and not self.unterdrueckt

    def _diagnose(self, text: str) -> None:
        _diagnose(self.lauf, text)

    def _melde(self, text: str) -> None:
        """Job-Log nur für eine Entscheidung, und nur bei eingeschalteter Diagnose."""
        self._diagnose(text)
        if not _diagnose_an():
            return
        melde = self.log
        if melde is None:
            return
        try:
            melde(text)
        except Exception:
            return

    def _hash(self, address: str, *, intern: bool | None = None) -> str:
        umdrehen = self.hash_intern if intern is None else intern
        if not umdrehen:
            return address_to_scripthash(address)
        from embit.script import address_to_scriptpubkey

        skript = address_to_scriptpubkey(address).data
        return hashlib.sha256(skript).hexdigest()

    def _verbinde(self) -> socket.socket:
        ensure_resolves_to_allowed_host(self.host, service="fulcrum")
        from core.fulcrum_transport import _socks5_connect, merke_kette_socket

        if self.tor_proxy:
            proxy_host, proxy_port = self.tor_proxy
            return _socks5_connect(
                proxy_host,
                proxy_port,
                self.host,
                self.port,
                int(self.timeout) or 1,
            )
        roh = socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout,
        )
        merke_kette_socket(roh)
        try:
            roh.settimeout(float(self.timeout))
        except OSError:
            pass
        return roh

    def _anfrage(self, pfad: str, *, datenformat: str) -> tuple[int, bytes]:
        if int(self.port) in (50001, 50002):
            self.aktiv = False
            self.grund = "electrum-port"
            self._diagnose(f"anfrage abgelehnt port={self.port} grund=electrum-port")
            raise NativeFehler("Electrum-Port")
        if datenformat not in ("json", "data"):
            raise NativeFehler("Format")
        if not _PFAD.fullmatch(pfad):
            raise NativeFehler("Pfad")
        self.anfragen += 1
        self.pfade.append(pfad)
        abfrage = f"/v1/{pfad}?format={datenformat}"
        ziel = self.host
        if ":" in ziel and not ziel.startswith("["):
            ziel = f"[{ziel}]"
        kopf = (
            f"GET {abfrage} HTTP/1.1\r\n"
            f"Host: {ziel}:{self.port}\r\n"
            "Accept: application/json, application/octet-stream\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        from core.fulcrum_transport import vergiss_kette_socket

        sock = self._verbinde()
        try:
            sock.sendall(kopf)
            status, body = _lies_http(sock)
        finally:
            vergiss_kette_socket(sock)
            try:
                sock.close()
            except OSError:
                pass
        self.antwort_bytes += len(body)
        return status, body

    def _holen(self, pfad: str, *, datenformat: str) -> Any:
        art = _routenart(pfad)
        kurz = _pfad_fuer_log(pfad)
        unbestaetigt = pfad.endswith("/unconfirmed")
        if art in self._tot:
            if art not in self._tot_gemeldet:
                self._tot_gemeldet.add(art)
                self._diagnose(f"holen {kurz} aus cache tot")
            if unbestaetigt:
                return _LEER
            raise NativeFehler("nicht implementiert")
        start = time.perf_counter()
        try:
            status, body = self._anfrage(pfad, datenformat=datenformat)
        except NativeFehler as exc:
            self._diagnose(
                f"holen {kurz} fehler={exc} ms={_ms(start)}"
            )
            if _nicht_implementiert(exc.roh):
                self._tot.add(art)
                if unbestaetigt:
                    return _LEER
            raise
        except OSError as exc:
            self._diagnose(
                f"holen {kurz} fehler=Netz art={type(exc).__name__} ms={_ms(start)}"
            )
            raise NativeFehler("Netz") from exc
        ms = _ms(start)
        if status == 404:
            self._diagnose(f"holen {kurz} status=404 bytes={len(body)} ms={ms}")
            return _LEER
        if status == 501 or _nicht_implementiert(body):
            self._tot.add(art)
            self._diagnose(f"holen {kurz} status={status} nicht-implementiert ms={ms}")
            if unbestaetigt:
                return _LEER
            raise NativeFehler("nicht implementiert")
        if status != 200:
            self._diagnose(f"holen {kurz} status={status} bytes={len(body)} ms={ms}")
            raise NativeFehler(f"HTTP {status}")
        if datenformat == "data":
            self._diagnose(f"holen {kurz} status=200 bytes={len(body)} ms={ms} art=data")
            return body
        daten = _json_bytes(body)
        form = _form(daten)
        if form not in self._formen:
            self._formen.add(form)
            self._diagnose(
                f"holen {kurz} status=200 bytes={len(body)} ms={ms} form={form}"
            )
        else:
            self._diagnose(f"holen {kurz} status=200 bytes={len(body)} ms={ms}")
        return daten

    def _index_aus(self, exc: NativeFehler) -> None:
        if exc.index_aus:
            self.aktiv = False
            self.grund = "index"

    def benutzt(self, address: str) -> bool | None:
        """None: diese Abfrage bleibt bei Electrum. Sonst 404/200 der Adresse."""
        if not self.nutzbar() or not self.hash_bestaetigt:
            if not self._luecke_gemeldet:
                self._luecke_gemeldet = True
                self._diagnose(
                    f"luecke wartet nutzbar={self.nutzbar()} "
                    f"hash={self.hash_bestaetigt} grund={self.grund or '-'}"
                )
            return None
        try:
            daten = self._holen(f"address/{self._hash(address)}", datenformat="json")
        except NativeFehler as exc:
            self._index_aus(exc)
            self._diagnose(f"luecke aus fehler={exc}")
            return None
        self._diagnose("luecke " + ("treffer" if daten is not _LEER else "leer"))
        return daten is not _LEER

    def _punkte(
        self,
        address: str,
        art: str,
        *,
        intern: bool | None = None,
    ) -> list[tuple[str, int, int | None]]:
        pfad = f"address/{self._hash(address, intern=intern)}/{art}"
        daten = self._holen(pfad, datenformat="json")
        if daten is _LEER:
            return []
        return _outpoints(daten)

    def merke_hash(self, address: str, entries: list) -> None:
        """Erst ein nicht-leeres listunspent darf 404 als unbenutzt gelten."""
        if not self.aktiv or self.hash_bestaetigt or not entries:
            return
        bestaetigt: set[tuple[str, int]] = set()
        offen: set[tuple[str, int]] = set()
        for eintrag in entries:
            if not isinstance(eintrag, dict):
                continue
            txid = str(eintrag.get("tx_hash") or "")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", txid):
                continue
            try:
                vout = int(eintrag.get("tx_pos"))
                hoehe = int(eintrag.get("height") or 0)
            except (TypeError, ValueError):
                continue
            ziel = bestaetigt if hoehe > 0 else offen
            ziel.add((txid.lower(), vout))
        if bestaetigt:
            art, erwartet = "confirmed", bestaetigt
        elif offen:
            art, erwartet = "unconfirmed", offen
        else:
            return
        for intern in (False, True):
            try:
                punkte = self._punkte(address, art, intern=intern)
            except NativeFehler as exc:
                self._index_aus(exc)
                self._diagnose(f"hash-probe aus fehler={exc}")
                if exc.unbrauchbar:
                    self.aktiv = False
                    self.grund = "antwort"
                    self._melde(
                        "libbitcoin-nativ: Antwort unbrauchbar — Electrum bleibt."
                    )
                return
            menge = {(txid, vout) for txid, vout, _wert in punkte}
            self._diagnose(
                f"hash-probe art={art} ordnung={'intern' if intern else 'electrum'} "
                f"erwartet={len(erwartet)} punkte={len(punkte)} "
                f"schnitt={len(menge & erwartet)}"
            )
            if menge == erwartet:
                self.hash_intern = intern
                self.hash_bestaetigt = True
                name = "interne Reihenfolge" if intern else "Electrum-Reihenfolge"
                self._melde(
                    f"libbitcoin-nativ: Skript-Hash festgelegt ({name})."
                )
                return
        self.aktiv = False
        self.grund = "hash"
        self._melde("libbitcoin-nativ: Skript-Hash passt nicht — Electrum bleibt.")

    def _cache_karte(self) -> dict[tuple[str, int], dict]:
        if self._karte_fertig:
            return self._bekannt
        self._karte_fertig = True
        if not self.hydrate_aus_cache:
            return self._bekannt
        try:
            from core.wallet_context import EXTERNAL_ADDRESS_CACHE_NAME
            from core.xpub_cache import UTXO_CACHE_DIR
        except Exception:
            return self._bekannt
        wurzel = UTXO_CACHE_DIR
        if not wurzel.is_dir():
            return self._bekannt
        for pfad in wurzel.glob("*.json"):
            if pfad.name == EXTERNAL_ADDRESS_CACHE_NAME:
                continue
            try:
                daten = json.loads(pfad.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(daten, dict):
                continue
            utxos = daten.get("utxos")
            if not isinstance(utxos, list):
                continue
            for utxo in utxos:
                if not isinstance(utxo, dict):
                    continue
                txid = str(utxo.get("txid") or "").lower()
                if not re.fullmatch(r"[0-9a-fA-F]{64}", txid):
                    continue
                try:
                    vout = int(utxo.get("vout"))
                    wert = int(utxo.get("value"))
                except (TypeError, ValueError):
                    continue
                status = utxo.get("status") if isinstance(utxo.get("status"), dict) else {}
                if status.get("confirmed") and not status.get("block_time"):
                    continue
                self._bekannt[(txid, vout)] = {
                    "txid": txid,
                    "vout": vout,
                    "value": wert,
                    "status": dict(status),
                }
        return self._bekannt

    def _output_wert(self, txid: str, vout: int) -> int:
        daten = self._holen(f"output/{txid}/{vout}", datenformat="json")
        if daten is _LEER or not isinstance(daten, dict) or "value" not in daten:
            raise NativeFehler("Output")
        return int(daten["value"])

    def _kopf(self, txid: str) -> tuple[int | None, int | None] | None:
        daten = self._holen(f"tx/{txid}/header", datenformat="json")
        if daten is _LEER:
            return None
        return _header_felder(daten)

    def utxos(self, address: str) -> list[dict] | None:
        if not self.nutzbar() or not self.hash_bestaetigt:
            if not self._utxo_warte_gemeldet:
                self._utxo_warte_gemeldet = True
                self._diagnose(
                    f"utxos wartet nutzbar={self.nutzbar()} "
                    f"hash={self.hash_bestaetigt} grund={self.grund or '-'}"
                )
            return None
        try:
            bestaetigt = self._punkte(address, "confirmed")
            offen = self._punkte(address, "unconfirmed")
        except NativeFehler as exc:
            self._index_aus(exc)
            self._diagnose(f"utxos aus fehler={exc}")
            return None
        except (TypeError, ValueError) as exc:
            self._diagnose(f"utxos aus parser={type(exc).__name__}")
            return None
        koepfe: dict[str, tuple[int | None, int | None] | None] = {}
        ergebnis: list[dict] = []
        gesehen: set[tuple[str, int]] = set()
        aus_cache = 0
        bestaetigt_keys = {(txid, vout) for txid, vout, _wert in bestaetigt}
        try:
            for txid, vout, wert in [*bestaetigt, *offen]:
                if (txid, vout) in gesehen:
                    continue
                gesehen.add((txid, vout))
                bekannt = self._cache_karte().get((txid, vout))
                if bekannt is not None:
                    aus_cache += 1
                    ergebnis.append({
                        "txid": bekannt["txid"],
                        "vout": bekannt["vout"],
                        "value": bekannt["value"],
                        "status": dict(bekannt["status"]),
                    })
                    continue
                if wert is None:
                    wert = self._output_wert(txid, vout)
                status: dict[str, object] = {
                    "confirmed": (txid, vout) in bestaetigt_keys,
                }
                if status["confirmed"]:
                    if txid not in koepfe:
                        koepfe[txid] = self._kopf(txid)
                    kopf = koepfe[txid]
                    if kopf is None:
                        raise NativeFehler("Header")
                    hoehe, zeit = kopf
                    if hoehe is None or zeit is None or hoehe <= 0:
                        raise NativeFehler("Header")
                    status["block_height"] = hoehe
                    status["block_time"] = zeit
                ergebnis.append({
                    "txid": txid,
                    "vout": vout,
                    "value": int(wert),
                    "status": status,
                })
        except NativeFehler as exc:
            self._index_aus(exc)
            self._diagnose(f"utxos aus fehler={exc}")
            return None
        except (TypeError, ValueError) as exc:
            self._diagnose(f"utxos aus parser={type(exc).__name__}")
            return None
        self._diagnose(
            f"utxos n={len(ergebnis)} bestaetigt={len(bestaetigt)} "
            f"offen={len(offen)} cache={aus_cache}"
        )
        return ergebnis

    def prevout(self, txid: str, vout: int) -> dict | None:
        """Wert, Adresse und Blockzeit ohne die Vorgänger-Transaktion."""
        if not self.nutzbar():
            return None
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(txid or "")):
            return None
        txid = str(txid).lower()
        try:
            vout = int(vout)
        except (TypeError, ValueError):
            return None
        if vout < 0:
            return None
        ziel = f"{txid}/{vout}"
        try:
            daten = self._holen(f"output/{txid}/{vout}", datenformat="json")
            if daten is _LEER or not isinstance(daten, dict):
                self._diagnose(f"prevout {ziel} aus=leer-oder-form")
                return None
            wert = int(daten["value"])
            skript = skript_aus_nativ(daten.get("script"))
            kopf = self._kopf(txid)
        except NativeFehler as exc:
            self._index_aus(exc)
            self._diagnose(f"prevout {ziel} aus fehler={exc}")
            return None
        except (TypeError, ValueError, KeyError) as exc:
            self._diagnose(f"prevout {ziel} aus parser={type(exc).__name__}")
            return None
        if skript is None or kopf is None:
            self._diagnose(
                f"prevout {ziel} aus skript={skript is not None} kopf={kopf is not None}"
            )
            return None
        hoehe, zeit = kopf
        if zeit is None or hoehe is None or hoehe <= 0:
            self._diagnose(f"prevout {ziel} aus hoehe={hoehe} zeit={zeit is not None}")
            return None
        try:
            from embit.script import Script

            from core.derivation import script_address

            adresse = script_address(Script(skript))
        except Exception:
            return None
        if not adresse:
            self._diagnose(f"prevout {ziel} aus=keine-adresse")
            return None
        self._diagnose(f"prevout {ziel} ok hoehe={hoehe}")
        return {
            "value": wert,
            "scriptpubkey": skript.hex(),
            "scriptpubkey_address": adresse,
            "_prev_tx_time_ts": int(zeit),
        }

    def transaktion(self, txid: str) -> dict | None:
        if not self.nutzbar():
            if not self._tx_warte_gemeldet:
                self._tx_warte_gemeldet = True
                self._diagnose(f"tx wartet grund={self.grund or '-'}")
            return None
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(txid or "")):
            return None
        txid = str(txid).lower()
        try:
            roh = self._holen(f"tx/{txid}", datenformat="data")
            if roh is _LEER or not isinstance(roh, (bytes, bytearray)):
                self._diagnose(f"tx {txid} aus=leer-oder-form")
                return None
            from core.fulcrum_history import _normalize_electrum_tx, _parse_tx_hex

            tx = _normalize_electrum_tx(_parse_tx_hex(_tx_hex(bytes(roh)), expected_txid=txid))
            kopf = self._kopf(txid)
        except NativeFehler as exc:
            self._index_aus(exc)
            self._diagnose(f"tx {txid} aus fehler={exc}")
            return None
        except (TypeError, ValueError, RuntimeError) as exc:
            self._diagnose(f"tx {txid} aus parser={type(exc).__name__}")
            return None
        if kopf is None:
            tx["confirmations"] = 0
            tx["status"] = {"confirmed": False}
            self._diagnose(f"tx {txid} ok unbestaetigt vin={len(tx.get('vin') or [])}")
            return tx
        hoehe, zeit = kopf
        if hoehe is None or zeit is None or hoehe <= 0:
            self._diagnose(f"tx {txid} aus hoehe={hoehe} zeit={zeit is not None}")
            return None
        self._diagnose(
            f"tx {txid} ok vin={len(tx.get('vin') or [])} hoehe={hoehe}"
        )
        tx["blockheight"] = hoehe
        tx["blocktime"] = int(zeit)
        tx["confirmations"] = max(int(tx.get("confirmations") or 0), 1)
        tx["status"] = {
            "confirmed": True,
            "block_height": hoehe,
            "block_time": int(zeit),
        }
        return tx


def _werte_fuer(client, werte: dict[str, str] | None) -> dict[str, str]:
    if werte is None:
        # Tests setzen das, damit nicht die .env des Rechners die Probe auslöst.
        gesetzt = getattr(client, "_libbitcoin_werte", None)
        if isinstance(gesetzt, dict):
            werte = gesetzt
    return _werte_lesen(werte)


def abfrage_hinweis(client, werte: dict[str, str] | None = None, *, log=None) -> str | None:
    """Eine Zeile fürs Job-Log, wenn dieser Client der eigene libbitcoin ist.

    Prüft die Abfrage einmal und legt die Sitzung am Client ab. Electrs,
    Fulcrum und ein fremder Server, der sich libbitcoin nennt, bleiben stumm.
    """
    if str(getattr(client, "server_software", "") or "") != "libbitcoin":
        return None
    if log is not None:
        try:
            client._libbitcoin_log = log
        except Exception:
            pass
    frisch = not isinstance(getattr(client, "_libbitcoin_native", None), NativeSitzung)
    if frisch and log is not None:
        geladen = _werte_fuer(client, werte)
        host = normalize_host(getattr(client, "host", "") or "")
        if host in _eigene_hosts(geladen):
            ports = _enge_ports(host, _ports_aus(geladen))
            if len(ports) == 1:
                log(f"Prüfe libbitcoin-Abfrage {host}:{ports[0]}…")
            else:
                namen = " und ".join(str(port) for port in ports)
                log(f"Prüfe libbitcoin-Abfrage {host} auf {namen}…")
    sitzung = sitzung_fuer(client, werte)
    if sitzung.grund in ("software", "fremd"):
        return None
    ziel = f"{sitzung.host}:{sitzung.port}"
    if sitzung.aktiv:
        text = (
            f"libbitcoin-Abfrage {ziel}: Adressindex an — "
            "Bestand und Herkunft darüber."
        )
    elif sitzung.grund == "index":
        text = f"libbitcoin-Abfrage {ziel}: kein Adressindex — Electrum bleibt."
    else:
        ports = getattr(sitzung, "ports", ())
        if len(ports) > 1:
            namen = " und ".join(str(port) for port in ports)
            ziel = f"{sitzung.host} auf {namen}"
        text = f"libbitcoin-Abfrage {ziel}: nicht erreichbar — Electrum bleibt."
    if log is not None:
        log(text)
        if _diagnose_an():
            log("libbitcoin-Diagnose: logs/libbitcoin-native.log")
    return text


def sitzung_fuer(client, werte: dict[str, str] | None = None) -> NativeSitzung:
    """Legt die Sitzung einmal am Client ab. Wiederholte Aufrufe prüfen nicht neu."""
    vorhanden = getattr(client, "_libbitcoin_native", None)
    melde = getattr(client, "_libbitcoin_log", None)
    if isinstance(vorhanden, NativeSitzung):
        if melde is not None:
            vorhanden.log = melde
        return vorhanden
    host = normalize_host(getattr(client, "host", "") or "")
    timeout = getattr(client, "timeout", None) or 8
    try:
        timeout_f = float(timeout)
    except (TypeError, ValueError):
        timeout_f = 8.0
    proxy = getattr(client, "tor_proxy", None)
    if proxy is not None and not (
        isinstance(proxy, tuple) and len(proxy) == 2
    ):
        proxy = None
    geladen = _werte_fuer(client, werte)
    ports = _ports_aus(geladen)
    software = str(getattr(client, "server_software", "") or "")
    if software != "libbitcoin" or host not in _eigene_hosts(geladen):
        sitzung = NativeSitzung(host, ports[0], timeout_f, proxy)
        sitzung.ports = ports
        sitzung.aktiv = False
        sitzung.grund = "software" if software != "libbitcoin" else "fremd"
        sitzung.log = melde
        client._libbitcoin_native = sitzung
        return sitzung
    sitzung = _waehle_port(host, ports, timeout_f, proxy)
    sitzung.log = melde
    client._libbitcoin_native = sitzung
    return sitzung


def _waehle_port(
    host: str,
    ports: tuple[int, ...],
    timeout: float,
    tor_proxy: tuple[str, int] | None,
) -> NativeSitzung:
    """Erster Port, dessen ``/v1/configuration`` von libbitcoin stammt.

    Antwortet einer der Kandidaten, gilt er bis zum Prozessende. Der andere
    wird nicht mehr verbunden, egal ob 8181 oder 8180 der stille Port war.
    """
    ursprung = ports
    ports = _enge_ports(host, ports)
    letzte: NativeSitzung | None = None
    mehrere = len(ports) > 1
    for port in ports:
        sitzung = NativeSitzung(host, port, timeout, tor_proxy)
        sitzung.ports = ports
        try:
            daten = sitzung._holen("configuration", datenformat="json")
        except NativeFehler as exc:
            sitzung._diagnose(f"konfiguration port={port} fehler={exc}")
            letzte = sitzung
            continue
        if mehrere and not _libbitcoin_antwortet(daten):
            sitzung._diagnose(
                f"konfiguration port={port} feld={_address_lage(daten)} "
                f"form={_form(daten)} antwort=fremd"
            )
            letzte = sitzung
            continue
        sitzung.aktiv = _address_index_an(daten)
        sitzung.grund = "" if sitzung.aktiv else "index"
        sitzung._diagnose(
            f"konfiguration port={port} feld={_address_lage(daten)} "
            f"form={_form(daten)} index={'an' if sitzung.aktiv else 'aus'}"
        )
        _merke_antwort_port(host, ursprung, port)
        return sitzung
    sitzung = letzte or NativeSitzung(host, ports[0], timeout, tor_proxy)
    sitzung.ports = ports
    sitzung.aktiv = False
    sitzung.grund = "probe"
    sitzung._diagnose(f"konfiguration ports={','.join(str(p) for p in ports)} kein-treffer")
    return sitzung


def luecke_benutzt(client, address: str, werte: dict[str, str] | None = None) -> bool | None:
    with _sperre(client):
        return sitzung_fuer(client, werte).benutzt(address)


def hole_native_utxos(client, address: str, werte: dict[str, str] | None = None) -> list[dict] | None:
    with _sperre(client):
        return sitzung_fuer(client, werte).utxos(address)


def merke_hash_aus_listunspent(
    client,
    address: str,
    entries: list,
    werte: dict[str, str] | None = None,
) -> None:
    with _sperre(client):
        sitzung = getattr(client, "_libbitcoin_native", None)
        if not isinstance(sitzung, NativeSitzung):
            sitzung = sitzung_fuer(client, werte)
        sitzung.merke_hash(address, entries)


def versuche_tx(client, txid: str, werte: dict[str, str] | None = None) -> dict | None:
    with _sperre(client):
        return sitzung_fuer(client, werte).transaktion(txid)


def haenge_prevout_duenn_an(get_tx, client, werte: dict[str, str] | None = None) -> None:
    sitzung = sitzung_fuer(client, werte)
    if not sitzung.aktiv:
        return

    def prevout_duenn(txid: str, vout: int) -> dict | None:
        with _sperre(client):
            return sitzung.prevout(txid, vout)

    get_tx.prevout_duenn = prevout_duenn


# ``threading.Lock`` und ``RLock`` sind Factory-Funktionen, keine Klassen:
# ``isinstance(x, threading.Lock)`` wirft immer TypeError, gleich was x ist.
# Die echten Typen stehen deshalb einmal hier.
_LOCK_TYPEN = (type(threading.Lock()), type(threading.RLock()))


def _sperre(client):
    sperre = getattr(client, "_lock", None)
    if isinstance(sperre, _LOCK_TYPEN):
        return sperre
    sperre = getattr(client, "_libbitcoin_native_lock", None)
    if not isinstance(sperre, _LOCK_TYPEN):
        sperre = threading.Lock()
        try:
            client._libbitcoin_native_lock = sperre
        except Exception:
            pass
    return sperre
