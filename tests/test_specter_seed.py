"""Unit-Tests für Specter → SatSage Cache-Seed (ohne laufendes Specter)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SRC = ROOT / "specter_plugin" / "src"
if str(PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SRC))

from satsage.specterext.satsage import specter_seed as seed  # noqa: E402
from satsage.specterext.satsage.bridge import SatSageContext, SpecterWalletInfo  # noqa: E402


class FakeWallet:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def getlabel(self, addr):
        return (self.labels or {}).get(addr)


class TestSpecterSeedHelpers(unittest.TestCase):
    def test_suggested_max_addresses_from_indices(self):
        w = FakeWallet(address_index=40, change_index=5, _addresses={})
        # tip = 40+20+1 = 61 → *2 = 122, min 200
        self.assertEqual(seed.suggested_max_addresses(w), 200)
        w2 = FakeWallet(address_index=120, change_index=10, _addresses={})
        self.assertGreaterEqual(seed.suggested_max_addresses(w2), 2 * (120 + 20 + 1))

    def test_verlauf_from_utxo(self):
        ein = seed._verlauf_from_utxo(
            {
                "txid": "aa" * 32,
                "vout": 1,
                "value": 12345,
                "address": "bcrt1qtest",
                "confirmations": 3,
                "status": {"confirmed": True, "block_height": 10, "block_time": 1000},
                "label": "Sparschwein",
            }
        )
        self.assertIsNotNone(ein)
        self.assertEqual(ein["vout"], 1)
        self.assertEqual(ein["value"], 12345)
        self.assertEqual(ein["label"], "Sparschwein")
        self.assertFalse(ein["spent"])

    def test_labels_merge_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            n = seed.merge_specter_labels(Path(tmp), {"bcrt1qa": "Alice", "bcrt1qb": "Bob"})
            self.assertEqual(n, 2)
            seed.merge_specter_labels(Path(tmp), {"bcrt1qa": "Alice2"})
            geladen = seed.load_specter_labels(Path(tmp))
            self.assertEqual(geladen["bcrt1qa"], "Alice2")
            self.assertEqual(geladen["bcrt1qb"], "Bob")

    def test_seed_caches_writes_utxo_and_verlauf(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            xpub = "vpubTestSeed000000000000000000000000000000000000000"
            w = FakeWallet(
                alias="alpha",
                name="Lab Alpha",
                keys=[
                    SimpleNamespace(
                        original=xpub,
                        xpub=xpub,
                        fingerprint="aabbccdd",
                        derivation="m/84h/1h/0h",
                        purpose="wpkh",
                    )
                ],
                address_index=3,
                change_index=1,
                _addresses={
                    "bcrt1qrecv0": {"address": "bcrt1qrecv0", "label": "Empfang", "index": 0},
                },
                labels={"bcrt1qrecv0": "Empfang"},
                full_utxo=[
                    {
                        "txid": "11" * 32,
                        "vout": 0,
                        "amount": 0.01,
                        "address": "bcrt1qrecv0",
                        "confirmations": 6,
                        "time": 1700000000,
                        "label": "Empfang",
                    }
                ],
                txlist=[
                    {
                        "txid": "11" * 32,
                        "category": "receive",
                        "vout": 0,
                        "amount": 0.01,
                        "address": "bcrt1qrecv0",
                        "confirmations": 6,
                        "time": 1700000000,
                        "blockheight": 100,
                    }
                ],
            )
            # Minimal specter stub
            specter = SimpleNamespace(
                wallet_manager=SimpleNamespace(wallets={"alpha": w}),
                node=None,
                chain="regtest",
            )
            ctx = SatSageContext(
                wallets=[
                    SpecterWalletInfo(
                        name="Lab Alpha",
                        alias="alpha",
                        xpubs=[xpub],
                    )
                ]
            )
            stats = seed.seed_caches_from_specter(specter, ctx, cache)
            self.assertGreaterEqual(stats["utxo_files"], 1)
            self.assertGreaterEqual(stats["labels"], 1)
            self.assertGreaterEqual(stats["verlauf_merged"], 1)
            labels = seed.load_specter_labels(cache)
            self.assertEqual(labels.get("bcrt1qrecv0"), "Empfang")
            # Verlauf-Datei existiert
            verlauf_files = list(cache.glob("*_verlauf.json")) + list(cache.glob("*.json"))
            self.assertTrue(any(p.name != "specter_address_labels.json" for p in cache.iterdir()))


if __name__ == "__main__":
    unittest.main()
