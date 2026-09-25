"""Health-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations


def api_health(state) -> dict:
    from core.version import version as app_version

    return {
        "ok": True,
        "version": app_version(),
        "managed_by": state.managed_by,
    }
