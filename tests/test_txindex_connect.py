"""Verbindung zu Core gilt nur mit aktivem txindex."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.bitcoind_rpc import (
    TxindexFehltError,
    txindex_aktiv,
    verify_core_rpc,
)


def _client() -> MagicMock:
    client = MagicMock()
    client.cfg.ziel = "192.0.2.1:8332"
    client.cfg.host = "192.0.2.1"
    client.cfg.port = 8332
    client.call.side_effect = lambda methode, *_a, **_k: {
        "getblockchaininfo": {"chain": "main", "blocks": 900_000},
        "getindexinfo": {"txindex": {"synced": True, "best_block_height": 900_000}},
    }[methode]
    return client


class TestTxindexVerbindung(unittest.TestCase):
    def test_aktiv_wenn_synced(self):
        self.assertTrue(txindex_aktiv({"txindex": {"synced": True}}))

    def test_inaktiv_ohne_eintrag(self):
        self.assertFalse(txindex_aktiv({}))
        self.assertFalse(txindex_aktiv({"txindex": {"synced": False}}))

    def test_verbindung_ok_mit_index(self):
        logs: list[str] = []
        info = verify_core_rpc(_client(), on_log=logs.append)
        self.assertTrue(info["txindex"])
        self.assertIn("txindex ist aktiv.", logs)

    def test_verbindung_abgelehnt_ohne_index(self):
        client = _client()
        client.call.side_effect = lambda methode, *_a, **_k: {
            "getblockchaininfo": {"chain": "main", "blocks": 900_000},
            "getindexinfo": {},
        }[methode]
        logs: list[str] = []
        with self.assertRaises(TxindexFehltError) as ctx:
            verify_core_rpc(client, on_log=logs.append)
        self.assertIn("txindex=1", str(ctx.exception))
        self.assertIn("Prüfe txindex…", logs)
        self.assertNotIn("txindex ist aktiv.", logs)


if __name__ == "__main__":
    unittest.main()
