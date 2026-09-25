"""
Rückwärtskompatible Fassade.

Implementierung: ``core.wallet_export_import`` (Sparrow + Wasabi, Auto-Erkennung).
"""
from __future__ import annotations

from core.wallet_export_import import (  # noqa: F401
    WalletExportErgebnis as SparrowImportErgebnis,
    parse_sparrow_dateien,
    parse_wallet_export_dateien,
)
