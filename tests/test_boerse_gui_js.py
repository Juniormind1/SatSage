"""GUI-Vorschau für Börsen-CSV: Zähler, kein Import ohne Vorschau."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WEB = WURZEL / "web"


class BoerseGuiTest(unittest.TestCase):
    def test_vorschau_elemente(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="boerse-vorschau"', html)
        self.assertIn('id="boerse-csv-trades"', html)
        js = (WEB / "views" / "datenquellen.js").read_text(encoding="utf-8")
        self.assertIn("function zeigeBoersenVorschau", js)
        self.assertIn('"/exchange-reports/vorschau"', js)
        self.assertIn("csv_trades", js)
        self.assertIn("function importiereBoersenCsv", js)
        # Kein direkter Import mehr ohne Vorschau: der Datei-Handler zeigt zuerst die Vorschau.
        self.assertIn("zeigeBoersenVorschau()", js)

    def test_locale_schluessel(self):
        keys = (
            "sources.exchangePreview",
            "sources.exchangeImportNow",
            "sources.exchangeCounts",
            "sources.exchangeRecognized",
            "sources.exchangeImportedV2",
            "sources.exchangeLineV2",
            "sources.exchangeAddTrades",
            "sources.exchangeRemoveV1",
        )
        for code in ("de", "en"):
            katalog = json.loads((WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))
            for key in keys:
                self.assertTrue(katalog.get(key), f"{code}: {key}")


if __name__ == "__main__":
    unittest.main()
