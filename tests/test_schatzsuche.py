"""Schatzsuche: Fenster, Zuordnung, Cache-Merge — ohne Node."""
import tempfile
import unittest
from pathlib import Path

import main
from core.bitcoind_rpc import descriptors_for_key
from core.schatzsuche import (
    SCHATZ_WEITE,
    merge_utxos,
    sammle_schaetze,
    schatz_hinweis,
    schreibe_schaetze_in_cache,
    suchfenster,
)
from core.xpub_cache import load_xpub_cache_entry, save_xpub_utxo_cache
from tests.fixtures import BIP84_ZPUB


def _utxo(txid, adresse, sats=50_000, vout=0):
    return {
        "txid": txid,
        "vout": vout,
        "value": sats,
        "address": adresse,
        "status": {"confirmed": True, "block_height": 800_000},
    }


class TestSchatzfenster(unittest.TestCase):

    def test_beginnt_hinter_dem_normalen_fenster(self):
        start, ende = suchfenster(500)
        self.assertEqual(start, 500)
        self.assertEqual(ende, 500 + SCHATZ_WEITE)

    def test_cache_weiter_als_cap_gilt(self):
        start, ende = suchfenster(500, cache_scan_end=800)
        self.assertEqual(start, 800)
        self.assertEqual(ende, 800 + SCHATZ_WEITE)

    def test_range_start_sitzt_im_deskriptor(self):
        objs = descriptors_for_key(
            BIP84_ZPUB, max_index=700, range_start=500, script_type="segwit",
        )
        self.assertTrue(objs)
        self.assertTrue(all(o["range"] == [500, 700] for o in objs))

    def test_hinweis_nennt_die_luecke(self):
        text = schatz_hinweis(
            wallet="Cold", chain=0, index=812, fenster_bis=500, sats=12000,
        )
        self.assertIn("Empfang #812", text)
        self.assertIn("bis Index #499", text)
        self.assertIn("außerhalb des Suchfensters", text)


class TestSammelnUndCache(unittest.TestCase):

    def test_nur_neue_outpoints_im_fenster(self):
        adresse = "bc1qschatz"
        vorhanden = [_utxo("aa" * 32, adresse, vout=0)]
        roh = [
            vorhanden[0],
            _utxo("bb" * 32, adresse, sats=90_000, vout=1),
            _utxo("cc" * 32, "bc1qfremd"),
        ]
        funde = sammle_schaetze(
            roh,
            zuordnung={
                adresse: {
                    "xpub": "zpub",
                    "wallet": "Cold",
                    "chain": 1,
                    "index": 900,
                    "fenster_bis": 500,
                },
            },
            vorhanden_je_xpub={"zpub": vorhanden},
        )
        self.assertEqual(len(funde), 1)
        self.assertEqual(funde[0]["txid"], "bb" * 32)
        self.assertIn("Wechselgeld #900", funde[0]["hinweis"])

    def test_merge_behaelt_den_bestand(self):
        alt = [_utxo("aa" * 32, "bc1qalt")]
        neu = [_utxo("bb" * 32, "bc1qneu")]
        gemischt = merge_utxos(alt, neu + alt)
        self.assertEqual(
            [u["txid"] for u in gemischt],
            ["aa" * 32, "bb" * 32],
        )

    def test_cache_behaelt_alte_utxos_und_scanende(self):
        main.set_chain_network("main")
        with tempfile.TemporaryDirectory() as tmp:
            wurzel = Path(tmp)
            alt = _utxo("aa" * 32, "bc1qalt", sats=1000)
            save_xpub_utxo_cache(
                BIP84_ZPUB, [alt], wurzel, "test",
                scan_end_index=40, max_addresses=80,
            )
            fund = {
                "xpub": BIP84_ZPUB,
                "address": "bc1qneu",
                "utxo": _utxo("bb" * 32, "bc1qneu", sats=80_000),
            }
            schreibe_schaetze_in_cache(
                [fund],
                cache_dir=wurzel,
                vorhanden_je_xpub={BIP84_ZPUB: [alt]},
                scan_end_je_xpub={BIP84_ZPUB: 40},
                max_addresses_je_xpub={BIP84_ZPUB: 80},
            )
            eintrag = load_xpub_cache_entry(BIP84_ZPUB, wurzel)
            txids = {u["txid"] for u in eintrag["utxos"]}
            self.assertEqual(txids, {"aa" * 32, "bb" * 32})
            self.assertEqual(eintrag["scan_end_index"], 40)
            self.assertIn("bc1qneu", eintrag["raw"].get("scanned_addresses", []))
