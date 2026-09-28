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
const Zustand = { steuer: { _abfrage: "?jahr=2024&frist=1&stichtag=" }, herkunftAlleLaeuft: false };
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
    { key: "%(K)s", typ: "eigen", pos_output: 70, y: 50, value_sats: 1000, anteil_sats: 1000, zeit: "01.06.2024 12:00" },
    { key: "%(V)s", typ: "eigen", pos_output: 40, y: 60, value_sats: 5000, anteil_sats: 600, zeit: "01.02.2024 12:00" },
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
        self.assertIn("herkunftsnetzBericht(key)", steuer)
        self.assertIn('addEventListener("dblclick"', steuer)
        self.assertIn("herkunftsnetzZeichnen()", steuer)
        # Zeitstrahl-Rechnung unberührt: kein Overlay in events.
        self.assertNotIn("events.push", NETZ)
        nav = (WEB / "chrome_nav.js").read_text(encoding="utf-8")
        start = nav.index("function zeigeAnsicht(")
        self.assertIn("herkunftsnetzBeenden()", nav[start:start + 600])
        herkunft = (WEB / "views" / "herkunft.js").read_text(encoding="utf-8")
        self.assertIn("ziele.danach({ art })", herkunft)
        self.assertIn("baum_noetig: true", herkunft)

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
        self.assertEqual(de["tax.netzHint"], "Orange: eigene Vorgänger nach Output-Zeit")


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestEinUndAusstieg(unittest.TestCase):

    def test_klick_zeigt_netz_zweiter_klick_beendet(self):
        r = _node("""
          antworten.push(NETZ);
          pA.fire("click");
          const laedt = stand();
          await warte();
          const an = stand();
          const schicht = spur.querySelector(".netz-schicht");
          const fremd = schicht.querySelectorAll(".netz-fremd")[0];
          const vorFrist = schicht.querySelector(".netz-eigen:not(.netz-fokus-b)");
          const kanten = [...schicht.querySelectorAll(".netz-kante")];
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
        self.assertEqual(r["api"], [f"/tax/herkunftsnetz?jahr=2024&frist=1&stichtag=&key={K.replace(':', '%3A')}"])
        an = r["an"]
        self.assertTrue(an["an"] and an["fokus"] and an["hinweis"])
        self.assertFalse(an["andererFokus"])
        self.assertEqual(an["ringe"], 3)
        self.assertEqual(an["linien"], 3)  # 2 Kanten + Anschaffung→Output-Zeit
        self.assertIn("tax.netzHint", an["hinweisText"])
        # Vor dem Achsenbeginn / über dem Skalenende: an den Rand geklemmt.
        self.assertEqual(r["fremdLeft"], "0%")
        self.assertEqual(r["fremdBottom"], "100%")
        self.assertIn("netz-vor-achse", r["fremdKlasse"])
        self.assertIn("netz-ueber-achse", r["fremdKlasse"])
        self.assertIn("netz-vor-frist", r["fremdKlasse"])
        self.assertIn("netz-vor-frist", r["vorFrist"])
        # Beide Kanten kreuzen die Frist (grün → orange). Die Anschaffungslinie nicht.
        self.assertEqual(len(r["verlauf"]), 2)
        self.assertTrue(all(str(s).startswith("url(#netz-verlauf-") for s in r["verlauf"]))
        aus = r["aus"]
        self.assertFalse(aus["an"] or aus["fokus"] or aus["hinweis"])
        self.assertEqual(aus["ringe"], 0)

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

    def test_fehlender_trace_startet_horizont_lauf(self):
        r = _node("""
          antworten.push({ ...NETZ, trace_fehlt: true, vorfahren: [], kanten: [] });
          pA.fire("click"); await warte();
          const lauf = aufrufe.lauf[0];
          const waehrend = stand();
          await lauf.danach({ art: "warn" });
          const abbruch = { ...stand(), laden: aufrufe.laden };
          // Neuer Anlauf: diesmal fertig, danach Netz da.
          pA.fire("click");  // zweiter Klick: aus
          antworten.push({ ...NETZ, trace_fehlt: true, vorfahren: [], kanten: [] }, NETZ);
          pA.fire("click"); await warte();
          await aufrufe.lauf[1].danach({ art: "gut" }); await warte();
          console.log(JSON.stringify({
            steuer: lauf.steuer, keys: lauf.utxo_keys, gelb: lauf.gelbVertiefen, baum: lauf.baumNoetig,
            waehrend, abbruch, fertig: { ...stand(), laden: aufrufe.laden },
            log: aufrufe.log.length,
          }));
        """)
        self.assertTrue(r["steuer"])
        self.assertEqual(r["keys"], [K])
        self.assertFalse(r["gelb"])
        self.assertTrue(r["baum"])
        self.assertEqual(r["waehrend"]["status"], "trace")
        self.assertIn("tax.netzTraceRunning", r["waehrend"]["hinweisText"])
        self.assertEqual(r["log"], 2)
        # Abbruch: Bestand unangetastet (kein Neuladen), Hinweis „kein Baum“.
        self.assertEqual(r["abbruch"]["laden"], 0)
        self.assertEqual(r["abbruch"]["status"], "fehlt")
        self.assertEqual(r["abbruch"]["ringe"], 0)
        self.assertTrue(r["abbruch"]["fokus"])
        # Erfolg: Steuerjahr neu (Layer A), dann Netz.
        self.assertEqual(r["fertig"]["laden"], 1)
        self.assertEqual(r["fertig"]["ringe"], 3)

    def test_laufender_lauf_blockiert_nicht(self):
        r = _node("""
          Zustand.herkunftAlleLaeuft = true;
          antworten.push({ ...NETZ, trace_fehlt: true, vorfahren: [], kanten: [] });
          pA.fire("click"); await warte();
          console.log(JSON.stringify({ ...stand(), laeufe: aufrufe.lauf.length }));
        """)
        self.assertEqual(r["laeufe"], 0)
        self.assertEqual(r["status"], "busy")

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
