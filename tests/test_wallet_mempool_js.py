"""
Mempool-Abgleich der Wallet-Ansicht erst nach dem Start (web/views/wallets.js).

Während des Starts wartet ``/wallets/<id>/utxos`` ohne ``mempool=0`` serverseitig
auf den Kontext aller Wallets. Jeder Klick hielt so eine Browser-Verbindung
(HTTP/1.1: sechs je Host). Node-Stub über die echten Funktionen.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_web_js import ohne_texte_und_kommentare

WEB = Path(__file__).resolve().parent.parent / "web"
WALLETS = (WEB / "views" / "wallets.js").read_text(encoding="utf-8")
PAGER = (WEB / "views" / "pager.js").read_text(encoding="utf-8")
API = (WEB / "api.js").read_text(encoding="utf-8")
CHROME = (WEB / "chrome.js").read_text(encoding="utf-8")
NAV = (WEB / "chrome_nav.js").read_text(encoding="utf-8")


def _funktion(quelle: str, kopf: str) -> str:
    """Ganze Top-Level-Funktion ab *kopf* (Bereinigung erhält die Länge)."""
    sauber = ohne_texte_und_kommentare(quelle)
    start = sauber.index(kopf)
    # Parameterliste überspringen (Destrukturierung enthält eigene Klammern).
    klammer = 0
    for j in range(sauber.index("(", start), len(sauber)):
        klammer += {"(": 1, ")": -1}.get(sauber[j], 0)
        if klammer == 0:
            break
    tiefe = 0
    for i in range(sauber.index("{", j), len(sauber)):
        if sauber[i] == "{":
            tiefe += 1
        elif sauber[i] == "}":
            tiefe -= 1
            if tiefe == 0:
                return quelle[start:i + 1]
    raise AssertionError(kopf)


_STUB = r"""
const window = { addEventListener() {} };
const localStorage = { getItem() { return null; }, setItem() {} };
const t = (k) => k;
const Zustand = { config: { wallets: [{ id: "a", name: "A" }, { id: "b", name: "B" }] },
                  ansicht: "wallet", walletId: null, contextBereit: false };
const aufrufe = [];
async function api(pfad, opts = {}) {
  aufrufe.push({ pfad, signal: opts.signal || null });
  return { items: [], total: 0 };
}
const $ = () => ({ hidden: false, value: "betrag" });
const uiSprache = () => "de";
const kopfFilterParameter = () => new URLSearchParams("");
const bestandSeitenAuszug = (a) => ({ items: a.items || [], total: a.total || 0 });
const verlaufSeitenAuszug = bestandSeitenAuszug;
function zeigeAnsicht(n) { Zustand.ansicht = n; }
function ladeEmpfang() { return Promise.resolve(null); }
function empfangSonderAtemLaeuft() { return false; }
function setzeWalletTitel() {}
function setzeText() {}
function zeichneUtxos() {}
function zeigeLeer() {}
function aktualisiereScanAnzeige() {}
const warte = () => new Promise((r) => setTimeout(r, 20));
const utxos = () => aufrufe.filter((x) => x.pfad.includes("/utxos"));
"""

_FUNKTIONEN = [
    "async function zeigeWallet(",
    "function walletListenParameter(",
    "function walletMempoolErlaubt(",
    "function holeWalletMempoolNachStart(",
    "function walletSeitenQuelle(",
    "function ladeWalletSeitenNeu(",
]


def _node(skript: str) -> dict:
    teile = [_STUB, PAGER] + [_funktion(WALLETS, k) for k in _FUNKTIONEN]
    code = "\n".join(teile) + "\n(async () => {\n" + skript + "\n})().catch((e) => { console.error(e); process.exit(1); });"
    aus = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    if aus.returncode != 0:
        raise AssertionError(aus.stderr[-2000:])
    return json.loads(aus.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestMempoolNachStart(unittest.TestCase):

    def test_klicks_waehrend_start_nur_cache_und_nur_letztes_wallet_danach(self):
        erg = _node(r"""
          await zeigeWallet("a"); await warte();
          await zeigeWallet("b"); await warte();
          await zeigeWallet("a"); await warte();
          await zeigeWallet("b"); await warte();
          const waehrend = utxos().map((x) => x.pfad);
          const flag = Zustand.walletMempoolNachStart;
          Zustand.contextBereit = true;
          const erst = holeWalletMempoolNachStart(); await warte();
          const zweit = holeWalletMempoolNachStart(); await warte();
          const danach = utxos().map((x) => x.pfad).slice(waehrend.length);
          process.stdout.write(JSON.stringify({ waehrend, flag, erst, zweit, danach }));
        """)
        # Jeder Klick: genau der Cache-Erst-Paint, kein Mempool-Abgleich.
        self.assertEqual(len(erg["waehrend"]), 4)
        for pfad in erg["waehrend"]:
            self.assertIn("mempool=0", pfad)
        self.assertEqual(erg["flag"], "b")
        # Nach dem Start: einmal, nur für das offene Wallet.
        self.assertTrue(erg["erst"])
        self.assertFalse(erg["zweit"])
        self.assertTrue(erg["danach"], "Mempool-Abgleich nach dem Start fehlt")
        for pfad in erg["danach"]:
            self.assertIn("/wallets/b/", pfad)
            self.assertNotIn("mempool=0", pfad)

    def test_veraltetes_wallet_wird_nicht_nachgeholt(self):
        erg = _node(r"""
          await zeigeWallet("a"); await warte();
          Zustand.ansicht = "steuerjahr";
          Zustand.contextBereit = true;
          const n = utxos().length;
          const geholt = holeWalletMempoolNachStart(); await warte();
          process.stdout.write(JSON.stringify({ geholt, neu: utxos().length - n }));
        """)
        self.assertFalse(erg["geholt"])
        self.assertEqual(erg["neu"], 0)

    def test_vor_ende_des_starts_bleibt_die_merkung(self):
        erg = _node(r"""
          await zeigeWallet("a"); await warte();
          const geholt = holeWalletMempoolNachStart();
          process.stdout.write(JSON.stringify({ geholt, flag: Zustand.walletMempoolNachStart }));
        """)
        self.assertFalse(erg["geholt"])
        self.assertEqual(erg["flag"], "a")

    def test_nach_dem_start_wie_bisher(self):
        erg = _node(r"""
          Zustand.contextBereit = true;
          await zeigeWallet("a"); await warte();
          process.stdout.write(JSON.stringify({ p: utxos().map((x) => x.pfad) }))
        """)
        self.assertEqual(len(erg["p"]), 2)
        self.assertIn("mempool=0", erg["p"][0])
        self.assertNotIn("mempool=0", erg["p"][1])

    def test_wechsel_bricht_anfragen_des_vorigen_wallets_ab(self):
        erg = _node(r"""
          Zustand.contextBereit = true;
          await zeigeWallet("a"); await warte();
          const alt = utxos().filter((x) => x.signal).map((x) => x.signal);
          await zeigeWallet("b"); await warte();
          const neu = utxos().filter((x) => x.signal && x.pfad.includes("/b/")).map((x) => x.signal);
          process.stdout.write(JSON.stringify({
            alt: alt.length, altAbgebrochen: alt.every((s) => s.aborted),
            neuOffen: neu.every((s) => !s.aborted), neu: neu.length,
          }));
        """)
        self.assertGreaterEqual(erg["alt"], 1)
        self.assertTrue(erg["altAbgebrochen"])
        self.assertGreaterEqual(erg["neu"], 1)
        self.assertTrue(erg["neuOffen"])

    def test_blaettern_waehrend_start_nur_cache(self):
        erg = _node(r"""
          const q = walletSeitenQuelle("a", "bestand");
          await q.seite(0);
          Zustand.contextBereit = true;
          const q2 = walletSeitenQuelle("a", "bestand");
          await q2.seite(0);
          process.stdout.write(JSON.stringify({ p: utxos().map((x) => x.pfad) }));
        """)
        self.assertIn("mempool=0", erg["p"][0])
        self.assertNotIn("mempool=0", erg["p"][-1])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestApiAbbruch(unittest.TestCase):

    def test_signal_bricht_ab_und_meldet_abgebrochen(self):
        stub = r"""
          const window = { addEventListener() {} };
          const location = { search: "", pathname: "/", hash: "" };
          const sessionStorage = { getItem() { return ""; }, setItem() {} };
          const history = { replaceState() {} };
          const t = (k) => k;
          function fetch(url, opts) {
            return new Promise((_, nein) => {
              opts.signal.addEventListener("abort", () => {
                const e = new Error("abort"); e.name = "AbortError"; nein(e);
              });
            });
          }
        """
        skript = r"""
          const ctrl = new AbortController();
          const p = api("/wallets/a/utxos", { signal: ctrl.signal });
          ctrl.abort();
          try { await p; process.stdout.write(JSON.stringify({ ok: true })); }
          catch (e) {
            process.stdout.write(JSON.stringify({ abgebrochen: !!e.abgebrochen, status: e.status }));
          }
        """
        code = stub + API + "\n(async () => {\n" + skript + "\n})();"
        aus = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30, check=True)
        erg = json.loads(aus.stdout)
        self.assertTrue(erg["abgebrochen"])
        self.assertNotEqual(erg["status"], 408)


class TestEinbindung(unittest.TestCase):

    def test_start_ende_holt_nach(self):
        self.assertIn("holeWalletMempoolNachStart()", _funktion(CHROME, "async function leseBootLogStream("))
        self.assertIn("holeWalletMempoolNachStart()", _funktion(NAV, "async function ladeJobsNav("))


if __name__ == "__main__":
    unittest.main()
