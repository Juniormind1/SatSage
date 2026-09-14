"""Sprachauflösung im Browser-Client (``web/i18n.js``).

Die Reihenfolge ist: ausdrückliche Wahl des Nutzers (localStorage) →
Antwort des Servers (``config.ui_lang``) → Browsersprache. Der mittlere
Schritt war lange wirkungslos, weil ``storedLang()`` auch ohne
gespeicherten Wert ``"de"`` lieferte — die serverseitige Sprachwahl kam
damit nie in der Oberfläche an.
"""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
HARNESS = WURZEL / "tests" / "i18n_harness.mjs"
I18N = WURZEL / "web" / "i18n.js"


def _node() -> str | None:
    return shutil.which("node")


@unittest.skipIf(_node() is None, "node nicht verfügbar")
class TestClientSprachwahl(unittest.TestCase):
    def _lang(self, gespeichert: str, config: str, browser: str) -> str:
        ergebnis = subprocess.run(
            [_node(), str(HARNESS), str(I18N), gespeichert, config, browser],
            capture_output=True, text=True, timeout=60, cwd=WURZEL,
        )
        self.assertEqual(ergebnis.returncode, 0, ergebnis.stderr)
        return ergebnis.stdout.strip().splitlines()[-1]

    def test_server_schlaegt_browser(self):
        """Der Server hat Accept-Language schon ausgewertet — seine Antwort gilt."""
        self.assertEqual(self._lang("-", "en", "de"), "en")
        self.assertEqual(self._lang("-", "de", "en"), "de")

    def test_eigene_wahl_schlaegt_server(self):
        self.assertEqual(self._lang("de", "en", "en"), "de")
        self.assertEqual(self._lang("en", "de", "de"), "en")

    def test_ohne_config_entscheidet_der_browser(self):
        """Nur wenn /api/config nicht erreichbar war."""
        self.assertEqual(self._lang("-", "-", "en"), "en")
        self.assertEqual(self._lang("-", "-", "de"), "de")

    def test_ohne_alles_nicht_stillschweigend_deutsch(self):
        """Ein englischer Browser darf keine deutsche Oberfläche bekommen."""
        self.assertEqual(self._lang("-", "-", "en-US"), "en")


class TestStoredLangQuelle(unittest.TestCase):
    """Statische Absicherung gegen den Rückfall, der den Fehler verursacht hat."""

    def test_stored_lang_gibt_null_ohne_wert(self):
        quelle = I18N.read_text(encoding="utf-8")
        anfang = quelle.index("function storedLang()")
        block = quelle[anfang:anfang + 500]
        self.assertIn("return null", block)
        self.assertNotIn(
            "return normalizeLang(localStorage.getItem(STORAGE_KEY))", block,
            "storedLang() darf normalizeLang() nicht direkt zurückgeben — das "
            "macht jeden fehlenden Wert zu 'de' und entwertet config.ui_lang",
        )


if __name__ == "__main__":
    unittest.main()
