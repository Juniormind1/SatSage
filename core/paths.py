"""
Pfadauflösung, die zwischen normalem Skriptlauf und einer eingefrorenen
PyInstaller-Executable unterscheidet.

Im Onefile-Modus zeigt ``__file__`` auf einen Wegwerf-Temp-Ordner
(``sys._MEIPASS``), der nach Programmende verschwindet. Gebündelte,
schreibgeschützte Assets (z. B. ``web/``) liegen dort und müssen über
``resource_dir()`` aufgelöst werden. Persistente Nutzerdaten (``.env``,
Caches) müssen dagegen neben der Executable selbst liegen, damit sie
Neustarts überleben — dafür ist ``app_dir()`` da.
"""
from __future__ import annotations

import sys
from pathlib import Path


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
