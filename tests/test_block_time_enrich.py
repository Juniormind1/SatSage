"""Fehlende UTXO-Blockzeiten aus lokalem Header-Cache nachziehen."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.utxos import load_cached_utxos, utxo_as_dict
from main import (
    block_time_for_height,
    enrich_utxos_with_block_times,
    save_cached_block_time,
)


class TestBlockTimeForHeight(unittest.TestCase):
    def test_aus_json_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_cached_block_time(912_682, 1_756_721_941, root, "test")
            self.assertEqual(block_time_for_height(912_682, root), 1_756_721_941)

    def test_ungueltige_hoehe(self):
        self.assertIsNone(block_time_for_height(0))
        self.assertIsNone(block_time_for_height(-1))


class TestEnrichUtxos(unittest.TestCase):
    def test_setzt_block_time_und_laesst_vorhandene(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_cached_block_time(100, 1_600_000_000, root, "test")
            save_cached_block_time(200, 1_700_000_000, root, "test")
            utxos = [
                {"txid": "aa" * 32, "vout": 0, "value": 1,
                 "status": {"confirmed": True, "block_height": 100}},
                {"txid": "bb" * 32, "vout": 0, "value": 2,
                 "status": {
                     "confirmed": True,
                     "block_height": 200,
                     "block_time": 1_111,
                 }},
            ]
            n = enrich_utxos_with_block_times(utxos, root)
            self.assertEqual(n, 1)
            self.assertEqual(utxos[0]["status"]["block_time"], 1_600_000_000)
            self.assertEqual(utxos[1]["status"]["block_time"], 1_111)


class TestLoadCachedPersists(unittest.TestCase):
    def test_schreibt_zeiten_zurueck(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "utxo_cache"
            imm = Path(tmp) / "immutable_cache"
            cache.mkdir()
            imm.mkdir()
            save_cached_block_time(912_682, 1_756_721_941, imm, "test")
            xpub = "zpubTestBlockTimeEnrich000000000000000000000"
            # Dateiname wie main._xpub_cache_key
            from main import _xpub_cache_key

            pfad = cache / f"{_xpub_cache_key(xpub)}.json"
            pfad.write_text(json.dumps({
                "xpub": xpub,
                "scanned_at": "2026-01-01T00:00:00Z",
                "source": "bitcoind",
                "scan_end_index": 25,
                "max_addresses": 50,
                "utxo_count": 1,
                "utxos": [{
                    "txid": "ab" * 32,
                    "vout": 0,
                    "value": 924433,
                    "address": "bc1qtest",
                    "status": {"confirmed": True, "block_height": 912682},
                }],
            }), encoding="utf-8")

            geladen = load_cached_utxos(
                xpub, cache, immutable_cache_dir=imm, persist_times=True,
            )
            self.assertIsNotNone(geladen)
            self.assertEqual(geladen[0]["status"]["block_time"], 1_756_721_941)

            erneut = json.loads(pfad.read_text(encoding="utf-8"))
            self.assertEqual(
                erneut["utxos"][0]["status"]["block_time"], 1_756_721_941,
            )
            # scanned_at unverändert (kein Full-Resave)
            self.assertEqual(erneut["scanned_at"], "2026-01-01T00:00:00Z")
            self.assertEqual(erneut["source"], "bitcoind")

            eintrag = utxo_as_dict(geladen[0], immutable_cache_dir=imm)
            self.assertIn(".", eintrag["time_label"])  # Datum, nicht nur Block
            self.assertNotIn("Block ", eintrag["time_label"])


if __name__ == "__main__":
    unittest.main()
