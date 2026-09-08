"""
Anzeigeformate.

Die Web-Oberfläche formatiert Beträge in JavaScript nach, weil sie sonst für
jede Zahl den Server fragen müsste. Damit CLI und Oberfläche nicht
auseinanderlaufen, hält dieser Test die Regeln fest — inklusive der Schwelle,
die in web/app.js noch einmal steht.
"""
import re
import unittest
from pathlib import Path

import display
from core.utxos import _zeit_ohne_block

APP_JS = Path(__file__).resolve().parent.parent / "web" / "app.js"


class TestBetragsSchwelle(unittest.TestCase):

    def test_schwelle_ist_ein_hundertstel_btc(self):
        self.assertEqual(display.SATS_BTC_MIN_DISPLAY, 1_000_000)

    def test_javascript_kennt_dieselbe_schwelle(self):
        """
        Ändert jemand die Schwelle in display.py, muss web/app.js nachgezogen
        werden — sonst zeigt die Oberfläche andere Beträge als das CLI.
        """
        quelle = APP_JS.read_text(encoding="utf-8")
        treffer = re.search(r"SATS_BTC_MIN_DISPLAY\s*=\s*(\d+)", quelle)
        self.assertIsNotNone(treffer, "SATS_BTC_MIN_DISPLAY fehlt in web/app.js")
        self.assertEqual(
            int(treffer.group(1)),
            display.SATS_BTC_MIN_DISPLAY,
            "web/app.js und display.py verwenden verschiedene Schwellen",
        )

    def test_kleine_betraege_bleiben_sats(self):
        self.assertIn("sats", display.format_sats(61_200))
        self.assertIn("sats", display.format_sats(124_500))
        self.assertIn("sats", display.format_sats(999_999))

    def test_ab_der_schwelle_btc(self):
        self.assertIn("BTC", display.format_sats(1_000_000))
        self.assertEqual(display.format_sats(84_000_000), "0.84 BTC")

    def test_kein_betrag_wird_zu_null_gerundet(self):
        """
        Der Grund für die Schwelle: 124.500 sats als '0,00 BTC' anzuzeigen
        wäre schlicht falsch.
        """
        for sats in (1, 61_200, 124_500, 999_999):
            self.assertNotIn("0.00", display.format_sats(sats))


class TestZeitLabel(unittest.TestCase):

    def test_blockangabe_wird_abgetrennt(self):
        self.assertEqual(
            _zeit_ohne_block("Block 857,930 · 14.09.2024 09:46:40"),
            "14.09.2024 09:46:40",
        )

    def test_nur_blockhoehe_bleibt_stehen(self):
        self.assertEqual(_zeit_ohne_block("Block 857,930"), "Block 857,930")

    def test_reine_zeit_bleibt_unveraendert(self):
        self.assertEqual(
            _zeit_ohne_block("14.09.2024 09:46:40"), "14.09.2024 09:46:40"
        )

    def test_unbekannt_bleibt_unveraendert(self):
        self.assertEqual(_zeit_ohne_block("unbekannt"), "unbekannt")

    def test_unbestaetigt_behaelt_den_zusatz(self):
        self.assertEqual(
            _zeit_ohne_block("Block 857,930 · 14.09.2024 09:46:40 (noch unbestätigt)"),
            "14.09.2024 09:46:40 (noch unbestätigt)",
        )


if __name__ == "__main__":
    unittest.main()
