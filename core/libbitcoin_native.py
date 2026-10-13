"""Libbitcoin-Abfrage auf dem eigenen Indexer.

Nur wenn der Electrum-Handshake dieses Sockets ``libbitcoin`` sagt und der
Host ``FULCRUM_HOST`` oder ``FULCRUM_TOR`` ist. Öffentliche Server bleiben
beim Electrum-Protokoll. Ein fehlender Adressindex oder eine abweichende
Skript-Hash-Reihenfolge schaltet die Sitzung auf Electrum zurück.

Erlaubte Pfade: ``configuration``, ``address/<hash>`` (+ ``/confirmed``,
``/unconfirmed``), ``output/<txid>/<index>``, ``tx/<txid>`` als
``format=data``, ``tx/<txid>/header``. Kein Core-RPC, keine Weiterleitung.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
from typing import Any

from core.fulcrum_client import address_to_scripthash
from core.outbound_policy import ensure_resolves_to_allowed_host, normalize_host

_STANDARD_PORT = 8181
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
    ) -> None:
        super().__init__(text)
        self.index_aus = index_aus
        self.unbrauchbar = unbrauchbar


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


def _port_aus(werte: dict[str, str]) -> int:
    roh = str(werte.get("LIBBITCOIN_NATIVE_PORT") or os.environ.get("LIBBITCOIN_NATIVE_PORT") or "")
    roh = roh.strip()
    if not roh:
        return _STANDARD_PORT
    try:
        port = int(roh)
    except ValueError:
        return _STANDARD_PORT
    if 1 <= port <= 65535:
        return port
    return _STANDARD_PORT


def _eigene_hosts(werte: dict[str, str]) -> set[str]:
    hosts: set[str] = set()
    for schluessel in ("FULCRUM_HOST", "FULCRUM_TOR"):
        name = _host_aus_env(werte.get(schluessel, ""))
        if name:
            hosts.add(name)
    return hosts


def _address_index_an(daten: Any) -> bool:
    if not isinstance(daten, dict):
        return False
    flag = daten.get("address")
    if flag is True:
        return True
    if isinstance(flag, str) and flag.strip().lower() == "true":
        return True
    return False


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
            raise NativeFehler("Verbindung zu")
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
        self._lock = threading.Lock()
        self._karte_fertig = False
        self._bekannt: dict[tuple[str, int], dict] = {}

    def nutzbar(self) -> bool:
        return self.aktiv and not self.unterdrueckt

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
        try:
            status, body = self._anfrage(pfad, datenformat=datenformat)
        except NativeFehler:
            raise
        except OSError as exc:
            raise NativeFehler("Netz") from exc
        if status == 404:
            return _LEER
        unbestaetigt = pfad.endswith("/unconfirmed")
        if status == 501 and unbestaetigt:
            return _LEER
        if status == 501:
            raise NativeFehler("Index", index_aus=True)
        if status != 200:
            raise NativeFehler(f"HTTP {status}")
        if datenformat == "data":
            return body
        return _json_bytes(body)

    def _index_aus(self, exc: NativeFehler) -> None:
        if exc.index_aus:
            self.aktiv = False
            self.grund = "index"

    def benutzt(self, address: str) -> bool | None:
        """None: diese Abfrage bleibt bei Electrum. Sonst 404/200 der Adresse."""
        if not self.nutzbar() or not self.hash_bestaetigt:
            return None
        try:
            daten = self._holen(f"address/{self._hash(address)}", datenformat="json")
        except NativeFehler as exc:
            self._index_aus(exc)
            return None
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
                if exc.unbrauchbar:
                    self.aktiv = False
                    self.grund = "antwort"
                return
            menge = {(txid, vout) for txid, vout, _wert in punkte}
            if menge == erwartet:
                self.hash_intern = intern
                self.hash_bestaetigt = True
                return
        self.aktiv = False
        self.grund = "hash"

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
            return None
        try:
            bestaetigt = self._punkte(address, "confirmed")
            offen = self._punkte(address, "unconfirmed")
        except NativeFehler as exc:
            self._index_aus(exc)
            return None
        except (TypeError, ValueError):
            return None
        koepfe: dict[str, tuple[int | None, int | None] | None] = {}
        ergebnis: list[dict] = []
        gesehen: set[tuple[str, int]] = set()
        bestaetigt_keys = {(txid, vout) for txid, vout, _wert in bestaetigt}
        try:
            for txid, vout, wert in [*bestaetigt, *offen]:
                if (txid, vout) in gesehen:
                    continue
                gesehen.add((txid, vout))
                bekannt = self._cache_karte().get((txid, vout))
                if bekannt is not None:
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
            return None
        except (TypeError, ValueError):
            return None
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
        try:
            daten = self._holen(f"output/{txid}/{vout}", datenformat="json")
            if daten is _LEER or not isinstance(daten, dict):
                return None
            wert = int(daten["value"])
            skript = skript_aus_nativ(daten.get("script"))
            kopf = self._kopf(txid)
        except NativeFehler as exc:
            self._index_aus(exc)
            return None
        except (TypeError, ValueError, KeyError):
            return None
        if skript is None or kopf is None:
            return None
        hoehe, zeit = kopf
        if zeit is None or hoehe is None or hoehe <= 0:
            return None
        try:
            from embit.script import Script

            from core.derivation import script_address

            adresse = script_address(Script(skript))
        except Exception:
            return None
        if not adresse:
            return None
        return {
            "value": wert,
            "scriptpubkey": skript.hex(),
            "scriptpubkey_address": adresse,
            "_prev_tx_time_ts": int(zeit),
        }

    def transaktion(self, txid: str) -> dict | None:
        if not self.nutzbar():
            return None
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(txid or "")):
            return None
        txid = str(txid).lower()
        try:
            roh = self._holen(f"tx/{txid}", datenformat="data")
            if roh is _LEER or not isinstance(roh, (bytes, bytearray)):
                return None
            from core.fulcrum_history import _normalize_electrum_tx, _parse_tx_hex

            tx = _normalize_electrum_tx(_parse_tx_hex(_tx_hex(bytes(roh)), expected_txid=txid))
            kopf = self._kopf(txid)
        except NativeFehler as exc:
            self._index_aus(exc)
            return None
        except (TypeError, ValueError, RuntimeError):
            return None
        if kopf is None:
            tx["confirmations"] = 0
            tx["status"] = {"confirmed": False}
            return tx
        hoehe, zeit = kopf
        if hoehe is None or zeit is None or hoehe <= 0:
            return None
        tx["blockheight"] = hoehe
        tx["blocktime"] = int(zeit)
        tx["confirmations"] = max(int(tx.get("confirmations") or 0), 1)
        tx["status"] = {
            "confirmed": True,
            "block_height": hoehe,
            "block_time": int(zeit),
        }
        return tx


def sitzung_fuer(client, werte: dict[str, str] | None = None) -> NativeSitzung:
    """Legt die Sitzung einmal am Client ab. Wiederholte Aufrufe prüfen nicht neu."""
    if werte is None:
        # Tests setzen das, damit nicht die .env des Rechners die Probe auslöst.
        gesetzt = getattr(client, "_libbitcoin_werte", None)
        if isinstance(gesetzt, dict):
            werte = gesetzt
    vorhanden = getattr(client, "_libbitcoin_native", None)
    if isinstance(vorhanden, NativeSitzung):
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
    geladen = _werte_lesen(werte)
    sitzung = NativeSitzung(host, _port_aus(geladen), timeout_f, proxy)
    software = str(getattr(client, "server_software", "") or "")
    if software != "libbitcoin" or host not in _eigene_hosts(geladen):
        sitzung.aktiv = False
        sitzung.grund = "software" if software != "libbitcoin" else "fremd"
        client._libbitcoin_native = sitzung
        return sitzung
    try:
        daten = sitzung._holen("configuration", datenformat="json")
    except NativeFehler:
        sitzung.aktiv = False
        sitzung.grund = "probe"
        client._libbitcoin_native = sitzung
        return sitzung
    if not _address_index_an(daten):
        sitzung.aktiv = False
        sitzung.grund = "index"
        client._libbitcoin_native = sitzung
        return sitzung
    sitzung.aktiv = True
    client._libbitcoin_native = sitzung
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


def _sperre(client):
    sperre = getattr(client, "_lock", None)
    if isinstance(sperre, threading.Lock):
        return sperre
    sperre = getattr(client, "_libbitcoin_native_lock", None)
    if not isinstance(sperre, threading.Lock):
        sperre = threading.Lock()
        try:
            client._libbitcoin_native_lock = sperre
        except Exception:
            pass
    return sperre
