"""Einheitliches Wallet-Etikett in HTML-/CSV-Berichten."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core import herkunft_bericht as hb
from core import selbstanzeige as sa
from core import tax
from core import trace_cache
from tests.fixtures import BIP84_RECEIVE_0, txid
from tests.test_selbstanzeige import FakeWallet, _spent
from tests.test_tax import auswerten_zum_jahresende, utxo

WEB = Path(__file__).resolve().parent.parent / "web"


class TestBerichtWalletLesen(unittest.TestCase):

    def test_vorgabe_ist_alias_nicht_echte_namen(self):
        cfg = tax.lese_bericht_wallet({})
        self.assertFalse(cfg["echte"])
        self.assertEqual(cfg["alias"], "Eigenverwahrung")
        self.assertEqual(tax.bericht_wallet_ersatz({}), "Eigenverwahrung")

    def test_echte_namen_wenn_flag_an(self):
        cfg = tax.lese_bericht_wallet({"STEUER_BERICHT_WALLET_ECHT": "1"})
        self.assertTrue(cfg["echte"])
        self.assertIsNone(tax.bericht_wallet_ersatz(
            {"STEUER_BERICHT_WALLET_ECHT": "1"},
        ))

    def test_leerer_alias_faellt_auf_standard(self):
        cfg = tax.lese_bericht_wallet({
            "STEUER_BERICHT_WALLET_ECHT": "0",
            "STEUER_BERICHT_WALLET_ALIAS": "  ",
        })
        self.assertEqual(cfg["alias"], "Eigenverwahrung")

    def test_alias_wird_uebernommen(self):
        cfg = tax.lese_bericht_wallet({
            "STEUER_BERICHT_WALLET_ALIAS": "Self-Custody",
        })
        self.assertEqual(cfg["alias"], "Self-Custody")
        self.assertEqual(
            tax.bericht_wallet_ersatz({"STEUER_BERICHT_WALLET_ALIAS": "Self-Custody"}),
            "Self-Custody",
        )

    def test_wallet_fuer_bericht(self):
        self.assertEqual(tax.wallet_fuer_bericht("Cold", None), "Cold")
        self.assertEqual(tax.wallet_fuer_bericht("Cold", "Eigenverwahrung"),
                         "Eigenverwahrung")

    def test_hinweise_ersetzen_walletnamen(self):
        texte = tax.hinweise_fuer_bericht(
            ['Für „Cold Storage“, „Ledger Alt“ fehlt die Wallet-Historie.'],
            ["Cold Storage", "Ledger Alt"],
            "Eigenverwahrung",
        )
        self.assertEqual(len(texte), 1)
        self.assertNotIn("Cold Storage", texte[0])
        self.assertNotIn("Ledger Alt", texte[0])
        self.assertIn("Eigenverwahrung", texte[0])
        self.assertNotIn("„Eigenverwahrung“, „Eigenverwahrung“", texte[0])

    def test_wallets_liste_wird_zusammengezogen(self):
        self.assertEqual(
            tax.wallets_fuer_bericht(["A", "B"], None), ["A", "B"],
        )
        self.assertEqual(
            tax.wallets_fuer_bericht(["A", "B"], "Eigenverwahrung"),
            ["Eigenverwahrung"],
        )
        self.assertEqual(tax.wallets_fuer_bericht([], "Eigenverwahrung"), [])


class TestSteuerExportEtikett(unittest.TestCase):

    def setUp(self):
        self.auswertung = auswerten_zum_jahresende(
            [utxo(1000, "01.01.2024 12:00")], 2026,
        )
        self.auswertung["eintraege"][0]["wallet"] = "Cold Storage"

    def test_ohne_ersatz_bleibt_der_name(self):
        csv_text = tax.als_csv(self.auswertung).decode("utf-8-sig")
        html = tax.als_bericht(self.auswertung).decode("utf-8")
        self.assertIn("Cold Storage", csv_text)
        self.assertIn("Cold Storage", html)

    def test_mit_ersatz_verschwindet_der_name(self):
        csv_text = tax.als_csv(
            self.auswertung, wallet_ersatz="Eigenverwahrung",
        ).decode("utf-8-sig")
        html = tax.als_bericht(
            self.auswertung, wallet_ersatz="Eigenverwahrung",
        ).decode("utf-8")
        self.assertNotIn("Cold Storage", csv_text)
        self.assertNotIn("Cold Storage", html)
        self.assertIn("Eigenverwahrung", csv_text)
        self.assertIn("Eigenverwahrung", html)


class TestHopKetteEtikett(unittest.TestCase):

    def test_alias_macht_internen_wallet_wechsel_flach(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        cache = Path(tmp)
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
            "summary": {"external_count": 1, "node_count": 4},
            "verfolgt_vollstaendig": True,
        }
        trace_cache.speichern(t, 0, baum, cache)
        html = hb.hop_kette_html(
            t, 0, immutable_cache_dir=cache, wallet="A",
            wallet_ersatz="Eigenverwahrung",
        )
        self.assertIn("Eigenverwahrung", html)
        self.assertNotIn(" · A · ", html)
        self.assertNotIn(" · B · ", html)
        self.assertNotIn("hop-wallet-uebergang", html)
        self.assertIn("hop-external", html)
        self.assertIn("der Eigenverwahrung", html)


class TestSelbstanzeigeEtikett(unittest.TestCase):

    def test_html_und_csv_ersetzen_walletnamen(self):
        from datetime import datetime

        t0 = int(datetime(2023, 1, 1).timestamp())
        t1 = int(datetime(2025, 1, 2).timestamp())
        spend = "aa" * 32
        utxos = [_spent("55" * 32, 0, 10_000, t0, spend, t1, "bc1qa1")]
        report = sa.auswerten(
            utxos, 2025, [spend], haltefrist_jahre=1, wallet=FakeWallet(),
        )
        html = sa.als_html(report, wallet_ersatz="Eigenverwahrung").decode("utf-8")
        csv_text = sa.als_csv(report, wallet_ersatz="Eigenverwahrung").decode("utf-8")
        self.assertNotIn("Wallet A", html)
        self.assertNotIn("Wallet A", csv_text)
        self.assertIn("Eigenverwahrung", html)
        self.assertIn("Eigenverwahrung", csv_text)


class TestEinstellungenKarte(unittest.TestCase):

    def test_karte_liegt_in_der_html(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="bericht-wallet-echt"', html)
        self.assertIn('id="bericht-wallet-alias"', html)
        self.assertIn('id="bericht-wallet-uebernehmen"', html)
        self.assertIn("Echte Walletnamen in externen Berichten verwenden", html)
        js = (WEB / "views" / "einstellungen.js").read_text(encoding="utf-8")
        self.assertIn("/config/bericht-wallet", js)
        self.assertIn("setzeBerichtWalletAliasAktiv", js)


if __name__ == "__main__":
    unittest.main()
