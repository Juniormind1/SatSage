"""UTXO-Scan: Zwischenstand schon während des Laufs in Cache und Callback."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from fulcrum import collect_used_chain_indices_fulcrum, fetch_wallet_utxos_fulcrum
from tests.fixtures import BIP84_RECEIVE_0, BIP84_RECEIVE_1, BIP84_ZPUB, txid
from tests.test_fulcrum_verlauf import FakeFulcrumClient
from fulcrum import address_to_scripthash


def _utxo(marker="a1", sats=1000, address=BIP84_RECEIVE_0):
    return {
        "txid": txid(marker),
        "vout": 0,
        "address": address,
        "value": sats,
        "status": {"confirmed": True, "block_height": 800_000},
    }


class TestSchreibeUtxoZwischenstand(unittest.TestCase):
    def test_erhaelt_scan_end_und_laesst_tip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            main.save_xpub_utxo_cache(
                BIP84_ZPUB,
                [_utxo("alt")],
                cache,
                "fulcrum",
                scan_end_index=7,
                scan_tip_height=850_000,
            )
            neu = [_utxo("alt"), _utxo("neu", address=BIP84_RECEIVE_1)]
            main.schreibe_utxo_zwischenstand(
                BIP84_ZPUB, neu, cache, "fulcrum", max_addresses=50,
            )
            entry = main.load_xpub_cache_entry(BIP84_ZPUB, cache)
            self.assertEqual(entry["scan_end_index"], 7)
            self.assertEqual(entry["raw"].get("scan_tip_height"), 850_000)
            self.assertEqual(len(entry["utxos"]), 2)

    def test_ohne_vorherigen_cache_scan_end_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            main.schreibe_utxo_zwischenstand(
                BIP84_ZPUB, [_utxo()], cache, "bip158",
            )
            entry = main.load_xpub_cache_entry(BIP84_ZPUB, cache)
            self.assertEqual(entry["scan_end_index"], 0)
            self.assertEqual(len(entry["utxos"]), 1)


class TestGapScanMeldetUtxos(unittest.TestCase):
    def test_on_utxos_update_bei_fund(self):
        adresse = BIP84_RECEIVE_0
        sh = address_to_scripthash(adresse)
        client = FakeFulcrumClient(
            history_by_scripthash={sh: [{"tx_hash": txid("a1"), "height": 1}]},
            tx_by_id={},
        )
        gesehen = []

        with patch(
            "fulcrum.fetch_address_utxos_fulcrum",
            return_value=[{"txid": txid("aa"), "vout": 0, "value": 100}],
        ):
            collect_used_chain_indices_fulcrum(
                client, "xpubTEST", 0, 1, 2,
                lambda *_args: adresse,
                on_utxos_update=gesehen.append,
                kette="Empfang",
            )
        self.assertEqual(len(gesehen), 1)
        self.assertEqual(gesehen[0][0]["txid"], txid("aa"))
        self.assertEqual(gesehen[0][0]["address"], adresse)


class TestListunspentMeldetUtxos(unittest.TestCase):
    def test_sequentiell_meldet_zwischenstand(self):
        class Client:
            def request(self, method, params=None):
                if method == "blockchain.scripthash.listunspent":
                    # eine Adresse → ein UTXO
                    return [{
                        "tx_hash": txid("x1"),
                        "tx_pos": 0,
                        "value": 42,
                        "height": 1,
                    }]
                if method == "blockchain.block.header":
                    # 80-Byte-Header mit Timestamp an Offset 68
                    return ("00" * 68) + "01000000" + ("00" * 8)
                raise AssertionError(method)

        gesehen = []
        utxos = fetch_wallet_utxos_fulcrum(
            Client(),
            {BIP84_RECEIVE_0, BIP84_RECEIVE_1},
            on_utxos_update=gesehen.append,
        )
        self.assertEqual(len(utxos), 2)
        self.assertGreaterEqual(len(gesehen), 1)
        self.assertEqual(len(gesehen[-1]), 2)


class TestScanXpubZwischenstand(unittest.TestCase):
    def test_gap_schreibt_cache_vor_listunspent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            updates = []

            def fake_discover(*_a, **kw):
                on_u = kw.get("on_utxos_update")
                stand = [_utxo("early")]
                if on_u:
                    on_u(stand)
                return {BIP84_RECEIVE_0}, 2

            def fake_fetch(addrs, **kw):
                return [_utxo("final")]

            with patch("main.discover_wallet_scan_addresses", side_effect=fake_discover), \
                 patch("main._try_scantxoutset_xpub", return_value=None):
                out = main._scan_xpub_utxos(
                    BIP84_ZPUB,
                    fake_fetch,
                    cache,
                    "fulcrum",
                    max_addresses=50,
                    fulcrum=object(),
                    on_utxos_update=updates.append,
                )
            self.assertEqual(out[0]["txid"], txid("final"))
            # Zwischenstand schon während Gap, finaler Stand danach
            self.assertGreaterEqual(len(updates), 1)
            self.assertEqual(updates[0][0]["txid"], txid("early"))
            mid = main.load_xpub_cache_entry(BIP84_ZPUB, cache)
            self.assertEqual(len(mid["utxos"]), 1)
            self.assertEqual(mid["utxos"][0]["txid"], txid("final"))


if __name__ == "__main__":
    unittest.main()
