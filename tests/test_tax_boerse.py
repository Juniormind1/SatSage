"""M8: Börsen-FIFO im Steuerbericht, P&L nur optional."""
from __future__ import annotations

import csv
import io
import unittest
from datetime import datetime
from decimal import Decimal

from core.boerse.fifo import BoerseLos
from core.boerse.overlay import BoerseKontext
from core.tax import als_bericht, als_csv, auswerten, lese_steuer_einstellungen
from tests.fixtures import BIP84_RECEIVE_0, txid
from tests.test_tax import NACH_JAHRESENDE, utxo


T_KAUF_1 = int(datetime(2024, 3, 1, 12, 0).timestamp())
T_KAUF_2 = int(datetime(2024, 6, 1, 12, 0).timestamp())


def _kontext(marker="m8a", vout=0) -> BoerseKontext:
    kontext = BoerseKontext()
    kontext.setze(txid(marker), vout, (
        BoerseLos(
            sats=100_000, zeit_ts=T_KAUF_1, konto="kraken", boerse="Kraken",
            kauf_art="kauf", einzelpreis_btc=Decimal("50000"),
            waehrung="EUR", kosten=Decimal("50"),
        ),
        BoerseLos(
            sats=50_000, zeit_ts=T_KAUF_2, konto="kraken", boerse="Kraken",
            kauf_art="kauf", einzelpreis_btc=Decimal("60000"),
            waehrung="EUR", kosten=Decimal("30"),
        ),
    ))
    return kontext


def _auswertung(*, pnl=False, kurs=Decimal("70000")):
    u = utxo(150_000, "01.07.2024 18:00", marker="m8a")
    def kurs_am(bezug, waehrung):
        self_check = (waehrung or "").upper() == "EUR"
        return kurs if self_check else None
    return auswerten(
        [u], 2026,
        jetzt=NACH_JAHRESENDE,
        boerse_kontext=_kontext(),
        boerse_pnl=pnl,
        kurs_am=kurs_am,
    )


class EinstellungenPnlTest(unittest.TestCase):
    def test_default_ist_aus(self):
        werte = lese_steuer_einstellungen({})
        self.assertFalse(werte["boerse_pnl"])

    def test_eins_schaltet_ein(self):
        werte = lese_steuer_einstellungen({"STEUER_BOERSE_PNL": "1"})
        self.assertTrue(werte["boerse_pnl"])


class BerichtOhnePnlTest(unittest.TestCase):
    def setUp(self):
        self.ergebnis = _auswertung(pnl=False)

    def test_onchain_datum_bleibt_untergrenze(self):
        eintrag = self.ergebnis["eintraege"][0]
        self.assertEqual(eintrag["datum"], "01.07.2024")
        self.assertEqual(eintrag["time_ts"], int(datetime(2024, 7, 1, 18, 0).timestamp()))
        self.assertTrue(eintrag["boerse_belegt"])
        self.assertEqual(eintrag["boerse_label"], "laut Kraken")
        self.assertEqual(len(eintrag["boerse_lose"]), 2)
        self.assertIsNone(eintrag["boerse_lose"][0].get("ergebnis"))
        self.assertNotIn("ergebnis", eintrag["boerse_lose"][0])

    def test_einzelpreise_nicht_gemittelt(self):
        lose = self.ergebnis["eintraege"][0]["boerse_lose"]
        self.assertEqual(lose[0]["einzelpreis"], "50000.00")
        self.assertEqual(lose[0]["sats"], 100_000)
        self.assertEqual(lose[0]["datum"], "01.03.2024")
        self.assertEqual(lose[1]["einzelpreis"], "60000.00")
        self.assertEqual(lose[1]["sats"], 50_000)
        self.assertEqual(lose[1]["datum"], "01.06.2024")
        self.assertEqual(lose[0]["label"], "laut Kraken")

    def test_csv_hat_lose_ohne_gewinnspalten(self):
        text = als_csv(self.ergebnis).decode("utf-8-sig")
        self.assertIn("laut Börse", text)
        self.assertIn("Einzelkaufpreis", text)
        self.assertIn("laut Kraken", text)
        self.assertIn("50000.00 EUR/BTC", text)
        self.assertIn("60000.00 EUR/BTC", text)
        self.assertNotIn("Ergebnis laut Börse", text)
        self.assertNotIn("Summe Ergebnis laut Börse", text)
        self.assertNotIn("Wert zum Bezugstag", text)

    def test_html_ohne_gewinnsumme(self):
        html = als_bericht(self.ergebnis).decode("utf-8")
        self.assertIn("laut Kraken", html)
        self.assertIn("Einzelkaufpreis", html)
        self.assertNotIn("Summe Ergebnis laut Börse", html)
        self.assertIn("Börsenbeleg", html)

    def test_hinweis_kein_pnl(self):
        text = " ".join(self.ergebnis["hinweise"])
        self.assertTrue(any("tax.hintExchangeNoPnl" in h or "saldieren" in h or "Profit" in h or "Gewinn" in h or "net" in h.lower() or "switched off" in h.lower() or "ausgeschaltet" in h for h in self.ergebnis["hinweise"]))


class BerichtMitPnlTest(unittest.TestCase):
    def setUp(self):
        self.ergebnis = _auswertung(pnl=True, kurs=Decimal("70000"))

    def test_ergebnis_je_los_nicht_als_schnitt(self):
        lose = self.ergebnis["eintraege"][0]["boerse_lose"]
        # 100k sats * 70000 / 1e8 = 70, kosten 50 → 20
        #  50k sats * 70000 / 1e8 = 35, kosten 30 → 5
        self.assertEqual(lose[0]["wert_bezug"], "70.00")
        self.assertEqual(lose[0]["ergebnis"], "20.00")
        self.assertEqual(lose[1]["wert_bezug"], "35.00")
        self.assertEqual(lose[1]["ergebnis"], "5.00")
        self.assertEqual(self.ergebnis["boerse_pnl_summen"]["EUR"], "25.00")

    def test_csv_und_html_haben_summe_nur_wenn_an(self):
        text = als_csv(self.ergebnis).decode("utf-8-sig")
        self.assertIn("Ergebnis laut Börse", text)
        self.assertIn("Summe Ergebnis laut Börse (EUR)", text)
        self.assertIn("25.00", text)
        html = als_bericht(self.ergebnis).decode("utf-8")
        self.assertIn("Summe Ergebnis laut Börse", html)
        self.assertIn("25.00 EUR", html)


class OhneZuordnungUnveraendertTest(unittest.TestCase):
    def test_ohne_kontext_keine_boerse_lose(self):
        ergebnis = auswerten(
            [utxo(150_000, "01.07.2024 18:00", marker="m8b")],
            2026,
            jetzt=NACH_JAHRESENDE,
            boerse_kontext=False,
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertFalse(eintrag.get("boerse_belegt"))
        self.assertFalse(eintrag.get("boerse_lose"))
        self.assertEqual(eintrag["datum"], "01.07.2024")
        self.assertFalse(ergebnis["boerse_pnl"])


if __name__ == "__main__":
    unittest.main()
