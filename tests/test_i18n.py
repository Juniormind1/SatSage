"""
UI-i18n: Gerüst in web/.

Key-Parität und genutzte Schlüssel prüft ``test_web_locales.py``.
Hier bleibt nur: Dateien ladbar, ``i18n.js`` verdrahtet, Sprache-Karte in index.html.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DE = WEB / "locales" / "de.json"
EN = WEB / "locales" / "en.json"
INDEX = WEB / "index.html"
I18N_JS = WEB / "i18n.js"


class TestI18nLocales(unittest.TestCase):

    def test_locale_dateien_existieren(self):
        self.assertTrue(DE.is_file(), "web/locales/de.json fehlt")
        self.assertTrue(EN.is_file(), "web/locales/en.json fehlt")

    def test_locale_json_ladbar(self):
        de = json.loads(DE.read_text(encoding="utf-8"))
        en = json.loads(EN.read_text(encoding="utf-8"))
        self.assertIsInstance(de, dict)
        self.assertIsInstance(en, dict)
        self.assertGreater(len(de), 50)


class TestI18nGeruest(unittest.TestCase):

    def test_i18n_js_vorhanden(self):
        self.assertTrue(I18N_JS.is_file())
        quelle = I18N_JS.read_text(encoding="utf-8")
        for name in ("function t(", "applyDom", "setLang", "initI18n", "formatLocale"):
            self.assertIn(name, quelle, f"{name} fehlt in i18n.js")

    def test_index_laedt_i18n_und_hat_sprache_karte(self):
        html = INDEX.read_text(encoding="utf-8")
        self.assertIn('src="/i18n.js', html)
        self.assertIn('data-i18n="settings.language.title"', html)
        self.assertIn('id="ui-lang"', html)
        self.assertIn("Sprache", html)


if __name__ == "__main__":
    unittest.main()
