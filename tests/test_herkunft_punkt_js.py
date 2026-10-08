"""Herkunft-Baum: Fristfarbe an Enden, Lücke als rotes Fragezeichen."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WEB = WURZEL / "web"


class TestHerkunftPunkt(unittest.TestCase):

    def test_ende_nutzt_fristklasse_intern_fragezeichen(self):
        herkunft = (WEB / "views" / "herkunft.js").read_text(encoding="utf-8")
        self.assertIn("function macheKnotenPunkt", herkunft)
        self.assertIn("function teilbaumHerkunftStand", herkunft)
        self.assertIn("knoten-frist-ok", herkunft)
        self.assertIn("knoten-frist-offen", herkunft)
        self.assertIn("knoten-luecke", herkunft)
        self.assertIn('punkt.textContent = "?"', herkunft)
        self.assertIn('knoten.type === "coinbase"', herkunft)

    def test_legende_zeigt_frist_und_luecke(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        start = html.index('id="trace-liste-zusatz"')
        ausschnitt = html[start:start + 1200]
        self.assertIn("trace.legendHeld", ausschnitt)
        self.assertIn("trace.legendUnheld", ausschnitt)
        self.assertIn("trace.legendIncomplete", ausschnitt)
        self.assertIn("trace.legendOpen", ausschnitt)
        self.assertNotIn("trace.legendOwn", ausschnitt)
        self.assertIn("punkt-frist-erfuellt", ausschnitt)
        self.assertIn("punkt-luecke", ausschnitt)

    def test_locale_schluessel(self):
        for code in ("de", "en"):
            katalog = json.loads((WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))
            for key in (
                "trace.legendHeld",
                "trace.legendUnheld",
                "trace.legendIncomplete",
                "trace.legendUndated",
            ):
                self.assertTrue(katalog.get(key), f"{code}: {key}")


if __name__ == "__main__":
    unittest.main()
