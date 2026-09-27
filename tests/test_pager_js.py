"""Seitenleiste (web/views/pager.js) und ihre Einbindung — statisch, optional mit Node."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
PAGER = (WEB / "views" / "pager.js").read_text(encoding="utf-8")


def _node(skript: str) -> object:
    stub = (
        "const window = { addEventListener() {} };"
        "const localStorage = { _d: {}, getItem(k) { return this._d[k] ?? null; },"
        " setItem(k, v) { this._d[k] = String(v); } };"
        "const t = (k) => k;\n"
    )
    aus = subprocess.run(
        ["node", "-e", stub + PAGER + "\n" + skript],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(aus.stdout)


class TestEinbindung(unittest.TestCase):

    def test_vor_den_ansichten_geladen(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        pager = html.index('src="/views/pager.js')
        for m in re.finditer(r'src="/views/(\w+)\.js', html):
            if m.group(1) != "pager":
                self.assertLess(pager, m.start(), m.group(1))

    def test_limit_wahl_ersetzt(self):
        for datei in [WEB / "index.html", *WEB.glob("*.js"), *WEB.glob("views/*.js")]:
            self.assertNotIn("limit-wahl", datei.read_text(encoding="utf-8"), datei.name)

    def test_texte_in_beiden_sprachen(self):
        for code in ("de", "en"):
            katalog = json.loads((WEB / "locales" / f"{code}.json").read_text(encoding="utf-8"))
            for schluessel in re.findall(r't\("(pager\.\w+)"', PAGER):
                self.assertTrue(katalog.get(schluessel), f"{code}: {schluessel}")

    def test_ansichten_holen_seiten_vom_server(self):
        herkunft = (WEB / "views" / "herkunft.js").read_text(encoding="utf-8")
        wallets = (WEB / "views" / "wallets.js").read_text(encoding="utf-8")
        for js in (herkunft, wallets):
            self.assertIn('p.set("seite", "1")', js)
            self.assertIn("neueSeitenQuelle(", js)
            self.assertIn("kopfFilterParameter()", js)
        # „Bereits ausgegeben“: erst beim Aufklappen vom Server.
        self.assertIn("block.oeffneAusgegeben = oeffne", herkunft)

    def test_filter_geht_an_den_server(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn('p.set("q", roh)', app)
        self.assertIn("ladeTraceSeitenNeu()", app)
        self.assertIn("ladeWalletSeitenNeu()", app)

    def test_steuerjahr_seitenweise(self):
        steuer = (WEB / "views" / "steuerjahr.js").read_text(encoding="utf-8")
        self.assertIn('p.set("seite", "1")', steuer)
        self.assertIn('p.set("limit_abgaenge"', steuer)
        self.assertIn('ansicht: "steuerjahr"', steuer)
        self.assertIn('ansicht: "abgaenge"', steuer)
        # Kennzahlen-Fiat aus dem Server-Tag, nicht aus der Seite.
        self.assertIn("kennzahlen_ts", steuer)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("ladeSteuerSeitenNeu()", app)
        self.assertIn("_steuerFensterTreffer(tbody)", app)
        herkunft = (WEB / "views" / "herkunft.js").read_text(encoding="utf-8")
        self.assertIn("daten.gelb_keys", herkunft)

    def test_baum_knotenweise(self):
        herkunft = (WEB / "views" / "herkunft.js").read_text(encoding="utf-8")
        self.assertIn("&seite=1&limit=${2 * pagerGroesse(\"baum\")}", herkunft)
        self.assertIn("/trace/knoten?target=", herkunft)
        self.assertIn('ansicht: "baum"', herkunft)
        # „Alles aufklappen“: ein Abruf des ganzen Baums statt je Knoten.
        a = herkunft.index("async function expandiereBaumAlles")
        self.assertIn("/trace?target=${encodeURIComponent(ziel)}`", herkunft[a:a + 900])
        api = (WEB / "api.js").read_text(encoding="utf-8")
        self.assertEqual(api.count("const stapel = baumStapel(ergebnis);"), 2)

    def test_seitencache_verfaellt(self):
        self.assertIn('addEventListener("satsage:lang", () => pagerCachesVerwerfen())', PAGER)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("pagerCachesVerwerfen();", app)
        # Sortierwechsel und fertiger Scan verwerfen vorgeladene Seiten.
        chrome = (WEB / "chrome.js").read_text(encoding="utf-8")
        self.assertRegex(chrome, r'#sort-wahl"\)\.addEventListener\("change", \(\) => \{[^}]*pagerCachesVerwerfen\(\)')
        wallets = (WEB / "views" / "wallets.js").read_text(encoding="utf-8")
        self.assertRegex(wallets, r'job\.status === "done"\) \{[^}]*pagerCachesVerwerfen\(\)')


@unittest.skipUnless(shutil.which("node"), "node nicht installiert")
class TestPagerLogik(unittest.TestCase):

    def test_bereiche_exakt_und_luecken(self):
        aus = _node("console.log(JSON.stringify(pagerBereiche(247, 10, 120).map("
                    "(b) => b === '…' ? b : `${b.von}-${b.bis}${b.aktiv ? '*' : ''}`)))")
        self.assertEqual(aus, ["1-10", "…", "101-110", "111-120", "121-130*",
                               "131-140", "141-150", "…", "241-247"])

    def test_wenige_seiten_ohne_luecke(self):
        aus = _node("console.log(JSON.stringify(pagerBereiche(25, 10, 0).length))")
        self.assertEqual(aus, 3)

    def test_groesse_je_ansicht(self):
        aus = _node("setzePagerGroesse('trace', 50); setzePagerGroesse('wallet', 7);"
                    "console.log(JSON.stringify([pagerGroesse('trace'), pagerGroesse('wallet')]))")
        self.assertEqual(aus, [50, 10])

    def test_quelle_holt_doppelt_und_laedt_vor(self):
        aus = _node("""
const rufe = [];
const q = neueSeitenQuelle({ groesse: 10,
  laden: async (o, l) => { rufe.push([o, l]); return { o }; },
  auszug: (a) => ({ items: Array.from({ length: 20 }, (_, i) => a.o + i), total: 95, art: 'utxos' }) });
(async () => {
  const s1 = await q.seite(0);
  await new Promise((r) => setTimeout(r, 0));
  const s2 = await q.seite(10);
  await new Promise((r) => setTimeout(r, 0));
  console.log(JSON.stringify({ rufe, s1: s1.items[0], s2: s2.items[0], n: s2.items.length }));
})();
""")
        # Seite 1+2 in einem Abruf (20), Block ab 20 im Hintergrund vorgeladen.
        self.assertEqual(aus["rufe"], [[0, 20], [20, 20]])
        self.assertEqual((aus["s1"], aus["s2"], aus["n"]), (0, 10, 10))

    def test_vorab_block_ohne_abruf(self):
        aus = _node("""
const rufe = [];
const q = neueSeitenQuelle({ groesse: 10, vorab: { o: 0 },
  laden: async (o, l) => { rufe.push([o, l]); return { o }; },
  auszug: (a) => ({ items: Array.from({ length: 20 }, (_, i) => a.o + i), total: 25 }) });
(async () => {
  const s2 = await q.seite(10);
  await new Promise((r) => setTimeout(r, 0));
  console.log(JSON.stringify({ rufe, s2: s2.items[0] }));
})();
""")
        # Seite 2 kommt aus der Vorab-Antwort; nur der Rest (21–25) wird geholt.
        self.assertEqual(aus, {"rufe": [[20, 20]], "s2": 10})

    def test_generation_leert_cache(self):
        aus = _node("""
let n = 0;
const q = neueSeitenQuelle({ groesse: 10, laden: async () => { n += 1; return {}; },
  auszug: () => ({ items: [], total: 5 }) });
(async () => { await q.seite(0); await q.seite(0); pagerCachesVerwerfen(); await q.seite(0);
  console.log(JSON.stringify(n)); })();
""")
        self.assertEqual(aus, 2)


if __name__ == "__main__":
    unittest.main()
