"""Sammel-Bündel im Labor: Soll-Prüfung ohne Node."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "lab" / "regtest" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from buendel_szenario import (  # noqa: E402
    NAME,
    lade_soll,
    offen_ohne_erwartetes_buendel,
    pruefe_zeile,
    stand_ohne_erwartetes_buendel,
)
from core.trace import FULL_RESOLUTION_INPUT_LIMIT  # noqa: E402
from generate_scenarios import BUENDEL_FREMDE, BUENDEL_NAME  # noqa: E402

BLOCK = 1_700_000_000
EIGEN = 1_580_000_000


def _soll() -> dict:
    return {
        "name": NAME,
        "txid": "ab" * 32,
        "vout": 0,
        "block_time": BLOCK,
        "eigen_time": EIGEN,
    }


def _zeile(**kw) -> dict:
    zeile = {
        "time_ts": BLOCK,
        "untergrenze": False,
        "buendel_obergrenze": True,
        "erfuellt": False,
        "sats_gruen": 0,
    }
    zeile.update(kw)
    return zeile


class TestBuendelSzenario(unittest.TestCase):
    def test_mehr_fremde_als_das_aufloese_limit(self):
        self.assertEqual(BUENDEL_NAME, NAME)
        self.assertGreater(BUENDEL_FREMDE, FULL_RESOLUTION_INPUT_LIMIT)

    def test_frist_offen_ist_still(self):
        bezug = datetime.fromtimestamp(BLOCK) + timedelta(days=30)
        self.assertEqual(pruefe_zeile(_zeile(), _soll(), bezug=bezug, haltefrist_jahre=1), [])

    def test_alter_eigener_eingang_ist_zu_alt(self):
        bezug = datetime.fromtimestamp(BLOCK) + timedelta(days=30)
        fehler = pruefe_zeile(
            _zeile(time_ts=EIGEN, erfuellt=True, sats_gruen=1000),
            _soll(),
            bezug=bezug,
            haltefrist_jahre=1,
        )
        self.assertTrue(any(str(EIGEN) in text for text in fehler))
        self.assertTrue(any("Haltefrist erfüllt" in text for text in fehler))
        self.assertTrue(any("grün" in text for text in fehler))

    def test_untergrenze_und_fehlende_markierung(self):
        bezug = datetime.fromtimestamp(BLOCK) + timedelta(days=30)
        fehler = pruefe_zeile(
            _zeile(untergrenze=True, buendel_obergrenze=False),
            _soll(),
            bezug=bezug,
            haltefrist_jahre=1,
        )
        self.assertTrue(any("Untergrenze" in text for text in fehler))
        self.assertTrue(any("vorsichtig" in text for text in fehler))

    def test_ausserhalb_der_frist_darf_gruen_sein(self):
        bezug = datetime.fromtimestamp(BLOCK) + timedelta(days=400)
        self.assertEqual(
            pruefe_zeile(
                _zeile(erfuellt=True, sats_gruen=1000),
                _soll(),
                bezug=bezug,
                haltefrist_jahre=1,
            ),
            [],
        )

    def test_offen_laesst_nur_dieses_utxo_durch(self):
        soll = _soll()
        key = f"{soll['txid']}:{soll['vout']}"
        self.assertEqual(
            offen_ohne_erwartetes_buendel([key.upper(), "cc" * 32 + ":1"], soll),
            ["cc" * 32 + ":1"],
        )

    def test_roter_ring_des_buendels_faellt_raus(self):
        soll = _soll()
        key = f"{soll['txid']}:{soll['vout']}"
        anderer = "ee" * 32 + ":3"
        stand = {
            "offen": [key, "dd" * 32 + ":2"],
            "rote_keys": [key.upper(), anderer],
            "rote": 2,
        }
        self.assertTrue(stand_ohne_erwartetes_buendel(stand, soll))
        self.assertEqual(stand["offen"], ["dd" * 32 + ":2"])
        self.assertEqual(stand["rote_keys"], [anderer])
        self.assertEqual(stand["rote"], 1)

    def test_bericht_ohne_buendel_bricht_ab(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "scenario-report.json"
            pfad.write_text(json.dumps({"records": []}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "frische Chain"):
                lade_soll(pfad)


if __name__ == "__main__":
    unittest.main()
