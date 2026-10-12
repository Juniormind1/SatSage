"""Specter setzt ein App-Passwort ohne .env-Scramble.

Ein Hash neben der Klartext-``satsage.env`` ist dort das Passwort. Die
Oberfläche darf das Setzen nicht mit „Aktuelles Passwort ist falsch“
ablehnen, solange noch keins gilt — und muss es danach als gesetzt führen.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import server
from tests.env_scramble_helpers import clear_scramble_session


class TestSpecterAppPasswort(unittest.TestCase):
    def setUp(self):
        clear_scramble_session()
        self.addCleanup(clear_scramble_session)

    def _state(self, tmp: str):
        env_path = Path(tmp) / "satsage.env"
        env_path.write_text(
            "SATSAGE_MANAGED_BY=specter\nUI_LANG=de\n",
            encoding="utf-8",
        )
        state = server.AppState(
            env_path=env_path,
            cache_dir=Path(tmp) / "cache",
            immutable_cache_dir=Path(tmp) / "immutable",
            managed_by="specter",
        )
        return state, env_path

    def test_hash_ohne_scramble_gilt_als_gesetzt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, env_path = self._state(tmp)
            self.assertFalse(server._password_is_set(state))
            server._write_password_hash(state, "erstes-mal")
            self.assertTrue(server._password_is_set(state))
            self.assertFalse(env_path.read_bytes().startswith(b"SSGB1\n"))

    def test_erstes_setzen_ohne_aktuelles_passwort(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, env_path = self._state(tmp)
            vorher = env_path.read_text(encoding="utf-8")
            ergebnis = server.api_save_app_password(
                state,
                {"new_password": "specter-pass", "confirm": "specter-pass"},
            )
            self.assertTrue(ergebnis["password_set"])
            self.assertTrue(server._password_is_set(state))
            self.assertTrue(
                server._verify_password("specter-pass", server._password_hash(state))
            )
            self.assertEqual(env_path.read_text(encoding="utf-8"), vorher)
            self.assertFalse(ergebnis["env_scramble"]["active"])

    def test_erneutes_setzen_verlangt_das_aktuelle(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp)
            server.api_save_app_password(
                state,
                {"new_password": "specter-pass", "confirm": "specter-pass"},
            )
            with self.assertRaises(server.ApiError) as gefangen:
                server.api_save_app_password(
                    state,
                    {"new_password": "anderes", "confirm": "anderes"},
                )
            self.assertEqual(gefangen.exception.status, 403)
            self.assertIn("Aktuelles Passwort ist falsch", str(gefangen.exception))
            self.assertTrue(
                server._verify_password("specter-pass", server._password_hash(state))
            )
            ergebnis = server.api_save_app_password(
                state,
                {
                    "current_password": "specter-pass",
                    "new_password": "anderes",
                    "confirm": "anderes",
                },
            )
            self.assertTrue(ergebnis["password_set"])
            self.assertTrue(
                server._verify_password("anderes", server._password_hash(state))
            )

    def test_loeschen_verlangt_das_aktuelle_und_laesst_die_env(self):
        """Einstellungen · Entfernen, nicht der Login-„Vergessen“-Pfad."""
        with tempfile.TemporaryDirectory() as tmp:
            state, env_path = self._state(tmp)
            server.api_save_app_password(
                state,
                {"new_password": "specter-pass", "confirm": "specter-pass"},
            )
            with self.assertRaises(server.ApiError) as gefangen:
                server.api_delete_app_password(state, {})
            self.assertEqual(gefangen.exception.status, 403)
            self.assertIn("Aktuelles Passwort ist falsch", str(gefangen.exception))
            self.assertTrue(server._password_is_set(state))
            ergebnis = server.api_delete_app_password(
                state, {"current_password": "specter-pass"},
            )
            self.assertFalse(ergebnis["password_set"])
            self.assertFalse(ergebnis["env_scramble"]["active"])
            self.assertFalse(server._password_is_set(state))
            self.assertIn("UI_LANG=de", env_path.read_text(encoding="utf-8"))
            self.assertFalse((env_path.parent / ".satsage-password").is_file())

    def test_vergessen_loescht_nur_den_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, env_path = self._state(tmp)
            server.api_save_app_password(
                state,
                {"new_password": "specter-pass", "confirm": "specter-pass"},
            )
            server._scramble_discard_locked(state)
            self.assertIn("UI_LANG=de", env_path.read_text(encoding="utf-8"))
            self.assertFalse(server._password_is_set(state))
            self.assertFalse((env_path.parent / ".satsage-password").is_file())


if __name__ == "__main__":
    unittest.main()
