"""Testsuite für SatSage — läuft offline, ohne Node und ohne echte .env.

``_load_dotenv()`` ohne Pfad liest ``ENV_FILE`` und setzt daraus das Netz.
Eine offene oder entschlüsselte persönliche ``.env`` macht daraus Mainnet
und einen erreichbaren Explorer. Die Suite zeigt auf eine leere Datei
im Worktree und wirft den Scramble-Session-Key weg. Tests mit eigener
Datei übergeben den Pfad oder setzen ``ENV_FILE`` selbst.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_LEER = Path(__file__).resolve().parent.parent / "tmp" / "unittest-leer.env"
_LEER.parent.mkdir(parents=True, exist_ok=True)
_LEER.write_text("", encoding="utf-8")
os.environ["ENV_FILE"] = str(_LEER)

from core import env_bootstrap  # noqa: E402
from core.env_scramble import clear_session_key  # noqa: E402

env_bootstrap.ENV_FILE = _LEER
clear_session_key()
_main = sys.modules.get("main")
if _main is not None:
    _main.ENV_FILE = _LEER
