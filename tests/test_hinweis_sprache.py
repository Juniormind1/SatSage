"""Der On-Chain-Hinweis folgt der Sprache — in UI, Exporten und LLM-Kontext.

Der Text ist die kanonische Haftungsaussage. Er lag als deutsche Konstante
in ``core/tax.py`` und wurde von der Oberfläche über die bereits
übersetzte Fassung gestempelt: die API meldete ``ui_lang: en``, der Dialog
blieb deutsch. Exporte und LLM-Kontext zitieren denselben Text.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import i18n
from core import tax


class TestSprachspezifischerLookup(unittest.TestCase):
    def test_liefert_die_angeforderte_sprache(self):
        de = i18n.t_lang("de", "dialog.onchain.title")
        en = i18n.t_lang("en", "dialog.onchain.title")
        self.assertEqual(de, "Hinweis zum On-Chain-Beleg")
        self.assertEqual(en, "Note on the on-chain record")

    def test_unbekannte_sprache_faellt_auf_deutsch(self):
        self.assertEqual(
            i18n.t_lang("fr", "dialog.onchain.title"),
            i18n.t_lang("de", "dialog.onchain.title"),
        )

    def test_ruehrt_die_globale_sprache_nicht_an(self):
        i18n.set_lang("de")
        vorher = i18n.lang()
        i18n.t_lang("en", "dialog.onchain.title")
        self.assertEqual(i18n.lang(), vorher, "t_lang darf keinen globalen Zustand setzen")

    def test_platzhalter_werden_ersetzt(self):
        self.assertEqual(i18n.t_lang("en", "tax.yearsN", n=3), "3 years")


class TestHinweisOnchain(unittest.TestCase):
    def test_beide_sprachen(self):
        de = tax.hinweis_onchain("de")
        en = tax.hinweis_onchain("en")
        self.assertIn("rekonstruiert", de)
        self.assertIn("reconstructs", en)
        self.assertNotEqual(de, en)

    def test_default_bleibt_deutsch(self):
        self.assertEqual(tax.hinweis_onchain(), tax.HINWEIS_ONCHAIN)

    def test_keine_beratung_enthaelt_den_hinweis(self):
        for lang in ("de", "en"):
            with self.subTest(lang=lang):
                self.assertIn(
                    tax.hinweis_onchain(lang), tax.hinweis_keine_beratung(lang)
                )

    def test_keine_beratung_ist_uebersetzt(self):
        self.assertNotEqual(
            tax.hinweis_keine_beratung("de"), tax.hinweis_keine_beratung("en")
        )


class TestApiConfigFolgtDerSprache(unittest.TestCase):
    def _state(self, tmp):
        (Path(tmp) / ".env").write_text("", encoding="utf-8")
        return __import__("server").AppState(
            env_path=Path(tmp) / ".env",
            cache_dir=Path(tmp) / "cache",
            immutable_cache_dir=Path(tmp) / "imm",
        )

    def test_englischer_browser_bekommt_englisch(self):
        import server
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp)
            cfg = server.api_config(state, {}, "en-US,en;q=0.9")
            self.assertEqual(cfg["ui_lang"], "en")
            self.assertIn("reconstructs", cfg["hinweis_onchain"])

    def test_deutscher_browser_bekommt_deutsch(self):
        import server
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp)
            cfg = server.api_config(state, {}, "de-DE,de;q=0.9")
            self.assertEqual(cfg["ui_lang"], "de")
            self.assertIn("rekonstruiert", cfg["hinweis_onchain"])


if __name__ == "__main__":
    unittest.main()
