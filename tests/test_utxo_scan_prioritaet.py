"""
UTXO-Bestand: Electrs-LAN vor Core-scantxoutset (auch vor lokalem UTXO-Slot).
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import main
from fulcrum import FulcrumClient, RotatingFulcrumPool


def _client(*, host: str, tor_proxy=None) -> MagicMock:
    c = MagicMock(spec=FulcrumClient)
    c.host = host
    c.tor_proxy = tor_proxy
    return c


class TestUtxoScanPrioritaet(unittest.TestCase):
    def test_electrs_lan_schlaegt_scantxoutset(self):
        lan = _client(host="192.168.1.100")
        self.assertTrue(main._fulcrum_transport_ist_lan(lan))
        self.assertFalse(main._utxo_scan_scantxoutset_vorrang(lan, env={}))

    def test_electrs_lan_schlaegt_auch_lokalen_utxo_slot(self):
        lan = _client(host="192.168.1.100")
        env = {"UTXO_RPC_HOST": "127.0.0.1", "UTXO_RPC_COOKIE_FILE": "/x/.cookie"}
        self.assertFalse(main._utxo_scan_scantxoutset_vorrang(lan, env=env))

    def test_electrs_onion_laesst_core_zuerst(self):
        onion = _client(host="abc.onion", tor_proxy=("127.0.0.1", 9050))
        self.assertFalse(main._fulcrum_transport_ist_lan(onion))
        self.assertTrue(main._utxo_scan_scantxoutset_vorrang(onion, env={}))

    def test_oeffentlicher_pool_laesst_core_zuerst(self):
        pool = MagicMock(spec=RotatingFulcrumPool)
        self.assertFalse(main._fulcrum_transport_ist_lan(pool))
        self.assertTrue(main._utxo_scan_scantxoutset_vorrang(pool, env={}))

    def test_ohne_fulcrum_core_vor_bip158(self):
        self.assertTrue(main._utxo_scan_scantxoutset_vorrang(None, env={}))

    def test_try_scantxoutset_ueberspringt_bei_lan_electrs(self):
        lan = _client(host="10.0.0.2")
        with patch.object(main, "_load_dotenv", return_value={
            "UTXO_RPC_HOST": "127.0.0.1",
        }):
            with patch("core.bitcoind_rpc.try_scantxoutset_for_xpubs") as mock_core:
                out = main._try_scantxoutset_xpub(
                    "zpub6rFR7y4Q2AijBEqTUquhVz38LU3R8JGvG4RZQRVfBLWjqs2mJg9gH4z4",
                    main.UTXO_CACHE_DIR,
                    fulcrum=lan,
                )
                self.assertIsNone(out)
                mock_core.assert_not_called()


if __name__ == "__main__":
    unittest.main()
