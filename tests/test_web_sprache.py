"""Sprachwahl der Web-GUI und Wahrheitsgehalt der Fußzeile.

Die Weboberfläche wird auch von Leuten geöffnet, die kein Deutsch lesen —
im Umbrel App Store ist das der Normalfall. umbrelOS reicht seine eigene
Spracheinstellung nicht an Apps durch, also bleibt als Signal nur der
``Accept-Language``-Header des Browsers.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import server


class TestAcceptLanguage(unittest.TestCase):
    def test_englischer_browser(self):
        self.assertEqual(server._sprache_aus_accept_language("en-US,en;q=0.9"), "en")

    def test_deutscher_browser(self):
        self.assertEqual(
            server._sprache_aus_accept_language("de-DE,de;q=0.9,en;q=0.8"), "de"
        )

    def test_qualitaet_entscheidet_nicht_die_reihenfolge(self):
        """``en`` steht vorn, ``de`` hat aber das höhere q."""
        self.assertEqual(
            server._sprache_aus_accept_language("en;q=0.5,de;q=0.9"), "de"
        )

    def test_nicht_unterstuetzte_sprache(self):
        self.assertIsNone(server._sprache_aus_accept_language("fr-FR,fr;q=0.9"))

    def test_leer_und_unsinn(self):
        for roh in ("", None, "   ", "*", "q=;;;"):
            self.assertIsNone(server._sprache_aus_accept_language(roh))

    def test_wildcard_zaehlt_nicht_als_treffer(self):
        self.assertIsNone(server._sprache_aus_accept_language("*"))


class TestUiLangFuerWeb(unittest.TestCase):
    def test_ui_lang_schlaegt_browser(self):
        self.assertEqual(
            server._ui_lang_fuer_web({"UI_LANG": "de"}, "en-US,en;q=0.9"), "de"
        )
        self.assertEqual(
            server._ui_lang_fuer_web({"UI_LANG": "en"}, "de-DE,de;q=0.9"), "en"
        )

    def test_ohne_ui_lang_entscheidet_der_browser(self):
        self.assertEqual(server._ui_lang_fuer_web({}, "en-US,en;q=0.9"), "en")
        self.assertEqual(server._ui_lang_fuer_web({}, "de-DE,de;q=0.9"), "de")

    def test_ohne_alles_englisch(self):
        """Default Englisch — die Web-GUI hat internationales Publikum."""
        self.assertEqual(server._ui_lang_fuer_web({}, None), "en")
        self.assertEqual(server._ui_lang_fuer_web({}, "fr-FR"), "en")


class TestLoginTexte(unittest.TestCase):
    def test_beide_sprachen_decken_dieselben_schluessel(self):
        de = set(server._LOGIN_TEXTE["de"])
        en = set(server._LOGIN_TEXTE["en"])
        self.assertEqual(de, en, "Login-Katalog ist zwischen de und en ungleich")

    def test_kein_eintrag_ist_leer(self):
        for lang, texte in server._LOGIN_TEXTE.items():
            for schluessel, wert in texte.items():
                with self.subTest(lang=lang, schluessel=schluessel):
                    self.assertTrue(str(wert).strip(), "leerer Text")

    def test_englisch_ist_nicht_nur_kopiertes_deutsch(self):
        de = server._LOGIN_TEXTE["de"]
        en = server._LOGIN_TEXTE["en"]
        gleich = [k for k in de if de[k] == en[k]]
        self.assertFalse(gleich, f"unübersetzt geblieben: {gleich}")

    def test_umbrel_hinweis_vorhanden(self):
        for lang in ("de", "en"):
            self.assertIn("hinweis_umbrel", server._LOGIN_TEXTE[lang])


class TestFussLocalOnly(unittest.TestCase):
    def _state(self, tmp):
        return server.AppState(
            env_path=Path(tmp) / ".env",
            cache_dir=Path(tmp) / "cache",
            immutable_cache_dir=Path(tmp) / "immutable",
        )

    def test_loopback_ist_local_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text("SATSAGE_BIND=127.0.0.1\n", encoding="utf-8")
            self.assertTrue(server._ist_local_only(self._state(tmp)))

    def test_offener_bind_ist_nicht_local_only(self):
        """Hinter Umbrels app_proxy bindet SatSage an 0.0.0.0."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text("SATSAGE_BIND=0.0.0.0\n", encoding="utf-8")
            self.assertFalse(server._ist_local_only(self._state(tmp)))

    def test_default_ohne_angabe_ist_loopback(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text("", encoding="utf-8")
            self.assertTrue(server._ist_local_only(self._state(tmp)))


if __name__ == "__main__":
    unittest.main()


class TestLoginSeiteGerendert(unittest.TestCase):
    """Die gerenderte Seite selbst — nicht nur der Katalog."""

    def _seite(self, accept_language, *, managed_by=None):
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("", encoding="utf-8")
            prozess = {"SATSAGE_BOOTSTRAP_PASSWORD": "geheim"}
            if managed_by:
                prozess["SATSAGE_MANAGED_BY"] = managed_by
            with mock.patch.dict("os.environ", prozess, clear=False):
                state = server.AppState(
                    env_path=env_path,
                    cache_dir=Path(tmp) / "cache",
                    immutable_cache_dir=Path(tmp) / "immutable",
                )
                server._seed_managed_password(state)

                handler = server.Handler.__new__(server.Handler)
                handler.state = state
                handler.headers = {"Accept-Language": accept_language or ""}
                gesendet = {}
                handler._auth_ok = lambda query: False
                handler._send = lambda status, body, typ: gesendet.update(
                    status=status, body=body.decode("utf-8")
                )
                handler._login_page()
                return gesendet["body"]

    def test_englischer_browser_sieht_englisch(self):
        seite = self._seite("en-US,en;q=0.9")
        self.assertIn("<h1>Sign in</h1>", seite)
        self.assertIn('<html lang="en">', seite)
        self.assertNotIn("Bitte Passwort eingeben", seite)

    def test_deutscher_browser_sieht_deutsch(self):
        seite = self._seite("de-DE,de;q=0.9")
        self.assertIn("<h1>Anmelden</h1>", seite)
        self.assertIn('<html lang="de">', seite)

    def test_ohne_header_englisch(self):
        self.assertIn("<h1>Sign in</h1>", self._seite(None))

    def test_umbrel_hinweis_folgt_der_sprache(self):
        self.assertIn(
            "Umbrel shows this password", self._seite("en", managed_by="umbrel")
        )
        self.assertIn(
            "Umbrel zeigt dieses Passwort", self._seite("de", managed_by="umbrel")
        )
