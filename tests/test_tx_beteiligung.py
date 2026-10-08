"""Gezielte Tx-Analyse: eigene Wallets in Inputs/Outputs."""
import unittest

from unittest.mock import patch

from core.tx_beteiligung import analysiere_tx, cache_deckt_analyse, parse_txid
from tests.fixtures import (
    BIP84_RECEIVE_0,
    EXTERN_A,
    TXID_EXTERN,
    TXID_SPEND,
    TXID_WALLET_IN,
    core_tx,
    core_vin,
    core_vout,
    esplora_tx,
    esplora_vin,
    esplora_vout,
    txid,
)


class _Wallet:
    def resolve_address(self, addr):
        if addr == BIP84_RECEIVE_0:
            return "Cold Storage"
        return None


class TestParseTxid(unittest.TestCase):
    def test_reine_txid(self):
        self.assertEqual(parse_txid("AA" * 32), "aa" * 32)

    def test_outpoint(self):
        self.assertEqual(parse_txid(f"{'bb' * 32}:3"), "bb" * 32)

    def test_ungueltig(self):
        self.assertIsNone(parse_txid(""))
        self.assertIsNone(parse_txid("kein-hash"))


class TestAnalysiereTx(unittest.TestCase):
    def test_eigenes_input_und_fremdes_output(self):
        tx = esplora_tx(
            TXID_SPEND,
            [esplora_vin(TXID_WALLET_IN, 0, BIP84_RECEIVE_0, 80_000)],
            [esplora_vout(EXTERN_A, 79_000)],
        )
        aus = analysiere_tx(TXID_SPEND, get_tx=lambda _t: tx, wallet=_Wallet())
        self.assertEqual(aus["eigene_inputs"], 1)
        self.assertEqual(aus["eigene_outputs"], 0)
        self.assertTrue(aus["inputs"][0]["eigen"])
        self.assertEqual(aus["inputs"][0]["wallet"], "Cold Storage")
        self.assertFalse(aus["outputs"][0]["eigen"])

    def test_eigenes_output(self):
        tx = esplora_tx(
            TXID_WALLET_IN,
            [esplora_vin(TXID_EXTERN, 1, EXTERN_A, 50_000)],
            [esplora_vout(BIP84_RECEIVE_0, 49_000)],
        )
        aus = analysiere_tx(TXID_WALLET_IN, get_tx=lambda _t: tx, wallet=_Wallet())
        self.assertEqual(aus["eigene_inputs"], 0)
        self.assertEqual(aus["eigene_outputs"], 1)
        self.assertEqual(aus["outputs"][0]["wallet"], "Cold Storage")

    def test_ungueltig_wirft(self):
        with self.assertRaises(ValueError):
            analysiere_tx("nein", get_tx=lambda _t: {})


class TestCacheDeckt(unittest.TestCase):
    def test_inline_prevout_reicht(self):
        tx = esplora_tx(
            TXID_SPEND,
            [esplora_vin(TXID_WALLET_IN, 0, BIP84_RECEIVE_0, 80_000)],
            [esplora_vout(EXTERN_A, 79_000)],
        )

        def lade(t, _root=None):
            return tx if t == TXID_SPEND else None

        with patch("core.tx_beteiligung.load_cached_tx", side_effect=lade):
            self.assertTrue(cache_deckt_analyse(TXID_SPEND))

    def test_ohne_parent_nicht(self):
        tx = core_tx(
            TXID_SPEND,
            [core_vin(TXID_WALLET_IN, 0)],
            [core_vout(0, EXTERN_A, 0.001)],
        )

        def lade(t, _root=None):
            return tx if t == TXID_SPEND else None

        with patch("core.tx_beteiligung.load_cached_tx", side_effect=lade):
            self.assertFalse(cache_deckt_analyse(TXID_SPEND))


if __name__ == "__main__":
    unittest.main()
