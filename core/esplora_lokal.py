"""Lokales Esplora für Bestand und kleine Herkunft.

Nur wenn der verbundene Electrum-Server kein libbitcoin ist und
``MEMPOOL_URL`` auf eine Instanz im eigenen Netz zeigt. Öffentliche
Explorer und Onion-Adressen bleiben außen. Die Adresslücke bleibt
beim Electrum-Protokoll.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

_MAX_TX = 256 * 1024
_MAX_UTXO = 2 * 1024 * 1024
_MAX_STATUS = 16 * 1024

_sperre = threading.Lock()
_zustand: dict[str, object] = {"url": None, "sitzung": None}


class _PfadFehlt(Exception):
    pass


class _ZuGross(Exception):
    pass


class _Netz(Exception):
    pass


@dataclass
class EsploraSitzung:
    aktiv: bool = False
    utxo_an: bool = False
    herkunft_an: bool = False
    praefix: str = ""
    grund: str = ""
    anfragen: int = 0
    antwort_bytes: int = 0
    zeiten: dict[str, int] = field(default_factory=dict)


def zuruecksetzen() -> None:
    """Leert die Prozess-Sitzung. Nur für Tests."""
    with _sperre:
        _zustand["url"] = None
        _zustand["sitzung"] = None


def sitzung_fuer(client=None, werte: dict[str, str] | None = None) -> EsploraSitzung:
    if _ist_libbitcoin(client):
        return EsploraSitzung(grund="libbitcoin")
    url = _roh_url(client, werte)
    with _sperre:
        if _zustand["sitzung"] is not None and _zustand["url"] == url:
            sitzung = _zustand["sitzung"]
            if isinstance(sitzung, EsploraSitzung):
                return sitzung
    neu = _baue(url)
    with _sperre:
        vorhanden = _zustand["sitzung"]
        if isinstance(vorhanden, EsploraSitzung) and _zustand["url"] == url:
            return vorhanden
        _zustand["url"] = url
        _zustand["sitzung"] = neu
        return neu


def hole_utxos(client, address: str, werte: dict[str, str] | None = None) -> list[dict] | None:
    """UTXOs einer Adresse. ``None`` heißt: Electrum macht diesen Abruf."""
    if _ist_libbitcoin(client):
        return None
    sitzung = sitzung_fuer(client, werte)
    if not sitzung.aktiv or not sitzung.utxo_an:
        return None
    try:
        roh = _get(
            sitzung,
            f"address/{quote(str(address), safe='')}/utxo",
            _MAX_UTXO,
            timeout=4,
        )
    except _PfadFehlt:
        sitzung.utxo_an = False
        sitzung.grund = "pfad"
        return None
    except _Netz as exc:
        # Ein stiller Adressindex antwortet gar nicht. Einmal warten reicht.
        if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            sitzung.utxo_an = False
            sitzung.grund = "zeit"
        return None
    except (_ZuGross, ValueError):
        return None
    try:
        daten = json.loads(roh.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        sitzung.utxo_an = False
        sitzung.grund = "form"
        return None
    if not isinstance(daten, list):
        sitzung.utxo_an = False
        sitzung.grund = "form"
        return None
    try:
        return [_utxo(eintrag) for eintrag in daten]
    except (TypeError, ValueError, KeyError):
        sitzung.utxo_an = False
        sitzung.grund = "form"
        return None


def hole_tx(client, txid: str, werte: dict[str, str] | None = None) -> dict | None:
    """Kleine Tx mit Prevouts. ``None`` fällt auf den Electrum-Abruf zurück."""
    if _ist_libbitcoin(client):
        return None
    sitzung = sitzung_fuer(client, werte)
    if not sitzung.aktiv or not sitzung.herkunft_an:
        return None
    ziel = str(txid or "").strip().lower()
    if len(ziel) != 64 or any(c not in "0123456789abcdef" for c in ziel):
        return None
    try:
        roh = _get(sitzung, f"tx/{ziel}", _MAX_TX)
    except _PfadFehlt:
        # Eine unbekannte Tx antwortet genauso. Der Pfad bleibt an.
        return None
    except _ZuGross:
        return None
    except (_Netz, ValueError):
        return None
    try:
        daten = json.loads(roh.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        sitzung.herkunft_an = False
        sitzung.grund = "form"
        return None
    if not isinstance(daten, dict) or not daten.get("txid"):
        sitzung.herkunft_an = False
        sitzung.grund = "form"
        return None
    if not _prevouts_brauchbar(daten):
        sitzung.herkunft_an = False
        sitzung.grund = "prevout"
        return None
    if _bestaetigt_ohne_zeit(daten):
        return None
    return daten


def haenge_vorgaengerzeit_an(get_tx, client, werte: dict[str, str] | None = None) -> None:
    """Blockzeit eines Vorgängers über ``/tx/:id/status``, ohne die volle Tx."""
    if _ist_libbitcoin(client):
        return
    sitzung = sitzung_fuer(client, werte)
    if not sitzung.aktiv:
        return

    def vorgaengerzeit(txid: str) -> int | None:
        if not sitzung.aktiv or not sitzung.herkunft_an:
            return None
        ziel = str(txid or "").strip().lower()
        if len(ziel) != 64:
            return None
        with _sperre:
            if ziel in sitzung.zeiten:
                return sitzung.zeiten[ziel]
        try:
            roh = _get(sitzung, f"tx/{ziel}/status", _MAX_STATUS)
        except (_PfadFehlt, _ZuGross, _Netz, ValueError):
            return None
        try:
            daten = json.loads(roh.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(daten, dict) or not daten.get("confirmed"):
            return None
        zeit = daten.get("block_time")
        try:
            wert = int(zeit)
        except (TypeError, ValueError):
            return None
        if wert <= 0:
            return None
        with _sperre:
            sitzung.zeiten[ziel] = wert
        return wert

    get_tx.vorgaengerzeit = vorgaengerzeit


def utxo_fuer_tor_batch(client, werte: dict[str, str] | None = None) -> bool:
    """LAN-Esplora statt Onion-Batch, sobald der UTXO-Pfad an ist."""
    if _ist_libbitcoin(client):
        return False
    sitzung = sitzung_fuer(client, werte)
    return bool(sitzung.aktiv and sitzung.utxo_an)


def _ist_libbitcoin(client) -> bool:
    return str(getattr(client, "server_software", "") or "") == "libbitcoin"


def _roh_url(client, werte: dict[str, str] | None) -> str:
    if werte is None:
        eigen = getattr(client, "_esplora_werte", None)
        if isinstance(eigen, dict):
            werte = eigen
    if werte is None:
        if not _echter_client(client):
            return ""
        from core.env_bootstrap import _load_dotenv

        werte = _load_dotenv()
    return str((werte or {}).get("MEMPOOL_URL") or "")


def _echter_client(client) -> bool:
    from core.fulcrum_client import FulcrumClient, RotatingFulcrumPool

    return isinstance(client, (FulcrumClient, RotatingFulcrumPool))


def _baue(roh: str) -> EsploraSitzung:
    from core.config import mempool_info

    info = mempool_info(roh)
    sitzung = EsploraSitzung()
    if not info.get("configured"):
        sitzung.grund = "keine"
        return sitzung
    host = str(urlparse(str(info.get("url") or "")).hostname or "")
    if host.endswith(".onion"):
        sitzung.grund = "onion"
        return sitzung
    if not info.get("local") or info.get("stufe") != "lokal":
        sitzung.grund = "fremd"
        return sitzung
    praefix = _tip_praefix(str(info["url"]), sitzung)
    if not praefix:
        sitzung.grund = sitzung.grund or "probe"
        return sitzung
    sitzung.aktiv = True
    sitzung.utxo_an = True
    sitzung.herkunft_an = True
    sitzung.praefix = praefix
    sitzung.grund = ""
    return sitzung


def _praefixe(basis: str) -> list[str]:
    """Esplora-REST liegt unter ``/api``, nicht unter ``/api/v1``."""
    text = str(basis or "").rstrip("/")
    if not text:
        return []
    if text.endswith("/api/v1"):
        return [text[: -len("/v1")], text]
    if text.endswith("/api"):
        return [text, f"{text}/v1"]
    return [f"{text}/api", text, f"{text}/api/v1"]


def _tip_praefix(url: str, sitzung: EsploraSitzung) -> str:
    from core.config import normalize_mempool_url

    try:
        basis = normalize_mempool_url(url)
    except ValueError:
        return ""
    for praefix in _praefixe(basis):
        try:
            roh = _get(sitzung, "blocks/tip/height", 64, praefix=praefix)
        except (_PfadFehlt, _ZuGross, _Netz, ValueError):
            continue
        text = roh.decode("utf-8", errors="replace").strip().strip('"')
        if text.isdigit():
            return praefix
    return ""


def _get(
    sitzung: EsploraSitzung,
    rel: str,
    max_body: int,
    *,
    praefix: str = "",
    timeout: float = 8,
) -> bytes:
    from core.outbound_policy import OutboundPolicyError, ensure_url_allowed, tls_context

    wurzel = praefix or sitzung.praefix
    ziel = f"{wurzel}/{rel.lstrip('/')}"
    try:
        erlaubt = ensure_url_allowed(ziel, service="mempool")
    except OutboundPolicyError as exc:
        raise _Netz(str(exc)) from exc
    host = urlparse(erlaubt).hostname or ""
    handler: list = [_OhneWeiterleitung()]
    if erlaubt.startswith("https"):
        handler.append(urllib.request.HTTPSHandler(context=tls_context(host=host)))
    opener = urllib.request.build_opener(*handler)
    anfrage = urllib.request.Request(
        erlaubt,
        headers={"User-Agent": "SatSage", "Accept": "application/json, text/plain, */*"},
    )
    with _sperre:
        sitzung.anfragen += 1
    try:
        antwort = opener.open(anfrage, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            exc.close()
        except Exception:
            pass
        if exc.code == 404:
            raise _PfadFehlt()
        raise _Netz(f"HTTP {exc.code}")
    except Exception as exc:
        raise _Netz(str(exc) or type(exc).__name__) from exc
    try:
        laenge = antwort.headers.get("Content-Length")
        if laenge is not None and int(laenge) > max_body:
            raise _ZuGross()
        teile: list[bytes] = []
        bisher = 0
        while True:
            block = antwort.read(65536)
            if not block:
                break
            bisher += len(block)
            if bisher > max_body:
                raise _ZuGross()
            teile.append(block)
        roh = b"".join(teile)
    finally:
        antwort.close()
    with _sperre:
        sitzung.antwort_bytes += len(roh)
    return roh


class _OhneWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise _Netz("weiterleitung")


def _utxo(eintrag: dict) -> dict:
    if not isinstance(eintrag, dict):
        raise TypeError("kein Objekt")
    txid = str(eintrag["txid"])
    vout = int(eintrag["vout"])
    wert = int(eintrag["value"])
    status = eintrag.get("status") if isinstance(eintrag.get("status"), dict) else {}
    bestaetigt = bool(status.get("confirmed"))
    aus: dict[str, object] = {"confirmed": bestaetigt}
    if bestaetigt:
        hoehe = status.get("block_height")
        zeit = status.get("block_time")
        if hoehe is None or zeit is None:
            raise ValueError("blockzeit fehlt")
        hoehe_i = int(hoehe)
        zeit_i = int(zeit)
        if hoehe_i <= 0 or zeit_i <= 0:
            raise ValueError("blockzeit fehlt")
        aus["block_height"] = hoehe_i
        aus["block_time"] = zeit_i
    return {"txid": txid, "vout": vout, "value": wert, "status": aus}


def _prevouts_brauchbar(tx: dict) -> bool:
    eingaenge = [v for v in (tx.get("vin") or []) if isinstance(v, dict)]
    fremd = [v for v in eingaenge if not v.get("is_coinbase")]
    if not fremd:
        return True
    return any(_prevout_traegt(v.get("prevout")) for v in fremd)


def _prevout_traegt(prev) -> bool:
    if not isinstance(prev, dict) or "value" not in prev:
        return False
    return bool(prev.get("scriptpubkey_address") or prev.get("scriptpubkey"))


def _bestaetigt_ohne_zeit(tx: dict) -> bool:
    status = tx.get("status") if isinstance(tx.get("status"), dict) else {}
    if not status.get("confirmed"):
        return False
    try:
        return int(status.get("block_time") or 0) <= 0
    except (TypeError, ValueError):
        return True
