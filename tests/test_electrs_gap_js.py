"""Gap-Limit im Electrs-Formular (web/views/datenquellen.js) — mit Node."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
JS = (WEB / "views" / "datenquellen.js").read_text(encoding="utf-8")


def _ausschnitt() -> str:
    """Konstanten und ``electrsGapGueltig`` ohne den Rest der Ansicht."""
    teile = [
        re.search(r"^const ELECTRS_GAP_MIN = \d+;$", JS, re.M).group(0),
        re.search(r"^const ELECTRS_GAP_MAX = \d+;$", JS, re.M).group(0),
        re.search(
            r"^function electrsGapGueltig\(roh\) \{.*?^\}$", JS, re.M | re.S,
        ).group(0),
    ]
    return "\n".join(teile)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestElectrsGapGueltig(unittest.TestCase):

    def pruefe(self, werte: list[object]) -> list[bool]:
        skript = (
            _ausschnitt()
            + f"\nconsole.log(JSON.stringify({json.dumps(werte)}.map(electrsGapGueltig)));"
        )
        aus = subprocess.run(
            ["node", "-e", skript], capture_output=True, text=True,
            timeout=30, check=True,
        )
        return json.loads(aus.stdout)

    def test_grenzen(self):
        self.assertEqual(
            self.pruefe(["1", "20", "100", "250", "10000", " 300 "]),
            [True] * 6,
        )
        self.assertEqual(
            self.pruefe(["0", "10001", "-5", "1e3", "12.5", "abc", "99999"]),
            [False] * 7,
        )

    def test_leer_heisst_vorgabe(self):
        self.assertEqual(self.pruefe(["", "  ", None]), [True, True, True])


class TestGrenzenWieBackend(unittest.TestCase):

    def test_js_und_python_gleich(self):
        from core import wallet_sync_engine as wse

        self.assertIn(f"const ELECTRS_GAP_MIN = {wse.UTXO_SCAN_GAP_MIN};", JS)
        self.assertIn(f"const ELECTRS_GAP_MAX = {wse.UTXO_SCAN_GAP_MAX};", JS)

    def test_uebernehmen_prueft_vor_dem_speichern(self):
        klick = JS.index('speichern.addEventListener("click"')
        pruefung = JS.index("electrsGapGueltig(gapEingabe.value)", klick)
        anfrage = JS.index('api("/config/source"', klick)
        self.assertLess(pruefung, anfrage)
        self.assertIn("validity.badInput", JS)


if __name__ == "__main__":
    unittest.main()
