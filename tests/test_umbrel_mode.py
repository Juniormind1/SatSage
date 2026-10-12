"""Regressionen für den Umbrel-Modus (``SATSAGE_MANAGED_BY=umbrel``).

Umbrel reicht Electrum-, Core- und Mempool-Adressen als Compose-Env herein und
zeigt das App-Passwort (``APP_PASSWORD``) in der eigenen Oberfläche an. SatSage
übernimmt beides, sperrt die Bridge-Quellen in der Datenquellen-UI und verlangt
hinter dem ``app_proxy`` weiterhin seinen eigenen Login.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server
from tests.env_scramble_helpers import (
    clear_scramble_session,
    read_env_plaintext,
    write_env_scrambled,
)


UMBREL_ENV = {
    "SATSAGE_MANAGED_BY": "umbrel",
    "FULCRUM_HOST": "10.21.21.10",
    "FULCRUM_PORT": "50001",
    "FULCRUM_SSL": "false",
    "NODE_IP": "10.21.21.8",
    "RPCPORT": "8332",
    "RPCUSER": "umbrel",
    "RPCPASSWORD": "geheim",
    "MEMPOOL_URL": "http://10.21.21.26:3006",
}


class UmbrelModeTestCase(unittest.TestCase):
    def setUp(self):
        clear_scramble_session()
        self.addCleanup(clear_scramble_session)

    def _state(self, tmp: str, env_text: str = "", process_env: dict | None = None):
        env_path = Path(tmp) / ".env"
        write_env_scrambled(env_path, env_text or "\n")
        with mock.patch.dict(os.environ, process_env or UMBREL_ENV, clear=False):
            return server.AppState(
                env_path=env_path,
                cache_dir=Path(tmp) / "cache",
                immutable_cache_dir=Path(tmp) / "immutable",
            ), env_path


class TestUmbrelManagedMode(UmbrelModeTestCase):
    def test_modus_wird_aus_prozess_env_erkannt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp)
            self.assertEqual(state.managed_by, "umbrel")
            self.assertTrue(server._managed_mode(state))

    def test_modus_wird_aus_env_datei_erkannt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp, "SATSAGE_MANAGED_BY=umbrel\n", process_env={})
            self.assertEqual(state.managed_by, "umbrel")

    def test_bridge_adressen_kommen_aus_prozess_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp)
            with mock.patch.dict(os.environ, UMBREL_ENV, clear=False):
                werte = state.env().values()
            self.assertEqual(werte["FULCRUM_HOST"], "10.21.21.10")
            self.assertEqual(werte["FULCRUM_PORT"], "50001")
            self.assertEqual(werte["NODE_IP"], "10.21.21.8")
            self.assertEqual(werte["RPCUSER"], "umbrel")
            self.assertEqual(werte["RPCPASSWORD"], "geheim")
            self.assertEqual(werte["MEMPOOL_URL"], "http://10.21.21.26:3006")

    def test_bridge_werte_landen_nicht_in_der_env_datei(self):
        """RPC-Zugangsdaten der Plattform bleiben laufzeit-only."""
        with tempfile.TemporaryDirectory() as tmp:
            state, env_path = self._state(tmp)
            with mock.patch.dict(os.environ, UMBREL_ENV, clear=False):
                state.env().values()
            self.assertNotIn("RPCPASSWORD", read_env_plaintext(env_path))

    def test_nutzer_env_schlaegt_prozess_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp, "MEMPOOL_URL=http://eigener:3006\n")
            with mock.patch.dict(os.environ, UMBREL_ENV, clear=False):
                werte = state.env().values()
            self.assertEqual(werte["MEMPOOL_URL"], "http://eigener:3006")

    def test_ellectrs_host_fallback_ohne_fulcrum_host(self):
        prozess = {k: v for k, v in UMBREL_ENV.items() if k != "FULCRUM_HOST"}
        prozess["ELECTRS_HOST"] = "10.21.21.10"
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp, process_env=prozess)
            with mock.patch.dict(os.environ, prozess, clear=False):
                werte = state.env().values()
            self.assertEqual(werte["FULCRUM_HOST"], "10.21.21.10")


class TestUmbrelDatenquellenGesperrt(UmbrelModeTestCase):
    def test_node_mutation_wird_abgelehnt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp)
            with self.assertRaises(server.ApiError) as raised:
                server.api_save_source(
                    state, {"source": "own_core", "values": {"NODE_IP": "127.0.0.1"}}
                )
            self.assertEqual(raised.exception.status, 403)
            self.assertIn("Umbrel", str(raised.exception))

    def test_fulcrum_mutation_wird_abgelehnt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp)
            with self.assertRaises(server.ApiError) as raised:
                server.api_save_source(
                    state,
                    {"source": "own_fulcrum", "values": {"FULCRUM_HOST": "boeser.host"}},
                )
            self.assertEqual(raised.exception.status, 403)

    def test_managed_hint_nennt_umbrel_und_indexer(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp)
            with mock.patch.dict(os.environ, UMBREL_ENV, clear=False):
                hint = server._managed_hint(state, state.env().values())
            self.assertIn("Umbrel", hint)
            self.assertIn("Electrs", hint)

    def test_lokale_core_erkennung_bleibt_aus(self):
        """Im Managed-Modus wird kein Loopback-bitcoind angeboten."""
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp)
            self.assertIsNone(server._local_core_status_for_api(state))


class TestUmbrelBootstrapPasswort(UmbrelModeTestCase):
    def test_app_password_wird_als_hash_hinterlegt(self):
        prozess = dict(UMBREL_ENV, SATSAGE_BOOTSTRAP_PASSWORD="umbrel-app-passwort")
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp, process_env=prozess)
            with mock.patch.dict(os.environ, prozess, clear=False):
                server._seed_managed_password(state)
                self.assertTrue(server._password_is_set(state))
                self.assertTrue(
                    server._verify_password(
                        "umbrel-app-passwort", server._password_hash(state)
                    )
                )
                # Der Klartext bleibt nicht in der Prozess-Umgebung stehen.
                self.assertNotIn("SATSAGE_BOOTSTRAP_PASSWORD", os.environ)

    def test_rotiertes_passwort_wird_neu_gehasht(self):
        with tempfile.TemporaryDirectory() as tmp:
            erst = dict(UMBREL_ENV, SATSAGE_BOOTSTRAP_PASSWORD="altes-passwort")
            state, _ = self._state(tmp, process_env=erst)
            with mock.patch.dict(os.environ, erst, clear=False):
                server._seed_managed_password(state)
            zweit = dict(UMBREL_ENV, SATSAGE_BOOTSTRAP_PASSWORD="neues-passwort")
            with mock.patch.dict(os.environ, zweit, clear=False):
                server._seed_managed_password(state)
                hash_ = server._password_hash(state)
            self.assertTrue(server._verify_password("neues-passwort", hash_))
            self.assertFalse(server._verify_password("altes-passwort", hash_))

    def test_fehlendes_bootstrap_passwort_meldet_umbrel(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, _ = self._state(tmp)
            with mock.patch.dict(os.environ, UMBREL_ENV, clear=False):
                os.environ.pop("SATSAGE_BOOTSTRAP_PASSWORD", None)
                with self.assertRaises(RuntimeError) as raised:
                    server._seed_managed_password(state)
            self.assertIn("Umbrel", str(raised.exception))

    def _klartext_state(self, tmp: str, process_env: dict):
        """Klartext-.env. Eine vorher scrambled Datei würde den Hash als
        Passwort zählen, auch wenn Umbrel im Betrieb nicht scramblt.
        """
        env_path = Path(tmp) / ".env"
        env_path.write_text(
            "SATSAGE_MANAGED_BY=umbrel\nUI_LANG=de\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, process_env, clear=False):
            state = server.AppState(
                env_path=env_path,
                cache_dir=Path(tmp) / "cache",
                immutable_cache_dir=Path(tmp) / "immutable",
                managed_by="umbrel",
            )
        return state, env_path

    def test_klartext_hash_gilt_als_gesetzt(self):
        """Der Bootstrap-Hash sperrt die Oberfläche, ohne die .env zu scramblen."""
        prozess = dict(UMBREL_ENV, SATSAGE_BOOTSTRAP_PASSWORD="umbrel-app-passwort")
        with tempfile.TemporaryDirectory() as tmp:
            state, env_path = self._klartext_state(tmp, prozess)
            with mock.patch.dict(os.environ, prozess, clear=False):
                server._seed_managed_password(state)
            self.assertTrue(server._password_is_set(state))
            self.assertFalse(env_path.read_bytes().startswith(b"SSGB1\n"))
            self.assertIn("UI_LANG=de", env_path.read_text(encoding="utf-8"))
            self.assertNotIn("SATSAGE_BOOTSTRAP_PASSWORD", os.environ)

    def test_aendern_und_loeschen_verlangt_das_bootstrap_passwort(self):
        """Wie die Einstellungen: leeres „Aktuelles Passwort“ ist kein Setzen."""
        prozess = dict(UMBREL_ENV, SATSAGE_BOOTSTRAP_PASSWORD="umbrel-app-passwort")
        with tempfile.TemporaryDirectory() as tmp:
            state, env_path = self._klartext_state(tmp, prozess)
            with mock.patch.dict(os.environ, prozess, clear=False):
                server._seed_managed_password(state)
            with self.assertRaises(server.ApiError) as gefangen:
                server.api_save_app_password(
                    state,
                    {"new_password": "anderes", "confirm": "anderes"},
                )
            self.assertEqual(gefangen.exception.status, 403)
            self.assertIn("Aktuelles Passwort ist falsch", str(gefangen.exception))
            self.assertTrue(
                server._verify_password(
                    "umbrel-app-passwort", server._password_hash(state),
                )
            )
            geaendert = server.api_save_app_password(
                state,
                {
                    "current_password": "umbrel-app-passwort",
                    "new_password": "anderes",
                    "confirm": "anderes",
                },
            )
            self.assertTrue(geaendert["password_set"])
            self.assertFalse(geaendert["env_scramble"]["allowed"])
            self.assertFalse(geaendert["env_scramble"]["active"])
            self.assertFalse(env_path.read_bytes().startswith(b"SSGB1\n"))
            self.assertIn("UI_LANG=de", env_path.read_text(encoding="utf-8"))
            self.assertTrue(
                server._verify_password("anderes", server._password_hash(state))
            )
            with self.assertRaises(server.ApiError) as gefangen:
                server.api_delete_app_password(state, {})
            self.assertEqual(gefangen.exception.status, 403)
            self.assertTrue(server._password_is_set(state))
            geloescht = server.api_delete_app_password(
                state, {"current_password": "anderes"},
            )
            self.assertFalse(geloescht["password_set"])
            self.assertFalse(server._password_is_set(state))
            self.assertIn("UI_LANG=de", env_path.read_text(encoding="utf-8"))
            self.assertFalse((env_path.parent / ".satsage-password").is_file())


class TestUmbrelProxyVertrauen(UmbrelModeTestCase):
    def test_umbrel_vertraut_keinen_proxy_headern(self):
        """Der app_proxy ersetzt den SatSage-Login nicht — Header sind wertlos."""
        with tempfile.TemporaryDirectory() as tmp:
            prozess = dict(
                UMBREL_ENV,
                SATSAGE_BOOTSTRAP_PASSWORD="geheim",
                SATSAGE_TRUST_PROXY="1",
            )
            state, _ = self._state(tmp, process_env=prozess)
            with mock.patch.dict(os.environ, prozess, clear=False):
                server._seed_managed_password(state)
                headers = {"X-Forwarded-Proto": "https", "X-Forwarded-User": "admin"}
                self.assertFalse(server._start9_proxy_authenticated(state, headers))


if __name__ == "__main__":
    unittest.main()
