"""
Herkunftsnetz-Overlay (web/views/herkunftsnetz.js): Einbindung statisch,
Ein-/Ausstieg mit Node gegen einen kleinen DOM-Ersatz.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WEB = WURZEL / "web"
NETZ = (WEB / "views" / "herkunftsnetz.js").read_text(encoding="utf-8")
STUB = (WURZEL / "tests" / "herkunftsnetz_dom_stub.js").read_text(encoding="utf-8")

K = "a" * 64 + ":0"
VORFAHR = "b" * 64 + ":1"
FREMD = "c" * 64 + ":0"

UMGEBUNG = """
const t = (k, v) => v ? `${k} ${JSON.stringify(v)}` : k;
const uiSprache = () => "de";
const formatZeitstrahlBetrag = (s) => `${s} sat`;
const ZeitstrahlAnsicht = { x0: 0, x1: 100, daten: null };
const zeitstrahlSichtPos = (p) => ((p - ZeitstrahlAnsicht.x0) / (ZeitstrahlAnsicht.x1 - ZeitstrahlAnsicht.x0)) * 100;
const Zustand = {
  steuer: { _abfrage: "?jahr=2024&frist=1&stichtag=" },
  herkunftAlleLaeuft: false,
  config: { wallets: [{ id: "wid-1", name: "Cold" }] },
};
const spruenge = [];
const walletSpruenge = [];
const traceSpruenge = [];
function springeZuWalletUtxo(id, key, adresse) { walletSpruenge.push([id, key, adresse]); return true; }
function springeZuTraceUtxo(key, meta) { traceSpruenge.push([key, meta]); return true; }
const kopien = [];
function zeigeHerkunftFuer(key, opts) { spruenge.push([key, Zustand.traceSprung, opts]); }
function kopiereInZwischenablage(text) { kopien.push(text); return true; }
const aufrufe = { api: [], lauf: [], laden: 0, bericht: [], log: [] };
let antworten = [];
async function api(pfad) { aufrufe.api.push(pfad); return antworten.shift(); }
function herkunftAllerUtxos(ziele) { aufrufe.lauf.push(ziele); }
async function ladeSteuerjahr() { aufrufe.laden += 1; }
function logZeile(text) { aufrufe.log.push(text); }
function saAnkreuzAuswahl() { return { txids: [], utxos: [] }; }
function ladeSelbstanzeigeExport(art, auswahl) { aufrufe.bericht.push([art, auswahl]); }
const viewport = mitId("achse-viewport", new El("div"));
const spur = mitId("achse-spur", new El("div"));
viewport.append(spur);
const hinweis = mitId("netz-hinweis", new El("div"));
function punkt(key) {
  const p = new El("span"); p.className = "achse-punkt mittel offen klickbar"; p.dataset.key = key;
  p.addEventListener("click", (e) => { e.stopPropagation(); herkunftsnetzUmschalten(key); });
  spur.append(p); return p;
}
const geist = new El("span"); geist.className = "achse-punkt geister erfuellt"; spur.append(geist);
const pA = punkt("%(K)s"); const pB = punkt("dd:0");
ZeitstrahlAnsicht.daten = { zeitstrahl: { frist_pos: 50, events: [{ key: "%(K)s" }, { key: "dd:0" }] } };
const warte = () => new Promise((r) => setTimeout(r, 0));
const NETZ = {
  fokus_key: "%(K)s", fokus_pos: 60, fokus_y: 50, fokus_sats: 1000, trace_fehlt: false,
  verfolgt_vollstaendig: false, gekappt: false,
  vorfahren: [
    { key: "%(K)s", typ: "eigen", pos_output: 70, y: 50, value_sats: 1000, anteil_sats: 1000, zeit: "01.06.2024 12:00", wallet: "Hot" },
    { key: "%(V)s", typ: "eigen", pos_output: 40, y: 60, value_sats: 5000, anteil_sats: 600, zeit: "01.02.2024 12:00", wallet: "Cold" },
    { key: "%(F)s", typ: "fremd", pos_output: -10, y: 120, value_sats: 9000, anteil_sats: 400, zeit: "01.01.2020 12:00" },
  ],
  kanten: [
    { von: "%(V)s", nach: "%(K)s", sats: 600, eigen: true },
    { von: "%(F)s", nach: "%(K)s", sats: 400, eigen: false },
  ],
};
const stand = () => {
  const schicht = spur.querySelector(".netz-schicht");
  return {
    an: spur.classList.contains("netz-an"),
    fokus: pA.classList.contains("netz-fokus"),
    andererFokus: pB.classList.contains("netz-fokus"),
    ringe: schicht ? schicht.querySelectorAll(".netz-knoten").length : 0,
    linien: schicht ? schicht.children[0].querySelectorAll(".netz-kante").length : 0,
    hinweis: !hinweis.hidden,
    hinweisText: hinweis.textContent,
    status: hinweis.dataset.status || "",
  };
};
""" % {"K": K, "V": VORFAHR, "F": FREMD}


def _node(szenario: str) -> dict:
    aus = subprocess.run(
        ["node", "-e", STUB + UMGEBUNG + NETZ + "\n(async () => {\n" + szenario + "\n})();"],
        capture_output=True, text=True, timeout=30,
    )
    if aus.returncode != 0:
        raise AssertionError(aus.stderr)
    return json.loads(aus.stdout)


class TestEinbindung(unittest.TestCase):

    def test_geladen_nach_steuerjahr_und_hinweiszeile_da(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('src="/views/steuerjahr.js'),
                        html.index('src="/views/herkunftsnetz.js'))
        self.assertLess(html.index('src="/views/herkunftsnetz.js'),
                        html.index('src="/chrome_nav.js'))
        self.assertIn('id="netz-hinweis"', html)

    def test_punktklick_und_neuzeichnen_und_ansichtswechsel(self):
        steuer = (WEB / "views" / "steuerjahr.js").read_text(encoding="utf-8")
        self.assertIn("herkunftsnetzUmschalten(key)", steuer)
        self.assertIn("herkunftsnetzZumBaum(v)", NETZ)
        self.assertIn("function herkunftsnetzBaumVorladen", NETZ)
        self.assertIn("kopiereInZwischenablage(outpoint)", NETZ)
        self.assertIn("kopiereInZwischenablage(eintrag.address)", steuer)
        self.assertIn("herkunftsnetzSpringbar", NETZ)
        herkunft = (WEB / "views" / "herkunft.js").read_text(encoding="utf-8")
        self.assertIn("function springeImHerkunftsbaum", herkunft)
        self.assertIn("function springeZuTraceUtxo", herkunft)
        self.assertIn("setzeKlapp(kopf, klapp, zweig, true)", herkunft)
        self.assertIn("herkunftsnetzBericht(key)", steuer)
        self.assertIn('addEventListener("dblclick"', steuer)
        self.assertIn("herkunftsnetzZeichnen()", steuer)
        self.assertIn("function herkunftsnetzOhneHerkunft", NETZ)
        self.assertIn("springeZuTraceUtxo(key, punkt)", NETZ)
        # Zeitstrahl-Rechnung unberührt: kein Overlay in events.
        self.assertNotIn("events.push", NETZ)
        nav = (WEB / "chrome_nav.js").read_text(encoding="utf-8")
        start = nav.index("function zeigeAnsicht(")
        self.assertIn("herkunftsnetzBeenden()", nav[start:start + 600])
        herkunft = (WEB / "views" / "herkunft.js").read_text(encoding="utf-8")
        self.assertIn("ziele.danach({ art })", herkunft)

    def test_texte_in_beiden_sprachen(self):
        schluessel = set(re.findall(r't\("(tax\.netz\w+)"', NETZ))
        steuer = (WEB / "views" / "steuerjahr.js").read_text(encoding="utf-8")
        schluessel |= set(re.findall(r't\("(tax\.netz\w+)"', steuer))
        self.assertIn("tax.netzHint", schluessel)
        for code in ("de", "en"):
            katalog = json.loads((WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))
            for s in schluessel:
                self.assertTrue(katalog.get(s), f"{code}: {s}")
        de = json.loads((WEB / "locales" / "de.json").read_text(encoding="utf-8"))
        self.assertIn("eigene Vorgänger nach Output-Zeit", de["tax.netzHint"])
        self.assertIn("tax.netzJump", schluessel)
        self.assertIn("tax.netzJumpTitle", schluessel)
        self.assertNotIn("tax.netzJumpMissing", schluessel)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestEinUndAusstieg(unittest.TestCase):

    def test_klick_zeigt_netz_zweiter_klick_beendet(self):
        r = _node("""
          antworten.push(NETZ);
          pA.fire("click");
          const laedt = stand();
          await warte();
          const an = stand();
          const fremd = spur.querySelector(".netz-fremd");
          const vorFrist = spur.querySelector(".netz-eigen:not(.netz-fokus-b)");
          const kanten = [...spur.querySelectorAll(".netz-kante")];
          const verlauf = kanten.filter((k) => k.classList.contains("netz-kante-verlauf"));
          pA.fire("click");
          console.log(JSON.stringify({ laedt, an, aus: stand(), api: aufrufe.api,
            fremdLeft: fremd.style.left, fremdBottom: fremd.style.bottom,
            fremdKlasse: fremd.className,
            vorFrist: vorFrist ? vorFrist.className : "",
            verlauf: verlauf.map((k) => k.style.stroke) }));
        """)
        self.assertEqual(r["laedt"]["status"], "laedt")
        self.assertIn("tax.netzWait", r["laedt"]["hinweisText"])
        self.assertEqual(
            r["api"][0],
            f"/tax/herkunftsnetz?jahr=2024&frist=1&stichtag=&key={K.replace(':', '%3A')}",
        )
        self.assertTrue(any(p.startswith("/trace?target=") for p in r["api"]))
        an = r["an"]
        self.assertTrue(an["an"] and an["fokus"] and an["hinweis"])
        self.assertFalse(an["andererFokus"])
        self.assertEqual(an["ringe"], 3)
        self.assertEqual(an["linien"], 3)  # 2 Kanten + Anschaffung→Output-Zeit
        self.assertIn("tax.netzHint", an["hinweisText"])
        # Über dem Skalenende an den Rand. Vor dem Achsenbeginn als eigene X-Lage,
        # nicht auf den Nullpunkt geklemmt (Fenster steht hier bei 0..100).
        self.assertEqual(r["fremdLeft"], "-10%")
        self.assertEqual(r["fremdBottom"], "100%")
        self.assertIn("netz-vor-achse", r["fremdKlasse"])
        self.assertIn("netz-ueber-achse", r["fremdKlasse"])
        self.assertIn("netz-vor-frist", r["fremdKlasse"])
        self.assertIn("netz-vor-frist", r["vorFrist"])

    def test_grauer_punkt_oeffnet_herkunft_aufgeklappt(self):
        """Ohne Herkunft gibt es kein Netz. Der Klick öffnet den Trace aufgeklappt."""
        r = _node("""
          pA.className = "achse-punkt mittel ungeprueft klickbar";
          pA.dataset.walletId = "wid-1";
          pA.dataset.address = "bc1qgrau";
          pA.fire("click");
          await warte();
          console.log(JSON.stringify({
            an: stand().an, trace: traceSpruenge, wallet: walletSpruenge,
            api: aufrufe.api.length,
          }));
        """)
        self.assertFalse(r["an"])
        self.assertEqual(r["wallet"], [])
        self.assertEqual(r["trace"][0][0], K)
        self.assertEqual(r["trace"][0][1]["address"], "bc1qgrau")
        self.assertEqual(r["api"], 0)

    def test_roter_rahmen_springt_ins_wallet_auch_mit_netzdaten(self):
        """Gelber oder grüner Punkt mit rotem Rahmen: Wallet, kein Pie/Netz."""
        r = _node("""
          pA.dataset.walletId = "wid-1";
          pA.dataset.address = "bc1qtest";
          pA.classList.add("herkunft-offen-marke");
          antworten.push(NETZ);
          pA.fire("click");
          await warte();
          console.log(JSON.stringify({
            an: stand().an, wallet: walletSpruenge, api: aufrufe.api.length,
          }));
        """)
        self.assertFalse(r["an"])
        self.assertEqual(r["wallet"], [["wid-1", K, "bc1qtest"]])
        self.assertEqual(r["api"], 1)

    def test_klick_auf_eigenen_vorgaenger_springt_in_den_baum(self):
        r = _node("""
          antworten.push(NETZ);
          pA.fire("click");
          await warte();
          const vorab = aufrufe.api.filter((p) => p.startsWith("/trace?target="));
          const eigen = spur.querySelector(".netz-eigen:not(.netz-fokus-b)");
          const fremd = spur.querySelector(".netz-fremd");
          eigen.fire("click");
          const nachEigen = spruenge.slice();
          const kopie = kopien.slice();
          fremd.fire("click");
          console.log(JSON.stringify({
            sprung: eigen.classList.contains("netz-sprung"),
            fremdSprung: fremd.classList.contains("netz-sprung"),
            nachEigen, spruenge, kopie, vorab,
          }));
        """)
        self.assertTrue(r["sprung"])
        self.assertTrue(r["fremdSprung"])
        self.assertEqual(r["nachEigen"][0][0], K)
        self.assertEqual(r["nachEigen"][0][1]["key"], VORFAHR)
        self.assertEqual(r["spruenge"][1][1]["typ"], "fremd")
        self.assertEqual(r["spruenge"][1][1]["eltern"], K)
        self.assertEqual(r["kopie"], [VORFAHR])
        self.assertEqual(len(r["vorab"]), 1)
        self.assertIn("target=", r["vorab"][0])

    def test_kante_zwischen_verschiedenen_wallets_ist_gepunktet(self):
        r = _node("""
          antworten.push(NETZ);
          pA.fire("click");
          await warte();
          const kanten = [...spur.querySelectorAll(".netz-kante")];
          console.log(JSON.stringify(kanten.map((k) => k.className)));
        """)
        wallet = [k for k in r if "netz-kante-wallet" in k]
        self.assertEqual(len(wallet), 1)
        self.assertNotIn("netz-kante-fremd", wallet[0])

    def test_x_achse_reicht_bis_zum_aeltesten_herkunftsdatum(self):
        steuer = (WEB / "views" / "steuerjahr.js").read_text(encoding="utf-8")
        start = steuer.index("/**\n * Linke Grenze der Zeitachse")
        ende = steuer.index("function zeitstrahlZoom(")
        rumpf = steuer[start:ende]
        aus = subprocess.run(
            ["node", "-e", """
const Herkunftsnetz = { daten: { fokus_pos: 40, vorfahren: [
  { pos_output: 40 }, { pos_output: -25 }, { pos_output: -8 },
] } };
const ZEITSTRAHL_MIN_SPAN = 2;
function zeitstrahlYMax() { return 100; }
""" + rumpf + """
const ZeitstrahlAnsicht = { x0: 0, x1: 100, y0: 0, y1: 100 };
zeitstrahlFensterBegrenzen();
const voll = { x0: ZeitstrahlAnsicht.x0, x1: ZeitstrahlAnsicht.x1 };
ZeitstrahlAnsicht.x0 = -40;
ZeitstrahlAnsicht.x1 = 60;
zeitstrahlFensterBegrenzen();
const links = { x0: ZeitstrahlAnsicht.x0, x1: ZeitstrahlAnsicht.x1 };
ZeitstrahlAnsicht.x0 = -10;
ZeitstrahlAnsicht.x1 = -8;
zeitstrahlFensterBegrenzen();
const nah = { x0: ZeitstrahlAnsicht.x0, x1: ZeitstrahlAnsicht.x1 };
const ohne = (() => {
  Herkunftsnetz.daten = null;
  const a = { x0: -5, x1: 95, y0: 0, y1: 100 };
  Object.assign(ZeitstrahlAnsicht, a);
  zeitstrahlFensterBegrenzen();
  return { x0: ZeitstrahlAnsicht.x0, x1: ZeitstrahlAnsicht.x1 };
})();
console.log(JSON.stringify({ min: zeitstrahlXMin(), quelle: zeitstrahlXMin.toString().slice(0, 180), voll, links, nah, ohne }));
"""],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(aus.returncode, 0, aus.stderr)
        r = json.loads(aus.stdout)
        self.assertEqual(r["links"]["x0"], -25)
        self.assertEqual(r["links"]["x1"], 75)
        self.assertLess(r["nah"]["x0"], 0)
        self.assertEqual(r["ohne"], {"x0": 0, "x1": 100})
        self.assertEqual(r["voll"], {"x0": 0, "x1": 100})
        self.assertIn("zeitstrahlXMin()", (WEB / "views" / "steuerjahr.js").read_text(encoding="utf-8"))
        self.assertIn("fensterGeoeffnet", NETZ)

    def test_x_labels_verdichten_sich_bis_auf_tage(self):
        steuer = (WEB / "views" / "steuerjahr.js").read_text(encoding="utf-8")
        start = steuer.index("function formatTickMonatJahr(")
        ende = steuer.index("/**\n * Dekaden-Ticks")
        aus = subprocess.run(
            ["node", "-e", """
function parseDeDatum(text) {
  const m = String(text || "").match(/^(\\d{2})\\.(\\d{2})\\.(\\d{4})$/);
  if (!m) return null;
  return new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]), 12, 0, 0);
}
const ZeitstrahlAnsicht = { x0: 0, x1: 100 };
""" + steuer[start:ende] + """
const strahl = { von: "01.01.2016", bis: "01.01.2026" };
function labels(x0, x1) {
  ZeitstrahlAnsicht.x0 = x0;
  ZeitstrahlAnsicht.x1 = x1;
  return zeitstrahlTicksImFenster(strahl, 720).map((t) => t.label);
}
const weit = labels(0, 100);
const monate = labels(50, 56);
const tage = labels(50, 50.15);
console.log(JSON.stringify({ weit, monate, tage }));
"""],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(aus.returncode, 0, aus.stderr)
        r = json.loads(aus.stdout)
        self.assertTrue(all(len(x) == 4 for x in r["weit"]), r)
        self.assertGreaterEqual(len(r["monate"]), 3, r)
        self.assertTrue(all("/" in x for x in r["monate"]), r)

        self.assertTrue(any("." in x and len(x) > 7 for x in r["tage"]), r["tage"])
        abstaende = []
        for a, b in zip(r["tage"], r["tage"][1:]):
            abstaende.append(abs(int(a[:2]) - int(b[:2])))
        self.assertTrue(abstaende)
        self.assertTrue(all(d <= 1 or d >= 27 for d in abstaende), abstaende)

    def test_esc_leerklick_ziehen_und_ringklick(self):
        r = _node("""
          antworten.push(NETZ, NETZ);
          pA.fire("click"); await warte();
          const ring = spur.querySelector(".netz-knoten");
          ring.fire("click");
          const nachRing = stand().an;
          viewport.handlers.pointerdown[0]({ clientX: 10, clientY: 10 });
          spur.fire("click", { clientX: 60, clientY: 10 });
          const nachZiehen = stand().an;
          viewport.handlers.pointerdown[0]({ clientX: 10, clientY: 10 });
          spur.fire("click", { clientX: 11, clientY: 10 });
          const nachLeer = stand().an;
          pA.fire("click"); await warte();
          document.fire("keydown", { key: "Escape" });
          console.log(JSON.stringify({ nachRing, nachZiehen, nachLeer, nachEsc: stand().an }));
        """)
        self.assertEqual(r, {"nachRing": True, "nachZiehen": True,
                             "nachLeer": False, "nachEsc": False})

    def test_anderer_punkt_wechselt_fokus_neuzeichnen_ohne_punkt_beendet(self):
        r = _node("""
          antworten.push(NETZ, { ...NETZ, fokus_key: "dd:0", vorfahren: [], kanten: [] });
          pA.fire("click"); await warte();
          pB.fire("click"); await warte();
          const gewechselt = { a: pA.classList.contains("netz-fokus"), b: pB.classList.contains("netz-fokus") };
          ZeitstrahlAnsicht.daten = { zeitstrahl: { events: [{ key: "%(K)s" }] } };
          herkunftsnetzZeichnen();
          console.log(JSON.stringify({ gewechselt, danach: stand().an }));
        """ % {"K": K})
        self.assertEqual(r["gewechselt"], {"a": False, "b": True})
        self.assertFalse(r["danach"])

    def test_fehlender_trace_zeigt_netz_nicht(self):
        """Ohne Baum kein Overlay. Der Sprung ins Wallet hängt an der Wallet-Kennung."""
        r = _node("""
          antworten.push({ ...NETZ, trace_fehlt: true, vorfahren: [], kanten: [] });
          pA.fire("click"); await warte();
          console.log(JSON.stringify({
            ...stand(), laeufe: aufrufe.lauf.length, api: aufrufe.api.length,
          }));
        """)
        self.assertEqual(r["laeufe"], 0)
        self.assertGreaterEqual(r["api"], 1)
        self.assertEqual(r["ringe"], 0)
        self.assertTrue(r["an"])

    def test_doppelklick_oeffnet_bericht_ohne_netz_zu_toggeln(self):
        r = _node("""
          herkunftsnetzBericht("%(K)s");
          await warte();
          console.log(JSON.stringify({ bericht: aufrufe.bericht, an: stand().an }));
        """ % {"K": K})
        self.assertEqual(r["bericht"], [["html", {"txids": [], "utxos": [K]}]])
        self.assertFalse(r["an"])

    def test_bericht_knopf_behaelt_html_report(self):
        r = _node("""
          antworten.push(NETZ);
          pA.fire("click"); await warte();
          hinweis.querySelector(".netz-bericht").fire("click");
          console.log(JSON.stringify(aufrufe.bericht));
        """)
        self.assertEqual(r, [["html", {"txids": [], "utxos": [K]}]])


if __name__ == "__main__":
    unittest.main()
