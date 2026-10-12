import tempfile
import unittest
from pathlib import Path

import main
from tests.fixtures import BIP84_ZPUB, BIP84_RECEIVE_0, txid


def _u(hoehe, marker="a"):
    return {
        "txid": txid(marker),
        "vout": 0,
        "address": BIP84_RECEIVE_0,
        "value": 1,
        "status": {"confirmed": True, "block_height": hoehe, "block_time": 1_600_000_000},
    }


class TestFirstSeenScan(unittest.TestCase):
    def test_from_utxos_nimmt_frueheste_hoehe(self):
        fs = main.first_seen_from_utxos([_u(800_000, "b"), _u(700_000, "a")])
        self.assertEqual(fs["height"], 700_000)

    def test_bip158_start_aus_alter(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            main.save_xpub_first_seen(
                BIP84_ZPUB, cache, {"height": 700_010, "time_ts": 1},
            )
            self.assertEqual(
                main.bip158_start_aus_first_seen(
                    BIP84_ZPUB, cache, floor=481_824, puffer=6,
                ),
                700_004,
            )

    def test_scan_start_nimmt_first_seen_auch_wenn_datenquelle_neuer(self):
        from core.bip158_wallet import scan_start_fuer_xpub

        class Client:
            def __init__(self, cache, start):
                self.cache_dir = cache
                self.start_height = start
                self.gap_limit = 100

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            main.save_xpub_first_seen(
                BIP84_ZPUB, cache, {"height": 700_010, "time_ts": 1},
            )
            plan = scan_start_fuer_xpub(Client(cache, 850_000), BIP84_ZPUB)
            self.assertEqual(plan["start"], 700_004)
            self.assertEqual(plan["start_grund"], "alter")

            leer = scan_start_fuer_xpub(
                Client(Path(tmp) / "leer", 850_000), BIP84_ZPUB,
            )
            self.assertEqual(leer["start"], 850_000)
            self.assertEqual(leer["start_grund"], "konfiguriert")

            main.save_xpub_utxo_cache(
                BIP84_ZPUB, [_u(900_000)], cache, "bip158",
                scan_tip_height=900_000, bip158_fullscan_ok=True,
            )
            tip = scan_start_fuer_xpub(Client(cache, 850_000), BIP84_ZPUB)
            self.assertEqual(tip["start_grund"], "tip")
            self.assertGreater(tip["start"], 700_004)

    def test_ermittle_first_seen_aus_utxos_ohne_fulcrum(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            fs = main.ermittle_first_seen(
                BIP84_ZPUB, [BIP84_RECEIVE_0], cache, None, utxos=[_u(650_000)],
            )
            self.assertEqual(fs["height"], 650_000)
            main.save_xpub_first_seen(BIP84_ZPUB, cache, fs)
            # Zweiter Aufruf: Alter-Datei, nicht erneut aus UTXO
            fs2 = main.ermittle_first_seen(
                BIP84_ZPUB, [], cache, None, utxos=[_u(900_000)],
            )
            self.assertEqual(fs2["height"], 650_000)


if __name__ == "__main__":
    unittest.main()
