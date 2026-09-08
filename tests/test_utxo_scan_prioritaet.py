"""
UTXO-Bestand: Electrs-LAN vor Core-scantxoutset.

Ohne diese Regel startet Cash+Carry mit LAN-Electrs trotzdem einen
~1‑Minuten-scantxoutset — und die Oberfläche wartet unnötig.
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
        self.assertFalse(main._utxo_scan_scantxoutset_vorrang(lan))

    def test_electrs_onion_laesst_core_zuerst(self):
        onion = _client(host="abc.onion", tor_proxy=("127.0.0.1", 9050))
        self.assertFalse(main._fulcrum_transport_ist_lan(onion))
        self.assertTrue(main._utxo_scan_scantxoutset_vorrang(onion))

    def test_oeffentlicher_pool_laesst_core_zuerst(self):
        pool = MagicMock(spec=RotatingFulcrumPool)
        self.assertFalse(main._fulcrum_transport_ist_lan(pool))
        self.assertTrue(main._utxo_scan_scantxoutset_vorrang(pool))

    def test_ohne_fulcrum_core_vor_bip158(self):
        self.assertTrue(main._utxo_scan_scantxoutset_vorrang(None))

    def test_try_scantxoutset_ueberspringt_bei_lan_electrs(self):
        lan = _client(host="10.0.0.2")
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
