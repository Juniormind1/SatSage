"""Strike-Statement-Parser, nur synthetische Fixtures."""
from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from tests.fixtures import BIP84_RECEIVE_0, txid
from core.boerse.strike import parse
from core.boerse.modell import Art, FormatFehler

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "boerse"

KOPF = (
    "Reference,Date & Time (UTC),Transaction Type,Amount EUR,Fee EUR,"
    "Amount BTC,Fee BTC,BTC Price,Cost Basis (EUR),Destination,"
    "Description,Transaction Hash,Note"
)
LN_INV = "lnbc1synthetictestinvoice0001"


def _csv(*zeilen: str) -> str:
    return KOPF + "\n" + "\n".join(zeilen) + "\n"


class FixtureParseTest(unittest.TestCase):
    def test_eur_statement(self):
        text = (FIXTURES / "strike_eur.csv").read_text(encoding="utf-8")
        ergebnis = parse(text)
        self.assertEqual(ergebnis.variante, "statement-eur")
        arten = [b.art for b in ergebnis.buchungen]
        self.assertEqual(arten.count(Art.FIAT_EIN), 1)
        self.assertEqual(arten.count(Art.KAUF), 1)
        self.assertEqual(arten.count(Art.VERKAUF), 1)
        self.assertEqual(arten.count(Art.BTC_AUSGANG), 2)  # on-chain + LN
        self.assertEqual(arten.count(Art.BTC_EINGANG), 1)
        self.assertEqual(arten.count(Art.FIAT_AUS), 1)
        self.assertEqual(len(ergebnis.quarantaene), 1)
        self.assertEqual(ergebnis.quarantaene[0].grund, "P2P-Typ")

        kauf = next(b for b in ergebnis.buchungen if b.art == Art.KAUF)
        self.assertEqual(kauf.sats, 1_000_000)
        self.assertEqual(kauf.fiat, Decimal("-500.00"))
        self.assertEqual(kauf.fiat_gebuehr, Decimal("1.25"))
        self.assertEqual(kauf.waehrung, "EUR")
        self.assertEqual(kauf.kurs, Decimal("50000.00"))
        self.assertEqual(kauf.zeit_ts, 1_772_366_400)
        self.assertTrue(kauf.zeit_zone_belegt)
        self.assertEqual(kauf.ref, "STSYN-0002")
        self.assertEqual(kauf.konto, "strike")

        verkauf = next(b for b in ergebnis.buchungen if b.art == Art.VERKAUF)
        self.assertEqual(verkauf.sats, -400_000)
        self.assertEqual(verkauf.gebuehr_sats, 1_000)
        self.assertEqual(verkauf.fiat, Decimal("240.00"))
        self.assertEqual(verkauf.kurs, Decimal("60000.00"))

        aus = [b for b in ergebnis.buchungen if b.art == Art.BTC_AUSGANG]
        kette = next(b for b in aus if not b.lightning)
        blitz = next(b for b in aus if b.lightning)
        self.assertEqual(kette.sats, -500_000)
        self.assertEqual(kette.gebuehr_sats, 10_000)
        self.assertEqual(kette.adresse, BIP84_RECEIVE_0)
        self.assertEqual(kette.txid, txid("c1"))
        self.assertEqual(blitz.sats, -50_000)
        self.assertTrue(blitz.lightning)
        self.assertIsNone(blitz.txid)
        self.assertIsNone(blitz.adresse)

        ein = next(b for b in ergebnis.buchungen if b.art == Art.BTC_EINGANG)
        self.assertEqual(ein.sats, 100_000)
        self.assertEqual(ein.txid, txid("c1"))
        self.assertFalse(ein.lightning)


class SonderfaelleTest(unittest.TestCase):
    def test_kauf_ignoriert_negatives_btc_vorzeichen(self):
        text = _csv(
            "STSYN-0100,Mar 01 2026 12:00:00,Buy,-100.00,0.00,-0.00200000,0.00000000,50000.00,-,-,x,-,"
        )
        ergebnis = parse(text)
        self.assertEqual(ergebnis.buchungen[0].art, Art.KAUF)
        self.assertEqual(ergebnis.buchungen[0].sats, 200_000)

    def test_lightning_receive(self):
        text = _csv(
            f"STSYN-0101,Jul 02 2026 11:00:00,Receive,-,-,0.00100000,0.00000000,-,-,{LN_INV},ln,{txid('ab')},"
        )
        ergebnis = parse(text)
        b = ergebnis.buchungen[0]
        self.assertEqual(b.art, Art.BTC_EINGANG)
        self.assertTrue(b.lightning)
        self.assertIsNone(b.txid)
        self.assertEqual(b.sats, 100_000)

    def test_unbekannter_typ(self):
        text = _csv(
            "STSYN-0102,Mar 01 2026 12:00:00,Rebate,10.00,0.00,-,-,-,-,-,x,-,"
        )
        ergebnis = parse(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(ergebnis.quarantaene[0].grund, "nicht unterstützter Typ")

    def test_zahl_nicht_lesbar(self):
        text = _csv(
            "STSYN-0103,Mar 01 2026 12:00:00,Purchase,-100.00,0.00,keinbetrag,0,50000,-,-,x,-,"
        )
        ergebnis = parse(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(ergebnis.quarantaene[0].grund, "Zahl nicht lesbar")

    def test_fremdes_format(self):
        with self.assertRaises(FormatFehler):
            parse("ID,Timestamp,Transaction Type,Asset,Quantity Transacted,Notes\n")

    def test_usd_variante(self):
        kopf = KOPF.replace("Amount EUR", "Amount USD").replace("Fee EUR", "Fee USD").replace(
            "Cost Basis (EUR)", "Cost Basis (USD)"
        )
        text = (
            kopf + "\nSTSYN-0104,Mar 01 2026 12:00:00,Purchase,-80.00,0.20,0.00200000,"
            "0.00000000,40000.00,80.00,-,x,-,\n"
        )
        ergebnis = parse(text)
        self.assertEqual(ergebnis.variante, "statement-usd")
        self.assertEqual(ergebnis.buchungen[0].waehrung, "USD")
        self.assertEqual(ergebnis.buchungen[0].fiat, Decimal("-80.00"))


if __name__ == "__main__":
    unittest.main()
