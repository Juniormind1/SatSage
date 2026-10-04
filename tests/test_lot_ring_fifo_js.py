"""Lot-Donut in Herkunft/Wallet-Liste nimmt den Server-Ring (``lot_fifo``, FIFO je Output)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
HERKUNFT = (WURZEL / "web" / "views" / "herkunft.js").read_text(encoding="utf-8")


def _funktion(name: str) -> str:
    start = HERKUNFT.index(f"function {name}(")
    tiefe, i = 0, HERKUNFT.index("{", start)
    while True:
        c = HERKUNFT[i]
        tiefe += c == "{"
        tiefe -= c == "}"
        i += 1
        if tiefe == 0:
            return HERKUNFT[start:i]


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestLotRingFifo(unittest.TestCase):
    def _lauf(self, antwort) -> dict:
        skript = "\n".join([
            "let antwort = %s;" % json.dumps(antwort),
            "const aufrufe = [];",
            "async function api(p) { aufrufe.push(p); return antwort; }",
            "function lotZeitTs() { return 0; }",
            "function lotMischungAusBaum() { return { gruen: 1, orange: 99, grau: 0, anteilig: true }; }",
            _funktion("lotFifoAusAntwort"),
            _funktion("holeLotMischung"),
            "holeLotMischung('ab:4', {}).then((m) => console.log(JSON.stringify({ m, aufrufe })));",
        ])
        aus = subprocess.run(["node", "-e", skript], capture_output=True, text=True, timeout=30)
        self.assertEqual(aus.returncode, 0, aus.stderr)
        return json.loads(aus.stdout)

    def test_server_ring_vor_anteiliger_mischung(self):
        r = self._lauf({"vorhanden": True, "ergebnis": {"children": [{"type": "internal"}]},
                        "lot_fifo": {"sats_gruen": 1_000_000, "sats_orange": 0, "sats_grau": 0}})
        self.assertEqual(r["m"], {"gruen": 1_000_000, "orange": 0, "grau": 0})
        self.assertEqual(r["aufrufe"], ["/trace?target=ab%3A4"])

    def test_ohne_server_ring_wie_bisher(self):
        r = self._lauf({"vorhanden": True, "ergebnis": {"children": [{"type": "internal"}]}})
        self.assertTrue(r["m"]["anteilig"])
        r = self._lauf({"vorhanden": True, "ergebnis": {"children": [{"type": "internal"}]},
                        "lot_fifo": {"sats_gruen": 0, "sats_orange": 0, "sats_grau": 0}})
        self.assertTrue(r["m"]["anteilig"])

    def test_aufgeklappte_wurzel_merkt_den_ring_je_baum(self):
        quelle = _funktion("aktualisiereLotDonut")
        self.assertIn("zweig._lotFifo", quelle)
        self.assertIn("lotFifoAusAntwort(g)", quelle)
        # Neu geladener Baum vergisst den Ring (kein veralteter Stand).
        self.assertEqual(len(re.findall(r"delete (?:zweig|alt)\._lotKinder;", HERKUNFT)),
                         len(re.findall(r"delete (?:zweig|alt)\._lotFifo;", HERKUNFT)))


if __name__ == "__main__":
    unittest.main()
