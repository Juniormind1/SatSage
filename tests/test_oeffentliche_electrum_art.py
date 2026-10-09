"""Öffentliche Electrum: GUI-Wahl Clearnet XOR Onion."""
from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock, patch

import main
import core.chain_sources as chain_sources
from core.outbound_policy import (
    _reset_oeffentliche_electrum_suche_fuer_tests,
    oeffentliche_electrum_art,
    oeffentliche_familie_aktiv,
    setze_oeffentliche_electrum_art,
    setze_oeffentliche_electrum_session,
)
from core.source import SourceInfo, PRIVACY_MEDIUM
from core import source as source_mod


class TestOeffentlicheElectrumArt(unittest.TestCase):

    def setUp(self):
        _reset_oeffentliche_electrum_suche_fuer_tests()
        self.addCleanup(_reset_oeffentliche_electrum_suche_fuer_tests)
        main._reset_quelle_log()
        self.args = SimpleNamespace(
            bip158_start=None, rpchost=None, fulcrum_host=None,
            oeffentliche_electrum=True,
        )

    def test_session_aus_loescht_art(self):
        setze_oeffentliche_electrum_art("onion")
        self.assertEqual(oeffentliche_electrum_art(), "onion")
        setze_oeffentliche_electrum_session(True)
        self.assertEqual(oeffentliche_electrum_art(), "onion")
        setze_oeffentliche_electrum_session(False)
        self.assertIsNone(oeffentliche_electrum_art())
        self.assertTrue(oeffentliche_familie_aktiv("clearnet"))
        self.assertTrue(oeffentliche_familie_aktiv("onion"))

    def test_familie_aktiv_nach_wahl(self):
        setze_oeffentliche_electrum_art("clearnet")
        self.assertTrue(oeffentliche_familie_aktiv("clearnet"))
        self.assertFalse(oeffentliche_familie_aktiv("onion"))
        setze_oeffentliche_electrum_art("onion")
        self.assertFalse(oeffentliche_familie_aktiv("clearnet"))
        self.assertTrue(oeffentliche_familie_aktiv("onion"))

    def test_setup_clearnet_schweigt_bei_onion_wahl(self):
        setze_oeffentliche_electrum_art("onion")
        with patch(
            "core.sanctions_pool.resolve_sanctions_clearnet_pool",
        ) as resolve:
            self.assertIsNone(
                chain_sources._setup_public_clearnet_fulcrum(self.args, {})
            )
        resolve.assert_not_called()

    def test_try_onion_schweigt_bei_clearnet_wahl(self):
        setze_oeffentliche_electrum_art("clearnet")
        with patch.object(
            chain_sources, "_setup_public_onion_rotation",
        ) as setup:
            self.assertIsNone(
                chain_sources._try_public_onion_fulcrum(
                    self.args, {"FULCRUM_TOR_0": "x.onion"},
                )
            )
        setup.assert_not_called()

    def test_pruefe_art_onion_probt_kein_clearnet(self):
        setze_oeffentliche_electrum_art("onion")
        gefunden = {
            "public_onion": SourceInfo(
                rank=5, key="public_onion", name="Onion", detail="",
                privacy=PRIVACY_MEDIUM, configured=True,
            ),
            "clearnet": SourceInfo(
                rank=6, key="clearnet", name="Clear", detail="",
                privacy=PRIVACY_MEDIUM, configured=True,
            ),
        }
        values = {"FULCRUM_TOR_0": "abc.onion", "OEFFENTLICHE_ELECTRUM": "1"}
        logs: list[str] = []

        def zaehle(endpunkte, **_kw):
            if endpunkte and not str(endpunkte[0][0]).endswith(".onion"):
                raise AssertionError("Clearnet darf nicht geprobt werden")
            return ["abc.onion:50002"]

        with mock.patch.object(
            source_mod, "_zaehle_electrum_endpunkte", side_effect=zaehle,
        ), mock.patch.object(
            source_mod, "splitte_electrum_server",
            return_value=([], [("1.2.3.4", 50002, True)] * 3),
        ), mock.patch(
            "core.electrum_servers.load_electrum_servers", return_value={},
        ), mock.patch.object(
            source_mod, "_loese_oeffentliches_onion_tor",
        ) as loese, mock.patch(
            "core.tor.stelle_tor_socks_bereit",
            return_value=("127.0.0.1", 9050),
        ):
            out = source_mod._pruefe_oeffentliche_electrum(
                gefunden, values, timeout=1, on_log=logs.append,
            )
        loese.assert_not_called()
        self.assertEqual(out["public_onion"].peer_count, 1)
        self.assertEqual(out["clearnet"].peer_count, 0)
        self.assertIsNone(out["clearnet"].reachable)
        self.assertTrue(any("Onion" in z for z in logs), logs)

    def test_pruefe_art_clearnet_ohne_treffer_probt_keine_onions(self):
        setze_oeffentliche_electrum_art("clearnet")
        gefunden = {
            "public_onion": SourceInfo(
                rank=5, key="public_onion", name="Onion", detail="",
                privacy=PRIVACY_MEDIUM, configured=True,
            ),
            "clearnet": SourceInfo(
                rank=6, key="clearnet", name="Clear", detail="",
                privacy=PRIVACY_MEDIUM, configured=True,
            ),
        }
        values = {"FULCRUM_TOR_0": "abc.onion", "OEFFENTLICHE_ELECTRUM": "1"}
        logs: list[str] = []

        def zaehle(endpunkte, **_kw):
            if endpunkte and str(endpunkte[0][0]).endswith(".onion"):
                raise AssertionError("Onion darf nicht geprobt werden")
            return []

        with mock.patch.object(
            source_mod, "_zaehle_electrum_endpunkte", side_effect=zaehle,
        ), mock.patch.object(
            source_mod, "splitte_electrum_server",
            return_value=([], [("1.2.3.4", 50002, True)] * 3),
        ), mock.patch(
            "core.electrum_servers.load_electrum_servers", return_value={},
        ), mock.patch.object(
            source_mod, "_loese_oeffentliches_onion_tor",
        ) as loese:
            out = source_mod._pruefe_oeffentliche_electrum(
                gefunden, values, timeout=1, on_log=logs.append,
            )
        loese.assert_called_once()
        self.assertEqual(out["public_onion"].peer_count, 0)
        self.assertIsNone(out["public_onion"].reachable)
        self.assertEqual(out["clearnet"].peer_count, 0)

    def test_kette_art_onion_nimmt_onion_ohne_clearnet(self):
        setze_oeffentliche_electrum_art("onion")
        onion = MagicMock()
        with patch.object(
            chain_sources, "_try_own_fulcrum_client", return_value=None,
        ), patch.object(
            chain_sources, "_try_bip158_backend", return_value=None,
        ), patch(
            "core.sanctions_pool.resolve_sanctions_clearnet_pool",
        ) as resolve, patch.object(
            chain_sources, "_try_public_onion_fulcrum", return_value=onion,
        ), patch.object(
            chain_sources, "_nach_oeffentlichem_onion_latenz",
            return_value=("fulcrum", onion),
        ):
            quelle, backend, _ = main._try_data_source_priority_chain(
                self.args, {"OEFFENTLICHE_ELECTRUM": "1"}, include_bip158=True,
            )
        resolve.assert_not_called()
        self.assertEqual(quelle, "fulcrum")
        self.assertIs(backend, onion)

    def test_kette_art_clearnet_kein_onion_fallback(self):
        setze_oeffentliche_electrum_art("clearnet")
        with patch.object(
            chain_sources, "_try_own_fulcrum_client", return_value=None,
        ), patch.object(
            chain_sources, "_try_bip158_backend", return_value=None,
        ), patch(
            "core.sanctions_pool.resolve_sanctions_clearnet_pool",
            return_value=(None, False),
        ), patch.object(
            chain_sources, "_setup_public_onion_rotation",
        ) as onion_rot:
            result = main._try_data_source_priority_chain(
                self.args, {"OEFFENTLICHE_ELECTRUM": "1"}, include_bip158=True,
            )
        onion_rot.assert_not_called()
        self.assertIsNone(result)


class TestOeffentlicherEmpfangArt(unittest.TestCase):

    def setUp(self):
        _reset_oeffentliche_electrum_suche_fuer_tests()
        self.addCleanup(_reset_oeffentliche_electrum_suche_fuer_tests)

    def _state(self):
        class _S:
            def __init__(self):
                self._empfang_fulcrum_lock = threading.Lock()
                self._empfang_public_fulcrum = None

            def env(self):
                return SimpleNamespace(
                    values=lambda: {"OEFFENTLICHE_ELECTRUM": "1"},
                )

            def args_namespace(self):
                return SimpleNamespace()

        return _S()

    def test_empfang_art_onion_kein_clearnet(self):
        from httpserver import empfang as empfang_mod
        import server

        setze_oeffentliche_electrum_art("onion")
        onion_pool = object()
        state = self._state()
        with patch.object(
            server.main, "_try_public_onion_fulcrum", return_value=onion_pool,
        ) as onion, patch.object(
            server.main, "_setup_public_clearnet_fulcrum",
        ) as clear:
            pool = empfang_mod._oeffentlicher_fulcrum_fuer_empfang(state)
        self.assertIs(pool, onion_pool)
        onion.assert_called_once()
        clear.assert_not_called()

    def test_empfang_art_clearnet_kein_onion(self):
        from httpserver import empfang as empfang_mod
        import server

        setze_oeffentliche_electrum_art("clearnet")
        clear_pool = object()
        state = self._state()
        with patch.object(
            server.main, "_try_public_onion_fulcrum",
        ) as onion, patch.object(
            server.main, "_setup_public_clearnet_fulcrum",
            return_value=clear_pool,
        ) as clear:
            pool = empfang_mod._oeffentlicher_fulcrum_fuer_empfang(state)
        self.assertIs(pool, clear_pool)
        clear.assert_called_once()
        onion.assert_not_called()

    def test_empfang_ohne_wahl_clearnet_zuerst(self):
        from httpserver import empfang as empfang_mod
        import server

        clear_pool = object()
        state = self._state()
        with patch.object(
            server.main, "_try_public_onion_fulcrum",
        ) as onion, patch.object(
            server.main, "_setup_public_clearnet_fulcrum",
            return_value=clear_pool,
        ):
            pool = empfang_mod._oeffentlicher_fulcrum_fuer_empfang(state)
        self.assertIs(pool, clear_pool)
        onion.assert_not_called()


if __name__ == "__main__":
    unittest.main()
