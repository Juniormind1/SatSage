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
import sys
import time
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

from core.chain_sources import (
    DEFAULT_BIP158_START_HEIGHT,
    ELECTRUM_SERVERS_FILE,
    FULCRUM_CONNECT_TIMEOUT,
    MAX_PUBLIC_ONION_SERVERS,
    MIN_PUBLIC_ONION_POOL,
    PUBLIC_ONION_LATENCY_GATE_SECONDS,
    PUBLIC_ONION_PROBE_WORKERS,
    SCAN_POOL_WORKERS,
    apply_data_source_choice,
    resolve_verbose_from_env,
    connection_error_hint,
    is_own_fulcrum_backend,
    privacy_notice_for_source,
    tls_should_try_opposite,
    try_bip158_fetch_for_tip_sync,
    wrap_get_tx_with_immutable_cache,
    _build_blockchain_fetchers,
    _build_clearnet_fulcrum_targets,
    _data_source_is_explicit,
    _dedupe_clearnet_fulcrum_hits,
    _default_fulcrum_port,
    _default_fulcrum_ssl,
    _env_port,
    _format_fulcrum_route,
    _fulcrum_transport_ist_lan,
    _is_private_fulcrum_host,
    _load_public_onion_endpoints,
    _log_quelle,
    _mache_prefetch,
    _measure_onion_get_history_latency,
    _nach_oeffentlichem_onion_latenz,
    _normalize_fulcrum_host,
    _oeffentliche_electrum_erlaubt,
    _open_scan_pool,
    _parse_env_bool,
    _parse_tor_proxy,
    _print_connection_error,
    _print_public_onion_probe_result,
    _probe_clearnet_fulcrum,
    _probe_public_onion_endpoint,
    _public_onion_latency_limit,
    _quelle_log_lock,
    _quelle_log_zuletzt,
    _require_tor_proxy,
    _reset_quelle_log,
    _resolve_data_source,
    _resolve_own_lan_endpoint,
    _resolve_own_tor_endpoint,
    _setup_bip158_client,
    _setup_blockchain_client,
    _setup_public_clearnet_fulcrum,
    _setup_public_onion_rotation,
    _setup_verlauf_client,
    _try_bip158_backend,
    _try_data_source_priority_chain,
    _try_fulcrum_endpoint,
    _try_own_fulcrum_client,
    _try_public_electrum_fuer_verlauf,
    _try_public_onion_fulcrum,
    _try_verlauf_priority_chain,
    _wants_bip158,
    _wants_fulcrum,
)

from core.sanctions_pool import (
    SANCTIONS_CLEARNET_MAX_SERVERS,
    SANCTIONS_CLEARNET_MIN_SERVERS,
    SANCTIONS_CLEARNET_PROBE_TIMEOUT,
    SANCTIONS_CLEARNET_PROBE_WORKERS,
    SANCTIONS_OWN_NODE_WORKERS,
    build_sanctions_fulcrum_fetchers,
    make_cached_fulcrum_get_tx,
    resolve_sanctions_clearnet_fulcrum,
    resolve_sanctions_clearnet_pool,
    resolve_sanctions_preferred_client,
    resolve_sanctions_preferred_pool,
    _open_own_sanctions_pool,
    _print_sanctions_clearnet_pool,
    _sanctions_fulcrum_exclude_hosts,
)



from core.wallet_sync_engine import (
    BIP44_GAP_LIMIT,
    UTXO_SCAN_GAP_LIMIT,
    _adressen_bis_index,
    _collect_used_chain_indices_gap,
    _ensure_address_cached,
    _full_rescan_xpub,
    _light_rescan_xpub,
    _merge_cached_utxos,
    _mempool_pending_nach_prune,
    _scan_index_cap_per_chain,
    _scan_xpub_utxos,
    _supplement_cache_address,
    _try_scantxoutset_xpub,
    _utxo_scan_scantxoutset_vorrang,
    _verify_cached_utxos_against_chain,
    discover_wallet_scan_addresses,
    ermittle_first_seen,
    resolve_wallet_utxos,
    resolve_wallet_verlauf,
    sync_wallets_zum_tip,
    sync_xpub_zum_tip,
)


MAX_TRACE_DEPTH = 20


MAX_TRACE_ADDRESS_SEARCH = 500

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