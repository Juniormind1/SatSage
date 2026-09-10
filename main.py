#!/usr/bin/env python3
"""
Multi-XPUB + Taproot Analyzer für Wasabi / Standard Wallet
Analysiert eine TxID oder unspent Wallet-Adresse und zeigt Herkunft der Sats.

Datenquelle: eigener Electrum-Server (Fulcrum/electrs), P2P-BIP-158, öffentliche Onions, Clearnet.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import threading
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Python 3.10-kompatibel (datetime.UTC erst ab 3.11)
UTC = timezone.utc

from display import abbrev_display, format_sats, format_tx_display, format_utxo_display, set_verbose
from embit.bip32 import HDKey
from embit import script

#: Adress-HRP-Netz (None = embit-Default/main). Gesetzt via set_chain_network().
_CHAIN_NETWORK = None


def _script_address(sc) -> str:
    """Bech32/Base58-Adresse im konfigurierten Chain-Netz."""
    if _CHAIN_NETWORK is None:
        return sc.address()
    return sc.address(_CHAIN_NETWORK)

from core.paths import app_dir

DEFAULT_BIP158_START_HEIGHT = 481_824  # SegWit-Aktivierung; P2P-Filter ab hier
ENV_FILE = app_dir() / ".env"
MAX_TRACE_DEPTH = 20
FULCRUM_CONNECT_TIMEOUT = 8
SANCTIONS_CLEARNET_PROBE_TIMEOUT = 4
SANCTIONS_CLEARNET_PROBE_WORKERS = 12
SANCTIONS_CLEARNET_MAX_SERVERS = 10
SANCTIONS_CLEARNET_MIN_SERVERS = 2
#: Verbindungen zum eigenen Node für den parallelen Sanktions-Scan. Ein
#: Fulcrum im LAN verträgt das mühelos; darüber hinaus bremst nicht mehr die
#: Verbindung, sondern die Auswertung.
SANCTIONS_OWN_NODE_WORKERS = 4
ELECTRUM_SERVERS_FILE = app_dir() / "electrum_servers.json"
MAX_PUBLIC_ONION_SERVERS = 10
MIN_PUBLIC_ONION_POOL = 3
PUBLIC_ONION_PROBE_WORKERS = 6
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
DEFAULT_MAX_ADDRESSES = 50
SALDEN_CHECK_LOOKAHEAD = 5
MAX_TRACE_ADDRESS_SEARCH = 500
BIP44_GAP_LIMIT = 20
UTXO_SCAN_GAP_LIMIT = 100  # Wasabi/CoinJoin: Lücken >20 zwischen genutzten Indizes
_immutable_tx_memory: dict[str, dict] = {}
_immutable_tx_lock = threading.Lock()
_xpub_address_positive_cache: set[tuple[str, str]] = set()
_xpub_address_negative_cache: set[tuple[str, str, int]] = set()

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
    print(
        f"Cache wächst — sqlite ab jetzt sinnvoll "
        f"({kind}: {n:,} Dateien unter {subdir}). "
        f"Falls das stört: GitHub-Issue an SatSage — wir prüfen die Schwelle.",
        flush=True,
    )


def set_chain_network(name: str | None) -> None:
    """Setzt das Adress-Netz aus ``NETWORK`` (main/regtest/test/signet)."""
    global _CHAIN_NETWORK
    from embit.networks import NETWORKS

    roh = (name or "").strip().lower()
    if not roh or roh in ("main", "mainnet", "bitcoin"):
        net = None
    else:
        alias = {
            "regtest": "regtest",
            "test": "test",
            "testnet": "test",
            "signet": "signet",
        }
        key = alias.get(roh, roh)
        net = NETWORKS.get(key)
    _CHAIN_NETWORK = net
    _hdkey_by_xpub.clear()
    _xpub_address_positive_cache.clear()
    _xpub_address_negative_cache.clear()

_hdkey_by_xpub: dict[str, HDKey] = {}
#: Cache-Kennung pro Deskriptor-Text (erste Adresse → Hash), damit
#: umsortierte Cosigner denselben Cache behalten.
_deskriptor_kennungen: dict[str, str] = {}
EXTERNAL_ADDRESS_CACHE_NAME = "external_addresses.json"
_external_cache_dir: Path | None = None
_external_cache_fingerprint: str = ""
_external_cache_max_index: int = 0
_known_external_addresses: set[str] = set()
_xpub_disk_negatives: dict[str, set[str]] = {}
_known_wallet_addresses: dict[str, str] = {}
_external_cache_lock = threading.Lock()

def _dump_cache_json(payload: dict | list) -> str:
    """Kompaktes JSON für Flatfile-Caches (ohne indent)."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))



def _load_dotenv(env_path: Path = ENV_FILE) -> dict[str, str]:
    """Lädt KEY=VALUE-Paare aus einer .env-Datei (ohne externe Abhängigkeit)."""
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    if values.get("NETWORK"):
        set_chain_network(values.get("NETWORK"))
    return values

def _indexed_env_values(env: dict[str, str], prefix: str) -> list[str]:
    """Liest fortlaufende PREFIX_0, PREFIX_1, … aus der .env."""
    values: list[str] = []
    for index in range(100):
        raw = env.get(f"{prefix}_{index}", "").strip()
        if not raw:
            break
        values.append(raw)
    return values


#: Hinweis, wenn Multisig-Wallets konfiguriert sind.
#:
#: Sie werden gespeichert und angezeigt, aber noch nicht abgeleitet: Für
#: wsh(sortedmulti(…)) fehlt der Adress-Encoder. Ihre Cosigner dürfen deshalb
#: nicht in den Analyse-Stack — einzeln gescannt wären sie leere Wallets, und
#: das sähe aus wie „kein Guthaben" statt „noch nicht unterstützt".
UNLESBAR_HINWEIS = (
    "Achtung: {anzahl} Wallet(s) lassen sich nicht ableiten — der Deskriptor "
    "ist unlesbar oder nutzt eine nicht unterstützte Form (aggregierte "
    "Taproot-Schlüssel, musig). Für sie werden weder Bestände noch Herkunft "
    "ermittelt."
)


def wallets_aus_env_datei(env_path: Path | None = None):
    """
    Die konfigurierten Wallets — Single-Sig wie Multisig.

    Liegt in main, damit die CLI dieselbe Quelle nutzt wie die Oberfläche.
    core.config wird erst hier importiert: Es importiert seinerseits main,
    und auf Modulebene wäre das ein Zirkelbezug.
    """
    from core.config import EnvFile, read_wallets

    return read_wallets(EnvFile.load(env_path or ENV_FILE))


def _xpubs_from_env(env: dict[str, str]) -> list[str] | None:
    """
    XPUBs aus XPUBS (whitespace-getrennt) oder XPUB_0, XPUB_1, …

    Nur noch für die alte Schreibweise zuständig; das Blockformat liest
    core.config.read_wallets. Bleibt erhalten, weil es von dort aufgerufen
    wird.
    """
    raw = env.get("XPUBS", "").strip()
    if raw:
        return raw.split()
    indexed = _indexed_env_values(env, "XPUB")
    return indexed or None


def _wallet_names_from_env(env: dict[str, str]) -> list[str] | None:
    """Wallet-Namen aus WALLET_NAMES (pipe-getrennt) oder WALLET_NAME_0, …"""
    raw = env.get("WALLET_NAMES", "").strip()
    if raw:
        return [part.strip() for part in raw.split("|") if part.strip()]
    indexed = _indexed_env_values(env, "WALLET_NAME")
    return indexed or None


def _max_addresses_per_xpub_from_env(env: dict[str, str]) -> list[int] | None:
    """Scan-Tiefe je XPUB aus MAX_ADDRESSES_PER_XPUB (pipe-getrennt)."""
    raw = env.get("MAX_ADDRESSES_PER_XPUB", "").strip()
    if not raw:
        return None
    werte: list[int] = []
    for teil in raw.split("|"):
        try:
            werte.append(int(teil.strip()))
        except ValueError:
            return None
    return werte or None


def _script_types_from_env(env: dict[str, str]) -> list[str] | None:
    """Skripttypen aus SCRIPT_TYPES (pipe-getrennt) oder SCRIPT_TYPE_0, …"""
    raw = env.get("SCRIPT_TYPES", "").strip()
    if raw:
        return [part.strip() for part in raw.split("|")]
    indexed = _indexed_env_values(env, "SCRIPT_TYPE")
    return indexed or None


def _editor_from_env() -> list[str] | None:
    """EDITOR/VISUAL aus der Umgebung (Windows: posix=False für Pfade mit Leerzeichen)."""
    import os
    import platform
    import shlex

    for key in ("EDITOR", "VISUAL"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return shlex.split(raw, posix=(platform.system() != "Windows"))
    return None


def open_env_file_in_editor(env_path: Path = ENV_FILE) -> None:
    """Öffnet .env im System-Editor (blockiert bis der Editor geschlossen wird)."""
    import os
    import platform
    import shutil
    import subprocess

    env_path = Path(env_path)
    if not env_path.is_file():
        example = env_path.parent / ".env.example"
        if example.is_file():
            env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.touch()

    target = str(env_path.resolve())

    def _wait_editor(cmd, *, shell: bool = False) -> None:
        proc = subprocess.Popen(cmd, shell=shell, cwd=env_path.parent)
        proc.wait()

    def _run_checked(cmd: list[str]) -> None:
        subprocess.run(cmd, cwd=env_path.parent, check=True)

    def _prompt_saved() -> None:
        print("Nach dem Speichern hier Enter drücken… ", end="", flush=True)
        try:
            input()
        except EOFError:
            pass

    def _run_custom_editor(editor: list[str]) -> None:
        print(f"Öffne {env_path.name} mit {editor[0]}…", flush=True)
        print("(Editor schließen = Bearbeitung beenden)", flush=True)
        try:
            _wait_editor([*editor, target])
        except OSError:
            quoted = " ".join(
                f'"{part}"' if " " in part else part for part in [*editor, target]
            )
            _wait_editor(quoted, shell=True)

    custom = _editor_from_env()
    if custom:
        _run_custom_editor(custom)
        return

    system = platform.system()
    if system == "Windows":
        notepad = (
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
        )
        print(f"Öffne {env_path.name} mit Notepad…", flush=True)
        print("(Editor schließen = Bearbeitung beenden)", flush=True)
        if notepad.is_file():
            try:
                _wait_editor([str(notepad), target])
                return
            except OSError:
                pass
        try:
            _wait_editor(f'notepad.exe "{target}"', shell=True)
            return
        except OSError:
            pass
        try:
            os.startfile(target)
            print("  → Datei mit Standard-App geöffnet.", flush=True)
            _prompt_saved()
            return
        except OSError as exc:
            raise OSError(f"Editor konnte nicht gestartet werden: {exc}") from exc

    if system == "Darwin":
        print(f"Öffne {env_path.name}…", flush=True)
        print("(Editor schließen = Bearbeitung beenden)", flush=True)
        errors: list[str] = []
        try:
            print("  → TextEdit", flush=True)
            _run_checked(["open", "-W", "-e", target])
            return
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"TextEdit: {exc}")

        code = shutil.which("code")
        if code:
            try:
                print("  → Visual Studio Code", flush=True)
                _wait_editor([code, "--wait", target])
                return
            except OSError as exc:
                errors.append(f"code: {exc}")

        nano = shutil.which("nano")
        if nano:
            try:
                print("  → nano", flush=True)
                _wait_editor([nano, target])
                return
            except OSError as exc:
                errors.append(f"nano: {exc}")

        try:
            print("  → Standard-Texteditor", flush=True)
            _run_checked(["open", "-W", "-t", target])
            return
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"open -t: {exc}")

        try:
            subprocess.run(["open", target], cwd=env_path.parent, check=True)
            print("  → Datei im Standard-Programm geöffnet.", flush=True)
            _prompt_saved()
            return
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"open: {exc}")
        raise OSError(
            "Editor konnte nicht gestartet werden: " + "; ".join(errors)
        ) from None

    editor = ["nano"]
    for candidate in ("nano", "vim", "vi"):
        found = shutil.which(candidate)
        if found:
            editor = [found]
            break
    _run_custom_editor(editor)


def _escape_for_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def launch_check_fulcrum_tor_external(project_dir: Path | None = None) -> None:
    """Startet check_fulcrum_tor.py in einem eigenen Terminalfenster."""
    import platform
    import shlex
    import subprocess
    import sys

    root = project_dir or Path(__file__).resolve().parent
    script = root / "check_fulcrum_tor.py"
    if not script.is_file():
        raise FileNotFoundError(f"{script.name} nicht gefunden")

    py = sys.executable
    if platform.system() == "Windows":
        inner = f'cd /d "{root}" && "{py}" "{script}"'
        subprocess.Popen(
            f'start "check_fulcrum_tor" cmd /k {inner}',
            shell=True,
            cwd=root,
        )
        return

    if platform.system() == "Darwin":
        shell_cmd = (
            f"cd {shlex.quote(str(root))} && "
            f"{shlex.quote(py)} {shlex.quote(str(script))}; "
            f"echo; read -r -p 'Enter zum Schliessen...'"
        )
        escaped = _escape_for_applescript(shell_cmd)
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Terminal" to activate',
                "-e",
                f'tell application "Terminal" to do script "{escaped}"',
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                detail or "Terminal konnte nicht gestartet werden (osascript)"
            )
        return

    for term_cmd in (
        ["x-terminal-emulator", "-e", py, str(script)],
        ["gnome-terminal", "--", py, str(script)],
        ["konsole", "-e", py, str(script)],
        ["xterm", "-e", py, str(script)],
    ):
        try:
            subprocess.Popen(term_cmd, cwd=root)
            return
        except OSError:
            continue
    raise RuntimeError("Kein Terminal-Emulator gefunden")





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
        _cache_disk_blocked = True
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




def _block_header_cache_path(height: int, cache_root: Path) -> Path:
    return cache_root / BLOCK_HEADER_CACHE_SUBDIR / f"{int(height)}.json"


def load_cached_block_time(height: int, cache_root: Path | None = None) -> int | None:
    """Blockzeit (Unix) für eine Höhe — unveränderlich nach Bestätigung."""
    if height <= 0:
        return None
    root = cache_root or IMMUTABLE_CACHE_DIR
    path = _block_header_cache_path(height, root)
    if not path.is_file():
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
        "cached_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
    }
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


_ESTIMATED_HEIGHT_CACHE: dict[str, int] = {}


def estimate_block_height_for_date(date_str: str) -> int:
    """
    Schätzt die Blockhöhe zum UTC-Tagesbeginn eines Datums.
    Annahme: konstante 10-Minuten-Blöcke ab Genesis (ohne Netzwerkabfrage).
    """
    from fulcrum import _parse_utc_date_timestamp

    key = date_str.strip()
    cached = _ESTIMATED_HEIGHT_CACHE.get(key)
    if cached is not None:
        return cached

    target_ts = _parse_utc_date_timestamp(key)
    if target_ts <= BITCOIN_GENESIS_TIMESTAMP:
        height = 0
    else:
        height = (target_ts - BITCOIN_GENESIS_TIMESTAMP) // BITCOIN_BLOCK_INTERVAL_SECONDS

    _ESTIMATED_HEIGHT_CACHE[key] = height
    return height


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
    if not cache_disk_write_allowed(root):
        return path
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(_dump_cache_json(payload), encoding="utf-8")
    tmp.replace(path)
    _maybe_log_sqlite_flatfile_hint(path.parent, kind="utxo_ingress")
    return path






def _resolve_utxo_ingress_address(
    entry: dict,
    cache_root: Path | None = None,
) -> str | None:
    """Adresse eines gecachten UTXO-Eintrags (Cache-Feld oder Tx-Flatfile)."""
    address = entry.get("address")
    if address:
        return str(address)

    txid = str(entry.get("txid", "")).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", txid):
        return None
    try:
        vout = int(entry.get("vout", -1))
    except (TypeError, ValueError):
        return None
    if vout < 0:
        return None

    tx = load_cached_tx(txid, cache_root)
    if not tx:
        return None
    vouts = tx.get("vout", [])
    if vout >= len(vouts):
        return None
    addrs = _extract_addresses(vouts[vout])
    if not addrs:
        return None
    return addrs[0] if len(addrs) == 1 else ", ".join(addrs)

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


def print_analyzed_utxo_ingress_report(
    cache_root: Path | None = None,
    utxo_cache_dir: Path | None = None,
    unspent_values: dict[str, int] | None = None,
) -> int:
    """Listet gespeicherte Herkunfts-Analysen zu Outputs (auch bereits ausgegebene).

    Noch unspent Outputs (laut Wallet-UTXO-Cache) werden mit ``UTXO: <Saldo>`` markiert.
    """
    entries = iter_utxo_ingress_cache_entries(cache_root)
    if not entries:
        print(
            "\nKeine gespeicherten Herkunfts-Analysen gefunden "
            f"({UTXO_INGRESS_CACHE_SUBDIR}/ im Immutable-Cache leer)."
        )
        return 0

    if unspent_values is None:
        unspent_values = load_unspent_outpoint_values(utxo_cache_dir)

    entries.sort(
        key=lambda e: (
            -(e.get("youngest_time_ts") or 0),
            str(e.get("txid", "")),
            int(e.get("vout", 0)),
        )
    )
    unique_txids = {str(e.get("txid", "")).lower() for e in entries}

    unspent_count = 0
    for entry in entries:
        try:
            key = f"{str(entry.get('txid', '')).lower()}:{int(entry.get('vout', -1))}"
        except (TypeError, ValueError):
            continue
        if key in unspent_values:
            unspent_count += 1

    print(f"\n{'=' * 85}")
    print(
        f"Herkunfts-Analysen: {len(entries)}  |  "
        f"davon unspent UTXOs: {unspent_count}  |  "
        f"verschiedene TxIDs: {len(unique_txids)}"
    )
    print(
        "  (Tx-Outputs mit gespeicherter Jüngste-Sats-Analyse — "
        "inkl. bereits ausgegebener; unspent = laut Wallet-UTXO-Cache)"
    )
    print(f"{'=' * 85}\n")

    for index, entry in enumerate(entries, start=1):
        txid = str(entry.get("txid", ""))
        vout_raw = entry.get("vout")
        youngest_time = entry.get("youngest_time") or "unbekannt"
        youngest_wallet = entry.get("youngest_wallet") or "?"
        youngest_sats = entry.get("youngest_sats")

        has_vout = False
        vout = -1
        try:
            vout = int(vout_raw)
            has_vout = vout >= 0
        except (TypeError, ValueError):
            has_vout = False

        unspent_sats: int | None = None
        if has_vout:
            unspent_sats = unspent_values.get(f"{txid.lower()}:{vout}")
            address = _resolve_utxo_ingress_address(entry, cache_root)
            out_ref = format_utxo_display(txid, vout, address=None)
            if address:
                ref_label = f"Output {out_ref}  →  {abbrev_display(address)}"
            else:
                ref_label = f"Output {out_ref}"
        else:
            ref_label = f"TxID: {abbrev_display(txid)}"

        print(f"{index:3}. {ref_label}")
        if unspent_sats is not None:
            print(f"     UTXO: {format_sats(unspent_sats)}")
        print(f"     Jüngste Sats zugegangen: {youngest_time}")
        if youngest_sats is not None:
            try:
                sats = int(youngest_sats)
                print(f"     Wallet: {youngest_wallet}    Jüngste Sats: {sats:,}")
            except (TypeError, ValueError):
                print(f"     Wallet: {youngest_wallet}")
        else:
            print(f"     Wallet: {youngest_wallet}")
        print()

    return len(entries)

def wrap_get_tx_with_immutable_cache(
    fetch_tx,
    cache_root: Path,
    source: str,
    *,
    pool=None,
):
    """
    Umschließt get_tx: Flatfile-Cache → Live-Abfrage → persistieren.

    Mit *pool* trägt die zurückgegebene Funktion zusätzlich ein Attribut
    ``prefetch(txids)``: Es lädt mehrere Transaktionen parallel in den Cache.
    Die Herkunftsanalyse holt ihre Vorgänger anschließend wie gehabt einzeln —
    nur eben aus dem warmen Cache statt über das Netz. Reihenfolge und
    Ergebnis bleiben damit unverändert; allein die Wartezeit fällt weg.

    Als Attribut und nicht als weiterer Parameter, weil das Vorladen zur
    Datenquelle gehört und nicht zur Baumlogik — sonst müsste es durch jede
    Zwischenschicht gereicht werden.
    """

    def get_tx(txid: str) -> dict:
        cached = load_cached_tx(txid, cache_root)
        if cached is not None:
            return cached
        tx = fetch_tx(txid)
        save_cached_tx(txid, tx, cache_root, source)
        return tx

    if pool is not None and len(pool) > 1:
        get_tx.prefetch = _mache_prefetch(pool, cache_root, source)
    return get_tx


def _mache_prefetch(pool, cache_root: Path, source: str):
    """
    Baut einen parallelen Vorlader für Transaktionen.

    Lädt nur, was nicht schon im Cache liegt. Fehler werden geschluckt: Das
    Vorladen ist eine Beschleunigung, kein Abruf — was hier ausfällt, holt
    der reguläre Weg gleich danach einzeln nach und meldet dort seinen Fehler.
    """
    from fulcrum import fetch_tx_fulcrum, parallel_ueber_pool

    def prefetch(txids) -> None:
        fehlend = []
        gesehen = set()
        for txid in txids:
            key = _normalize_txid(txid)
            if key in gesehen:
                continue
            gesehen.add(key)
            if load_cached_tx(key, cache_root) is None:
                fehlend.append(key)
        if len(fehlend) < 2:
            return

        def hole(client, txid: str) -> None:
            tx = fetch_tx_fulcrum(client, txid)
            save_cached_tx(txid, tx, cache_root, source)

        parallel_ueber_pool(pool, fehlend, hole)

    return prefetch


def make_cached_fulcrum_get_tx(
    client,
    cache_root: Path | None = None,
    *,
    enrich_block_info: bool = False,
):
    """Gecachter get_tx für einen Fulcrum-Client (parallel pro Worker nutzbar)."""
    from fulcrum import fetch_tx_fulcrum

    root = cache_root or IMMUTABLE_CACHE_DIR
    return wrap_get_tx_with_immutable_cache(
        lambda txid: fetch_tx_fulcrum(
            client,
            txid,
            enrich_block_info=enrich_block_info,
        ),
        root,
        "fulcrum",
    )


def _normalize_fulcrum_host(value: str) -> str:
    """Host aus .env/CLI: ohne Schema, ohne Port (ausser .onion)."""
    raw = value.strip()
    for prefix in ("https://", "http://"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    # user:pass@host oder user@host (Start9/Copy-Paste)
    if "@" in raw:
        raw = raw.rsplit("@", 1)[-1]
    if ":" in raw and not raw.endswith(".onion"):
        host, port_str = raw.rsplit(":", 1)
        if port_str.isdigit():
            return host
    return raw


def _parse_tor_proxy(env: dict[str, str]) -> tuple[str, int]:
    raw = env.get("FULCRUM_TOR_PROXY") or env.get("TOR_PROXY") or "127.0.0.1:9050"
    value = raw.strip()
    if ":" in value:
        host, port_str = value.rsplit(":", 1)
        if port_str.isdigit():
            return host, int(port_str)
    return value, 9050


def _require_tor_proxy(env: dict[str, str]) -> tuple[str, int]:
    from core.jobs import aktueller_zwischenstand
    from core.tor import TOR_BROWSER_DOWNLOAD, TorFehler, stelle_tor_socks_bereit

    configured = _parse_tor_proxy(env)

    def _tor_log(meldung: str) -> None:
        print(f"  {meldung}", flush=True)
        stand = aktueller_zwischenstand()
        if stand is not None:
            stand.phase(meldung)

    try:
        return stelle_tor_socks_bereit(
            configured,
            env=env,
            log=_tor_log,
        )
    except TorFehler as exc:
        print(f"  {exc}", flush=True)
        print(f"     {TOR_BROWSER_DOWNLOAD}", flush=True)
        raise SystemExit(
            "Tor-Proxy nicht erreichbar — Binary fehlt oder Autostart aus"
        ) from exc


def resolve_verbose_from_env(env: dict[str, str], default: bool = False) -> bool:
    return _parse_env_bool(env.get("VERBOSE"), default=default)


def resolve_wallets_beim_start_aktualisieren(
    env: dict[str, str],
    default: bool = False,
) -> bool:
    """
    „Wallets immer aktuell halten“ — opt-in, Vorgabe aus.

    Env: ``WALLETS_IMMER_AKTUELL`` oder legacy ``WALLETS_BEIM_START_AKTUALISIEREN``.

    Bei ja: Tip-Nachzug beim Start **und** Dauer-Watch über eigenen Electrs
    (scripthash.subscribe). Kein Fullscan.
    """
    raw = env.get("WALLETS_IMMER_AKTUELL")
    if raw is None or not str(raw).strip():
        raw = env.get("WALLETS_BEIM_START_AKTUALISIEREN")
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "ja", "yes", "on")


def _parse_env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no")


def _env_port(env: dict[str, str], key: str, default: int = 50002) -> int:
    """
    Portnummer aus der .env — leere oder unlesbare Werte ergeben *default*.

    Eine leergeräumte Zeile (`FULCRUM_PORT=`) ist ein völlig normaler
    Zwischenzustand beim Bearbeiten der .env und darf keine Abfrage mit
    einem ValueError abbrechen.
    """
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _default_fulcrum_port(args, env: dict[str, str]) -> int:
    if getattr(args, "fulcrum_port", None):
        return int(args.fulcrum_port)
    if env.get("FULCRUM_PORT"):
        return int(env["FULCRUM_PORT"])
    return 50002


def _default_fulcrum_ssl(args, env: dict[str, str]) -> bool:
    if getattr(args, "fulcrum_no_ssl", False):
        return False
    return _parse_env_bool(env.get("FULCRUM_SSL"), default=True)


def _resolve_own_lan_endpoint(
    args,
    env: dict[str, str],
) -> tuple[str, int, bool] | None:
    """LAN-Fulcrum nur bei explizitem FULCRUM_HOST / --fulcrum-host / --rpchost.

    NODE_IP / RPCHOST sind Bitcoin-Core-RPC und werden hier bewusst nicht
    als Fulcrum-Fallback verwendet (eigener Fulcrum oft nur über Tor).
    """
    host_raw = (
        getattr(args, "fulcrum_host", None)
        or args.rpchost
        or env.get("FULCRUM_HOST")
    )
    if not host_raw:
        return None
    host = _normalize_fulcrum_host(host_raw)
    if host.endswith(".onion"):
        return None
    return host, _default_fulcrum_port(args, env), _default_fulcrum_ssl(args, env)


def _resolve_own_tor_endpoint(
    args,
    env: dict[str, str],
) -> tuple[str, int, bool] | None:
    host_raw = env.get("FULCRUM_TOR")
    if not host_raw:
        return None
    host = _normalize_fulcrum_host(host_raw)
    if not host.endswith(".onion"):
        return None
    port_raw = env.get("FULCRUM_TOR_PORT", "").strip()
    port = int(port_raw) if port_raw else _default_fulcrum_port(args, env)
    ssl_raw = env.get("FULCRUM_TOR_SSL", "").strip()
    if ssl_raw:
        use_ssl = _parse_env_bool(ssl_raw, default=True)
    else:
        use_ssl = _default_fulcrum_ssl(args, env)
    return host, port, use_ssl


def _load_public_onion_endpoints(
    args,
    env: dict[str, str],
) -> list[tuple[int, str, int, bool]]:
    """FULCRUM_TOR_0…9 aus .env; Rückgabe: (index, host, port, use_ssl)."""
    default_port = _default_fulcrum_port(args, env)
    default_ssl = _default_fulcrum_ssl(args, env)
    endpoints: list[tuple[int, str, int, bool]] = []
    for index in range(MAX_PUBLIC_ONION_SERVERS):
        host_raw = env.get(f"FULCRUM_TOR_{index}")
        if not host_raw:
            continue
        host = _normalize_fulcrum_host(host_raw)
        port_raw = env.get(f"FULCRUM_PORT_{index}")
        port = int(port_raw) if port_raw else default_port
        ssl_raw = env.get(f"FULCRUM_SSL_{index}")
        use_ssl = _parse_env_bool(ssl_raw, default_ssl) if ssl_raw else default_ssl
        endpoints.append((index, host, port, use_ssl))
    return endpoints


def _format_fulcrum_route(use_ssl: bool, tor_proxy: tuple[str, int] | None) -> str:
    route = "SSL" if use_ssl else "TCP"
    if tor_proxy:
        route += f", via Tor {tor_proxy[0]}:{tor_proxy[1]}"
    return route


def _probe_public_onion_endpoint(
    index: int,
    host: str,
    port: int,
    use_ssl: bool,
    tor_proxy: tuple[str, int],
) -> tuple[int, object | None, str | None]:
    from fulcrum import FULCRUM_ONION_TIMEOUT, connect_fulcrum

    client, error = connect_fulcrum(
        host,
        port,
        use_ssl=use_ssl,
        timeout=FULCRUM_ONION_TIMEOUT,
        tor_proxy=tor_proxy,
        require_listunspent=True,
    )
    return index, client, error


def connection_error_hint(error: str | None, use_ssl: bool) -> str | None:
    """
    Übersetzt typische Verbindungsfehler in einen umsetzbaren Hinweis.

    Ein Protokoll-Mismatch sieht sonst aus wie ein reines Erreichbarkeits-
    problem: Wer FULCRUM_SSL=true gegen einen Node ohne TLS stellt, sieht nur
    „nicht erreichbar" und sucht an der falschen Stelle.
    """
    if not error:
        return None
    text = str(error).lower()

    if use_ssl and "wrong version number" in text:
        return (
            "TLS-Handshake fehlgeschlagen — der Port spricht vermutlich kein SSL. "
            "FULCRUM_SSL=false in .env setzen oder --fulcrum-no-ssl verwenden."
        )
    if use_ssl and "certificate verify failed" in text:
        return (
            "Zertifikat nicht überprüfbar — bei öffentlichen Hosts prüft SatSage "
            "streng. Heimnetz/LAN bleibt ohne CA-Prüfung; für öffentliche "
            "Self-Signed-Ziele: SATSAGE_TLS_INSECURE=1."
        )
    if not use_ssl and ("unexpected eof" in text or "not enough data" in text):
        return (
            "Verbindung ohne TLS abgebrochen — der Port erwartet vermutlich SSL. "
            "FULCRUM_SSL=true in .env setzen."
        )
    if "connection refused" in text:
        return "Port geschlossen — läuft Fulcrum, und stimmt FULCRUM_PORT?"
    return None


def _print_connection_error(prefix: str, error: str | None, use_ssl: bool) -> None:
    """Meldet einen Verbindungsfehler samt Hinweis, falls einer ableitbar ist."""
    print(f"{prefix}nicht erreichbar: {error}", flush=True)
    hint = connection_error_hint(error, use_ssl)
    if hint:
        print(f"     ↳ {hint}", flush=True)


def _print_public_onion_probe_result(
    index: int,
    host: str,
    port: int,
    use_ssl: bool,
    tor_proxy: tuple[str, int],
    client: object | None,
    error: str | None,
) -> None:
    route = _format_fulcrum_route(use_ssl, tor_proxy)
    label = f"[{index}] öffentlicher Server"
    target = f"{label}: {host}:{port} ({route})"
    if client:
        print(f"  → {target} — erreichbar", flush=True)
        return
    if error and "listunspent" in error:
        print(f"  → {target} — ungeeignet: {error}", flush=True)
    else:
        _print_connection_error(f"  → {target} — ", error, use_ssl)


def _try_fulcrum_endpoint(
    label: str,
    host: str,
    port: int,
    use_ssl: bool,
    tor_proxy: tuple[str, int] | None,
):
    route = _format_fulcrum_route(use_ssl, tor_proxy)
    print(f"Prüfe {label}: {host}:{port} ({route})...", flush=True)
    if tor_proxy:
        _index, client, error = _probe_public_onion_endpoint(
            0,
            host,
            port,
            use_ssl,
            tor_proxy,
        )
    else:
        from fulcrum import connect_fulcrum

        client, error = connect_fulcrum(
            host,
            port,
            use_ssl=use_ssl,
            timeout=FULCRUM_CONNECT_TIMEOUT,
            tor_proxy=None,
            require_listunspent=True,
        )
    if (
        not client
        and use_ssl
        and tor_proxy
        and error
        and "wrong version number" in error.lower()
    ):
        print(
            "  → TLS-Handshake fehlgeschlagen, versuche denselben Port ohne TLS…",
            flush=True,
        )
        return _try_fulcrum_endpoint(label, host, port, False, tor_proxy)
    if client:
        print(f"  → {label} erreichbar", flush=True)
        return client
    if error and "listunspent" in error:
        print(f"  → ungeeignet: {error}", flush=True)
    else:
        _print_connection_error("  → ", error, use_ssl)
    return None


_sanctions_clearnet_pool = None
_sanctions_clearnet_cache_key: tuple[str, str, str] | None = None

#: Offener Pool zum eigenen, privat adressierten Node (siehe
#: resolve_sanctions_preferred_pool) samt (host, port, ssl) als Schlüssel.
_sanctions_own_pool = None
_sanctions_own_cache_key: tuple[str, int, bool] | None = None


def _is_private_fulcrum_host(host: str) -> bool:
    import ipaddress

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def _sanctions_fulcrum_exclude_hosts(env: dict[str, str]) -> set[str]:
    hosts: set[str] = set()
    for key in (
        "FULCRUM_HOST",
        "NODE_IP",
        "RPCHOST",
        "FULCRUM_TOR",
        "FULCRUM_SANCTIONS_HOST",
    ):
        raw = env.get(key, "").strip()
        if raw:
            hosts.add(_normalize_fulcrum_host(raw))
    for index in range(MAX_PUBLIC_ONION_SERVERS):
        raw = env.get(f"FULCRUM_TOR_{index}", "").strip()
        if raw:
            hosts.add(_normalize_fulcrum_host(raw))
    hosts.discard("")
    return hosts


def _build_clearnet_fulcrum_targets(
    servers: dict[str, dict],
    exclude_hosts: set[str],
) -> list[tuple[str, int, bool]]:
    targets: list[tuple[str, int, bool]] = []
    for host in sorted(servers):
        if host.endswith(".onion"):
            continue
        host_norm = _normalize_fulcrum_host(host)
        if host_norm in exclude_hosts or _is_private_fulcrum_host(host_norm):
            continue
        meta = servers[host]
        if "s" in meta:
            targets.append((host_norm, int(meta["s"]), True))
        elif "t" in meta:
            targets.append((host_norm, int(meta["t"]), False))
    return targets


def _probe_clearnet_fulcrum(
    host: str,
    port: int,
    use_ssl: bool,
    timeout: int,
) -> tuple[object, float] | None:
    from fulcrum import (
        SANCTIONS_HISTORY_PROBE_HEIGHT,
        connect_fulcrum,
        supports_historical_headers,
    )

    started = time.monotonic()
    client, _error = connect_fulcrum(
        host,
        port,
        use_ssl=use_ssl,
        timeout=timeout,
        require_listunspent=True,
    )
    if not client:
        return None
    if not supports_historical_headers(client, SANCTIONS_HISTORY_PROBE_HEIGHT):
        client.close()
        return None
    latency = time.monotonic() - started
    return client, latency


def _dedupe_clearnet_fulcrum_hits(
    hits: list[tuple[object, float]],
) -> list[tuple[object, float]]:
    """Pro Host der schnellste Treffer; sortiert nach Latenz."""
    by_host: dict[str, tuple[object, float]] = {}
    for client, latency in hits:
        host = str(getattr(client, "host", ""))
        if not host:
            continue
        existing = by_host.get(host)
        if existing is None or latency < existing[1]:
            by_host[host] = (client, latency)
    return sorted(by_host.values(), key=lambda item: item[1])


def _print_sanctions_clearnet_pool(pool) -> None:
    from fulcrum import SanctionsClearnetPool

    if not isinstance(pool, SanctionsClearnetPool):
        return
    print(
        f"  → {len(pool)} Clearnet-Server für Sanktionslisten:",
        flush=True,
    )
    for index, client in enumerate(pool._clients, start=1):
        route = "SSL" if client.use_ssl else "TCP"
        print(
            f"     [{index}] {client.host}:{client.port} ({route})",
            flush=True,
        )


def resolve_sanctions_clearnet_pool(
    env: dict[str, str],
) -> tuple[object | None, bool]:
    """
    Mehrere schnelle Clearnet-Fulcrum-Server für OFAC-Listenabfragen.
    Rückgabe: (SanctionsClearnetPool oder None, aus Session-Cache).
    """
    global _sanctions_clearnet_pool, _sanctions_clearnet_cache_key

    from fulcrum import SanctionsClearnetPool

    cache_key = (
        env.get("FULCRUM_SANCTIONS_HOST", "").strip(),
        env.get("FULCRUM_SANCTIONS_PORT", "").strip(),
        env.get("FULCRUM_SANCTIONS_SSL", "").strip(),
    )
    if (
        _sanctions_clearnet_pool is not None
        and _sanctions_clearnet_cache_key == cache_key
    ):
        return _sanctions_clearnet_pool, True

    if _sanctions_clearnet_pool is not None:
        _sanctions_clearnet_pool.close()
        _sanctions_clearnet_pool = None

    configured = env.get("FULCRUM_SANCTIONS_HOST", "").strip()
    if configured:
        host = _normalize_fulcrum_host(configured)
        port = _env_port(env, "FULCRUM_SANCTIONS_PORT")
        use_ssl = _parse_env_bool(env.get("FULCRUM_SANCTIONS_SSL"), default=True)
        route = "SSL" if use_ssl else "TCP"
        print(
            f"Sanktions-Fulcrum (Clearnet, .env): {host}:{port} ({route})…",
            flush=True,
        )
        hit = _probe_clearnet_fulcrum(
            host,
            port,
            use_ssl,
            SANCTIONS_CLEARNET_PROBE_TIMEOUT,
        )
        if hit:
            client, latency = hit
            pool = SanctionsClearnetPool([client])
            print(
                f"  → {host}:{port} ({route}, {latency * 1000:.0f} ms)",
                flush=True,
            )
            _sanctions_clearnet_pool = pool
            _sanctions_clearnet_cache_key = cache_key
            return pool, False
        print(
            "  → nicht erreichbar, ohne listunspent oder ohne Block-Historie",
            flush=True,
        )

    from check_fulcrum_tor import load_electrum_servers

    try:
        servers = load_electrum_servers(ELECTRUM_SERVERS_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"  ⚠️  electrum_servers.json nicht nutzbar: {exc}", flush=True)
        return None, False

    exclude = _sanctions_fulcrum_exclude_hosts(env)
    targets = _build_clearnet_fulcrum_targets(servers, exclude)
    if not targets:
        print("  ⚠️  Keine Clearnet-Kandidaten in electrum_servers.json", flush=True)
        return None, False

    print(
        f"Suche geeignete Clearnet-Fulcrum-Server für Sanktionslisten "
        f"({len(targets)} Kandidaten, max. "
        f"{SANCTIONS_CLEARNET_PROBE_WORKERS} parallel, "
        f"bis zu {SANCTIONS_CLEARNET_MAX_SERVERS})…",
        flush=True,
    )

    hits: list[tuple[object, float]] = []
    executor = ThreadPoolExecutor(max_workers=SANCTIONS_CLEARNET_PROBE_WORKERS)
    futures = [
        executor.submit(
            _probe_clearnet_fulcrum,
            host,
            port,
            use_ssl,
            SANCTIONS_CLEARNET_PROBE_TIMEOUT,
        )
        for host, port, use_ssl in targets
    ]
    try:
        for future in as_completed(futures):
            try:
                probe = future.result()
            except Exception:
                probe = None
            if probe is None:
                continue
            client, latency = probe
            hits.append((client, latency))
            if len(_dedupe_clearnet_fulcrum_hits(hits)) >= SANCTIONS_CLEARNET_MAX_SERVERS:
                break
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    unique_hits = _dedupe_clearnet_fulcrum_hits(hits)[:SANCTIONS_CLEARNET_MAX_SERVERS]
    if not unique_hits:
        print(
            "  → kein Clearnet-Fulcrum mit listunspent gefunden",
            flush=True,
        )
        return None, False

    selected_hosts = {getattr(client, "host", "") for client, _lat in unique_hits}
    for client, _latency in hits:
        if getattr(client, "host", "") not in selected_hosts:
            client.close()

    pool = SanctionsClearnetPool([client for client, _lat in unique_hits])
    _print_sanctions_clearnet_pool(pool)
    _sanctions_clearnet_pool = pool
    _sanctions_clearnet_cache_key = cache_key
    return pool, False


#: Zusätzliche Verbindungen zum eigenen Node für den parallelen Wallet-Scan.
#:
#: Vier ist bewusst zurückhaltend: Ein Fulcrum im LAN verträgt deutlich mehr,
#: aber der Nutzen flacht schnell ab, und der Node gehört jemandem, der ihn
#: vielleicht noch für anderes braucht.
SCAN_POOL_WORKERS = 4


def _open_scan_pool(client, workers: int = SCAN_POOL_WORKERS):
    """
    Öffnet weitere Verbindungen zum selben Server für parallele Scans.

    Ein FulcrumClient hält einen Socket und verträgt keine gleichzeitigen
    Anfragen; ohne zusätzliche Verbindungen bliebe jeder Scan sequenziell.

    **Nur eigener Einzel-Client.** `RotatingFulcrumPool` (öffentliche
    Onions/Clearnet) hat keinen einzelnen Host/Port — `.host` ist nur ein
    Label. Extra-Verbindungen dorthin wären falsch; der Scan bleibt dann
    bei der einen Rotation.

    **Nicht über Tor.** Jede weitere Verbindung wäre ein eigener Circuit —
    langsam im Aufbau und unnötige Last für das Netz. Dort bleibt es beim
    einen Socket.

    Schlägt das Öffnen fehl, gibt es keinen Pool und der Scan läuft wie
    bisher. Ein langsamer Scan ist besser als gar keiner.
    """
    from fulcrum import FulcrumClient, SanctionsClearnetPool, connect_fulcrum

    if not isinstance(client, FulcrumClient) or client.tor_proxy:
        return None
    if workers < 2:
        return None

    clients = [client]
    for _ in range(workers - 1):
        weiterer, _fehler = connect_fulcrum(
            client.host,
            client.port,
            use_ssl=client.use_ssl,
            timeout=client.timeout,
        )
        if not weiterer:
            break
        clients.append(weiterer)

    if len(clients) < 2:
        return None
    return SanctionsClearnetPool(clients)


def _open_own_sanctions_pool(
    host: str,
    port: int,
    use_ssl: bool,
    workers: int,
) -> tuple[object | None, float]:
    """
    Mehrere Verbindungen zum eigenen Node als Pool.

    Der Parallel-Scan über die Listenadressen (Menü 6.2) braucht eine
    Verbindung pro Worker-Thread. Beim Clearnet-Pool kommt die aus je einem
    anderen Server; ein eigener Fulcrum im LAN verträgt die Last dagegen
    problemlos selbst, also werden mehrere Verbindungen dorthin geöffnet.

    Die erste Verbindung muss listunspent können. Die Mainnet-Historie-Sonde
    (Höhe 500k) entfällt hier — Regtest/Testnet und frische LAN-Nodes hätten
    sonst fälschlich Clearnet als Fallback.
    """
    from fulcrum import SanctionsClearnetPool, connect_fulcrum

    started = time.monotonic()
    erster, _fehler = connect_fulcrum(
        host,
        port,
        use_ssl=use_ssl,
        timeout=SANCTIONS_CLEARNET_PROBE_TIMEOUT,
        require_listunspent=True,
    )
    if not erster:
        return None, 0.0
    latency = time.monotonic() - started

    clients = [erster]
    for _ in range(max(0, workers - 1)):
        weiterer, _fehler = connect_fulcrum(
            host,
            port,
            use_ssl=use_ssl,
            timeout=SANCTIONS_CLEARNET_PROBE_TIMEOUT,
            require_listunspent=True,
        )
        if not weiterer:
            break
        clients.append(weiterer)
    return SanctionsClearnetPool(clients), latency


def resolve_sanctions_preferred_pool(env: dict[str, str]):
    """
    Fulcrum-Pool für Sanktionsabfragen.

    Reihenfolge:
    1. Eigener Server, wenn er **privat** adressiert ist (LAN, Loopback,
       Link-Local) — egal ob über FULCRUM_SANCTIONS_HOST oder FULCRUM_HOST
       konfiguriert. Gehört dem Benutzer: schnell im LAN, und die Anfragen
       nach gelisteten Fremdadressen verlassen das eigene Netz nicht.
       Der Pool bündelt mehrere Verbindungen dorthin, damit der
       Parallel-Scan auch mit eigenem Node parallel bleibt.
    2. Sonst der öffentliche Clearnet-Pool (resolve_sanctions_clearnet_pool):
       Sanktionsabfragen laufen bewusst nicht über einen öffentlich
       konfigurierten eigenen Server oder Tor, damit sie nicht mit der
       Identität des Benutzers verknüpft werden.

    Rückgabe: (pool, quelle, aus_cache). *quelle* ist "own_private",
    "clearnet_pool" oder "none"; *aus_cache* meldet einen bereits offenen
    Pool, damit Aufrufer die Statusmeldung nicht bei jedem Menüpunkt
    wiederholen.
    """
    global _sanctions_own_pool, _sanctions_own_cache_key

    kandidaten: list[tuple[str, int, bool]] = []
    configured = env.get("FULCRUM_SANCTIONS_HOST", "").strip()
    if configured:
        host = _normalize_fulcrum_host(configured)
        if _is_private_fulcrum_host(host):
            kandidaten.append((
                host,
                _env_port(env, "FULCRUM_SANCTIONS_PORT"),
                _parse_env_bool(env.get("FULCRUM_SANCTIONS_SSL"), default=True),
            ))

    own = env.get("FULCRUM_HOST", "").strip()
    if own:
        host = _normalize_fulcrum_host(own)
        if _is_private_fulcrum_host(host):
            kandidaten.append((
                host,
                _env_port(env, "FULCRUM_PORT"),
                _parse_env_bool(env.get("FULCRUM_SSL"), default=True),
            ))

    for host, port, use_ssl in kandidaten:
        # Ein einmal geöffneter Pool bleibt offen: vier Verbindungen bei
        # jedem Menüpunkt neu aufzubauen kostet mehr als es bringt.
        if _sanctions_own_pool is not None and _sanctions_own_cache_key == (
            host, port, use_ssl
        ):
            return _sanctions_own_pool, "own_private", True

        route = "SSL" if use_ssl else "TCP"
        print(
            f"Sanktions-Fulcrum (eigener Server): {host}:{port} ({route})…",
            flush=True,
        )
        pool, latency = _open_own_sanctions_pool(
            host, port, use_ssl, SANCTIONS_OWN_NODE_WORKERS
        )
        if pool is not None:
            print(
                f"  → {host}:{port} ({route}, {latency * 1000:.0f} ms, "
                f"{len(pool)} Verbindung(en))",
                flush=True,
            )
            if _sanctions_own_pool is not None:
                _sanctions_own_pool.close()
            _sanctions_own_pool = pool
            _sanctions_own_cache_key = (host, port, use_ssl)
            return pool, "own_private", False
        print("  → nicht erreichbar, falle auf Clearnet zurück", flush=True)

    pool, aus_cache = resolve_sanctions_clearnet_pool(env)
    if pool is None:
        return None, "none", False
    return pool, "clearnet_pool", aus_cache


def resolve_sanctions_preferred_client(env: dict[str, str]):
    """
    Einzelner Client aus dem bevorzugten Sanktions-Pool — für Abfragen
    ohne Parallelität (Einzel-UTXO-Prüfung, get_tx).

    Rückgabe: (client, quelle) oder (None, grund).
    """
    pool, quelle, _aus_cache = resolve_sanctions_preferred_pool(env)
    if pool is None:
        return None, quelle
    return pool.primary, quelle


def resolve_sanctions_clearnet_fulcrum(
    env: dict[str, str],
) -> tuple[object | None, bool]:
    """Kompatibilität: erster Server aus dem Sanktions-Clearnet-Pool."""
    pool, from_cache = resolve_sanctions_clearnet_pool(env)
    if pool is None:
        return None, from_cache
    return pool.primary, from_cache


def build_sanctions_fulcrum_fetchers(session) -> dict:
    """
    Fetcher für Sanktionslisten (nur OFAC-Adressen).

    Eigener privat adressierter Server (LAN/Loopback) zuerst — schnell und
    die Anfragen bleiben im eigenen Netz; sonst Clearnet-Fulcrum-Pool
    (Priorität 4), unabhängig von der Wallet-Datenquelle. In beiden Fällen
    trägt der Pool den Parallel-Scan aus Menü 6.2.
    """
    from fulcrum import fetch_address_utxos_fulcrum

    pool, quelle, aus_cache = resolve_sanctions_preferred_pool(session.env)
    if pool is None:
        print(
            "  ⚠️  Sanktionsabfragen: kein Fulcrum erreichbar",
            flush=True,
        )
        return {}

    client = pool.primary
    cache_root = resolve_immutable_cache_dir(session.args)
    fetch_address_utxos = lambda addr: fetch_address_utxos_fulcrum(client, addr)
    get_tx = make_cached_fulcrum_get_tx(client, cache_root)
    fetch_addresses_utxos_utxoset = lambda addrs, **kw: _fetch_utxos_for_addresses(
        addrs,
        fetch_address_utxos,
        **kw,
    )

    if not aus_cache:
        if quelle == "own_private":
            print(
                f"  Sanktionsabfragen über den eigenen Server (privates Netz, "
                f"{len(pool)} Verbindung(en) parallel)",
                flush=True,
            )
        elif len(pool) > 1:
            print(
                f"  Sanktionsabfragen parallel über {len(pool)} Clearnet-Server",
                flush=True,
            )
        else:
            print(
                "  Sanktionsabfragen über öffentlichen Clearnet-Server (ohne Tor)",
                flush=True,
            )

    return {
        "fulcrum": client,
        "fulcrum_pool": pool,
        "get_tx": get_tx,
        "fetch_addresses_utxos_utxoset": fetch_addresses_utxos_utxoset,
    }


def _setup_public_onion_rotation(
    args,
    env: dict[str, str],
    *,
    interactive: bool = True,
):
    from fulcrum import RotatingFulcrumPool

    endpoints = _load_public_onion_endpoints(args, env)
    if not endpoints:
        raise SystemExit(
            "Eigener Fulcrum nicht erreichbar und keine FULCRUM_TOR_0… "
            "in .env konfiguriert. "
            "Nutze check_fulcrum_tor.py --onion-list-only für Vorschläge."
        )

    tor_proxy = _require_tor_proxy(env)
    workers = min(PUBLIC_ONION_PROBE_WORKERS, len(endpoints))
    print(
        f"\nEigener Node nicht erreichbar — prüfe "
        f"{len(endpoints)} öffentliche Server (FULCRUM_TOR_0…, "
        f"max. {workers} parallel):",
        flush=True,
    )

    endpoint_by_index = {
        index: (host, port, use_ssl)
        for index, host, port, use_ssl in endpoints
    }
    reachable_by_index: dict[int, object] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _probe_public_onion_endpoint,
                index,
                host,
                port,
                use_ssl,
                tor_proxy,
            ): index
            for index, host, port, use_ssl in endpoints
        }
        for future in as_completed(futures):
            index = futures[future]
            host, port, use_ssl = endpoint_by_index[index]
            try:
                _index, client, error = future.result()
            except Exception as exc:
                client, error = None, str(exc)
            _print_public_onion_probe_result(
                index,
                host,
                port,
                use_ssl,
                tor_proxy,
                client,
                error,
            )
            if client:
                reachable_by_index[index] = client

    reachable_clients = [
        reachable_by_index[index]
        for index in sorted(reachable_by_index)
    ]

    if not reachable_clients:
        raise SystemExit(
            "Kein öffentlicher Fulcrum-Server erreichbar. "
            "Tor Browser/Proxy prüfen oder check_fulcrum_tor.py ausführen."
        )

    configured = len(endpoints)
    reachable_count = len(reachable_clients)
    if reachable_count < MIN_PUBLIC_ONION_POOL:
        print(
            f"\n⚠️  Nur {reachable_count} von {configured} Server(n) erreichbar "
            f"(empfohlen: mindestens {MIN_PUBLIC_ONION_POOL}).",
            flush=True,
        )
        print(
            "Mit wenigen Servern ist die Privatsphäre-Rotation eingeschränkt.",
            flush=True,
        )
        if interactive:
            print("Trotzdem fortfahren? [j/N]: ", end="", flush=True)
            from interact import prompt_yes_no

            if not prompt_yes_no(default_yes=False):
                for client in reachable_clients:
                    client.close()
                raise SystemExit("Abgebrochen.")

    _log_quelle(
        f"Datenquelle: öffentliche Electrum-Server "
        f"(Onion-Rotation, {reachable_count} von {configured} erreichbar)"
    )
    return RotatingFulcrumPool(reachable_clients)


#: Letzte _log_quelle-Zeile (Dedup bei Watch/Reconnect/Setup-Wiederholung).
_quelle_log_zuletzt: str = ""
_quelle_log_lock = threading.Lock()


def _log_quelle(text: str) -> None:
    """
    Eine Zeile nach stdout und in den Web-Log.

    „Datenquelle: …“ nur für die wirklich gewählte Quelle — nicht für
    fehlgeschlagene Probes der Prioritätskette.

    Identische Zeilen und erneute „Priorität…“ nach bereits gewählter Quelle
    werden unterdrückt (sonst spammt Herkunft/Wallet-Watch das Log alle paar
    Sekunden mit derselben Datenquellen-Zeile).
    """
    global _quelle_log_zuletzt
    zeile = (text or "").strip()
    if not zeile:
        return
    with _quelle_log_lock:
        if zeile == _quelle_log_zuletzt:
            return
        # Schon eine Quelle gemeldet → erneute Prioritäts-Ansage weglassen,
        # bis etwas anderes (Fehler/andere Quelle) den Stand ändert.
        if (
            zeile == "Automatische Datenquellen-Priorität…"
            and _quelle_log_zuletzt.startswith("Datenquelle:")
        ):
            return
        _quelle_log_zuletzt = zeile
    print(zeile, flush=True)
    from display import melde_zwischenstand

    melde_zwischenstand(zeile)


def _reset_quelle_log() -> None:
    """Für Tests: Dedup-Zustand leeren."""
    global _quelle_log_zuletzt
    with _quelle_log_lock:
        _quelle_log_zuletzt = ""


def _try_own_fulcrum_client(args, env: dict[str, str]):
    """Priorität 1: eigener Fulcrum (LAN, dann Tor)."""
    lan = _resolve_own_lan_endpoint(args, env)
    if lan:
        host, port, use_ssl = lan
        client = _try_fulcrum_endpoint(
            "eigener Fulcrum-Node (LAN)",
            host,
            port,
            use_ssl,
            None,
        )
        if client:
            _log_quelle(
                f"Datenquelle: eigener Electrum-Server (LAN) {host}:{port}"
            )
            return client

    tor = _resolve_own_tor_endpoint(args, env)
    if tor:
        host, port, use_ssl = tor
        tor_proxy = _require_tor_proxy(env)
        client = _try_fulcrum_endpoint(
            "eigener Fulcrum-Node (Tor)",
            host,
            port,
            use_ssl,
            tor_proxy,
        )
        if client:
            _log_quelle(
                f"Datenquelle: eigener Electrum-Server (Tor) {host}:{port}"
            )
            return client
    return None


def _try_bip158_backend(args, env: dict[str, str]):
    """Priorität 2: Compact Filter über Bitcoin-P2P (kein eigener Core)."""
    if env.get("BIP158_P2P", "1").strip() in ("0", "false", "nein", "off"):
        return None
    try:
        return _setup_bip158_client(args, env, raise_on_error=False)
    except (SystemExit, RuntimeError) as exc:
        _log_quelle(f"→ P2P-BIP-158 nicht erreichbar: {exc}")
        return None


def try_bip158_fetch_for_tip_sync(
    args,
    env: dict[str, str] | None = None,
    wallet_ctx: "WalletContext | None" = None,
    *,
    immutable_cache_dir: Path | None = None,
):
    """
    Optionaler BIP-158-``fetch_wallet_utxos`` für Tip-Nachzug.

    Unabhängig von der aktiven allgemeinen Datenquelle (Electrs/Core).
    ``None``, wenn Compact-Filter-Peers fehlen oder ``BIP158_P2P=0``.
    """
    env = env or _load_dotenv()
    backend = _try_bip158_backend(args, env)
    if backend is None:
        return None
    fetchers = _build_blockchain_fetchers(
        "bip158",
        backend,
        args,
        wallet_ctx,
        immutable_cache_dir=immutable_cache_dir,
    )
    return fetchers.get("fetch_wallet_utxos")


def _try_public_onion_fulcrum(
    args,
    env: dict[str, str],
    *,
    interactive: bool = False,
):
    """Priorität 3: öffentliche Fulcrum-Server über Tor."""
    if not _load_public_onion_endpoints(args, env):
        return None
    try:
        return _setup_public_onion_rotation(args, env, interactive=interactive)
    except SystemExit as exc:
        _log_quelle(f"→ öffentliche Onion-Server nicht nutzbar: {exc}")
        return None


def _setup_public_clearnet_fulcrum(args, env: dict[str, str]):
    """Priorität 4: öffentliche Fulcrum-Server über Clearnet."""
    from fulcrum import RotatingFulcrumPool

    # Vor der Suche ansagen — sonst wiederholt der 10s-Herzschlag die
    # letzte Probe (z. B. „Onions nicht nutzbar“), während Clearnet
    # nur nach stdout schreibt.
    _log_quelle("Suche öffentliche Electrum-Server (Clearnet)…")
    pool, _from_cache = resolve_sanctions_clearnet_pool(env)
    if pool is None:
        _log_quelle("→ kein Clearnet-Electrum für Wallet-Zugriff gefunden")
        return None
    clients = [pool.client_at(worker_id) for worker_id in range(len(pool))]
    _log_quelle(
        f"Datenquelle: öffentliche Electrum-Server "
        f"(Clearnet, {len(clients)} Server)"
    )
    return RotatingFulcrumPool(clients)


def _try_data_source_priority_chain(
    args,
    env: dict[str, str],
    *,
    include_bip158: bool = True,
    interactive_onion: bool = False,
):
    """
    Automatische Datenquelle in Prioritätsreihenfolge.
    1. eigener Electrum-Server (Fulcrum/electrs), 2. P2P-BIP-158.
    Öffentliche Onions/Clearnet nur nach Bestätigung (OEFFENTLICHE_ELECTRUM).
    """
    _log_quelle("Automatische Datenquellen-Priorität…")

    client = _try_own_fulcrum_client(args, env)
    if client:
        return "fulcrum", client, None

    if include_bip158:
        backend = _try_bip158_backend(args, env)
        if backend:
            return "bip158", backend, None

    erlaubt = _oeffentliche_electrum_erlaubt(env, args)
    if not erlaubt and interactive_onion:
        print(
            "\nCompact Filter (BIP-158) haben keine Peers geliefert. "
            "Öffentliche Electrum-Server (Onion oder Clearnet) sehen die "
            "abgeleiteten Wallet-Adressen.",
            flush=True,
        )
        print("Trotzdem verbinden? [j/N]: ", end="", flush=True)
        from interact import prompt_yes_no

        if prompt_yes_no(default_yes=False):
            erlaubt = True
            if args is not None:
                args.oeffentliche_electrum = True
    if not erlaubt:
        _log_quelle(
            "Öffentliche Electrum-Server nicht genutzt (Bestätigung fehlt)."
        )
        return None

    pool = _try_public_onion_fulcrum(args, env, interactive=interactive_onion)
    if pool:
        return "fulcrum", pool, None

    pool = _setup_public_clearnet_fulcrum(args, env)
    if pool:
        return "fulcrum", pool, None

    return None


def _try_public_electrum_fuer_verlauf(
    args,
    env: dict[str, str],
    *,
    interactive_onion: bool = False,
):
    """Öffentliche Electrum-Server für Verlauf — nur nach Bestätigung."""
    erlaubt = _oeffentliche_electrum_erlaubt(env, args)
    if not erlaubt and interactive_onion:
        print(
            "\nFür den Verlaufsscan fehlt ein eigener Electrum-Server "
            "(und BIP-158 ist nicht nutzbar). Öffentliche Electrum-Server "
            "sehen die abgeleiteten Wallet-Adressen.",
            flush=True,
        )
        print("Trotzdem verbinden? [j/N]: ", end="", flush=True)
        from interact import prompt_yes_no

        if prompt_yes_no(default_yes=False):
            erlaubt = True
            if args is not None:
                args.oeffentliche_electrum = True
    if not erlaubt:
        _log_quelle(
            "Verlauf: öffentliche Electrum-Server nicht genutzt "
            "(Bestätigung fehlt)."
        )
        return None

    pool = _try_public_onion_fulcrum(args, env, interactive=interactive_onion)
    if pool:
        _log_quelle(
            "Verlauf: öffentliche Electrum-Server (Onion) — get_history "
            "(Privatsphäre mäßig)."
        )
        return "fulcrum", pool

    pool = _setup_public_clearnet_fulcrum(args, env)
    if pool:
        _log_quelle(
            "Verlauf: öffentliche Electrum-Server (Clearnet) — get_history "
            "(Privatsphäre mäßig)."
        )
        return "fulcrum", pool
    return None


def _try_verlauf_priority_chain(
    args,
    env: dict[str, str],
    *,
    include_bip158: bool = True,
    interactive_onion: bool = False,
):
    """
    Datenquelle nur für den Verlaufsscan (Historie inkl. ausgegebener Outputs).

    Reihenfolge (anders als UTXO-Bestand — Core scantxoutset liefert keinen
    Verlauf):

    1. Electrs/Fulcrum im LAN (``get_history``)
    2. Electrs/Fulcrum über Onion
    3. BIP-158 Compact Filter (Blockwalk/Cache, kein get_history)
    4. öffentliche Electrum (Onion, dann Clearnet) nach Bestätigung
    """
    _log_quelle("Verlaufsscan — eigene Datenquellen-Priorität…")

    lan = _resolve_own_lan_endpoint(args, env)
    if lan:
        host, port, use_ssl = lan
        client = _try_fulcrum_endpoint(
            "eigener Fulcrum-Node (LAN)",
            host,
            port,
            use_ssl,
            None,
        )
        if client:
            _log_quelle(
                f"Verlauf: eigener Electrum-Server (LAN) {host}:{port} "
                f"— get_history."
            )
            return "fulcrum", client

    tor = _resolve_own_tor_endpoint(args, env)
    if tor:
        host, port, use_ssl = tor
        tor_proxy = _require_tor_proxy(env)
        client = _try_fulcrum_endpoint(
            "eigener Fulcrum-Node (Tor)",
            host,
            port,
            use_ssl,
            tor_proxy,
        )
        if client:
            _log_quelle(
                f"Verlauf: eigener Electrum-Server (Tor) {host}:{port} "
                f"— get_history."
            )
            return "fulcrum", client

    if include_bip158:
        backend = _try_bip158_backend(args, env)
        if backend:
            _log_quelle(
                "Verlauf: BIP-158 Compact Filter — Electrs nicht erreichbar; "
                "Historie per Blockwalk/Cache."
            )
            return "bip158", backend

    return _try_public_electrum_fuer_verlauf(
        args, env, interactive_onion=interactive_onion,
    )


def _setup_verlauf_client(
    args,
    env: dict[str, str] | None = None,
    *,
    interactive_onion: bool = False,
):
    """
    Wählt die Datenquelle für den Verlaufsscan.

    Siehe ``_try_verlauf_priority_chain``. Nicht ``_setup_blockchain_client``:
    dessen Auto-Kette kann BIP-158 wählen und dann am fehlenden
    ``fetch_wallet_history`` scheitern.
    """
    env = env or _load_dotenv()

    if _data_source_is_explicit(args, env):
        if _wants_bip158(args, env):
            backend = _setup_bip158_client(args, env, raise_on_error=True)
            _log_quelle(
                "Verlauf: BIP-158 Compact Filter (explizit) — "
                "Historie per Blockwalk/Cache."
            )
            return "bip158", backend

        if _wants_fulcrum(args, env):
            result = _try_verlauf_priority_chain(
                args,
                env,
                include_bip158=False,
                interactive_onion=interactive_onion,
            )
            if result:
                return result[0], result[1]
            raise SystemExit(
                "Verlauf: Fulcrum/Electrs nicht erreichbar (eigener Node). "
                "Öffentliche Server nur nach Bestätigung "
                "(OEFFENTLICHE_ELECTRUM=1)."
            )
        raise SystemExit(
            "Verlauf: keine Datenquelle gewählt (--bip158 oder --rpc-only)."
        )

    result = _try_verlauf_priority_chain(
        args,
        env,
        include_bip158=True,
        interactive_onion=interactive_onion,
    )
    if result:
        return result[0], result[1]

    grund = (
        "Verlauf: keine Quelle mit Historie erreichbar "
        "(Electrs, BIP-158, öffentliche Electrum nur nach Bestätigung)."
    )
    _log_quelle(grund)
    raise SystemExit(grund)


def _oeffentliche_electrum_erlaubt(env: dict[str, str], args=None) -> bool:
    if args is not None and getattr(args, "oeffentliche_electrum", False):
        return True
    from core.source import oeffentliche_electrum_erlaubt

    return oeffentliche_electrum_erlaubt(env)


def _data_source_is_explicit(args, env: dict[str, str]) -> bool:
    """True wenn CLI oder manuelle Menüwahl die Datenquelle festlegen."""
    return bool(
        getattr(args, "bip158", False) or args.rpc_only
    )


def apply_data_source_choice(
    args,
    env: dict[str, str],
    choice: str,
    *,
    bip158_start: int | None = None,
) -> None:
    """Übernimmt die interaktive Datenquellen-Wahl in args."""
    args.bip158 = False
    args.rpc_only = False
    if choice == "bip158":
        args.bip158 = True
        if bip158_start is not None:
            args.bip158_start = bip158_start
    elif choice == "fulcrum":
        args.rpc_only = True
    else:
        raise ValueError(f"unbekannte Datenquelle: {choice}")


def _resolve_data_source(args, env: dict[str, str]) -> None:
    """Setzt args bei mehrdeutiger Quelle per interaktiver Abfrage."""
    if _data_source_is_explicit(args, env):
        return
    from interact import prompt_data_source

    choice = prompt_data_source()
    if choice is None:
        raise SystemExit("Keine Datenquelle gewählt.")
    apply_data_source_choice(args, env, choice)


def _wants_bip158(args, env: dict[str, str]) -> bool:
    """P2P-BIP-158 wenn --bip158 oder BIP158_P2P=1 (ohne 0)."""
    if getattr(args, "bip158", False):
        return True
    return _parse_env_bool(env.get("BIP158_P2P"), default=False)


def _wants_fulcrum(args, env: dict[str, str]) -> bool:
    """Fulcrum wenn --rpc-only (oder nach interaktiver Auswahl)."""
    if _wants_bip158(args, env):
        return False
    if args.rpc_only:
        return True
    return True


def _setup_bip158_client(args, env: dict[str, str], *, raise_on_error: bool = True):
    from bip158_scanner import (
        create_bip158_client_from_env,
        fetch_address_utxos_bip158,
        fetch_addresses_utxos_bip158,
        fetch_tx_p2p_mit_fallback,
        fetch_wallet_utxos_bip158,
        verify_p2p_filters,
    )
    from core.bitcoind_rpc import stelle_core_client_bereit

    if args.bip158_start is not None:
        start_height = args.bip158_start
    else:
        start_height = int(
            env.get("BIP158_START_HEIGHT", str(DEFAULT_BIP158_START_HEIGHT))
        )
    if raise_on_error:
        _log_quelle("Datenquelle: Bitcoin-P2P (BIP-158 Compact Filter)")
    else:
        _log_quelle("Prüfe P2P-BIP-158 (Compact Filter)…")
    cache = Path(getattr(args, "cache_dir", None) or UTXO_CACHE_DIR)
    client = create_bip158_client_from_env(
        env,
        start_height=start_height,
        verbose=resolve_verbose_from_env(env),
        cache_dir=cache,
    )
    try:
        tip = verify_p2p_filters(client)
        # Nach dem 1-Peer-Handshake Pool auf Scan-Ziel füllen (bis 4 / Tor 2).
        pool = client.scanner._ensure_peers()
    except RuntimeError as exc:
        if raise_on_error:
            raise SystemExit(f"P2P-BIP-158 nicht erreichbar: {exc}") from exc
        raise
    if not raise_on_error:
        _log_quelle("Datenquelle: Bitcoin-P2P (BIP-158 Compact Filter)")
    weg = "Tor" if client.scanner._tor_proxy else "Clearnet"
    n_peers = len(pool) if pool else 1
    wort = "Peer" if n_peers == 1 else "Peers"
    _log_quelle(f"→ {n_peers} Compact-Filter-{wort} über {weg}")
    tip_zeile = f"Chain-Tip: {tip:,}, BIP-158 ab Höhe {start_height:,}"
    _log_quelle(tip_zeile)

    def _bip158_fetch_wallet_utxos(
        addrs,
        xpubs=None,
        wallet=None,
        max_addr=DEFAULT_MAX_ADDRESSES,
        max_by=None,
        *,
        filter_scan=False,
        on_utxos_update=None,
    ):
        if filter_scan:
            return fetch_wallet_utxos_bip158(
                client,
                xpubs or args.xpubs,
                max_addresses=max_addr,
                max_addresses_by_xpub=max_by,
                on_utxos_update=on_utxos_update,
            )
        if addrs:
            return fetch_addresses_utxos_bip158(client, addrs)
        return fetch_wallet_utxos_bip158(
            client,
            xpubs or args.xpubs,
            max_addresses=max_addr,
            max_addresses_by_xpub=max_by,
            on_utxos_update=on_utxos_update,
        )

    # Core optional: getrawtransaction (txindex) vor P2P-getdata / Block-Fallback.
    core = None
    try:
        core = stelle_core_client_bereit(env, timeout=30.0)
        if core is not None:
            _log_quelle("→ Core-RPC für Tx-Lookup verfügbar (getrawtransaction)")
    except Exception as exc:
        _log_quelle(f"→ Core-RPC für Tx-Lookup nicht nutzbar: {exc}")
        core = None

    def _get_tx_bip158(txid: str) -> dict:
        return fetch_tx_p2p_mit_fallback(
            client,
            txid,
            core_client=core,
            on_log=_log_quelle,
        )

    return {
        "get_tx": _get_tx_bip158,
        "fetch_address_utxos": lambda addr: fetch_address_utxos_bip158(client, addr),
        "fetch_addresses_utxos": lambda addrs, **kw: fetch_addresses_utxos_bip158(
            client, addrs, **kw
        ),
        "fetch_addresses_utxos_utxoset": lambda addrs, **kw: fetch_addresses_utxos_bip158(
            client, addrs, **kw
        ),
        "verify_utxo_spent": None,
        "fetch_wallet_utxos": _bip158_fetch_wallet_utxos,
        "fulcrum": None,
        "client": client,
        "core_rpc": core,
    }


def _setup_blockchain_client(
    args,
    env: dict[str, str] | None = None,
    *,
    interactive_onion: bool = False,
):
    """
    Wählt die Datenquelle:
    - explizit (--bip158, --rpc-only oder manuelle Menüwahl)
    - sonst automatische Priorität:
      1. eigener Electrum-Server, 2. P2P-BIP-158;
      öffentliche Onions/Clearnet nur nach Bestätigung
    """
    env = env or _load_dotenv()

    if _data_source_is_explicit(args, env):
        if _wants_bip158(args, env):
            return (
                "bip158",
                _setup_bip158_client(args, env, raise_on_error=True),
            )

        if _wants_fulcrum(args, env):
            result = _try_data_source_priority_chain(
                args,
                env,
                include_bip158=False,
                interactive_onion=interactive_onion,
            )
            if result:
                return result[0], result[1]
            raise SystemExit(
                "Fulcrum nicht erreichbar (eigener Node). "
                "Öffentliche Server nur nach Bestätigung "
                "(OEFFENTLICHE_ELECTRUM=1)."
            )
        raise SystemExit("Keine Datenquelle gewählt (--bip158 oder --rpc-only).")

    result = _try_data_source_priority_chain(
        args,
        env,
        include_bip158=True,
        interactive_onion=interactive_onion,
    )
    if result:
        return result[0], result[1]

    grund = (
        "Keine Datenquelle erreichbar (eigener Electrum-Server, BIP-158). "
        "Öffentliche Electrum-Server nur nach Bestätigung."
    )
    _log_quelle(grund)
    raise SystemExit(grund)

def is_own_fulcrum_backend(fulcrum) -> bool:
    """True bei direktem FulcrumClient (eigener Node), nicht bei öffentlicher Rotation."""
    from fulcrum import FulcrumClient, RotatingFulcrumPool

    if isinstance(fulcrum, FulcrumClient):
        return True
    if isinstance(fulcrum, RotatingFulcrumPool):
        return False
    return False


def privacy_notice_for_source(
    source: str | None,
    *,
    fulcrum=None,
) -> str:
    """Privatsphäre-Hinweis zur Datenquelle (Menü-Statuszeile)."""
    if source == "bip158":
        return "Privatsphäre: hoch (P2P-Filter, keine Adressen an Peers)"
    if source in ("bitcoind", "scantxoutset"):
        return "Privatsphäre: hoch (eigener Bitcoin Core)"
    if source == "fulcrum":
        if is_own_fulcrum_backend(fulcrum):
            return "Privatsphäre: hoch"
        return "⚠ Privatsphäre: mäßig"
    return ""


def _build_blockchain_fetchers(
    source: str,
    backend,
    args,
    wallet_ctx: "WalletContext | None",
    *,
    immutable_cache_dir: Path | None = None,
):
    """Bindet get_tx / fetch_*-Funktionen an die gewählte Datenquelle."""
    cache_root = immutable_cache_dir or resolve_immutable_cache_dir(args)

    if source == "bip158":
        raw_get_tx = backend["get_tx"]
        fetch_address_utxos = backend["fetch_address_utxos"]
        max_by = {
            xpub: wallet_ctx.max_addresses_for(xpub, args.max_addresses)
            for xpub in args.xpubs
        }
        def fetch_wallet_utxos(
            addrs,
            *,
            filter_scan=False,
            max_addr=None,
            on_progress=None,
            on_utxos_update=None,
            xpubs=None,
        ):
            # Explizites max_addr (Gap-/Filter-Scan) darf die konfigurierte
            # Anzeige-Tiefe nicht wieder auf 50/2 = Index 25 stauchen.
            # *xpubs* eingrenzen: sonst scannte BIP-158 bei jedem Wallet
            # den gesamten args.xpubs-Satz und mischte die UTXOs.
            try:
                return backend["fetch_wallet_utxos"](
                    addrs,
                    xpubs=xpubs if xpubs is not None else args.xpubs,
                    wallet=wallet_ctx,
                    max_addr=max_addr if max_addr is not None else args.max_addresses,
                    max_by=None if max_addr is not None else max_by,
                    filter_scan=filter_scan,
                    on_utxos_update=on_utxos_update,
                )
            except TypeError:
                return backend["fetch_wallet_utxos"](
                    addrs,
                    xpubs=xpubs if xpubs is not None else args.xpubs,
                    wallet=wallet_ctx,
                    max_addr=max_addr if max_addr is not None else args.max_addresses,
                    max_by=None if max_addr is not None else max_by,
                    filter_scan=filter_scan,
                )
        fetch_addresses_utxos = backend.get(
            "fetch_addresses_utxos",
            lambda addrs: _fetch_utxos_for_addresses(addrs, fetch_address_utxos),
        )
        fetch_addresses_utxos_utxoset = backend.get(
            "fetch_addresses_utxos_utxoset",
            fetch_addresses_utxos,
        )
        verify_utxo_spent = backend.get("verify_utxo_spent")
        get_tx = wrap_get_tx_with_immutable_cache(raw_get_tx, cache_root, source)
        cache_dir = getattr(backend.get("client"), "cache_dir", None)

        def fetch_wallet_history(
            addrs,
            *,
            skip_addresses=None,
            on_address_done=None,
            on_progress=None,
            seed_eintraege=None,
            **_kw,
        ):
            """
            Historie über BIP-158-Blockwalk (kein Electrum get_history).

            Löst denselben Compact-Filter-Scan aus wie der UTXO-Pfad; der
            schreibt ``merke_bip158_verlauf``. Anschließend Cache lesen.
            """
            skip = {str(a) for a in (skip_addresses or [])}
            offen = [a for a in addrs if a not in skip]
            if not offen:
                seed = list(seed_eintraege or [])
                return [
                    e for e in seed
                    if e.get("address") in set(addrs)
                ]

            xpubs: list[str] = []
            gesehen: set[str] = set()
            if wallet_ctx is not None:
                for adresse in offen:
                    xpub = wallet_ctx.address_to_xpub.get(adresse)
                    if xpub and xpub not in gesehen:
                        gesehen.add(xpub)
                        xpubs.append(xpub)
            if not xpubs:
                xpubs = list(args.xpubs)

            if on_progress:
                on_progress(
                    "BIP-158 Blockwalk für Verlauf "
                    f"({len(xpubs)} Wallet(s), {len(offen)} Adressen)…",
                    sofort=True,
                )
            fetch_wallet_utxos(
                offen,
                filter_scan=True,
                xpubs=xpubs,
            )

            cache_je_xpub: dict[str, list[dict]] = {}
            if cache_dir is not None:
                for xpub in xpubs:
                    cache_je_xpub[xpub] = (
                        load_xpub_verlauf_cache(xpub, cache_dir) or []
                    )

            gesammelt: list[dict] = []
            for adresse in offen:
                xpub = None
                if wallet_ctx is not None:
                    xpub = wallet_ctx.address_to_xpub.get(adresse)
                kandidaten = (
                    cache_je_xpub.get(xpub, [])
                    if xpub
                    else [
                        e
                        for roh in cache_je_xpub.values()
                        for e in roh
                    ]
                )
                neu = [
                    e for e in kandidaten
                    if e.get("address") == adresse
                ]
                if on_address_done:
                    on_address_done(adresse, neu)
                gesammelt.extend(neu)
            return gesammelt

        return {
            "get_tx": get_tx,
            "fetch_address_utxos": fetch_address_utxos,
            "fetch_addresses_utxos": fetch_addresses_utxos,
            "fetch_addresses_utxos_utxoset": fetch_addresses_utxos_utxoset,
            "verify_utxo_spent": verify_utxo_spent,
            "fetch_wallet_utxos": fetch_wallet_utxos,
            "fetch_wallet_history": fetch_wallet_history,
            "fetch_utxos": fetch_address_utxos,
            "fulcrum": None,
            "immutable_cache_dir": cache_root,
        }

    if source == "fulcrum":
        from fulcrum import (
            fetch_address_utxos_fulcrum,
            fetch_tx_fulcrum,
            fetch_wallet_history_fulcrum,
            fetch_wallet_utxos_fulcrum,
        )

        fulcrum = backend
        # Weitere Verbindungen für den parallelen Scan. Einmal geöffnet und
        # über die Fetcher weitergereicht — nicht je Aufruf neu, das kostete
        # mehr als es einbrächte.
        scan_pool = _open_scan_pool(fulcrum)
        if scan_pool is not None and not getattr(args, "no_verbose", False):
            print(
                f"  Scan über {len(scan_pool)} parallele Verbindungen",
                flush=True,
            )
        fetch_address_utxos = lambda addr: fetch_address_utxos_fulcrum(fulcrum, addr)
        raw_get_tx = lambda txid: fetch_tx_fulcrum(fulcrum, txid)
        get_tx = wrap_get_tx_with_immutable_cache(
            raw_get_tx, cache_root, source, pool=scan_pool
        )
        fetch_addresses_utxos = lambda addrs, **kw: _fetch_utxos_for_addresses(
            addrs, fetch_address_utxos, **kw
        )
        return {
            "get_tx": get_tx,
            "fetch_address_utxos": fetch_address_utxos,
            "fetch_addresses_utxos": fetch_addresses_utxos,
            "fetch_addresses_utxos_utxoset": fetch_addresses_utxos,
            "verify_utxo_spent": None,
            "fetch_wallet_utxos": lambda addrs, *, filter_scan=False, on_progress=None, on_utxos_update=None, xpubs=None: (
                fetch_wallet_utxos_fulcrum(
                    fulcrum,
                    addrs,
                    pool=scan_pool,
                    on_progress=on_progress,
                    on_utxos_update=on_utxos_update,
                )
            ),
            "fulcrum_scan_pool": scan_pool,
            # Vollständiger Verlauf inkl. ausgegebener Outputs — nur über
            # einen Electrum-Server. Bei BIP-158 schreibt der UTXO-Scan
            # den Verlauf mit; hier bleibt der Schlüssel None.
            "fetch_wallet_history": lambda addrs, on_progress=None, **kw: (
                fetch_wallet_history_fulcrum(
                    fulcrum, addrs, on_progress=on_progress, **kw,
                )
            ),
            "fetch_utxos": fetch_address_utxos,
            "fulcrum": fulcrum,
            "immutable_cache_dir": cache_root,
        }



SCRIPT_TYPE_CHOICES = ("auto", "legacy", "nested", "segwit", "taproot")

#: Konfigurierter Skripttyp je XPUB. Global wie die übrigen Caches in diesem
#: Modul, damit auch Aufrufstellen ohne WalletContext (derive_address_at_index,
#: _address_belongs_to_xpub, consolidate.py) den gewählten Typ berücksichtigen.
_script_type_by_xpub: dict[str, str] = {}

_SCRIPT_TYPE_ALIASES = {
    "auto": "auto",
    "legacy": "legacy", "p2pkh": "legacy", "bip44": "legacy",
    "nested": "nested", "p2sh-p2wpkh": "nested", "bip49": "nested",
    "segwit": "segwit", "p2wpkh": "segwit", "bip84": "segwit", "native": "segwit",
    "taproot": "taproot", "p2tr": "taproot", "bip86": "taproot",
}


def normalize_script_type(value: str | None) -> str:
    """Vereinheitlicht Schreibweisen; alles Unbekannte wird zu 'auto'."""
    if not value:
        return "auto"
    return _SCRIPT_TYPE_ALIASES.get(value.strip().lower(), "auto")


def register_script_types(types_by_xpub: dict[str, str]) -> None:
    """Hinterlegt den konfigurierten Skripttyp je XPUB."""
    for xpub, value in types_by_xpub.items():
        _script_type_by_xpub[xpub] = normalize_script_type(value)


def script_type_for_xpub(xpub: str) -> str:
    """Konfigurierter Skripttyp eines XPUB, sonst 'auto'."""
    return _script_type_by_xpub.get(xpub, "auto")


def _encoders_for_xpub(xpub: str, script_type: str | None = None):
    """
    Wählt Adress-Encoder — bevorzugt nach konfiguriertem Skripttyp,
    sonst nach XPUB-Präfix (SLIP-132).

    SLIP-132 ist optional: Manche Wallets (u. a. Ledger Desktop) exportieren
    immer 'xpub', unabhängig vom tatsächlichen Ableitungspfad. Für 'xpub' und
    'tpub' werden deshalb alle gängigen Typen probiert, statt natives SegWit
    auszulassen — sonst finden solche Wallets keine UTXOs. Wer das nicht
    braucht, setzt den Typ ausdrücklich und spart die überflüssigen Ableitungen.
    """
    pubkey = lambda pk: script.p2pkh(pk)
    nested = lambda pk: script.p2sh(script.p2wpkh(pk))
    segwit = lambda pk: script.p2wpkh(pk)
    taproot = lambda pk: script.p2tr(pk)

    chosen = normalize_script_type(script_type or script_type_for_xpub(xpub))
    by_type = {
        "legacy": [pubkey],
        "nested": [nested],
        "segwit": [segwit],
        "taproot": [taproot],
    }
    if chosen in by_type:
        return by_type[chosen]

    prefix = xpub[:4].lower()
    mapping = {
        "ypub": [nested],
        "zpub": [segwit],
        "upub": [nested],
        "vpub": [segwit],
    }
    return mapping.get(prefix, [pubkey, nested, segwit, taproot])


def ist_deskriptor(text: str) -> bool:
    """
    Ist das ein Output-Deskriptor und kein einzelner XPUB?

    Klammern entscheiden: Ein Extended Public Key ist Base58 und enthält
    niemals welche. Damit lassen sich beide Formen in denselben Feldern
    führen, ohne sie zu verwechseln.
    """
    text = (text or "").strip()
    return "(" in text and ")" in text


def parse_deskriptor(text: str):
    """
    Liest einen Output-Deskriptor. None, wenn er nicht verwendbar ist.

    Deckt ab, was embit versteht — von ``sh(multi(…))`` über
    ``wsh(sortedmulti(…))`` bis zu Taproot mit ``multi_a`` und
    Miniscript-Policies mit Zeitschlössern (Liana). Nicht unterstützt sind
    aggregierte Taproot-Schlüssel (``musig``); dort scheitert der Parser, und
    das ist besser als eine falsche Adresse.
    """
    if not ist_deskriptor(text):
        return None
    try:
        from embit.descriptor import Descriptor

        return Descriptor.from_string(text.strip())
    except Exception:
        return None


def derive_descriptor_addresses(
    descriptor: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    start_index: int = 0,
) -> set:
    """
    Leitet Adressen aus einem Output-Deskriptor ab.

    Empfang und Change kommen aus den Zweigen des Deskriptors — bei der
    üblichen Schreibweise ``/<0;1>/*`` sind das genau zwei. Hat er nur einen
    Zweig, wird auch nur dieser abgeleitet: embit lieferte für den zweiten
    sonst stillschweigend dieselben Adressen noch einmal.

    Ohne Wildcard (``/*``) beschreibt der Deskriptor eine einzige feste
    Adresse; dann ist die Scan-Tiefe gegenstandslos.
    """
    desc = parse_deskriptor(descriptor)
    if desc is None:
        return set()

    addresses: set[str] = set()
    if not getattr(desc, "is_wildcard", True):
        try:
            addresses.add(_script_address(desc.derive(0)))
        except Exception:
            pass
        return addresses

    zweige = max(1, int(getattr(desc, "num_branches", 1) or 1))
    count_per_chain = max(1, max_addresses // max(1, zweige))
    for zweig in range(zweige):
        for i in range(start_index, start_index + count_per_chain):
            try:
                addresses.add(_script_address(desc.derive(i, branch_index=zweig)))
            except Exception:
                break
    return addresses


def derive_addresses(
    xpub: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    start_index: int = 0,
    script_type: str | None = None,
) -> set:
    """
    Leitet Adressen ab — aus einem XPUB (Bip44 + Bip49 + Bip84 + Bip86) oder
    aus einem Output-Deskriptor.

    Beide Formen laufen durch dieselbe Funktion, weil der ganze Analyse-Stack
    seine Wallets über einen Zeichenketten-Schlüssel führt. Für Multisig ist
    dieser Schlüssel der Deskriptor.
    """
    if ist_deskriptor(xpub):
        return derive_descriptor_addresses(xpub, max_addresses, start_index)

    addresses = set()

    try:
        hd = HDKey.from_string(xpub)
    except Exception:
        return addresses

    count_per_chain = max_addresses // 2
    for encoder in _encoders_for_xpub(xpub, script_type):
        for change in (0, 1):
            for i in range(start_index, start_index + count_per_chain):
                try:
                    child = hd.derive([change, i])
                    addr = _script_address(encoder(child.key))
                    addresses.add(addr)
                except Exception:
                    break

    return addresses


def _hdkey_for_xpub(xpub: str) -> HDKey | None:
    cached = _hdkey_by_xpub.get(xpub)
    if cached is not None:
        return cached
    try:
        hd = HDKey.from_string(xpub)
    except Exception:
        return None
    _hdkey_by_xpub[xpub] = hd
    return hd



def _xpub_set_fingerprint(xpubs: list[str]) -> str:
    """Stabiler Schlüssel für die aktuelle XPUB-Kombination."""
    return hashlib.sha256("\n".join(sorted(xpubs)).encode("utf-8")).hexdigest()


def _xpub_fingerprint(xpub: str) -> str:
    return hashlib.sha256(xpub.encode("utf-8")).hexdigest()


def _external_address_cache_path(cache_dir: Path) -> Path:
    return cache_dir / EXTERNAL_ADDRESS_CACHE_NAME


def init_external_address_cache(
    cache_dir: Path,
    xpubs: list[str],
    max_index: int = MAX_TRACE_ADDRESS_SEARCH,
) -> tuple[int, int, int]:
    """
    Lädt Adress-Auflösungs-Cache von Platte (extern, XPUB-Negativ, Wallet-Positiv).
    Ungültig bei anderem XPUB-Set oder kleinerem max_index als aktuell gefordert.
    """
    global _external_cache_dir, _external_cache_fingerprint
    global _external_cache_max_index, _known_external_addresses, _xpub_disk_negatives
    global _known_wallet_addresses

    fingerprint = _xpub_set_fingerprint(xpubs)
    _external_cache_dir = cache_dir
    _external_cache_fingerprint = fingerprint
    _external_cache_max_index = 0
    _known_external_addresses = set()
    _xpub_disk_negatives = {}
    _known_wallet_addresses = {}

    path = _external_address_cache_path(cache_dir)
    if not path.is_file():
        return 0, 0, 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0, 0

    if data.get("xpub_set_hash") != fingerprint:
        return 0, 0, 0

    file_max = int(data.get("max_index", 0))
    if file_max < max_index:
        return 0, 0, 0

    addresses = data.get("addresses", [])
    if not isinstance(addresses, list):
        return 0, 0, 0

    _known_external_addresses = {str(addr) for addr in addresses if addr}
    _external_cache_max_index = file_max

    xpub_negs = data.get("xpub_negatives", {})
    if isinstance(xpub_negs, dict):
        for xpub in xpubs:
            fp = _xpub_fingerprint(xpub)
            addrs = xpub_negs.get(fp, [])
            if not isinstance(addrs, list):
                continue
            bucket = {str(a) for a in addrs if a}
            if bucket:
                _xpub_disk_negatives[fp] = bucket
                for addr in bucket:
                    _xpub_address_negative_cache.add((xpub, addr, file_max))


    known = data.get("known_wallet_addresses", {})
    if isinstance(known, dict):
        _known_wallet_addresses = {
            str(addr): str(fp)
            for addr, fp in known.items()
            if addr and fp
        }

    return len(_known_external_addresses), sum(
        len(v) for v in _xpub_disk_negatives.values()
    ), len(_known_wallet_addresses)


def _is_known_external_address(
    address: str,
    xpubs: list[str],
    max_search: int,
) -> bool:
    if not address or not _known_external_addresses:
        return False
    if _xpub_set_fingerprint(xpubs) != _external_cache_fingerprint:
        return False
    if max_search > _external_cache_max_index:
        return False
    return address in _known_external_addresses


def _persist_external_address_cache() -> None:
    if _external_cache_dir is None:
        return
    if not cache_disk_write_allowed(_external_cache_dir):
        return
    _external_cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "xpub_set_hash": _external_cache_fingerprint,
        "max_index": _external_cache_max_index,
        "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "addresses": sorted(_known_external_addresses),
        "xpub_negatives": {
            fp: sorted(addrs)
            for fp, addrs in sorted(_xpub_disk_negatives.items())
            if addrs
        },
        "known_wallet_addresses": dict(sorted(_known_wallet_addresses.items())),
    }
    path = _external_address_cache_path(_external_cache_dir)
    path.write_text(_dump_cache_json(payload), encoding="utf-8")


def _mark_external_address(
    address: str,
    xpubs: list[str],
    max_search: int,
) -> None:
    global _external_cache_max_index, _known_external_addresses, _known_wallet_addresses
    if not address:
        return
    fingerprint = _xpub_set_fingerprint(xpubs)
    with _external_cache_lock:
        if fingerprint != _external_cache_fingerprint:
            return
        _known_external_addresses.add(address)
        _known_wallet_addresses.pop(address, None)
        _external_cache_max_index = max(_external_cache_max_index, max_search)
        _persist_external_address_cache()


def _remove_external_address_if_present(address: str) -> None:
    global _known_external_addresses
    with _external_cache_lock:
        if address not in _known_external_addresses:
            return
        _known_external_addresses.discard(address)
        _persist_external_address_cache()


def _mark_xpub_negative(xpub: str, address: str, max_index: int) -> None:
    global _external_cache_max_index, _xpub_disk_negatives
    if not xpub or not address:
        return
    fp = _xpub_fingerprint(xpub)
    with _external_cache_lock:
        if _external_cache_dir is None:
            return
        bucket = _xpub_disk_negatives.setdefault(fp, set())
        if address in bucket and max_index <= _external_cache_max_index:
            return
        bucket.add(address)
        _external_cache_max_index = max(_external_cache_max_index, max_index)
        _persist_external_address_cache()


def _is_known_xpub_negative(xpub: str, address: str, max_index: int) -> bool:
    if not xpub or not address:
        return False
    if max_index > _external_cache_max_index:
        return False
    return address in _xpub_disk_negatives.get(_xpub_fingerprint(xpub), set())


def _remove_xpub_negative_if_present(xpub: str, address: str) -> None:
    global _xpub_disk_negatives
    fp = _xpub_fingerprint(xpub)
    with _external_cache_lock:
        bucket = _xpub_disk_negatives.get(fp)
        if not bucket or address not in bucket:
            return
        bucket.discard(address)
        if not bucket:
            _xpub_disk_negatives.pop(fp, None)
        _persist_external_address_cache()




def _mark_wallet_address_positive(xpub: str, address: str) -> None:
    """Persistiert eine per XPUB verifizierte Wallet-Adresse (ohne API-Scan)."""
    global _known_wallet_addresses
    if not xpub or not address:
        return
    fp = _xpub_fingerprint(xpub)
    with _external_cache_lock:
        if _external_cache_dir is None:
            return
        if _known_wallet_addresses.get(address) == fp:
            return
        _known_wallet_addresses[address] = fp
        _persist_external_address_cache()


def _remove_wallet_address_positive_if_present(address: str) -> None:
    global _known_wallet_addresses
    with _external_cache_lock:
        if address not in _known_wallet_addresses:
            return
        _known_wallet_addresses.pop(address, None)
        _persist_external_address_cache()


def seed_wallet_addresses_from_resolution_cache(
    wallet: "WalletContext | None",
    xpubs: list[str],
) -> int:
    """Lädt verifizierte Wallet-Adressen aus dem Auflösungs-Cache ins Mapping."""
    if not wallet or not _known_wallet_addresses:
        return 0
    fp_to_xpub = {_xpub_fingerprint(xpub): xpub for xpub in xpubs}
    loaded = 0
    for address, fp in _known_wallet_addresses.items():
        xpub = fp_to_xpub.get(fp)
        if xpub:
            _register_wallet_address(wallet, xpub, address)
            loaded += 1
    return loaded


def _register_wallet_address(
    wallet: "WalletContext",
    xpub: str,
    address: str,
) -> None:
    """Merkt eine Adresse im Wallet-Mapping und im XPUB-Treffer-Cache."""
    label = wallet.names_by_xpub.get(xpub)
    if not label or not address:
        return
    wallet.address_to_wallet[address] = label
    wallet.address_to_xpub[address] = xpub
    _xpub_address_positive_cache.add((xpub, address))


def _address_belongs_to_xpub(xpub: str, address: str, max_index: int) -> bool:
    """Prüft, ob eine Adresse aus dem XPUB stammt (bis max_index pro Chain)."""
    if (xpub, address) in _xpub_address_positive_cache:
        return True
    neg_key = (xpub, address, max_index)
    if neg_key in _xpub_address_negative_cache:
        return False
    if _is_known_xpub_negative(xpub, address, max_index):
        _xpub_address_negative_cache.add(neg_key)
        return False

    hd = _hdkey_for_xpub(xpub)
    if hd is None:
        return False

    for encoder in _encoders_for_xpub(xpub):
        for change in (0, 1):
            for i in range(max_index):
                try:
                    child = hd.derive([change, i])
                    if _script_address(encoder(child.key)) == address:
                        _xpub_address_positive_cache.add((xpub, address))
                        return True
                except Exception:
                    break
    _xpub_address_negative_cache.add(neg_key)
    _mark_xpub_negative(xpub, address, max_index)
    return False


def _default_wallet_name(xpub: str) -> str:
    """Fallback-Bezeichnung: SHA256-Hex des XPUB-Strings."""
    return hashlib.sha256(xpub.encode()).hexdigest()


@dataclass
class WalletContext:
    """Zuordnung XPUB/Adresse → Anzeigename für Berichte."""
    xpubs: list[str]
    names_by_xpub: dict[str, str]
    address_to_wallet: dict[str, str]
    address_to_xpub: dict[str, str]
    max_addresses_by_xpub: dict[str, int]
    script_type_by_xpub: dict[str, str] = field(default_factory=dict)

    def xpub_label(self, xpub: str) -> str:
        return self.names_by_xpub.get(xpub, _default_wallet_name(xpub))

    def script_type_for(self, xpub: str) -> str:
        return self.script_type_by_xpub.get(xpub, "auto")

    def max_addresses_for(
        self,
        xpub: str,
        default: int = DEFAULT_MAX_ADDRESSES,
    ) -> int:
        return self.max_addresses_by_xpub.get(xpub, default)

    def xpub_for_address(self, address: str) -> str | None:
        return self.address_to_xpub.get(address)

    def own_label(self, address: str) -> str | None:
        return self.address_to_wallet.get(address)

    def resolve_address(
        self,
        address: str,
        max_search: int = MAX_TRACE_ADDRESS_SEARCH,
    ) -> str | None:
        """
        Ordnet eine Adresse einem Wallet zu.
        Nutzt den Scan-Cache; bei Bedarf erweiterte XPUB-Suche für die Trace-Analyse.
        """
        if not address:
            return None
        cached = self.address_to_wallet.get(address)
        if cached:
            return cached
        if _is_known_external_address(address, self.xpubs, max_search):
            return None
        for xpub in self.xpubs:
            if _address_belongs_to_xpub(xpub, address, max_search):
                _register_wallet_address(self, xpub, address)
                _mark_wallet_address_positive(xpub, address)
                _remove_external_address_if_present(address)
                _remove_xpub_negative_if_present(xpub, address)
                return self.names_by_xpub[xpub]
        _mark_external_address(address, self.xpubs, max_search)
        return None

    def is_own_address(self, address: str) -> bool:
        return self.resolve_address(address) is not None

    def own_labels(self, addresses: list[str]) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for addr in addresses:
            label = self.resolve_address(addr)
            if label and label not in seen:
                labels.append(label)
                seen.add(label)
        return labels

    def format_addresses(self, addresses: list[str]) -> str:
        """Eigene Adressen als Wallet-Namen, sonst Rohadresse."""
        if not addresses:
            return "?"
        parts: list[str] = []
        for addr in addresses:
            label = self.resolve_address(addr)
            parts.append(label if label else abbrev_display(addr))
        return ", ".join(parts)

    def scope_label(self) -> str:
        names = [self.xpub_label(x) for x in self.xpubs]
        if len(names) == 1:
            return names[0]
        return " + ".join(names)


def _max_addresses_for_xpub(
    xpub: str,
    wallet: WalletContext | None = None,
    default: int = DEFAULT_MAX_ADDRESSES,
) -> int:
    if wallet:
        return wallet.max_addresses_for(xpub, default)
    return default


def build_wallet_context(
    xpubs: list[str],
    wallet_names: list[str] | None = None,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    max_addresses_per_xpub: list[int] | None = None,
    script_types: list[str] | None = None,
) -> WalletContext:
    """Baut Namenszuordnung aus XPUBs und optionalen CLI-Namen."""
    names_by_xpub: dict[str, str] = {}
    max_by_xpub: dict[str, int] = {}
    type_by_xpub: dict[str, str] = {}
    for index, xpub in enumerate(xpubs):
        if wallet_names and index < len(wallet_names):
            names_by_xpub[xpub] = wallet_names[index]
        else:
            names_by_xpub[xpub] = _default_wallet_name(xpub)
        if max_addresses_per_xpub and index < len(max_addresses_per_xpub):
            max_by_xpub[xpub] = max_addresses_per_xpub[index]
        else:
            max_by_xpub[xpub] = max_addresses
        if script_types and index < len(script_types):
            type_by_xpub[xpub] = normalize_script_type(script_types[index])
        else:
            type_by_xpub[xpub] = "auto"

    # Vor der Ableitung registrieren: Aufrufstellen ohne WalletContext
    # (derive_address_at_index, _address_belongs_to_xpub, consolidate.py)
    # lesen den Typ aus dieser Registry.
    register_script_types(type_by_xpub)

    address_to_wallet: dict[str, str] = {}
    address_to_xpub: dict[str, str] = {}
    for xpub in xpubs:
        wallet_name = names_by_xpub[xpub]
        xpub_max = max_by_xpub[xpub]
        for addr in derive_addresses(xpub, xpub_max, script_type=type_by_xpub[xpub]):
            address_to_wallet[addr] = wallet_name
            address_to_xpub[addr] = xpub

    return WalletContext(
        xpubs=xpubs,
        names_by_xpub=names_by_xpub,
        address_to_wallet=address_to_wallet,
        address_to_xpub=address_to_xpub,
        max_addresses_by_xpub=max_by_xpub,
        script_type_by_xpub=type_by_xpub,
    )




def _seed_wallet_addresses_from_cache(
    wallet: WalletContext | None,
    cached_by_xpub: dict[str, list[dict]],
    *,
    cache_dir: Path | None = None,
    xpubs: list[str] | None = None,
) -> None:
    """UTXO- und scanned_addresses aus dem Scan-Cache ins Wallet-Mapping."""
    if not wallet:
        return
    targets = xpubs or list(cached_by_xpub.keys())
    for xpub in targets:
        if xpub not in wallet.names_by_xpub:
            continue
        for utxo in cached_by_xpub.get(xpub, []):
            addr = utxo.get("address")
            if addr:
                _register_wallet_address(wallet, xpub, str(addr))
        if cache_dir is None:
            continue
        entry = load_xpub_cache_entry(xpub, cache_dir)
        if not entry:
            continue
        for addr in entry["raw"].get("scanned_addresses", []):
            if addr:
                _register_wallet_address(wallet, xpub, str(addr))
        for utxo in entry.get("utxos", []):
            addr = utxo.get("address")
            if addr:
                _register_wallet_address(wallet, xpub, str(addr))


def seed_wallet_addresses_from_utxo_cache(
    wallet: WalletContext | None,
    xpubs: list[str],
    cache_dir: Path,
) -> None:
    """Lädt alle bekannten Wallet-Adressen aus dem UTXO-Flatfile-Cache."""
    cached_by_xpub: dict[str, list[dict]] = {}
    for xpub in xpubs:
        cached = load_xpub_utxo_cache(xpub, cache_dir)
        if cached is not None:
            cached_by_xpub[xpub] = cached
    _seed_wallet_addresses_from_cache(
        wallet,
        cached_by_xpub,
        cache_dir=cache_dir,
        xpubs=xpubs,
    )


def _merge_cached_utxos(
    xpubs: list[str],
    cached_by_xpub: dict[str, list[dict]],
    wallet: WalletContext | None = None,
    *,
    cache_dir: Path | None = None,
) -> list[dict]:
    _seed_wallet_addresses_from_cache(
        wallet,
        cached_by_xpub,
        cache_dir=cache_dir,
        xpubs=xpubs,
    )
    merged: list[dict] = []
    for xpub in xpubs:
        merged.extend(cached_by_xpub.get(xpub, []))
    return merged

def _extract_addresses(vout: dict) -> list[str]:
    """Adressen aus RPC-/Electrum-Output extrahieren."""
    if "scriptpubkey_address" in vout:
        addr = vout.get("scriptpubkey_address")
        return [addr] if addr else []

    spk = vout.get("scriptPubKey", {})
    if spk.get("address"):
        return [spk["address"]]
    return spk.get("addresses", [])


def _extract_value_sats(vout: dict) -> int:
    """Wert in Satoshis aus RPC- (float BTC) oder Esplora-Format (Satoshis)."""
    if "scriptpubkey_address" in vout or "scriptpubkey" in vout:
        return int(vout.get("value", 0))
    return int(round(float(vout.get("value", 0)) * 1e8))


def _extract_value_btc(vout: dict) -> float:
    """Wert in BTC aus RPC- (float) oder Esplora-Format (Satoshis)."""
    return _extract_value_sats(vout) / 1e8


def _tx_block_height(tx: dict) -> int | None:
    """Blockhöhe der Tx (Fulcrum verbose oder Hex-Anreicherung)."""
    status = tx.get("status", {})
    if status.get("block_height") is not None:
        return int(status["block_height"])
    if tx.get("blockheight") is not None:
        return int(tx["blockheight"])
    if tx.get("blockHeight") is not None:
        return int(tx["blockHeight"])
    return None


def _tx_block_time(tx: dict) -> int | None:
    """Unix-Zeitstempel der Tx (Electrum oder RPC)."""
    status = tx.get("status", {})
    if status.get("block_time"):
        return status["block_time"]
    if tx.get("blocktime"):
        return tx["blocktime"]
    if tx.get("time"):
        return tx["time"]
    return None


def _format_tx_time(tx: dict) -> str:
    """Datum/Uhrzeit der Tx; bei Blockhöhe auch Blocknummer anzeigen."""
    ts = _tx_block_time(tx)
    height = _tx_block_height(tx)

    if ts is None and height is None:
        return "unbekannt"
    if height is not None and height > 0 and ts is not None:
        dt = datetime.fromtimestamp(ts)
        label = dt.strftime("%d.%m.%Y %H:%M:%S")
        confirmed = tx.get("status", {}).get(
            "confirmed",
            tx.get("confirmations", 0) > 0,
        )
        block_label = f"Block {height:,}"
        if not confirmed:
            return f"{block_label} · {label} (noch unbestätigt)"
        return f"{block_label} · {label}"
    if height is not None and height > 0:
        return f"Block {height:,}"

    dt = datetime.fromtimestamp(ts)
    label = dt.strftime("%d.%m.%Y %H:%M:%S")
    confirmed = tx.get("status", {}).get("confirmed", tx.get("confirmations", 0) > 0)
    if not confirmed:
        return f"{label} (noch unbestätigt)"
    return label



def derive_address_at_index(xpub: str, change: int, index: int) -> str | None:
    """
    Leitet eine Wallet-Adresse (change, index) ab.

    Auch aus einem Deskriptor: Der Gap-Scan geht Index für Index vor und
    braucht deshalb den Einzelzugriff. Hat der Deskriptor nur einen Zweig,
    liefert *change* dort keine eigene Kette.
    """
    if ist_deskriptor(xpub):
        desc = parse_deskriptor(xpub)
        if desc is None:
            return None
        zweige = max(1, int(getattr(desc, "num_branches", 1) or 1))
        if change >= zweige:
            return None
        try:
            return _script_address(desc.derive(index, branch_index=change))
        except Exception:
            return None

    hd = _hdkey_for_xpub(xpub)
    if hd is None:
        return None
    for encoder in _encoders_for_xpub(xpub):
        try:
            child = hd.derive([change, index])
            return _script_address(encoder(child.key))
        except Exception:
            continue
    return None


def derive_receive_address_at_index(
    xpub: str,
    index: int,
) -> tuple[str, int, HDKey, object] | None:
    """Leitet die Empfangsadresse (change=0) am Index ab."""
    try:
        hd = HDKey.from_string(xpub)
    except Exception:
        return None

    for encoder in _encoders_for_xpub(xpub):
        try:
            child = hd.derive([0, index])
            sc = encoder(child.key)
            return _script_address(sc), index, child, sc
        except Exception:
            continue
    return None


def _scan_index_cap_per_chain(
    xpub: str,
    wallet: WalletContext | None,
    max_addresses: int,
) -> int:
    """Obergrenze Indizes pro Chain; Default nutzt Gap-Scan bis MAX_TRACE_ADDRESS_SEARCH."""
    configured = _max_addresses_for_xpub(xpub, wallet, max_addresses)
    if configured > DEFAULT_MAX_ADDRESSES:
        return configured // 2
    return MAX_TRACE_ADDRESS_SEARCH



def _collect_used_chain_indices_gap(
    xpub: str,
    change: int,
    max_index: int,
    gap_limit: int,
    address_has_received,
    *,
    start_index: int = 0,
    progress_label: str | None = None,
    on_progress=None,
) -> tuple[set[int], int]:
    """Gap-Walk: benutzte Indizes einer Chain (change=0/1)."""
    from display import is_list_abort_requested

    used: set[int] = set()
    gap = 0
    next_index = start_index
    for i in range(start_index, max_index):
        if is_list_abort_requested():
            break
        next_index = i + 1
        address = derive_address_at_index(xpub, change, i)
        if not address:
            break
        if address_has_received(address):
            used.add(i)
            gap = 0
        else:
            gap += 1
            if gap >= gap_limit:
                break
        if progress_label and (i - start_index + 1) % 25 == 0:
            print(f"  {progress_label} Index #{i}…", flush=True)
        if on_progress:
            on_progress(f"Gap-Scan {progress_label or ''} Index #{i}…".replace("  ", " "))
    return used, next_index


def discover_wallet_scan_addresses(
    xpub: str,
    *,
    max_index_per_chain: int,
    gap_limit: int = UTXO_SCAN_GAP_LIMIT,
    start_index: int = 0,
    fulcrum=None,
    on_progress=None,
    on_utxos_update=None,
) -> tuple[set[str], int]:
    """
    Gap-Scan (Fulcrum): Adressen mit Historie (+ Gap-Puffer).
    Rückgabe: (adressen, scan_end_index für Light-Rescan).
    """
    if fulcrum is not None:
        from fulcrum import collect_used_chain_indices_fulcrum

        from display import is_list_abort_requested

        addresses: set[str] = set()
        scan_end_index = start_index
        gesamt_utxos: list[dict] = []

        def _kette_utxos(teil: list[dict]) -> None:
            if not on_utxos_update:
                return
            # Empfang + Change teilen sich den Zwischenstand.
            nonlocal gesamt_utxos
            gesamt_utxos = _merge_utxo_lists(gesamt_utxos, teil)
            on_utxos_update(list(gesamt_utxos))

        for change, label in ((0, "Empfang"), (1, "Change")):
            if is_list_abort_requested():
                break
            print(
                f"  Gap-Scan {label}-Chain "
                f"(ab Index #{start_index}, max #{max_index_per_chain - 1})...",
                flush=True,
            )
            if on_progress:
                on_progress(f"Gap-Scan {label}-Adressen…")
            used, next_index = collect_used_chain_indices_fulcrum(
                fulcrum,
                xpub,
                change,
                max_index_per_chain,
                gap_limit,
                derive_address_at_index,
                start_index=start_index,
                on_progress=on_progress,
                on_utxos_update=_kette_utxos if on_utxos_update else None,
                kette=label,
            )
            scan_end_index = max(scan_end_index, next_index)
            indices_to_derive: set[int] = set(used)
            if used:
                last_used = max(used)
                for i in range(
                    last_used + 1,
                    min(last_used + 1 + gap_limit, max_index_per_chain),
                ):
                    indices_to_derive.add(i)
            for i in sorted(indices_to_derive):
                addr = derive_address_at_index(xpub, change, i)
                if addr:
                    addresses.add(addr)
            print(
                f"  → {label}: {len(used)} genutzte Indizes, "
                f"{len(indices_to_derive)} Adressen",
                flush=True,
            )
        return addresses, scan_end_index
    raise ValueError("fulcrum erforderlich für Gap-Scan")


def _receive_index_for_address(
    xpub: str,
    address: str,
    max_index: int,
) -> int | None:
    """Empfangs-Index (change=0) einer XPUB-Adresse, falls bekannt."""
    from consolidate import resolve_address_derivation

    derived = resolve_address_derivation(xpub, address, max_index)
    if not derived:
        return None
    change, addr_index, _, _ = derived
    return addr_index if change == 0 else None


def next_unused_receive_index(
    used_indices: set[int],
    max_index: int,
    gap_limit: int = BIP44_GAP_LIMIT,
) -> int | None:
    """Nächster Empfangs-Index nach BIP44-Gap-Limit."""
    last_used = -1
    gap = 0
    for i in range(max_index):
        if i in used_indices:
            last_used = i
            gap = 0
        else:
            gap += 1
            if gap >= gap_limit:
                break
    next_index = last_used + 1
    if next_index >= max_index:
        return None
    return next_index


def next_unused_receive_address_fulcrum(
    fulcrum,
    xpub: str,
    max_index: int | None = None,
    gap_limit: int = BIP44_GAP_LIMIT,
    wallet: WalletContext | None = None,
) -> tuple[str, int, HDKey, object] | None:
    """
    Ermittelt die nächste freie Empfangsadresse per Fulcrum (get_history).
    Rückgabe: (adresse, index, child_hdkey, script) oder None.
    """
    if max_index is None:
        max_index = MAX_TRACE_ADDRESS_SEARCH
    from fulcrum import collect_used_receive_indices_fulcrum

    used = collect_used_receive_indices_fulcrum(
        fulcrum,
        xpub,
        max_index,
        gap_limit,
        derive_receive_address_at_index,
    )
    next_index = next_unused_receive_index(used, max_index, gap_limit)
    if next_index is None:
        return None
    return derive_receive_address_at_index(xpub, next_index)


def _format_utxo_status(utxo: dict) -> str:
    """Datum/Uhrzeit, wann das UTXO erstellt (bestätigt) wurde."""
    status = utxo.get("status", {})
    return _format_tx_time({
        "status": status,
        "blocktime": status.get("block_time"),
        "blockheight": status.get("block_height"),
        "confirmations": 1 if status.get("confirmed") else 0,
    })



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


def settle_gezielte_spends_im_cache(
    xpub: str,
    cache_dir: Path,
    *,
    confirmed_spent: list[dict],
    live_auf_adressen: list[dict],
    source: str = "fulcrum",
) -> list[dict] | None:
    """
    Bestätigte Spends und frisches listunspent nur für betroffene Adressen.

    * confirmed_spent → aus UTXO-Cache, in Verlauf mit spent_*
    * live_auf_adressen → ersetzt Cache-UTXOs **dieser** Adressen
      (Change/neue Empfänge), andere Adressen unangetastet

    Kein Gap, kein Fullscan. Rückgabe: neue UTXO-Liste oder None ohne Cache.
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
    # Tip: höchste Bestätigungshöhe der Settles, falls höher
    for s in confirmed_spent:
        try:
            h = int(s.get("spent_height") or 0)
        except (TypeError, ValueError):
            h = 0
        if h > 0 and (tip_i is None or h > tip_i):
            tip_i = h

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


def ermittle_first_seen(
    xpub: str,
    addresses,
    cache_dir: Path,
    fulcrum_client=None,
    *,
    on_progress=None,
    utxos: list[dict] | None = None,
) -> dict | None:
    """
    Erhebt das Wallet-Alter — einmalig, und nur wenn es noch fehlt.

    Die älteste Transaktion eines Wallets kann sich nicht mehr ändern; steht
    sie im Cache, wird nicht erneut gefragt. Ohne Electrum-Server: aus den
    gefundenen UTXOs (BIP-158), sonst leer bis zum nächsten Electrum-Scan.

    Kostet eine Abfrage je Adresse und läuft deshalb bewusst nur dieses eine
    Mal (Fulcrum).
    """
    vorhanden = xpub_first_seen(xpub, cache_dir)
    if vorhanden:
        return vorhanden

    aus_utxo = first_seen_from_utxos(utxos)
    if aus_utxo:
        print(
            f"  → Wallet erstmals benutzt: {_first_seen_label(aus_utxo)}",
            flush=True,
        )
        return aus_utxo

    if fulcrum_client is None or not addresses:
        return None

    if on_progress:
        try:
            on_progress("Ermittle Wallet-Alter…", sofort=True)
        except TypeError:
            on_progress("Ermittle Wallet-Alter…")

    try:
        from fulcrum import first_seen_fulcrum

        ergebnis = first_seen_fulcrum(
            fulcrum_client, sorted(addresses), on_progress=on_progress
        )
    except Exception:
        return None
    if ergebnis:
        print(
            f"  → Wallet erstmals benutzt: {_first_seen_label(ergebnis)}",
            flush=True,
        )
    return ergebnis


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
    payload = {
        "eintraege": eintraege,
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


def resolve_wallet_verlauf(
    xpubs: list[str],
    fetch_wallet_history,
    cache_dir: Path,
    wallet: "WalletContext | None" = None,
) -> dict[str, list[dict]]:
    """
    Erhebt den Verlauf je XPUB und legt ihn ab.

    Je XPUB werden nur dessen eigene Adressen abgefragt. Nach jeder Adresse
    Zwischenstand speichern; nach Abbruch/Timeout setzt der nächste Lauf bei
    denselben geplanten Adressen fort.
    """
    ergebnis: dict[str, list[dict]] = {}
    for xpub in xpubs:
        adressen = sorted({
            adresse
            for adresse, zugehoerig in (wallet.address_to_xpub if wallet else {}).items()
            if zugehoerig == xpub
        })
        if not adressen:
            ergebnis[xpub] = load_xpub_verlauf_cache(xpub, cache_dir) or []
            continue

        bisher = load_xpub_verlauf_cache(xpub, cache_dir) or []
        meta = load_xpub_verlauf_scan_meta(xpub, cache_dir)
        geplant = list(adressen)
        skip: list[str] = []
        if (
            meta.get("incomplete")
            and meta.get("planned_addresses") == geplant
            and meta.get("scanned_addresses")
        ):
            skip = list(meta["scanned_addresses"])

        stand = {
            "eintraege": list(bisher),
            "scanned": set(skip),
        }

        def on_address_done(address: str, neu: list[dict], *, _xpub=xpub) -> None:
            stand["eintraege"] = _merge_verlauf_eintraege(stand["eintraege"], neu)
            stand["scanned"].add(address)
            save_xpub_verlauf_cache(
                _xpub,
                stand["eintraege"],
                cache_dir,
                scanned_addresses=sorted(stand["scanned"]),
                planned_addresses=geplant,
                incomplete=True,
            )

        fehler: BaseException | None = None
        try:
            try:
                fetch_wallet_history(
                    adressen,
                    skip_addresses=skip,
                    on_address_done=on_address_done,
                    seed_eintraege=bisher,
                )
            except TypeError:
                # Älterer Fetcher ohne Resume-Argumente.
                roh = fetch_wallet_history(adressen)
                stand["eintraege"] = _merge_verlauf_eintraege(bisher, roh or [])
                stand["scanned"] = set(geplant)
        except BaseException as exc:
            # Timeout/Abbruch: Zwischenstand aus on_address_done bleibt,
            # incomplete=True — nächster Lauf setzt fort.
            fehler = exc
            if not stand["scanned"]:
                raise

        from display import is_list_abort_requested

        fertig = (
            fehler is None
            and (not is_list_abort_requested())
            and set(geplant) <= stand["scanned"]
        )
        save_xpub_verlauf_cache(
            xpub,
            stand["eintraege"],
            cache_dir,
            scanned_addresses=[] if fertig else sorted(stand["scanned"]),
            planned_addresses=geplant,
            incomplete=not fertig,
        )
        if fehler is not None:
            raise fehler
        ergebnis[xpub] = stand["eintraege"]
    return ergebnis


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


def save_xpub_utxo_cache(
    xpub: str,
    utxos: list[dict],
    cache_dir: Path,
    source: str,
    scan_end_index: int | None = None,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    first_seen: dict | None = None,
    scan_tip_height: int | None = None,
) -> Path:
    """
    Speichert UTXOs eines XPUB als JSON-Flatfile.

    *first_seen* hält fest, wann das Wallet zum ersten Mal benutzt wurde
    (``{"height": …, "time_ts": …}``). Fehlt der Wert, wird ein bereits
    gespeicherter übernommen — er wird einmal erhoben und ändert sich nie
    wieder, ein Rescan darf ihn also nicht verlieren.

    *scan_tip_height* (BIP-158): bis zu welcher Chain-Höhe der Filter-Scan
    ging. Fehlt der Wert, bleibt ein bereits gespeicherter Tip erhalten.
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
    payload = {
        "xpub": xpub,
        "xpub_prefix": xpub[:25],
        "scanned_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "scan_end_index": scan_end_index,
        "max_addresses": max_addresses,
        "utxo_count": len(utxos),
        "utxos": utxos,
    }
    if first_seen:
        payload["first_seen_height"] = first_seen.get("height")
        payload["first_seen_ts"] = first_seen.get("time_ts")
    if scan_tip_height is not None:
        payload["scan_tip_height"] = int(scan_tip_height)
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
    First-seen wird nicht neu erhoben — nur übernommen, falls schon da.
    """
    entry = load_xpub_cache_entry(xpub, cache_dir)
    scan_end = int(entry["scan_end_index"] or 0) if entry else 0
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


def _supplement_cache_address(
    xpub: str,
    address: str,
    fetch_address_utxos,
    cache_dir: Path,
    source: str,
    wallet: WalletContext | None = None,
) -> None:
    """Scannt genau eine Adresse und ergänzt den Cache — kein Bereichs-Scan."""
    entry = load_xpub_cache_entry(xpub, cache_dir)
    if _address_known_in_cache(entry, address):
        return

    label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
    print(f"  Ziel-Scan {label}: {abbrev_display(address)}", flush=True)
    try:
        live_utxos = fetch_address_utxos(address)
    except Exception as exc:
        print(f"  ⚠️  Ziel-Scan fehlgeschlagen: {exc}", flush=True)
        return

    for utxo in live_utxos:
        utxo["address"] = address

    cached = list(entry["utxos"]) if entry else []
    merged = _merge_utxo_lists(cached, live_utxos)
    _mark_address_scanned(xpub, address, cache_dir, source, merged)

    if wallet:
        wallet.address_to_wallet[address] = wallet.names_by_xpub[xpub]
        wallet.address_to_xpub[address] = xpub

    if live_utxos:
        print(
            f"  → {len(live_utxos)} UTXO(s) für {abbrev_display(address)} im Cache ergänzt",
            flush=True,
        )
    else:
        print(f"  → Keine unspent UTXOs auf {abbrev_display(address)} (im Cache vermerkt)", flush=True)


def _ensure_address_cached(
    address: str,
    wallet: WalletContext,
    cache_dir: Path | None,
    fetch_address_utxos,
    source: str,
) -> None:
    """
    Wallet-Zuordnung lokal per XPUB; API nur für diese eine Adresse,
    und nur wenn sie noch nicht im Cache bekannt ist.
    """
    if not wallet.resolve_address(address):
        return
    xpub = wallet.xpub_for_address(address)
    if not xpub or not cache_dir or not fetch_address_utxos:
        return
    _supplement_cache_address(
        xpub, address, fetch_address_utxos, cache_dir, source, wallet
    )


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
) -> list[dict]:
    """Entfernt aus dem Cache UTXOs, die nicht mehr unspent sind."""
    if not cached:
        return []

    if verify_utxo_spent is not None:
        pruned = []
        for utxo in cached:
            try:
                live_value = verify_utxo_spent(utxo["txid"], int(utxo["vout"]))
            except Exception:
                continue
            if live_value is not None and live_value == utxo["value"]:
                pruned.append(utxo)
        return pruned

    live_sig: dict[str, int] = {}
    addresses = {u["address"] for u in cached if u.get("address")}
    for address in sorted(addresses):
        try:
            for utxo in fetch_address_utxos(address):
                live_sig[f"{utxo['txid']}:{utxo['vout']}"] = utxo["value"]
        except Exception:
            continue

    pruned = []
    for utxo in cached:
        key = f"{utxo['txid']}:{utxo['vout']}"
        if key in live_sig and live_sig[key] == utxo["value"]:
            pruned.append(utxo)
    return pruned


def _mempool_pending_nach_prune(
    xpub: str,
    cached: list[dict],
    pruned: list[dict],
    *,
    fulcrum=None,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
) -> list[dict]:
    """
    Nach Light-Prune: Mempool-Spends behalten und eigene Empfänge anhängen.

    ``listunspent`` sieht unbestätigte Ausgaben nicht — ohne diesen Schritt
    verschwinden Self-Tx/Change still aus dem Cache (15→14), obwohl die Tx
    nur im Mempool liegt. Zusätzlich: bereits im Verlauf als
    ``spent_pending`` vermerkte Outpoints erneut prüfen (Recovery).
    """
    if fulcrum is None:
        return pruned

    live_keys = {
        f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        for u in pruned
    }
    fehlt = [
        u for u in cached
        if f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        not in live_keys
    ]
    # Recovery: Pending aus Verlauf, falls Light sie schon entfernt hatte.
    if cache_dir is not None:
        try:
            verlauf = load_xpub_verlauf_cache(xpub, cache_dir) or []
        except Exception:
            verlauf = []
        gesehen_f = {
            f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
            for u in fehlt
        }
        for e in verlauf:
            if not e.get("spent_pending"):
                continue
            key = (
                f"{str(e.get('txid') or '').lower()}:"
                f"{int(e.get('vout') or 0)}"
            )
            if key in live_keys or key in gesehen_f:
                continue
            gesehen_f.add(key)
            fehlt.append({
                "txid": e.get("txid"),
                "vout": e.get("vout"),
                "value": int(e.get("value") or 0),
                "address": e.get("address"),
                "status": e.get("status") or {},
            })


    try:
        from fulcrum import eigene_mempool_empfaenge, klassifiziere_utxo_spends
    except Exception:
        return pruned

    # Auch andere Wallet-Caches liefern Inputs für Cross-Wallet-Empfänge.
    kandidaten = list(fehlt)
    gesehen_k = {f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}" for u in kandidaten}
    if wallet is not None and cache_dir is not None:
        for anderes in wallet.xpubs:
            if anderes == xpub:
                continue
            try:
                eintrag = load_xpub_cache_entry(anderes, cache_dir)
                andere_utxos = (eintrag or {}).get("utxos") or []
            except Exception:
                andere_utxos = []
            for u in andere_utxos:
                key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
                if key not in gesehen_k:
                    gesehen_k.add(key)
                    kandidaten.append(u)
            try:
                verlauf = load_xpub_verlauf_cache(anderes, cache_dir) or []
            except Exception:
                verlauf = []
            for e in verlauf:
                if not e.get("spent_pending"):
                    continue
                key = f"{str(e.get('txid') or '').lower()}:{int(e.get('vout') or 0)}"
                if key in gesehen_k:
                    continue
                gesehen_k.add(key)
                kandidaten.append({"txid": e.get("txid"), "vout": e.get("vout"), "value": int(e.get("value") or 0), "address": e.get("address"), "status": e.get("status") or {}})
    if not kandidaten:
        return pruned
    try:
        alle_pending, alle_confirmed, _live = klassifiziere_utxo_spends(fulcrum, kandidaten)
    except Exception:
        return pruned

    ziel_keys = {f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}" for u in fehlt}
    pending = [p for p in alle_pending if not xpub or f"{str(p.get('txid') or '').lower()}:{int(p.get('vout') or 0)}" in ziel_keys]
    confirmed = [c for c in alle_confirmed if not xpub or f"{str(c.get('txid') or '').lower()}:{int(c.get('vout') or 0)}" in ziel_keys]
    # Bestätigte Spends: Verlauf merken, UTXO bleibt draußen.
    if confirmed and cache_dir is not None:
        try:
            merke_bip158_verlauf(
                xpub,
                [
                    {
                        "txid": str(c.get("txid") or "").lower(),
                        "vout": int(c.get("vout") or 0),
                        "address": c.get("address"),
                        "value": int(c.get("value") or 0),
                        "spent": True,
                        "spent_pending": False,
                        "spent_txid": c.get("spent_txid") or "",
                        "spent_height": int(c.get("spent_height") or 0),
                        "spent_time_ts": c.get("spent_time_ts"),
                        "status": c.get("status") or {},
                    }
                    for c in confirmed
                ],
                cache_dir,
            )
        except Exception:
            pass


    by_key = {
        f"{str(p.get('txid') or '').lower()}:{int(p.get('vout') or 0)}": p
        for p in pending
    }
    result = list(pruned)
    result_keys = set(live_keys)
    for u in fehlt:
        key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        p = by_key.get(key)
        if p is None:
            continue
        neu = dict(u)
        neu["spending_pending"] = True
        neu["spent_txid"] = p.get("spent_txid") or ""
        if key not in result_keys:
            result_keys.add(key)
            result.append(neu)

    empfaenge: list[dict] = []
    if wallet is not None:
        try:
            if xpub:
                ziel_name = wallet.xpub_label(xpub)
                def _empfang_gehort(addr: str) -> bool:
                    return wallet.resolve_address(addr) == ziel_name
            else:
                _empfang_gehort = wallet.is_own_address
            empfaenge = eigene_mempool_empfaenge(
                fulcrum, alle_pending, is_own_address=_empfang_gehort,
            )
        except Exception:
            empfaenge = []
    for e in empfaenge:
        key = f"{str(e.get('txid') or '').lower()}:{int(e.get('vout') or 0)}"
        if key in result_keys:
            continue
        result_keys.add(key)
        result.append(dict(e))

    if cache_dir is not None:
        try:
            merke_bip158_verlauf(
                xpub,
                [
                    {
                        "txid": str(p.get("txid") or "").lower(),
                        "vout": int(p.get("vout") or 0),
                        "address": p.get("address"),
                        "value": int(p.get("value") or 0),
                        "spent": True,
                        "spent_pending": True,
                        "spent_txid": p.get("spent_txid") or "",
                        "spent_height": 0,
                        "status": p.get("status") or {},
                    }
                    for p in pending
                ],
                cache_dir,
            )
        except Exception:
            pass

    return result


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
        pruned = _prune_cached_utxos(
            cached,
            fetch_address_utxos,
            verify_utxo_spent=verify_utxo_spent,
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


def _light_rescan_xpub(
    xpub: str,
    cached: list[dict],
    scan_end_index: int,
    fetch_wallet_utxos,
    fetch_address_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
) -> list[dict]:
    """Light-Rescan: Cache bereinigen + nächste Adress-Batch scannen."""
    next_start = scan_end_index
    next_end = next_start + max_addresses // 2 - 1
    print(
        f"\nLight-Rescan {(wallet.xpub_label(xpub) if wallet else xpub[:25] + '...')} "
        f"(Index #{next_start}–#{next_end} pro Chain)",
        flush=True,
    )

    pruned = _prune_cached_utxos(cached, fetch_address_utxos)
    pruned = _mempool_pending_nach_prune(
        xpub,
        cached,
        pruned,
        fulcrum=fulcrum,
        wallet=wallet,
        cache_dir=cache_dir,
    )
    removed = len(cached) - len(pruned)
    if removed:
        print(f"  {removed} verbrauchte UTXO(s) aus Cache entfernt", flush=True)

    new_addresses = derive_addresses(
        xpub,
        max_addresses=max_addresses,
        start_index=next_start,
    )
    print(f"  Scanne {len(new_addresses)} neue Adressen...", flush=True)
    new_utxos = fetch_wallet_utxos(new_addresses)
    merged = _merge_utxo_lists(pruned, new_utxos)
    new_scan_end = next_start + max_addresses // 2

    cache_path = save_xpub_utxo_cache(
        xpub,
        merged,
        cache_dir,
        source,
        scan_end_index=new_scan_end,
        max_addresses=max_addresses,
        # Der Light-Rescan kennt nur die neue Batch; für das Alter zählen alle
        # bisher bekannten Adressen mit.
        first_seen=ermittle_first_seen(
            xpub,
            derive_addresses(xpub, max_addresses=max_addresses) | set(new_addresses),
            cache_dir,
            fulcrum,
        ),
    )
    print(
        f"  → {len(merged)} UTXO(s) gecacht "
        f"({len(new_utxos)} neu, bis Index #{new_scan_end - 1}) "
        f"in {cache_path.name}",
        flush=True,
    )
    return merged


def _full_rescan_xpub(
    xpub: str,
    fetch_wallet_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
    on_progress=None,
    on_utxos_update=None,
) -> list[dict]:
    """Full-Rescan: gesamten Adressraum ab Index #0 neu scannen."""
    label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
    print(f"\nFull-Rescan {label} (ab Index #0)", flush=True)
    return _scan_xpub_utxos(
        xpub,
        fetch_wallet_utxos,
        cache_dir,
        source,
        max_addresses,
        start_index=0,
        wallet=wallet,
        fulcrum=fulcrum,
        on_progress=on_progress,
        on_utxos_update=on_utxos_update,
    )


def _verify_cached_utxos_against_chain(
    cached_by_xpub: dict[str, list[dict]],
    fetch_wallet_utxos,
    fetch_address_utxos,
    fetch_addresses_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    verify_utxo_spent=None,
    fulcrum=None,
) -> dict[str, list[dict]]:
    """
    Fragt optional nach Cache-Prüfung der gecachten UTXOs
    plus der nächsten SALDEN_CHECK_LOOKAHEAD Adress-Indizes
    und bietet bei Abweichung Light- oder Full-Rescan an.
    """
    if not cached_by_xpub:
        return cached_by_xpub

    cached_xpubs = list(cached_by_xpub)
    prefixes = ", ".join(
        wallet.xpub_label(x) if wallet else x[:25] + "..."
        for x in cached_xpubs
    )
    print(
        f"\nUTXO-Set zu {len(cached_xpubs)} XPUB(s) im Cache gefunden "
        f"({prefixes})."
    )
    print(
        "Salden gegen Blockchain prüfen? [j/N] (Enter = Cache nutzen): ",
        end="",
        flush=True,
    )
    from interact import prompt_rescan_mode, prompt_yes_no

    if not prompt_yes_no(default_yes=False):
        return cached_by_xpub

    mismatched: list[str] = []
    scan_end_by_xpub: dict[str, int] = {}

    for xpub in cached_xpubs:
        cached = cached_by_xpub[xpub]
        entry = load_xpub_cache_entry(xpub, cache_dir)
        xpub_max = _max_addresses_for_xpub(xpub, wallet, max_addresses)
        scan_end_index = entry["scan_end_index"] if entry else xpub_max // 2
        scan_end_by_xpub[xpub] = scan_end_index

        label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
        print(f"\nPrüfe {label} gegen Blockchain...", flush=True)

        matches, pruned, lookahead = _verify_cached_utxo_set(
            xpub,
            cached,
            scan_end_index,
            fetch_address_utxos,
            fetch_addresses_utxos,
            fetch_wallet_utxos,
            verify_utxo_spent=verify_utxo_spent,
        )
        live = _merge_utxo_lists(pruned, lookahead)

        if matches:
            if cached:
                cached_total = sum(u["value"] for u in cached)
                print(
                    f"  {len(cached)} UTXO(s), {cached_total:,} sats — stimmt überein",
                    flush=True,
                )
            else:
                print("  Keine UTXOs — folgende Indizes ebenfalls leer.", flush=True)
        else:
            mismatched.append(xpub)
            _describe_utxo_diff(cached, live)

    if not mismatched:
        print("\nUTXO-Set unverändert.")
        return cached_by_xpub

    print("\nSalden weichen vom Cache ab.")
    mode = prompt_rescan_mode()
    if mode is None:
        print("Nutze veralteten Cache.", flush=True)
        return cached_by_xpub

    for xpub in mismatched:
        cached = cached_by_xpub[xpub]
        scan_end_index = scan_end_by_xpub[xpub]
        xpub_max = _max_addresses_for_xpub(xpub, wallet, max_addresses)
        if mode == "light":
            updated = _light_rescan_xpub(
                xpub,
                cached,
                scan_end_index,
                fetch_wallet_utxos,
                fetch_address_utxos,
                cache_dir,
                source,
                xpub_max,
                wallet=wallet,
                fulcrum=fulcrum,
            )
        else:
            updated = _full_rescan_xpub(
                xpub,
                fetch_wallet_utxos,
                cache_dir,
                source,
                xpub_max,
                wallet=wallet,
                fulcrum=fulcrum,
            )
        cached_by_xpub[xpub] = updated

    return cached_by_xpub


def _fulcrum_transport_ist_lan(fulcrum) -> bool:
    """
    True = eigener Electrum-Server ohne Tor (typisch IPv4 im LAN).

    Öffentliche Pools und Onion-Verbindungen zählen nicht — die sind
    für den UTXO-Bestand langsamer bzw. privatsphäreärmer.
    """
    if fulcrum is None:
        return False
    from fulcrum import FulcrumClient, RotatingFulcrumPool

    if isinstance(fulcrum, RotatingFulcrumPool):
        return False
    if not isinstance(fulcrum, FulcrumClient):
        return False
    host = (getattr(fulcrum, "host", None) or "").strip().lower()
    if not host or host.endswith(".onion"):
        return False
    if getattr(fulcrum, "tor_proxy", None):
        return False
    return True


def _utxo_scan_scantxoutset_vorrang(fulcrum=None) -> bool:
    """
    Wann Bitcoin Core ``scantxoutset`` vor dem Electrum-Gap-Scan steht.

    Reihenfolge für den **reinen UTXO-Bestand** (Geschwindigkeit, gleiche
    Privatsphäre bei eigenem Node):

    1. Electrs/Fulcrum im LAN — Gap-Scan nur über genutzte Adressen
    2. Core RPC im LAN — ``scantxoutset`` über das ganze UTXO-Set (~1 Min)
    3. Core RPC über Onion — dasselbe, plus Tor-Latenz
    4. Electrs über Onion
    5. BIP-158 Compact Filter (Header/Filter-Walk)

    Öffentliche Electrum-Server bleiben dahinter (schlechtere Privatsphäre).

    Ist Electrs im LAN die aktive Quelle, entfällt Core: der Gap-Scan ist
    für typische Wallets deutlich schneller als ein voller Set-Durchlauf.
    Fehlt LAN-Electrs, bleibt Core (LAN oder Onion) vor Onion-Electrs und
    BIP-158.
    """
    if _fulcrum_transport_ist_lan(fulcrum):
        return False
    return True


def _try_scantxoutset_xpub(
    xpub: str,
    cache_dir: Path,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
    on_progress=None,
) -> list[dict] | None:
    """
    UTXO-Bestand über Bitcoin Core ``scantxoutset``, falls sinnvoll und konfiguriert.

    None = absichtlich übersprungen, Core fehlt/unerreichbar → Caller nutzt
    Electrum/BIP-158. Siehe ``_utxo_scan_scantxoutset_vorrang``.
    """
    if not _utxo_scan_scantxoutset_vorrang(fulcrum):
        msg = (
            "scantxoutset übersprungen — Electrs/Fulcrum im LAN ist für den "
            "UTXO-Bestand typischerweise schneller (Gap-Scan)."
        )
        print(f"  {msg}", flush=True)
        if on_progress:
            try:
                on_progress(msg, sofort=True)
            except TypeError:
                on_progress(msg)
        return None

    env = _load_dotenv()
    from core.bitcoind_rpc import try_scantxoutset_for_xpubs

    scan_cap = _scan_index_cap_per_chain(xpub, wallet, max_addresses)

    def _max_for(key: str) -> int:
        return _scan_index_cap_per_chain(key, wallet, max_addresses)

    try:
        ergebnis = try_scantxoutset_for_xpubs(
            env,
            [xpub],
            max_addresses_for=_max_for,
            default_max=scan_cap,
            wallet=wallet,
            on_progress=on_progress,
        )
    except Exception as exc:
        print(f"  scantxoutset übersprungen: {exc}", flush=True)
        return None
    if ergebnis is None:
        return None
    by_xpub, tip = ergebnis
    utxos = by_xpub.get(xpub) or []
    label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
    print(
        f"\nscantxoutset {label}: {len(utxos)} UTXO(s)"
        + (f" · Tip {tip}" if tip else ""),
        flush=True,
    )
    cache_path = save_xpub_utxo_cache(
        xpub,
        utxos,
        cache_dir,
        "bitcoind",
        scan_end_index=scan_cap,
        max_addresses=max_addresses,
        first_seen=ermittle_first_seen(
            xpub,
            derive_addresses(xpub, max_addresses=max(scan_cap * 2, 2)),
            cache_dir,
            None,
            on_progress=on_progress,
            utxos=utxos,
        ),
        scan_tip_height=tip,
    )
    print(f"  → {len(utxos)} UTXO(s) gecacht in {cache_path.name}", flush=True)
    return utxos


def _scan_xpub_utxos(
    xpub: str,
    fetch_wallet_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    start_index: int = 0,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
    on_progress=None,
    on_utxos_update=None,
    allow_scantxoutset: bool = True,
) -> list[dict]:
    """Scannt ein XPUB und schreibt das Ergebnis in den Cache."""
    label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
    zwischen: list[dict] = []

    def _melde_utxos(stand: list[dict]) -> None:
        nonlocal zwischen
        zwischen = list(stand)
        schreibe_utxo_zwischenstand(
            xpub, zwischen, cache_dir, source, max_addresses=max_addresses,
        )
        if on_utxos_update:
            on_utxos_update(zwischen)

    # Core scantxoutset nur bei Vollabgleich (User-Scan), nie beim Tip-Nachzug.
    if allow_scantxoutset and start_index == 0:
        core_utxos = _try_scantxoutset_xpub(
            xpub,
            cache_dir,
            max_addresses,
            wallet=wallet,
            fulcrum=fulcrum,
            on_progress=on_progress,
        )
        if core_utxos is not None:
            if on_utxos_update:
                on_utxos_update(core_utxos)
            return core_utxos
    scan_end_index = start_index + max_addresses // 2
    scan_cap = _scan_index_cap_per_chain(xpub, wallet, max_addresses)
    use_gap_scan = start_index == 0 and (fulcrum is not None)
    if use_gap_scan:
        if on_progress:
            on_progress(f"Suche benutzte Adressen von {label}…")
        addresses, scan_end_index = discover_wallet_scan_addresses(
            xpub,
            fulcrum=fulcrum,
            max_index_per_chain=scan_cap,
            start_index=start_index,
            on_progress=on_progress,
            on_utxos_update=_melde_utxos,
        )
        print(
            f"\nScanne XPUB {label} "
            f"(Gap-Scan bis Index #{scan_end_index - 1} pro Chain, "
            f"{len(addresses)} Adressen)",
            flush=True,
        )
    elif source == "bip158" and start_index == 0:
        addresses = derive_addresses(
            xpub,
            max_addresses=max(scan_cap * 2, max_addresses),
            start_index=start_index,
        )
        print(
            f"\nScanne XPUB {label} "
            f"(BIP-158 Filter bis Index #{scan_cap - 1} pro Chain)",
            flush=True,
        )
    else:
        end_index = start_index + max_addresses // 2 - 1
        addresses = derive_addresses(
            xpub,
            max_addresses=max_addresses,
            start_index=start_index,
        )
        print(
            f"\nScanne XPUB {label} "
            f"(Index #{start_index}–#{end_index} pro Chain, {len(addresses)} Adressen)",
            flush=True,
        )
    from display import is_list_abort_requested

    if is_list_abort_requested():
        return list(zwischen)

    if on_progress:
        on_progress(
            f"Frage UTXOs…"
            if source == "bip158"
            else f"Frage UTXOs für {len(addresses)} Adressen…"
        )
    tip_hoehe = None
    # Nach Gap-Scan sind die UTXOs schon im Zwischenstand — listunspent
    # startet bei null und würde die GUI sonst kurz leeren. BIP-158 und
    # feste Adresslisten melden weiter live.
    live_update = None if use_gap_scan else _melde_utxos
    fetch_kwargs = {
        "filter_scan": False,
        "on_progress": on_progress,
        "on_utxos_update": live_update,
        "xpubs": [xpub],
    }
    if source == "bip158" and start_index == 0:
        fetch_kwargs["filter_scan"] = True
        fetch_kwargs["max_addr"] = scan_cap * 2
        try:
            utxos = fetch_wallet_utxos(addresses, **fetch_kwargs)
        except TypeError:
            fetch_kwargs.pop("on_utxos_update", None)
            utxos = fetch_wallet_utxos(addresses, **fetch_kwargs)
        scan_end_index = scan_cap
        try:
            from bip158_scanner import take_last_scan_tip

            tip_hoehe = take_last_scan_tip(xpub)
        except Exception:
            tip_hoehe = None
    else:
        try:
            utxos = fetch_wallet_utxos(addresses, **fetch_kwargs)
        except TypeError:
            fetch_kwargs.pop("on_utxos_update", None)
            utxos = fetch_wallet_utxos(addresses, **fetch_kwargs)
    if is_list_abort_requested() and not utxos:
        return list(zwischen) if zwischen else utxos
    cache_path = save_xpub_utxo_cache(
        xpub,
        utxos,
        cache_dir,
        source,
        scan_end_index=scan_end_index,
        max_addresses=max_addresses,
        first_seen=ermittle_first_seen(
            xpub,
            addresses,
            cache_dir,
            fulcrum,
            on_progress=on_progress,
            utxos=utxos,
        ),
        scan_tip_height=tip_hoehe,
    )
    print(
        f"  → {len(utxos)} UTXO(s) gecacht in {cache_path.name}",
        flush=True,
    )
    if on_utxos_update:
        on_utxos_update(utxos)
    return utxos


def _adressen_bis_index(xpub: str, end_index: int) -> set[str]:
    """Receive- und Change-Adressen Index #0 … #end_index−1."""
    addresses: set[str] = set()
    if end_index <= 0:
        return addresses
    for change in (0, 1):
        for i in range(end_index):
            addr = derive_address_at_index(xpub, change, i)
            if addr:
                addresses.add(addr)
    return addresses


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


def sync_xpub_zum_tip(
    xpub: str,
    fetch_wallet_utxos,
    fetch_address_utxos,
    fetch_addresses_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
    verify_utxo_spent=None,
    bip158_fetch_wallet_utxos=None,
    on_progress=None,
) -> list[dict] | None:
    """
    Leichtes Nachziehen bis Chain-Tip (Start-Sync / Light-Update).

    Nur mit bestehendem UTXO-Cache. **Kein** Fullscan, **kein** scantxoutset.

    Produktregel:
    1. **BIP-158 inkrementell**, wenn Compact-Filter-Fetcher und
       ``scan_tip_height`` vorhanden (auch wenn Electrs/Core die allgemeine
       Datenquelle sind).
    2. Sonst **Electrs/Adresse light**: nur bekannte UTXOs auf spent prüfen
       + Gap/Lookahead ab ``scan_end_index`` — nicht alle Indizes #0…N.
    3. Expliziter User-UTXO-Scan bleibt bei Electrs/Core-Vorrang (anderer Pfad).

    Rückgabe: aktualisierte UTXO-Liste, oder ``None`` ohne Cache.
    """
    entry = load_xpub_cache_entry(xpub, cache_dir)
    if entry is None:
        return None

    label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
    xpub_max = _max_addresses_for_xpub(xpub, wallet, max_addresses)
    scan_end = int(entry["scan_end_index"] or 0)
    if scan_end <= 0:
        scan_end = max(xpub_max // 2, 1)
    tip = (entry.get("raw") or {}).get("scan_tip_height")
    try:
        tip_i = int(tip) if tip is not None else None
    except (TypeError, ValueError):
        tip_i = None

    if on_progress:
        on_progress(f"Aktualisiere {label} bis Chain-Tip…")

    # --- 1) BIP-158 inkrementell (bevorzugt für Tip-Nachzug) ---------------
    bip_fetch = bip158_fetch_wallet_utxos
    if bip_fetch is None and source == "bip158":
        bip_fetch = fetch_wallet_utxos
    if bip_fetch is not None and tip_i is not None:
        print(
            f"\nAktualisiere {label} (BIP-158 ab Tip {tip_i:,})".replace(",", "."),
            flush=True,
        )
        if on_progress:
            on_progress(
                f"{label}: BIP-158 inkrementell ab Block {tip_i:,}".replace(",", ".")
            )
        try:
            # Kein Electrs-Gap und kein scantxoutset — nur Compact-Filter ab Tip.
            return _scan_xpub_utxos(
                xpub,
                bip_fetch,
                cache_dir,
                "bip158",
                xpub_max,
                start_index=0,
                wallet=wallet,
                fulcrum=None,
                on_progress=on_progress,
                allow_scantxoutset=False,
            )
        except Exception as exc:
            # Multisig/Deskriptor oder Peer-Fehler: nicht den ganzen Wallet
            # überspringen — Electrs light hält den Cache frisch.
            msg = (
                f"{label}: BIP-158 fehlgeschlagen ({exc}) — "
                "weiche auf Electrs light aus…"
            )
            print(f"  ⚠️  {msg}", flush=True)
            if on_progress:
                on_progress(msg)
    if bip_fetch is not None and tip_i is None:
        msg = (
            f"{label}: kein scan_tip_height im Cache — "
            "kein BIP-158-Filter-Nachzug (bräuchte mehrere Peers ab Tip); "
            "Electrs light (Gap) statt Multi-Peer-Scan."
        )
        print(f"  {msg}", flush=True)
        if on_progress:
            on_progress(msg)

    # --- 2) Electrs/Adresse light: spent der bekannten UTXOs + Gap ----------
    # BIP-158-Adressabruf ist teuer (Filter/Block) — nur echte Electrs/Core-
    # Spent-Prüfung oder Fulcrum-Gap, nicht der BIP-158-Fallback-Fetcher.
    electrs_light = (
        fulcrum is not None
        or verify_utxo_spent is not None
        or (
            source not in ("bip158",)
            and (
                fetch_address_utxos is not None
                or fetch_addresses_utxos is not None
            )
        )
    )
    if not electrs_light:
        msg = (
            f"{label}: kein Electrs-Light-Pfad — Cache unverändert."
            if bip_fetch is None or tip_i is not None
            else f"{label}: Cache unverändert (kein Tip, kein Electrs)."
        )
        if bip_fetch is None or tip_i is not None:
            print(f"  {msg}", flush=True)
            if on_progress:
                on_progress(msg)
        return list(entry["utxos"])

    alt = list(entry["utxos"] or [])
    # Adressen der Cache-UTXOs: auch nach spent erneut abfragen (neue Empfänge).
    addrs_cache = {u.get("address") for u in alt if u.get("address")}
    print(
        f"\nAktualisiere {label} (Light: bekannte UTXOs + Gap ab #{scan_end})",
        flush=True,
    )
    if on_progress:
        on_progress(
            f"{label}: prüfe {len(alt)} bekannte UTXO(s), Gap ab #{scan_end}…"
        )

    live = _prune_cached_utxos(
        alt,
        fetch_address_utxos,
        verify_utxo_spent=verify_utxo_spent,
    )
    live = _mempool_pending_nach_prune(
        xpub,
        alt,
        live,
        fulcrum=fulcrum,
        wallet=wallet,
        cache_dir=cache_dir,
    )
    extra_same: list[dict] = []
    if addrs_cache and (fetch_address_utxos or fetch_addresses_utxos):
        extra_same = _fetch_address_batch_utxos(
            addrs_cache,
            fetch_address_utxos,
            fetch_addresses_utxos,
            progress_label=f"Live {label}",
            on_progress=on_progress,
        )
    new_end = scan_end
    extra_utxos: list[dict] = []
    extra_window: list[dict] = []

    if fulcrum is not None:
        scan_cap = _scan_index_cap_per_chain(xpub, wallet, xpub_max)
        if on_progress:
            on_progress(f"{label}: Gap ab Index #{scan_end}…")
        try:
            extra_addrs, walked_end = discover_wallet_scan_addresses(
                xpub,
                fulcrum=fulcrum,
                max_index_per_chain=scan_cap,
                start_index=scan_end,
                gap_limit=UTXO_SCAN_GAP_LIMIT,
                on_progress=on_progress,
            )
        except ValueError:
            extra_addrs, walked_end = set(), scan_end
        neu = set(extra_addrs) - addrs_cache
        if neu:
            if on_progress:
                on_progress(f"{label}: {len(neu)} neue Gap-Adressen…")
            extra_utxos = _fetch_address_batch_utxos(
                neu,
                fetch_address_utxos,
                fetch_addresses_utxos,
                progress_label=f"Gap {label}",
                on_progress=on_progress,
            )
            new_end = max(scan_end, int(walked_end))
        # Rückwärts-Gap: Empfänge auf zuvor leeren Indizes können unterhalb
        # des bisherigen Scan-Endes liegen (Empfang und Change).
        window_start = max(0, scan_end - UTXO_SCAN_GAP_LIMIT)
        if window_start < scan_end and (fetch_address_utxos or fetch_addresses_utxos):
            window_addrs = derive_addresses(
                xpub,
                max_addresses=(scan_end - window_start) * 2,
                start_index=window_start,
            )
            neu_window = window_addrs - addrs_cache - set(extra_addrs)
            if neu_window:
                extra_window = _fetch_address_batch_utxos(
                    neu_window,
                    fetch_address_utxos,
                    fetch_addresses_utxos,
                    progress_label=f"Rückwärts-Gap {label}",
                    on_progress=on_progress,
                )
    else:
        lookahead = max(BIP44_GAP_LIMIT, SALDEN_CHECK_LOOKAHEAD)
        if on_progress:
            on_progress(f"{label}: Lookahead {lookahead} Indizes…")

        def _look_fetch(addrs, **_kw):
            return _fetch_address_batch_utxos(
                addrs,
                fetch_address_utxos,
                fetch_addresses_utxos,
                progress_label=f"Lookahead {label}",
                on_progress=on_progress,
            )

        extra_utxos = _fetch_lookahead_utxos(
            xpub, scan_end, _look_fetch, lookahead,
        )
        if extra_utxos:
            new_end = scan_end + lookahead

    merged = _merge_utxo_lists(live, extra_same)
    merged = _merge_utxo_lists(merged, extra_utxos)
    merged = _merge_utxo_lists(merged, extra_window)
    old_n = len(alt)
    # Electrs light: Tip auf Live-Electrs (bevorzugt) bzw. Header-Datei
    # anheben — sonst bleibt „−N Blöcke“ hängen, wenn p2p_headers hinter
    # dem Node liegt oder stundenlang nicht nachgezogen wurde.
    tip_fuer_cache = tip_i
    if fulcrum is not None:
        try:
            from fulcrum import get_chain_tip_height

            et = int(get_chain_tip_height(fulcrum, force=True))
            if tip_fuer_cache is None or et > int(tip_fuer_cache):
                tip_fuer_cache = et
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
            if tip_fuer_cache is None or ht > int(tip_fuer_cache):
                tip_fuer_cache = ht
    except Exception:
        pass
    cache_path = save_xpub_utxo_cache(
        xpub,
        merged,
        cache_dir,
        source if source != "bip158" else "fulcrum",
        scan_end_index=new_end,
        max_addresses=xpub_max,
        scan_tip_height=tip_fuer_cache,
    )
    print(
        f"  → {label}: {len(merged)} UTXO(s) (vorher {old_n}), "
        f"Scan bis Index #{max(new_end - 1, 0)} in {cache_path.name}",
        flush=True,
    )
    if on_progress:
        on_progress(f"{label}: {len(merged)} UTXO(s) aktuell.")
    return merged


def sync_wallets_zum_tip(
    xpubs: list[str],
    fetch_wallet_utxos,
    fetch_address_utxos,
    fetch_addresses_utxos,
    cache_dir: Path,
    source: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    fulcrum=None,
    verify_utxo_spent=None,
    bip158_fetch_wallet_utxos=None,
    on_progress=None,
    on_wallet_done=None,
) -> dict[str, list[dict]]:
    """
    Aktualisiert alle XPUBs mit Cache bis Chain-Tip (Light-Update).

    Ohne Cache: übersprungen. Rückgabe: ``{xpub: utxos}`` nur für
    bearbeitete Schlüssel. *on_wallet_done(xpub, utxos_oder_None)*.
    """
    ergebnis: dict[str, list[dict]] = {}
    for xpub in xpubs:
        try:
            aktualisiert = sync_xpub_zum_tip(
                xpub,
                fetch_wallet_utxos,
                fetch_address_utxos,
                fetch_addresses_utxos,
                cache_dir,
                source,
                max_addresses=_max_addresses_for_xpub(
                    xpub, wallet, max_addresses
                ),
                wallet=wallet,
                fulcrum=fulcrum,
                verify_utxo_spent=verify_utxo_spent,
                bip158_fetch_wallet_utxos=bip158_fetch_wallet_utxos,
                on_progress=on_progress,
            )
        except Exception as exc:
            label = wallet.xpub_label(xpub) if wallet else xpub[:25] + "..."
            msg = f"{label}: Aktualisierung fehlgeschlagen ({exc})"
            print(f"  ⚠️  {msg}", flush=True)
            if on_progress:
                on_progress(msg)
            if on_wallet_done:
                on_wallet_done(xpub, None)
            continue
        if aktualisiert is None:
            if on_wallet_done:
                on_wallet_done(xpub, None)
            continue
        ergebnis[xpub] = aktualisiert
        if on_wallet_done:
            on_wallet_done(xpub, aktualisiert)
    return ergebnis


def resolve_wallet_utxos(
    xpubs: list[str],
    fetch_wallet_utxos,
    fetch_address_utxos,
    fetch_addresses_utxos,
    cache_dir: Path,
    source: str,
    rescan: bool = False,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    wallet: WalletContext | None = None,
    *,
    verify_utxo_spent=None,
    use_cache_only: bool = False,
    fulcrum=None,
    on_missing_xpubs=None,
    on_progress=None,
    on_utxos_update=None,
) -> list[dict]:
    """
    Liefert Wallet-UTXOs aus Cache oder nach optionalem Scan.
    Mit --rescan werden alle XPUBs per Full-Rescan ab Index #0 neu gescannt.

    *on_missing_xpubs* entscheidet, ob nicht gecachte XPUBs gescannt werden:
    Callable[[list[str]], bool]. Ohne Angabe fragt das CLI wie bisher nach.
    Nicht-interaktive Aufrufer (Web-Server) müssen etwas übergeben — sonst
    blockiert der Prompt den Thread auf unbestimmte Zeit.

    *on_utxos_update* erhält während des Scans den bekannten UTXO-Zwischenstand
    (voller Snapshot), sobald neue Funde dazukommen.
    """
    if rescan:
        print("Erzwinge Full-Rescan (--rescan)...", flush=True)
        cached_by_xpub: dict[str, list[dict]] = {}
        for xpub in xpubs:
            xpub_max = _max_addresses_for_xpub(xpub, wallet, max_addresses)
            cached_by_xpub[xpub] = _full_rescan_xpub(
                xpub,
                fetch_wallet_utxos,
                cache_dir,
                source,
                xpub_max,
                wallet=wallet,
                fulcrum=fulcrum,
                on_progress=on_progress,
                on_utxos_update=on_utxos_update,
            )
        return _merge_cached_utxos(xpubs, cached_by_xpub, wallet, cache_dir=cache_dir)

    cached_by_xpub: dict[str, list[dict]] = {}
    missing_xpubs: list[str] = []

    for xpub in xpubs:
        cached = load_xpub_utxo_cache(xpub, cache_dir)
        if cached is not None:
            cached_by_xpub[xpub] = cached
            cache_path = _xpub_cache_path(xpub, cache_dir)
            print(
                f"UTXO-Cache geladen: {(wallet.xpub_label(xpub) if wallet else xpub[:25] + '...')} "
                f"({len(cached)} UTXO(s) aus {cache_path.name})",
                flush=True,
            )
        else:
            missing_xpubs.append(xpub)

    if not use_cache_only:
        cached_by_xpub = _verify_cached_utxos_against_chain(
            cached_by_xpub,
            fetch_wallet_utxos,
            fetch_address_utxos,
            fetch_addresses_utxos,
            cache_dir,
            source,
            max_addresses,
            wallet=wallet,
            verify_utxo_spent=verify_utxo_spent,
            fulcrum=fulcrum,
        )

    if not missing_xpubs:
        return _merge_cached_utxos(xpubs, cached_by_xpub, wallet, cache_dir=cache_dir)

    if on_missing_xpubs is None:
        from interact import prompt_wallet_scan

        do_scan = prompt_wallet_scan(missing_xpubs, wallet=wallet)
    else:
        do_scan = bool(on_missing_xpubs(missing_xpubs))
    if not do_scan:
        if cached_by_xpub:
            print(
                "Scan abgebrochen — nutze vorhandenen Cache "
                f"für {len(cached_by_xpub)} XPUB(s).",
                flush=True,
            )
            return _merge_cached_utxos(
                xpubs,
                cached_by_xpub,
                wallet,
                cache_dir=cache_dir,
            )

        print(
            "Kein UTXO-Cache vorhanden und Scan abgelehnt. "
            "Nutze --rescan für einen erzwungenen Scan.",
            file=sys.stderr,
        )
        return []

    for xpub in missing_xpubs:
        xpub_max = _max_addresses_for_xpub(xpub, wallet, max_addresses)
        cached_by_xpub[xpub] = _scan_xpub_utxos(
            xpub,
            fetch_wallet_utxos,
            cache_dir,
            source,
            xpub_max,
            wallet=wallet,
            fulcrum=fulcrum,
        )
    return _merge_cached_utxos(
        xpubs,
        cached_by_xpub,
        wallet,
        cache_dir=cache_dir,
    )


def _print_utxo_rank_row(
    rank: int,
    utxo: dict,
    wallet: WalletContext | None,
    immutable_cache_dir: Path | None = None,
) -> None:
    addr = utxo.get("address", "?")
    wallet_label = wallet.resolve_address(addr) if wallet else None
    if not wallet_label:
        if addr and addr != "?":
            wallet_label = hashlib.sha256(addr.encode()).hexdigest()
        else:
            wallet_label = "?"

    timestamp = _format_utxo_status(utxo)
    print(
        f"{rank:2}. {format_sats(utxo['value']):>14}  {timestamp}"
    )
    print(f"    Wallet: {wallet_label}    Adresse: {abbrev_display(addr)}")
    print(f"    UTXO: {format_utxo_display(utxo['txid'], utxo['vout'], address=addr)}")
    if immutable_cache_dir:
        ingress = load_utxo_ingress_cache(
            utxo["txid"], utxo["vout"], immutable_cache_dir
        )
        if ingress and ingress.get("youngest_time"):
            print(f"    Jüngste Sats im UTXO: {ingress['youngest_time']}")
    print()


def print_utxo_rank_entries(
    sorted_utxos: list[dict],
    start: int,
    end: int,
    wallet: WalletContext | None = None,
    immutable_cache_dir: Path | None = None,
) -> None:
    """Druckt Ranglisten-Einträge [start, end) (0-basiert)."""
    for index in range(start, min(end, len(sorted_utxos))):
        _print_utxo_rank_row(index + 1, sorted_utxos[index], wallet, immutable_cache_dir)


def list_top_wallet_utxos(
    all_utxos: list,
    limit: int,
    wallet: WalletContext | None = None,
    immutable_cache_dir: Path | None = None,
) -> list[dict]:
    """Listet die größten unspent UTXOs; gibt die vollständige sortierte Liste zurück."""
    if not all_utxos:
        print("Keine unspent UTXOs im Wallet gefunden.")
        return []

    sorted_utxos = sorted(all_utxos, key=lambda u: u["value"], reverse=True)
    total_count = len(sorted_utxos)
    total_sats = sum(u["value"] for u in sorted_utxos)
    shown_end = min(limit, total_count)
    shown = sorted_utxos[:shown_end]
    shown_sats = sum(u["value"] for u in shown)

    print(f"\n{'='*85}")
    print(
        f"Wallet-UTXOs: {total_count} unspent gesamt, "
        f"{format_sats(total_sats)}"
    )
    print(
        f"Top {shown_end} (Limit: {limit}): "
        f"{format_sats(shown_sats)}"
    )
    print(f"{'='*85}\n")

    print_utxo_rank_entries(sorted_utxos, 0, shown_end, wallet, immutable_cache_dir)

    if total_count > shown_end:
        print(f"... und {total_count - shown_end} weitere UTXO(s) in der Rangliste")
    print(f"{'='*85}")
    return sorted_utxos


def main():
    parser = argparse.ArgumentParser(description="Multi-XPUB + Taproot Tx Analyzer")
    parser.add_argument(
        "--xpubs",
        nargs="+",
        default=None,
        help="Eine oder mehrere XPUBs (auch Taproot); sonst XPUBS/XPUB_0… aus .env",
    )
    parser.add_argument(
        "--wallet-names",
        nargs="+",
        default=None,
        metavar="NAME",
        help=(
            "Anzeigenamen für die XPUBs (Reihenfolge wie --xpubs). "
            "Sonst WALLET_NAMES/WALLET_NAME_0… aus .env; "
            "ohne Angabe: SHA256-Hex des jeweiligen XPUBs."
        ),
    )
    parser.add_argument("--txid",
                        default=None,
                        help="Transaction ID (Spending-Tx-Analyse)")
    parser.add_argument(
        "--address",
        help="Wallet-Adresse: unspent UTXO(s) und deren Herkunft analysieren",
    )
    parser.add_argument(
        "--utxo",
        help="Nur dieses UTXO (txid:vout), optional zusammen mit --address",
    )
    parser.add_argument(
        "--top-utxos",
        type=int,
        default=10,
        metavar="N",
        help="Top-N Limit im Menü bzw. mit --cli (Default: 10)",
    )
    parser.add_argument(
        "--max-addresses",
        type=int,
        default=DEFAULT_MAX_ADDRESSES,
        metavar="N",
        help=(
            f"Max. abgeleitete Adressen pro XPUB (Fallback) "
            f"(Default: {DEFAULT_MAX_ADDRESSES}, schont API-Limits)"
        ),
    )
    parser.add_argument(
        "--max-addresses-per-xpub",
        nargs="+",
        type=int,
        default=None,
        metavar="N",
        help="Max. Adressen pro XPUB in Reihenfolge von --xpubs (optional)",
    )
    parser.add_argument(
        "--script-types",
        nargs="+",
        default=None,
        choices=SCRIPT_TYPE_CHOICES,
        metavar="TYP",
        help=(
            "Skripttyp pro XPUB in Reihenfolge von --xpubs "
            f"({'|'.join(SCRIPT_TYPE_CHOICES)}); sonst SCRIPT_TYPES/SCRIPT_TYPE_0… "
            "aus .env. Nötig für Wallets, die ohne SLIP-132 immer 'xpub' exportieren"
        ),
    )
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="UTXO-Cache ignorieren und alle XPUBs neu scannen",
    )
    parser.add_argument(
        "--immutable-cache-dir",
        default=None,
        metavar="DIR",
        help=(
            "Flatfile-Cache unveränderlicher Daten (Tx; Default: "
            "immutable_cache/ neben --cache-dir)"
        ),
    )
    parser.add_argument(
        "--cache-dir",
        default=str(UTXO_CACHE_DIR),
        metavar="DIR",
        help=f"Verzeichnis für UTXO-Flatfiles (Default: {UTXO_CACHE_DIR})",
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--rpc-only",
        action="store_true",
        help=(
            "Fulcrum erzwingen (Electrum-Protokoll)"
        ),
    )
    source_group.add_argument(
        "--bip158",
        action="store_true",
        help=(
            "Compact Filter über Bitcoin-P2P (BIP 157/158, kein Core-RPC; "
            "Peers mit peerblockfilters=1)"
        ),
    )
    parser.add_argument(
        "--oeffentliche-electrum",
        action="store_true",
        help=(
            "Öffentliche Electrum-Server (Onion/Clearnet) erlauben — "
            "Adressen gehen an Dritte. Ohne dieses Flag oder "
            "OEFFENTLICHE_ELECTRUM=1 in .env nur eigener Node und BIP-158"
        ),
    )
    parser.add_argument(
        "--bip158-start",
        type=int,
        default=None,
        metavar="HEIGHT",
        help=f"Erste Blockhöhe für BIP-158-Scan (Default: {DEFAULT_BIP158_START_HEIGHT:,} oder BIP158_START_HEIGHT)",
    )
    parser.add_argument(
        "--rpchost",
        default=None,
        help="Fulcrum-Host (überschreibt FULCRUM_HOST aus .env; kein NODE_IP-Fallback)",
    )
    parser.add_argument(
        "--rpcport",
        type=int,
        default=None,
        help="Fulcrum-Port (überschreibt FULCRUM_PORT aus .env, Default: 50002)",
    )
    parser.add_argument(
        "--rpcuser",
        default=None,
        help="(veraltet, ungenutzt) — Fulcrum benötigt keine RPC-Zugangsdaten",
    )
    parser.add_argument(
        "--rpcpass",
        default=None,
        help="(veraltet, ungenutzt) — Fulcrum benötigt keine RPC-Zugangsdaten",
    )
    parser.add_argument(
        "--fulcrum-host",
        default=None,
        help="Fulcrum-Host (Alternative zu --rpchost)",
    )
    parser.add_argument(
        "--fulcrum-port",
        type=int,
        default=None,
        help="Fulcrum-Port (Alternative zu --rpcport, Default: 50002)",
    )
    parser.add_argument(
        "--no-verbose",
        action="store_true",
        help="Kurzdarstellung von TxID, UTXO und Adressen (8…8 Zeichen)",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Direktmodus Top-UTXOs (ohne interaktives Legacy-Menü)",
    )
    parser.add_argument(
        "--fulcrum-no-ssl",
        action="store_true",
        help="Fulcrum ohne SSL (TCP, z. B. Port 50001)",
    )

    args = parser.parse_args()
    import interact

    env = _load_dotenv()
    try:
        from core.i18n import init_from_env
        from core.log_i18n import install_stdout_translation

        init_from_env(env)
        install_stdout_translation()
    except Exception:
        pass

    # Wallets über core.config lesen, nicht über die einzelnen _*_from_env:
    # Die Oberfläche schreibt WALLET_n_*-Blöcke, und nur read_wallets kennt
    # beide Schreibweisen. Ohne das sähe die CLI nach einem Speichern in der
    # Oberfläche keine Wallets mehr.
    wallets_aus_env = wallets_aus_env_datei()
    # Single-Sig und Multisig gleichermaßen — der Analyse-Schlüssel ist bei
    # Multisig der Deskriptor. Nur was sich nicht ableiten lässt, bleibt
    # draußen und wird gemeldet.
    ableitbar = [e for e in wallets_aus_env if e.is_valid()]
    unlesbar = [e for e in wallets_aus_env if not e.is_valid()]

    if args.xpubs is None:
        args.xpubs = [e.analyse_schluessel for e in ableitbar] or None
    if not args.xpubs:
        parser.error(
            "--xpubs fehlt: XPUB(s) per CLI angeben oder WALLET_0_XPUB in .env setzen"
        )

    if args.wallet_names is None:
        args.wallet_names = [e.display_name for e in ableitbar] or None

    if args.script_types is None:
        args.script_types = [e.script_type for e in ableitbar] or None

    if args.max_addresses_per_xpub is None:
        args.max_addresses_per_xpub = [e.max_addresses for e in ableitbar] or None

    if unlesbar:
        print(UNLESBAR_HINWEIS.format(anzahl=len(unlesbar)), flush=True)

    set_verbose(False if args.no_verbose else resolve_verbose_from_env(env))
    if args.bip158_start is None and not args.bip158:
        env_start = env.get("BIP158_START_HEIGHT")
        if env_start:
            try:
                args.bip158_start = int(env_start)
            except ValueError:
                pass

    if args.max_addresses < 1:
        parser.error("--max-addresses muss >= 1 sein")

    if args.wallet_names and len(args.wallet_names) != len(args.xpubs):
        parser.error(
            "--wallet-names: Anzahl muss der Anzahl der --xpubs entsprechen "
            f"({len(args.wallet_names)} Namen, {len(args.xpubs)} XPUBs)"
        )

    max_per_xpub = args.max_addresses_per_xpub
    if max_per_xpub and len(max_per_xpub) != len(args.xpubs):
        parser.error(
            "--max-addresses-per-xpub: Anzahl muss der Anzahl der --xpubs entsprechen "
            f"({len(max_per_xpub)} Werte, {len(args.xpubs)} XPUBs)"
        )

    if args.script_types and len(args.script_types) != len(args.xpubs):
        parser.error(
            "--script-types/SCRIPT_TYPES: Anzahl muss der Anzahl der --xpubs "
            f"entsprechen ({len(args.script_types)} Typen, {len(args.xpubs)} XPUBs)"
        )

    wallet_ctx = build_wallet_context(
        args.xpubs,
        wallet_names=args.wallet_names,
        max_addresses=args.max_addresses,
        max_addresses_per_xpub=max_per_xpub,
        script_types=args.script_types,
    )
    base_address_count = len(wallet_ctx.address_to_wallet)

    cache_dir = Path(args.cache_dir)
    seed_wallet_addresses_from_utxo_cache(wallet_ctx, args.xpubs, cache_dir)
    external_cached, xpub_neg_cached, positive_cached = init_external_address_cache(
        cache_dir, args.xpubs, MAX_TRACE_ADDRESS_SEARCH
    )
    seed_wallet_addresses_from_resolution_cache(wallet_ctx, args.xpubs)

    all_addresses = set(wallet_ctx.address_to_wallet.keys())
    cache_extra = max(0, len(all_addresses) - base_address_count)

    print(f"\nWallet-Adressmapping ({len(args.xpubs)} XPUB(s)):")
    for xpub in args.xpubs:
        xpub_max = wallet_ctx.max_addresses_for(xpub, args.max_addresses)
        mapped = sum(
            1 for mapped_xpub in wallet_ctx.address_to_xpub.values()
            if mapped_xpub == xpub
        )
        print(
            f"  {wallet_ctx.xpub_label(xpub)} → {mapped} Adressen "
            f"(Basis-Limit max {xpub_max})"
        )
    print(
        f"  Mapping gesamt: {len(all_addresses)} eigene Adressen"
        + (f" (davon {cache_extra} aus Cache ergänzt)" if cache_extra else "")
    )
    if external_cached or xpub_neg_cached or positive_cached:
        print(
            f"  Auflösungs-Cache: {external_cached} global extern, "
            f"{xpub_neg_cached} XPUB-Negativ, {positive_cached} Wallet-Positiv"
        )
    print()

    if args.address or args.txid:
        source, backend = _setup_blockchain_client(args, env)
        fetchers = _build_blockchain_fetchers(
            source, backend, args, wallet_ctx
        )
        cache_dir = Path(args.cache_dir)
        if args.address:
            interact.run_analyze_address_utxos(
                fetchers["get_tx"],
                fetchers["fetch_utxos"],
                args.address,
                all_addresses,
                utxo_ref=args.utxo,
                wallet=wallet_ctx,
                cache_dir=cache_dir,
                fetch_address_utxos=fetchers["fetch_address_utxos"],
                cache_source=source,
            )
        else:
            interact.run_analyze_tx(
                fetchers["get_tx"],
                args.txid,
                all_addresses,
                wallet=wallet_ctx,
                cache_dir=cache_dir,
                fetch_address_utxos=fetchers["fetch_address_utxos"],
                cache_source=source,
            )
    elif args.cli:
        if args.top_utxos < 1:
            parser.error("--top-utxos muss >= 1 sein")

        source, backend = _setup_blockchain_client(args, env)
        fetchers = _build_blockchain_fetchers(
            source, backend, args, wallet_ctx
        )
        cache_dir = Path(args.cache_dir)
        print(f"UTXO-Cache-Verzeichnis: {cache_dir.resolve()}\n")
        wallet_utxos = resolve_wallet_utxos(
            args.xpubs,
            fetchers["fetch_wallet_utxos"],
            fetchers["fetch_address_utxos"],
            fetchers["fetch_addresses_utxos"],
            cache_dir,
            source,
            rescan=args.rescan,
            max_addresses=args.max_addresses,
            wallet=wallet_ctx,
            verify_utxo_spent=fetchers.get("verify_utxo_spent"),
            fulcrum=fetchers.get("fulcrum"),
        )
        ranked_utxos = list_top_wallet_utxos(
            wallet_utxos,
            args.top_utxos,
            wallet=wallet_ctx,
            immutable_cache_dir=fetchers.get("immutable_cache_dir"),
        )
        if ranked_utxos:
            interact.interactive_analyze_top_utxos(
                fetchers["get_tx"],
                fetchers["fetch_utxos"],
                ranked_utxos,
                all_addresses,
                shown_count=args.top_utxos,
                wallet=wallet_ctx,
                cache_dir=cache_dir,
                fetch_address_utxos=fetchers["fetch_address_utxos"],
                cache_source=source,
                output_dir=cache_dir.parent / "psbt_out",
                fulcrum=fetchers["fulcrum"],
                immutable_cache_dir=fetchers.get("immutable_cache_dir"),
                f_hint=(
                    "'f' alle UTXOs tracen, "
                    "'F' + transaktionsorientiert (ohne erneuten Scan)"
                ),
            )
    else:
        from menu import MenuSession, run_main_menu

        bip158_start = args.bip158_start
        if bip158_start is None:
            bip158_start = DEFAULT_BIP158_START_HEIGHT
        args.bip158_start = bip158_start

        session = MenuSession(
            args=args,
            wallet_ctx=wallet_ctx,
            cache_dir=Path(args.cache_dir),
            env=env,
            all_addresses=all_addresses,
            bip158_start=bip158_start,
            top_utxos_limit=args.top_utxos,
            verbose=False if args.no_verbose else resolve_verbose_from_env(env),
        )
        run_main_menu(session)


if __name__ == "__main__":
    main()