"""Adressen aus Export-Verlauf nachziehen."""
from __future__ import annotations

import unittest

from core import export_adressen as adr
from tests.fixtures import BIP84_RECEIVE_0, BIP84_RECEIVE_1, txid


class TestExportAdressen(unittest.TestCase):

    def test_unique_txids(self):
        t1, t2 = txid("a1"), txid("a2")
        e = [
            {"txid": t1, "vout": 0},
            {"txid": t1, "vout": 1},
            {"txid": t2, "spent": True},
        ]
        self.assertEqual(adr.unique_txids(e), [t1, t2])

    def test_verlauf_ohne_adresse(self):
        e = [
            {"txid": txid("a1"), "address": BIP84_RECEIVE_0},
            {"txid": txid("a2"), "address": ""},
            {"txid": "kurz"},
        ]
        o = adr.verlauf_ohne_adresse(e)
        self.assertEqual(len(o), 1)
        self.assertEqual(o[0]["txid"], txid("a2"))

    def test_adresse_empfang_match(self):
        t = txid("r1")
        tx = {
            "txid": t,
            "vout": [
                {
                    "value": 0.0001,
                    "scriptPubKey": {"address": BIP84_RECEIVE_0},
                },
                {
                    "value": 0.5,
                    "scriptPubKey": {"address": BIP84_RECEIVE_1},
                },
            ],
        }
        own = {BIP84_RECEIVE_0, BIP84_RECEIVE_1}
        eintrag = {"txid": t, "vout": 0, "value": 10_000, "spent": False}
        addr, vout = adr.adresse_fuer_tx_eintrag(eintrag, tx, own=own)
        self.assertEqual(addr, BIP84_RECEIVE_0)
        self.assertEqual(vout, 0)

    def test_nachziehen_fuellt(self):
        t = txid("r2")
        own = {BIP84_RECEIVE_0}

        def get_tx(txid_s):
            return {
                "txid": txid_s,
                "vout": [{
                    "value": 0.0002,
                    "scriptPubKey": {"address": BIP84_RECEIVE_0},
                }],
            }

        verlauf = [
            {"txid": t, "vout": 0, "value": 20_000, "spent": False},
            {"txid": t, "vout": 0, "value": 20_000, "spent": False, "address": BIP84_RECEIVE_0},
        ]
        neu, stats = adr.nachziehen_verlauf_adressen(
            verlauf, own=own, get_tx=get_tx,
        )
        self.assertEqual(stats["filled"], 1)
        self.assertEqual(neu[0]["address"], BIP84_RECEIVE_0)

    def test_batch_prefetch_via_client(self):
        """Fulcrum-Client mit request_batch füllt mehrere Tx in einem Rutsch."""
        t1, t2 = txid("b1"), txid("b2")
        own = {BIP84_RECEIVE_0}

        class FakeClient:
            tor_proxy = ("127.0.0.1", 9050)

            def tor_batch_sinnvoll(self, n):
                return n >= 2

            def request_batch(self, calls):
                out = []
                for method, params in calls:
                    self.assertEqual(method, "blockchain.transaction.get")
                    tid = params[0]
                    out.append({
                        "txid": tid,
                        "vin": [],
                        "vout": [{
                            "value": 0.0001,
                            "scriptPubKey": {"address": BIP84_RECEIVE_0},
                        }],
                    })
                return out

            def assertEqual(self, a, b):
                assert a == b

        verlauf = [
            {"txid": t1, "vout": 0, "value": 10_000, "spent": False},
            {"txid": t2, "vout": 0, "value": 10_000, "spent": False},
        ]
        neu, stats = adr.nachziehen_verlauf_adressen(
            verlauf, own=own, fulcrum_client=FakeClient(),
        )
        self.assertEqual(stats["filled"], 2)
        self.assertEqual(stats["batched"], 1)
        self.assertEqual(neu[0]["address"], BIP84_RECEIVE_0)
        self.assertEqual(neu[1]["address"], BIP84_RECEIVE_0)


if __name__ == "__main__":
    unittest.main()
