"""Kraken-Parser: Ledger plus optionale Trades, nur synthetische Fixtures."""
from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from core.boerse.kraken import parse, parse_ledgers, pruefe_saldo
from core.boerse.modell import Art, FormatFehler

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "boerse"

KOPF = (
    '"txid","refid","time","type","subtype","aclass","asset",'
    '"wallet","amount","fee","balance"'
)
KOPF_ALT = (
    '"txid","refid","time","type","subtype","aclass","asset",'
    '"amount","fee","balance"'
)


def _csv(*zeilen: str, kopf: str = KOPF) -> str:
    return kopf + "\n" + "\n".join(zeilen) + "\n"


def _z(
    txid: str,
    refid: str,
    zeit: str,
    typ: str,
    asset: str,
    amount: str,
    fee: str,
    balance: str,
    *,
    subtype: str = "",
    wallet: str = "spot / main",
    kopf: str = KOPF,
) -> str:
    if kopf == KOPF_ALT:
        return (
            f'"{txid}","{refid}","{zeit}","{typ}","{subtype}",'
            f'"currency","{asset}","{amount}","{fee}","{balance}"'
        )
    return (
        f'"{txid}","{refid}","{zeit}","{typ}","{subtype}",'
        f'"currency","{asset}","{wallet}","{amount}","{fee}","{balance}"'
    )


class FixtureParseTest(unittest.TestCase):
    def test_grund_ohne_trades_e9(self):
        text = (FIXTURES / "ledgers_grund.csv").read_text(encoding="utf-8")
        ergebnis = parse_ledgers(text)
        self.assertEqual(ergebnis.variante, "ledgers")
        self.assertEqual(pruefe_saldo(text), ())
        arten = [b.art for b in ergebnis.buchungen]
        self.assertEqual(arten.count(Art.FIAT_EIN), 1)
        self.assertEqual(arten.count(Art.KAUF), 1)
        self.assertEqual(arten.count(Art.VERKAUF), 1)
        self.assertEqual(arten.count(Art.INTERN), 2)
        self.assertEqual(arten.count(Art.BTC_AUSGANG), 1)
        self.assertEqual(ergebnis.quarantaene, ())

        kauf = next(b for b in ergebnis.buchungen if b.art == Art.KAUF)
        self.assertEqual(kauf.sats, 1_000_000)
        self.assertEqual(kauf.gebuehr_sats, 0)
        self.assertEqual(kauf.fiat, Decimal("-500.0000"))
        self.assertEqual(kauf.fiat_gebuehr, Decimal("1.2500"))
        self.assertEqual(kauf.waehrung, "EUR")
        self.assertEqual(kauf.kurs, Decimal("50000"))
        self.assertEqual(kauf.zeit_ts, 1_709_294_400)
        self.assertTrue(kauf.zeit_zone_belegt)
        self.assertIsNone(kauf.txid)
        self.assertEqual(kauf.gruppe, "TSYN01-00000-000001")
        self.assertEqual(kauf.konto, "kraken")

        verkauf = next(b for b in ergebnis.buchungen if b.art == Art.VERKAUF)
        self.assertEqual(verkauf.sats, -400_000)
        self.assertEqual(verkauf.gebuehr_sats, 1_000)
        self.assertEqual(verkauf.fiat, Decimal("240.0000"))
        self.assertEqual(verkauf.kurs, Decimal("60000"))
        self.assertEqual(verkauf.zeit_ts, 1_718_440_200)

        aus = next(b for b in ergebnis.buchungen if b.art == Art.BTC_AUSGANG)
        self.assertEqual(aus.sats, -490_000)
        self.assertEqual(aus.gebuehr_sats, 9_000)
        self.assertIsNone(aus.txid)
        self.assertFalse(aus.lightning)

        intern = [b for b in ergebnis.buchungen if b.art == Art.INTERN]
        self.assertEqual(sorted(b.sats for b in intern), [-100_000, 100_000])
        self.assertEqual({b.gruppe for b in intern}, {"TSYN01-00000-000002"})

    def test_grund_mit_trades_nimmt_preis(self):
        ledgers = (FIXTURES / "ledgers_grund.csv").read_text(encoding="utf-8")
        trades = (FIXTURES / "trades_grund.csv").read_text(encoding="utf-8")
        ergebnis = parse(ledgers, trades)
        kauf = next(b for b in ergebnis.buchungen if b.art == Art.KAUF)
        self.assertEqual(kauf.kurs, Decimal("50000.5"))
        verkauf = next(b for b in ergebnis.buchungen if b.art == Art.VERKAUF)
        self.assertEqual(verkauf.kurs, Decimal("60000.0"))

    def test_ledgers_ohne_wallet(self):
        text = (FIXTURES / "ledgers_ohne_wallet.csv").read_text(encoding="utf-8")
        ergebnis = parse_ledgers(text)
        self.assertEqual(ergebnis.variante, "ledgers-ohne-wallet")
        self.assertEqual(len(ergebnis.buchungen), 1)
        kauf = ergebnis.buchungen[0]
        self.assertEqual(kauf.art, Art.KAUF)
        self.assertEqual(kauf.sats, 200_000)
        self.assertEqual(kauf.waehrung, "USD")
        self.assertEqual(kauf.fiat, Decimal("-80.0000"))
        self.assertEqual(kauf.kurs, Decimal("40000"))
        self.assertEqual(kauf.zeit_ts, 1_699_701_071)


class PaarungTest(unittest.TestCase):
    def test_spend_receive_und_karten_deposit(self):
        text = _csv(
            _z("LSYN03-00000-000001", "TSYN03-00000-000001", "2024-05-20 16:45:00.1234",
               "deposit", "ZEUR", "505.0000", "0.0000", "505.0000"),
            _z("LSYN03-00000-000002", "TSYN03-00000-000001", "2024-05-20 16:45:00.1234",
               "spend", "ZEUR", "-500.0000", "5.0000", "0.0000"),
            _z("LSYN03-00000-000003", "TSYN03-00000-000001", "2024-05-20 16:45:00.1234",
               "receive", "XXBT", "0.01000000", "0.00000000", "0.01000000"),
        )
        ergebnis = parse_ledgers(text)
        arten = [b.art for b in ergebnis.buchungen]
        self.assertEqual(arten.count(Art.KAUF), 1)
        self.assertEqual(arten.count(Art.FIAT_EIN), 1)
        kauf = next(b for b in ergebnis.buchungen if b.art == Art.KAUF)
        self.assertEqual(kauf.sats, 1_000_000)
        self.assertEqual(kauf.roh_typ, "receive")
        self.assertEqual(ergebnis.quarantaene, ())

    def test_btc_gegen_eth_wird_quarantaene(self):
        text = _csv(
            _z("LSYN04-00000-000001", "TSYN04-00000-000001", "2024-03-01 12:00:00.0000",
               "trade", "XXBT", "0.00200000", "0.00000000", "0.01200000"),
            _z("LSYN04-00000-000002", "TSYN04-00000-000001", "2024-03-01 12:00:00.0000",
               "trade", "XETH", "-1.00000000", "0.00000000", "0.00000000"),
        )
        ergebnis = parse_ledgers(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertTrue(ergebnis.quarantaene)
        self.assertTrue(all(q.grund == "Trade ohne Fiat-Gegenzeile" for q in ergebnis.quarantaene))

    def test_trade_ohne_refid(self):
        text = _csv(
            _z("LSYN05-00000-000001", "", "2024-03-01 12:00:00.0000",
               "trade", "XXBT", "0.00200000", "0.00000000", "0.00200000"),
        )
        ergebnis = parse_ledgers(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(ergebnis.quarantaene[0].grund, "refid fehlt")

    def test_unbekannter_typ(self):
        text = _csv(
            _z("LSYN06-00000-000001", "", "2024-03-01 12:00:00.0000",
               "foobar", "XXBT", "0.00100000", "0.00000000", "0.00100000"),
        )
        ergebnis = parse_ledgers(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(ergebnis.quarantaene[0].grund, "nicht unterstützter Typ")
        self.assertEqual(ergebnis.quarantaene[0].roh_typ, "foobar")

    def test_margin_und_futures(self):
        text = _csv(
            _z("LSYN07-00000-000001", "TSYN07-00000-000001", "2024-03-01 12:00:00.0000",
               "margin trade", "XXBT", "0.00100000", "0.00000000", "0.00100000"),
            _z("LSYN07-00000-000002", "TSYN07-00000-000002", "2024-03-01 12:00:00.0000",
               "transfer", "XXBT", "-0.00100000", "0.00000000", "0.00000000",
               subtype="spottofutures"),
        )
        ergebnis = parse_ledgers(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(len(ergebnis.quarantaene), 2)
        self.assertTrue(all(q.grund == "nicht unterstützter Typ" for q in ergebnis.quarantaene))

    def test_unbekannter_btc_suffix(self):
        text = _csv(
            _z("LSYN08-00000-000001", "", "2024-03-01 12:00:00.0000",
               "deposit", "XBT.WEIRD", "0.00100000", "0.00000000", "0.00100000"),
        )
        ergebnis = parse_ledgers(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(ergebnis.quarantaene[0].grund, "unbekannter BTC-Suffix")

    def test_bekannter_suffix_xbt_m(self):
        text = _csv(
            _z("LSYN09-00000-000001", "", "2024-03-01 12:00:00.0000",
               "deposit", "XXBT.M", "0.00100000", "0.00000000", "0.00100000"),
        )
        ergebnis = parse_ledgers(text)
        self.assertEqual(len(ergebnis.buchungen), 1)
        self.assertEqual(ergebnis.buchungen[0].art, Art.BTC_EINGANG)
        self.assertEqual(ergebnis.buchungen[0].sats, 100_000)

    def test_zahl_nicht_lesbar(self):
        text = _csv(
            _z("LSYN10-00000-000001", "TSYN10-00000-000001", "2024-03-01 12:00:00.0000",
               "trade", "XXBT", "keinbetrag", "0.00000000", "0.00000000"),
            _z("LSYN10-00000-000002", "TSYN10-00000-000001", "2024-03-01 12:00:00.0000",
               "trade", "ZEUR", "-10.0000", "0.0000", "0.0000"),
        )
        ergebnis = parse_ledgers(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(ergebnis.quarantaene[0].grund, "Zahl nicht lesbar")

    def test_sale_wird_ignoriert(self):
        text = _csv(
            _z("LSYN11-00000-000001", "", "2024-03-01 12:00:00.0000",
               "sale", "XXBT", "-0.00100000", "0.00000000", "0.00000000"),
        )
        ergebnis = parse_ledgers(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(ergebnis.quarantaene, ())

    def test_fremdes_format_wird_abgelehnt(self):
        with self.assertRaises(FormatFehler):
            parse_ledgers("Timestamp,Type,Amount\n2024-01-01,Buy,1\n")

    def test_eth_deposit_wird_ignoriert(self):
        text = _csv(
            _z("LSYN12-00000-000001", "", "2024-03-01 12:00:00.0000",
               "deposit", "XETH", "1.00000000", "0.00000000", "1.00000000"),
        )
        ergebnis = parse_ledgers(text)
        self.assertEqual(ergebnis.buchungen, ())
        self.assertEqual(ergebnis.quarantaene, ())


class SaldoTest(unittest.TestCase):
    def test_luecke_wird_gemeldet(self):
        text = _csv(
            _z("LSYN13-00000-000001", "", "2024-02-01 09:00:00.0000",
               "deposit", "XXBT", "0.01000000", "0.00000000", "0.01000000"),
            _z("LSYN13-00000-000002", "", "2024-02-02 09:00:00.0000",
               "withdrawal", "XXBT", "-0.00100000", "0.00000000", "0.00800000"),
        )
        luecken = pruefe_saldo(text)
        self.assertEqual(luecken, (3,))  # Kopf ist Zeile 1, erste Datenzeile 2, Lücke in 3

    def test_getrennte_wallets_sind_unabhaengig(self):
        text = _csv(
            _z("LSYN14-00000-000001", "", "2024-02-01 09:00:00.0000",
               "deposit", "XXBT", "0.01000000", "0.00000000", "0.01000000",
               wallet="spot / main"),
            _z("LSYN14-00000-000002", "", "2024-02-01 09:00:00.0000",
               "deposit", "XXBT", "0.00200000", "0.00000000", "0.00200000",
               wallet="earn / flexible"),
        )
        self.assertEqual(pruefe_saldo(text), ())


if __name__ == "__main__":
    unittest.main()
