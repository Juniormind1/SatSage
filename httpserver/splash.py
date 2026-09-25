"""Splash-Helfer (pyi/Tk) — aus server.py extrahiert (Modularisierung).

Fassade bleibt in server.py / httpserver.main_cli für Late-Imports.
"""

from __future__ import annotations

import os
import sys
import threading
import time

from core import splash_ui as splash_ui_mod


def lauf_splash_kind_einstieg(argv=None) -> int:
    """Früher --splash-only-Einstieg (vor schweren Imports in server.py)."""
    from core.splash_ui import lauf_splash_kind

    return lauf_splash_kind(argv if argv is not None else sys.argv)


# pyi_splash nur mit Bootloader (_PYI_SPLASH_IPC). Sonst Tk-Fallback (macOS).
_splash_mod = None  # False = kein pyi; Modul = aktiv
_splash_tk = False
_splash_browser_gesehen = threading.Event()
_splash_zu = threading.Event()


def _splash_laden():
    """Lädt pyi_splash einmalig, oder None wenn nicht verfügbar."""
    global _splash_mod
    if _splash_mod is False:
        return None
    if _splash_mod is not None:
        return _splash_mod
    if "_PYI_SPLASH_IPC" not in os.environ:
        _splash_mod = False
        return None
    try:
        import pyi_splash  # type: ignore

        _splash_mod = pyi_splash
        return pyi_splash
    except Exception:
        _splash_mod = False
        return None


def _splash_start() -> None:
    """Früh: PyInstaller-Splash nutzen oder Tk-Kind starten (macOS/Fallback)."""
    global _splash_tk
    if _splash_laden() is not None:
        return
    # Windows-CLI: kein Tk-Kindprozess — der Prozessbaum wird sonst leicht
    # mit taskkill /T mitgerissen, und die Konsole gerät durcheinander.
    if sys.platform == "win32" and os.environ.get("SATSAGE_SPLASH", "").strip().lower() not in (
        "1", "true", "yes", "ja",
    ):
        return
    if splash_ui_mod.start_tk_splash():
        _splash_tk = True


def _splash_text(meldung: str) -> None:
    """Statuszeile am Splash (pyi oder Tk)."""
    try:
        splash = _splash_laden()
        if splash is not None and splash.is_alive():
            splash.update_text(meldung)
            return
    except Exception:
        pass
    if _splash_tk:
        splash_ui_mod.update_tk_splash(meldung)


def _splash_schliessen() -> None:
    """Splash ausblenden (idempotent)."""
    if _splash_zu.is_set():
        return
    _splash_zu.set()
    try:
        splash = _splash_laden()
        if splash is not None and splash.is_alive():
            splash.close()
    except Exception:
        pass
    if _splash_tk:
        splash_ui_mod.close_tk_splash()


def _splash_bei_browser() -> None:
    """Erster authentifizierter GUI-Request → Oberfläche steht, Splash weg."""
    if _splash_browser_gesehen.is_set():
        return
    _splash_browser_gesehen.set()
    _splash_schliessen()


def _splash_timeout_wache(sekunden: float = 25.0) -> None:
    """Fallback: Splash spätestens nach sekunden schließen (Browser ohne Request)."""

    def _lauf() -> None:
        ende = time.time() + sekunden
        while time.time() < ende:
            if _splash_zu.is_set() or _splash_browser_gesehen.is_set():
                return
            time.sleep(0.4)
        _splash_schliessen()

    threading.Thread(target=_lauf, name="satsage-splash-timeout", daemon=True).start()

