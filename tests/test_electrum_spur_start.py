"""409-Startbug: ohne Quellen-Check zählt ein erreichbarer eigener Electrs."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from httpserver.api import trace as trace_api


def _state(sources_last):
    env = SimpleNamespace(values=lambda: {"FULCRUM_HOST": "127.0.0.1", "FULCRUM_PORT": "50031"})
    return SimpleNamespace(env=lambda: env, sources_last=sources_last)


class TestElectrumSpurNachStart(unittest.TestCase):
    def setUp(self):
        p = patch("core.wallet_watch.wallet_watch_status", return_value={})
        p.start()
        self.addCleanup(p.stop)

    def test_leere_quellen_eigener_electrs_erreichbar_kein_409(self):
        with patch("core.chain_sources.eigene_electrs_ist_verbunden", return_value=True) as probe:
            trace_api.verlange_electrum_fuer_spur(_state(None))
        probe.assert_called_once()

    def test_leere_quellen_nicht_erreichbar_409(self):
        from server import ApiError

        with patch("core.chain_sources.eigene_electrs_ist_verbunden", return_value=False):
            with self.assertRaises(ApiError) as ctx:
                trace_api.verlange_electrum_fuer_spur(_state([]))
        self.assertEqual(ctx.exception.status, 409)

    def test_vorhandener_check_ohne_electrum_kein_probe(self):
        """Steht ein Quellen-Check (z. B. Electrs bewusst verworfen), gilt er."""
        from server import ApiError

        quellen = [{"key": "own_fulcrum", "reachable": False}]
        with patch("core.chain_sources.eigene_electrs_ist_verbunden") as probe:
            with self.assertRaises(ApiError):
                trace_api.verlange_electrum_fuer_spur(_state(quellen))
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
