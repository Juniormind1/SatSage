"""Rückwärts-Walk über Tx-Inputs (vin → prevout).

Dünne Re-Export-Fassade. Der Walk lebt in ``core.trace``.
Symbol-Identität: ``trace_engine.X is core.trace.X``.
"""
from __future__ import annotations

from core.trace import (
    FULL_RESOLUTION_INPUT_LIMIT,
    MAX_TRACE_DEPTH,
    BackwardWalkState,
    CoinbaseFunding,
    FundingEdge,
    FundingInput,
    PrevoutRef,
    ProgressCallback,
    UnresolvedExternalBatch,
    UnresolvedPrevout,
    _abbruch_durchreichen,
    _funding_edge_from_vin,
    _mit_vorgaengerzeit,
    is_own_output,
    iter_funding_inputs,
    iter_trace_funding_inputs,
    match_own_address,
    parse_utxo_ref,
    resolve_vin_prevout,
    utxo_ref,
    visit_utxo,
)
