"""Herkunftsbaum knotenweise (ISSUES P2): Pfade, Seiten, Baum-Marken."""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from core import trace_cache
from core import trace_knoten as tk
from tests.fixtures import BIP84_ZPUB, txid
from tests.test_api import ApiTestBasis, utxo

import main

WEB = Path(__file__).resolve().parent.parent / "web"


def baum(breite=3, tiefe=3, *, zufall=None):
    zufall = zufall or random.Random(7)
    zaehler = iter(range(10_000))

    def knoten(t):
        n = next(zaehler)
        k = {"id": n, "type": "internal", "address": f"bc1q{n}", "amount_sats": n}
        wahl = zufall.random()
        if wahl < 0.2:
            k["label"] = {"name": zufall.choice(["Kraken", "Bitstamp"]), "kategorie": "exchange",
                          "rolle": zufall.choice(["", "Einzahlung", "Auszahlung"])}
            k["abfluss"] = zufall.random() < 0.5
        elif wahl < 0.3:
            k["tx_class"] = zufall.choice(["whirlpool", "wabisabi", "joinmarket"])
        elif wahl < 0.4:
            k["sources"] = [{"label": {"name": "Coinbase", "kategorie": "exchange"}}]
        kinder = [knoten(t + 1) for _ in range(zufall.randint(0, breite))] if t < tiefe else []
        k["children"] = kinder
        k["expandable"] = bool(kinder)
        return k

    return {"found": True, "root": {"txid": txid("aa"), "vout": 0, "tx_class": "wabisabi"},
            "children": [knoten(0) for _ in range(25)], "summary": {}, "tx_class": "wabisabi"}


class TestPfade(unittest.TestCase):

    def test_pfad_teile(self):
        self.assertEqual(tk.pfad_teile(""), [])
        self.assertEqual(tk.pfad_teile("0.3.12"), [0, 3, 12])
        self.assertIsNone(tk.pfad_teile("0.-1"))
        self.assertIsNone(tk.pfad_teile("a"))

    def test_kinder_und_seite(self):
        b = baum()
        s = tk.seite(tk.kinder_an(b, []), [], 20, 10)
        self.assertEqual(s["total"], 25)
        self.assertEqual([k["pfad"] for k in s["items"]], [str(i) for i in range(20, 25)])
        self.assertTrue(all("children" not in k for k in s["items"]))
        tief = next(k for k in b["children"] if k["children"])
        i = b["children"].index(tief)
        s = tk.seite(tk.kinder_an(b, [i]), [i], 0, 10)
        self.assertEqual(s["total"], len(tief["children"]))
        self.assertEqual(s["items"][0]["pfad"], f"{i}.0")
        self.assertEqual(s["items"][0]["kinder_count"], len(tief["children"][0]["children"]))
        self.assertIsNone(tk.kinder_an(b, [99]))

    def test_seitenweise_ohne_unterbaum(self):
        b = baum()
        s = tk.seitenweise(b, 20)
        self.assertTrue(s["seitenweise"])
        self.assertEqual(s["children_total"], 25)
        self.assertEqual(len(s["children"]), 20)
        self.assertLess(len(json.dumps(s)), len(json.dumps(b)))
        self.assertEqual(tk.seitenweise({"found": False, "error": "x"}, 10),
                         {"found": False, "error": "x"})


@unittest.skipUnless(shutil.which("node"), "node nicht installiert")
class TestMarkenWieBrowser(unittest.TestCase):
    """mixArtenAusErgebnis/boerseNamenAusErgebnis: ganzer Baum == Marken."""

    def test_gleiches_ergebnis(self):
        stub = (
            "const window = { addEventListener() {}, location: { search: '', href: '' } };"
            "const location = window.location;"
            "const sessionStorage = { getItem() { return ''; }, setItem() {}, removeItem() {} };"
            "const localStorage = sessionStorage;"
            "const document = { addEventListener() {}, querySelector() { return null; },"
            " documentElement: { dataset: {} }, cookie: '' };"
            "const history = { replaceState() {} };"
            "const t = (k) => k;\n"
        )
        for seed in range(6):
            b = baum(breite=4, tiefe=4, zufall=random.Random(seed))
            with tempfile.TemporaryDirectory() as tmp:
                voll = Path(tmp) / "v.json"
                schl = Path(tmp) / "s.json"
                voll.write_text(json.dumps(b))
                schl.write_text(json.dumps(tk.seitenweise(b, 10)))
                labels = (WEB / "views" / "adress_labels.js").read_text(encoding="utf-8")
                a = labels.index("function boerseRichtung(")
                richtung = labels[a:labels.index("\n}\n", a) + 3]
                skript = (
                    stub + richtung + (WEB / "api.js").read_text(encoding="utf-8") + "\n"
                    "const fs = require('fs');"
                    f"const v = JSON.parse(fs.readFileSync({json.dumps(str(voll))}, 'utf8'));"
                    f"const s = JSON.parse(fs.readFileSync({json.dumps(str(schl))}, 'utf8'));"
                    "console.log(JSON.stringify([[mixArtenAusErgebnis(v), boerseNamenAusErgebnis(v)],"
                    " [mixArtenAusErgebnis(s), boerseNamenAusErgebnis(s)]]));"
                )
                aus = subprocess.run(["node", "-e", skript], capture_output=True, text=True,
                                     timeout=30)
                self.assertEqual(aus.returncode, 0, aus.stderr[-500:])
                v, s = json.loads(aus.stdout)
                self.assertEqual(v, s, seed)
                self.assertTrue(v[1]["namen"], "Testbaum ohne Börsen taugt nichts")


class TestKnotenApi(ApiTestBasis):

    def setUp(self):
        super().setUp()
        main.save_xpub_utxo_cache(BIP84_ZPUB, [utxo(84_000, marker="a1")], self.cache, 6)
        self.ziel = f"{txid('a1')}:0"
        self.baum = baum()
        trace_cache.speichern(txid("a1"), 0, self.baum, self.immutable, set())

    def test_seite_und_knoten(self):
        _, voll = self.anfrage(f"/api/trace?target={self.ziel}")
        self.assertEqual(len(voll["ergebnis"]["children"]), 25)
        _, körper = self.anfrage(f"/api/trace?target={self.ziel}&seite=1&limit=10")
        e = körper["ergebnis"]
        self.assertEqual((e["children_total"], len(e["children"])), (25, 10))
        self.assertIn("baum_marken", e)
        i = next(n for n, k in enumerate(self.baum["children"]) if k["children"])
        _, k = self.anfrage(f"/api/trace/knoten?target={self.ziel}&pfad={i}&offset=0&limit=50")
        self.assertEqual(k["total"], len(self.baum["children"][i]["children"]))
        self.assertEqual(k["items"][0]["pfad"], f"{i}.0")
        status, _ = self.anfrage(f"/api/trace/knoten?target={self.ziel}&pfad=99")
        self.assertEqual(status, 404)
        status, _ = self.anfrage(f"/api/trace/knoten?target={self.ziel}&pfad=x")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
