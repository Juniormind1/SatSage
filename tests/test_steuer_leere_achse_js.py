"""Leerer Steuerjahr-Plot: Achse bleibt sichtbar, Y von 1 000 bis 1 000 000 sats."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
STUB = (WURZEL / "tests" / "herkunftsnetz_dom_stub.js").read_text(encoding="utf-8")
STEUER = (WURZEL / "web" / "views" / "steuerjahr.js").read_text(encoding="utf-8")

PREAMBLE = r"""
function formatZeitstrahlBetrag(sats) { return String(sats); }
function t(key) { return key; }
function setzeText(el, text) { if (el) el.textContent = text; }
const $ = (sel) => document.querySelector(sel);
const Zustand = { ansicht: "steuerjahr", config: { steuer: {} }, steuer: null };
const karte = mitId("zeitstrahl-karte", new El("div"));
karte.hidden = true;
mitId("achse-y", new El("div"));
mitId("achse-viewport", new El("div"));
const spur = mitId("achse-spur", new El("div"));
const ticks = mitId("achse-ticks", new El("div"));
ticks.getBoundingClientRect = () => ({ width: 800, height: 16, top: 0, left: 0, bottom: 16, right: 800 });
mitId("zeitstrahl-zusatz", new El("span"));
const localStorage = { getItem() { return null; }, setItem() {} };
"""

SZENARIO = r"""
function yTexte() {
  return [...document.querySelector("#achse-y").querySelectorAll(".achse-y-tick")]
    .map((el) => el.textContent);
}
zeichneZeitstrahl({
  zeitstrahl: {
    vorhanden: true,
    leer: true,
    von: "02.10.2024",
    bis: "02.10.2026",
    frist_pos: 50,
    frist_datum: "02.10.2025",
    events: [],
    max_sats: 1000000,
    y_min_sats: 1000,
    geister_saldo: null,
  },
});
const leer = {
  hidden: karte.hidden,
  y0: ZeitstrahlAnsicht.y0,
  y1: ZeitstrahlAnsicht.y1,
  unten: zeitstrahlYSatsAn(1000000, ZeitstrahlAnsicht.y0),
  oben: zeitstrahlYSatsAn(1000000, ZeitstrahlAnsicht.y1),
  yTexte: yTexte(),
  punkte: spur.querySelectorAll(".achse-punkt").length,
  xTicks: ticks.textContent,
};
zeichneZeitstrahl({
  zeitstrahl: { vorhanden: false, events: [] },
});
console.log(JSON.stringify({ leer, weg: karte.hidden }));
"""


def _node() -> dict:
    aus = subprocess.run(
        ["node"],
        input=STUB + PREAMBLE + STEUER + "\n" + SZENARIO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if aus.returncode != 0:
        raise AssertionError(aus.stderr or aus.stdout)
    return json.loads(aus.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestLeereAchseJs(unittest.TestCase):

    def test_leerer_rahmen_zeigt_tausend_bis_eine_million(self):
        r = _node()["leer"]
        self.assertFalse(r["hidden"])
        self.assertAlmostEqual(r["unten"], 1000, delta=5)
        self.assertEqual(r["oben"], 1_000_000)
        self.assertGreater(r["y0"], 49)
        self.assertLess(r["y0"], 51)
        self.assertEqual(r["y1"], 100)
        self.assertIn("1000", r["yTexte"])
        self.assertIn("1000000", r["yTexte"])
        self.assertNotIn("0", r["yTexte"])
        self.assertEqual(r["punkte"], 0)
        self.assertIn("2024", r["xTicks"])
        self.assertIn("2026", r["xTicks"])

    def test_ohne_rahmen_bleibt_die_karte_verborgen(self):
        self.assertTrue(_node()["weg"])
