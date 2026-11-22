"""
Pfadauflösung für PyInstaller-Frozen-Modus vs. normalen Skriptlauf.

sys.frozen/sys._MEIPASS/sys.executable werden pro Test gezielt gesetzt und
danach wieder in den Ursprungszustand versetzt — auch für den Fall, dass
sys._MEIPASS im Testlauf selbst gar nicht existiert (Normalfall außerhalb
einer gebauten Executable).
"""
import sys
import unittest
from pathlib import Path

import os
import tempfile

from core.paths import (
    ENV_DATA_DIR,
    app_dir,
    data_dir_override,
    exchange_dir,
    log_dir,
    resource_dir,
    setze_data_dir,
    setze_exchange_dir,
    setze_log_dir,
    warnhinweis_daten_im_arbeitsbaum,
)

PROJEKT_ROOT = Path(__file__).resolve().parent.parent

_FEHLT = object()


class PathsTest(unittest.TestCase):
    def setUp(self):
        self._original = {
            name: getattr(sys, name, _FEHLT)
            for name in ("frozen", "_MEIPASS", "executable")
        }
        self._data_dir_vorher = os.environ.get(ENV_DATA_DIR)
        self.addCleanup(self._restore)
        self.addCleanup(lambda: _restore_env(self._data_dir_vorher))

    def _restore(self):
        for name, wert in self._original.items():
            if wert is _FEHLT:
                if hasattr(sys, name):
                    delattr(sys, name)
            else:
                setattr(sys, name, wert)

    def _als_frozen(self, meipass=_FEHLT, executable=_FEHLT):
        sys.frozen = True
        if meipass is _FEHLT:
            if hasattr(sys, "_MEIPASS"):
                delattr(sys, "_MEIPASS")
        else:
            sys._MEIPASS = meipass
        if executable is not _FEHLT:
            sys.executable = executable

    def test_resource_dir_ohne_frozen_ist_projekt_wurzel(self):
        if hasattr(sys, "frozen"):
            delattr(sys, "frozen")
        self.assertEqual(resource_dir(), PROJEKT_ROOT)

    def test_app_dir_ohne_frozen_ist_projekt_wurzel(self):
        if hasattr(sys, "frozen"):
            delattr(sys, "frozen")
        self.assertEqual(app_dir(), PROJEKT_ROOT)

    def test_resource_dir_frozen_nutzt_meipass(self):
        self._als_frozen(meipass="/tmp/xpq-bundle")
        self.assertEqual(resource_dir(), Path("/tmp/xpq-bundle"))

    def test_resource_dir_frozen_ohne_meipass_faellt_auf_exe_verzeichnis_zurueck(self):
        self._als_frozen(executable="/opt/xpq/satsage-webgui")
        self.assertEqual(resource_dir(), Path("/opt/xpq").resolve())

    def test_app_dir_frozen_nutzt_exe_verzeichnis(self):
        self._als_frozen(executable="/opt/xpq/satsage-webgui")
        self.assertEqual(app_dir(), Path("/opt/xpq").resolve())

    def test_app_dir_achtet_auf_satsage_data_dir(self):
        vorher = os.environ.get(ENV_DATA_DIR)
        self.addCleanup(lambda: _restore_env(vorher))
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp).resolve()
            setze_data_dir(ziel)
            self.assertEqual(app_dir(), ziel)
            self.assertEqual(data_dir_override(), ziel)
            self.assertEqual(log_dir(), ziel / "logs")
            self.assertEqual(exchange_dir(), ziel / "exchange_reports")
            self.assertIsNone(warnhinweis_daten_im_arbeitsbaum())

    def test_ohne_data_dir_warnt_im_repo(self):
        vorher = os.environ.get(ENV_DATA_DIR)
        self.addCleanup(lambda: _restore_env(vorher))
        setze_data_dir(None)
        self.assertEqual(app_dir(), PROJEKT_ROOT)
        hinweis = warnhinweis_daten_im_arbeitsbaum()
        self.assertIsNotNone(hinweis)
        self.assertIn("Git-Arbeitsbaum", hinweis)

    def test_log_und_exchange_dir_override(self):
        self.addCleanup(lambda: setze_log_dir(None))
        self.addCleanup(lambda: setze_exchange_dir(None))
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "meine-logs"
            boerse = Path(tmp) / "meine-boerse"
            setze_log_dir(logs)
            setze_exchange_dir(boerse)
            self.assertEqual(log_dir(), logs.resolve())
            self.assertEqual(exchange_dir(), boerse.resolve())


def _restore_env(vorher: str | None) -> None:
    setze_log_dir(None)
    setze_exchange_dir(None)
    if vorher is None:
        setze_data_dir(None)
    else:
        os.environ[ENV_DATA_DIR] = vorher




if __name__ == "__main__":
    unittest.main()


class DataDirCliTest(unittest.TestCase):
    def setUp(self):
        self._vorher = os.environ.get(ENV_DATA_DIR)
        self.addCleanup(lambda: _restore_env(self._vorher))

    def test_cli_flags_und_wende_datenpfade(self):
        import server

        p = server.build_argumente()
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp).resolve()
            args = p.parse_args([
                "--data-dir", str(ziel),
                "--log-dir", str(ziel / "logs2"),
                "--exchange-dir", str(ziel / "ex2"),
            ])
            server.wende_datenpfade_an(args)
            self.assertEqual(app_dir(), ziel)
            self.assertEqual(log_dir(), (ziel / "logs2").resolve())
            self.assertEqual(exchange_dir(), (ziel / "ex2").resolve())
            self.assertIsNone(warnhinweis_daten_im_arbeitsbaum())
