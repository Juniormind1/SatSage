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
  "wallet.fifoSpendAmountTitle": "Betrag in BTC, mehr als 0 bis {max}.",
  "wallet.fifoSpendAmountSats": "= {sats} sats = {btc}",
  "wallet.fifoSpendUnitSats": "sats",
  "wallet.fifoSpendUnitBtc": "BTC",
  "wallet.fifoSpendPsbtOpen": "Senden \u25b8",
  "wallet.fifoSpendPsbtExpanded": "Senden \u25be",
  "wallet.fifoTargetMine": "Eigenes Wallet: „{wallet}“.",
  "wallet.fifoTargetExternal": "Gültige {netz}-Adresse, extern.",
  "wallet.fifoTargetExchange": "Bekannte Börsenadresse: „{exchange}“ ({netz}).",
  "wallet.fifoTargetSanctioned": "Steht auf einer Sanktionsliste: „{label}“.",
  "wallet.fifoTargetStatusSanctioned": "Sanktion",
  "wallet.fifoPsbtSanctionConfirm": "Willst Du wirklich an die sanktionierte Adresse {label} senden?",
  "wallet.fifoTargetWrongNetwork": "Adresse für {adressNetz} – SatSage läuft im {netz}.",
  "wallet.fifoTargetUnavailable": "Prüfung gerade nicht möglich: {msg}",
  "wallet.fifoTargetFeeSuggested": "Vorschlag {rate} sat/vB (Schätzung {schaetzung}, {vsize} vB, {inputs} Inputs, {fee} sats)",
  "wallet.fifoTargetFeeCapped": "Deckel: {rate} sat/vB wären {fee} sats bei {vsize} vB",
  "wallet.fifoTargetFeeFallback": "Fallback 1 sat/vB ({grund})",
  "wallet.fifoTargetFeeOwn": "Eigener Wert",
  "wallet.fifoTargetSelection": "Auswahl {inputs} Inputs, {gruen} grün, Wechselgeld {wechsel}",
  "wallet.fifoStrategyChange": "Wenig Wechselgeld",
  "wallet.fifoStrategyDust": "Staub aufräumen",
  "wallet.fifoTargetSelectionNoChange": "Auswahl {inputs} Inputs, {gruen} grün, ohne Wechselgeld",
  "wallet.fifoTargetSelectionDustFee": "Staub {staub} in die Gebühr",
  "wallet.fifoTargetSelectionDustKept": "Staub-Wechselgeld bleibt",
  "wallet.fifoTargetSelectionNonGreen": "Gemischt {n}: {sats} zurück",
  "wallet.fifoTargetSelectionGreedy": "Budget erschöpft",
  "wallet.fifoTargetSelectionShort": "Nicht gedeckt ({gruen})",
  "wallet.fifoTargetSelectionNone": "Keine Kandidaten",
  "wallet.fifoTargetSelectionCleanup": "Aufräumen {n} / {sats}",
  "wallet.fifoTargetSelectionCleanupLimited": "Aufräumen begrenzt",
  "wallet.fifoStrategyTitle": "Strategien",
  "wallet.fifoStrategySaveFailed": "Nicht gespeichert: {msg}",
  "wallet.fifoTargetStatusExternal": "extern",
  "wallet.fifoTargetStatusInvalid": "ungültig",
  "wallet.fifoTargetStatusWrongNetwork": "falsches Netz",
  "wallet.fifoTargetStatusChecking": "…",
  "wallet.fifoSpendAmountInvalidFormat": "Format ungültig, mehr als 0 bis {max}.",
  "wallet.fifoSpendAmountInvalidRange": "Bereich: mehr als 0 bis {max}.",
  "wallet.fifoSpendUnavailableTitle": "Grüne sats gerade nicht verfügbar: {msg}",
  "wallet.fifoPsbtSummary": "{datei}: {inputs} Input(s), Gebühr {fee} sats ({rate} sat/vB, {vsize} vB)",
  "wallet.fifoPsbtOutputTarget": "Ziel {betrag} → {adresse} ({farbe}) grün {gruen} / gelb {gelb}",
  "wallet.fifoPsbtOutputChange": "Wechselgeld {betrag} → {adresse} ({farbe}) grün {gruen} / gelb {gelb}",
  "wallet.fifoPsbtRbf": "RBF, nLockTime {locktime}",
  "wallet.fifoPsbtMultisigInfo": "Multisig {m}/{n}: {fps}",
  "wallet.fifoPsbtOverMax": "Über Maximum ({max})",
  "wallet.fifoPsbtFailed": "PSBT nicht erzeugt: {msg}",
};
const t = (k, v = {}) => (katalog[k] || k).replace(/\{(\w+)\}/g, (_, n) => String(v[n] ?? ""));
const formatZahl = (n) => Number(n || 0).toLocaleString("de-DE");
const formatLocale = () => "de-DE";
const formatSats = (n) => `${n} sats`;
let SPRACHE = "de";
const uiSprache = () => SPRACHE;
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
  "#fifo-spend-einheit": mkEl(),
  "#fifo-spend-psbt": mkEl(),
  "#fifo-spend-psbt-huelle": mkEl(),
  "#fifo-spend-ziel": mkEl(),
  "#fifo-ziel-adresse": mkEl(),
  "#fifo-ziel-status": mkEl(),
  "#fifo-ziel-strategie": mkEl(),
  "#fifo-ziel-fee": mkEl(),
  "#fifo-ziel-psbt": mkEl(),
  "#fifo-ziel-psbt-huelle": mkEl(),
  "#fifo-psbt-ergebnis": mkEl(),
  "#fifo-psbt-text": mkEl(),
  "#fifo-psbt-kopieren": mkEl(),
};
const downloads = [];
const document = {
  body: { appendChild() {} },
  createElement() {
    const a = { click() { downloads.push({ name: a.download, href: a.href }); }, remove() {} };
    return a;
  },
};
let kopiert = null;
async function kopiereInZwischenablage(text) { kopiert = text; return true; }
const psbtAufrufe = [];
let psbtAntwort = () => ({ status: "ok", wallet: "HS Alpha", psbt_base64: "cHNidP8BAA==",
  inputs: [{ key: "aa:0" }], outputs: [
    { rolle: "ziel", value_sats: 30000, adresse: "bcrt1qfremd", farbe: "gelb", sats_gruen: 30000, sats_gelb: 0 },
    { rolle: "wechsel", value_sats: 19718, adresse: "bcrt1qwechsel", farbe: "gruen", sats_gruen: 19718, sats_gelb: 0 },
  ], fee_sats: 282, sat_vb: 2, vsize: 141, locktime: 646, ohne_wechselgeld: false,
  herkunft: { quelle: "xpub" }, mempool_geprueft: true });
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
const adressAufrufe = [];
const feeAufrufe = [];
let feeAntwort = () => ({ status: "ok", quelle: "schaetzung", sat_vb: 4, schaetzung_sat_vb: 3.2, vsize: 141,
  anzahl_inputs: 1, outputs: 2, fee_sats: 564, wechselgeld_sats: 9436, ohne_wechselgeld: false, summe_gruen_sats: 50000 });
let adressAntwort = () => ({ status: "fremd", netz: "regtest" });
const configAufrufe = [];
let configFehler = null;
const nettoAufrufe = [];
// Standard: Server rechnet kein Netto-Maximum — die Zeile bleibt beim Brutto.
let nettoAntwort = () => { throw new Error("kein Netto"); };
async function api(pfad, opts = {}) {
  if (pfad === "/config/fifo-strategie") {
    configAufrufe.push({ methode: opts.methode, daten: opts.daten });
    if (configFehler) throw new Error(configFehler);
    return { saved: true, fifo_strategie: opts.daten.fifo_strategie };
  }
  if (pfad === "/psbt/auswahl") {
    if (opts.methode !== "POST") throw new Error("POST erwartet");
    const daten = JSON.parse(JSON.stringify(opts.daten));
    feeAufrufe.push(daten);
    return feeAntwort(daten);
  }
  if (pfad === "/psbt/erzeugen") {
    if (opts.methode !== "POST") throw new Error("POST erwartet");
    const daten = JSON.parse(JSON.stringify(opts.daten));
    psbtAufrufe.push(daten);
    return psbtAntwort(daten);
  }
  if (pfad === "/psbt/max") {
    if (opts.methode !== "POST") throw new Error("POST erwartet");
    const daten = JSON.parse(JSON.stringify(opts.daten));
    nettoAufrufe.push(daten);
    return nettoAntwort(daten);
  }
  if (pfad.startsWith("/address/owner?")) {
    const addr = new URLSearchParams(pfad.split("?")[1]).get("addr");
    adressAufrufe.push(addr);
    return adressAntwort(addr);
  }
  aufrufe.push(pfad);
  return JSON.parse(JSON.stringify(antwort));
}
const warte = () => new Promise((r) => setTimeout(r, 10));
const EV = [
  // w1: ganz grün
  { key: "aa:0", wallet_id: "w1", value_sats: 50000, sats_gruen: 50000, sats_orange: 0, sats_grau: 0 },
  // w1: gemischt grün/grau — nie Input (Grau), auch offensiv nicht
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
    "function fifoSpendBrutto(",
    "function fifoSpendMax(",
    "function fifoNettoSchluessel(",
    "function fifoNettoAktuell(",
    "function planeFifoNetto(",
    "function fifoGrueneSats(",
    "function fifoSpendAbfrage(",
    "function holeFifoSpendAuswertung(",
    "function aktualisiereFifoSpend(",
    "function zeichneFifoSpend(",
    "function fifoSatsGruppiert(",
    "function fifoBetragFeldText(",
    "function fifoBetragZuSats(",
    "function fifoBetragNeuSchreiben(",
    "function fifoSpendBetragPruefen(",
    "function fifoSpendBetragGueltig(",
    "function pruefeFifoSpendBetrag(",
    "function formatiereFifoSpendBetrag(",
    "function fifoNetzName(",
    "function fifoZielZeileOffen(",
    "function fifoZielZeigen(",
    "function aktualisiereFifoPsbtKnopf(",
    "function fifoZielUmschalten(",
    "function zeigeFifoZielAdresse(",
    "function pruefeFifoZielAdresse(",
    "function fifoFeeZuMilli(",
    "function pruefeFifoZielFee(",
    "function fifoStrategie(",
    "function fifoStrategieWechsel(",
    "function fifoAuswahlKoerper(",
    "function fifoAuswahlText(",
    "function fifoFeeVorschlagText(",
    "function planeFifoFeeVorschlag(",
    "function fifoZielAnteile(",
    "function fifoAuswahlAktuell(",
    "function fifoFeeEingabe(",
    "function fifoFeeVerlassen(",
    "function fifoAktuellesWallet(",
    "function fifoPsbtSperre(",
    "function fifoPsbtSchluessel(",
    "function aktualisiereFifoPsbtErzeugen(",
    "function fifoMilliText(",
    "function fifoPsbtKoerper(",
    "function fifoPsbtDateiname(",
    "function fifoPsbtHerunterladen(",
    "function fifoPsbtZusammenfassung(",
    "function fifoPsbtStatusText(",
    "function zeigeFifoPsbtErgebnis(",
    "function fifoPsbtErzeugen(",
    "function fifoPsbtKopieren(",
]


def _node(skript: str) -> dict:
    konst = [z for z in WALLETS.splitlines()
             if z.startswith(("const FIFO_SATCOMMA_LUECKE", "const FIFO_MAX_SATS",
                              "const FIFO_ZIEL_ENTPRELLEN_MS", "const FIFO_FEE_ENTPRELLEN_MS",
                              "const FIFO_STRATEGIEN", "const FIFO_NETTO_ENTPRELLEN_MS"))]
    teile = [_STUB, *konst] + [_funktion(WALLETS, k) for k in _FUNKTIONEN]
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
        # offensiv: 50000 + 4000 — auch der grüne Teil von cc:0 (grün/gelb
        # gemischt, Gelb geht ins Wechselgeld). bb:1 hat Grau → nie Input,
        # auch sein Grün zählt nicht; ohne Baum und Neuvermögen auch nicht.
        self.assertEqual(erg["offensiv"], 54000)
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
        self.assertEqual(m["offensiv"], 4000)   # grüner Teil von cc:0 (gemischt)
        # bb:1 (mit Grau) zählt nirgends, auch nicht im Abzug.
        self.assertEqual(m["abzug"], {"defensiv": 50000, "offensiv": 50000, "anzahl": 2})
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
          const max = els["#fifo-spend-betrag"].dataset.max;
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
        self.assertEqual(erg["offensiv"], f"offensiv max 0,00{NB}054{NB}000 BTC grün ausgebbar")  # bb:1 (Grau) nie
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
          const max = els["#fifo-spend-betrag"].dataset.max;
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
        # 54 000 − aa:0 (50 000).
        self.assertEqual(erg["offensiv"], f"offensiv max 0,00{NB}004{NB}000 BTC grün ausgebbar")
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

    def test_feld_tooltip_nennt_grenze_in_satcomma_und_sats(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: [
            { key: "zz:0", wallet_id: "w1", value_sats: 113815319, sats_gruen: 113815319, sats_orange: 0, sats_grau: 0 },
          ] } };
          aktualisiereFifoSpend("w1"); await warte();
          const feld = els["#fifo-spend-betrag"];
          feld.value = "1,13815319"; pruefeFifoSpendBetrag();
          const einheit = els["#fifo-spend-einheit"].textContent;
          const ok = !feld.classList.contains("ungueltig");
          const titel = feld.title, sats = Zustand.fifoSpendBetragSats;
          feld.value = "1.1381532"; pruefeFifoSpendBetrag();
          const rot = feld.classList.contains("ungueltig");
          process.stdout.write(JSON.stringify({
            text: els["#fifo-spend-text"].textContent, max: feld.dataset.max, ok, titel, sats,
            rot, titelRot: feld.title, satsRot: Zustand.fifoSpendBetragSats, einheit,
          }));
        """)
        self.assertEqual(erg["text"], f"defensiv max 1,13{NB}815{NB}319 BTC grün ausgebbar")
        self.assertEqual(erg["max"], "113815319")
        self.assertTrue(erg["ok"])
        self.assertEqual(erg["sats"], 113815319)
        self.assertEqual(erg["einheit"], "BTC")
        grenze = f"1,13{NB}815{NB}319 BTC (113{NB}815{NB}319 sats)"
        self.assertEqual(
            erg["titel"],
            f"Betrag in BTC, mehr als 0 bis {grenze}.\n= 113{NB}815{NB}319 sats = 1,13{NB}815{NB}319 BTC")
        # 1 sat über dem exakten Höchstbetrag: rot, kein Betrag für die PSBT.
        self.assertTrue(erg["rot"])
        self.assertEqual(erg["titelRot"], f"Bereich: mehr als 0 bis {grenze}.")
        self.assertIsNone(erg["satsRot"])

    def test_parser_sats_ohne_trenner_btc_mit_trenner(self):
        erg = _node(r"""
          const f = (v) => { const p = fifoBetragZuSats(v);
            return p.leer ? "leer" : (p.fehler ? `${p.einheit}:${p.fehler}` : `${p.einheit}:${p.sats}`); };
          process.stdout.write(JSON.stringify({
            sats: f("113749323"), tausend: f("1 000"), gruppiert: f("12\u202f345\u00a0678"),
            komma: f("1,01"), punkt: f("1.01"), staub: f("0,00000546"), staubP: f("0.00000546"),
            neun: f("1,123456789"), zwei: f("1.000,5"), zwei2: f("1,000.5"), drei: f("1.000.000"),
            ein_punkt: f("1.000"), vorne: f(".5"), hinten: f("3,"), nullen: f("00,1"), satsNull: f("0007"),
            satcomma: f(" 0,02\u202f345 678 "), btcEndung: f("0,02 345 678 BTC"), btcGanz: f("2 BTC"),
            satsEndung: f("12 345 678 sats"), satsTrenner: f("1,5 sats"),
            leer: f(""), nurLuecke: f(" \u202f "), trenner: f(","), minus: f("-1"), exp: f("1e3"),
            buchstabe: f("1,0a"), zuvielBtc: f("21000001,0"), grenzeBtc: f("21000000,0"),
            zuvielSats: f("2100000000000001"), grenzeSats: f("2100000000000000"),
          }));
        """)
        self.assertEqual(erg["sats"], "sats:113749323")
        self.assertEqual(erg["tausend"], "sats:1000")
        self.assertEqual(erg["gruppiert"], "sats:12345678")
        self.assertEqual(erg["komma"], "btc:101000000")
        self.assertEqual(erg["punkt"], "btc:101000000")
        self.assertEqual(erg["staub"], "btc:546")
        self.assertEqual(erg["staubP"], "btc:546")
        self.assertEqual(erg["neun"], "btc:format")      # 9 Nachkommastellen
        self.assertEqual(erg["zwei"], "btc:format")      # zwei Trenner
        self.assertEqual(erg["zwei2"], "btc:format")
        self.assertEqual(erg["drei"], "btc:format")
        self.assertEqual(erg["ein_punkt"], "btc:100000000")  # ein Trenner = Dezimalzeichen
        self.assertEqual(erg["vorne"], "btc:50000000")
        self.assertEqual(erg["hinten"], "btc:300000000")
        self.assertEqual(erg["nullen"], "btc:10000000")
        self.assertEqual(erg["satsNull"], "sats:7")
        self.assertEqual(erg["satcomma"], "btc:2345678")
        self.assertEqual(erg["btcEndung"], "btc:2345678")
        self.assertEqual(erg["btcGanz"], "btc:200000000")   # Einheit ausdrücklich
        self.assertEqual(erg["satsEndung"], "sats:12345678")
        self.assertEqual(erg["satsTrenner"], "sats:format")
        self.assertEqual(erg["leer"], "leer")
        self.assertEqual(erg["nurLuecke"], "leer")
        self.assertEqual(erg["trenner"], "btc:format")
        self.assertEqual(erg["minus"], "sats:format")
        self.assertEqual(erg["exp"], "sats:format")
        self.assertEqual(erg["buchstabe"], "btc:format")
        self.assertEqual(erg["zuvielBtc"], "btc:format")
        self.assertEqual(erg["grenzeBtc"], "btc:2100000000000000")
        self.assertEqual(erg["zuvielSats"], "sats:format")
        self.assertEqual(erg["grenzeSats"], "sats:2100000000000000")

    def test_parser_ohne_gleitkomma_fehler(self):
        """0,29 BTC ist exakt 29 000 000 sats (0.29 * 1e8 wäre 28 999 999,99…)."""
        erg = _node(r"""
          const werte = ["0,29", "0.57", "1,1", "20999999,99999999", "0,00000001"];
          process.stdout.write(JSON.stringify(werte.map((v) => fifoBetragZuSats(v).sats)));
        """)
        self.assertEqual(erg, [29000000, 57000000, 110000000, 2099999999999999, 1])

    def test_formatierte_ausgabe_wird_wieder_gelesen_beide_einheiten_de_en(self):
        erg = _node(r"""
          const aus = {};
          for (const lang of ["de", "en"]) {
            for (const einheit of ["sats", "btc"]) {
              for (const sats of [1, 546, 1000, 101000000, 113749323, 2100000000000000]) {
                const text = fifoBetragFeldText(sats, einheit, lang);
                const p = fifoBetragZuSats(text);
                aus[`${lang}:${einheit}:${sats}`] = { text, sats: p.sats, einheit: p.einheit };
              }
            }
          }
          process.stdout.write(JSON.stringify(aus));
        """)
        self.assertEqual(erg["de:sats:113749323"]["text"], f"113{NB}749{NB}323")
        self.assertEqual(erg["en:sats:1000"]["text"], f"1{NB}000")
        self.assertEqual(erg["de:btc:101000000"]["text"], f"1,01{NB}000{NB}000")
        self.assertEqual(erg["en:btc:101000000"]["text"], f"1.01{NB}000{NB}000")
        self.assertEqual(erg["de:btc:546"]["text"], f"0,00{NB}000{NB}546")
        self.assertEqual(erg["en:btc:2100000000000000"]["text"], f"21{NB}000{NB}000.00{NB}000{NB}000")
        for k, v in erg.items():
            _, einheit, sats = k.split(":")
            self.assertNotIn("BTC", v["text"], k)
            self.assertNotIn(".", v["text"] if einheit == "sats" else "", k)
            self.assertEqual(v["sats"], int(sats), k)
            self.assertEqual(v["einheit"], einheit, k)

    def test_verlassen_formatiert_in_erkannter_einheit(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          Zustand.walletId = "w2";
          aktualisiereFifoSpend("w2"); await warte();   // max 1 000 000 sats
          const feld = els["#fifo-spend-betrag"], einheit = els["#fifo-spend-einheit"];
          const aus = {};
          feld.value = "1,01"; pruefeFifoSpendBetrag(); aus.liveBtc = einheit.textContent;
          feld.value = "1 000"; pruefeFifoSpendBetrag(); aus.liveSats = einheit.textContent;
          feld.value = ""; pruefeFifoSpendBetrag(); aus.liveLeer = einheit.textContent;
          feld.value = "0.0101"; formatiereFifoSpendBetrag();
          aus.btcDrueber = feld.value; aus.btcDrueberSats = Zustand.fifoSpendBetragSats ?? null;
          aus.btcDrueberRot = feld.classList.contains("ungueltig");
          feld.value = "0,0099"; formatiereFifoSpendBetrag();
          aus.btc = feld.value; aus.btcSats = Zustand.fifoSpendBetragSats; aus.btcDs = feld.dataset.sats;
          feld.value = "990000"; formatiereFifoSpendBetrag();
          aus.sats = feld.value; aus.satsSats = Zustand.fifoSpendBetragSats; aus.satsEinheit = einheit.textContent;
          formatiereFifoSpendBetrag(); aus.satsZweimal = feld.value;
          feld.value = "1.000,5"; formatiereFifoSpendBetrag();
          aus.kaputt = feld.value; aus.kaputtRot = feld.classList.contains("ungueltig");
          feld.value = "0,005"; formatiereFifoSpendBetrag();
          SPRACHE = "en";
          aktualisiereFifoSpend();   // Sprachwechsel zeichnet neu
          aus.en = feld.value; aus.enSats = Zustand.fifoSpendBetragSats;
          feld.value = "500000"; formatiereFifoSpendBetrag(); aktualisiereFifoSpend();
          aus.enSatsText = feld.value;
          process.stdout.write(JSON.stringify(aus));
        """)
        self.assertEqual(erg["liveBtc"], "BTC")
        self.assertEqual(erg["liveSats"], "sats")
        self.assertEqual(erg["liveLeer"], "")
        # 1 010 000 sats > max 1 000 000: formatiert, aber rot und ohne Betrag.
        self.assertEqual(erg["btcDrueber"], f"0,01{NB}010{NB}000")
        self.assertIsNone(erg["btcDrueberSats"])
        self.assertTrue(erg["btcDrueberRot"])
        self.assertEqual(erg["btc"], f"0,00{NB}990{NB}000")
        self.assertEqual(erg["btcSats"], 990000)
        self.assertEqual(erg["btcDs"], "990000")
        self.assertEqual(erg["sats"], f"990{NB}000")
        self.assertEqual(erg["satsSats"], 990000)
        self.assertEqual(erg["satsEinheit"], "sats")
        self.assertEqual(erg["satsZweimal"], f"990{NB}000")
        self.assertEqual(erg["kaputt"], "1.000,5")  # ungültig bleibt stehen
        self.assertTrue(erg["kaputtRot"])
        self.assertEqual(erg["en"], f"0.00{NB}500{NB}000")
        self.assertEqual(erg["enSats"], 500000)
        self.assertEqual(erg["enSatsText"], f"500{NB}000")

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
          aktualisiereFifoSpend("w1"); await warte();   // max 50 000 sats
          const feld = els["#fifo-spend-betrag"];
          const probe = (v) => { feld.value = v; pruefeFifoSpendBetrag();
            return feld.classList.contains("ungueltig"); };
          process.stdout.write(JSON.stringify({
            leer: probe(""), ok: probe("0,0005"), okP: probe("0.0005"), drueber: probe("0,00050001"),
            null_: probe("0"), null2: probe("0,00000000"), neun: probe("0,000000001"),
            tausend: probe("1.000,5"), minus: probe("-0,0001"), sats: probe("50000"),
            satsDrueber: probe("50 001"), satsKomma: probe("50000 sats,"),
            aria: (probe("1,123456789"), feld.getAttribute("aria-invalid")),
            titel: feld.title,
          }));
        """)
        self.assertFalse(erg["leer"])
        self.assertFalse(erg["ok"])
        self.assertFalse(erg["okP"])
        self.assertTrue(erg["drueber"])
        self.assertTrue(erg["null_"])
        self.assertTrue(erg["null2"])
        self.assertTrue(erg["neun"])
        self.assertTrue(erg["tausend"])
        self.assertTrue(erg["minus"])
        self.assertFalse(erg["sats"])        # ohne Trenner = sats, genau max
        self.assertTrue(erg["satsDrueber"])
        self.assertTrue(erg["satsKomma"])
        self.assertEqual(erg["aria"], "true")
        self.assertEqual(
            erg["titel"], f"Format ungültig, mehr als 0 bis 0,00{NB}050{NB}000 BTC (50{NB}000 sats).")

    def test_unvollstaendiger_mempool_sperrt_feld(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          Zustand._walletUtxoDaten = { pending_spending_count: 2, pending_spending_keys: undefined, utxos: [] };
          aktualisiereFifoSpend("w1"); await warte();
          const feld = els["#fifo-spend-betrag"];
          process.stdout.write(JSON.stringify({ gesperrt: feld.disabled, max: feld.dataset.max ?? null }));
        """)
        self.assertTrue(erg["gesperrt"])
        self.assertIsNone(erg["max"])

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


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestFifoNettoMax(unittest.TestCase):
    """Kopfzeile und Betragsprüfung nehmen das Netto-Maximum (Gebühr abgezogen)."""

    def test_netto_ersetzt_brutto_und_plus_eins_ist_ungueltig(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          nettoAntwort = (d) => ({ status: "max", max_netto_sats: 49718, max_netto_fee_sats: 282,
            max_netto_inputs: 1, sat_vb: 2, max_sats: 50000 });
          aktualisiereFifoSpend("w1"); await warte();
          const vorher = els["#fifo-spend-betrag"].dataset.max;
          await new Promise((r) => setTimeout(r, FIFO_NETTO_ENTPRELLEN_MS + 30));
          const feld = els["#fifo-spend-betrag"];
          const probe = (v) => { feld.value = v; pruefeFifoSpendBetrag();
            return feld.classList.contains("ungueltig"); };
          process.stdout.write(JSON.stringify({
            vorher, nachher: feld.dataset.max, aufrufe: nettoAufrufe,
            text: els["#fifo-spend-text"].textContent, titel: els["#fifo-spend-text"].title,
            genau: probe("49718"), plusEins: probe("49719"),
          }));
        """)
        self.assertEqual(erg["vorher"], "50000")       # Brutto, solange der Server rechnet
        self.assertEqual(erg["nachher"], "49718")      # Netto
        self.assertEqual(erg["aufrufe"], [{"wallet_id": "w1"}])  # ohne Gebühr: Server-Schätzung
        self.assertIn(f"49{NB}718", erg["text"])
        self.assertFalse(erg["genau"])
        self.assertTrue(erg["plusEins"])

    def test_gebuehr_aendert_netto(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          nettoAntwort = (d) => {
            const rate = d.fee ? Number(d.fee) : 1;
            return { status: "max", max_netto_sats: 50000 - 110 * rate, max_netto_fee_sats: 110 * rate,
              max_netto_inputs: 1, sat_vb: rate };
          };
          aktualisiereFifoSpend("w1"); await warte();
          await new Promise((r) => setTimeout(r, FIFO_NETTO_ENTPRELLEN_MS + 30));
          const eins = els["#fifo-spend-betrag"].dataset.max;
          const fee = els["#fifo-ziel-fee"];
          fee.value = "5"; pruefeFifoZielFee();
          await new Promise((r) => setTimeout(r, FIFO_NETTO_ENTPRELLEN_MS + 30));
          process.stdout.write(JSON.stringify({ eins, fuenf: els["#fifo-spend-betrag"].dataset.max,
            letzte: nettoAufrufe[nettoAufrufe.length - 1] }));
        """)
        self.assertEqual(erg["eins"], "49890")
        self.assertEqual(erg["fuenf"], "49450")
        self.assertEqual(erg["letzte"], {"wallet_id": "w1", "fee": "5"})

    def test_server_fehler_bleibt_brutto(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();
          await new Promise((r) => setTimeout(r, FIFO_NETTO_ENTPRELLEN_MS + 30));
          process.stdout.write(JSON.stringify({ max: els["#fifo-spend-betrag"].dataset.max,
            titel: els["#fifo-spend-text"].title }));
        """)
        self.assertEqual(erg["max"], "50000")
        self.assertIn("wallet.fifoSpendTitleGross", erg["titel"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestFifoZielZeile(unittest.TestCase):

    def test_psbt_frage_nur_mit_gueltigem_betrag_und_klappt_auf(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();   // max 50 000 sats
          const feld = els["#fifo-spend-betrag"], knopf = els["#fifo-spend-psbt"];
          const zeile = els["#fifo-spend-ziel"];
          const aus = { leer: knopf.disabled, leerTitel: knopf.title };
          feld.value = "50001"; pruefeFifoSpendBetrag(); aus.drueber = knopf.disabled;
          feld.value = "40 000"; pruefeFifoSpendBetrag(); aus.gueltig = knopf.disabled;
          aus.textZu = knopf.textContent;
          fifoZielUmschalten();
          aus.offen = !zeile.hidden; aus.expanded = knopf.getAttribute("aria-expanded");
          aus.textAuf = knopf.textContent;
          aus.offenTitel = knopf.title;
          feld.value = "1.000,5"; pruefeFifoSpendBetrag();
          aus.zuNachUngueltig = zeile.hidden; aus.wiederAus = knopf.disabled;
          feld.value = "0,0004"; pruefeFifoSpendBetrag(); fifoZielUmschalten();
          aus.wiederOffen = !zeile.hidden;
          fifoZielUmschalten(); aus.zuPerKnopf = zeile.hidden;
          aus.textWiederZu = knopf.textContent; aus.expandedZu = knopf.getAttribute("aria-expanded");
          aktualisiereFifoSpend(null); aus.ohneWalletZu = zeile.hidden;
          process.stdout.write(JSON.stringify(aus));
        """)
        self.assertTrue(erg["leer"])
        self.assertEqual(erg["leerTitel"], "wallet.fifoSpendPsbtNeedsAmount")
        self.assertTrue(erg["drueber"])
        self.assertFalse(erg["gueltig"])
        self.assertTrue(erg["offen"])
        self.assertEqual(erg["expanded"], "true")
        self.assertEqual(erg["offenTitel"], "wallet.fifoSpendPsbtClose")
        self.assertTrue(erg["zuNachUngueltig"])
        self.assertTrue(erg["wiederAus"])
        self.assertTrue(erg["wiederOffen"])
        self.assertTrue(erg["zuPerKnopf"])
        self.assertEqual(erg["textZu"], "Senden \u25b8")
        self.assertEqual(erg["textAuf"], "Senden \u25be")
        self.assertEqual(erg["textWiederZu"], "Senden \u25b8")
        self.assertEqual(erg["expandedZu"], "false")
        self.assertTrue(erg["ohneWalletZu"])

    def test_adresse_entprellt_und_farben(self):
        erg = _node(r"""
          const feld = els["#fifo-ziel-adresse"];
          const antworten = {
            "bcrt1qeigen": { status: "meine", wallet: "HS Beta", netz: "regtest" },
            "bcrt1qfremd": { status: "fremd", netz: "regtest" },
            "bcrt1qkraken": { status: "fremd", netz: "regtest", exchange: "Kraken" },
            "bcrt1qofac": { status: "sanktioniert", netz: "regtest", sanction: "Beispiel Person" },
            "bc1qmain": { status: "falsches_netz", netz: "regtest", adress_netze: ["main"] },
            "kaputt": { status: "ungueltig", netz: "regtest" },
          };
          adressAntwort = (a) => antworten[a];
          const tippe = async (v, ms = 400) => { feld.value = v; pruefeFifoZielAdresse(); await new Promise((r) => setTimeout(r, ms)); };
          const aus = {};
          // Schnell tippen: nur die letzte Eingabe geht an den Server.
          for (const v of ["b", "bc", "bcrt1", "bcrt1qeig"]) await tippe(v, 20);
          aus.waehrend = feld.dataset.zustand;
          await tippe("bcrt1qeigen");
          aus.anfragen = adressAufrufe.slice();
          const marke = els["#fifo-ziel-status"];
          const lab = () => [marke.textContent, marke.dataset.zustand];
          aus.gruen = feld.dataset.zustand; aus.gruenTitel = feld.title; aus.gruenLabel = lab();
          await tippe("bcrt1qfremd"); aus.gelb = feld.dataset.zustand; aus.gelbTitel = feld.title; aus.gelbLabel = lab();
          await tippe("bcrt1qkraken"); aus.boerse = feld.dataset.zustand; aus.boerseTitel = feld.title; aus.boerseLabel = lab();
          await tippe("bcrt1qofac"); aus.sanktion = feld.dataset.zustand; aus.sanktionTitel = feld.title; aus.sanktionLabel = lab();
          aus.sanktionAria = feld.getAttribute("aria-invalid");
          await tippe("bc1qmain"); aus.netz = feld.dataset.zustand; aus.netzTitel = feld.title; aus.netzLabel = lab();
          aus.netzAria = feld.getAttribute("aria-invalid");
          await tippe("kaputt"); aus.rot = feld.dataset.zustand; aus.rotLabel = lab();
          feld.value = "bcrt1qneu"; pruefeFifoZielAdresse(); aus.pruefeLabel = lab();
          await tippe(""); aus.leer = feld.dataset.zustand; aus.leerAria = feld.getAttribute("aria-invalid");
          aus.leerLabel = lab(); aus.leerTitel = feld.title;
          aus.n = adressAufrufe.length;
          process.stdout.write(JSON.stringify(aus));
        """)
        self.assertEqual(erg["waehrend"], "pruefe")
        self.assertEqual(erg["anfragen"], ["bcrt1qeigen"])
        self.assertEqual(erg["gruen"], "gruen")
        self.assertIn("HS Beta", erg["gruenTitel"])
        self.assertEqual(erg["gelb"], "gelb")
        self.assertIn("Regtest", erg["gelbTitel"])
        self.assertEqual(erg["boerse"], "gelb")
        self.assertEqual(erg["boerseLabel"], ["Kraken", "gelb"])
        self.assertIn("Kraken", erg["boerseTitel"])
        self.assertEqual(erg["sanktion"], "rot")
        self.assertEqual(erg["sanktionLabel"], ["Beispiel Person", "rot"])
        self.assertIn("Beispiel Person", erg["sanktionTitel"])
        self.assertEqual(erg["sanktionAria"], "true")
        self.assertEqual(erg["netz"], "rot")
        self.assertIn("Mainnet", erg["netzTitel"])
        self.assertEqual(erg["netzAria"], "true")
        self.assertEqual(erg["rot"], "rot")
        self.assertEqual(erg["leer"], "")
        self.assertIsNone(erg["leerAria"])
        self.assertEqual(erg["n"], 6)   # leeres Feld fragt nicht; Börse und Sanktion zählen mit
        # Status-Label neben dem Feld; Tooltip beginnt mit der vollen Adresse.
        self.assertEqual(erg["gruenLabel"], ["HS Beta", "gruen"])
        self.assertEqual(erg["gelbLabel"], ["extern", "gelb"])
        self.assertEqual(erg["netzLabel"], ["falsches Netz", "rot"])
        self.assertEqual(erg["rotLabel"], ["ungültig", "rot"])
        self.assertEqual(erg["pruefeLabel"], ["…", "pruefe"])
        self.assertEqual(erg["leerLabel"], ["", ""])
        self.assertTrue(erg["gruenTitel"].startswith("bcrt1qeigen\n"))
        self.assertTrue(erg["netzTitel"].startswith("bc1qmain\n"))
        self.assertFalse(erg["leerTitel"].startswith("\n"))

    def test_spaete_antwort_wird_verworfen(self):
        erg = _node(r"""
          const feld = els["#fifo-ziel-adresse"];
          adressAntwort = (a) => new Promise((r) => setTimeout(() => r(
            a === "alt" ? { status: "meine", wallet: "Alt" } : { status: "fremd", netz: "regtest" }), a === "alt" ? 500 : 0));
          feld.value = "alt"; pruefeFifoZielAdresse();
          await new Promise((r) => setTimeout(r, 350));   // Anfrage „alt“ läuft
          feld.value = "neu"; pruefeFifoZielAdresse();
          await new Promise((r) => setTimeout(r, 700));
          process.stdout.write(JSON.stringify({ zustand: feld.dataset.zustand, titel: feld.title }));
        """)
        self.assertEqual(erg["zustand"], "gelb")
        self.assertNotIn("Alt", erg["titel"])

    def test_server_fehler_bleibt_neutral(self):
        erg = _node(r"""
          const feld = els["#fifo-ziel-adresse"];
          adressAntwort = () => { throw new Error("Wallets werden noch vorbereitet"); };
          feld.value = "bcrt1qx"; pruefeFifoZielAdresse();
          await new Promise((r) => setTimeout(r, 400));
          process.stdout.write(JSON.stringify({ zustand: feld.dataset.zustand, titel: feld.title }));
        """)
        self.assertEqual(erg["zustand"], "")
        self.assertIn("vorbereitet", erg["titel"])

    def test_gebuehr(self):
        erg = _node(r"""
          const f = fifoFeeZuMilli;
          const feld = els["#fifo-ziel-fee"];
          const rot = (v) => { feld.value = v; pruefeFifoZielFee(); return feld.classList.contains("ungueltig"); };
          process.stdout.write(JSON.stringify({
            eins: f("1"), komma: f("2,5"), punkt: f("2.5"), drei: f("0,125"), vier: f("0,1255"),
            null_: f("0"), zwei: f("1.000,5"), riesig: f("10001"), grenze: f("10000"), einheit: f("3 sat/vB"),
            leerRot: rot(""), okRot: rot("1,5"), kaputtRot: rot("abc"), milli: Zustand.fifoZielFeeMilli,
          }));
        """)
        self.assertEqual(erg["eins"], 1000)
        self.assertEqual(erg["komma"], 2500)
        self.assertEqual(erg["punkt"], 2500)
        self.assertEqual(erg["drei"], 125)
        self.assertIsNone(erg["vier"])
        self.assertIsNone(erg["null_"])
        self.assertIsNone(erg["zwei"])
        self.assertIsNone(erg["riesig"])
        self.assertEqual(erg["grenze"], 10000000)
        self.assertEqual(erg["einheit"], 3000)
        self.assertFalse(erg["leerRot"])
        self.assertFalse(erg["okRot"])
        self.assertTrue(erg["kaputtRot"])
        self.assertIsNone(erg["milli"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestFifoGebuehrVorschlag(unittest.TestCase):

    _OFFEN = r"""
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();   // defensiv max 50 000 sats
          const betrag = els["#fifo-spend-betrag"], fee = els["#fifo-ziel-fee"];
          const zeile = els["#fifo-spend-ziel"];
          const pause = (ms = 500) => new Promise((r) => setTimeout(r, ms));
          betrag.value = "40000"; pruefeFifoSpendBetrag();
          fifoZielUmschalten();
    """

    def test_vorbelegt_beim_aufklappen(self):
        erg = _node(self._OFFEN + r"""
          const vorher = feeAufrufe.length;
          await pause();
          process.stdout.write(JSON.stringify({
            vorher, aufrufe: feeAufrufe, wert: fee.value, titel: fee.title, vorschlag: fee.dataset.vorschlag,
          }));
        """)
        self.assertEqual(erg["vorher"], 0)            # entprellt
        self.assertEqual(len(erg["aufrufe"]), 1)
        koerper = erg["aufrufe"][0]
        self.assertEqual(koerper["betrag"], 40000)
        self.assertEqual(koerper["modus"], "defensiv")
        self.assertEqual(koerper["strategie"], "wechselgeld")   # Standard
        self.assertEqual(koerper["pending"], [])
        # Nur Punkte dieses Wallets, nur Beträge und Lot-Anteile.
        self.assertEqual([u["key"] for u in koerper["utxos"]], ["aa:0", "bb:1", "cc:0", "dd:0", "ee:0"])
        # (undefined fällt in JSON weg — EV hat kein txid/vout/time_ts.)
        self.assertLessEqual(set(koerper["utxos"][0]), {
            "key", "txid", "vout", "value_sats", "sats_gruen", "sats_orange", "sats_grau",
            "neuvermoegen", "time_ts"})
        self.assertEqual(koerper["utxos"][0]["value_sats"], 50000)
        self.assertEqual(erg["wert"], "4")
        self.assertEqual(erg["vorschlag"], "1")
        self.assertIn("Vorschlag 4 sat/vB (Schätzung 3,2, 141 vB, 1 Inputs, 564 sats)", erg["titel"])
        self.assertIn("Auswahl 1 Inputs, 50.000 grün, Wechselgeld 9.436", erg["titel"])

    def test_eigener_wert_wird_nicht_ueberschrieben(self):
        erg = _node(self._OFFEN + r"""
          await pause();
          fee.value = "7"; fifoFeeEingabe();
          feeAntwort = () => ({ status: "ok", quelle: "schaetzung", sat_vb: 9, schaetzung_sat_vb: 8.5, vsize: 141, anzahl_inputs: 1, fee_sats: 1269 });
          betrag.value = "45000"; pruefeFifoSpendBetrag();   // neuer Betrag → neuer Vorschlag
          await pause();
          const nachNeu = fee.value, titelNeu = fee.title, n = feeAufrufe.length;
          fee.value = ""; fifoFeeEingabe(); const leer = fee.value;
          fifoFeeVerlassen();
          process.stdout.write(JSON.stringify({ nachNeu, titelNeu, n, leer, danach: fee.value, vonHand: fee.dataset.vonHand }));
        """)
        self.assertEqual(erg["nachNeu"], "7")
        self.assertEqual(erg["n"], 2)
        self.assertIn("Eigener Wert", erg["titelNeu"])
        self.assertIn("Vorschlag 9 sat/vB", erg["titelNeu"])
        self.assertEqual(erg["leer"], "")              # Löschen geht
        self.assertEqual(erg["danach"], "9")          # beim Verlassen wieder der Vorschlag
        self.assertEqual(erg["vonHand"], "")

    def test_fallback_und_deckel_tooltip(self):
        erg = _node(r"""
          feeAntwort = () => ({ quelle: "fallback", sat_vb: 1, vsize: 141, anzahl_inputs: 1, fee_sats: 141,
                                grund: "Insufficient data or no feerate found" });
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();
          const betrag = els["#fifo-spend-betrag"], fee = els["#fifo-ziel-fee"];
          betrag.value = "40000"; pruefeFifoSpendBetrag(); fifoZielUmschalten();
          await new Promise((r) => setTimeout(r, 500));
          const fb = { wert: fee.value, titel: fee.title };
          const deckel = fifoFeeVorschlagText({ quelle: "deckel", sat_vb: 1, rate_ohne_deckel: 4, fee_ohne_deckel: 564, vsize: 141 });
          process.stdout.write(JSON.stringify({ fb, deckel }));
        """)
        self.assertEqual(erg["fb"]["wert"], "1")
        self.assertIn("Fallback 1 sat/vB (Insufficient data", erg["fb"]["titel"])
        self.assertEqual(erg["deckel"], "Deckel: 4 sat/vB wären 564 sats bei 141 vB")

    def test_ohne_gueltigen_betrag_kein_abruf(self):
        erg = _node(r"""
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();
          els["#fifo-spend-betrag"].value = "60000"; pruefeFifoSpendBetrag();  // > max
          planeFifoFeeVorschlag(); fifoZielUmschalten();
          await new Promise((r) => setTimeout(r, 500));
          process.stdout.write(JSON.stringify({ n: feeAufrufe.length, zu: els["#fifo-spend-ziel"].hidden }));
        """)
        self.assertEqual(erg["n"], 0)
        self.assertTrue(erg["zu"])

    def test_auswahl_koerper_mit_mempool_und_modus(self):
        erg = _node(r"""
          Zustand._walletUtxoDaten = { pending_spending_count: 1, pending_spending_keys: ["AA:0"] };
          const k = fifoAuswahlKoerper({ modus: "offensiv", walletId: "w1", events: EV }, 1234);
          process.stdout.write(JSON.stringify({
            betrag: k.betrag, modus: k.modus, pending: k.pending, keys: k.utxos.map((u) => u.key),
            def: fifoAuswahlKoerper({ modus: "x", walletId: "w1", events: EV }, 1).modus,
            wallet_id: k.wallet_id,
          }));
        """)
        self.assertEqual(erg["betrag"], 1234)
        self.assertEqual(erg["wallet_id"], "w1")        # nur für die vbytes (Multisig)
        self.assertEqual(erg["modus"], "offensiv")
        self.assertEqual(erg["pending"], ["aa:0"])
        self.assertNotIn("ff:0", erg["keys"])          # anderes Wallet
        self.assertEqual(erg["def"], "defensiv")

    def test_neuer_bestand_fragt_neu(self):
        erg = _node(TestFifoGebuehrVorschlag._OFFEN + r"""
          await pause();
          const n1 = feeAufrufe.length;
          planeFifoFeeVorschlag(); await pause();       // gleicher Stand → kein Abruf
          const n2 = feeAufrufe.length;
          Zustand._walletUtxoDaten = { pending_spending_count: 1, pending_spending_keys: ["aa:0"] };
          planeFifoFeeVorschlag(); await pause();       // Mempool geändert → neu
          process.stdout.write(JSON.stringify({ n1, n2, n3: feeAufrufe.length,
            pending: feeAufrufe[feeAufrufe.length - 1].pending }));
        """)
        self.assertEqual((erg["n1"], erg["n2"], erg["n3"]), (1, 1, 2))
        self.assertEqual(erg["pending"], ["aa:0"])

    def test_strategie_wechsel_speichert_und_fragt_neu(self):
        erg = _node(TestFifoGebuehrVorschlag._OFFEN + r"""
          await pause();
          const wahl = els["#fifo-ziel-strategie"];
          const vorher = wahl.value;
          wahl.value = "staub"; await fifoStrategieWechsel(); await pause();
          const n2 = feeAufrufe.length, letzte = feeAufrufe[n2 - 1].strategie;
          wahl.value = "unsinn"; await fifoStrategieWechsel(); await pause();
          configFehler = "kaputt";
          wahl.value = "gebuehr"; await fifoStrategieWechsel(); await pause();
          process.stdout.write(JSON.stringify({
            vorher, n2, letzte, config: configAufrufe, strategien: feeAufrufe.map((a) => a.strategie),
            gespeichert: Zustand.config.fifo_strategie, titel: wahl.title,
          }));
        """)
        self.assertEqual(erg["vorher"], "wechselgeld")   # beim Aufklappen gesetzt
        self.assertEqual(erg["n2"], 2)
        self.assertEqual(erg["letzte"], "staub")
        self.assertEqual(erg["config"], [
            {"methode": "PUT", "daten": {"fifo_strategie": "staub"}},
            {"methode": "PUT", "daten": {"fifo_strategie": "wechselgeld"}},
            {"methode": "PUT", "daten": {"fifo_strategie": "gebuehr"}},
        ])
        self.assertEqual(erg["strategien"], ["wechselgeld", "staub", "wechselgeld", "gebuehr"])
        self.assertEqual(erg["gespeichert"], "gebuehr")   # gilt lokal trotz Speicherfehler
        self.assertIn("kaputt", erg["titel"])

    def test_strategie_aus_konfiguration(self):
        erg = _node(r"""
          const a = fifoStrategie();
          Zustand.config.fifo_strategie = "aelteste"; const b = fifoStrategie();
          Zustand.config.fifo_strategie = "AELTESTE "; const c = fifoStrategie();
          Zustand.config.fifo_strategie = "x"; const d = fifoStrategie();
          process.stdout.write(JSON.stringify([a, b, c, d]));
        """)
        self.assertEqual(erg, ["wechselgeld", "aelteste", "aelteste", "wechselgeld"])

    def test_auswahl_tooltip_varianten(self):
        erg = _node(r"""
          const T = fifoAuswahlText;
          process.stdout.write(JSON.stringify({
            ohne: T({ status: "ok", anzahl_inputs: 2, summe_gruen_sats: 70000, ohne_wechselgeld: true,
                      staub_in_gebuehr_sats: 300, wechselgeld_sats: 0 }),
            bleibt: T({ status: "ok", anzahl_inputs: 1, summe_gruen_sats: 50000, ohne_wechselgeld: false,
                        wechselgeld_sats: 400, staub_wechselgeld: true, methode: "greedy" }),
            kurz: T({ status: "nicht_gedeckt", gruen_verfuegbar_sats: 70000 }),
            keine: T({ status: "keine_kandidaten" }),
            alt: T({ quelle: "schaetzung", sat_vb: 2 }),
            strat: (() => {
              katalog["wallet.fifoTargetSelection"] = "[{strategie}]";
              const r = [T({ status: "ok", strategie: "staub", anzahl_inputs: 1 })[0],
                         T({ status: "ok", strategie: "??", anzahl_inputs: 1 })[0]];
              katalog["wallet.fifoTargetSelection"] = "Auswahl {inputs} Inputs, {gruen} grün, Wechselgeld {wechsel}";
              return r;
            })(),
            gemischt: T({ status: "ok", anzahl_inputs: 2, summe_gruen_sats: 30000, wechselgeld_sats: 9000,
                          wechselgeld_nicht_gruen_sats: 6000, gemischte_inputs: 1 }),
            staub: T({ status: "ok", anzahl_inputs: 4, summe_gruen_sats: 80000, wechselgeld_sats: 9000,
                       aufraeumen_anzahl: 2, aufraeumen_sats: 13000, aufraeumen_begrenzt: true }),
          }));
        """)
        self.assertEqual(erg["ohne"], ["Auswahl 2 Inputs, 70.000 grün, ohne Wechselgeld",
                                       "Staub 300 in die Gebühr"])
        self.assertEqual(erg["bleibt"], ["Auswahl 1 Inputs, 50.000 grün, Wechselgeld 400",
                                         "Staub-Wechselgeld bleibt", "Budget erschöpft"])
        self.assertEqual(erg["kurz"], ["Nicht gedeckt (70.000)"])
        self.assertEqual(erg["keine"], ["Keine Kandidaten"])
        self.assertEqual(erg["alt"], [])
        self.assertEqual(erg["strat"], ["[Staub aufräumen]", "[Wenig Wechselgeld]"])
        self.assertEqual(erg["gemischt"], ["Auswahl 2 Inputs, 30.000 grün, Wechselgeld 9.000",
                                           "Gemischt 1: 6.000 zurück"])
        self.assertEqual(erg["staub"], ["Auswahl 4 Inputs, 80.000 grün, Wechselgeld 9.000",
                                        "Aufräumen 2 / 13.000", "Aufräumen begrenzt"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestFifoAuswahlListe(unittest.TestCase):

    def test_zielanteile_fuellen_aelteste_zuerst(self):
        erg = _node(r"""
          const inputs = [
            { key: "aa:0", sats_gruen: 50000 },
            { key: "bb:1", sats_gruen: 30000 },
            { key: "cc:2", sats_gruen: 20000 },
          ];
          process.stdout.write(JSON.stringify({
            teil: fifoZielAnteile(inputs, 60000).map((a) => a.ziel_sats),
            voll: fifoZielAnteile(inputs, 40000).map((a) => a.ziel_sats),
            leer: fifoZielAnteile(inputs, 0).map((a) => a.ziel_sats),
            staub: fifoZielAnteile(inputs, 100000).map((a) => a.ziel_sats),
          }));
        """)
        self.assertEqual(erg["teil"], [50000, 10000, 0])
        self.assertEqual(erg["voll"], [40000, 0, 0])
        self.assertEqual(erg["leer"], [0, 0, 0])
        self.assertEqual(erg["staub"], [50000, 30000, 20000])

    def test_zielzeile_offen_und_auswahl_aktuell(self):
        erg = _node(r"""
          const aus = { zu: fifoZielZeileOffen() };
          els["#fifo-spend-ziel"].hidden = false;
          aus.auf = fifoZielZeileOffen();
          Zustand.fifoSpendBetragSats = 40000;
          Zustand.fifoFeeLaedt = false;
          Zustand.fifoFeeVorschlag = { status: "ok", inputs: [{ key: "aa:0", sats_gruen: 50000 }] };
          aus.ok = Boolean(fifoAuswahlAktuell());
          Zustand.fifoFeeLaedt = true;
          aus.laedt = fifoAuswahlAktuell();
          Zustand.fifoFeeLaedt = false;
          Zustand.fifoFeeVorschlag = { status: "nicht_gedeckt", inputs: [] };
          aus.kurz = fifoAuswahlAktuell();
          els["#fifo-spend-ziel"].hidden = true;
          Zustand.fifoFeeVorschlag = { status: "ok", inputs: [{ key: "aa:0" }] };
          aus.zuWieder = Boolean(fifoAuswahlAktuell());
          process.stdout.write(JSON.stringify(aus));
        """)
        self.assertFalse(erg["zu"])
        self.assertTrue(erg["auf"])
        self.assertTrue(erg["ok"])
        self.assertIsNone(erg["laedt"])
        self.assertIsNone(erg["kurz"])
        self.assertFalse(erg["zuWieder"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestFifoPsbtErzeugen(unittest.TestCase):

    _BEREIT = r"""
          Zustand.config.wallets = [{ id: "w1", name: "HS Alpha", is_multisig: false },
                                    { id: "w2", name: "HS Multi", is_multisig: true }];
          antwort = { zeitstrahl: { events: EV } };
          aktualisiereFifoSpend("w1"); await warte();   // defensiv max 50 000 sats
          const betrag = els["#fifo-spend-betrag"], fee = els["#fifo-ziel-fee"];
          const adresse = els["#fifo-ziel-adresse"], psbt = els["#fifo-ziel-psbt"];
          const huelle = els["#fifo-ziel-psbt-huelle"], kasten = els["#fifo-psbt-ergebnis"];
          const pause = (ms = 500) => new Promise((r) => setTimeout(r, ms));
          adressAntwort = (a) => (a === "bcrt1qkaputt" ? { status: "ungueltig", netz: "regtest" }
            : a === "bcrt1qeigen" ? { status: "meine", wallet: "HS Beta", netz: "regtest" }
            : { status: "fremd", netz: "regtest" });
    """

    def test_freigabe_nur_mit_betrag_adresse_und_gebuehr(self):
        erg = _node(self._BEREIT + r"""
          const zustand = () => [psbt.disabled, psbt.title, huelle.title];
          const aus = { start: zustand() };
          betrag.value = "30000"; pruefeFifoSpendBetrag(); fifoZielUmschalten();
          aus.ohneAdresse = zustand();
          adresse.value = "bcrt1qkaputt"; pruefeFifoZielAdresse(); await pause();
          aus.rot = zustand();
          adresse.value = "bcrt1qfremd"; pruefeFifoZielAdresse(); await pause();
          aus.gelb = zustand();   // Gebühr kam als Vorschlag (4 sat/vB)
          fee.value = "abc"; fifoFeeEingabe(); aus.ohneFee = zustand();
          fee.value = "2,5"; fifoFeeEingabe(); aus.mitFee = zustand();
          adresse.value = "bcrt1qeigen"; pruefeFifoZielAdresse(); await pause();
          aus.gruen = zustand();
          betrag.value = "50001"; pruefeFifoSpendBetrag(); aus.ueberMax = psbt.disabled;
          betrag.value = "30000"; pruefeFifoSpendBetrag();
          Zustand.fifoSpend.walletId = "w2"; aktualisiereFifoPsbtErzeugen();
          aus.multisig = zustand();
          process.stdout.write(JSON.stringify(aus));
        """)
        self.assertTrue(erg["start"][0])
        self.assertEqual(erg["ohneAdresse"][:2], [True, "wallet.fifoPsbtNeedsAddress"])
        self.assertEqual(erg["rot"][:2], [True, "wallet.fifoPsbtNeedsAddress"])
        self.assertEqual(erg["gelb"][:2], [False, "wallet.fifoSpendPsbtTitle"])
        self.assertEqual(erg["ohneFee"][:2], [True, "wallet.fifoPsbtNeedsFee"])
        self.assertFalse(erg["mitFee"][0])
        self.assertFalse(erg["gruen"][0])
        self.assertTrue(erg["ueberMax"])
        # Multisig: frei wie Single-Sig (der Server baut wsh/sh-wsh sortedmulti).
        self.assertEqual(erg["multisig"], [False, "wallet.fifoSpendPsbtTitle", "wallet.fifoSpendPsbtTitle"])

    def test_klick_sendet_nur_wunsch_laedt_datei_und_zeigt_uebersicht(self):
        erg = _node(self._BEREIT + r"""
          betrag.value = "30000"; pruefeFifoSpendBetrag(); fifoZielUmschalten();
          adresse.value = "bcrt1qfremd"; pruefeFifoZielAdresse(); await pause();
          fee.value = "2,5"; fifoFeeEingabe();
          const laeuft = fifoPsbtErzeugen();
          const waehrend = { gesperrt: psbt.disabled, zustand: kasten.dataset.zustand, sichtbar: !kasten.hidden };
          await laeuft;
          const aus = { waehrend, aufrufe: psbtAufrufe, downloads, text: els["#fifo-psbt-text"].textContent,
            zustand: kasten.dataset.zustand, kopierenSichtbar: !els["#fifo-psbt-kopieren"].hidden,
            frei: !psbt.disabled };
          aus.kopiertOk = await fifoPsbtKopieren(); aus.kopiert = kopiert;
          aus.kopierText = els["#fifo-psbt-kopieren"].textContent;
          // Andere Gebühr → altes Ergebnis passt nicht mehr und verschwindet.
          fee.value = "3"; fifoFeeEingabe(); aus.nachAenderung = kasten.hidden;
          process.stdout.write(JSON.stringify(aus));
        """)
        self.assertTrue(erg["waehrend"]["gesperrt"])
        self.assertEqual(erg["waehrend"]["zustand"], "laedt")
        self.assertEqual(len(erg["aufrufe"]), 1)
        koerper = erg["aufrufe"][0]
        self.assertEqual(koerper, {"wallet_id": "w1", "betrag": 30000, "adresse": "bcrt1qfremd",
                                   "fee": "2.5", "strategie": "wechselgeld", "modus": "defensiv",
                                   "lang": koerper.get("lang")})
        self.assertNotIn("utxos", koerper)
        self.assertEqual(len(erg["downloads"]), 1)
        self.assertRegex(erg["downloads"][0]["name"], r"^HS-Alpha-\d{8}-\d{4}\.psbt$")
        self.assertTrue(erg["downloads"][0]["href"].startswith("blob:"))
        text = erg["text"]
        self.assertIn("1 Input(s), Gebühr 282 sats (2 sat/vB, 141 vB)", text)
        self.assertIn("Ziel 30.000 → bcrt1qfremd (extern) grün 30.000 / gelb 0", text)
        self.assertIn("Wechselgeld 19.718 → bcrt1qwechsel (wallet.fifoPsbtOwnWallet)", text)
        self.assertIn("RBF, nLockTime 646", text)
        self.assertIn("wallet.fifoPsbtFingerprintXpub", text)
        self.assertEqual(erg["zustand"], "ok")
        self.assertTrue(erg["kopierenSichtbar"])
        self.assertTrue(erg["frei"])
        self.assertTrue(erg["kopiertOk"])
        self.assertEqual(erg["kopiert"], "cHNidP8BAA==")
        self.assertEqual(erg["kopierText"], "wallet.fifoPsbtCopied")
        self.assertTrue(erg["nachAenderung"])

    def test_sanktion_fragt_vor_dem_erzeugen(self):
        erg = _node(self._BEREIT + r"""
          betrag.value = "30000"; pruefeFifoSpendBetrag(); fifoZielUmschalten();
          adresse.value = "bcrt1qofac";
          adressAntwort = () => ({ status: "sanktioniert", netz: "regtest", sanction: "Beispiel Person", address: "bcrt1qofac" });
          pruefeFifoZielAdresse(); await pause();
          fee.value = "2,5"; fifoFeeEingabe();
          const fragen = [];
          globalThis.confirm = (text) => { fragen.push(text); return false; };
          await fifoPsbtErzeugen();
          const abbruch = { fragen: fragen.slice(), aufrufe: psbtAufrufe.length, downloads: downloads.length };
          globalThis.confirm = (text) => { fragen.push(text); return true; };
          await fifoPsbtErzeugen();
          process.stdout.write(JSON.stringify({
            frei: !psbt.disabled, rot: adresse.dataset.zustand,
            abbruch, danach: { fragen, aufrufe: psbtAufrufe.length, downloads: downloads.length },
          }));
        """)
        self.assertTrue(erg["frei"])
        self.assertEqual(erg["rot"], "rot")
        self.assertEqual(erg["abbruch"]["fragen"], [
            "Willst Du wirklich an die sanktionierte Adresse Beispiel Person senden?",
        ])
        self.assertEqual(erg["abbruch"]["aufrufe"], 0)
        self.assertEqual(erg["abbruch"]["downloads"], 0)
        self.assertEqual(len(erg["danach"]["fragen"]), 2)
        self.assertEqual(erg["danach"]["aufrufe"], 1)
        self.assertEqual(erg["danach"]["downloads"], 1)

    def test_uebersicht_multisig_nennt_cosigner(self):
        erg = _node(self._BEREIT + r"""
          const ms = { status: "ok", inputs: [{}, {}], outputs: [], fee_sats: 314, sat_vb: 1, vsize: 314,
            locktime: 700, herkunft: { quelle: "deskriptor" },
            multisig: { m: 2, n: 3, skript: "wsh", fingerprints: ["919aea07", "e08c7fa9", "1af8622e"] } };
          const ohne = { ...ms, multisig: null, herkunft: { quelle: "xpub" } };
          process.stdout.write(JSON.stringify({ ms: fifoPsbtZusammenfassung(ms, "HS-Multi.psbt"),
            ohne: fifoPsbtZusammenfassung(ohne, "x.psbt") }));
        """)
        self.assertEqual(erg["ms"][-1], "Multisig 2/3: 919aea07, e08c7fa9, 1af8622e")
        self.assertNotIn("wallet.fifoPsbtFingerprintXpub", erg["ms"])
        self.assertFalse(any(z.startswith("Multisig") for z in erg["ohne"]))
        self.assertIn("wallet.fifoPsbtFingerprintXpub", erg["ohne"])

    def test_ohne_psbt_kein_download_und_fehlertext(self):
        erg = _node(self._BEREIT + r"""
          betrag.value = "30000"; pruefeFifoSpendBetrag(); fifoZielUmschalten();
          adresse.value = "bcrt1qfremd"; pruefeFifoZielAdresse(); await pause();
          const text = els["#fifo-psbt-text"], kopieren = els["#fifo-psbt-kopieren"];
          psbtAntwort = () => ({ status: "ueber_max", max_sats: 25000 });
          await fifoPsbtErzeugen();
          const aus = { max: text.textContent, maxZustand: kasten.dataset.zustand, maxKopieren: kopieren.hidden };
          psbtAntwort = () => { throw new Error("Server sagt nein"); };
          await fifoPsbtErzeugen();
          aus.fehler = text.textContent; aus.fehlerZustand = kasten.dataset.zustand;
          aus.downloads = downloads.length; aus.kopieren = await fifoPsbtKopieren();
          process.stdout.write(JSON.stringify(aus));
        """)
        self.assertEqual(erg["max"], "Über Maximum (25.000)")
        self.assertEqual(erg["maxZustand"], "fehler")
        self.assertTrue(erg["maxKopieren"])
        self.assertEqual(erg["fehler"], "PSBT nicht erzeugt: Server sagt nein")
        self.assertEqual(erg["fehlerZustand"], "fehler")
        self.assertEqual(erg["downloads"], 0)
        self.assertFalse(erg["kopieren"])

    def test_dateiname_und_fee_text(self):
        erg = _node(r"""
          const d = new Date(2026, 9, 4, 9, 5);
          process.stdout.write(JSON.stringify({
            normal: fifoPsbtDateiname("HS Alpha", d), umlaut: fifoPsbtDateiname("Spar/Bücher: 2026!", d),
            leer: fifoPsbtDateiname("  ", d), punkt: fifoPsbtDateiname("..x", d),
            m: [fifoMilliText(1000), fifoMilliText(2500), fifoMilliText(125), fifoMilliText(10000000), fifoMilliText(1010)],
          }));
        """)
        self.assertEqual(erg["normal"], "HS-Alpha-20261004-0905.psbt")
        self.assertEqual(erg["umlaut"], "Spar-Bücher-2026-20261004-0905.psbt")
        self.assertEqual(erg["leer"], "wallet-20261004-0905.psbt")
        self.assertEqual(erg["punkt"], "x-20261004-0905.psbt")
        self.assertEqual(erg["m"], ["1", "2.5", "0.125", "10000", "1.01"])


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
        "wallet.fifoSpendTitleNet",
        "wallet.fifoSpendTitleGross",
        "wallet.fifoSpendTitleMempool",
        "wallet.fifoSpendMempoolIncompleteTitle",
        "wallet.fifoSpendTitleUnchecked",
        "wallet.fifoSpendLoadingTitle",
        "wallet.fifoSpendWaitStartTitle",
        "wallet.fifoSpendUnavailableTitle",
        "wallet.fifoSpendAmountPlaceholder",
        "wallet.fifoSpendAmountTitle",
        "wallet.fifoSpendAmountSats",
        "wallet.fifoSpendAmountInvalidFormat",
        "wallet.fifoSpendAmountInvalidRange",
        "wallet.fifoSpendUnitSats",
        "wallet.fifoSpendUnitBtc",
        "wallet.fifoSpendPsbtOpen",
        "wallet.fifoSpendPsbtExpanded",
        "wallet.fifoSpendPsbtNeedsAmount",
        "wallet.fifoSpendPsbtOpenTitle",
        "wallet.fifoSpendPsbtClose",
        "wallet.fifoSpendPsbtTitle",
        "wallet.fifoTargetAria",
        "wallet.fifoTargetAddressPlaceholder",
        "wallet.fifoTargetAddressTitle",
        "wallet.fifoTargetMine",
        "wallet.fifoTargetExternal",
        "wallet.fifoTargetExchange",
        "wallet.fifoTargetSanctioned",
        "wallet.fifoTargetStatusSanctioned",
        "wallet.fifoPsbtSanctionConfirm",
        "wallet.fifoTargetWrongNetwork",
        "wallet.fifoTargetInvalid",
        "wallet.fifoTargetChecking",
        "wallet.fifoTargetUnavailable",
        "wallet.fifoTargetFeePlaceholder",
        "wallet.fifoTargetFeeUnit",
        "wallet.fifoTargetFeeTitle",
        "wallet.fifoTargetFeeInvalid",
        "wallet.fifoTargetFeeSuggested",
        "wallet.fifoTargetFeeCapped",
        "wallet.fifoTargetFeeFallback",
        "wallet.fifoTargetFeeLoading",
        "wallet.fifoTargetFeeOwn",
        "wallet.fifoTargetPsbt",
        "wallet.fifoTargetSelection",
        "wallet.fifoTargetSelectionNoChange",
        "wallet.fifoTargetSelectionDustFee",
        "wallet.fifoTargetSelectionDustKept",
        "wallet.fifoTargetSelectionGreedy",
        "wallet.fifoTargetSelectionShort",
        "wallet.fifoTargetSelectionNone",
        "wallet.fifoTargetStatusExternal",
        "wallet.fifoTargetStatusInvalid",
        "wallet.fifoTargetStatusWrongNetwork",
        "wallet.fifoTargetStatusChecking",
        "wallet.fifoStrategyAria",
        "wallet.fifoStrategyChange",
        "wallet.fifoStrategyFee",
        "wallet.fifoStrategyOldest",
        "wallet.fifoStrategyDust",
        "wallet.fifoStrategyTitle",
        "wallet.fifoStrategySaveFailed",
        "wallet.fifoTargetSelectionCleanup",
        "wallet.fifoTargetSelectionCleanupLimited",
        "wallet.fifoTargetSelectionNonGreen",
        "wallet.fifoPsbtNeedsAddress",
        "wallet.fifoPsbtNeedsFee",
        "wallet.fifoPsbtMultisigInfo",
        "wallet.fifoPsbtBusy",
        "wallet.fifoPsbtSummary",
        "wallet.fifoPsbtSummaryNoChange",
        "wallet.fifoPsbtOutputTarget",
        "wallet.fifoPsbtOutputChange",
        "wallet.fifoPsbtOwnWallet",
        "wallet.fifoPsbtRbf",
        "wallet.fifoPsbtFingerprintXpub",
        "wallet.fifoPsbtMempoolUnchecked",
        "wallet.fifoPsbtOverMax",
        "wallet.fifoPsbtNotEligible",
        "wallet.fifoPsbtFailed",
        "wallet.fifoPsbtCopy",
        "wallet.fifoPsbtCopied",
        "wallet.fifoPsbtCopyFailed",
        "wallet.fifoPsbtResultAria",
        "wallet.fifoChangeRow",
        "wallet.fifoChangeRowTitle",
        "wallet.fifoUtxoToDestTitle",
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
        self.assertTrue(de["wallet.fifoSpendPsbtTitle"].startswith("Unsignierte PSBT (BIP174)"))
        self.assertIn("signiert und sendet nichts", de["wallet.fifoSpendPsbtTitle"])
        # Aufklapp-Knopf je Sprache: „Senden ▸/▾“ bzw. „Send ▸/▾“; „PSBT“ bleibt.
        self.assertEqual((de["wallet.fifoSpendPsbtOpen"], de["wallet.fifoSpendPsbtExpanded"]),
                         ("Senden \u25b8", "Senden \u25be"))
        self.assertEqual((en["wallet.fifoSpendPsbtOpen"], en["wallet.fifoSpendPsbtExpanded"]),
                         ("Send \u25b8", "Send \u25be"))
        for code in (de, en):
            self.assertEqual(code["wallet.fifoTargetPsbt"], "PSBT")
        self.assertIn("{exchange}", de["wallet.fifoTargetExchange"])
        self.assertIn("{exchange}", en["wallet.fifoTargetExchange"])
        self.assertIn("{label}", de["wallet.fifoPsbtSanctionConfirm"])
        self.assertIn("{label}", en["wallet.fifoPsbtSanctionConfirm"])
        self.assertEqual(de["wallet.fifoChangeRow"], "Change")
        self.assertEqual(en["wallet.fifoChangeRow"], "Change")
        self.assertEqual(de["wallet.fifoTargetStatusExternal"], "extern")
        self.assertEqual(en["wallet.fifoTargetStatusExternal"], "external")
        self.assertEqual(de["wallet.fifoTargetStatusInvalid"], "ungültig")
        self.assertEqual(de["wallet.fifoTargetStatusWrongNetwork"], "falsches Netz")
        self.assertEqual([de[f"wallet.fifoStrategy{k}"] for k in ("Change", "Fee", "Oldest", "Dust")],
                         ["Wenig Wechselgeld", "Wenig Gebühr", "Älteste zuerst", "Staub aufräumen"])
        # Tooltip: Kopfzeile + je Strategie ein Satz.
        for code in (de, en):
            self.assertEqual(len(code["wallet.fifoStrategyTitle"].split("\n")), 5)
        self.assertEqual(de["wallet.fifoSpendAmountPlaceholder"], "sats oder BTC")
        self.assertEqual(en["wallet.fifoSpendAmountPlaceholder"], "sats or BTC")
        self.assertNotIn("wallet.fifoSpendAmountInvalid", de)
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
        self.assertIn('type="text"', feld)
        self.assertIn('inputmode="decimal"', feld)
        self.assertNotIn('type="number"', feld)
        self.assertIn('id="fifo-spend-einheit"', kopf)
        self.assertIn('data-i18n-placeholder="wallet.fifoSpendAmountPlaceholder"', feld)
        knopf = re.search(r'<button[^>]*id="fifo-spend-psbt"[^>]*>Senden ▸</button>', kopf, re.S).group(0)
        self.assertIn("disabled", knopf)
        self.assertIn('aria-controls="fifo-spend-ziel"', knopf)
        self.assertIn('data-i18n="wallet.fifoSpendPsbtOpen"', knopf)
        # Ziel-Zeile direkt unter der Kopfzeile, vor der UTXO-Liste.
        ziel = HTML[HTML.index('id="fifo-spend-ziel"'):HTML.index('id="adress-koerper"')]
        self.assertGreater(HTML.index('id="fifo-spend-ziel"'), HTML.index('id="fifo-spend"'))
        self.assertIn('id="fifo-ziel-adresse"', ziel)
        # Status-Label direkt rechts neben der Adresse, vor der Gebühr.
        adr = ziel.index('id="fifo-ziel-adresse"')
        self.assertLess(adr, ziel.index('id="fifo-ziel-status"'))
        self.assertLess(ziel.index('id="fifo-ziel-status"'), ziel.index('id="fifo-ziel-strategie"'))
        self.assertLess(ziel.index('id="fifo-ziel-strategie"'), ziel.index('id="fifo-ziel-fee"'))
        wahl = ziel[ziel.index('id="fifo-ziel-strategie"'):ziel.index("</select>")]
        self.assertEqual(re.findall(r'<option value="(\w+)"', wahl),
                         ["wechselgeld", "gebuehr", "aelteste", "staub"])
        self.assertIn('data-i18n-title="wallet.fifoStrategyTitle"', ziel)
        fee = re.search(r'<input[^>]*id="fifo-ziel-fee"[^>]*>', ziel, re.S).group(0)
        self.assertIn('inputmode="decimal"', fee)
        self.assertIn('data-i18n="wallet.fifoTargetFeeUnit"', ziel)
        fertig = re.search(r'<button[^>]*id="fifo-ziel-psbt"[^>]*>PSBT</button>', ziel, re.S).group(0)
        self.assertIn("disabled", fertig)
        self.assertIn('data-i18n-title="wallet.fifoSpendPsbtTitle"', fertig)
        self.assertIn('id="fifo-ziel-psbt-huelle"', ziel)
        # Ergebnis-Kasten unter der Ziel-Zeile, vor der UTXO-Liste.
        self.assertLess(HTML.index('id="fifo-spend-ziel"'), HTML.index('id="fifo-psbt-ergebnis"'))
        self.assertLess(HTML.index('id="fifo-psbt-ergebnis"'), HTML.index('id="adress-koerper"'))
        self.assertIn('id="fifo-psbt-kopieren"', ziel)
        # Sortier-Info lebt im Sortierfeld weiter (sichtbarer Wert + Tooltip).
        self.assertIn('id="sort-wahl" data-i18n-title="wallet.sortTitle"', HTML)

    def test_kein_versand_kein_signieren(self):
        teil = WALLETS[WALLETS.index("/* --- wallet-fifo-spend --- */"):]
        teil = teil[:teil.index("Zeigt den Abgleich gegen die Sanktionslisten")]
        # Schreibaufrufe: Auswahl-Vorschau, Netto-Maximum und PSBT-Erzeugung (POST,
        # ohne Schlüssel) und die Strategie-Einstellung (PUT). Kein Signier- oder Sende-Endpunkt.
        self.assertEqual(sorted(re.findall(r'methode:\s*"(\w+)"', teil)), ["POST", "POST", "POST", "PUT"])
        self.assertIn('api("/psbt/max", { methode: "POST"', teil)
        self.assertIn('api("/config/fifo-strategie", { methode: "PUT"', teil)
        self.assertIn('api("/psbt/auswahl", { methode: "POST"', teil)
        self.assertIn('api("/psbt/erzeugen", { methode: "POST"', teil)
        self.assertNotRegex(teil.lower(), r"sign(?!et)|broadcast|sendraw")  # Signet ist ein Netzname
        # Klicks: „Senden ▸“ klappt auf, „PSBT“ erzeugt, „Base64 kopieren“.
        klicks = re.findall(r'addEventListener\("click",\s*(\w+)', teil)
        self.assertEqual(klicks, ["fifoZielUmschalten", "fifoPsbtErzeugen", "fifoPsbtKopieren"])
        # Der Körper trägt keine UTXOs/Lot-Anteile — der Server rechnet selbst.
        koerper = teil[teil.index("function fifoPsbtKoerper("):teil.index("function fifoPsbtDateiname(")]
        self.assertNotIn("utxos", koerper)
        self.assertNotIn("sats_gruen", koerper)

    def test_einstellungen_hook_und_css_theme(self):
        self.assertIn("aktualisiereFifoSpend()", EINST)
        self.assertIn(".fifo-spend-betrag.ungueltig", CSS)
        block = CSS[CSS.index(".fifo-spend {"):CSS.index("@media (max-width: 720px) {\n  .fifo-spend")]
        self.assertNotRegex(block, r"#[0-9A-Fa-f]{3,6}\b", "Farben nur über Theme-Variablen")
        # Adressfeld: Platz für bech32m (62 Zeichen, Regtest 64), darf schrumpfen (Text scrollt).
        adr = CSS[CSS.index('input[type="text"].fifo-ziel-adresse {'):][:200]
        self.assertIn("flex: 0 1 calc(64ch", adr)
        for farbe in ("gruen", "gelb", "rot"):
            self.assertIn(f'.fifo-ziel-status[data-zustand="{farbe}"]', CSS)
        self.assertIn(".fifo-auswahl-liste", CSS)
        self.assertIn("fifo-betrag-gruen", CSS)
        self.assertIn("fifo-betrag-gelb", CSS)
        self.assertIn("var(--lot-gruen)", CSS[CSS.index(".fifo-auswahl-liste"):])
        self.assertIn("var(--lot-orange)", CSS[CSS.index(".fifo-change-zeile"):])

    def test_sende_vorschau_haengt_an_zielzeile_und_auswahl(self):
        teil = WALLETS[WALLETS.index("/* --- wallet-fifo-spend --- */"):]
        self.assertIn("function fifoZielAnteile(", teil)
        self.assertIn("function aktualisiereFifoAuswahlListe(", teil)
        self.assertIn("fifo-change-zeile", teil)
        self.assertIn("wallet.fifoChangeRow", teil)
        zeige = teil[teil.index("function fifoZielZeigen("):teil.index("function aktualisiereFifoPsbtKnopf(")]
        self.assertIn("aktualisiereFifoAuswahlListe()", zeige)
        vorschlag = teil[teil.index("function planeFifoFeeVorschlag("):teil.index("function fifoZielAnteile(")]
        self.assertIn("aktualisiereFifoAuswahlListe()", vorschlag)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        kopf = app[app.index("function aktualisiereKopfFilterFuerAnsicht("):][:900]
        self.assertIn("fifoZielZeileOffen", kopf)
        self.assertIn("header.filterTitleFifoSpend", kopf)


if __name__ == "__main__":
    unittest.main()
