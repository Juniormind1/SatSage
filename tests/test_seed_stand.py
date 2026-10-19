"""Start-Pille aus dem schon gelesenen Cache, ohne die Dateien noch einmal zu parsen."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from core.config import WalletEntry
from core import wallets as wallets_mod
from core import xpub_cache
from core.wallet_context import (
    build_wallet_context,
    seed_wallet_addresses_from_utxo_cache,
    seed_wallet_addresses_from_verlauf_cache,
)

_XPUB = "zpub-seed-stand-nicht-echt"
_TXID = "ab" * 32


def _lege_cache(wurzel: Path, *, export_luecke: bool) -> None:
    xpub_cache.save_xpub_utxo_cache(
        _XPUB,
        [{"txid": _TXID, "vout": 0, "value": 5000, "address": "bcrt1qstand"}],
        wurzel,
        "cache",
        scan_end_index=4,
        first_seen={"height": 100, "time_ts": 1_500_000_000},
        scan_tip_height=200,
    )
    eintraege = [
        {"txid": _TXID, "vout": 0, "value": 5000, "address": "bcrt1qstand"},
        {"txid": _TXID, "vout": 1, "value": 1000, "address": "bcrt1qaus"},
    ]
    if export_luecke:
        eintraege.append({"txid": _TXID, "vout": 2, "value": 50, "address": ""})
    xpub_cache.save_xpub_verlauf_cache(_XPUB, eintraege, wurzel)


class TestSeedStand(unittest.TestCase):
    def test_pillenstand_aus_dem_speicher_gleicht_der_vollen_uebersicht(self):
        with TemporaryDirectory() as tmp:
            wurzel = Path(tmp)
            _lege_cache(wurzel, export_luecke=True)
            eintrag = WalletEntry(
                xpub=_XPUB, name="Kasse", script_type="segwit", origin="wallet_export",
            )
            erwartet = wallets_mod.summarize([eintrag], wurzel)[0].as_dict()
            cache_eintrag = xpub_cache.load_xpub_cache_entry(_XPUB, wurzel)
            verlauf = xpub_cache.load_xpub_verlauf_cache(_XPUB, wurzel)
            with mock.patch.object(
                wallets_mod.xpub_cache, "load_xpub_cache_entry",
                side_effect=AssertionError("UTXO-JSON noch einmal"),
            ), mock.patch.object(
                wallets_mod.xpub_cache, "load_xpub_verlauf_cache",
                side_effect=AssertionError("Verlauf noch einmal"),
            ):
                stand = wallets_mod.zusammenfassung_aus_gelesenem(
                    eintrag, wurzel, cache_eintrag=cache_eintrag, verlauf=verlauf,
                ).as_dict()
        self.assertEqual(stand, erwartet)
        self.assertEqual(stand["utxo_count"], 1)
        self.assertEqual(stand["total_sats"], 5000)
        self.assertEqual(stand["scan_tip_height"], 200)
        self.assertEqual(stand["first_seen_height"], 100)
        self.assertEqual(stand["export_import"], "partial")
        self.assertEqual(stand["export_ohne_adresse"], 1)
        self.assertGreater(stand["export_verlauf_n"], 1)
        self.assertTrue(stand["has_cache"])
        self.assertIsInstance(stand["cache_mtime"], int)

    def test_seed_behaelt_den_stand_fuer_die_pille(self):
        with TemporaryDirectory() as tmp:
            wurzel = Path(tmp)
            _lege_cache(wurzel, export_luecke=False)
            ctx = build_wallet_context(
                [_XPUB], wallet_names=["Kasse"], ableiten=False,
            )
            utxo_gemerkt: dict = {}
            verlauf_gemerkt: dict = {}
            seed_wallet_addresses_from_utxo_cache(
                ctx, [_XPUB], wurzel, scan_end_ableiten=False, merken=utxo_gemerkt,
            )
            seed_wallet_addresses_from_verlauf_cache(
                ctx, [_XPUB], wurzel, merken=verlauf_gemerkt,
            )
            self.assertIn(_XPUB, utxo_gemerkt)
            self.assertEqual(len(utxo_gemerkt[_XPUB]["utxos"]), 1)
            self.assertGreaterEqual(len(verlauf_gemerkt[_XPUB]), 2)
            eintrag = WalletEntry(xpub=_XPUB, name="Kasse", script_type="segwit")
            with mock.patch.object(
                wallets_mod.xpub_cache, "load_xpub_cache_entry",
                side_effect=AssertionError("UTXO-JSON noch einmal"),
            ), mock.patch.object(
                wallets_mod.xpub_cache, "load_xpub_verlauf_cache",
                side_effect=AssertionError("Verlauf noch einmal"),
            ):
                stand = wallets_mod.zusammenfassung_aus_gelesenem(
                    eintrag,
                    wurzel,
                    cache_eintrag=utxo_gemerkt[_XPUB],
                    verlauf=verlauf_gemerkt[_XPUB],
                )
        self.assertEqual(stand.utxo_count, 1)
        self.assertEqual(stand.total_sats, 5000)
        self.assertTrue(stand.has_cache)
        self.assertEqual(stand.scan_tip_height, 200)


if __name__ == "__main__":
    unittest.main()
