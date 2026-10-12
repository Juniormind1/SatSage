"""Rescan-Payload: Höhe sticht Datumsschätzung, Gap-Limit 1…10.000."""
from __future__ import annotations

import unittest

from core.utxo_report import estimate_block_height_for_date
from httpserver.api.source import lese_rescan_scan_grenzen


class TestRescanScanGrenzen(unittest.TestCase):
    def test_start_height_sticht_datum(self):
        scan_ab, hoehe, gap = lese_rescan_scan_grenzen({
            "scan_ab": "2017-08-24",
            "start_height": 481824,
            "gap_limit": 250,
        })
        self.assertEqual(scan_ab, "2017-08-24")
        self.assertEqual(hoehe, 481824)
        self.assertEqual(gap, 250)
        self.assertNotEqual(hoehe, estimate_block_height_for_date("2017-08-24"))

    def test_nur_datum_schaetzt(self):
        scan_ab, hoehe, gap = lese_rescan_scan_grenzen({"scan_ab": "2017-08-24"})
        self.assertEqual(scan_ab, "2017-08-24")
        self.assertEqual(hoehe, estimate_block_height_for_date("2017-08-24"))
        self.assertIsNone(gap)

    def test_leeres_payload(self):
        scan_ab, hoehe, gap = lese_rescan_scan_grenzen({})
        self.assertEqual(scan_ab, "")
        self.assertIsNone(hoehe)
        self.assertIsNone(gap)

    def test_hoehe_null_ist_genesis(self):
        _, hoehe, _ = lese_rescan_scan_grenzen({"start_height": 0})
        self.assertEqual(hoehe, 0)

    def test_ungultige_hoehe(self):
        with self.assertRaisesRegex(ValueError, "Scan-Block"):
            lese_rescan_scan_grenzen({"start_height": "x"})
        with self.assertRaisesRegex(ValueError, "Scan-Block"):
            lese_rescan_scan_grenzen({"start_height": -1})

    def test_ungultige_luecke(self):
        with self.assertRaisesRegex(ValueError, "Lücke"):
            lese_rescan_scan_grenzen({"gap_limit": 0})
        with self.assertRaisesRegex(ValueError, "Lücke"):
            lese_rescan_scan_grenzen({"gap_limit": 10001})
        with self.assertRaisesRegex(ValueError, "Lücke"):
            lese_rescan_scan_grenzen({"gap_limit": "breit"})


if __name__ == "__main__":
    unittest.main()
