"""UTXO-Cache-Frischheit für Verlaufs-Job (kein Doppel-Gap)."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import main

XPUB = (
    "xpub6D4BDPcP2GT577Vvch3R8wDkScZWzQzMMUm3PWbmWvVJrZwQY4VUNgqFJPMM3N"
    "o2dFDFGTsxxpG5uJh7n7epu4trkrX7x7DogT5Uf1nxASY"
)


class TestUtxoCacheFrisch(unittest.TestCase):
    def test_frisch_nach_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            main.save_xpub_utxo_cache(
                XPUB,
                [{"txid": "ab" * 32, "vout": 0, "value": 1, "address": "bc1q"}],
                cache,
                "fulcrum",
            )
            utxos, grund = main.utxo_cache_frisch_genug([XPUB], cache)
            self.assertIsNotNone(utxos)
            self.assertEqual(len(utxos), 1)
            self.assertIn("Gap-Scan übersprungen", grund)

    def test_zu_alt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            main.save_xpub_utxo_cache(
                XPUB,
                [{"txid": "ab" * 32, "vout": 0, "value": 1, "address": "bc1q"}],
                cache,
                "fulcrum",
            )
            pfad = main._xpub_cache_path(XPUB, cache)
            data = json.loads(pfad.read_text(encoding="utf-8"))
            data["scanned_at"] = (
                datetime.now(main.UTC) - timedelta(hours=3)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            pfad.write_text(json.dumps(data), encoding="utf-8")
            utxos, grund = main.utxo_cache_frisch_genug([XPUB], cache)
            self.assertIsNone(utxos)
            self.assertIn("alt", grund)

    def test_bip158_partial_zaehlt_nicht(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            main.save_xpub_utxo_cache(
                XPUB,
                [{"txid": "ab" * 32, "vout": 0, "value": 1, "address": "bc1q"}],
                cache,
                "bip158",
                bip158_fullscan_ok=False,
            )
            utxos, grund = main.utxo_cache_frisch_genug([XPUB], cache)
            self.assertIsNone(utxos)
            self.assertIn("unvollst", grund)


if __name__ == "__main__":
    unittest.main()
