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

from core.paths import app_dir, resource_dir

PROJEKT_ROOT = Path(__file__).resolve().parent.parent

_FEHLT = object()


class PathsTest(unittest.TestCase):
    def setUp(self):
        self._original = {
            name: getattr(sys, name, _FEHLT)
            for name in ("frozen", "_MEIPASS", "executable")
        }
        self.addCleanup(self._restore)

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


if __name__ == "__main__":
    unittest.main()
