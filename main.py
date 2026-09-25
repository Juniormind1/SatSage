#!/usr/bin/env python3
"""
Multi-XPUB + Taproot Analyzer für Wasabi / Standard Wallet
Analysiert eine TxID oder unspent Wallet-Adresse und zeigt Herkunft der Sats.

Datenquelle: eigener Electrum-Server (Fulcrum/electrs), P2P-BIP-158, öffentliche Onions, Clearnet.
"""

from __future__ import annotations

import argparse
from datetime import timezone
from pathlib import Path

# Python 3.10-kompatibel (datetime.UTC erst ab 3.11)
UTC = timezone.utc

from display import set_verbose

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

from core.env_wallets import (
    UNLESBAR_HINWEIS,
    _indexed_env_values,
    _max_addresses_per_xpub_from_env,
    _script_types_from_env,
    _wallet_names_from_env,
    _xpubs_from_env,
    resolve_wallets_beim_start_aktualisieren,
    resolve_wallets_nur_bekannte_utxos,
    wallets_aus_env_datei,
)
from core.launch_checks import (
    _escape_for_applescript,
    launch_check_fulcrum_tor_external,
)
from core.receive_address import (
    _receive_index_for_address,
    next_unused_receive_address_fulcrum,
    next_unused_receive_index,
)
from core.utxo_report import (
    _ESTIMATED_HEIGHT_CACHE,
    _extract_addresses,
    _extract_value_btc,
    _extract_value_sats,
    _format_tx_time,
    _format_utxo_status,
    _print_utxo_rank_row,
    _resolve_utxo_ingress_address,
    _tx_block_height,
    _tx_block_time,
    estimate_block_height_for_date,
    list_top_wallet_utxos,
    print_analyzed_utxo_ingress_report,
    print_utxo_rank_entries,
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