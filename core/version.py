"""
Anwendungsversion — einzige Quelle: Datei ``VERSION`` im Projektroot.

Nur Maintainer setzen neue Nummern (Inhalt von ``VERSION`` ändern).
Build, API und UI lesen nur; nichts erhöht die Version automatisch.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from core.paths import resource_dir

#: Fallback, falls die Datei fehlt (kaputter Checkout / Spec ohne Bundle).
_FALLBACK = "0.9"


@lru_cache(maxsize=1)
def version() -> str:
    """Aktuelle SatSage-Version, z. B. ``\"0.9\"``."""
    pfad = resource_dir() / "VERSION"
    try:
        text = pfad.read_text(encoding="utf-8").strip()
    except OSError:
        return _FALLBACK
    # Erste nicht-leere Zeile; Kommentare mit # am Zeilenanfang ignorieren.
    for zeile in text.splitlines():
        zeile = zeile.strip()
        if zeile and not zeile.startswith("#"):
            return zeile
    return _FALLBACK
