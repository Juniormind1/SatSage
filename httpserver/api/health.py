"""Health-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations


def api_health(state) -> dict:
    from core.bitcoind_rpc import rpc_allowlist_status
    from core.version import version as app_version

    # Ohne Login erreichbar — nur das Flag, keine Methoden-/Detailtexte.
    return {
        "ok": True,
        "version": app_version(),
        "managed_by": state.managed_by,
        "rpc_allowlist_verstoss": bool(rpc_allowlist_status()["verstoss"]),
    }
