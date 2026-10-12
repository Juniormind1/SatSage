"""
Anwendungsversion.

Reihenfolge:
1. ``git describe --tags --always --dirty`` im Projektroot (führendes ``v``
   entfernt), sofern ein Git-Checkout vorliegt und git verfügbar ist.
2. Datei ``VERSION`` (PyInstaller-Binaries, StartOS, Specter-Plugin, Tarballs).
3. ``_FALLBACK``.
"""
from __future__ import annotations

from functools import lru_cache
import subprocess
import sys
from pathlib import Path

from core.paths import resource_dir

#: Fallback, falls die Datei fehlt (kaputter Checkout / Spec ohne Bundle).
_FALLBACK = "0.9"


_REPO_ROOT = Path(__file__).resolve().parents[1]


def git_version(root: Path | None = None) -> str | None:
    """Version aus ``git describe`` oder ``None`` (kein Repo/kein git)."""
    root = root or _REPO_ROOT
    if getattr(sys, "frozen", False) or not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=root, capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    return out[1:] if out[:1] in ("v", "V") else out


def datei_version() -> str:
    """Version aus der Datei ``VERSION`` (oder ``_FALLBACK``)."""
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


@lru_cache(maxsize=1)
def version() -> str:
    """Aktuelle SatSage-Version, z. B. ``\"0.9.9.5-57-g2592306\"``."""
    return git_version() or datei_version()
