"""
XPUB-/UTXO-/Verlauf-/Ingress-Caches und Immutable-Flatfile-Helfer.

Aus main.py ausgelagert (Slice 3 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.

Sync-/Scan-Engines, Chain-Fetcher und WalletContext bleiben woanders.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.derivation import (
    DEFAULT_MAX_ADDRESSES,
    _CHAIN_NETWORK,
    derive_addresses,
    derive_descriptor_addresses,
    ist_deskriptor,
)
from core.paths import app_dir

# Python 3.10-kompatibel (datetime.UTC erst ab 3.11)
UTC = timezone.utc


def _sync_main_cache_scalars() -> None:
    """Hält main.* Skalare nach Rebind auf demselben Stand (Tests/Fassade)."""
    import sys

    main_mod = sys.modules.get("main")
    if main_mod is None:
        return
    for name in (
        "_cache_disk_warned",
        "_cache_disk_blocked",
        "_sqlite_flatfile_hint_emitted",
        "_P2P_HEADER_CHAIN_CACHE",
    ):
        if hasattr(main_mod, name):
            setattr(main_mod, name, globals()[name])

UTXO_CACHE_DIR = app_dir() / "utxo_cache"
IMMUTABLE_CACHE_DIR = app_dir() / "immutable_cache"
MIN_FREE_DISK_RATIO = 0.05
#: Absolute Untergrenze: große Platten haben bei 4 % oft noch Dutzende GiB frei.
#: Dann blockiert die reine Prozent-Schwelle unnötig den UTXO-Cache.
MIN_FREE_DISK_BYTES = 2 * 1024 ** 3
_cache_disk_warned = False
_cache_disk_blocked = False
_cache_disk_lock = threading.Lock()

class CacheDiskFullError(OSError):
    """Cache-Schreibvorgang abgelehnt — zu wenig freier Speicher."""
TX_IMMUTABLE_CACHE_SUBDIR = "tx"
BLOCK_HEADER_CACHE_SUBDIR = "block_header"
UTXO_INGRESS_CACHE_SUBDIR = "utxo_ingress"
BITCOIN_GENESIS_TIMESTAMP = 1231006505  # 2009-01-03 18:15:05 UTC
BITCOIN_BLOCK_INTERVAL_SECONDS = 600  # Ziel: 10 Minuten pro Block
SALDEN_CHECK_LOOKAHEAD = 5

_immutable_tx_memory: dict[str, dict] = {}
_immutable_tx_lock = threading.Lock()
# SQLite-Hinweis für tx/ / utxo_ingress/ — siehe ISSUES.md (nach CoinJoin-Verfolgung).
_SQLITE_FLATFILE_HINT_THRESHOLD = 10_000
_SQLITE_FLATFILE_RECOUNT_EVERY = 500
_sqlite_flatfile_hint_emitted = False
_sqlite_flatfile_save_ticks: dict[str, int] = {}
_sqlite_flatfile_last_count: dict[str, int] = {}

def _maybe_log_sqlite_flatfile_hint(subdir: Path, *, kind: str) -> None:
    """Einmaliger Log-Hinweis, wenn Winz-JSON-Caches die SQLite-Schwelle erreichen."""
    global _sqlite_flatfile_hint_emitted
    if _sqlite_flatfile_hint_emitted:
        return
    key = str(subdir.resolve()) if subdir.exists() else str(subdir)
    ticks = _sqlite_flatfile_save_ticks.get(key, 0) + 1
    _sqlite_flatfile_save_ticks[key] = ticks
    # Nicht bei jedem Write den Ordner zählen — nur beim ersten Write und periodisch.
    if ticks != 1 and ticks % _SQLITE_FLATFILE_RECOUNT_EVERY != 0:
        n = _sqlite_flatfile_last_count.get(key, 0)
    else:
        try:
            n = sum(1 for p in subdir.iterdir() if p.suffix == ".json")
        except OSError:
            return
        _sqlite_flatfile_last_count[key] = n
    if n < _SQLITE_FLATFILE_HINT_THRESHOLD:
        return
    _sqlite_flatfile_hint_emitted = True
    _sync_main_cache_scalars()
    print(
        f"Cache wächst — sqlite ab jetzt sinnvoll "
        f"({kind}: {n:,} Dateien unter {subdir}). "
        f"Falls das stört: GitHub-Issue an SatSage — wir prüfen die Schwelle.",
        flush=True,
    )

#: Cache-Kennung pro Deskriptor-Text (erste Adresse → Hash), damit
#: umsortierte Cosigner denselben Cache behalten.
_deskriptor_kennungen: dict[str, str] = {}
def _dump_cache_json(payload: dict | list) -> str:
    """Kompaktes JSON für Flatfile-Caches (ohne indent)."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

def _cache_disk_target(path: Path) -> Path:
    target = Path(path).resolve()
    if target.is_file():
        target = target.parent
    return target

def cache_disk_write_allowed(cache_path: Path | str) -> bool:
    """
    Prüft freien Plattenplatz am Cache-Ziel.

    Blockiert, wenn **beides** gilt: unter MIN_FREE_DISK_RATIO (5 %) **und**
    unter MIN_FREE_DISK_BYTES (2 GiB). Große Platten mit z. B. 18 GiB frei
    bei 4 % bleiben schreibbar — sonst landet ein UTXO-Scan als „15 gefunden“
    ohne „Cache vom …“ in der Oberfläche.
    """
    global _cache_disk_warned, _cache_disk_blocked
    with _cache_disk_lock:
        try:
            target = _cache_disk_target(Path(cache_path))
            usage = shutil.disk_usage(target)
        except OSError:
            return True
        if usage.total <= 0:
            return True
        ratio = usage.free / usage.total
        if ratio >= MIN_FREE_DISK_RATIO or usage.free >= MIN_FREE_DISK_BYTES:
            _cache_disk_blocked = False
            _sync_main_cache_scalars()
            return True
        if not _cache_disk_warned:
            free_gib = usage.free / (1024 ** 3)
            total_gib = usage.total / (1024 ** 3)
            min_gib = MIN_FREE_DISK_BYTES / (1024 ** 3)
            location = target.drive if target.drive else str(target.anchor)
            print(
                f"\n⚠️  Wenig Speicherplatz ({location}): "
                f"noch {free_gib:.2f} GiB frei "
                f"({ratio * 100:.1f} % von {total_gib:.1f} GiB). "
                f"Cache-Aufbau wird gestoppt "
                f"(Schwelle: unter {MIN_FREE_DISK_RATIO * 100:.0f} % frei "
                f"und unter {min_gib:.0f} GiB).\n",
                flush=True,
            )
            _cache_disk_warned = True
            _sync_main_cache_scalars()
        _cache_disk_blocked = True
        _sync_main_cache_scalars()
        return False

def is_cache_disk_write_blocked() -> bool:
    """True, wenn Cache-Schreibvorgänge wegen wenig Plattenplatz pausiert sind."""
    return _cache_disk_blocked

def _cache_disk_full_meldung(cache_path: Path | str | None = None) -> str:
    """Nutzertext, wenn ein Scan-Ergebnis nicht auf die Platte passt."""
    free_txt = ""
    try:
        ziel = _cache_disk_target(Path(cache_path or UTXO_CACHE_DIR))
        usage = shutil.disk_usage(ziel)
        free_txt = (
            f" Noch {usage.free / (1024 ** 3):.1f} GiB frei "
            f"({100.0 * usage.free / usage.total:.1f} %)."
            if usage.total > 0
            else ""
        )
    except OSError:
        pass
    return (
        "UTXO-Cache nicht speicherbar: zu wenig freier Speicherplatz."
        f"{free_txt} "
        "Bitte Speicher freimachen und den Scan wiederholen — "
        "sonst bleiben die gefundenen UTXOs unsichtbar."
    )

def resolve_immutable_cache_dir(args=None, utxo_cache_dir: Path | str | None = None) -> Path:
    """Verzeichnis für unveränderliche Flatfile-Caches (Tx, …)."""
    if args is not None:
        custom = getattr(args, "immutable_cache_dir", None)
        if custom:
            return Path(custom)
        if getattr(args, "cache_dir", None):
            return Path(args.cache_dir).resolve().parent / "immutable_cache"
    if utxo_cache_dir:
        return Path(utxo_cache_dir).resolve().parent / "immutable_cache"
    return IMMUTABLE_CACHE_DIR

def _normalize_txid(txid: str) -> str:
    value = txid.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"ungültige TxID: {txid!r}")
    return value

def _immutable_tx_cache_path(txid: str, cache_root: Path) -> Path:
    return cache_root / TX_IMMUTABLE_CACHE_SUBDIR / f"{_normalize_txid(txid)}.json"

def load_cached_tx(txid: str, cache_root: Path | None = None) -> dict | None:
    """Lädt eine gecachte Transaktion (RAM → Flatfile)."""
    key = _normalize_txid(txid)
    with _immutable_tx_lock:
        cached = _immutable_tx_memory.get(key)
        if cached is not None:
            return cached

    root = cache_root or IMMUTABLE_CACHE_DIR
    path = _immutable_tx_cache_path(key, root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if str(data.get("txid", "")).lower() != key:
        return None
    tx = data.get("tx")
    if not isinstance(tx, dict):
        return None
    with _immutable_tx_lock:
        _immutable_tx_memory[key] = tx
    return tx

def save_cached_tx(
    txid: str,
    tx: dict,
    cache_root: Path,
    source: str,
) -> Path:
    """Speichert eine Transaktion als JSON-Flatfile."""
    key = _normalize_txid(txid)
    root = Path(cache_root)
    path = _immutable_tx_cache_path(key, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "txid": key,
        "cached_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "tx": tx,
    }
    if not cache_disk_write_allowed(root):
        with _immutable_tx_lock:
            _immutable_tx_memory[key] = tx
        return path
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(_dump_cache_json(payload), encoding="utf-8")
    tmp.replace(path)
    with _immutable_tx_lock:
        _immutable_tx_memory[key] = tx
    _maybe_log_sqlite_flatfile_hint(path.parent, kind="tx")
    return path

def _block_header_network_tag() -> str:
    """Unterscheidet Mainnet/Regtest — Höhe 130 ist nicht dieselbe Chain."""
    if _CHAIN_NETWORK is None:
        return "main"
    name = str(_CHAIN_NETWORK.get("name") or "main").strip().lower()
    if "regtest" in name:
        return "regtest"
    if "signet" in name:
        return "signet"
    if "test" in name:
        return "test"
    return "main"

def _block_header_cache_path(height: int, cache_root: Path) -> Path:
    # Netzwerk im Dateinamen: Mainnet-Cache darf Regtest-Höhen nicht vergiften.
    return (
        cache_root
        / BLOCK_HEADER_CACHE_SUBDIR
        / f"{_block_header_network_tag()}-{int(height)}.json"
    )

def load_cached_block_time(height: int, cache_root: Path | None = None) -> int | None:
    """Blockzeit (Unix) für eine Höhe — unveränderlich nach Bestätigung."""
    if height <= 0:
        return None
    root = cache_root or IMMUTABLE_CACHE_DIR
    path = _block_header_cache_path(height, root)
    if not path.is_file():
        # Legacy: höhen-only (Mainnet-Ära) — nur ohne aktives Alt-Netz lesen.
        legacy = root / BLOCK_HEADER_CACHE_SUBDIR / f"{int(height)}.json"
        if _block_header_network_tag() == "main" and legacy.is_file():
            path = legacy
        else:
            return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if int(data.get("height", -1)) != int(height):
        return None
    block_time = data.get("block_time")
    return int(block_time) if block_time is not None else None

def save_cached_block_time(
    height: int,
    block_time: int,
    cache_root: Path,
    source: str,
) -> Path:
    root = Path(cache_root)
    path = _block_header_cache_path(height, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "height": int(height),
        "block_time": int(block_time),
        "network": _block_header_network_tag(),
        "cached_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
    }
    try:
        from core import price as price_mod

        price_mod.reichere_fiat_an(
            payload,
            time_ts=int(block_time),
            value_sats=None,
            immutable_cache_dir=root,
            prefix="",
        )
    except Exception:
        pass
    if not cache_disk_write_allowed(root):
        return path
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(_dump_cache_json(payload), encoding="utf-8")
    tmp.replace(path)
    return path

#: (Pfad, mtime_ns, HeaderChain) — Header-Datei nicht je Höhe neu laden.
_P2P_HEADER_CHAIN_CACHE: tuple[str, int, object] | None = None

def _p2p_header_chain(immutable_cache_dir: Path | None):
    """Header-Kette aus ``p2p_headers.bin``, mit Prozess-Cache."""
    global _P2P_HEADER_CHAIN_CACHE
    from core.p2p import HeaderChain, SEGWIT_HEIGHT, p2p_headers_path

    path = p2p_headers_path(immutable_cache_dir)
    if not path.is_file():
        return None
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    key = str(path.resolve())
    geladen = _P2P_HEADER_CHAIN_CACHE
    if geladen and geladen[0] == key and geladen[1] == mtime:
        return geladen[2]
    try:
        chain = HeaderChain(path, start_height=SEGWIT_HEIGHT)
    except Exception:
        return None
    _P2P_HEADER_CHAIN_CACHE = (key, mtime, chain)
    _sync_main_cache_scalars()
    return chain

def block_time_for_height(
    height: int,
    cache_root: Path | None = None,
) -> int | None:
    """
    Unix-Zeit eines Blocks zur Höhe — lokal, ohne Netz.

    Reihenfolge: ``block_header/*.json``, sonst ``p2p_headers.bin``.
    Treffer aus der Header-Datei werden in den JSON-Cache geschrieben.
    """
    try:
        hoehe = int(height)
    except (TypeError, ValueError):
        return None
    if hoehe <= 0:
        return None
    root = Path(cache_root) if cache_root else IMMUTABLE_CACHE_DIR
    cached = load_cached_block_time(hoehe, root)
    if cached is not None:
        return cached

    chain = _p2p_header_chain(root)
    if chain is None:
        return None
    try:
        if hoehe > chain.tip_height() or hoehe < getattr(chain, "_anchor_height", 0):
            return None
        header = chain.header_at(hoehe) if hoehe != chain._anchor_height else None
        if header is None and hoehe == chain._anchor_height:
            # Anker-Höhe: nur Hash bekannt, kein voller Header in der Datei.
            return None
        if header is None or len(header) < 72:
            return None
        block_time = int.from_bytes(header[68:72], "little")
    except (IndexError, OSError, ValueError, TypeError):
        return None
    if block_time <= 0:
        return None
    try:
        save_cached_block_time(hoehe, block_time, root, "p2p_headers")
    except Exception:
        pass
    return block_time

def enrich_utxos_with_block_times(
    utxos: list[dict],
    cache_root: Path | None = None,
) -> int:
    """
    Setzt fehlendes ``status.block_time`` aus der lokalen Header-Quelle.

    Rückgabe: Anzahl nachgezogener UTXOs. Mutiert *utxos* in place.
    """
    if not utxos:
        return 0
    root = Path(cache_root) if cache_root else IMMUTABLE_CACHE_DIR
    # Höhe → betroffene status-Dicts (ein Lookup je Höhe).
    nach_hoehe: dict[int, list[dict]] = {}
    for utxo in utxos:
        if not isinstance(utxo, dict):
            continue
        status = utxo.get("status")
        if not isinstance(status, dict):
            status = {}
            utxo["status"] = status
        if status.get("block_time"):
            continue
        raw = status.get("block_height", utxo.get("height"))
        try:
            hoehe = int(raw)
        except (TypeError, ValueError):
            continue
        if hoehe <= 0:
            continue
        nach_hoehe.setdefault(hoehe, []).append(status)

    angereichert = 0
    for hoehe, stati in nach_hoehe.items():
        ts = block_time_for_height(hoehe, root)
        if ts is None:
            continue
        for status in stati:
            status["block_time"] = ts
            angereichert += 1
    return angereichert

def rewrite_utxo_cache_times(
    xpub: str,
    cache_dir: Path,
    utxos: list[dict],
) -> None:
    """
    Schreibt nur die UTXO-Liste zurück — ohne ``scanned_at``/Quelle anzufassen.

    Für das Nachziehen von Blockzeiten nach scantxoutset o. ä.
    """
    path = _xpub_cache_path(xpub, cache_dir)
    if not path.is_file() or not cache_disk_write_allowed(cache_dir):
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    data["utxos"] = utxos
    data["utxo_count"] = len(utxos)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(_dump_cache_json(data), encoding="utf-8")
    tmp.replace(path)

def _utxo_ingress_cache_path(txid: str, vout: int, cache_root: Path) -> Path:
    return cache_root / UTXO_INGRESS_CACHE_SUBDIR / f"{_normalize_txid(txid)}_{int(vout)}.json"

def load_utxo_ingress_cache(
    txid: str,
    vout: int,
    cache_root: Path | None = None,
) -> dict | None:
    """Gecachtes Zugangsdatum der jüngsten Sats eines analysierten Outputs."""
    root = cache_root or IMMUTABLE_CACHE_DIR
    path = _utxo_ingress_cache_path(txid, vout, root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if str(data.get("txid", "")).lower() != _normalize_txid(txid):
        return None
    if int(data.get("vout", -1)) != int(vout):
        return None
    return data

def save_utxo_ingress_cache(
    txid: str,
    vout: int,
    ingress: dict,
    cache_root: Path,
) -> Path:
    """Speichert jüngstes Wallet-Zugangsdatum für einen Output (txid:vout)."""
    root = Path(cache_root)
    path = _utxo_ingress_cache_path(txid, vout, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "txid": _normalize_txid(txid),
        "vout": int(vout),
        "youngest_time": ingress.get("youngest_time"),
        "youngest_time_ts": ingress.get("youngest_time_ts"),
        "youngest_wallet": ingress.get("youngest_wallet"),
        "youngest_sats": ingress.get("youngest_sats"),
        # Steuerliches Anschaffungsdatum: jüngster externer Zufluss, nicht
        # der jüngste Wallet-Eingang. Interne Überträge zwischen eigenen
        # XPUBs/Seeds verändern die Haltedauer nicht.
        "external_time_ts": ingress.get("external_time_ts"),
        "external_sats": ingress.get("external_sats"),
        "external_address": ingress.get("external_address"),
        # Ältester externer Zufluss — für STEUER_ANSCHAFFUNG=aelteste.
        "external_oldest_time_ts": ingress.get("external_oldest_time_ts"),
        "external_oldest_sats": ingress.get("external_oldest_sats"),
        "external_oldest_address": ingress.get("external_oldest_address"),
        # True, wenn externe Eingänge unaufgelöst blieben (Sammel-Tx über
        # dem Auflösungs-Limit) und das Datum deshalb zu alt sein kann.
        "external_untergrenze": bool(ingress.get("external_untergrenze")),
        "address": ingress.get("address"),
    }
    if ingress.get("tax_horizon_time_ts") is not None:
        payload["tax_horizon_time_ts"] = ingress.get("tax_horizon_time_ts")
    # Kursfelder aus *ingress* übernehmen (falls schon gesetzt) + lokal anreichern.
    for k, v in (ingress or {}).items():
        if k.startswith(("youngest_btc_", "youngest_value_",
                         "external_btc_", "external_value_",
                         "external_oldest_btc_", "external_oldest_value_",
                         "tax_horizon_btc_", "tax_horizon_value_")):
            payload[k] = v
    try:
        from core import price as price_mod

        payload = price_mod.anreichere_ingress(
            payload, immutable_cache_dir=root,
        )
    except Exception:
        pass
    if not cache_disk_write_allowed(root):
        return path
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(_dump_cache_json(payload), encoding="utf-8")
    tmp.replace(path)
    _maybe_log_sqlite_flatfile_hint(path.parent, kind="utxo_ingress")
    return path

def iter_utxo_ingress_cache_entries(cache_root: Path | None = None) -> list[dict]:
    """Lädt alle gespeicherten Herkunfts-Analysen (Jüngste-Sats) zu Outputs."""
    root = Path(cache_root or IMMUTABLE_CACHE_DIR)
    subdir = root / UTXO_INGRESS_CACHE_SUBDIR
    if not subdir.is_dir():
        return []

    entries: list[dict] = []
    for path in sorted(subdir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        txid = str(data.get("txid", "")).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", txid):
            continue
        try:
            vout = int(data.get("vout", -1))
        except (TypeError, ValueError):
            continue
        if vout < 0:
            continue
        entries.append(data)
    return entries

def load_unspent_outpoint_values(utxo_cache_dir: Path | None = None) -> dict[str, int]:
    """Unspent Outpoints aus XPUB-UTXO-Caches: ``txid:vout`` → Wert in sats."""
    from core.wallet_context import EXTERNAL_ADDRESS_CACHE_NAME
    cache_dir = Path(utxo_cache_dir or UTXO_CACHE_DIR)
    if not cache_dir.is_dir():
        return {}

    values: dict[str, int] = {}
    for path in sorted(cache_dir.glob("*.json")):
        if path.name == EXTERNAL_ADDRESS_CACHE_NAME:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        utxos = data.get("utxos")
        if not isinstance(utxos, list):
            continue
        for utxo in utxos:
            if not isinstance(utxo, dict):
                continue
            txid = str(utxo.get("txid", "")).strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", txid):
                continue
            try:
                vout = int(utxo.get("vout", -1))
                value = int(utxo.get("value", 0))
            except (TypeError, ValueError):
                continue
            if vout < 0 or value < 0:
                continue
            values[f"{txid}:{vout}"] = value
    return values

def _xpub_cache_key(xpub: str) -> str:
    """
    Kurzer Dateiname-Schlüssel für ein XPUB oder einen Deskriptor.

    Bei Deskriptoren zählt die **erste abgeleitete Adresse**, nicht der Text:
    Dieselben Cosigner in anderer Reihenfolge ergeben bei ``sortedmulti``
    (BIP-67) dieselben Adressen — also dieselbe Wallet, die auch denselben
    Cache behalten soll. Nach dem Text wären es zwei, und Beträge zählten
    doppelt.
    """
    if ist_deskriptor(xpub):
        # setdefault: auch nach reload/Teilimport nie wieder NameError.
        kennungen = globals().setdefault("_deskriptor_kennungen", {})
        bekannt = kennungen.get(xpub)
        if bekannt:
            return bekannt
        adressen = derive_descriptor_addresses(xpub, max_addresses=2)
        grundlage = sorted(adressen)[0] if adressen else xpub
        kennung = hashlib.sha256(grundlage.encode("utf-8")).hexdigest()[:16]
        kennungen[xpub] = kennung
        return kennung
    return hashlib.sha256(xpub.encode("utf-8")).hexdigest()[:16]

def _xpub_cache_path(xpub: str, cache_dir: Path) -> Path:
    return cache_dir / f"{_xpub_cache_key(xpub)}.json"

def _cache_scan_end_index(
    cache_data: dict | None,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
) -> int:
    """Nächster zu scannender Index pro Chain (0 = m/0/0, m/1/0)."""
    if cache_data and "scan_end_index" in cache_data:
        return int(cache_data["scan_end_index"])
    return max_addresses // 2

def load_xpub_cache_entry(xpub: str, cache_dir: Path) -> dict | None:
    """Lädt Cache-Eintrag inkl. UTXOs und Scan-Position."""
    path = _xpub_cache_path(xpub, cache_dir)
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if data.get("xpub") != xpub:
        return None

    utxos = data.get("utxos")
    if not isinstance(utxos, list):
        return None

    return {
        "utxos": utxos,
        "scan_end_index": _cache_scan_end_index(data),
        "raw": data,
    }

def load_xpub_utxo_cache(xpub: str, cache_dir: Path) -> list[dict] | None:
    """Lädt gecachte UTXOs für ein XPUB aus einer Flatfile."""
    entry = load_xpub_cache_entry(xpub, cache_dir)
    return entry["utxos"] if entry else None

def _scan_tip_anheben(
    tip_i: int | None,
    cache_dir: Path,
    *,
    fulcrum=None,
    extra_heights: list[int] | tuple[int, ...] | None = None,
) -> int | None:
    """
    Hebt ``scan_tip_height`` nur an (nie absenken).

    Reihenfolge: bisheriger Tip → optionale Höhen (Spends/UTXOs) →
    Electrs-Tip → Header-Datei. Sonst bleibt nach Wallet-Watch-Settle die
    mtime frisch, der Tip aber Wochen hinter dem Chain-Tip („vor 12 Min · −53 Blöcke“).
    """
    tip = tip_i
    for roh in extra_heights or ():
        try:
            h = int(roh or 0)
        except (TypeError, ValueError):
            continue
        if h > 0 and (tip is None or h > tip):
            tip = h
    if fulcrum is not None:
        try:
            from fulcrum import get_chain_tip_height

            et = int(get_chain_tip_height(fulcrum, force=True))
            if tip is None or et > int(tip):
                tip = et
        except Exception:
            pass
    try:
        from core.p2p import header_datei_tip, p2p_headers_path

        header_tip = header_datei_tip(
            p2p_headers_path(
                resolve_immutable_cache_dir(None, utxo_cache_dir=cache_dir)
            )
        )
        if header_tip is not None:
            ht = int(header_tip)
            if tip is None or ht > int(tip):
                tip = ht
    except Exception:
        pass
    return tip

def _blockhoehe_aus_utxo(utxo: dict) -> int:
    """Bestätigungshöhe aus UTXO-Dict (status oder height)."""
    status = utxo.get("status") if isinstance(utxo.get("status"), dict) else {}
    for roh in (
        status.get("block_height"),
        utxo.get("height"),
        utxo.get("block_height"),
        utxo.get("spent_height"),
    ):
        try:
            h = int(roh or 0)
        except (TypeError, ValueError):
            continue
        if h > 0:
            return h
    return 0

def settle_gezielte_spends_im_cache(
    xpub: str,
    cache_dir: Path,
    *,
    confirmed_spent: list[dict],
    live_auf_adressen: list[dict],
    source: str = "fulcrum",
    fulcrum=None,
) -> list[dict] | None:
    """
    Bestätigte Spends und frisches listunspent nur für betroffene Adressen.

    * confirmed_spent → aus UTXO-Cache, in Verlauf mit spent_*
    * live_auf_adressen → ersetzt Cache-UTXOs **dieser** Adressen
      (Change/neue Empfänge), andere Adressen unangetastet

    Kein Gap, kein Fullscan. Rückgabe: neue UTXO-Liste oder None ohne Cache.
    ``scan_tip_height`` wird mit Header-/Electrs-Tip und bekannten Höhen
    angehoben — sonst wirkt der Cache frisch (mtime), bleibt aber „−N Blöcke“.
    """
    entry = load_xpub_cache_entry(xpub, cache_dir)
    if entry is None:
        return None
    alt = list(entry.get("utxos") or [])
    if not confirmed_spent and not live_auf_adressen:
        return alt

    spent_keys = {
        f"{str(s.get('txid') or '').lower()}:{int(s.get('vout') or 0)}"
        for s in confirmed_spent
    }
    adressen_live = {
        str(u.get("address") or "").strip()
        for u in live_auf_adressen
        if (u.get("address") or "").strip()
    }
    # Auch Adressen der confirmed spends (falls live leer war)
    for s in confirmed_spent:
        a = str(s.get("address") or "").strip()
        if a:
            adressen_live.add(a)

    behalten: list[dict] = []
    for u in alt:
        key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        if key in spent_keys:
            continue
        addr = str(u.get("address") or "").strip()
        if addr and addr in adressen_live:
            # Wird durch frisches listunspent ersetzt
            continue
        behalten.append(u)

    live_keys: set[str] = set()
    for u in live_auf_adressen:
        key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        if key in live_keys:
            continue
        live_keys.add(key)
        behalten.append(u)

    scan_end = int(entry.get("scan_end_index") or 0) or None
    tip = (entry.get("raw") or {}).get("scan_tip_height")
    try:
        tip_i = int(tip) if tip is not None else None
    except (TypeError, ValueError):
        tip_i = None
    # Nur Spend-Höhe bzw. Live-UTXO-Höhe — nicht die Empfangshöhe des
    # ausgegebenen Outputs (die kann weit hinter dem Tip liegen und würde
    # fälschlich als „Scan-Tip“ wirken).
    extra: list[int] = []
    for s in confirmed_spent:
        try:
            h = int(s.get("spent_height") or 0)
        except (TypeError, ValueError):
            h = 0
        if h > 0:
            extra.append(h)
    for u in live_auf_adressen:
        h = _blockhoehe_aus_utxo(u)
        if h > 0:
            extra.append(h)
    tip_i = _scan_tip_anheben(
        tip_i, cache_dir, fulcrum=fulcrum, extra_heights=extra,
    )

    max_addr = int((entry.get("raw") or {}).get("max_addresses") or DEFAULT_MAX_ADDRESSES)
    save_xpub_utxo_cache(
        xpub,
        behalten,
        cache_dir,
        source,
        scan_end_index=scan_end,
        max_addresses=max_addr,
        scan_tip_height=tip_i,
    )

    if confirmed_spent:
        verlauf_neu: list[dict] = []
        for s in confirmed_spent:
            verlauf_neu.append({
                "txid": str(s.get("txid") or "").lower(),
                "vout": int(s.get("vout") or 0),
                "address": s.get("address"),
                "value": int(s.get("value") or 0),
                "spent": True,
                "spent_pending": False,
                "spent_txid": s.get("spent_txid") or "",
                "spent_height": int(s.get("spent_height") or 0),
                "spent_time_ts": s.get("spent_time_ts"),
                "status": s.get("status") or {},
            })
        merke_bip158_verlauf(xpub, verlauf_neu, cache_dir)

    return behalten

def first_seen_from_utxos(utxos: list[dict] | None) -> dict | None:
    """
    Früheste Bestätigung aus einer UTXO-Liste (Höhe + optional Blockzeit).

    Für BIP-158: dort gibt es keinen Electrum-History-Lookup — das Alter
    kommt aus den gefundenen Outputs.
    """
    beste_hoehe: int | None = None
    beste_ts: int | None = None
    for u in utxos or []:
        status = u.get("status") if isinstance(u, dict) else None
        if not isinstance(status, dict):
            status = {}
        try:
            hoehe = int(status.get("block_height") or u.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if hoehe <= 0:
            continue
        try:
            ts = status.get("block_time") or u.get("block_time")
            ts_i = int(ts) if ts is not None else None
        except (TypeError, ValueError):
            ts_i = None
        if beste_hoehe is None or hoehe < beste_hoehe:
            beste_hoehe = hoehe
            beste_ts = ts_i
        elif hoehe == beste_hoehe and ts_i is not None:
            if beste_ts is None or ts_i < beste_ts:
                beste_ts = ts_i
    if beste_hoehe is None:
        return None
    return {"height": beste_hoehe, "time_ts": beste_ts}

def bip158_start_aus_first_seen(
    xpub: str,
    cache_dir: Path | None,
    *,
    floor: int | None = None,
    puffer: int = 6,
) -> int | None:
    """
    Scan-Start ab Wallet-Beginn (First-seen), mit kleinem Vorlauf.

    Für Rescan ohne UTXO-Cache: statt SegWit dort beginnen, wo das Wallet
    wirklich losging. Rückgabe None, wenn kein Alter bekannt.
    """
    if cache_dir is None:
        return None
    alter = xpub_first_seen(xpub, cache_dir)
    if not alter:
        return None
    try:
        hoehe = int(alter["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if hoehe <= 0:
        return None
    start = max(0, hoehe - max(0, int(puffer)))
    if floor is not None:
        start = max(int(floor), start)
    return start

def _first_seen_label(first_seen: dict | None) -> str:
    """„22.08.2023 18:05" oder, ohne Blockzeit, „Block 800.123"."""
    if not first_seen:
        return "unbekannt"
    stempel = first_seen.get("time_ts")
    if stempel:
        try:
            return datetime.fromtimestamp(int(stempel)).strftime("%d.%m.%Y %H:%M")
        except (ValueError, OSError, OverflowError):
            pass
    hoehe = first_seen.get("height")
    return f"Block {hoehe:,}".replace(",", ".") if hoehe else "unbekannt"

def _xpub_verlauf_cache_path(xpub: str, cache_dir: Path) -> Path:
    """
    Dateiname des Verlaufs-Caches.

    Getrennt vom UTXO-Cache und nicht in ihn hinein: Der Verlauf ist um ein
    Vielfaches größer. Wer Bestände liest, soll ihn nicht mitladen müssen.
    BIP-158-UTXO-Scan schreibt ihn mit (Empfang und Ausgabe liegen im Blockscan);
    Fulcrum erhebt ihn auf ausdrückliche Anforderung.
    """
    return Path(cache_dir) / f"{_xpub_cache_key(xpub)}_verlauf.json"

def load_xpub_verlauf_cache(xpub: str, cache_dir: Path) -> list[dict] | None:
    """
    Gespeicherter Verlauf eines XPUB, oder None.

    Jeder Zweifel — fehlende Datei, kaputtes JSON, unerwartete Form — führt zu
    None: lieber neu erheben als eine halbe Historie auswerten. Aus einer
    unvollständigen Aufstellung würden falsche Steuerzahlen.

    Unvollständige Scans (Abbruch/Timeout) liefern trotzdem die bisher
    gemerkten Einträge — siehe ``load_xpub_verlauf_scan_meta``.
    """
    path = _xpub_verlauf_cache_path(xpub, cache_dir)
    if not path.is_file():
        return None
    try:
        daten = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(daten, list):
        return daten
    if isinstance(daten, dict) and isinstance(daten.get("eintraege"), list):
        return daten["eintraege"]
    return None

def load_xpub_verlauf_scan_meta(xpub: str, cache_dir: Path) -> dict:
    """
    Scan-Zwischenstand: welche Adressen schon abgefragt wurden.

    ``incomplete``: Lauf abgebrochen — beim nächsten Start fortsetzen.
    """
    path = _xpub_verlauf_cache_path(xpub, cache_dir)
    leer = {
        "incomplete": False,
        "scanned_addresses": [],
        "planned_addresses": [],
    }
    if not path.is_file():
        return leer
    try:
        daten = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return leer
    if not isinstance(daten, dict):
        return leer
    scan = daten.get("scan") if isinstance(daten.get("scan"), dict) else {}
    return {
        "incomplete": bool(scan.get("incomplete")),
        "scanned_addresses": [
            str(a) for a in (scan.get("scanned_addresses") or []) if a
        ],
        "planned_addresses": [
            str(a) for a in (scan.get("planned_addresses") or []) if a
        ],
    }

def save_xpub_verlauf_cache(
    xpub: str,
    eintraege: list[dict],
    cache_dir: Path,
    *,
    scanned_addresses: list[str] | None = None,
    planned_addresses: list[str] | None = None,
    incomplete: bool | None = None,
) -> Path:
    """
    Schreibt den Verlauf eines XPUB.

    Optionaler Scan-Zwischenstand: bei ``incomplete=True`` setzt der nächste
    Lauf bei den noch fehlenden Adressen fort.
    """
    path = _xpub_verlauf_cache_path(xpub, cache_dir)
    if not cache_disk_write_allowed(cache_dir):
        return path
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    meta = load_xpub_verlauf_scan_meta(xpub, cache_dir)
    if scanned_addresses is not None:
        meta["scanned_addresses"] = sorted(set(scanned_addresses))
    if planned_addresses is not None:
        meta["planned_addresses"] = sorted(set(planned_addresses))
    if incomplete is not None:
        meta["incomplete"] = bool(incomplete)
    imm = resolve_immutable_cache_dir(None, utxo_cache_dir=cache_dir)

    def _bt_hoehe(h: int):
        try:
            return load_cached_block_time(int(h), imm)
        except Exception:
            return None

    try:
        from core import price as price_mod

        eintraege_out = price_mod.anreichere_utxo_liste(
            list(eintraege or []),
            immutable_cache_dir=imm,
            block_time_fuer_hoehe=_bt_hoehe,
        )
    except Exception:
        eintraege_out = list(eintraege or [])
    payload = {
        "eintraege": eintraege_out,
        "scan": {
            "incomplete": bool(meta["incomplete"]),
            "scanned_addresses": list(meta["scanned_addresses"]),
            "planned_addresses": list(meta["planned_addresses"]),
        },
    }
    path.write_text(_dump_cache_json(payload), encoding="utf-8")
    return path

def merke_bip158_verlauf(
    xpub: str,
    eintraege: list[dict],
    cache_dir: Path,
) -> Path:
    """
    Mischt BIP-158-Verlauf in den Cache.

    Ein späterer Turbo-Pass sieht nicht jede alte Adresse — vorhandene
    Einträge bleiben, ``spent`` wird nur gesetzt, nie gelöscht.
    """
    alt = load_xpub_verlauf_cache(xpub, cache_dir) or []
    return save_xpub_verlauf_cache(
        xpub, _merge_verlauf_eintraege(alt, eintraege), cache_dir,
    )

def _merge_verlauf_eintraege(
    alt: list[dict],
    neu: list[dict],
) -> list[dict]:
    """Mischt Verlaufseinträge; spent und Blockzeiten nur ergänzen."""
    index: dict[tuple[str, int], dict] = {}
    for eintrag in alt:
        key = (str(eintrag.get("txid") or "").lower(), int(eintrag.get("vout") or 0))
        index[key] = dict(eintrag)
    for eintrag in neu:
        key = (str(eintrag.get("txid") or "").lower(), int(eintrag.get("vout") or 0))
        bisher = index.get(key)
        if bisher is None:
            index[key] = dict(eintrag)
            continue
        if eintrag.get("spent"):
            for feld in ("spent", "spent_txid", "spent_height", "spent_time_ts"):
                if feld in eintrag:
                    bisher[feld] = eintrag[feld]
        if not bisher.get("address") and eintrag.get("address"):
            bisher["address"] = eintrag["address"]
        status = bisher.setdefault("status", {})
        neu_st = eintrag.get("status") or {}
        if not status.get("block_time") and neu_st.get("block_time"):
            status["block_time"] = neu_st["block_time"]
        if not status.get("block_height") and neu_st.get("block_height"):
            status["block_height"] = neu_st["block_height"]
    return list(index.values())

def _xpub_alter_path(xpub: str, cache_dir: Path) -> Path:
    """
    Eigenes File fürs Wallet-Alter — überlebt das Löschen des UTXO-Caches.

    Die älteste Transaktion ändert sich nicht; sie darf nicht mit den
    veränderlichen Beständen verschwinden.
    """
    return Path(cache_dir) / f"{_xpub_cache_key(xpub)}_alter.json"

def _alter_aus_payload(roh: dict | None) -> dict | None:
    if not roh:
        return None
    hoehe = roh.get("height", roh.get("first_seen_height"))
    if not hoehe:
        return None
    return {
        "height": int(hoehe),
        "time_ts": roh.get("time_ts", roh.get("first_seen_ts")),
    }

def save_xpub_first_seen(
    xpub: str,
    cache_dir: Path,
    first_seen: dict | None,
) -> Path:
    """
    Schreibt das Wallet-Alter. Ein vorhandener Wert bleibt — erhoben wird
    nur einmal, ein jüngerer Fund darf ihn nicht überschreiben.
    """
    path = _xpub_alter_path(xpub, cache_dir)
    if path.is_file():
        return path
    wert = _alter_aus_payload(first_seen)
    if not wert:
        return path
    try:
        from core import price as price_mod

        imm = resolve_immutable_cache_dir(None, utxo_cache_dir=cache_dir)
        price_mod.reichere_fiat_an(
            wert,
            time_ts=wert.get("time_ts"),
            value_sats=None,
            immutable_cache_dir=imm,
            prefix="",
        )
    except Exception:
        pass
    if not cache_disk_write_allowed(cache_dir):
        return path
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_cache_json(wert), encoding="utf-8")
    return path

def xpub_first_seen(xpub: str, cache_dir: Path) -> dict | None:
    """
    Wann dieses Wallet zum ersten Mal benutzt wurde.

    Zuerst die eigene Alters-Datei (überlebt Cache-Löschen), sonst die
    Felder in der UTXO-Cache-Datei — die werden dann ins eigene File
    übernommen. Liefert ``{"height": …, "time_ts": …}`` oder None.
    """
    alter_pfad = _xpub_alter_path(xpub, cache_dir)
    if alter_pfad.is_file():
        try:
            roh = json.loads(alter_pfad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            roh = None
        gefunden = _alter_aus_payload(roh if isinstance(roh, dict) else None)
        if gefunden:
            return gefunden

    eintrag = load_xpub_cache_entry(xpub, cache_dir)
    gefunden = _alter_aus_payload((eintrag or {}).get("raw") or {})
    if gefunden:
        save_xpub_first_seen(xpub, cache_dir, gefunden)
    return gefunden

def bip158_fullscan_ist_fertig(roh: dict | None) -> bool:
    """
    True, wenn der UTXO-Bestand am Chain-Tip bekannt ist.

    Gesetzt nach erfolgreichem BIP-158-Fullscan **oder** Electrum-/Fulcrum-
    Fullscan (Gap liefert den Stand am Tip). Zwischenstände (Abbruch) dürfen
    Turbo-Erstscan nicht deaktivieren. Alt-Caches ohne Flag: vorhandenes
    ``scan_tip_height`` gilt als fertig.
    """
    if not roh:
        return False
    flag = roh.get("bip158_fullscan_ok")
    if flag is True:
        return True
    if flag is False:
        return False
    tip = roh.get("scan_tip_height")
    if tip is None:
        return False
    try:
        return int(tip) > 0
    except (TypeError, ValueError):
        return False

#: Nach frischem UTXO-Scan: Verlauf braucht keinen zweiten Gap-Scan.
VERLAUF_UTXO_CACHE_MAX_ALTER_S = 2 * 3600

def _parse_scanned_at(stempel: object) -> datetime | None:
    if not stempel:
        return None
    text = str(stempel).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None

def utxo_cache_frisch_genug(
    xpubs: list[str],
    cache_dir: Path,
    *,
    max_alter_s: int = VERLAUF_UTXO_CACHE_MAX_ALTER_S,
) -> tuple[list[dict] | None, str]:
    """
    Liefert (alle UTXOs, Grund), wenn jeder XPUB einen frischen Cache hat.

    Sonst ``(None, grund)`` — Verlaufs-Job soll Gap-Scan nachziehen.
    Partial-BIP-158 (``bip158_fullscan_ok=false``) zählt nicht als frisch.
    """
    if not xpubs:
        return None, "keine XPUBs"
    jetzt = datetime.now(UTC)
    alle: list[dict] = []
    aeltest_s = 0
    for xpub in xpubs:
        entry = load_xpub_cache_entry(xpub, cache_dir)
        if entry is None:
            return None, "UTXO-Cache fehlt"
        roh = entry.get("raw") or {}
        if roh.get("bip158_fullscan_ok") is False:
            return None, "BIP-158-Scan unvollständig"
        stempel = _parse_scanned_at(roh.get("scanned_at"))
        if stempel is None:
            return None, "kein scanned_at"
        if stempel.tzinfo is None:
            stempel = stempel.replace(tzinfo=UTC)
        alter = (jetzt - stempel.astimezone(UTC)).total_seconds()
        if alter < 0:
            alter = 0
        if alter > max_alter_s:
            return None, f"Cache {int(alter // 60)} Min. alt"
        aeltest_s = max(aeltest_s, int(alter))
        alle.extend(entry.get("utxos") or [])
    minuten = max(1, aeltest_s // 60) if aeltest_s >= 60 else 0
    if minuten:
        grund = f"UTXO-Cache ≤{minuten} Min. alt — Gap-Scan übersprungen"
    else:
        grund = "UTXO-Cache frisch — Gap-Scan übersprungen"
    return alle, grund

def save_xpub_utxo_cache(
    xpub: str,
    utxos: list[dict],
    cache_dir: Path,
    source: str,
    scan_end_index: int | None = None,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    first_seen: dict | None = None,
    scan_tip_height: int | None = None,
    *,
    bip158_fullscan_ok: bool | None = None,
) -> Path:
    """
    Speichert UTXOs eines XPUB als JSON-Flatfile.

    *first_seen* hält fest, wann das Wallet zum ersten Mal benutzt wurde
    (``{"height": …, "time_ts": …}``). Fehlt der Wert, wird ein bereits
    gespeicherter übernommen — er wird einmal erhoben und ändert sich nie
    wieder, ein Rescan darf ihn also nicht verlieren.

    *scan_tip_height* (BIP-158): bis zu welcher Chain-Höhe der Filter-Scan
    ging. Fehlt der Wert, bleibt ein bereits gespeicherter Tip erhalten.

    *bip158_fullscan_ok*: nur ``True`` nach komplettem BIP-158-Fullscan.
    ``None`` = bisherigen Wert behalten (Zwischenstand darf nicht auf fertig
    setzen). Explizit ``False`` markiert unvollständig.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _xpub_cache_path(xpub, cache_dir)
    bisher = load_xpub_cache_entry(xpub, cache_dir)
    roh_bisher = (bisher or {}).get("raw") or {}
    if scan_end_index is None:
        scan_end_index = max_addresses // 2
    if first_seen is None:
        first_seen = xpub_first_seen(xpub, cache_dir)
    if scan_tip_height is None and roh_bisher.get("scan_tip_height") is not None:
        try:
            scan_tip_height = int(roh_bisher["scan_tip_height"])
        except (TypeError, ValueError):
            scan_tip_height = None
    save_xpub_first_seen(xpub, cache_dir, first_seen)
    # Tageskurs EUR/USD + Fiat-Gegenwert nur lokal, nur fehlende Felder
    # (kein Migrations-Rerun; neue/ergänzte Einträge beim Schreiben).
    imm = resolve_immutable_cache_dir(None, utxo_cache_dir=cache_dir)

    def _bt_hoehe(h: int):
        try:
            return load_cached_block_time(int(h), imm)
        except Exception:
            return None

    try:
        from core import price as price_mod

        utxos_out = price_mod.anreichere_utxo_liste(
            list(utxos or []),
            immutable_cache_dir=imm,
            block_time_fuer_hoehe=_bt_hoehe,
        )
    except Exception:
        utxos_out = list(utxos or [])
    payload = {
        "xpub": xpub,
        "xpub_prefix": xpub[:25],
        "scanned_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "scan_end_index": scan_end_index,
        "max_addresses": max_addresses,
        "utxo_count": len(utxos_out),
        "utxos": utxos_out,
    }
    if first_seen:
        payload["first_seen_height"] = first_seen.get("height")
        payload["first_seen_ts"] = first_seen.get("time_ts")
        try:
            from core import price as price_mod

            fs = dict(first_seen)
            price_mod.reichere_fiat_an(
                fs,
                time_ts=fs.get("time_ts"),
                value_sats=None,
                immutable_cache_dir=imm,
                prefix="first_seen_",
            )
            if fs.get("first_seen_btc_eur") is not None:
                payload["first_seen_btc_eur"] = fs["first_seen_btc_eur"]
            if fs.get("first_seen_btc_usd") is not None:
                payload["first_seen_btc_usd"] = fs["first_seen_btc_usd"]
            if fs.get("first_seen_btc_day"):
                payload["first_seen_btc_day"] = fs["first_seen_btc_day"]
        except Exception:
            pass
    if scan_tip_height is not None:
        payload["scan_tip_height"] = int(scan_tip_height)
    if bip158_fullscan_ok is not None:
        payload["bip158_fullscan_ok"] = bool(bip158_fullscan_ok)
    elif "bip158_fullscan_ok" in roh_bisher:
        payload["bip158_fullscan_ok"] = bool(roh_bisher["bip158_fullscan_ok"])
    if not cache_disk_write_allowed(cache_dir):
        # Früher: still return path — Scan meldete Erfolg, UI zeigte keinen Cache.
        raise CacheDiskFullError(_cache_disk_full_meldung(cache_dir))
    path.write_text(_dump_cache_json(payload), encoding="utf-8")
    return path

def schreibe_utxo_zwischenstand(
    xpub: str,
    utxos: list[dict],
    cache_dir: Path,
    source: str,
    *,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
) -> Path:
    """
    Schreibt den bekannten UTXO-Bestand während eines laufenden Scans.

    ``scan_end_index`` und ``scan_tip_height`` bleiben unverändert (bzw. 0),
    damit ein Abbruch keinen unfertigen Lauf als Tip-Sync-fertig markiert.
    ``bip158_fullscan_ok`` wird nicht auf True gesetzt (Abbruch ≠ Fullscan).
    First-seen wird nicht neu erhoben — nur übernommen, falls schon da.
    """
    entry = load_xpub_cache_entry(xpub, cache_dir)
    scan_end = int(entry["scan_end_index"] or 0) if entry else 0
    # BIP-158-Zwischenstand: explizit unvollständig, falls noch nie fertig.
    # War schon ein Fullscan ok, Flag behalten (Rescan-Abbruch).
    full_ok = None
    if source == "bip158":
        roh = (entry or {}).get("raw") or {}
        if not bip158_fullscan_ist_fertig(roh):
            full_ok = False
    return save_xpub_utxo_cache(
        xpub,
        utxos,
        cache_dir,
        source,
        scan_end_index=scan_end,
        max_addresses=(
            int((entry or {}).get("raw", {}).get("max_addresses") or max_addresses)
            if entry
            else max_addresses
        ),
        bip158_fullscan_ok=full_ok,
    )

def _uebernehme_first_seen(payload: dict, entry: dict | None) -> None:
    """
    Trägt ein bereits erhobenes Wallet-Alter in einen neu gebauten Payload.

    Mehrere Stellen schreiben den XPUB-Cache und stellen ihren Payload dabei
    selbst zusammen. Ohne diese Übernahme fiele das Alter beim nächsten
    Ziel-Scan wieder heraus — erhoben wird es aber nur ein einziges Mal.
    """
    roh = (entry or {}).get("raw") or {}
    if roh.get("first_seen_height"):
        payload["first_seen_height"] = roh["first_seen_height"]
        payload["first_seen_ts"] = roh.get("first_seen_ts")

def _address_utxos_in_cache(cached: list[dict], address: str) -> bool:
    return any(u.get("address") == address for u in cached)

def _address_known_in_cache(entry: dict | None, address: str) -> bool:
    if not entry:
        return False
    if _address_utxos_in_cache(entry["utxos"], address):
        return True
    return address in entry["raw"].get("scanned_addresses", [])

def _mark_address_scanned(
    xpub: str,
    address: str,
    cache_dir: Path,
    source: str,
    existing_utxos: list[dict] | None = None,
) -> None:
    """Merkt eine Adresse als gescannt, auch wenn sie 0 UTXOs hat."""
    entry = load_xpub_cache_entry(xpub, cache_dir)
    utxos = existing_utxos if existing_utxos is not None else (
        entry["utxos"] if entry else []
    )
    scanned = set(entry["raw"].get("scanned_addresses", [])) if entry else set()
    scanned.add(address)
    scan_end = entry["scan_end_index"] if entry else 0
    max_addr = (
        entry["raw"].get("max_addresses", DEFAULT_MAX_ADDRESSES)
        if entry else DEFAULT_MAX_ADDRESSES
    )
    cache_path = _xpub_cache_path(xpub, cache_dir)
    if not cache_disk_write_allowed(cache_dir):
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "xpub": xpub,
        "xpub_prefix": xpub[:25],
        "scanned_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "scan_end_index": scan_end,
        "max_addresses": max_addr,
        "scanned_addresses": sorted(scanned),
        "utxo_count": len(utxos),
        "utxos": utxos,
    }
    _uebernehme_first_seen(payload, entry)
    cache_path.write_text(_dump_cache_json(payload), encoding="utf-8")

def _utxo_set_signature(utxos: list[dict]) -> dict[str, int]:
    """Kanonische UTXO-Menge zum Vergleich: txid:vout -> Satoshis."""
    return {f"{u['txid']}:{u['vout']}": u["value"] for u in utxos}

def _utxo_sets_match(cached: list[dict], live: list[dict]) -> bool:
    return _utxo_set_signature(cached) == _utxo_set_signature(live)

def _merge_utxo_lists(*groups: list[dict]) -> list[dict]:
    """Vereinigt UTXO-Listen ohne Duplikate (nach txid:vout)."""
    merged: dict[str, dict] = {}
    for group in groups:
        for utxo in group:
            merged[f"{utxo['txid']}:{utxo['vout']}"] = utxo
    return list(merged.values())

def _fetch_utxos_for_addresses(
    addresses: set[str] | list[str],
    fetch_address_utxos,
    *,
    on_batch_progress=None,
) -> list[dict]:
    """UTXOs fuer mehrere Adressen (Fallback: einzeln pro Adresse)."""
    addr_list = sorted(set(addresses))
    utxos: list[dict] = []
    batch_len = len(addr_list)
    for done, address in enumerate(addr_list, start=1):
        for utxo in fetch_address_utxos(address):
            utxo["address"] = address
            utxos.append(utxo)
        if on_batch_progress is not None:
            try:
                on_batch_progress(addrs_done_in_batch=done)
            except TypeError:
                on_batch_progress(done)
    if on_batch_progress is not None and batch_len == 0:
        try:
            on_batch_progress(addrs_done_in_batch=0)
        except TypeError:
            on_batch_progress(0)
    return utxos

def _prune_cached_utxos(
    cached: list[dict],
    fetch_address_utxos,
    *,
    verify_utxo_spent=None,
    fetch_addresses_utxos=None,
    on_progress=None,
    progress_label: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Entfernt aus dem Cache UTXOs, die nicht mehr unspent sind.

    Rückgabe ``(noch_unspent, live_auf_adressen)``:
    *live_auf_adressen* ist das frische ``listunspent`` der Cache-Adressen
    (ein RPC-Durchgang) — der Tip-Light-Pfad nutzt es für Prune **und**
    neue Empfänge auf denselben Adressen, ohne zweites listunspent.
    """
    if not cached:
        return [], []

    if verify_utxo_spent is not None:
        pruned = []
        for utxo in cached:
            try:
                live_value = verify_utxo_spent(utxo["txid"], int(utxo["vout"]))
            except Exception:
                continue
            if live_value is not None and live_value == utxo["value"]:
                pruned.append(utxo)
        # Kein Adress-Snapshot — Aufrufer holt listunspent nur bei Bedarf.
        return pruned, []

    addresses = {u["address"] for u in cached if u.get("address")}
    live_list = _fetch_address_batch_utxos(
        addresses,
        fetch_address_utxos,
        fetch_addresses_utxos,
        progress_label=progress_label or "Live",
        on_progress=on_progress,
    )
    live_sig: dict[str, int] = {}
    for utxo in live_list:
        try:
            key = f"{str(utxo.get('txid') or '').lower()}:{int(utxo.get('vout') or 0)}"
            live_sig[key] = int(utxo.get("value") or 0)
        except (TypeError, ValueError):
            continue

    pruned = []
    for utxo in cached:
        key = f"{str(utxo.get('txid') or '').lower()}:{int(utxo.get('vout') or 0)}"
        try:
            wert = int(utxo.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if key in live_sig and live_sig[key] == wert:
            pruned.append(utxo)
    return pruned, live_list

def _fetch_lookahead_utxos(
    xpub: str,
    scan_end_index: int,
    fetch_addresses_utxos,
    lookahead_indices: int = SALDEN_CHECK_LOOKAHEAD,
) -> list[dict]:
    """UTXOs auf den nächsten Adress-Indizes ab scan_end_index."""
    if lookahead_indices <= 0:
        return []

    addresses = derive_addresses(
        xpub,
        max_addresses=lookahead_indices * 2,
        start_index=scan_end_index,
    )
    if not addresses:
        return []

    return fetch_addresses_utxos(addresses)

def _verify_cached_utxo_set(
    xpub: str,
    cached: list[dict],
    scan_end_index: int,
    fetch_address_utxos,
    fetch_addresses_utxos,
    fetch_wallet_utxos,
    *,
    verify_utxo_spent=None,
    lookahead_indices: int = SALDEN_CHECK_LOOKAHEAD,
) -> tuple[bool, list[dict], list[dict]]:
    """
    Prüft gecachte UTXOs und die nächsten Adress-Indizes gegen die Blockchain.
    Rückgabe: (stimmt_überein, gültige_cache_utxos, lookahead_utxos)
    """
    next_end = scan_end_index + lookahead_indices - 1
    if cached:
        addresses = {u["address"] for u in cached if u.get("address")}
        print(
            f"  Prüfe {len(cached)} UTXO(s) auf {len(addresses)} Adresse(n) "
            f"+ Indizes #{scan_end_index}–#{next_end} pro Chain...",
            flush=True,
        )
        pruned, _live_snapshot = _prune_cached_utxos(
            cached,
            fetch_address_utxos,
            verify_utxo_spent=verify_utxo_spent,
            fetch_addresses_utxos=None,
        )
        from display import summarize_utxo_cache_usage

        blocks, tx_count = summarize_utxo_cache_usage(pruned)
        print(
            f"  → {blocks} Blöcke / {tx_count} Transaktionen "
            f"aus Cache geprüft und benutzt",
            flush=True,
        )
        cached_ok = _utxo_sets_match(cached, pruned)
    else:
        print(
            f"  Prüfe Indizes #{scan_end_index}–#{next_end} pro Chain "
            f"(kein UTXO im Cache)...",
            flush=True,
        )
        pruned = []
        # Leerer Cache nach partiellem Scan ist kein Nachweis für 0 UTXOs.
        cached_ok = False

    if lookahead_indices > 0:
        print(
            f"  Scanne Lookahead-Indizes #{scan_end_index}–#{next_end} …",
            flush=True,
        )

    def _lookahead_fetch(addrs: set[str] | list[str]) -> list[dict]:
        try:
            return fetch_addresses_utxos(
                addrs,
                progress_label="UTXO-Set (Lookahead)",
            )
        except TypeError:
            return fetch_addresses_utxos(addrs)

    lookahead = _fetch_lookahead_utxos(
        xpub,
        scan_end_index,
        _lookahead_fetch,
        lookahead_indices,
    )
    if lookahead_indices > 0:
        print(f"  → Lookahead: {len(lookahead)} UTXO(s)", flush=True)
    return cached_ok and not lookahead, pruned, lookahead

def _describe_utxo_diff(cached: list[dict], live: list[dict]) -> None:
    """Zeigt Abweichungen zwischen Cache und Live-UTXOs."""
    cached_sig = _utxo_set_signature(cached)
    live_sig = _utxo_set_signature(live)
    removed = set(cached_sig) - set(live_sig)
    added = set(live_sig) - set(cached_sig)
    changed = {
        key for key in cached_sig
        if key in live_sig and cached_sig[key] != live_sig[key]
    }
    cached_total = sum(cached_sig.values())
    live_total = sum(live_sig.values())

    print(
        f"  Cache: {len(cached_sig)} UTXO(s), {cached_total:,} sats",
        flush=True,
    )
    print(
        f"  Live:  {len(live_sig)} UTXO(s), {live_total:,} sats",
        flush=True,
    )
    if removed:
        print(f"  Nicht mehr unspent: {len(removed)} UTXO(s)", flush=True)
    if added:
        print(f"  Neu gefunden: {len(added)} UTXO(s)", flush=True)
    if changed:
        print(f"  Wert geändert: {len(changed)} UTXO(s)", flush=True)

def _fetch_address_batch_utxos(
    addresses: set[str] | list[str],
    fetch_address_utxos,
    fetch_addresses_utxos=None,
    *,
    progress_label: str | None = None,
    on_progress=None,
) -> list[dict]:
    """UTXOs für eine Adressmenge — Batch wenn möglich, sonst einzeln."""
    if not addresses:
        return []
    if fetch_addresses_utxos is not None:
        try:
            return fetch_addresses_utxos(
                addresses,
                progress_label=progress_label or "Aktualisiere",
                on_progress=on_progress,
            )
        except TypeError:
            try:
                return fetch_addresses_utxos(addresses)
            except TypeError:
                pass
    return _fetch_utxos_for_addresses(addresses, fetch_address_utxos)

