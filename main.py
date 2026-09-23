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
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Python 3.10-kompatibel (datetime.UTC erst ab 3.11)
UTC = timezone.utc

from display import abbrev_display, format_sats, format_tx_display, format_utxo_display, set_verbose
from embit.bip32 import HDKey

from core.derivation import (
    DEFAULT_MAX_ADDRESSES,
    SCRIPT_TYPE_CHOICES,
    _SCRIPT_TYPE_ALIASES,
    _CHAIN_NETWORK,
    _encoders_for_xpub,
    _hdkey_by_xpub,
    _hdkey_for_xpub,
    _script_address,
    _script_type_by_xpub,
    derive_address_at_index,
    derive_addresses,
    derive_addresses_at_index,
    derive_descriptor_addresses,
    derive_receive_address_at_index,
    ist_deskriptor,
    normalize_script_type,
    parse_deskriptor,
    register_script_types,
    script_type_for_xpub,
)

from core.wallet_context import (
    EXTERNAL_ADDRESS_CACHE_NAME,
    WalletContext,
    _address_belongs_to_xpub,
    _default_wallet_name,
    _external_address_cache_path,
    _external_cache_dir,
    _external_cache_fingerprint,
    _external_cache_lock,
    _external_cache_max_index,
    _is_known_external_address,
    _is_known_xpub_negative,
    _known_external_addresses,
    _known_wallet_addresses,
    _mark_external_address,
    _mark_wallet_address_positive,
    _mark_xpub_negative,
    _max_addresses_for_xpub,
    _persist_external_address_cache,
    _register_wallet_address,
    _remove_external_address_if_present,
    _remove_wallet_address_positive_if_present,
    _remove_xpub_negative_if_present,
    _seed_wallet_addresses_from_cache,
    _xpub_address_negative_cache,
    _xpub_address_positive_cache,
    _xpub_disk_negatives,
    _xpub_fingerprint,
    _xpub_set_fingerprint,
    build_wallet_context,
    init_external_address_cache,
    seed_wallet_addresses_from_resolution_cache,
    seed_wallet_addresses_from_scan_end,
    seed_wallet_addresses_from_utxo_cache,
    seed_wallet_addresses_from_verlauf_cache,
)

from core.xpub_cache import (
    bip158_fullscan_ist_fertig,
    bip158_start_aus_first_seen,
    BITCOIN_BLOCK_INTERVAL_SECONDS,
    BITCOIN_GENESIS_TIMESTAMP,
    BLOCK_HEADER_CACHE_SUBDIR,
    block_time_for_height,
    cache_disk_write_allowed,
    CacheDiskFullError,
    enrich_utxos_with_block_times,
    first_seen_from_utxos,
    IMMUTABLE_CACHE_DIR,
    is_cache_disk_write_blocked,
    iter_utxo_ingress_cache_entries,
    load_cached_block_time,
    load_cached_tx,
    load_unspent_outpoint_values,
    load_utxo_ingress_cache,
    load_xpub_cache_entry,
    load_xpub_utxo_cache,
    load_xpub_verlauf_cache,
    load_xpub_verlauf_scan_meta,
    merke_bip158_verlauf,
    MIN_FREE_DISK_BYTES,
    MIN_FREE_DISK_RATIO,
    resolve_immutable_cache_dir,
    rewrite_utxo_cache_times,
    SALDEN_CHECK_LOOKAHEAD,
    save_cached_block_time,
    save_cached_tx,
    save_utxo_ingress_cache,
    save_xpub_first_seen,
    save_xpub_utxo_cache,
    save_xpub_verlauf_cache,
    schreibe_utxo_zwischenstand,
    settle_gezielte_spends_im_cache,
    TX_IMMUTABLE_CACHE_SUBDIR,
    UTXO_CACHE_DIR,
    utxo_cache_frisch_genug,
    UTXO_INGRESS_CACHE_SUBDIR,
    VERLAUF_UTXO_CACHE_MAX_ALTER_S,
    xpub_first_seen,
    _address_known_in_cache,
    _address_utxos_in_cache,
    _alter_aus_payload,
    _block_header_cache_path,
    _block_header_network_tag,
    _blockhoehe_aus_utxo,
    _cache_disk_blocked,
    _cache_disk_full_meldung,
    _cache_disk_lock,
    _cache_disk_target,
    _cache_disk_warned,
    _cache_scan_end_index,
    _describe_utxo_diff,
    _deskriptor_kennungen,
    _dump_cache_json,
    _fetch_address_batch_utxos,
    _fetch_lookahead_utxos,
    _fetch_utxos_for_addresses,
    _first_seen_label,
    _immutable_tx_cache_path,
    _immutable_tx_lock,
    _immutable_tx_memory,
    _mark_address_scanned,
    _maybe_log_sqlite_flatfile_hint,
    _merge_utxo_lists,
    _merge_verlauf_eintraege,
    _normalize_txid,
    _p2p_header_chain,
    _P2P_HEADER_CHAIN_CACHE,
    _parse_scanned_at,
    _prune_cached_utxos,
    _scan_tip_anheben,
    _sqlite_flatfile_hint_emitted,
    _SQLITE_FLATFILE_HINT_THRESHOLD,
    _sqlite_flatfile_last_count,
    _SQLITE_FLATFILE_RECOUNT_EVERY,
    _sqlite_flatfile_save_ticks,
    _uebernehme_first_seen,
    _utxo_ingress_cache_path,
    _utxo_set_signature,
    _utxo_sets_match,
    _verify_cached_utxo_set,
    _xpub_alter_path,
    _xpub_cache_key,
    _xpub_cache_path,
    _xpub_verlauf_cache_path,
)

from core.paths import app_dir
from core.env_bootstrap import (
    ENV_FILE,
    _editor_from_env,
    _load_dotenv,
    open_env_file_in_editor,
)

DEFAULT_BIP158_START_HEIGHT = 481_824  # SegWit-Aktivierung; P2P-Filter ab hier
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
#: Setup-Latenz-Gate für öffentliches Onion-Electrs (Auto-Priorität).
#: Probe = eine ``get_history`` auf Dummy-Scripthash; darüber → BIP-158
#: bevorzugen bzw. Warnung/Abbruch. ``PUBLIC_ONION_LATENCY_SECONDS=0`` aus.
PUBLIC_ONION_LATENCY_GATE_SECONDS = 8.0


MAX_TRACE_ADDRESS_SEARCH = 500
BIP44_GAP_LIMIT = 20
UTXO_SCAN_GAP_LIMIT = 100  # Wasabi/CoinJoin: Lücken >20 zwischen genutzten Indizes


def set_chain_network(name: str | None) -> None:
    """Setzt das Adress-Netz aus ``NETWORK`` (main/regtest/test/signet)."""
    import core.derivation as _derivation
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
    _derivation._CHAIN_NETWORK = net
    global _CHAIN_NETWORK
    _CHAIN_NETWORK = net  # Fassade parallel zum Modul-Attribut halten
    _hdkey_by_xpub.clear()
    _xpub_address_positive_cache.clear()
    _xpub_address_negative_cache.clear()
    # Fulcrum-Header-Zeiten: Mainnet-Höhe ≠ Regtest-Höhe.
    try:
        import fulcrum as _fulcrum_mod

        cache = getattr(_fulcrum_mod, "_HEADER_TIME_CACHE", None)
        if isinstance(cache, dict):
            cache.clear()
    except Exception:
        pass


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


def resolve_wallets_nur_bekannte_utxos(
    env: dict[str, str],
    default: bool = False,
) -> bool:
    """
    Unteroption zu „Wallets immer aktuell halten“.

    Env: ``WALLETS_NUR_BEKANNTE_UTXOS``. Bei ja: Tip-Nachzug (Start / Block /
    „Bis Tip“) prüft nur bekannte UTXOs/Adressen — kein Gap-Scan. Neue
    Empfangsadressen nur per manuellem UTXO-Scan. Vorgabe aus.
    """
    raw = env.get("WALLETS_NUR_BEKANNTE_UTXOS")
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


def tls_should_try_opposite(error: str | None) -> bool:
    """
    Ob nach Fehlversuch die andere TLS-Einstellung sinnvoll ist.

    Reine Netzfehler (Timeout, refused) nicht — da hilft SSL-Umschalten nicht.
    Protokoll-Mismatch (wrong version, EOF, SSL) und unklare Handshake-Fehler ja.
    """
    if not error:
        return False
    text = str(error).lower()
    if "listunspent" in text:
        return False
    if any(
        x in text
        for x in (
            "timed out",
            "timeout",
            "connection refused",
            "network is unreachable",
            "no route to host",
            "name or service not known",
            "nodename nor servname",
            "getaddrinfo failed",
            "temporary failure in name resolution",
        )
    ):
        return False
    return True


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
            "SatSage probiert beim nächsten Check ohne TLS und schreibt es fest."
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
            "SatSage probiert beim nächsten Check mit TLS und schreibt es fest."
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
    # TLS ja/nein: bei Protokoll-Mismatch die andere Einstellung (LAN + Onion).
    if not client and error and tls_should_try_opposite(error):
        alt = not use_ssl
        print(
            f"  → {'TLS' if use_ssl else 'ohne TLS'} fehlgeschlagen "
            f"({error}) — versuche {'ohne TLS' if use_ssl else 'mit TLS'}…",
            flush=True,
        )
        if tor_proxy:
            _index, client, error = _probe_public_onion_endpoint(
                0, host, port, alt, tor_proxy,
            )
        else:
            from fulcrum import connect_fulcrum

            client, error = connect_fulcrum(
                host,
                port,
                use_ssl=alt,
                timeout=FULCRUM_CONNECT_TIMEOUT,
                tor_proxy=None,
                require_listunspent=True,
            )
        use_ssl = alt
    if client:
        print(
            f"  → {label} erreichbar"
            + (f" ({'TLS' if use_ssl else 'ohne TLS'})"),
            flush=True,
        )
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
    """Öffentliche Fulcrum-Onions — nur wenn Clearnet öffentlich fehlt."""
    if not _load_public_onion_endpoints(args, env):
        return None
    try:
        return _setup_public_onion_rotation(args, env, interactive=interactive)
    except SystemExit as exc:
        _log_quelle(f"→ öffentliche Onion-Server nicht nutzbar: {exc}")
        return None


def _public_onion_latency_limit(env: dict[str, str]) -> float | None:
    """
    Schwelle in Sekunden für das Onion-Latenz-Gate.

    ``None`` = Gate aus (``PUBLIC_ONION_LATENCY_SECONDS=0`` / negativ).
    """
    raw = (env.get("PUBLIC_ONION_LATENCY_SECONDS") or "").strip()
    if raw:
        try:
            val = float(raw.replace(",", "."))
        except ValueError:
            val = PUBLIC_ONION_LATENCY_GATE_SECONDS
        if val <= 0:
            return None
        return val
    return PUBLIC_ONION_LATENCY_GATE_SECONDS


def _measure_onion_get_history_latency(backend) -> float | None:
    """
    Eine Probe-``get_history`` (Dummy-Scripthash) und Wandzeit in Sekunden.

    Ohne Retries — das Gate soll schnell entscheiden, nicht 3×30 s hängen.
    ``None`` bei Fehler (dann gilt der Pool nicht als „zu langsam“).
    """
    from fulcrum import _PROBE_SCRIPT_HASH

    clients = getattr(backend, "_clients", None)
    client = clients[0] if clients else backend
    t0 = time.monotonic()
    try:
        once = getattr(client, "_request_once", None)
        if callable(once):
            lock = getattr(client, "_lock", None)
            if lock is not None:
                with lock:
                    once(
                        "blockchain.scripthash.get_history",
                        [_PROBE_SCRIPT_HASH],
                    )
            else:
                once(
                    "blockchain.scripthash.get_history",
                    [_PROBE_SCRIPT_HASH],
                )
        else:
            backend.request(
                "blockchain.scripthash.get_history",
                [_PROBE_SCRIPT_HASH],
            )
    except Exception:
        return None
    return time.monotonic() - t0


def _nach_oeffentlichem_onion_latenz(
    pool,
    args,
    env: dict[str, str],
    *,
    allow_bip158_fallback: bool,
    interactive: bool,
) -> tuple[str, object] | None:
    """
    Latenz-Gate nur für Auto-Priorität (öffentliches Onion nach BIP-158-Fail).

    Zu langsam + BIP-158 erreichbar → BIP-158 binden (kein Mid-Scan-Hop).
    Zu langsam ohne BIP-158 → klare Warnung; interaktiv Abbruch möglich.
    Explizites ``--rpc-only`` (``allow_bip158_fallback=False``) überspringt
    das Gate.
    """
    if not allow_bip158_fallback:
        return "fulcrum", pool

    limit = _public_onion_latency_limit(env)
    if limit is None:
        return "fulcrum", pool

    _log_quelle("Prüfe Latenz öffentliches Onion-Electrs…")
    sekunden = _measure_onion_get_history_latency(pool)
    if sekunden is None:
        return "fulcrum", pool
    if sekunden <= limit:
        return "fulcrum", pool

    _log_quelle(
        f"Öffentliches Onion-Electrs langsam "
        f"(Probe {sekunden:.1f}s > {limit:.0f}s)."
    )

    bip = _try_bip158_backend(args, env)
    if bip:
        try:
            pool.close()
        except Exception:
            pass
        _log_quelle(
            "→ wechsle zu BIP-158 Compact Filter "
            "(Onion für diese Session zu langsam)."
        )
        return "bip158", bip

    _log_quelle(
        "Onion ist die einzige Option und wird langsam — "
        "Scan kann sehr lange dauern."
    )
    if interactive:
        print("Trotzdem fortfahren? [j/N]: ", end="", flush=True)
        from interact import prompt_yes_no

        if not prompt_yes_no(default_yes=False):
            try:
                pool.close()
            except Exception:
                pass
            _log_quelle("Abgebrochen (Onion zu langsam).")
            return None
    return "fulcrum", pool


def _setup_public_clearnet_fulcrum(args, env: dict[str, str]):
    """Öffentliche Fulcrum-Server über Clearnet (vor öffentlichem Onion)."""
    from fulcrum import RotatingFulcrumPool

    # Vor der Suche ansagen — sonst wiederholt der 10s-Herzschlag die
    # letzte Probe, während Clearnet nur nach stdout schreibt.
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
    # Tor-Autostart für öffentliche Onions nicht als Flaschenhals stehen lassen.
    try:
        from core.source import _loese_oeffentliches_onion_tor

        _loese_oeffentliches_onion_tor(on_log=_log_quelle)
    except Exception:
        pass
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
    Öffentliche Electrum nur nach Bestätigung: Clearnet vor Onion.
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

    # Clearnet vor öffentlichem Onion: nach Opt-in kein Tor-Flaschenhals,
    # solange Clearnet-Electrs erreichbar sind.
    pool = _setup_public_clearnet_fulcrum(args, env)
    if pool:
        return "fulcrum", pool, None

    pool = _try_public_onion_fulcrum(args, env, interactive=interactive_onion)
    if pool:
        gewählt = _nach_oeffentlichem_onion_latenz(
            pool,
            args,
            env,
            allow_bip158_fallback=include_bip158,
            interactive=interactive_onion,
        )
        if gewählt:
            return gewählt[0], gewählt[1], None
        return None

    return None


def _try_public_electrum_fuer_verlauf(
    args,
    env: dict[str, str],
    *,
    interactive_onion: bool = False,
    allow_bip158_fallback: bool = True,
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

    pool = _setup_public_clearnet_fulcrum(args, env)
    if pool:
        _log_quelle(
            "Verlauf: öffentliche Electrum-Server (Clearnet) — get_history "
            "(Privatsphäre mäßig)."
        )
        return "fulcrum", pool

    pool = _try_public_onion_fulcrum(args, env, interactive=interactive_onion)
    if pool:
        gewählt = _nach_oeffentlichem_onion_latenz(
            pool,
            args,
            env,
            allow_bip158_fallback=allow_bip158_fallback,
            interactive=interactive_onion,
        )
        if not gewählt:
            return None
        quelle, backend = gewählt
        if quelle == "bip158":
            _log_quelle(
                "Verlauf: BIP-158 Compact Filter — Historie per "
                "Blockwalk/Cache (Onion zu langsam)."
            )
            return quelle, backend
        _log_quelle(
            "Verlauf: öffentliche Electrum-Server (Onion) — get_history "
            "(Privatsphäre mäßig; Clearnet nicht erreichbar)."
        )
        return "fulcrum", backend
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
    4. öffentliche Electrum (Clearnet, sonst Onion) nach Bestätigung
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
        args,
        env,
        interactive_onion=interactive_onion,
        allow_bip158_fallback=include_bip158,
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
    from core.bitcoind_rpc import stelle_tx_lookup_rollen

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

    # Core optional: lokal (UTXO-Slot) bis pruneheight, sonst Lookup (Start9).
    lokal_core = None
    archival_core = None
    lokal_prune = None
    try:
        lokal_core, archival_core, lokal_prune = stelle_tx_lookup_rollen(
            env, timeout=30.0,
        )
        if lokal_core is not None:
            ph = (
                f"pruneheight {lokal_prune}"
                if lokal_prune and lokal_prune > 0
                else "nicht gepruned"
            )
            _log_quelle(
                f"→ Core lokal für Tx/Block ({lokal_core.cfg.ziel}, {ph})"
            )
        if archival_core is not None:
            _log_quelle(
                f"→ Core-Lookup für Tx/Block ({archival_core.cfg.ziel})"
            )
        if lokal_core is None and archival_core is None:
            _log_quelle("→ kein Core-RPC für Tx-Lookup konfiguriert")
    except Exception as exc:
        _log_quelle(f"→ Core-RPC für Tx-Lookup nicht nutzbar: {exc}")

    def _get_tx_bip158(txid: str) -> dict:
        return fetch_tx_p2p_mit_fallback(
            client,
            txid,
            local_core=lokal_core,
            archival_core=archival_core,
            local_pruneheight=lokal_prune,
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
        "core_rpc": archival_core or lokal_core,
        "core_local": lokal_core,
        "core_archival": archival_core,
        "core_local_pruneheight": lokal_prune,
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

    if _oeffentliche_electrum_erlaubt(env, args):
        grund = (
            "Keine Datenquelle erreichbar: eigener Electrum-Server und "
            "BIP-158 fehlen, öffentliche Electrum-Server (Onion/Clearnet) "
            "waren trotz Freigabe nicht nutzbar (Tor/Netz/Liste prüfen)."
        )
    else:
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
        from core.bitcoind_rpc import (
            fetch_tx_core_mit_rollen,
            stelle_tx_lookup_rollen,
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
        # Core nur Ausnahme, wenn Electrs die Tx nicht liefert.
        _core_lokal = _core_arch = None
        _core_ph = None
        try:
            _env_tx = _load_dotenv()
            _core_lokal, _core_arch, _core_ph = stelle_tx_lookup_rollen(
                _env_tx, timeout=20.0,
            )
        except Exception:
            pass

        def raw_get_tx(txid: str) -> dict:
            try:
                return fetch_tx_fulcrum(fulcrum, txid)
            except Exception as electrs_exc:
                if _core_lokal is None and _core_arch is None:
                    raise
                try:
                    return fetch_tx_core_mit_rollen(
                        txid,
                        local=_core_lokal,
                        archival=_core_arch,
                        local_pruneheight=_core_ph,
                        on_log=_log_quelle,
                    )
                except Exception:
                    raise electrs_exc from None

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
        adressen = derive_addresses_at_index(xpub, change, i)
        if not adressen:
            break
        if any(address_has_received(a) for a in adressen):
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
                derive_addresses_at_index,
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
                for addr in derive_addresses_at_index(xpub, change, i):
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

    pruned, _live_snapshot = _prune_cached_utxos(
        cached, fetch_address_utxos,
    )
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


def _utxo_scan_scantxoutset_vorrang(fulcrum=None, env: dict[str, str] | None = None) -> bool:
    """
    Wann Bitcoin Core ``scantxoutset`` vor dem Electrum-Gap-Scan steht.

    Reihenfolge für den **reinen UTXO-Bestand** (Alltag = Tempo):

    1. Electrs/Fulcrum **im LAN** — Gap-Scan nur über genutzte Adressen
    2. Core ``scantxoutset`` — bevorzugt ``UTXO_RPC_*`` (lokaler Node),
       sonst Lookup-``NODE_IP`` (z. B. Start9)
    3. Electrs Onion / BIP-158 / öffentlich

    Lokaler scantxoutset bleibt Fallback (Vollständigkeit ohne Gap-Policy,
    Privatsphäre), nicht der Default neben schnellem LAN-Electrs.
    """
    _ = env  # reserviert (Tests/Caller); Priorität hängt am Fulcrum-Transport
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
    env = _load_dotenv()
    if not _utxo_scan_scantxoutset_vorrang(fulcrum, env=env):
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
        from core.jobs import ist_abbruch

        if ist_abbruch(exc):
            raise
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
        # Electrum/Fulcrum liefert den Bestand am Tip — Höhe mitschreiben,
        # damit späterer P2P-Lauf Tip-Nachzug machen kann.
        if fulcrum is not None and not is_list_abort_requested():
            try:
                from fulcrum import get_chain_tip_height

                tip_hoehe = int(get_chain_tip_height(fulcrum, force=True))
            except Exception:
                tip_hoehe = None
    if is_list_abort_requested() and not utxos:
        return list(zwischen) if zwischen else utxos
    # Bestand am Tip: BIP-158-Fullscan oder erfolgreicher Electrum-Gap.
    # Abbruch: kein Tip / fullscan_ok=False → nächster P2P-Lauf Turbo-Erstscan.
    full_ok = None
    if is_list_abort_requested():
        if source == "bip158":
            full_ok = False
            tip_hoehe = None
    elif source == "bip158":
        full_ok = True
    elif tip_hoehe and tip_hoehe > 0:
        # Fulcrum/Electrum (und Core+Fulcrum-Tip): Flag heißt historisch
        # bip158_fullscan_ok, meint aber „UTXO-Stand am Tip bekannt“.
        full_ok = True
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
        bip158_fullscan_ok=full_ok,
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
    nur_bekannte: bool = False,
) -> list[dict] | None:
    """
    Leichtes Nachziehen bis Chain-Tip (Start-Sync / Light-Update).

    Nur mit bestehendem UTXO-Cache. **Kein** Fullscan, **kein** scantxoutset.

    Produktregel:
    1. **BIP-158 inkrementell**, wenn Compact-Filter-Fetcher und
       ``scan_tip_height`` vorhanden (auch wenn Electrs/Core die allgemeine
       Datenquelle sind) — entfällt bei ``nur_bekannte``.
    2. Sonst **Electrs/Adresse light**: nur bekannte UTXOs auf spent prüfen
       + Gap/Lookahead ab ``scan_end_index`` — nicht alle Indizes #0…N.
       Bei ``nur_bekannte``: nur bekannte UTXOs/Adressen, kein Gap.
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
        if nur_bekannte:
            on_progress(f"Aktualisiere {label} (nur bekannte UTXOs)…")
        else:
            on_progress(f"Aktualisiere {label} bis Chain-Tip…")

    # --- 1) BIP-158 inkrementell (bevorzugt für Tip-Nachzug) ---------------
    # Bei nur_bekannte: kein Filter-Walk — nur Light auf bekannte Adressen.
    bip_fetch = bip158_fetch_wallet_utxos
    if bip_fetch is None and source == "bip158":
        bip_fetch = fetch_wallet_utxos
    if not nur_bekannte and bip_fetch is not None and tip_i is not None:
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
            from core.jobs import ist_abbruch

            if ist_abbruch(exc):
                raise
            # Multisig/Deskriptor oder Peer-Fehler: nicht den ganzen Wallet
            # überspringen — Electrs light hält den Cache frisch.
            msg = (
                f"{label}: BIP-158 fehlgeschlagen ({exc}) — "
                "weiche auf Electrs light aus…"
            )
            print(f"  ⚠️  {msg}", flush=True)
            if on_progress:
                on_progress(msg)
    if not nur_bekannte and bip_fetch is not None and tip_i is None:
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
    if nur_bekannte:
        print(
            f"\nAktualisiere {label} (Light: nur {len(alt)} bekannte UTXO(s), kein Gap)",
            flush=True,
        )
        if on_progress:
            on_progress(
                f"{label}: prüfe {len(alt)} bekannte UTXO(s) (kein Gap)…"
            )
    else:
        print(
            f"\nAktualisiere {label} (Light: bekannte UTXOs + Gap ab #{scan_end})",
            flush=True,
        )
        if on_progress:
            on_progress(
                f"{label}: prüfe {len(alt)} bekannte UTXO(s), Gap ab #{scan_end}…"
            )

    # Ein listunspent-Durchgang: Prune + neue Empfänge auf denselben Adressen.
    # Früher: prune listunspent + extra_same listunspent = doppelt so langsam.
    live, extra_same = _prune_cached_utxos(
        alt,
        fetch_address_utxos,
        verify_utxo_spent=verify_utxo_spent,
        fetch_addresses_utxos=fetch_addresses_utxos,
        on_progress=on_progress,
        progress_label=f"Live {label}",
    )
    # verify_utxo_spent-Pfad liefert kein Adress-Snapshot → einmal nachholen.
    if (
        not extra_same
        and addrs_cache
        and (fetch_address_utxos or fetch_addresses_utxos)
    ):
        extra_same = _fetch_address_batch_utxos(
            addrs_cache,
            fetch_address_utxos,
            fetch_addresses_utxos,
            progress_label=f"Live {label}",
            on_progress=on_progress,
        )
    live = _mempool_pending_nach_prune(
        xpub,
        alt,
        live,
        fulcrum=fulcrum,
        wallet=wallet,
        cache_dir=cache_dir,
    )
    new_end = scan_end
    extra_utxos: list[dict] = []
    extra_window: list[dict] = []

    if not nur_bekannte and fulcrum is not None:
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
    elif not nur_bekannte:
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
    tip_fuer_cache = _scan_tip_anheben(tip_i, cache_dir, fulcrum=fulcrum)
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
    nur_bekannte: bool = False,
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
                nur_bekannte=nur_bekannte,
            )
        except Exception as exc:
            from core.jobs import ist_abbruch

            if ist_abbruch(exc):
                raise
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