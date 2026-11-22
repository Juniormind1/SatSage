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



    def test_zuordnung_und_erklaerung(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="boerse-zuordnung"', html)
        self.assertIn('id="zuordnung-auto"', html)
        js = (WEB / "views" / "datenquellen.js").read_text(encoding="utf-8")
        self.assertIn('"/exchange-reports/zuordnungen/vorschlagen"', js)
        self.assertIn("function setzeBoersenZuordnung", js)
        self.assertIn("function zeichneBoersenZuordnungText", js)
        self.assertIn("txid_kurz", js)
        self.assertIn("boerse-auto", js)
        fmt = (WEB / "format.js").read_text(encoding="utf-8")
        self.assertIn("function boerseErklaerungText", fmt)
        herkunft = (WEB / "views" / "herkunft.js").read_text(encoding="utf-8")
        self.assertIn("boerseErklaerungText", herkunft)
        self.assertIn("boerse-erklaerung", herkunft)
        # Keine Fristklasse an der Erklärung.
        idx = herkunft.index("boerseErklaerungText(utxo")
        ausschnitt = herkunft[idx:idx + 500]
        self.assertNotIn("knoten-frist", ausschnitt)
        steuer = (WEB / "views" / "steuerjahr.js").read_text(encoding="utf-8")
        self.assertIn("boerseErklaerungText(eintrag)", steuer)
        self.assertIn("boerse-erklaerung", steuer)

    def test_erklaerung_locale(self):
        for code in ("de", "en"):
            katalog = json.loads((WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))
            for key in ("sources.exchangeExplained", "sources.exchangeExplainedHint",
                        "sources.exchangeConfirm", "sources.exchangeAssignRefresh",
                        "sources.exchangeStatus.auto", "sources.exchangeMethod.adresse",
                        "settings.assign.auto"):
                self.assertTrue(katalog.get(key), f"{code}: {key}")


if __name__ == "__main__":
    unittest.main()
