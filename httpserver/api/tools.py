"""Kleine lokale Werkzeuge — auswerten, ohne Chain-Lookup."""

from __future__ import annotations

from typing import Any


def api_tools_adresse(state: Any, payload: dict | None) -> dict:
    """Gehört die Adresse zu einem hinterlegten Wallet? Auch unbenutzt."""
    from core.adresse_werkzeug import pruefe_eigene_adresse

    koerper = payload or {}
    return pruefe_eigene_adresse(
        state.wallet_ctx,
        str(koerper.get("address") or ""),
    )
