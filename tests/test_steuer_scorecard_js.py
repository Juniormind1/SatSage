"""Scorecards im Steuerjahr folgen neuen grauen Scan-Punkten ohne kompletten Reload."""
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
function formatSats(sats) { return `${sats} sat`; }
function formatSatsGemeinsam(sats) { return `${sats} sat HIST`; }
function formatSatsBasis(sats) { return `${sats} sat`; }
function formatZeitstrahlBetrag(sats) { return `${sats} sat`; }
function t(key) { return key; }
const $ = (sel) => document.querySelector(sel);
const umschalt = [];
function herkunftsnetzUmschalten(key) { umschalt.push(key); }
function herkunftsnetzBericht() {}
const Zustand = {
  ansicht: "steuerjahr",
  herkunftAlleLaeuft: false,
  config: { steuer: {} },
  steuer: {
    seitenweise: false,
    eintraege: [],
    grau_keys: [],
    kennzahlen: {
      gesamt_count: 2,
      gesamt_sats: 3000,
      erfuellt_count: 1,
      erfuellt_sats: 1000,
      offen_count: 1,
      offen_sats: 2000,
      ungeprueft_count: 0,
      ungeprueft_sats: 0,
      naechste_frist: "",
      ohne_datum: 0,
    },
  },
};
const kasten = mitId("steuer-kennzahlen", new El("div"));
const spur = mitId("achse-spur", new El("div"));
"""

SZENARIO = r"""
ZeitstrahlAnsicht.daten = {
  zeitstrahl: { von: "01.01.2020", bis: "31.12.2026", max_sats: 100000 },
};
ZeitstrahlAnsicht.x0 = 0;
ZeitstrahlAnsicht.x1 = 100;
ZeitstrahlAnsicht.y0 = 0;
ZeitstrahlAnsicht.y1 = 100;
function finde(el, pred, aus = []) {
  if (pred(el)) aus.push(el);
  for (const kind of el.children || []) finde(kind, pred, aus);
  return aus;
}
function knopf(id) {
  return finde(kasten, (el) => el.id === id)[0] || null;
}
zeichneSteuerScorecards(Zustand.steuer);
const gruenVorher = kasten.querySelector('[data-score="erfuellt"]');
const gelbKnopfVorher = knopf("herkunft-gelb");
gruenVorher._mark = "bleibt";
const keyA = "a".repeat(64) + ":0";
const keyB = "b".repeat(64) + ":0";
const tsA = Date.UTC(2024, 5, 15, 12, 0, 0) / 1000;
const tsB = Date.UTC(2024, 6, 1, 12, 0, 0) / 1000;
const punkt = (key, ts, sats) => ({
  key, time_ts: ts, value_sats: sats, wallet: "Cold", wallet_id: "w1",
});
zeichneScanPunkte([punkt(keyA, tsA, 500)]);
const nachErstem = {
  ids: [...kasten.children].map((el) => el.dataset.score),
  gruenNeu: kasten.querySelector('[data-score="erfuellt"]') !== gruenVorher,
  gelbKnopfNeu: knopf("herkunft-gelb") !== gelbKnopfVorher,
  grau: kasten.querySelector('[data-score="ungeprueft"]')
    ? kasten.querySelector('[data-score="ungeprueft"]').textContent
    : "",
  gesamt: kasten.querySelector('[data-score="gesamt"] .kennzahl-zahl').textContent,
  offen: kasten.querySelector('[data-score="offen"] .kennzahl-zahl').textContent,
  punkte: spur.querySelectorAll(".achse-punkt").length,
  // Kopie: zeichneScanPunkte ergänzt grau_keys an Ort und Stelle, ohne
  // Kopie stünde hier beim Ausgeben schon der Stand nach dem zweiten Punkt.
  keys: [...Zustand.steuer.grau_keys],
};
const gruenNachher = kasten.querySelector('[data-score="erfuellt"]');
const grauKarte = kasten.querySelector('[data-score="ungeprueft"]');
const grauKnopf = knopf("herkunft-grau");
gruenNachher._mark = "steht";
zeichneScanPunkte([punkt(keyA, tsA, 500), punkt(keyB, tsB, 700)]);
spur.replaceChildren();
zeichneScanPunkte([punkt(keyA, tsA, 500), punkt(keyB, tsB, 700)]);
const k = Zustand.steuer.kennzahlen;
console.log(JSON.stringify({
  nachErstem,
  zweiter: {
    gruenSteht: kasten.querySelector('[data-score="erfuellt"]') === gruenNachher
      && gruenNachher._mark === "steht",
    grauSteht: kasten.querySelector('[data-score="ungeprueft"]') === grauKarte,
    knopfSteht: knopf("herkunft-grau") === grauKnopf,
    grauText: grauKarte.textContent,
    gesamt: kasten.querySelector('[data-score="gesamt"] .kennzahl-zahl').textContent,
    offen: kasten.querySelector('[data-score="offen"] .kennzahl-zahl').textContent,
    gesamtCount: k.gesamt_count,
    gesamtSats: k.gesamt_sats,
    grauCount: k.ungeprueft_count,
    grauSats: k.ungeprueft_sats,
    keys: Zustand.steuer.grau_keys,
    punkte: spur.querySelectorAll(".achse-punkt").length,
  },
}));
"""


KLICK_SZENARIO = r"""
(async () => {
  ZeitstrahlAnsicht.daten = {
    zeitstrahl: { von: "01.01.2020", bis: "31.12.2026", max_sats: 100000 },
  };
  ZeitstrahlAnsicht.x0 = 0;
  ZeitstrahlAnsicht.x1 = 100;
  ZeitstrahlAnsicht.y0 = 0;
  ZeitstrahlAnsicht.y1 = 100;
  const keyA = "a".repeat(64) + ":0";
  const tsA = Date.UTC(2024, 5, 15, 12, 0, 0) / 1000;
  zeichneScanPunkte([{
    key: keyA, time_ts: tsA, value_sats: 500, wallet: "Cold", wallet_id: "w1",
  }]);
  const p = spur.querySelector(".achse-punkt");
  p.fire("click", { detail: 1 });
  await new Promise((r) => setTimeout(r, 320));
  console.log(JSON.stringify({
    klickbar: p.classList.contains("klickbar"),
    ungeprueft: p.classList.contains("ungeprueft"),
    umschalt,
  }));
})();
"""


def _node(szenario: str = SZENARIO) -> dict:
    aus = subprocess.run(
        ["node"],
        input=STUB + PREAMBLE + STEUER + "\n" + szenario,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if aus.returncode != 0:
        raise AssertionError(aus.stderr or aus.stdout)
    return json.loads(aus.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestScanScorecards(unittest.TestCase):

    def test_erste_graue_karte_baut_alle_neu_weitere_nur_zahlen(self):
        r = _node()
        erster = r["nachErstem"]
        self.assertEqual(
            erster["ids"],
            ["gesamt", "erfuellt", "offen", "ungeprueft"],
        )
        self.assertTrue(erster["gruenNeu"])
        self.assertTrue(erster["gelbKnopfNeu"])
        self.assertIn("1 UTXOs", erster["grau"])
        self.assertIn("500 sat", erster["grau"])
        self.assertEqual(erster["gesamt"], "3500 sat")
        self.assertEqual(erster["offen"], "2000 sat")
        self.assertEqual(erster["punkte"], 1)
        self.assertEqual(erster["keys"], ["a" * 64 + ":0"])

        zweiter = r["zweiter"]
        self.assertTrue(zweiter["gruenSteht"])
        self.assertTrue(zweiter["grauSteht"])
        self.assertTrue(zweiter["knopfSteht"])
        self.assertIn("2 UTXOs", zweiter["grauText"])
        self.assertIn("1200 sat", zweiter["grauText"])
        self.assertEqual(zweiter["gesamt"], "4200 sat")
        self.assertEqual(zweiter["offen"], "2000 sat")
        self.assertEqual(zweiter["gesamtCount"], 4)
        self.assertEqual(zweiter["gesamtSats"], 4200)
        self.assertEqual(zweiter["grauCount"], 2)
        self.assertEqual(zweiter["grauSats"], 1200)
        self.assertEqual(zweiter["keys"], ["a" * 64 + ":0", "b" * 64 + ":0"])
        self.assertEqual(zweiter["punkte"], 2)

    def test_grauer_scan_punkt_klick_oeffnet_herkunft(self):
        r = _node(KLICK_SZENARIO)
        self.assertTrue(r["klickbar"])
        self.assertTrue(r["ungeprueft"])
        self.assertEqual(r["umschalt"], ["a" * 64 + ":0"])

    def test_scorecard_betrag_ist_spot_nicht_einstand(self):
        r = _node(r"""
function formatSats(sats) { return `${sats} sat (≈ 9 €)`; }
zeichneSteuerScorecards(Zustand.steuer);
console.log(JSON.stringify({
  gesamt: kasten.querySelector('[data-score="gesamt"] .kennzahl-zahl').textContent,
  erfuellt: kasten.querySelector('[data-score="erfuellt"] .kennzahl-zahl').textContent,
  offen: kasten.querySelector('[data-score="offen"] .kennzahl-zahl').textContent,
}));
""")
        self.assertEqual(r["gesamt"], "3000 sat (≈ 9 €)")
        self.assertEqual(r["erfuellt"], "1000 sat (≈ 9 €)")
        self.assertEqual(r["offen"], "2000 sat (≈ 9 €)")
        self.assertNotIn("HIST", r["gesamt"])


if __name__ == "__main__":
    unittest.main()
