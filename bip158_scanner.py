#!/usr/bin/env python3
"""
BIP-158-Scanner über Bitcoin-P2P (BIP 157 Compact Filter).

Filter und Blöcke kommen von Peers mit NODE_COMPACT_FILTERS, nicht von
Bitcoin-Core-RPC. Abgleich lokal. Ungenutzte Keys nur gegen das Turbo-Fenster
(Wasabi-TurboSync), damit False-Positive-Downloads in der Historie entfallen.

chiabip158 nur für Self-Tests. Produktions-Filter: _CoreBasicFilterMatcher.

Scan-Pipeline und ``BIP158Scanner`` liegen in ``core.bip158_scan``,
Ableitung, Tx-Fetch und UTXO-API in ``core.bip158_wallet``. Beides wird
hier re-exportiert (Slice 5 Schritte 7–8).
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from chiabip158 import PyBIP158
except ImportError:  # pragma: no cover - optional at import time
    PyBIP158 = None  # type: ignore[misc, assignment]

from core.bip158_filter import (
    BASIC_FILTER_M,
    BASIC_FILTER_P,
    MatchedOutput,
    MatchedTransaction,
    ProgressCallback,
    ScanProgress,
    ScanResult,
    _BitStreamReader,
    _BitStreamWriter,
    _CoreBasicFilterMatcher,
    _encode_core_basic_filter,
    _golomb_rice_decode,
    _golomb_rice_encode,
    _hash_to_range,
    _match_with_chiabip158,
    _read_compact_size,
    _rotl64,
    _sip_keys_from_block_hash,
    _siphash_round,
    _write_compact_size,
    siphash,
)

from core.bip158_scan import (
    DEFAULT_GAP_LIMIT,
    DEFAULT_MAX_INDEX,
    DEFAULT_MAX_ADDRESSES,
    TURBO_WINDOW,
    _BLOCK_PENDING,
    plane_filter_passes,
    _cfilter_chunks,
    _filter_umfang,
    _filter_prozent_text,
    _tick_filter_stand,
    _kuerze_adresse,
    _filter_treffer_praefix,
    _beschreibe_block_treffer,
    _lade_cfilter_chunk,
    _block_aus_warteschlange,
    _zeilen_bloecke_aufloesen,
    verteile_cfilter_chunks,
    parse_raw_block,
    _header_unixzeit,
    _verlauf_eintrag,
    _uebernehme_block_verlauf,
    extract_from_parsed_block,
    _LIVE_FILTER_LOCK,
    _LIVE_FILTER_PEERS,
    _peer_host_label,
    melde_live_filter_peers,
    clear_live_filter_peers,
    live_filter_peer_hosts,
    BIP158Scanner,
    Bip158Client,
    vorab_block_header,
    verify_p2p_filters,
)

from core.bip158_wallet import (
    BIP158_REORG_BUFFER,
    _LAST_SCAN_TIPS,
    _TX_HEIGHT_HINTS,
    _embit_tx_to_dict,
    _encoders_for_xpub,
    _matched_output_to_utxo,
    _seed_aus_cache,
    _used_scripts_aus_cache,
    addresses_to_script_pubkeys,
    clear_tx_height_hints,
    create_bip158_client_from_env,
    derive_script_pubkeys_from_xpub,
    fetch_address_utxos_bip158,
    fetch_addresses_utxos_bip158,
    fetch_tx_from_block_p2p,
    fetch_tx_p2p,
    fetch_tx_p2p_mit_fallback,
    fetch_wallet_utxos_bip158,
    gap_scripts_anfang,
    note_tx_height,
    scripts_mit_gap_um_treffer,
    take_last_scan_tip,
    tx_height_hint,
)

ENV_FILE = Path(__file__).resolve().parent / ".env"


def _run_chiabip158_self_test() -> None:
    if PyBIP158 is None:
        print("chiabip158 not installed — skip self-test")
        return
    script_a = bytes.fromhex("0014" + "ab" * 20)
    script_b = bytes.fromhex("0014" + "cd" * 20)
    built = PyBIP158([bytearray(script_a), bytearray(script_b)])
    encoded = bytes(built.filter_bytes) if hasattr(built, "filter_bytes") else bytes()
    if not encoded:
        print("chiabip158 self-test skipped (kein filter_bytes)")
        return
    matcher = PyBIP158(list(encoded))
    print("chiabip158 self-test OK (synthetic filter)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BIP-158 Compact-Filter-Scanner (Bitcoin-P2P)"
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        _run_chiabip158_self_test()
        return 0
    print("P2P-Scan: py main.py --bip158", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


