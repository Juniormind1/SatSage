"""Scorecard „klären“ scannt nur Wallets ohne UTXO-Bestand, vor der Routine."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
STUB = (WURZEL / "tests" / "herkunftsnetz_dom_stub.js").read_text(encoding="utf-8")
HERKUNFT = (WURZEL / "web" / "views" / "herkunft.js").read_text(encoding="utf-8")

PREAMBLE = r"""
function t(key, vars) {
  let text = key;
  if (vars) {
    for (const [name, wert] of Object.entries(vars)) {
      text = text.split("{" + name + "}").join(String(wert));
    }
  }
  return text;
}
function setzeText(el, text) { if (el) el.textContent = text; }
function logZeile() {}
function nimmJobLogAb() {}
function übersetzeLogText(s) { return s || ""; }
function brauchtBip158Startdatum() { return false; }
function stoesseEmpfangScanPuls() {}
function loeseEmpfangScanPuls() {}
function merkeScanJobBeendet() {}
function ladeSteuerjahrMitKandidaten() {}
function chainTipHoehe() { return Zustand.config.header_tip; }
function steuerEinstellungen() { return { stichtag: "" }; }
let confirmN = 0;
globalThis.window = { confirm() { confirmN += 1; return false; } };
const $ = (sel) => document.querySelector(sel);
const Zustand = {
  herkunftAlleLaeuft: false,
  steuer: { gelb_keys: ["alt:0"], grau_keys: ["altg:0"], eintraege: [] },
  config: {
    context_bereit: true,
    header_tip: 200,
    wallets: [
      { id: "nie", name: "Nie", has_cache: false, utxo_count: 0, scan_tip_height: null },
      { id: "leer", name: "Leer", has_cache: true, utxo_count: 0, scan_tip_height: 200 },
      { id: "tip", name: "Tip", has_cache: true, utxo_count: 4, scan_tip_height: 100 },
      { id: "aktuell", name: "Aktuell", has_cache: true, utxo_count: 2, scan_tip_height: 200 },
      { id: "neu", name: "Entwurf", has_cache: false, utxo_count: 0, is_new: true },
      { id: "hinter", name: "Hinter", has_cache: false, utxo_count: 0, scan_tip_height: 100 },
    ],
  },
};
async function ladeConfig() {
  for (const wallet of Zustand.config.wallets) {
    if (wallet.id === "nie") wallet.has_cache = true;
  }
}
const aufrufe = [];
async function api(url, opt) {
  aufrufe.push({ url: String(url), daten: (opt && opt.daten) || null });
  if (url === "/jobs/rescan") return { id: "job-" + opt.daten.wallet_id };
  if (String(url).startsWith("/jobs/")) return { running: false, status: "done" };
  if (String(url).startsWith("/tax")) {
    return { gelb_keys: ["neu:0"], grau_keys: ["grauneu:0"], eintraege: [] };
  }
  if (url === "/trace/alle") return { nichts_zu_tun: true };
  return {};
}
mitId("herkunft-lauf", new El("div"));
mitId("herkunft-text", new El("div"));
mitId("herkunft-abbruch", new El("button"));
mitId("herkunft-gelb", new El("button"));
mitId("herkunft-grau", new El("button"));
mitId("steuer-meldung", new El("div"));
mitId("jahr-wahl", new El("select"));
mitId("frist-wahl", new El("select"));
"""

SZENARIO = r"""
const auswahl = walletsOhneUtxoScan(Zustand.config, 200).map((w) => w.id);
const knapp = walletsOhneUtxoScan({
  context_bereit: true,
  wallets: [{ id: "knapp", has_cache: false, utxo_count: 0, scan_tip_height: 198 }],
}, 200).map((w) => w.id);
const ohneKontext = walletsOhneUtxoScan({
  context_bereit: false,
  wallets: [{ id: "nie", has_cache: false, utxo_count: 0 }],
}, 200);
await herkunftGelbUtxos();
const nachGelb = aufrufe.map((a) => ({
  url: a.url.split("?")[0],
  wallet: a.daten && a.daten.wallet_id,
  keys: a.daten && a.daten.utxo_keys,
}));
aufrufe.length = 0;
Zustand.steuer = { gelb_keys: ["alt:0"], grau_keys: ["altg:0"], eintraege: [] };
await herkunftGrauUtxos();
const nachGrau = aufrufe.map((a) => ({
  url: a.url.split("?")[0],
  keys: a.daten && a.daten.utxo_keys,
}));
aufrufe.length = 0;
Zustand.config.wallets.find((w) => w.id === "nie").has_cache = false;
Zustand.herkunftAlleLaeuft = false;
const warten = warteAufJobEnde;
warteAufJobEnde = async () => {
  const err = new Error("abgebrochen");
  err.abgebrochen = true;
  throw err;
};
await herkunftGelbUtxos();
warteAufJobEnde = warten;
console.log(JSON.stringify({
  auswahl,
  knapp,
  ohneKontext: ohneKontext.map((w) => w.id),
  nachGelb,
  nachGrau,
  confirmN,
  abbruch: {
    laeuft: Zustand.herkunftAlleLaeuft,
    gelb: $("#herkunft-gelb").disabled,
    text: $("#steuer-meldung").textContent,
    trace: aufrufe.some((a) => a.url === "/trace/alle"),
  },
}));
"""


def _node() -> dict:
    aus = subprocess.run(
        ["node"],
        input=STUB + PREAMBLE + HERKUNFT + "\n" + SZENARIO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if aus.returncode != 0:
        raise AssertionError(aus.stderr or aus.stdout)
    return json.loads(aus.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestKlaerenVorabScan(unittest.TestCase):

    def test_nur_nie_gescannte_vor_der_routine(self):
        r = _node()
        self.assertEqual(r["auswahl"], ["nie"])
        self.assertEqual(r["knapp"], ["knapp"])
        self.assertEqual(r["ohneKontext"], [])
        self.assertEqual(
            [a["url"] for a in r["nachGelb"]],
            ["/jobs/rescan", "/jobs/job-nie", "/tax", "/trace/alle"],
        )
        self.assertEqual(r["nachGelb"][0]["wallet"], "nie")
        self.assertEqual(r["nachGelb"][3]["keys"], ["neu:0"])
        self.assertEqual(
            [a["url"] for a in r["nachGrau"]],
            ["/trace/alle"],
        )
        self.assertEqual(r["nachGrau"][0]["keys"], ["altg:0"])
        self.assertEqual(r["confirmN"], 0)
        self.assertFalse(r["abbruch"]["laeuft"])
        self.assertFalse(r["abbruch"]["gelb"])
        self.assertIn("allOriginsScanAbort", r["abbruch"]["text"])
        self.assertFalse(r["abbruch"]["trace"])


if __name__ == "__main__":
    unittest.main()
