"""Hop-weiser Herkunfts-Walk über viele UTXOs (Wald).

Statt jeden UTXO depth-first zu Ende zu führen, expandiert eine Runde
genau eine Schicht jeder noch offenen Wurzel. Kurze Ketten sind nach
Runde 1 fertig; Remix-Nüsse laufen in späteren Runden weiter.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from core.trace import MAX_TRACE_DEPTH
from core.utxo_origin import (
    _hat_pending,
    _hat_tax_horizon,
    _origin_hat_luecken,
    hat_brauchbaren_teilfortschritt,
    trace_utxo_origin,
    vertiefe_herkunft_luecken,
)

if TYPE_CHECKING:
    from core.wallet_context import WalletContext

UtxoKey = tuple[str, int]


def _wald_offen(node: dict | None) -> bool:
    """Weiter in der nächsten Runde: pending-Stubs oder Steuer-Horizont."""
    if not isinstance(node, dict):
        return True
    if _hat_pending(node) or _hat_tax_horizon(node):
        return True
    return False


def _expand_wurzel(
    node: dict | None,
    txid: str,
    vout: int,
    get_tx,
    own_addresses: set,
    *,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    progress=None,
    alle_eigenen_inputs: bool = False,
    memo: dict | None = None,
    stop_before_ts: int | None = None,
    on_teilstand=None,
) -> dict | None:
    """Eine Hop-Schicht dieser Wurzel."""
    walk = dict(
        wallet=wallet,
        cache_dir=cache_dir,
        fetch_address_utxos=fetch_address_utxos,
        cache_source=cache_source,
        progress=progress,
        alle_eigenen_inputs=alle_eigenen_inputs,
        memo=memo,
        on_teilstand=on_teilstand,
    )
    if node is None:
        return trace_utxo_origin(
            get_tx,
            txid,
            vout,
            own_addresses,
            hop_budget=1,
            stop_before_ts=stop_before_ts,
            **walk,
        )
    if (
        hat_brauchbaren_teilfortschritt(node)
        or _origin_hat_luecken(node)
    ):
        return vertiefe_herkunft_luecken(
            node,
            get_tx,
            own_addresses,
            hop_budget=1,
            **walk,
        )
    return node


def wald_schicht(
    baeume: dict[UtxoKey, dict | None],
    offen: list[UtxoKey],
    get_tx,
    own_addresses: set,
    *,
    wallet: WalletContext | None = None,
    cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    progress=None,
    alle_eigenen_inputs: bool = False,
    memo: dict | None = None,
    stop_before_ts: int | None = None,
    on_teilstand: Callable | None = None,
    on_wurzel: Callable | None = None,
) -> tuple[list[UtxoKey], list[UtxoKey]]:
    """
    Eine Runde: jede offene Wurzel um einen Hop.

    *baeume* wird in place aktualisiert. Rückgabe ``(weiter, fertig)``.
    *on_wurzel(key, node)* nach jeder Wurzel in dieser Runde.
    """
    weiter: list[UtxoKey] = []
    fertig: list[UtxoKey] = []
    for key in offen:
        txid, vout = key
        if callable(on_wurzel):
            try:
                on_wurzel(key, baeume.get(key))
            except Exception:
                pass
        node = _expand_wurzel(
            baeume.get(key),
            txid,
            vout,
            get_tx,
            own_addresses,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
            progress=progress,
            alle_eigenen_inputs=alle_eigenen_inputs,
            memo=memo,
            stop_before_ts=stop_before_ts,
            on_teilstand=on_teilstand,
        )
        baeume[key] = node
        if node is not None and _wald_offen(node):
            weiter.append(key)
        else:
            fertig.append(key)
    return weiter, fertig


def wald_max_runden() -> int:
    """Sicherheitskappe: eine Schicht je Tiefe plus etwas Luft."""
    return int(MAX_TRACE_DEPTH) + 2
