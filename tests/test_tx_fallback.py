"""Tx-Lookup ohne Electrs: Core → P2P-getdata → Block bei bekannter Höhe."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bip158_scanner import (
    clear_tx_height_hints,
    fetch_tx_p2p_mit_fallback,
    note_tx_height,
    tx_height_hint,
)
from core.bitcoind_rpc import normalize_core_tx
from core.trace import _blockhoehe_fuer_utxo, erklaere_fehler


class TestTxHeightHint(unittest.TestCase):
    def setUp(self):
        clear_tx_height_hints()

    def test_note_und_lesen(self):
        txid = "ab" * 32
        note_tx_height(txid, 900_000)
        self.assertEqual(tx_height_hint(txid), 900_000)
        self.assertIsNone(tx_height_hint("cd" * 32))


class TestNormalizeCoreTx(unittest.TestCase):
    def test_verbose_ohne_client(self):
        raw = {
            "txid": "ab" * 32,
            "vin": [{"txid": "cd" * 32, "vout": 1}],
            "vout": [{
                "n": 0,
                "value": 0.00924433,
                "scriptPubKey": {"hex": "0014" + "11" * 20, "address": "bc1qtest"},
            }],
            "confirmations": 10,
            "blocktime": 1_700_000_000,
        }
        tx = normalize_core_tx(raw, None)
        self.assertEqual(tx["txid"], "ab" * 32)
        self.assertEqual(tx["vin"][0]["vout"], 1)
        self.assertAlmostEqual(tx["vout"][0]["value"], 0.00924433)
        self.assertTrue(tx["status"]["confirmed"])
        self.assertEqual(tx["status"]["block_time"], 1_700_000_000)


class TestFallbackKette(unittest.TestCase):
    def setUp(self):
        clear_tx_height_hints()

    def test_core_gewinnt(self):
        client = MagicMock()
        core = MagicMock()
        erwartet = {"txid": "ab" * 32, "vin": [], "vout": [], "status": {"block_height": 1}}

        with patch("core.bitcoind_rpc.fetch_tx_core", return_value=erwartet) as mock_core:
            with patch("bip158_scanner.fetch_tx_p2p") as mock_p2p:
                out = fetch_tx_p2p_mit_fallback(
                    client, "ab" * 32, core_client=core,
                )
        self.assertEqual(out["txid"], "ab" * 32)
        mock_core.assert_called_once()
        mock_p2p.assert_not_called()

    def test_rollen_lokal_unter_prune_nimmt_archival(self):
        client = MagicMock()
        lokal = MagicMock()
        archival = MagicMock()
        erwartet = {"txid": "ab" * 32, "vin": [], "vout": [], "status": {"block_height": 50}}
        note_tx_height("ab" * 32, 50)

        with patch(
            "core.bitcoind_rpc.fetch_tx_core_mit_rollen", return_value=erwartet,
        ) as mock_rollen:
            with patch("bip158_scanner.fetch_tx_p2p") as mock_p2p:
                out = fetch_tx_p2p_mit_fallback(
                    client,
                    "ab" * 32,
                    local_core=lokal,
                    archival_core=archival,
                    local_pruneheight=100,
                )
        self.assertEqual(out["txid"], "ab" * 32)
        mock_rollen.assert_called_once()
        kw = mock_rollen.call_args.kwargs
        self.assertEqual(kw["height"], 50)
        self.assertEqual(kw["local_pruneheight"], 100)
        mock_p2p.assert_not_called()

    def test_block_nach_notfound(self):
        client = MagicMock()
        txid = "ab" * 32
        note_tx_height(txid, 962_859)
        block_tx = {"txid": txid, "vin": [], "vout": [], "status": {"block_height": 962_859}}

        with patch(
            "bip158_scanner.fetch_tx_p2p",
            side_effect=ConnectionError("Peer hat die Transaktion nicht"),
        ):
            with patch(
                "bip158_scanner.fetch_tx_from_block_p2p",
                return_value=block_tx,
            ) as mock_block:
                out = fetch_tx_p2p_mit_fallback(client, txid, core_client=None)
        self.assertEqual(out["status"]["block_height"], 962_859)
        mock_block.assert_called_once()
        self.assertEqual(mock_block.call_args.args[2], 962_859)

    def test_ohne_hoehe_klarer_fehler(self):
        client = MagicMock()
        with patch(
            "bip158_scanner.fetch_tx_p2p",
            side_effect=ConnectionError("Peer hat die Transaktion nicht"),
        ):
            with self.assertRaises(ConnectionError) as ctx:
                fetch_tx_p2p_mit_fallback(client, "ef" * 32, core_client=None)
        self.assertIn("keine Blockhöhe", str(ctx.exception))


class TestErklaereFehler(unittest.TestCase):
    def test_peer_notfound(self):
        text = erklaere_fehler("Peer hat die Transaktion nicht")
        self.assertIn("Block", text)
        self.assertIn("txindex", text.lower())

    def test_keine_hoehe(self):
        text = erklaere_fehler(
            "Transaktion nicht auflösbar ohne Electrs: keine Blockhöhe bekannt"
        )
        self.assertIn("Electrs", text)


class TestBlockhoeheCache(unittest.TestCase):
    def test_findet_hoehe_im_cache(self):
        txid = "60d6698d41e944025bbd1532de226cfe2e4254fbef427709d59106756642b6ab"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "deadbeefdeadbeef.json").write_text(
                json.dumps({
                    "xpub": "xpub-test",
                    "utxos": [{
                        "txid": txid,
                        "vout": 1,
                        "value": 924433,
                        "status": {"confirmed": True, "block_height": 962859},
                    }],
                }),
                encoding="utf-8",
            )
            h = _blockhoehe_fuer_utxo(txid, 1, root, wallet=None)
            self.assertEqual(h, 962859)


if __name__ == "__main__":
    unittest.main()
