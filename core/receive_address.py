"""
Nächste unbenutzte Empfangsadresse (Gap-Limit / Fulcrum).

Aus main.py ausgelagert (Slice 3 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.
"""
from __future__ import annotations

from embit.bip32 import HDKey

from core.derivation import derive_receive_address_at_index
from core.wallet_context import MAX_TRACE_ADDRESS_SEARCH, WalletContext
from core.wallet_sync_engine import BIP44_GAP_LIMIT


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
