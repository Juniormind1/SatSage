"""On-chain Hop-Kette im Steuer-HTML-Bericht."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import main
from core import herkunft_bericht as hb
from core import tax
from core import trace_cache
from tests.fixtures import BIP84_RECEIVE_0, txid


class TestHopKetteHtml(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name)

    def _speichere_mini_baum(self, marker: str = "a1"):
        t = txid(marker)
        baum = {
            "found": True,
            "error": "",
            "root": {
                "type": "utxo",
                "txid": t,
                "vout": 0,
                "address": BIP84_RECEIVE_0,
                "wallet": "Test",
                "amount_sats": 100_000,
            },
            "children": [
                {
                    "type": "internal",
                    "address": BIP84_RECEIVE_0,
                    "wallet": "Test",
                    "amount_sats": 100_000,
                    "from_utxo": f"{txid('b2')}:0",
                    "time_label": "01.01.2024 12:00:00",
                    "children": [
                        {
                            "type": "external",
                            "address": "bc1qextern",
                            "amount_sats": 100_000,
                            "from_utxo": f"{txid('e1')}:1",
                            "time_label": "01.06.2023 08:00:00",
                            "children": [],
                        }
                    ],
                }
            ],
            "summary": {
                "external_count": 1,
                "unresolved_inputs": 0,
                "max_depth": 2,
                "node_count": 3,
            },
            "verfolgt_vollstaendig": True,
        }
        trace_cache.speichern(t, 0, baum, self.cache)
        return t

    def test_hop_kette_enthaelt_intern_und_extern(self):
        t = self._speichere_mini_baum()
        html = hb.hop_kette_html(
            t, 0, immutable_cache_dir=self.cache, wallet="Test",
        )
        self.assertIn("Intern", html)
        self.assertIn("Extern", html)
        self.assertIn(txid("e1"), html)
        self.assertIn("hop-wurzel", html)

    def test_hop_kette_flach_im_selben_wallet(self):
        """Einrückung nur bei Wallet-Austritt, nicht pro internem Hop."""
        t = txid("f1")
        baum = {
            "found": True,
            "error": "",
            "root": {
                "type": "utxo",
                "txid": t,
                "vout": 0,
                "wallet": "A",
                "amount_sats": 50_000,
            },
            "children": [
                {
                    "type": "internal",
                    "wallet": "A",
                    "amount_sats": 50_000,
                    "from_utxo": f"{txid('a1')}:0",
                    "children": [
                        {
                            "type": "internal",
                            "wallet": "A",
                            "amount_sats": 50_000,
                            "from_utxo": f"{txid('a2')}:0",
                            "children": [
                                {
                                    "type": "internal",
                                    "wallet": "B",
                                    "amount_sats": 50_000,
                                    "from_utxo": f"{txid('b1')}:0",
                                    "children": [
                                        {
                                            "type": "external",
                                            "address": "bc1qextern",
                                            "amount_sats": 50_000,
                                            "from_utxo": f"{txid('e9')}:0",
                                            "children": [],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "summary": {"external_count": 1, "node_count": 5},
            "verfolgt_vollstaendig": True,
        }
        trace_cache.speichern(t, 0, baum, self.cache)
        html = hb.hop_kette_html(
            t, 0, immutable_cache_dir=self.cache, wallet="A",
        )
        self.assertIn("hop-kinder flach", html)
        self.assertIn("hop-austritt", html)
        self.assertIn("hop-wallet-uebergang", html)
        self.assertIn("hop-external", html)
        # Zweiter Hop im selben Wallet A: kein Austritt an der inneren A-Zeile
        # (nur B und Extern tragen hop-austritt).
        self.assertGreaterEqual(html.count("hop-austritt"), 2)
        self.assertIn(txid("b1"), html)

    def test_steuerbericht_haengt_hop_abschnitt_an(self):
        t = self._speichere_mini_baum("c3")
        aus = {
            "jahr": 2026,
            "stichtag": "31.12.2026",
            "haltefrist_jahre": 1,
            "stichtag_regel": "aus",
            "erstellt": "15.09.2026 12:00",
            "laufend": False,
            "kennzahlen": {
                "gesamt_sats": 100_000,
                "gesamt_count": 1,
                "erfuellt_sats": 100_000,
                "erfuellt_count": 1,
                "offen_sats": 0,
                "offen_count": 0,
            },
            "eintraege": [{
                "datum": "01.01.2024",
                "zeit": "12:00:00",
                "wallet": "Test",
                "address": BIP84_RECEIVE_0,
                "value_sats": 100_000,
                "haltedauer_tage": 700,
                "frist_ende": "01.01.2025",
                "erfuellt": True,
                "grundlage_label": "Herkunft verfolgt",
                "txid": t,
                "vout": 0,
                "herkunft": "",
            }],
            "hinweise": [],
            "abgaenge": [],
        }
        html = tax.als_bericht(
            aus, immutable_cache_dir=self.cache,
        ).decode("utf-8")
        self.assertIn("Herkunftsnachweis", html)
        self.assertIn("Extern", html)
        self.assertIn(t, html)


if __name__ == "__main__":
    unittest.main()
