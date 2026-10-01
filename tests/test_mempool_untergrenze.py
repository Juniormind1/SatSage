"""Unbestätigte Tx: Mindesthöhe ist der Chain-Tip, nicht Höhe 0."""
import json
import tempfile
import unittest
from pathlib import Path

from core import fulcrum_history as fh
from core import xpub_cache


class _Client:
    pass


class TestMempoolMindesthoehe(unittest.TestCase):

    def setUp(self):
        self._lookup = fh._lookup_tx_height
        self._tip = fh.get_chain_tip_height
        self._zeit = fh._block_time_for_height
        fh._lookup_tx_height = lambda *_a, **_k: 0
        fh.get_chain_tip_height = lambda *_a, **_k: 900_000
        fh._block_time_for_height = lambda *_a, **_k: 1_700_000_000

    def tearDown(self):
        fh._lookup_tx_height = self._lookup
        fh.get_chain_tip_height = self._tip
        fh._block_time_for_height = self._zeit

    def test_mempool_bekommt_tip_als_mindesthoehe(self):
        tx = {"txid": "ab" * 32, "vout": []}
        out = fh._enrich_tx_block_info(_Client(), tx)
        status = out["status"]
        self.assertFalse(status["confirmed"])
        self.assertTrue(status["mindesthoehe"])
        self.assertEqual(status["block_height"], 900_000)
        self.assertEqual(status["block_time"], 1_700_000_000)
        self.assertEqual(out["blockheight"], 900_000)
        self.assertEqual(out["confirmations"], 0)

    def test_bestaetigte_hoehe_bleibt_bestaetigt(self):
        fh._lookup_tx_height = lambda *_a, **_k: 800_000
        fh._block_time_for_height = lambda *_a, **_k: 1_600_000_000
        tx = {"txid": "cd" * 32, "vout": []}
        out = fh._enrich_tx_block_info(_Client(), tx)
        status = out["status"]
        self.assertTrue(status["confirmed"])
        self.assertNotIn("mindesthoehe", status)
        self.assertEqual(status["block_height"], 800_000)
        self.assertEqual(status["block_time"], 1_600_000_000)

    def test_untergrenze_wird_nicht_geschrieben(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wurzel = Path(tmp.name)
        txid = "ef" * 32
        xpub_cache.save_cached_tx(txid, {
            "txid": txid,
            "status": {
                "confirmed": False,
                "block_height": 900_000,
                "block_time": 1_700_000_000,
                "mindesthoehe": True,
            },
        }, wurzel, "test")
        self.assertFalse((wurzel / "tx" / f"{txid}.json").is_file())
        self.assertIsNone(xpub_cache.load_cached_tx(txid, wurzel))

    def test_hoehe_ohne_zeit_wird_aus_header_ueberschrieben(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wurzel = Path(tmp.name)
        txid = "11" * 32
        xpub_cache.save_cached_block_time(939_116, 1_760_000_000, wurzel, "test")
        pfad = wurzel / "tx" / f"{txid}.json"
        pfad.parent.mkdir(parents=True)
        pfad.write_text(json.dumps({
            "txid": txid,
            "source": "alt",
            "tx": {
                "txid": txid,
                "blockheight": 939_116,
                "status": {
                    "confirmed": True,
                    "block_height": 939_116,
                    "block_time": None,
                },
            },
        }), encoding="utf-8")
        tx = xpub_cache.load_cached_tx(txid, wurzel)
        self.assertEqual(tx["status"]["block_time"], 1_760_000_000)
        self.assertEqual(tx["blocktime"], 1_760_000_000)
        roh = json.loads(pfad.read_text(encoding="utf-8"))
        self.assertEqual(roh["tx"]["status"]["block_time"], 1_760_000_000)

    def test_unvollstaendig_wird_nicht_geschrieben(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wurzel = Path(tmp.name)
        txid = "22" * 32
        xpub_cache.save_cached_tx(txid, {
            "txid": txid,
            "blockheight": 939_116,
            "status": {"confirmed": True, "block_height": 939_116, "block_time": None},
        }, wurzel, "test")
        self.assertFalse((wurzel / "tx" / f"{txid}.json").is_file())
