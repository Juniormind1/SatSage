"""Lookup-Core gilt nur mit aktivem txindex. Pruned Node nicht."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.bitcoind_rpc import (
    TxindexFehltError,
    try_scantxoutset_for_xpubs,
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

    def test_pruned_node_ohne_txindex_bleibt_verbunden(self):
        client = _client()
        client.call.side_effect = lambda methode, *_a, **_k: {
            "getblockchaininfo": {
                "chain": "main", "blocks": 900_000, "pruned": True,
            },
        }[methode]
        logs: list[str] = []
        info = verify_core_rpc(
            client, on_log=logs.append, txindex_erforderlich=False,
        )
        self.assertFalse(info["txindex"])
        self.assertNotIn("Prüfe txindex…", logs)
        self.assertEqual(info["blocks"], 900_000)


class TestPrunedNodeScan(unittest.TestCase):
    def test_utxo_slot_scannt_ohne_getindexinfo(self):
        client = _client()
        methoden: list[str] = []

        def call(methode, *_a, **_k):
            methoden.append(methode)
            if methode == "getblockchaininfo":
                return {"chain": "main", "blocks": 900_000, "pruned": True}
            raise AssertionError(methode)

        client.call.side_effect = call
        env = {
            "UTXO_RPC_HOST": "192.0.2.1",
            "UTXO_RPCPORT": "8332",
            "UTXO_RPCUSER": "rpc",
            "UTXO_RPCPASSWORD": "geheim",
        }
        with patch(
            "core.bitcoind_rpc.stelle_utxo_core_client_bereit",
            return_value=client,
        ), patch(
            "core.bitcoind_rpc.scantxoutset_utxos",
            return_value=([], 900_000),
        ) as scan, patch(
            "core.derivation.derive_addresses",
            return_value=[],
        ):
            out = try_scantxoutset_for_xpubs(env, ["xpub-dummy"], default_max=2)
        self.assertIsNotNone(out)
        scan.assert_called_once()
        self.assertNotIn("getindexinfo", methoden)

    def test_lookup_fallback_ohne_txindex_scannt_nicht(self):
        client = _client()
        client.call.side_effect = lambda methode, *_a, **_k: {
            "getblockchaininfo": {"chain": "main", "blocks": 900_000},
            "getindexinfo": {},
        }[methode]
        env = {
            "NODE_IP": "192.0.2.1",
            "RPCPORT": "8332",
            "RPCUSER": "rpc",
            "RPCPASSWORD": "geheim",
        }
        with patch(
            "core.bitcoind_rpc.stelle_utxo_core_client_bereit",
            return_value=client,
        ), patch(
            "core.bitcoind_rpc.scantxoutset_utxos",
        ) as scan:
            out = try_scantxoutset_for_xpubs(env, ["xpub-dummy"], default_max=2)
        self.assertIsNone(out)
        scan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
