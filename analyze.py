"""Tx/UTXO-Herkunftsanalyse und Trace (ohne interaktive Prompts)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.utxo_origin import (
    MAX_TRACE_DEPTH,
    _EphemeralProgress,
    _hat_tax_horizon,
    _is_own_address,
    _is_own_output,
    _knoten_txid_vout,
    _match_own_address,
    _origin_hat_luecken,
    _parse_utxo_ref,
    _quelle_hat_luecke,
    _resolve_input_output,
    _seed_memo_fertige_unterbaeume,
    hat_brauchbaren_teilfortschritt,
    trace_utxo_origin,
    vertiefe_herkunft_luecken,
    vertiefe_tax_horizon,
)

from core.utxo_ingress_report import (
    TxFollowupContext,
    UtxoFollowupContext,
    _analyze_utxo_funding,
    _collect_external_ingress_events,
    _collect_internal_creator_txs,
    _collect_tax_horizon_events,
    _collect_wallet_ingress_events,
    _external_ingress_extrema,
    _find_wallet_entries,
    _format_amount_display,
    _format_utxo_count,
    _group_external_sources,
    _oldest_external_ingress,
    _print_external_groups,
    _print_funding_trace,
    _print_wallet_entries,
    _print_youngest_sats_summary,
    _run_tx_oriented_followups,
    _sum_external_sats,
    _sum_internal_sats,
    _youngest_external_ingress,
    _youngest_tax_horizon,
    _youngest_wallet_ingress,
    persist_utxo_ingress,
)

from core.tx_utxo_analyze import (
    _print_utxo_batch_progress,
    analyze_address_utxos,
    analyze_tx,
    trace_known_utxos,
)

from core.sanction_hops import (
    SanctionHitFound,
    _coinjoins_zusammenfuehren,
    _sanction_coinjoin_eintrag,
    _sanction_progress_status,
    scan_external_sanction_hops,
)

from core.wallet_sanctions_check import (
    _FortschrittsAdapter,
    _check_wallet_utxos_parallel,
    _event_gegen_liste,
    _events_aus_origin_tree,
    _pruefe_ein_utxo,
    _sammle_sanction_events_live,
    check_wallet_utxos_sanctions,
    print_sanction_check_report,
)

from core.sanctioned_address_utxos import (
    _UNMAPPED_SANCTION_ENTITY,
    _bucket_utxos_by_sanction_entity,
    _call_fetch_addresses_utxos,
    _print_sanction_utxo_items,
    _sanctioned_input_sats,
    _scan_sanctioned_address_utxos_parallel,
    print_sanctioned_utxo_findings,
    print_sanctioned_utxo_scan_report,
    scan_sanctioned_address_utxos,
    scan_sanctioned_addresses_fulcrum_sync,
)

from core.sanctioned_output_trace import (
    _build_entity_trace_entry,
    _collect_sanction_output_traces,
    _print_sanction_trace_entries,
    _trace_sanctioned_outputs_by_entity_parallel,
    print_sanctioned_entity_trace_report,
    print_sanctioned_output_trace_report,
    trace_sanctioned_outputs_by_entity,
    trace_sanctioned_outputs_since,
)


if TYPE_CHECKING:
    from main import WalletContext


def _main():
    import main
    return main
