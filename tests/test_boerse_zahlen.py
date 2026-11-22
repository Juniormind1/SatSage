"""Zahlenparser für Börsen-CSV: Punkt/Komma, Symbole, exakte Sats."""
from __future__ import annotations

import unittest
from decimal import Decimal

from core.boerse.zahlen import ZahlenFehler, btc_nach_sats, parse_btc_sats, parse_decimal


class ParseDecimalTest(unittest.TestCase):
    def test_punkt_und_leer(self):
        self.assertEqual(parse_decimal("1234.56"), Decimal("1234.56"))
        self.assertIsNone(parse_decimal(""))
        self.assertIsNone(parse_decimal("-"))
        self.assertIsNone(parse_decimal(None))

    def test_euro_symbol_und_tausender(self):
        self.assertEqual(parse_decimal("€1,234.56"), Decimal("1234.56"))
        self.assertEqual(parse_decimal("-€1,234.56"), Decimal("-1234.56"))

    def test_europaeisches_komma(self):
        self.assertEqual(parse_decimal("1.234,56"), Decimal("1234.56"))
        self.assertEqual(parse_decimal("1,23"), Decimal("1.23"))

    def test_acht_nachkommastellen(self):
        self.assertEqual(parse_decimal("0,01000000"), Decimal("0.01000000"))

    def test_unlesbar(self):
        with self.assertRaises(ZahlenFehler):
            parse_decimal("abc")


class BtcNachSatsTest(unittest.TestCase):
    def test_exakt(self):
        self.assertEqual(btc_nach_sats(Decimal("0.01")), 1_000_000)
        self.assertEqual(btc_nach_sats(Decimal("-0.00000001")), -1)
        self.assertEqual(parse_btc_sats("0.01000000"), 1_000_000)

    def test_zu_fein(self):
        with self.assertRaises(ZahlenFehler):
            btc_nach_sats(Decimal("0.000000001"))

    def test_kein_float(self):
        # 0.1 + 0.2 in float wäre ungenau; Decimal bleibt exakt.
        self.assertEqual(parse_btc_sats("0.00000003"), 3)


if __name__ == "__main__":
    unittest.main()
