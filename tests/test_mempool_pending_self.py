"""
Mempool-Selbstüberweisung: eigene Empfänge aus Spend-Tx + Bestandssumme.
"""
from __future__ import annotations

import unittest

from core.utxos import rank_wallet_utxos, utxo_as_dict
from fulcrum import eigene_mempool_empfaenge


class FakeClient:
    def __init__(self, txs: dict):
        self.txs = {k.lower(): v for k, v in txs.items()}

    def request(self, method, params):
        if method == "blockchain.transaction.get":
            return self.txs[str(params[0]).lower()]
        raise RuntimeError(method)


class TestEigeneMempoolEmpfaenge(unittest.TestCase):
    def test_nur_eigene_outputs(self):
        txid = "aa" * 32
        prev = "bb" * 32
        tx = {
            "txid": txid,
            "vin": [{"txid": prev, "vout": 1}],
            "vout": [
                {"value": 0.0001, "scriptPubKey": {"address": "bc1qa"}},
                {"value": 0.001, "scriptPubKey": {"address": "bc1qb"}},
                {"value": 0.002, "scriptPubKey": {"address": "bc1qexternal"}},
            ],
        }
        client = FakeClient({txid: tx})
        pending = [{
            "txid": prev,
            "vout": 1,
            "value": 310_000,
            "address": "bc1qold",
            "spent_txid": txid,
        }]
        empf = eigene_mempool_empfaenge(
            client,
            pending,
            is_own_address=lambda a: a in ("bc1qa", "bc1qb"),
        )
        self.assertEqual(len(empf), 2)
        self.assertEqual(sum(e["value"] for e in empf), 10_000 + 100_000)
        self.assertTrue(all(e.get("receive_pending") for e in empf))
        self.assertTrue(all(e["status"].get("confirmed") is False for e in empf))


class TestRankPendingTotals(unittest.TestCase):
    def test_spending_pending_nicht_doppelt(self):
        txid = "aa" * 32
        prev = "bb" * 32
        empf = [
            {
                "txid": txid,
                "vout": 0,
                "value": 10_000,
                "address": "bc1qa",
                "status": {"confirmed": False},
                "receive_pending": True,
            },
            {
                "txid": txid,
                "vout": 1,
                "value": 100_000,
                "address": "bc1qb",
                "status": {"confirmed": False},
                "receive_pending": True,
            },
        ]
        spending = {
            "txid": prev,
            "vout": 1,
            "value": 310_000,
            "address": "bc1qold",
            "status": {
                "confirmed": True,
                "block_height": 1,
                "block_time": 1_700_000_000,
            },
            "spending_pending": True,
            "spent_txid": txid,
        }
        ranked = rank_wallet_utxos([spending] + empf)
        self.assertEqual(ranked["total_sats"], 110_000)
        self.assertEqual(ranked["pending_spending_count"], 1)
        self.assertEqual(ranked["pending_receive_count"], 2)
        self.assertTrue(utxo_as_dict(empf[0])["receive_pending"])
        self.assertTrue(utxo_as_dict(spending)["spending_pending"])


if __name__ == "__main__":
    unittest.main()
