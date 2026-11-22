"""Coinbase-Statement-Parser, nur synthetische Fixtures."""
from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from tests.fixtures import BIP84_RECEIVE_0
from core.boerse.coinbase import parse
from core.boerse.modell import Art, FormatFehler

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "boerse"

KOPF_2024 = (
    "ID,Timestamp,Transaction Type,Asset,Quantity Transacted,"
    "Price Currency,Price at Transaction,Subtotal,"
    "Total (inclusive of fees and/or spread),Fees and/or Spread,Notes"
)


def _stmt(*zeilen: str) -> str:
    return (
        "Transactions\nUser,00000000-0000-0000-0000-000000000000\n"
        + KOPF_2024 + "\n" + "\n".join(zeilen) + "\n"
    )


class FixtureParseTest(unittest.TestCase):
    def test_2024_grund(self):
        text = (FIXTURES / "coinbase_2024.csv").read_text(encoding="utf-8")
        ergebnis = parse(text)
        self.assertEqual(ergebnis.variante, "2024")
        arten = [b.art for b in ergebnis.buchungen]
        self.assertEqual(arten.count(Art.FIAT_EIN), 1)
        self.assertEqual(arten.count(Art.KAUF), 1)
        self.assertEqual(arten.count(Art.VERKAUF), 1)
        self.assertEqual(arten.count(Art.BTC_AUSGANG), 1)
        self.assertEqual(arten.count(Art.BTC_EINGANG), 1)
        # Convert und Rewards in Quarantäne; ETH-Kauf bleibt draußen.
        self.assertEqual(len(ergebnis.quarantaene), 2)
        self.assertTrue(all(q.grund == "nicht unterstützter Typ" for q in ergebnis.quarantaene))

        kauf = next(b for b in ergebnis.buchungen if b.art == Art.KAUF)
        self.assertEqual(kauf.sats, 1_000_000)
        self.assertEqual(kauf.fiat, Decimal("-500.00"))
        self.assertEqual(kauf.fiat_gebuehr, Decimal("5.00"))
        self.assertEqual(kauf.waehrung, "EUR")
        self.assertEqual(kauf.kurs, Decimal("50000.00"))
        self.assertEqual(kauf.zeit_ts, 1_709_294_400)
        self.assertTrue(kauf.zeit_zone_belegt)
        self.assertEqual(kauf.ref, "CBSYN-0002")
        self.assertEqual(kauf.konto, "coinbase")
        self.assertIsNone(kauf.txid)

        verkauf = next(b for b in ergebnis.buchungen if b.art == Art.VERKAUF)
        self.assertEqual(verkauf.sats, -400_000)
        self.assertEqual(verkauf.fiat, Decimal("240.00"))
        self.assertEqual(verkauf.kurs, Decimal("60000.00"))

        aus = next(b for b in ergebnis.buchungen if b.art == Art.BTC_AUSGANG)
        self.assertEqual(aus.sats, -500_000)
        self.assertEqual(aus.adresse, BIP84_RECEIVE_0)
        self.assertFalse(aus.lightning)

        ein = next(b for b in ergebnis.buchungen if b.art == Art.BTC_EINGANG)
        self.assertEqual(ein.sats, 100_000)

        fiat = next(b for b in ergebnis.buchungen if b.art == Art.FIAT_EIN)
        self.assertEqual(fiat.fiat, Decimal("1500.00"))
        self.assertEqual(fiat.waehrung, "EUR")

    def test_2023_usd(self):
        text = (FIXTURES / "coinbase_2023.csv").read_text(encoding="utf-8")
        ergebnis = parse(text)
        self.assertEqual(ergebnis.variante, "2023")
        self.assertEqual(len(ergebnis.buchungen), 1)
        kauf = ergebnis.buchungen[0]
        self.assertEqual(kauf.art, Art.KAUF)
        self.assertEqual(kauf.sats, 200_000)
        self.assertEqual(kauf.waehrung, "USD")
        self.assertEqual(kauf.fiat, Decimal("-80.00"))
        self.assertEqual(kauf.kurs, Decimal("40000.00"))
        self.assertTrue(kauf.ref.startswith("CBH-"))
        self.assertEqual(kauf.zeit_ts, 1_699_701_071)

    def test_2019_eur_prefix(self):
        text = (FIXTURES / "coinbase_2019_eur.csv").read_text(encoding="utf-8")
        ergebnis = parse(text)
        self.assertEqual(ergebnis.variante, "2019-eur")
        kauf = ergebnis.buchungen[0]
        self.assertEqual(kauf.art, Art.KAUF)
        self.assertEqual(kauf.sats, 300_000)
        self.assertEqual(kauf.waehrung, "EUR")
        self.assertEqual(kauf.fiat, Decimal("-24.00"))
        self.assertEqual(kauf.fiat_gebuehr, Decimal("0.50"))
        self.assertEqual(kauf.kurs, Decimal("8000.00"))
        self.assertEqual(kauf.zeit_ts, 1_579_116_000)


class SonderfaelleTest(unittest.TestCase):
    def test_pro_deposit_ist_intern(self):
        text = _stmt(
            "CBSYN-0100,2024-03-01 12:00:00 UTC,Pro Deposit,BTC,0.00100000,EUR,50000.00,50.00,50.00,0.00,From Pro"
        )
        ergebnis = parse(text)
        self.assertEqual(len(ergebnis.buchungen), 1)
        self.assertEqual(ergebnis.buchungen[0].art, Art.INTERN)
        self.assertEqual(ergebnis.buchungen[0].sats, 100_000)

    def test_unbekannter_typ(self):
        text = _stmt(
            "CBSYN-0101,2024-03-01 12:00:00 UTC,Fork,BTC,0.00100000,EUR,50000.00,50.00,50.00,0.00,x"
        )
        ergebnis = parse(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(ergebnis.quarantaene[0].grund, "nicht unterstützter Typ")
        self.assertEqual(ergebnis.quarantaene[0].roh_typ, "Fork")

    def test_zahl_nicht_lesbar(self):
        text = _stmt(
            "CBSYN-0102,2024-03-01 12:00:00 UTC,Buy,BTC,keinbetrag,EUR,50000.00,50.00,50.00,0.00,x"
        )
        ergebnis = parse(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(ergebnis.quarantaene[0].grund, "Zahl nicht lesbar")

    def test_fremdes_format(self):
        with self.assertRaises(FormatFehler):
            parse('"txid","refid","time","type","asset","amount","fee","balance"\n')

    def test_recipient_address_spalte(self):
        kopf = KOPF_2024 + ",Sender Address,Recipient Address"
        text = (
            kopf + "\nCBSYN-0103,2024-03-01 12:00:00 UTC,Send,BTC,0.00100000,EUR,"
            "50000.00,50.00,50.00,0.00,note,," + BIP84_RECEIVE_0 + "\n"
        )
        ergebnis = parse(text)
        self.assertEqual(ergebnis.variante, "2024-adressen")
        self.assertEqual(ergebnis.buchungen[0].adresse, BIP84_RECEIVE_0)
        self.assertEqual(ergebnis.buchungen[0].art, Art.BTC_AUSGANG)

    def test_gleiche_zeile_ohne_id_ist_stabil(self):
        kopf = KOPF_2024[len("ID,"):]
        zeile = "2024-03-01 12:00:00 UTC,Buy,BTC,0.01000000,EUR,50000.00,500.00,505.00,5.00,x"
        a = parse(kopf + "\n" + zeile + "\n")
        b = parse(kopf + "\n" + zeile + "\n")
        self.assertEqual(a.buchungen[0].ref, b.buchungen[0].ref)
        self.assertTrue(a.buchungen[0].ref.startswith("CBH-"))


if __name__ == "__main__":
    unittest.main()
