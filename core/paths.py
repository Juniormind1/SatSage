"""
Pfadauflösung, die zwischen normalem Skriptlauf und einer eingefrorenen
PyInstaller-Executable unterscheidet.

Im Onefile-Modus zeigt ``__file__`` auf einen Wegwerf-Temp-Ordner
(``sys._MEIPASS``), der nach Programmende verschwindet. Gebündelte,
schreibgeschützte Assets (z. B. ``web/``) liegen dort und müssen über
``resource_dir()`` aufgelöst werden. Persistente Nutzerdaten (``.env``,
Caches, Börsenimporte, Logs) müssen dagegen überleben — dafür ist
``app_dir()`` da.

Entscheidung E13 (änderbar): Ist ``SATSAGE_DATA_DIR`` oder ``--data-dir``
gesetzt, ist das die Datenwurzel. Ohne Angabe bleibt das bisherige
Verhalten (Repo-Wurzel bzw. Verzeichnis der Executable). Liegen die Daten
im Git-Arbeitsbaum, warnt der Start, blockiert aber nicht.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_DATA_DIR = "SATSAGE_DATA_DIR"

_log_dir: Path | None = None
_exchange_dir: Path | None = None


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _eingebautes_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir_override() -> Path | None:
    """Gesetzte Datenwurzel oder ``None``, wenn das bisherige Verhalten gilt."""
    roh = (os.environ.get(ENV_DATA_DIR) or "").strip()
    if not roh:
        return None
    return Path(roh).expanduser().resolve()


def setze_data_dir(pfad: str | Path | None) -> Path | None:
    """Setzt ``SATSAGE_DATA_DIR``. ``None`` oder leer nimmt die Variable zurück."""
    if pfad is None or str(pfad).strip() == "":
        os.environ.pop(ENV_DATA_DIR, None)
        return None
    ziel = Path(str(pfad)).expanduser().resolve()
    os.environ[ENV_DATA_DIR] = str(ziel)
    return ziel


def app_dir() -> Path:
    override = data_dir_override()
    if override is not None:
        return override
    return _eingebautes_app_dir()


def setze_log_dir(pfad: str | Path | None) -> None:
    global _log_dir
    _log_dir = Path(str(pfad)).expanduser().resolve() if pfad else None


def log_dir() -> Path:
    if _log_dir is not None:
        return _log_dir
    return app_dir() / "logs"


def setze_exchange_dir(pfad: str | Path | None) -> None:
    global _exchange_dir
    _exchange_dir = Path(str(pfad)).expanduser().resolve() if pfad else None


def exchange_dir() -> Path:
    if _exchange_dir is not None:
        return _exchange_dir
    return app_dir() / "exchange_reports"


def daten_liegen_im_git_arbeitsbaum(pfad: Path | None = None) -> bool:
    """True, wenn *pfad* (Standard: ``app_dir()``) in einem Git-Arbeitsbaum liegt."""
    start = (pfad or app_dir()).resolve()
    for cand in (start, *start.parents):
        if (cand / ".git").exists():
            return True
    return False


def warnhinweis_daten_im_arbeitsbaum() -> str | None:
    """Kurzer Warntext oder ``None``, wenn die Daten außerhalb von Git liegen."""
    ziel = app_dir()
    if daten_liegen_im_git_arbeitsbaum(ziel):
        return f"Daten liegen im Git-Arbeitsbaum ({ziel})"
    return None


def aktualisiere_modulkonstanten() -> None:
    """Nachträglich gesetztes ``SATSAGE_DATA_DIR`` in Import-Konstanten nachziehen."""
    wurzel = app_dir()
    zuordnungen = (
        ("core.env_bootstrap", (("ENV_FILE", wurzel / ".env"),)),
        (
            "core.xpub_cache",
            (
                ("UTXO_CACHE_DIR", wurzel / "utxo_cache"),
                ("IMMUTABLE_CACHE_DIR", wurzel / "immutable_cache"),
            ),
        ),
        ("labels", (("LABEL_CACHE_DIR", wurzel / "label_cache"),)),
        ("sanctioned", (("SANCTIONED_CACHE_DIR", wurzel / "sanctioned_cache"),)),
        (
            "core.electrum_servers",
            (("ELECTRUM_SERVERS_FILE", wurzel / "electrum_servers.json"),),
        ),
        (
            "core.chain_sources",
            (("ELECTRUM_SERVERS_FILE", wurzel / "electrum_servers.json"),),
        ),
        (
            "main",
            (
                ("ENV_FILE", wurzel / ".env"),
                ("UTXO_CACHE_DIR", wurzel / "utxo_cache"),
                ("IMMUTABLE_CACHE_DIR", wurzel / "immutable_cache"),
            ),
        ),
    )
    for modulname, paare in zuordnungen:
        modul = sys.modules.get(modulname)
        if modul is None:
            continue
        for name, wert in paare:
            if hasattr(modul, name):
                setattr(modul, name, wert)
