"""Log-Bereich landet zusätzlich unter tmp/."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.sanctions_pool import _ssl_wie_electrum
from httpserver.logbereich import schreibe


class TestLogbereichDatei(unittest.TestCase):
    def test_haengt_zeilen_an(self) -> None:
        with tempfile.TemporaryDirectory() as ordner:
            ziel = Path(ordner) / "logbereich.log"
            with mock.patch("httpserver.logbereich.datei", return_value=ziel):
                schreibe([{
                    "t": "09:01:00",
                    "text": "Verbinde mit der Datenquelle",
                    "wallet": "Kasse",
                }])
                schreibe([{"t": "09:01:01", "text": "Verbunden."}])
            text = ziel.read_text(encoding="utf-8")
        self.assertIn("09:01:00  Kasse  Verbinde mit der Datenquelle\n", text)
        self.assertIn("09:01:01  Verbunden.\n", text)


class TestSanktionsSslWieElectrum(unittest.TestCase):
    def test_port_50001_ohne_flag_ist_klartext(self) -> None:
        self.assertFalse(_ssl_wie_electrum({}, "FULCRUM_SSL", 50001))
        self.assertTrue(_ssl_wie_electrum({}, "FULCRUM_SSL", 50002))
        self.assertTrue(_ssl_wie_electrum(
            {"FULCRUM_SSL": "true"}, "FULCRUM_SSL", 50001,
        ))
