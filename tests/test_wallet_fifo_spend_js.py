"""
FIFO-Spend-Leiste in der Kopfzeile der Wallet-UTXO-Liste (web/views/wallets.js).

Schritt 1 ist reine Anzeige: „n UTXOs“ statt „n Adresse(n) mit Guthaben“,
daneben „defensiv/offensiv max <n> grüne sats ausgebbar“, Betragsfeld und ein
PSBT-Knopf ohne Funktion. Die grünen sats kommen aus der Steuerauswertung
(Zeitstrahl-Punkte je UTXO), nicht aus einer Losbuchhaltung.
Node-Stub über die echten Funktionen; Kataloge und HTML statisch.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_wallet_mempool_js import _funktion

WURZEL = Path(__file__).resolve().parent.parent
WEB = WURZEL / "web"
WALLETS = (WEB / "views" / "wallets.js").read_text(encoding="utf-8")
FORMAT = (WEB / "format.js").read_text(encoding="utf-8")
#: Satcomma-Gruppentrenner (U+202F NARROW NO-BREAK SPACE).
NB = "\u202f"
STEUER = (WEB / "views" / "steuerjahr.js").read_text(encoding="utf-8")
EINST = (WEB / "views" / "einstellungen.js").read_text(encoding="utf-8")
HTML = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "style.css").read_text(encoding="utf-8")


def _katalog(code: str) -> dict:
    return json.loads((WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))


_STUB = r"""
const katalog = {
  "wallet.fifoSpendDefensive": "defensiv max {n} grün ausgebbar",
  "wallet.fifoSpendOffensive": "offensiv max {n} grün ausgebbar",
  "wallet.fifoSpendTitleMempool": "{count} UTXO(s) im Mempool – {betrag} grün abgezogen.",
  "wallet.fifoSpendMempoolIncompleteTitle": "Mempool-Stand unvollständig",
  "wallet.fifoSpendAmountTitle": "Betrag in sats, ganze Zahl von 1 bis {max}.",
  "wallet.fifoSpendUnavailableTitle": "Grüne sats gerade nicht verfügbar: {msg}",
};
const t = (k, v = {}) => (katalog[k] || k).replace(/\{(\w+)\}/g, (_, n) => String(v[n] ?? ""));
const formatZahl = (n) => Number(n || 0).toLocaleString("de-DE");
const formatLocale = () => "de-DE";
const formatSats = (n) => `${n} sats`;
const uiSprache = () => "de";
function mkEl() {
  const attrs = {};
  const klassen = new Set();
  return {
    hidden: true, value: "", disabled: false, title: "", textContent: "",
    dataset: {}, validity: { badInput: false },
    classList: {
      toggle(k, an) { if (an) klassen.add(k); else klassen.delete(k); },
      contains(k) { return klassen.has(k); },
    },
    setAttribute(k, v) { attrs[k] = String(v); },
    removeAttribute(k) { delete attrs[k]; if (k === "max") delete this.max; },
    getAttribute(k) { return attrs[k] ?? null; },
  };
}
const els = {
  "#fifo-spend": mkEl(),
  "#fifo-spend-text": mkEl(),
  "#fifo-spend-betrag": mkEl(),
};
const $ = (sel) => els[sel] || null;
function setzeText(el, text) { el.textContent = text; }
const Zustand = {
  config: { steuer: { anschaffung: "juengste", haltefrist_jahre: 1, stichtag: "" } },
  ansicht: "wallet", walletId: "w1", walletLadeGen: 1, contextBereit: true,
};
function steuerEinstellungen() { return Zustand.config.steuer; }
function walletMempoolErlaubt() { return Zustand.contextBereit !== false; }
const aufrufe = [];
let antwort = { zeitstrahl: { events: [] } };
async function api(pfad) { aufrufe.push(pfad); return JSON.parse(JSON.stringify(antwort)); }
const warte = () => new Promise((r) => setTimeout(r, 10));
const EV = [
  // w1: ganz grün
  { key: "aa:0", wallet_id: "w1", value_sats: 50000, sats_gruen: 50000, sats_orange: 0, sats_grau: 0 },
  // w1: gemischt grün/grau
  { key: "bb:1", wallet_id: "w1", value_sats: 30000, sats_gruen: 20000, sats_orange: 0, sats_grau: 10000 },
  // w1: gemischt grün/orange
  { key: "cc:0", wallet_id: "w1", value_sats: 10000, sats_gruen: 4000, sats_orange: 6000, sats_grau: 0 },
  // w1: ohne Herkunftsbaum (kein Lot) — nie grün, auch wenn erfuellt
  { key: "dd:0", wallet_id: "w1", value_sats: 7000, sats_gruen: null, erfuellt: true },
  // w1: grün, aber Neuvermögen (Stichtag)
  { key: "ee:0", wallet_id: "w1", value_sats: 9000, sats_gruen: 9000, sats_orange: 0, sats_grau: 0, neuvermoegen: true },
  // anderes Wallet
  { key: "ff:0", wallet_id: "w2", value_sats: 1000000, sats_gruen: 1000000, sats_orange: 0, sats_grau: 0 },
];
"""

_FUNKTIONEN = [
    "function fifoSpendModus(",
    "function fifoUtxoKey(",
    "function fifoPendingInfo(",
    "function formatSatcomma(",
    "function fifoBetragMitFiat(",
    "function fifoBetragText(",
    "function fifoSpendMax(",
    "function fifoGrueneSats(",
    "function fifoSpendAbfrage(",
    "function holeFifoSpendAuswertung(",
    "function aktualisiereFifoSpend(",
    "function zeichneFifoSpend(",
    "function fifoSpendBetragGueltig(",
    "function pruefeFifoSpendBetrag(",
]


def _node(skript: str) -> dict:
    luecke = next(z for z in WALLETS.splitlines() if z.startswith("const FIFO_SATCOMMA_LUECKE"))
    teile = [_STUB, luecke] + [_funktion(WALLETS, k) for k in _FUNKTIONEN]
    code = (
        "\n".join(teile)
        + "\n(async () => {\n" + skript
        + "\n})().catch((e) => { console.error(e); process.exit(1); });"
    )
    aus = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    if aus.returncode != 0:
        raise AssertionError(aus.stderr[-2000:])
    return json.loads(aus.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestFifoGrueneSats(unittest.TestCase):

    def test_defensiv_nur_ganz_gruene_offensiv_gruene_anteile(self):
        erg = _node(r"""
          process.stdout.write(JSON.stringify(fifoGrueneSats(EV, "w1")));
        """)
        # defensiv: nur der ganz grüne UTXO; grau/orange gemischt zählt nicht.
        self.assertEqual(erg["defensiv"], 50000)
        # offensiv: 50000 + 20000 + 4000 — ohne Baum und Neuvermögen nicht.
        self.assertEqual(erg["offensiv"], 74000)
        self.assertEqual(erg["anzahl"], 5)
        self.assertEqual(erg["ohneHerkunft"], 1)

    def test_fremdes_wallet_und_ohne_id_zaehlen_nicht(self):
        erg = _node(r"""
          process.stdout.write(JSON.stringify({
            leer: fifoGrueneSats(EV, ""), w3: fifoGrueneSats(EV, "w3"),
          }));
        """)
        self.assertEqual(erg["leer"]["offensiv"], 0)
        self.assertEqual(erg["w3"]["defensiv"], 0)
        self.assertEqual(erg["w3"]["anzahl"], 0)

    def test_gruenanteil_hoechstens_utxo_betrag(self):
        erg = _node(r"""
          const ev = [{ wallet_id: "w1", value_sats: 100, sats_gruen: 101, sats_orange: 0, sats_grau: 0 }];
          process.stdout.write(JSON.stringify(fifoGrueneSats(ev, "w1")));
        """)
        self.assertEqual(erg["offensiv"], 100)
        self.assertEqual(erg["defensiv"], 100)


    def test_mempool_ausgabe_wird_abgezogen(self):
        erg = _node(r"""
          const mit = fifoGrueneSats(EV, "w1", new Set(["aa:0", "bb:1"]));
          const gross = fifoGrueneSats(EV, "w1", ["AA:0"]);  // Schreibweise egal
          process.stdout.write(JSON.stringify({ mit, gross }));
        """)
        m = erg["mit"]
        # aa:0 (50000 ganz grün) und bb:1 (20000 grün von 30000) sind unterwegs.
        self.assertEqual(m["defensiv"], 0)
        self.assertEqual(m["offensiv"], 4000)
        self.assertEqual(m["abzug"], {"defensiv": 50000, "offensiv": 70000, "anzahl": 2})
        self.assertEqual(erg["gross"]["defensiv"], 0)
        self.assertEqual(erg["gross"]["abzug"]["defensiv"], 50000)

    def test_pending_info_ganzer_bestand_oder_seite(self):
        erg = _node(r"""
          const feld = fifoPendingInfo({ pending_spending_count: 2,
            pending_spending_keys: ["AA:0", "bb:1"], utxos: [] });
          const seite = fifoPendingInfo({ pending_spending_count: 1,
            addresses: [{ utxos: [{ key: "cc:0", spending_pending: true }, { key: "dd:0" }] }] });
          const luecke = fifoPendingInfo({ pending_spending_count: 3,
            utxos: [{ txid: "aa", vout: 0, spending_pending: true }] });
          const leer = fifoPendingInfo(null);
          process.stdout.write(JSON.stringify({
            feld: [...feld.keys], feldOk: feld.vollstaendig,
            seite: [...seite.keys], seiteOk: seite.vollstaendig,
            luecke: [...luecke.keys], lueckeOk: luecke.vollstaendig, leerOk: leer.vollstaendig,
          }));
        """)
        self.assertEqual(erg["feld"], ["aa:0", "bb:1"])
        self.assertTrue(erg["feldOk"])
        self.assertEqual(erg["seite"], ["cc:0"])
        self.assertTrue(erg["seiteOk"])
        self.assertEqual(erg["luecke"], ["aa:0"])
        self.assertFalse(erg["lueckeOk"])
        self.assertTrue(erg["leerOk"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestFifoLeiste(unittest.TestCase):

    def test_text_folgt_lesart_und_laedt_einmal(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1");
          const laedt = els["#fifo-spend-text"].textContent;
          const feldWaehrend = els["#fifo-spend-betrag"].disabled;
          await warte();
          const defensiv = els["#fifo-spend-text"].textContent;
          const max = els["#fifo-spend-betrag"].max;
          // Seitenwechsel / Mempool-Neumalen: derselbe Stand, keine Anfrage.
          aktualisiereFifoSpend("w1"); await warte();
          const n1 = aufrufe.length;
          // Einstellung umgeschaltet (Hook aus zeichneSteuerEinstellungen).
          Zustand.config.steuer.anschaffung = "aelteste";
          aktualisiereFifoSpend(); await warte();
          const offensiv = els["#fifo-spend-text"].textContent;
          process.stdout.write(JSON.stringify({
            laedt, feldWaehrend, defensiv, max, n1, n2: aufrufe.length, offensiv,
            sichtbar: !els["#fifo-spend"].hidden, pfad: aufrufe[0],
            modus: els["#fifo-spend-text"].dataset.modus,
          }));
        """)
        self.assertEqual(erg["laedt"], "defensiv max … grün ausgebbar")
        self.assertTrue(erg["feldWaehrend"])
        self.assertEqual(erg["defensiv"], f"defensiv max 0,00{NB}050{NB}000 BTC grün ausgebbar")
        self.assertEqual(erg["max"], "50000")
        self.assertEqual(erg["n1"], 1)
        self.assertEqual(erg["n2"], 2)
        self.assertEqual(erg["offensiv"], f"offensiv max 0,00{NB}074{NB}000 BTC grün ausgebbar")
        self.assertEqual(erg["modus"], "offensiv")
        self.assertTrue(erg["sichtbar"])
        self.assertTrue(erg["pfad"].startswith("/tax?jahr="))
        self.assertIn("seite=1", erg["pfad"])
        self.assertIn("limit=0", erg["pfad"])

    def test_mempool_abzug_beim_neuzeichnen_ohne_neue_anfrage(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          Zustand._walletUtxoDaten = { total_count: 5, pending_spending_count: 0,
                                       pending_spending_keys: [] };
          aktualisiereFifoSpend("w1"); await warte();
          const vorher = els["#fifo-spend-text"].textContent;
          // Mempool-Abgleich malt die Liste neu: aa:0 wird gerade ausgegeben.
          Zustand._walletUtxoDaten = { total_count: 5, pending_spending_count: 1,
                                       pending_spending_keys: ["aa:0"] };
          aktualisiereFifoSpend("w1"); await warte();
          const nachher = els["#fifo-spend-text"].textContent;
          const titel = els["#fifo-spend-text"].title;
          const max = els["#fifo-spend-betrag"].max;
          Zustand.config.steuer.anschaffung = "aelteste";
          aktualisiereFifoSpend(); await warte();
          process.stdout.write(JSON.stringify({
            vorher, nachher, titel, max, n: aufrufe.length,
            offensiv: els["#fifo-spend-text"].textContent,
            titelOff: els["#fifo-spend-text"].title,
          }));
        """)
        self.assertEqual(erg["vorher"], f"defensiv max 0,00{NB}050{NB}000 BTC grün ausgebbar")
        self.assertEqual(erg["nachher"], f"defensiv max 0,00{NB}000{NB}000 BTC grün ausgebbar")
        self.assertEqual(erg["max"], "0")
        self.assertIn(f"1 UTXO(s) im Mempool – 0,00{NB}050{NB}000 BTC grün abgezogen.", erg["titel"])
        # Abzug rechnet lokal; nur der Lesart-Wechsel holt neu.
        self.assertEqual(erg["n"], 2)
        self.assertEqual(erg["offensiv"], f"offensiv max 0,00{NB}024{NB}000 BTC grün ausgebbar")
        self.assertIn(f"0,00{NB}050{NB}000 BTC grün abgezogen", erg["titelOff"])

    def test_mempool_unvollstaendig_zeigt_strich(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          // Älterer Server ohne pending_spending_keys, Ausgabe nicht auf dieser Seite.
          Zustand._walletUtxoDaten = { total_count: 5, pending_spending_count: 1, utxos: [] };
          aktualisiereFifoSpend("w1"); await warte();
          process.stdout.write(JSON.stringify({
            text: els["#fifo-spend-text"].textContent,
            titel: els["#fifo-spend-text"].title,
            gesperrt: els["#fifo-spend-betrag"].disabled,
          }));
        """)
        self.assertEqual(erg["text"], "defensiv max — grün ausgebbar")
        self.assertEqual(erg["titel"], "Mempool-Stand unvollständig")
        self.assertTrue(erg["gesperrt"])

    def test_satcomma_de_en_null_staub_gross(self):
        erg = _node(r"""
          const f = formatSatcomma;
          process.stdout.write(JSON.stringify({
            null_de: f(0, "de"), staub: f(546, "de"), eins: f(1, "en"),
            kl_de: f(12500, "de"), mittel_de: f(2345678, "de"), mittel_en: f(2345678, "en"),
            ein_btc: f(100000000, "de"), gross_de: f(123456789012345, "de"),
            gross_en: f(123456789012345, "en-US"), auto: f(2345678),
            ungerade: f(-5, "de"), krumm: f(12.6, "de"),
          }));
        """)
        self.assertEqual(erg["null_de"], f"0,00{NB}000{NB}000 BTC")
        self.assertEqual(erg["staub"], f"0,00{NB}000{NB}546 BTC")
        self.assertEqual(erg["eins"], f"0.00{NB}000{NB}001 BTC")
        self.assertEqual(erg["kl_de"], f"0,00{NB}012{NB}500 BTC")
        self.assertEqual(erg["mittel_de"], f"0,02{NB}345{NB}678 BTC")
        self.assertEqual(erg["mittel_en"], f"0.02{NB}345{NB}678 BTC")
        self.assertEqual(erg["ein_btc"], f"1,00{NB}000{NB}000 BTC")
        self.assertEqual(erg["gross_de"], f"1{NB}234{NB}567,89{NB}012{NB}345 BTC")
        self.assertEqual(erg["gross_en"], f"1{NB}234{NB}567.89{NB}012{NB}345 BTC")
        self.assertEqual(erg["auto"], f"0,02{NB}345{NB}678 BTC")  # uiSprache() = de
        self.assertEqual(erg["ungerade"], f"0,00{NB}000{NB}000 BTC")
        self.assertEqual(erg["krumm"], f"0,00{NB}000{NB}013 BTC")

    def test_satcomma_nur_in_der_fifo_zeile(self):
        """Die globale App-Formatierung bleibt unverändert."""
        self.assertNotIn("formatSatcomma", FORMAT)
        self.assertIn("function formatSatsBasis(", FORMAT)

    def test_feld_tooltip_nennt_exakte_grenze_in_sats(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: [
            { key: "zz:0", wallet_id: "w1", value_sats: 113815319, sats_gruen: 113815319, sats_orange: 0, sats_grau: 0 },
          ] } };
          aktualisiereFifoSpend("w1"); await warte();
          const feld = els["#fifo-spend-betrag"];
          feld.value = "113815319"; pruefeFifoSpendBetrag();
          const ok = !feld.classList.contains("ungueltig");
          const titel = feld.title;
          feld.value = "114000000"; pruefeFifoSpendBetrag();
          process.stdout.write(JSON.stringify({
            text: els["#fifo-spend-text"].textContent, max: feld.max, ok, titel,
            rot: feld.classList.contains("ungueltig"),
          }));
        """)
        self.assertEqual(erg["text"], f"defensiv max 1,13{NB}815{NB}319 BTC grün ausgebbar")
        self.assertEqual(erg["max"], "113815319")
        self.assertTrue(erg["ok"])
        self.assertEqual(erg["titel"], f"Betrag in sats, ganze Zahl von 1 bis 113.815.319 sats (= 1,13{NB}815{NB}319 BTC).")
        # Über dem exakten Höchstbetrag: rot.
        self.assertTrue(erg["rot"])

    def test_walletwechsel_leert_betrag_und_rechnet_neu(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();
          els["#fifo-spend-betrag"].value = "40000";
          Zustand.walletId = "w2"; Zustand.walletLadeGen = 2;
          aktualisiereFifoSpend("w2");
          const sofort = els["#fifo-spend-betrag"].value;
          await warte();
          process.stdout.write(JSON.stringify({
            sofort, text: els["#fifo-spend-text"].textContent,
          }));
        """)
        self.assertEqual(erg["sofort"], "")
        self.assertEqual(erg["text"], f"defensiv max 0,01{NB}000{NB}000 BTC grün ausgebbar")

    def test_daten_nachladen_holt_neu(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();
          antwort = { zeitstrahl: { events: [
            { wallet_id: "w1", value_sats: 80000, sats_gruen: 80000, sats_orange: 0, sats_grau: 0 },
          ] } };
          Zustand.walletLadeGen += 1;  // zeigeWallet nach Scan/Herkunft
          aktualisiereFifoSpend("w1"); await warte();
          process.stdout.write(JSON.stringify({ text: els["#fifo-spend-text"].textContent }));
        """)
        self.assertEqual(erg["text"], f"defensiv max 0,00{NB}080{NB}000 BTC grün ausgebbar")

    def test_ohne_bestand_leiste_weg(self):
        erg = _node(r"""
          els["#fifo-spend"].hidden = false;
          aktualisiereFifoSpend(null);
          process.stdout.write(JSON.stringify({ hidden: els["#fifo-spend"].hidden, n: aufrufe.length }));
        """)
        self.assertTrue(erg["hidden"])
        self.assertEqual(erg["n"], 0)

    def test_fehler_zeigt_strich_und_sperrt_feld(self):
        erg = _node(r"""
          api = async () => { throw new Error("kaputt"); };
          aktualisiereFifoSpend("w1"); await warte();
          process.stdout.write(JSON.stringify({
            text: els["#fifo-spend-text"].textContent,
            titel: els["#fifo-spend-text"].title,
            gesperrt: els["#fifo-spend-betrag"].disabled,
          }));
        """)
        self.assertEqual(erg["text"], "defensiv max — grün ausgebbar")
        self.assertIn("kaputt", erg["titel"])
        self.assertTrue(erg["gesperrt"])

    def test_waehrend_des_starts_keine_anfrage(self):
        erg = _node(r"""
          Zustand.contextBereit = false;
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();
          const waehrend = aufrufe.length;
          const text = els["#fifo-spend-text"].textContent;
          Zustand.contextBereit = true;
          aktualisiereFifoSpend("w1"); await warte();  // holeWalletMempoolNachStart
          process.stdout.write(JSON.stringify({
            waehrend, text, danach: els["#fifo-spend-text"].textContent,
          }));
        """)
        self.assertEqual(erg["waehrend"], 0)
        self.assertEqual(erg["text"], "defensiv max … grün ausgebbar")
        self.assertEqual(erg["danach"], f"defensiv max 0,00{NB}050{NB}000 BTC grün ausgebbar")

    def test_ausserhalb_der_wallet_ansicht_kein_abruf(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();
          Zustand.ansicht = "einstellungen";
          Zustand.config.steuer.anschaffung = "aelteste";
          aktualisiereFifoSpend(); await warte();
          process.stdout.write(JSON.stringify({ n: aufrufe.length }));
        """)
        self.assertEqual(erg["n"], 1)

    def test_eingabe_ueber_max_und_unsinn_markiert(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();
          const feld = els["#fifo-spend-betrag"];
          const probe = (v) => { feld.value = v; pruefeFifoSpendBetrag();
            return feld.classList.contains("ungueltig"); };
          process.stdout.write(JSON.stringify({
            leer: probe(""), ok: probe("50000"), drueber: probe("50001"),
            null_: probe("0"), komma: probe("1.5"), minus: probe("-3"),
            aria: (probe("99999999"), feld.getAttribute("aria-invalid")),
          }));
        """)
        self.assertFalse(erg["leer"])
        self.assertFalse(erg["ok"])
        self.assertTrue(erg["drueber"])
        self.assertTrue(erg["null_"])
        self.assertTrue(erg["komma"])
        self.assertTrue(erg["minus"])
        self.assertEqual(erg["aria"], "true")

    def test_abfrage_teilt_server_cache_mit_steuerjahr(self):
        """Gleiche jahr/frist/stichtag-Parameter wie ladeSteuerjahr, kein anschaffung=."""
        erg = _node(r"""
          Zustand.config.steuer.stichtag = "28.02.2021";
          process.stdout.write(JSON.stringify({ q: fifoSpendAbfrage() }));
        """)
        q = erg["q"]
        self.assertRegex(q, r"^\?jahr=\d{4}&frist=1&stichtag=28\.02\.2021&")
        self.assertNotIn("anschaffung", q)
        self.assertIn("jahr=${encodeURIComponent(jahr)}&frist=${encodeURIComponent(frist)}", STEUER)
        self.assertIn("&stichtag=${encodeURIComponent(stichtag)}", STEUER)


class TestFifoStatisch(unittest.TestCase):

    SCHLUESSEL = (
        "wallet.utxoCount",
        "wallet.fifoSpendAria",
        "wallet.fifoSpendDefensive",
        "wallet.fifoSpendOffensive",
        "wallet.fifoSpendTitleDefensive",
        "wallet.fifoSpendTitleOffensive",
        "wallet.fifoSpendTitleBasis",
        "wallet.fifoSpendTitleExact",
        "wallet.fifoSpendTitleMempool",
        "wallet.fifoSpendMempoolIncompleteTitle",
        "wallet.fifoSpendTitleUnchecked",
        "wallet.fifoSpendLoadingTitle",
        "wallet.fifoSpendWaitStartTitle",
        "wallet.fifoSpendUnavailableTitle",
        "wallet.fifoSpendAmountPlaceholder",
        "wallet.fifoSpendAmountTitle",
        "wallet.fifoSpendAmountInvalid",
        "wallet.fifoSpendPsbt",
        "wallet.fifoSpendPsbtTitle",
    )

    def test_kataloge_de_en(self):
        de, en = _katalog("de"), _katalog("en")
        for k in self.SCHLUESSEL:
            self.assertTrue(str(de.get(k, "")).strip(), f"de fehlt {k}")
            self.assertTrue(str(en.get(k, "")).strip(), f"en fehlt {k}")
        self.assertEqual(de["wallet.utxoCount"], "{count} UTXOs")
        self.assertEqual(en["wallet.utxoCount"], "{count} UTXOs")
        self.assertEqual(de["wallet.fifoSpendDefensive"], "defensiv max {n} grün ausgebbar")
        self.assertEqual(de["wallet.fifoSpendOffensive"], "offensiv max {n} grün ausgebbar")
        self.assertEqual(en["wallet.fifoSpendDefensive"], "defensive: max {n} green spendable")
        self.assertEqual(en["wallet.fifoSpendOffensive"], "offensive: max {n} green spendable")
        self.assertEqual(de["wallet.fifoSpendPsbtTitle"], "PSBT-Erzeugung folgt")
        # Platzhalter in beiden Sprachen gleich.
        for k in self.SCHLUESSEL:
            self.assertEqual(
                sorted(re.findall(r"\{(\w+)\}", de[k])),
                sorted(re.findall(r"\{(\w+)\}", en[k])), k,
            )

    def test_alte_kopfzeile_weg(self):
        de = _katalog("de")
        self.assertNotIn("wallet.addressCountWithBalance", de)
        self.assertNotIn("addressCountWithBalance", WALLETS)
        # Zahl = UTXOs (total_count), nicht Adressen (adressen_count).
        kopf = WALLETS[WALLETS.index('$("#adress-zusatz")'):][:400]
        self.assertIn("wallet.utxoCount", kopf)
        self.assertIn("daten.total_count", kopf)
        self.assertNotIn("adressen_count", kopf)

    def test_js_schluessel_im_katalog(self):
        de, en = _katalog("de"), _katalog("en")
        benutzt = set(re.findall(r'\bt\(\s*"(wallet\.(?:fifoSpend\w*|utxoCount))"', WALLETS))
        self.assertTrue(benutzt)
        for k in benutzt:
            self.assertIn(k, de)
            self.assertIn(k, en)

    def test_html_leiste_im_kopf_mit_feld_und_gesperrtem_psbt(self):
        kopf_start = HTML.index('id="adress-zusatz"')
        kopf = HTML[kopf_start:HTML.index('id="adress-koerper"')]
        self.assertIn('id="fifo-spend"', kopf)
        self.assertIn('id="fifo-spend-text"', kopf)
        feld = re.search(r'<input[^>]*id="fifo-spend-betrag"[^>]*>', kopf, re.S).group(0)
        self.assertIn('type="number"', feld)
        self.assertIn('min="1"', feld)
        self.assertIn('step="1"', feld)
        self.assertIn('data-i18n-placeholder="wallet.fifoSpendAmountPlaceholder"', feld)
        knopf = re.search(r'<button[^>]*id="fifo-spend-psbt"[^>]*>', kopf, re.S).group(0)
        self.assertIn("disabled", knopf)
        self.assertIn('data-i18n-title="wallet.fifoSpendPsbtTitle"', knopf)
        # Sortier-Info lebt im Sortierfeld weiter (sichtbarer Wert + Tooltip).
        self.assertIn('id="sort-wahl" data-i18n-title="wallet.sortTitle"', HTML)

    def test_kein_versand_kein_signieren(self):
        teil = WALLETS[WALLETS.index("/* --- wallet-fifo-spend --- */"):]
        teil = teil[:teil.index("Zeigt den Abgleich gegen die Sanktionslisten")]
        self.assertNotIn("methode:", teil)
        self.assertNotRegex(teil.lower(), r"sign|broadcast|sendraw")
        self.assertNotIn('addEventListener("click"', teil)

    def test_einstellungen_hook_und_css_theme(self):
        self.assertIn("aktualisiereFifoSpend()", EINST)
        self.assertIn(".fifo-spend-betrag.ungueltig", CSS)
        block = CSS[CSS.index(".fifo-spend {"):CSS.index("@media (max-width: 720px) {\n  .fifo-spend")]
        self.assertNotRegex(block, r"#[0-9A-Fa-f]{3,6}\b", "Farben nur über Theme-Variablen")


if __name__ == "__main__":
    unittest.main()
