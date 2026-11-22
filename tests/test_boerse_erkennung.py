"""Formaterkennung: bekannte Köpfe, Präambel, Ablehnung unbekannter Varianten."""
from __future__ import annotations

import unittest

from core.boerse.erkennung import erkenne
from core.boerse.modell import FormatFehler

KOPF_LEDGER = '"txid","refid","time",' + '"type"' + ',"subtype","aclass","asset","wallet","amount","fee","balance"'
KOPF_TRADES = '"txid","ordertxid","pair","time",' + '"type"' + ',"ordertype","price","cost","fee","vol","margin","misc","ledgers"'
KOPF_CB_2024 = (
    "ID,Timestamp,Transaction Type,Asset,Quantity Transacted,"
    "Price Currency,Price at Transaction,Subtotal,"
    "Total (inclusive of fees and/or spread),Fees and/or Spread,Notes"
)
KOPF_STRIKE = (
    "Reference,Date & Time (UTC),Transaction Type,Amount EUR,Fee EUR,"
    "Amount BTC,Fee BTC,BTC Price,Cost Basis (EUR),Destination,"
    "Description,Transaction Hash,Note"
)


class ErkennungTest(unittest.TestCase):
    def test_kraken_ledgers(self):
        text = KOPF_LEDGER + "\nLSYN,ignored\n"
        e = erkenne(text)
        self.assertEqual(e.boerse, "kraken")
        self.assertEqual(e.variante, "ledgers")
        self.assertEqual(e.kopf_zeile, 1)
        self.assertEqual(e.trennzeichen, ",")
        self.assertEqual(len(e.zeilen), 1)

    def test_kraken_ledgers_ohne_wallet(self):
        kopf = '"txid","refid","time","type","asset","amount","fee","balance"'
        e = erkenne(kopf + "\n")
        self.assertEqual(e.variante, "ledgers-ohne-wallet")

    def test_kraken_trades(self):
        e = erkenne(KOPF_TRADES + "\n")
        self.assertEqual((e.boerse, e.variante), ("kraken", "trades"))

    def test_coinbase_praeambel(self):
        text = "\r\nTransactions\r\nUser,00000000-0000-0000-0000-000000000000\r\n" + KOPF_CB_2024 + "\r\nzeile\r\n"
        e = erkenne(text)
        self.assertEqual(e.boerse, "coinbase")
        self.assertEqual(e.variante, "2024")
        self.assertEqual(e.kopf_zeile, 4)
        self.assertEqual(e.zeilen, ("zeile",))

    def test_coinbase_2024_ohne_id(self):
        kopf = KOPF_CB_2024[len("ID,"):]
        e = erkenne(kopf + "\n")
        self.assertEqual(e.variante, "2024-ohne-id")

    def test_strike_eur(self):
        e = erkenne(KOPF_STRIKE + "\n")
        self.assertEqual((e.boerse, e.variante), ("strike", "statement-eur"))

    def test_bom_und_semikolon(self):
        text = "\ufeff" + KOPF_LEDGER.replace(",", ";") + "\n"
        e = erkenne(text)
        self.assertEqual(e.trennzeichen, ";")
        self.assertEqual(e.boerse, "kraken")

    def test_unbekannter_kopf_abgelehnt(self):
        with self.assertRaises(FormatFehler) as ctx:
            erkenne("Foo,Bar,Baz,Qux\n1,2,3,4\n")
        self.assertIn("Format nicht erkannt", str(ctx.exception))
        self.assertIn("foo", ctx.exception.spalten)
        # Keine Werte in der Meldung.
        self.assertNotIn("1,2,3,4", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
