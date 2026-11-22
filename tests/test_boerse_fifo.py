"""Börsen-FIFO: einzelne Lose, kein Durchschnittspreis, Logs ohne Geheimnisse."""
from __future__ import annotations

import io
import logging
import unittest
from datetime import datetime
from decimal import Decimal

from core.boerse.fifo import (
    BoerseLos,
    FifoFehler,
    anzeige_name,
    fifo_konto,
    lose_fuer_auszahlung,
    nimm_lose,
)
from core.boerse.modell import Art, Buchung
from core.boerse.bericht import lose_im_netz, parse_boerse_pnl
from core.boerse.overlay import BoerseKontext


T1 = int(datetime(2024, 3, 1, 12, 0).timestamp())
T2 = int(datetime(2024, 6, 1, 12, 0).timestamp())
T3 = int(datetime(2024, 7, 1, 12, 0).timestamp())
T4 = int(datetime(2024, 8, 1, 12, 0).timestamp())


def _b(
    art: Art,
    sats: int,
    *,
    ref: str = "r",
    zeit: int = T1,
    zeile: int = 1,
    gebuehr: int = 0,
    fiat=None,
    fiat_gebuehr=None,
    waehrung: str | None = "EUR",
    kurs=None,
    konto: str = "kraken",
    lightning: bool = False,
) -> Buchung:
    return Buchung(
        konto=konto,
        ref=ref,
        gruppe=None,
        zeit_ts=zeit,
        zeit_zone_belegt=True,
        art=art,
        sats=sats,
        gebuehr_sats=gebuehr,
        fiat=None if fiat is None else Decimal(str(fiat)),
        fiat_gebuehr=None if fiat_gebuehr is None else Decimal(str(fiat_gebuehr)),
        waehrung=waehrung,
        kurs=None if kurs is None else Decimal(str(kurs)),
        txid=None,
        adresse=None,
        lightning=lightning,
        roh_typ=str(art),
        roh_subtyp=None,
        datei="x",
        zeile=zeile,
    )


class AnzeigeNameTest(unittest.TestCase):
    def test_kraken_und_fremdname(self):
        self.assertEqual(anzeige_name("kraken"), "Kraken")
        self.assertEqual(anzeige_name("kraken-giro", "kraken"), "Kraken")
        self.assertEqual(anzeige_name("x", name="Kraken"), "Kraken")


class FifoKeinDurchschnittTest(unittest.TestCase):
    def test_zwei_kaeufe_werden_nicht_gemittelt(self):
        kauf1 = _b(Art.KAUF, 100_000, ref="k1", zeit=T1, zeile=1, fiat="-50", kurs="50000")
        kauf2 = _b(Art.KAUF, 100_000, ref="k2", zeit=T2, zeile=2, fiat="-60", kurs="60000")
        aus = _b(Art.BTC_AUSGANG, -150_000, ref="a1", zeit=T3, zeile=3, waehrung=None)
        lose = lose_fuer_auszahlung([kauf1, kauf2, aus], "a1", boerse_typ="kraken")
        self.assertEqual(len(lose), 2)
        self.assertEqual(lose[0].sats, 100_000)
        self.assertEqual(lose[0].einzelpreis_btc, Decimal("50000.00000000"))
        self.assertEqual(lose[0].kosten, Decimal("50.00000000"))
        self.assertEqual(lose[0].zeit_ts, T1)
        self.assertEqual(lose[1].sats, 50_000)
        self.assertEqual(lose[1].einzelpreis_btc, Decimal("60000.00000000"))
        self.assertEqual(lose[1].kosten, Decimal("30.00000000"))
        self.assertEqual(lose[1].zeit_ts, T2)
        self.assertEqual(lose[0].label(), "laut Kraken")
        # Kein gemittelter Preis 53333...
        self.assertNotEqual(lose[0].einzelpreis_btc, lose[1].einzelpreis_btc)

    def test_verkauf_dann_gebuehr_dann_auszahlung(self):
        kauf = _b(Art.KAUF, 200_000, ref="k1", zeit=T1, fiat="-100", kurs="50000")
        verkauf = _b(Art.VERKAUF, -50_000, ref="v1", zeit=T2, zeile=2, gebuehr=1_000, fiat="30")
        aus = _b(Art.BTC_AUSGANG, -149_000, ref="a1", zeit=T3, zeile=3, waehrung=None)
        lose = lose_fuer_auszahlung([kauf, verkauf, aus], "a1")
        self.assertEqual(len(lose), 1)
        self.assertEqual(lose[0].sats, 149_000)
        self.assertEqual(lose[0].einzelpreis_btc, Decimal("50000.00000000"))

    def test_einzahlung_ohne_kaufpreis(self):
        ein = _b(Art.BTC_EINGANG, 80_000, ref="e1", zeit=T1, waehrung=None, fiat=None)
        aus = _b(Art.BTC_AUSGANG, -80_000, ref="a1", zeit=T3, zeile=2, waehrung=None)
        lose = lose_fuer_auszahlung([ein, aus], "a1", boerse_typ="strike")
        self.assertEqual(len(lose), 1)
        self.assertIsNone(lose[0].kosten)
        self.assertIsNone(lose[0].einzelpreis_btc)
        self.assertEqual(lose[0].kauf_art, "btc_eingang")
        self.assertEqual(lose[0].label(), "laut Strike")

    def test_bestand_zu_klein_liefert_fehler_ohne_lose(self):
        kauf = _b(Art.KAUF, 50_000, ref="k1", zeit=T1, fiat="-25")
        aus = _b(Art.BTC_AUSGANG, -80_000, ref="a1", zeit=T3, zeile=2, waehrung=None)
        zu, _rest, fehler = fifo_konto([kauf, aus])
        self.assertEqual(zu, {})
        self.assertEqual(len(fehler), 1)
        self.assertIsInstance(fehler[0], FifoFehler)
        self.assertEqual(fehler[0].grund, "bestand_zu_klein")

    def test_fremde_waehrung_wird_uebersprungen(self):
        kauf = _b(Art.KAUF, 100_000, ref="k1", zeit=T1, fiat="-50", waehrung="GBP")
        aus = _b(Art.BTC_AUSGANG, -100_000, ref="a1", zeit=T3, zeile=2, waehrung=None)
        zu, _rest, fehler = fifo_konto([kauf, aus])
        self.assertEqual(len(fehler), 1)
        self.assertEqual(zu, {})

    def test_intern_aendert_bestand_nicht(self):
        kauf = _b(Art.KAUF, 100_000, ref="k1", zeit=T1, fiat="-50")
        intern_ab = _b(Art.INTERN, -100_000, ref="i1", zeit=T2, zeile=2, waehrung=None)
        intern_zu = _b(Art.INTERN, 100_000, ref="i2", zeit=T2, zeile=3, waehrung=None)
        aus = _b(Art.BTC_AUSGANG, -100_000, ref="a1", zeit=T3, zeile=4, waehrung=None)
        lose = lose_fuer_auszahlung([kauf, intern_ab, intern_zu, aus], "a1")
        self.assertEqual(len(lose), 1)
        self.assertEqual(lose[0].sats, 100_000)

    def test_konten_getrennt(self):
        k1 = _b(Art.KAUF, 100_000, ref="k1", zeit=T1, fiat="-50", konto="kraken")
        k2 = _b(Art.KAUF, 100_000, ref="k2", zeit=T1, fiat="-80", konto="coinbase", waehrung="USD")
        a1 = _b(Art.BTC_AUSGANG, -100_000, ref="a-kr", zeit=T3, zeile=3, konto="kraken", waehrung=None)
        a2 = _b(Art.BTC_AUSGANG, -100_000, ref="a-cb", zeit=T3, zeile=4, konto="coinbase", waehrung=None)
        zu, _rest, fehler = fifo_konto([k1, k2, a1, a2])
        self.assertEqual(fehler, [])
        self.assertEqual(zu["a-kr"][0].kosten, Decimal("50.00000000"))
        self.assertEqual(zu["a-kr"][0].boerse, "Kraken")
        self.assertEqual(zu["a-cb"][0].kosten, Decimal("80.00000000"))
        self.assertEqual(zu["a-cb"][0].boerse, "Coinbase")
        self.assertEqual(zu["a-cb"][0].waehrung, "USD")


class NimmLoseTest(unittest.TestCase):
    def test_nimmt_aeltestes_los_ganz_nicht_anteilig(self):
        a = BoerseLos(sats=60_000, zeit_ts=T1, konto="k", boerse="Kraken",
                      kauf_art="kauf", einzelpreis_btc=Decimal("50000"),
                      waehrung="EUR", kosten=Decimal("30"))
        b = BoerseLos(sats=40_000, zeit_ts=T2, konto="k", boerse="Kraken",
                      kauf_art="kauf", einzelpreis_btc=Decimal("60000"),
                      waehrung="EUR", kosten=Decimal("24"))
        teil = nimm_lose((a, b), 50_000)
        self.assertEqual(len(teil), 1)
        self.assertEqual(teil[0].sats, 50_000)
        self.assertEqual(teil[0].einzelpreis_btc, Decimal("50000"))
        self.assertEqual(teil[0].kosten, Decimal("25.00000000"))


class NetzFifoTest(unittest.TestCase):
    def test_spaeterer_hop_nimmt_fifo_nicht_den_schnitt(self):
        kontext = BoerseKontext()
        kontext.setze("aa" * 32, 0, (
            BoerseLos(sats=100_000, zeit_ts=T1, konto="k", boerse="Kraken",
                      kauf_art="kauf", einzelpreis_btc=Decimal("50000"),
                      waehrung="EUR", kosten=Decimal("50")),
            BoerseLos(sats=100_000, zeit_ts=T2, konto="k", boerse="Kraken",
                      kauf_art="kauf", einzelpreis_btc=Decimal("60000"),
                      waehrung="EUR", kosten=Decimal("60")),
        ))
        empfaenger = "aa" * 32 + ":0"
        fokus = "bb" * 32 + ":0"
        netz = {
            "fokus_key": fokus,
            "fokus_sats": 150_000,
            "kanten": [{"von": empfaenger, "nach": fokus, "sats": 150_000}],
        }
        lose = lose_im_netz(netz, kontext)
        self.assertEqual([l.sats for l in lose], [100_000, 50_000])
        self.assertEqual(lose[0].einzelpreis_btc, Decimal("50000"))
        self.assertEqual(lose[1].einzelpreis_btc, Decimal("60000"))
        self.assertEqual(lose[1].kosten, Decimal("30.00000000"))


class PnlSchalterTest(unittest.TestCase):
    def test_default_aus(self):
        self.assertFalse(parse_boerse_pnl(None))
        self.assertFalse(parse_boerse_pnl(""))
        self.assertFalse(parse_boerse_pnl("0"))
        self.assertFalse(parse_boerse_pnl("nein"))
        self.assertTrue(parse_boerse_pnl("1"))
        self.assertTrue(parse_boerse_pnl("ja"))
        self.assertTrue(parse_boerse_pnl(True))


class LogOhneGeheimnisseTest(unittest.TestCase):
    def test_fifo_log_enthaelt_keine_refs(self):
        kauf = _b(
            Art.KAUF, 100_000, ref="TSYN01-00000-000001", zeit=T1, fiat="-50",
        )
        aus = _b(Art.BTC_AUSGANG, -100_000, ref="TSYN01-00000-000009", zeit=T3, zeile=2, waehrung=None)
        with self.assertLogs("satsage.boerse", level="INFO") as cm:
            fifo_konto([kauf, aus])
        text = "\n".join(cm.output)
        self.assertNotIn("TSYN01-00000-000001", text)
        self.assertNotIn("TSYN01-00000-000009", text)
        self.assertIn("boerse_fifo", text)
        self.assertIn("n_kauf=1", text)
        self.assertIn("n_auszahlung=1", text)


if __name__ == "__main__":
    unittest.main()
