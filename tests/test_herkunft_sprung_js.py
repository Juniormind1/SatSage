"""Sprung aus dem Herkunftsnetz in einen noch seitenweisen Baum: nur der Pfad."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
STUB = (WURZEL / "tests" / "herkunftsnetz_dom_stub.js").read_text(encoding="utf-8")
PAGER = (WURZEL / "web" / "views" / "pager.js").read_text(encoding="utf-8")
HERKUNFT = (WURZEL / "web" / "views" / "herkunft.js").read_text(encoding="utf-8")

PREAMBLE = r"""
document.createDocumentFragment = () => new El("#fragment");
document.createTextNode = (text) => { const el = new El("#text"); el.textContent = text; return el; };
document.querySelectorAll = () => [];
El.prototype.scrollIntoView = function () {};
const _anhaengen = El.prototype.append;
El.prototype.append = function (...kinder) {
  const flach = [];
  for (const k of kinder) {
    if (k && k.tagName === "#FRAGMENT") flach.push(...k.children); else flach.push(k);
  }
  return _anhaengen.apply(this, flach);
};
globalThis.setTimeout = () => 0;
globalThis.window = { addEventListener() {}, confirm() { return false; } };
globalThis.localStorage = { _d: {}, getItem(k) { return this._d[k] ?? null; }, setItem(k, v) { this._d[k] = String(v); } };
function t(key) { return key; }
function setzeText(el, text) { if (el) el.textContent = text; }
function labelMarke() { return null; }
function softTxClassLabel() { return null; }
function kuerze(s) { return s; }
function macheKopierbar() { return null; }
function knotenNotiz() { return null; }
function mempoolVerweis() { return null; }
const $ = (sel) => document.querySelector(sel);
const Zustand = { config: {}, steuer: {} };
"""

SZENARIO = r"""
const aufrufe = [];
const k = (c) => c.repeat(64);
const blatt = (id) => ({ type: "external", from_utxo: `${k(id)}:0`, txid: k(id), vout: 0,
  value_sats: 1, expandable: false });
const knoten = (id, kinder) => ({ type: "internal", from_utxo: `${k(id)}:0`, txid: k(id), vout: 0,
  value_sats: 1, wallet: "Cold", expandable: true, children: kinder });
const nummeriere = (n, id) => { n.id = id; (n.children || []).forEach((c, i) => nummeriere(c, `${id}.${i}`)); };
const voll = { found: true, root: { utxo: `${k("f")}:0` }, children: [
  knoten("a", [blatt("c"), knoten("d", [blatt("e")])]),
  knoten("b", [knoten("g", [blatt("h")])]),
] };
voll.children.forEach((c, i) => nummeriere(c, String(i)));
async function api(url) {
  aufrufe.push(String(url).split("?")[0]);
  if (String(url).startsWith("/trace/pfad")) return { vorhanden: true, pfad: "0.1.0" };
  if (String(url).startsWith("/trace?")) return { vorhanden: true, ergebnis: voll };
  return {};
}
const wurzel = new El("div"); wurzel.className = "utxo-wurzel"; wurzel.dataset.key = `${k("f")}:0`;
const zweig = new El("div"); zweig.className = "utxo-zweig"; zweig.dataset.baumZiel = `${k("f")}:0`;
const ebene = new El("div"); ebene.className = "baum-ebene";
zweig.append(ebene); wurzel.append(zweig);
(async () => {
  // Herkunftsnetz hat den Baum noch nicht vorgeladen (Klick vor dem Abruf).
  const ok = await springeImHerkunftsbaum(zweig, { key: `${k("e")}:0`, typ: "fremd" });
  const bloecke = zweig.querySelectorAll(".baum-knoten-block");
  const offen = bloecke.filter((b) => {
    const { kinder } = baumKnotenEls(b);
    return kinder && !kinder.hidden && kinder.dataset.gezeichnet;
  }).map((b) => b.dataset.pfad);
  const markiert = zweig.querySelectorAll(".herkunft-sprung")
    .map((el) => (BAUM_KNOTEN_DATEN.get(el) || {}).from_utxo);
  console.log(JSON.stringify({ ok, aufrufe, offen, markiert }));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def _node() -> dict:
    aus = subprocess.run(
        ["node"],
        input=STUB + PREAMBLE + PAGER + "\n" + HERKUNFT + "\n" + SZENARIO,
        capture_output=True, text=True, timeout=30,
    )
    if aus.returncode != 0:
        raise AssertionError(aus.stderr or aus.stdout)
    return json.loads(aus.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestSprungOhneVorladen(unittest.TestCase):

    def test_nur_der_pfad_wird_aufgeklappt(self):
        """
        Lazy (ISSUES P2): Der Sprung holt den gespeicherten Baum einmal und
        klappt nur den Pfad zum Ziel auf — nicht wie bis HEAD f40bd2f über
        „Alles aufklappen“ jeden Zweig (bei Monster-Bäumen das ganze DOM).
        """
        r = _node()
        self.assertTrue(r["ok"])
        self.assertEqual(r["aufrufe"], ["/trace/pfad", "/trace"])
        self.assertEqual(r["markiert"], ["e" * 64 + ":0"])
        self.assertEqual(r["offen"], ["0", "0.1"])


if __name__ == "__main__":
    unittest.main()
