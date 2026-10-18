"""Cache-Suchtreffer: Sat-Betrag plus Spot-Fiat der Kopfzeile."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_wallet_mempool_js import _funktion

WEB = Path(__file__).resolve().parent.parent / "web"
TOOLS = (WEB / "views" / "tools.js").read_text(encoding="utf-8")
FORMAT = (WEB / "format.js").read_text(encoding="utf-8")


def _format_fn(name: str) -> str:
    return _funktion(FORMAT, f"function {name}(")


BETRAG = _funktion(TOOLS, "function toolsCacheBetrag(")
ZEICHNE = _funktion(TOOLS, "function zeichneCacheListe(")
FORMAT_STUECKE = "\n".join([
    _format_fn("uiSprache"),
    _format_fn("fiatWaehrung"),
    _format_fn("fiatSymbol"),
    _format_fn("formatFiatBetrag"),
    _format_fn("formatEurAusSats"),
    _format_fn("formatSatsBasis"),
])

_STUB = r"""
const window = { SatSageI18n: { currentLang() { return SPRACHE; }, formatLocale() {
  return SPRACHE === "en" ? "en-US" : "de-DE";
} } };
let SPRACHE = "de";
const SATS_BTC_MIN_DISPLAY = 1000000;
const Zustand = { kurs: null, ansicht: "tools" };
function formatLocale() { return SPRACHE === "en" ? "en-US" : "de-DE"; }
function t(key, vars) {
  const katalog = {
    "tools.cacheItem": "{amount} · {wallet} · {wo} · {address}",
    "tools.cacheSpent": "ausgegeben",
    "tools.cacheOpen": "Bestand",
  };
  let text = katalog[key] || key;
  for (const [n, w] of Object.entries(vars || {})) {
    text = text.split("{" + n + "}").join(String(w));
  }
  return text;
}
function kuerze(s) { return String(s || ""); }
function el(tag) {
  return {
    tagName: tag, type: "", className: "", textContent: "", hidden: false,
    children: [],
    append(...n) { this.children.push(...n); },
    addEventListener() {},
    replaceChildren(...n) { this.children = [...n]; },
  };
}
const liste = el("ul");
const document = { createElement: el };
const $ = (sel) => sel === "#tools-cache-liste" ? liste : null;
let cacheListeAnzeigen = true;
"""


def _node(skript: str) -> dict:
    quelle = _STUB + "\n" + FORMAT_STUECKE + "\n" + BETRAG + "\n" + ZEICHNE + "\n" + skript
    aus = subprocess.run(
        ["node", "-e", quelle],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if aus.returncode != 0:
        raise AssertionError(aus.stderr or aus.stdout)
    return json.loads(aus.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestToolsCacheFiat(unittest.TestCase):

    def test_ohne_kurs_nur_sats(self):
        aus = _node(r"""
          Zustand.kurs = null;
          console.log(JSON.stringify(toolsCacheBetrag(50000)));
        """)
        self.assertEqual(aus, "50.000 sats")
        self.assertNotIn("€", aus)
        self.assertNotIn("$", aus)

    def test_de_nimmt_eur_aus_der_gui(self):
        aus = _node(r"""
          SPRACHE = "de";
          Zustand.kurs = { amount: 100000, currency: "EUR" };
          console.log(JSON.stringify(toolsCacheBetrag(100000)));
        """)
        self.assertIn("sats", aus)
        self.assertIn("€", aus)
        self.assertNotIn("$", aus)

    def test_en_nimmt_usd_aus_der_gui(self):
        aus = _node(r"""
          SPRACHE = "en";
          Zustand.kurs = { amount: 100000, currency: "USD" };
          console.log(JSON.stringify(toolsCacheBetrag(100000)));
        """)
        self.assertIn("sats", aus)
        self.assertIn("$", aus)
        self.assertNotIn("€", aus)

    def test_trefferzeile_traegt_fiat(self):
        aus = _node(r"""
          SPRACHE = "de";
          Zustand.kurs = { amount: 50000, currency: "EUR" };
          zeichneCacheListe([{
            value_sats: 100000, wallet: "A", teil: "bestand",
            address: "bc1qtest", spent: false, key: "aa:0",
          }]);
          console.log(JSON.stringify({
            text: liste.children[0].children[0].textContent,
            hidden: liste.hidden,
          }));
        """)
        self.assertFalse(aus["hidden"])
        self.assertIn("€", aus["text"])
        self.assertIn("A", aus["text"])
        self.assertIn("Bestand", aus["text"])
