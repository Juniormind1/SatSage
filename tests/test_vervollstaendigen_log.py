"""Datei-Log für „vervollständigen“: jeder Hop sofort, ohne Adressen."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from core import vervollstaendigen_log as vl


class TestDatei(unittest.TestCase):
    def test_hop_landet_sofort_in_der_datei(self):
        with TemporaryDirectory() as roh:
            wurzel = Path(roh)
            with mock.patch("core.paths.app_dir", return_value=wurzel), \
                    mock.patch.object(vl, "AKTIV", True):
                spur = vl.Spur("aa" * 32, 1, "full")
                spur.zeile("START art=full")
                spur.hop(3, f"{'bb' * 32}:0", quelle="lade")
                spur.ende("done", extra="knoten=2")
                text = (wurzel / "logs" / "vervollstaendigen.log").read_text()
        self.assertIn("START art=full", text)
        self.assertIn("hop n=1 tiefe=3", text)
        self.assertIn("ENDE status=done", text)
        self.assertNotIn("bc1", text)

    def test_adapter_behaelt_die_spur(self):
        from core.trace import _FortschrittsAdapter

        class MitSpur:
            spur = "datei"

            def update(self, text):
                self.text = text

        adaptiert = _FortschrittsAdapter(MitSpur())
        self.assertEqual(adaptiert.spur, "datei")


if __name__ == "__main__":
    unittest.main()
