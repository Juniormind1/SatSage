"""
Cache-Reader für den Assistenten: nur lokale Bestände, keine Jobs.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import main
from core import llm_context as ctx
from tests.fixtures import BIP84_RECEIVE_0, BIP84_ZPUB, ZWEITER_ALS_XPUB, txid
from tests.test_steuer_grundlage import utxo


class TestLueckenUndWallets(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wurzel = Path(tmp.name)
        self.cache = wurzel / "utxo_cache"
        self.cache.mkdir()
        self.immutable = wurzel / "immutable_cache"
        self.immutable.mkdir()
        from core.config import read_wallets, EnvFile
        env = wurzel / ".env"
        env.write_text(
            f"XPUBS={BIP84_ZPUB} {ZWEITER_ALS_XPUB}\n"
            "WALLET_NAMES=Alpha|Beta\n"
            "MAX_ADDRESSES_PER_XPUB=4|4\n",
            encoding="utf-8",
        )
        self.entries = read_wallets(EnvFile.load(env))

    def test_ohne_cache_nennt_scan_knopf(self):
        stand = ctx.luecken(
            entries=self.entries,
            cache_dir=self.cache,
            immutable_dir=self.immutable,
        )
        self.assertEqual(stand["ohne_cache"], ["Alpha", "Beta"])
        self.assertIn(ctx.KNOPF_SCAN, stand["knoepfe"])
        self.assertIn("Kaffee", stand["text"])
        self.assertNotIn(BIP84_ZPUB, stand["text"])

    def test_bestand_ohne_verlauf_und_herkunft(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo("a1", 150_000)], self.cache, "test",
        )
        stand = ctx.luecken(
            entries=self.entries,
            cache_dir=self.cache,
            immutable_dir=self.immutable,
        )
        self.assertIn("Alpha", stand["ohne_verlauf"])
        self.assertEqual(stand["ohne_herkunft"], 1)
        self.assertIn(ctx.KNOPF_VERLAUF, stand["knoepfe"])
        self.assertIn(ctx.KNOPF_HERKUNFT, stand["knoepfe"])

    def test_wallets_nur_namen(self):
        main.save_xpub_utxo_cache(
            BIP84_ZPUB, [utxo("a1", 80_000)], self.cache, "test",
        )
        stand = ctx.wallets(
            entries=self.entries,
            cache_dir=self.cache,
            immutable_dir=self.immutable,
        )
        dump = json.dumps(stand, ensure_ascii=False)
        self.assertIn("Alpha", dump)
        self.assertNotIn(BIP84_ZPUB, dump)
        self.assertNotIn(BIP84_RECEIVE_0, dump)
        self.assertIn("kein Cache", stand["text"])


class TestSteuerKompakt(unittest.TestCase):

    def test_keine_adresslisten(self):
        auswertung = {
            "jahr": 2023,
            "stichtag_label": "Stichtag 31.12.2023",
            "haltefrist_jahre": 1,
            "stichtag_regel": "",
            "kennzahlen": {
                "gesamt_count": 1,
                "gesamt_sats": 150_000,
                "erfuellt_sats": 0,
                "offen_sats": 150_000,
                "erfuellt_count": 0,
                "offen_count": 1,
                "abgang_count": 0,
                "ungeprueft_count": 1,
                "ungeprueft_sats": 150_000,
            },
            "hinweise": ["Hinweis"],
            "ohne_verlauf": ["Alpha"],
            "verfuegbare_jahre": [2023],
            "hat_verlauf": False,
            "eintraege": [{"address": BIP84_RECEIVE_0}],
        }
        kompakt = ctx.steuer_kompakt(auswertung)
        dump = json.dumps(kompakt, ensure_ascii=False)
        self.assertNotIn("eintraege", kompakt)
        self.assertNotIn(BIP84_RECEIVE_0, dump)
        self.assertIn("2023", kompakt["text"])
        self.assertIn("Keine Steuerberatung", kompakt["text"])

    def test_export_legende(self):
        text = ctx.export_legende({"jahr": 2024, "hinweise": ["A"]})["text"]
        self.assertIn("Legende Steuerjahr 2024", text)
        self.assertIn("CSV", text)

    def test_export_markdown_und_brief_ohne_adressen(self):
        auswertung = {
            "jahr": 2023,
            "stichtag_label": "Stichtag 31.12.2023",
            "haltefrist_jahre": 1,
            "kennzahlen": {
                "gesamt_sats": 150_000,
                "gesamt_count": 1,
                "erfuellt_sats": 0,
                "offen_sats": 150_000,
                "abgang_count": 0,
            },
            "hinweise": ["Keine Steuerberatung."],
            "hat_verlauf": False,
            "eintraege": [{"address": BIP84_RECEIVE_0}],
        }
        md = ctx.export_markdown(auswertung)
        brief = ctx.export_brief(auswertung)
        for paket in (md, brief):
            dump = json.dumps(paket, ensure_ascii=False)
            self.assertNotIn(BIP84_RECEIVE_0, dump)
            self.assertNotIn("eintraege", paket)
            self.assertIn("2023", paket["text"])
            self.assertIn("steuerberatung", paket["text"].lower())
        self.assertIn("# Steuerjahr", md["text"])
        self.assertIn("Steuerberater", brief["text"])
