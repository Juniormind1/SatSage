"""Unit-Tests für core.tx_classify — Eigentum zuerst, dann Formheuristik."""
from __future__ import annotations

import unittest

import analyze
from core import tx_classify
from tests.fixtures import (
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    BIP84_RECEIVE_1,
    EXTERN_A,
    EXTERN_B,
    core_tx,
    core_vin,
    core_vout,
    make_get_tx,
    txid,
)

EXTERN_C = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
EIGENE = {BIP84_RECEIVE_0, BIP84_RECEIVE_1, BIP84_CHANGE_0}


class TestOwnership(unittest.TestCase):
    def test_outputs_ohne_prevout_inputs_unknown(self):
        t = core_tx(
            txid("o1"),
            [core_vin(txid("p0"), 0)],
            [core_vout(0, BIP84_RECEIVE_0, 0.1)],
        )
        own = tx_classify.analyze_ownership(t, EIGENE)
        self.assertEqual(own.own_output_count, 1)
        self.assertEqual(own.unknown_input_count, 1)
        self.assertFalse(own.ownership_complete)

    def test_own_prevouts_stufe1(self):
        prev = txid("p1")
        t = core_tx(
            txid("c1"),
            [core_vin(prev, 0), core_vin(txid("f1"), 0)],
            [core_vout(0, BIP84_RECEIVE_0, 0.05)],
        )
        own = tx_classify.analyze_ownership(
            t, EIGENE, own_prevouts={f"{prev}:0"}
        )
        self.assertEqual(own.own_input_indices, (0,))
        self.assertEqual(own.unknown_input_count, 1)


class TestFanOutPayJoinExchange(unittest.TestCase):
    def test_fan_out_own(self):
        vins = [core_vin(txid("a0"), 0)]
        vins[0]["prevout"] = {
            "value": 1.0,
            "scriptPubKey": {"address": BIP84_RECEIVE_0},
        }
        outs = [
            core_vout(i, BIP84_RECEIVE_1 if i < 9 else BIP84_CHANGE_0, 0.1)
            for i in range(10)
        ]
        t = core_tx(txid("fo"), vins, outs)
        c = tx_classify.classify_tx(t, EIGENE)
        self.assertEqual(c.kind, "fan_out_own")
        self.assertFalse(c.walk_own_inputs_only)

    def test_exchange_batch(self):
        vins = [core_vin(txid(f"ex{i}"), 0) for i in range(5)]
        for i, v in enumerate(vins):
            v["prevout"] = {
                "value": 0.2,
                "scriptPubKey": {
                    "address": EXTERN_A if i % 2 == 0 else EXTERN_B
                },
            }
        outs = [core_vout(0, BIP84_RECEIVE_0, 0.15)] + [
            core_vout(i + 1, EXTERN_C, 0.1) for i in range(4)
        ]
        t = core_tx(txid("xb"), vins, outs)
        c = tx_classify.classify_tx(t, EIGENE)
        self.assertEqual(c.kind, "exchange_batch")
        self.assertFalse(c.is_coinjoin)

    def test_payjoin(self):
        vins = [
            core_vin(txid("own"), 0),
            core_vin(txid("peer"), 0),
        ]
        vins[0]["prevout"] = {
            "value": 0.05,
            "scriptPubKey": {"address": BIP84_RECEIVE_0},
        }
        vins[1]["prevout"] = {
            "value": 0.04,
            "scriptPubKey": {"address": EXTERN_A},
        }
        outs = [
            core_vout(0, EXTERN_B, 0.07),
            core_vout(1, BIP84_CHANGE_0, 0.019),
        ]
        t = core_tx(txid("pj"), vins, outs)
        c = tx_classify.classify_tx(t, EIGENE)
        self.assertEqual(c.kind, "payjoin")
        self.assertFalse(c.walk_own_inputs_only)


class TestCoinJoinForms(unittest.TestCase):
    def _cj_like(
        self,
        *,
        n_own_in: int,
        n_foreign_in: int,
        equal_outs: int,
        equal_btc: float,
        change_outs: int,
        change_btc: float,
    ):
        vins = []
        for i in range(n_own_in):
            v = core_vin(txid(f"o{i:02x}"), 0)
            v["prevout"] = {
                "value": equal_btc,
                "scriptPubKey": {
                    "address": (
                        BIP84_RECEIVE_0 if i % 2 == 0 else BIP84_CHANGE_0
                    )
                },
            }
            vins.append(v)
        for i in range(n_foreign_in):
            v = core_vin(txid(f"f{i:02x}"), 0)
            v["prevout"] = {
                "value": equal_btc,
                "scriptPubKey": {"address": EXTERN_A},
            }
            vins.append(v)
        outs = []
        for i in range(equal_outs):
            addr = BIP84_RECEIVE_1 if i == 0 else EXTERN_B
            outs.append(core_vout(i, addr, equal_btc))
        for j in range(change_outs):
            addr = BIP84_CHANGE_0 if j == 0 else EXTERN_C
            outs.append(core_vout(equal_outs + j, addr, change_btc))
        return core_tx(txid("cj"), vins, outs)

    def test_whirlpool_5x5(self):
        t = self._cj_like(
            n_own_in=1,
            n_foreign_in=4,
            equal_outs=5,
            equal_btc=0.01,
            change_outs=0,
            change_btc=0,
        )
        c = tx_classify.classify_tx(t, EIGENE)
        self.assertEqual(c.kind, "whirlpool")
        self.assertTrue(c.walk_own_inputs_only)

    def test_wasabi_classic_many_equal(self):
        t = self._cj_like(
            n_own_in=6,
            n_foreign_in=18,
            equal_outs=24,
            equal_btc=0.045,
            change_outs=4,
            change_btc=0.029,
        )
        c = tx_classify.classify_tx(t, EIGENE)
        self.assertEqual(c.kind, "wasabi_classic")
        self.assertEqual(
            c.soft_label_de, "Wahrscheinlich Wasabi-CoinJoin (Classic)"
        )

    def test_wabisabi_unequal(self):
        vins = []
        for i in range(16):
            v = core_vin(txid(f"w{i:02x}"), 0)
            addr = BIP84_RECEIVE_0 if i < 2 else EXTERN_A
            v["prevout"] = {
                "value": 0.05,
                "scriptPubKey": {"address": addr},
            }
            vins.append(v)
        amounts = [
            0.031, 0.022, 0.017, 0.011, 0.009, 0.007, 0.005, 0.004,
            0.033, 0.019, 0.013, 0.008, 0.006, 0.003, 0.002, 0.001,
        ]
        outs = []
        for i, btc in enumerate(amounts):
            addr = BIP84_RECEIVE_1 if i == 0 else EXTERN_B
            outs.append(core_vout(i, addr, btc))
        t = core_tx(txid("ws"), vins, outs)
        c = tx_classify.classify_tx(t, EIGENE)
        self.assertEqual(c.kind, "wabisabi")

    def test_joinmarket_like(self):
        t = self._cj_like(
            n_own_in=1,
            n_foreign_in=3,
            equal_outs=4,
            equal_btc=0.1,
            change_outs=3,
            change_btc=0.05,
        )
        c = tx_classify.classify_tx(t, EIGENE)
        self.assertEqual(c.kind, "joinmarket")


class TestTraceOwnOnly(unittest.TestCase):
    def test_cj_trace_ohne_peer_externals(self):
        eigener = txid("e0")
        ziel = txid("z0")
        vins = [core_vin(eigener, 0)] + [
            core_vin(txid(f"p{i}"), 0) for i in range(4)
        ]
        for i, v in enumerate(vins):
            addr = BIP84_CHANGE_0 if i == 0 else EXTERN_A
            v["prevout"] = {
                "value": 0.01,
                "scriptPubKey": {"address": addr},
            }
        outs = [
            core_vout(i, BIP84_RECEIVE_0 if i == 0 else EXTERN_B, 0.01)
            for i in range(5)
        ]
        chain = {
            eigener: core_tx(
                eigener,
                [{"coinbase": "01", "sequence": 0, "is_coinbase": True}],
                [core_vout(0, BIP84_CHANGE_0, 0.01)],
            ),
            ziel: core_tx(ziel, vins, outs),
        }
        node = analyze.trace_utxo_origin(
            make_get_tx(chain), ziel, 0, EIGENE
        )
        self.assertEqual(node.get("tx_class"), "whirlpool")
        typen = [q["type"] for q in node["sources"]]
        self.assertNotIn("external", typen)
        self.assertNotIn("external_unresolved", typen)
        self.assertIn("internal", typen)


if __name__ == "__main__":
    unittest.main()
