"""
Steuerjahr-Auswertung und Export.

Hier landen Zahlen in einem Dokument, das an das Finanzamt geht. Entsprechend
kleinlich: Fristgrenzen auf den Tag, Schaltjahre, Beträge ohne Rundungsverlust
und ein Export, den Excel unter Windows richtig einliest.
"""
import csv
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import main
from core import tax
from core.tax import (
    STANDARD_HALTEFRIST_JAHRE,
    bezugsdatum,
    als_bericht,
    als_csv,
    auswerten,
    plus_jahre,
    stichtag,
    verfuegbare_jahre,
)
from tests.fixtures import BIP84_RECEIVE_0, BIP84_ZPUB, txid


def zeitstempel(datum: str) -> int:
    return int(datetime.strptime(datum, "%d.%m.%Y %H:%M").timestamp())


def utxo(sats, datum, *, marker="a1", vout=0, adresse=BIP84_RECEIVE_0):
    return {
        "txid": txid(marker), "vout": vout, "address": adresse, "value": sats,
        "status": {"confirmed": True, "block_height": 800_000,
                   "block_time": zeitstempel(datum)},
    }


#: Zeitpunkt nach Ablauf von 2026. Wer damit auswertet, bekommt den 31.12. als
#: Bezug — unabhängig davon, wann die Testsuite tatsächlich läuft.
NACH_JAHRESENDE = datetime(2027, 1, 1, 12, 0)


def auswerten_zum_jahresende(utxos, jahr=2026, **kw):
    """Wertet aus, als wäre das Jahr abgeschlossen."""
    return auswerten(utxos, jahr, jetzt=NACH_JAHRESENDE, **kw)



class TestDatumsrechnung(unittest.TestCase):

    def test_ein_jahr_dazu(self):
        self.assertEqual(
            plus_jahre(datetime(2024, 9, 14), 1), datetime(2025, 9, 14)
        )

    def test_schaltjahr_wird_aufgefangen(self):
        """29.02. gibt es im Folgejahr nicht — ohne Behandlung ein ValueError."""
        self.assertEqual(
            plus_jahre(datetime(2024, 2, 29), 1), datetime(2025, 2, 28)
        )

    def test_schaltjahr_auf_schaltjahr_bleibt_der_29(self):
        """
        Die Rückfalllösung greift nur, wenn das Zieljahr den Tag nicht kennt.
        2028 ist ein Schaltjahr — dort bleibt der 29.02. stehen.
        """
        self.assertEqual(
            plus_jahre(datetime(2024, 2, 29), 4), datetime(2028, 2, 29)
        )

    def test_zehn_jahre(self):
        self.assertEqual(
            plus_jahre(datetime(2016, 1, 1), 10), datetime(2026, 1, 1)
        )

    def test_stichtag_ist_jahresende(self):
        self.assertEqual(stichtag(2026), datetime(2026, 12, 31, 23, 59, 59))


class TestFristgrenzen(unittest.TestCase):
    """Der Übergang erfüllt/offen muss auf den Tag genau stimmen."""

    def test_genau_ein_jahr_vor_dem_stichtag_ist_erfuellt(self):
        ergebnis = auswerten_zum_jahresende([utxo(100_000, "31.12.2025 12:00")], 2026)
        self.assertTrue(ergebnis["eintraege"][0]["erfuellt"])

    def test_kurz_vor_jahresende_erworben_ist_offen(self):
        ergebnis = auswerten_zum_jahresende([utxo(100_000, "30.12.2026 12:00")], 2026)
        self.assertFalse(ergebnis["eintraege"][0]["erfuellt"])

    def test_frist_endet_exakt_am_stichtag(self):
        """Frist läuft am 31.12. ab — das zählt noch als erfüllt."""
        ergebnis = auswerten_zum_jahresende([utxo(100_000, "31.12.2025 23:00")], 2026)
        eintrag = ergebnis["eintraege"][0]
        self.assertEqual(eintrag["frist_ende"], "31.12.2026")
        self.assertTrue(eintrag["erfuellt"])

    def test_ohne_haltefrist_gilt_alles_als_erfuellt(self):
        ergebnis = auswerten_zum_jahresende(
            [utxo(100_000, "30.12.2026 12:00")], 2026, haltefrist_jahre=0
        )
        self.assertTrue(ergebnis["eintraege"][0]["erfuellt"])
        self.assertEqual(ergebnis["eintraege"][0]["frist_ende"], "")

    def test_zehnjahresfrist(self):
        ergebnis = auswerten_zum_jahresende(
            [utxo(100_000, "14.09.2024 09:00")], 2026, haltefrist_jahre=10
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertEqual(eintrag["frist_ende"], "14.09.2034")
        self.assertFalse(eintrag["erfuellt"])

    def test_stichtag_altbestand_nutzt_haltefrist(self):
        from core.tax import OESTERREICH_ALTBESTAND
        ergebnis = auswerten_zum_jahresende(
            [utxo(100_000, "01.01.2020 12:00")], 2026,
            haltefrist_jahre=1, stichtag=OESTERREICH_ALTBESTAND,
        )
        self.assertTrue(ergebnis["eintraege"][0]["erfuellt"])
        self.assertFalse(ergebnis["eintraege"][0]["neuvermoegen"])

    def test_stichtag_neuvermoegen_wird_nicht_durch_halten_frei(self):
        """Österreich: nach dem 28.02.2021 keine Steuerfreiheit durch Halten."""
        from core.tax import OESTERREICH_ALTBESTAND
        ergebnis = auswerten_zum_jahresende(
            [utxo(100_000, "01.06.2022 12:00")], 2026,
            haltefrist_jahre=1, stichtag=OESTERREICH_ALTBESTAND,
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertFalse(eintrag["erfuellt"])
        self.assertTrue(eintrag["neuvermoegen"])
        self.assertEqual(eintrag["frist_ende"], "")
        self.assertEqual(ergebnis["stichtag_regel"], "28.02.2021")


class TestJahresabgrenzung(unittest.TestCase):

    def test_eingang_nach_dem_stichtag_zaehlt_nicht(self):
        """Ein Zufluss aus 2027 gehört nicht ins Steuerjahr 2026."""
        ergebnis = auswerten_zum_jahresende([utxo(100_000, "05.01.2027 12:00")], 2026)
        self.assertEqual(ergebnis["kennzahlen"]["gesamt_count"], 0)

    def test_eingang_aus_frueheren_jahren_zaehlt_mit(self):
        """Bestand ist kumulativ — was 2020 kam, liegt 2026 noch da."""
        ergebnis = auswerten_zum_jahresende([utxo(100_000, "01.06.2020 12:00")], 2026)
        self.assertEqual(ergebnis["kennzahlen"]["gesamt_count"], 1)
        self.assertTrue(ergebnis["eintraege"][0]["erfuellt"])

    def test_utxo_ohne_datum_wird_gezaehlt_aber_nicht_gewertet(self):
        ohne = {"txid": txid("z9"), "vout": 0, "address": BIP84_RECEIVE_0,
                "value": 5000, "status": {"confirmed": False}}
        ergebnis = auswerten_zum_jahresende([utxo(100_000, "01.06.2020 12:00"), ohne], 2026)
        self.assertEqual(ergebnis["kennzahlen"]["gesamt_count"], 1)
        self.assertEqual(ergebnis["kennzahlen"]["ohne_datum"], 1)

    def test_sortierung_nach_zeitpunkt(self):
        ergebnis = auswerten_zum_jahresende([
            utxo(1, "01.06.2026 12:00", marker="c3"),
            utxo(2, "01.01.2020 12:00", marker="a1"),
            utxo(3, "01.03.2023 12:00", marker="b2"),
        ], 2026)
        daten = [e["datum"] for e in ergebnis["eintraege"]]
        self.assertEqual(daten, ["01.01.2020", "01.03.2023", "01.06.2026"])


class TestKennzahlen(unittest.TestCase):

    def setUp(self):
        self.ergebnis = auswerten_zum_jahresende([
            utxo(84_000_000, "14.09.2024 09:00", marker="a1"),
            utxo(51_000_000, "02.02.2025 10:00", marker="b2"),
            utxo(124_500, "28.11.2026 04:00", marker="c3"),
        ], 2026)

    def test_summen_stimmen(self):
        kennzahlen = self.ergebnis["kennzahlen"]
        self.assertEqual(kennzahlen["gesamt_sats"], 135_124_500)
        self.assertEqual(kennzahlen["erfuellt_sats"], 135_000_000)
        self.assertEqual(kennzahlen["offen_sats"], 124_500)

    def test_summen_ergaenzen_sich(self):
        kennzahlen = self.ergebnis["kennzahlen"]
        self.assertEqual(
            kennzahlen["erfuellt_sats"] + kennzahlen["offen_sats"],
            kennzahlen["gesamt_sats"],
        )
        self.assertEqual(
            kennzahlen["erfuellt_count"] + kennzahlen["offen_count"],
            kennzahlen["gesamt_count"],
        )

    def test_naechste_frist_wird_genannt(self):
        self.assertEqual(self.ergebnis["kennzahlen"]["naechste_frist"], "28.11.2027")

    def test_stichtag_und_erstelldatum_dabei(self):
        self.assertEqual(self.ergebnis["stichtag"], "31.12.2026")
        self.assertTrue(self.ergebnis["erstellt"])

    def test_hinweise_sind_enthalten(self):
        text = " ".join(self.ergebnis["hinweise"])
        self.assertIn("keine Steuerberatung", text)
        self.assertIn("Börsenhistorien", text)
        self.assertIn("Kaufbelege", text)
        self.assertIn("unverbrauchte", text)


class TestWalletZuordnung(unittest.TestCase):

    def test_wallet_name_wird_uebernommen(self):
        ctx = main.build_wallet_context(
            [BIP84_ZPUB], wallet_names=["Cold Storage"], max_addresses=6
        )
        ergebnis = auswerten_zum_jahresende([utxo(1000, "01.01.2024 12:00")], 2026, wallet=ctx)
        self.assertEqual(ergebnis["eintraege"][0]["wallet"], "Cold Storage")

    def test_ohne_zuordnung_unbekannt(self):
        ergebnis = auswerten_zum_jahresende([utxo(1000, "01.01.2024 12:00")], 2026)
        self.assertEqual(ergebnis["eintraege"][0]["wallet"], "unbekannt")


class TestVerfuegbareJahre(unittest.TestCase):

    def test_jahre_ab_dem_ersten_eingang(self):
        jahre = verfuegbare_jahre([utxo(1, "01.06.2023 12:00")])
        self.assertIn(2023, jahre)
        self.assertIn(datetime.now().year, jahre)
        self.assertEqual(jahre, sorted(jahre, reverse=True))

    def test_ohne_eingaenge_keine_jahre(self):
        self.assertEqual(verfuegbare_jahre([]), [])


class TestBezugsdatum(unittest.TestCase):
    """
    Gegen welchen Zeitpunkt Fristen gerechnet werden.

    Für abgeschlossene Jahre der 31.12., für das laufende Jahr der heutige
    Tag. Nähme man auch beim laufenden Jahr das Jahresende, gälten Beträge
    als fristerfüllt, deren Jahr erst später abläuft — wer danach entscheidet,
    was er heute verkaufen kann, bekäme zu viel angezeigt.
    """

    def test_abgeschlossenes_jahr_endet_am_31_12(self):
        zeitpunkt, laufend = bezugsdatum(2024, datetime(2026, 7, 21, 12, 0))
        self.assertEqual(zeitpunkt, datetime(2024, 12, 31, 23, 59, 59))
        self.assertFalse(laufend)

    def test_laufendes_jahr_nimmt_heute(self):
        heute = datetime(2026, 7, 21, 12, 0)
        zeitpunkt, laufend = bezugsdatum(2026, heute)
        self.assertEqual(zeitpunkt, heute)
        self.assertTrue(laufend)

    def test_am_letzten_tag_des_jahres_noch_laufend(self):
        heute = datetime(2026, 12, 31, 12, 0)
        zeitpunkt, laufend = bezugsdatum(2026, heute)
        self.assertEqual(zeitpunkt, heute)
        self.assertTrue(laufend)

    def test_nach_jahresende_nicht_mehr_laufend(self):
        zeitpunkt, laufend = bezugsdatum(2026, datetime(2027, 1, 1, 0, 0))
        self.assertEqual(zeitpunkt, datetime(2026, 12, 31, 23, 59, 59))
        self.assertFalse(laufend)


class TestLaufendesJahr(unittest.TestCase):
    """Der gemeldete Fehler: Fristgrenze lag im laufenden Jahr am 31.12."""

    HEUTE = datetime(2026, 7, 21, 12, 0)

    def test_fristgrenze_ist_heute_minus_haltefrist(self):
        ergebnis = auswerten(
            [utxo(1000, "01.01.2024 12:00")], 2026, jetzt=self.HEUTE
        )
        self.assertEqual(ergebnis["stichtag"], "21.07.2026")
        self.assertTrue(ergebnis["laufend"])

    def test_eingang_gilt_erst_nach_einem_vollen_jahr_als_erfuellt(self):
        """
        Ein Zufluss vom 01.10.2025 ist am 21.07.2026 noch keine zwölf Monate
        alt — gegen den 31.12.2026 gerechnet sähe er fälschlich erfüllt aus.
        """
        ergebnis = auswerten(
            [utxo(1000, "01.10.2025 12:00")], 2026, jetzt=self.HEUTE
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertFalse(eintrag["erfuellt"])
        self.assertEqual(eintrag["frist_ende"], "01.10.2026")

    def test_gegenprobe_abgeschlossenes_jahr(self):
        """Für 2025 zählt weiterhin der 31.12.2025."""
        ergebnis = auswerten(
            [utxo(1000, "01.10.2024 12:00")], 2025, jetzt=self.HEUTE
        )
        self.assertEqual(ergebnis["stichtag"], "31.12.2025")
        self.assertFalse(ergebnis["laufend"])
        self.assertTrue(ergebnis["eintraege"][0]["erfuellt"])

    def test_haltedauer_zaehlt_bis_heute(self):
        ergebnis = auswerten(
            [utxo(1000, "21.07.2025 12:00")], 2026, jetzt=self.HEUTE
        )
        self.assertEqual(ergebnis["eintraege"][0]["haltedauer_tage"], 365)

    def test_zeitstrahl_setzt_die_grenze_auf_heute_minus_frist(self):
        ergebnis = auswerten([
            utxo(1000, "01.01.2024 12:00", marker="a1"),
            utxo(2000, "01.03.2026 12:00", marker="b2"),
        ], 2026, jetzt=self.HEUTE)
        self.assertEqual(ergebnis["zeitstrahl"]["frist_datum"], "21.07.2025")

    def test_beschriftung_nennt_den_bezug(self):
        ergebnis = auswerten([utxo(1000, "01.01.2024 12:00")], 2026,
                             jetzt=self.HEUTE)
        self.assertIn("Stand heute", ergebnis["stichtag_label"])

        abgeschlossen = auswerten([utxo(1000, "01.01.2023 12:00")], 2024,
                                  jetzt=self.HEUTE)
        self.assertIn("Stichtag", abgeschlossen["stichtag_label"])

    def test_hinweis_erklaert_den_laufenden_bezug(self):
        ergebnis = auswerten([utxo(1000, "01.01.2024 12:00")], 2026,
                             jetzt=self.HEUTE)
        text = " ".join(ergebnis["hinweise"])
        self.assertIn("läuft noch", text)
        self.assertIn("heutigen Tag", text)

    def test_abgeschlossenes_jahr_ohne_diesen_hinweis(self):
        ergebnis = auswerten([utxo(1000, "01.01.2023 12:00")], 2024,
                             jetzt=self.HEUTE)
        self.assertNotIn("läuft noch", " ".join(ergebnis["hinweise"]))

    def test_export_nennt_stand_statt_stichtag(self):
        ergebnis = auswerten([utxo(1000, "01.01.2024 12:00")], 2026,
                             jetzt=self.HEUTE)
        text = als_csv(ergebnis).decode("utf-8-sig")
        self.assertIn("Stand heute;21.07.2026", text)
        self.assertIn("läuft noch", text)

    def test_bericht_nennt_stand_statt_stichtag(self):
        ergebnis = auswerten([utxo(1000, "01.01.2024 12:00")], 2026,
                             jetzt=self.HEUTE)
        html = als_bericht(ergebnis).decode("utf-8")
        self.assertIn("Stand heute 21.07.2026", html)


class TestAnschaffungsdatum(unittest.TestCase):
    """
    Welcher Zeitpunkt zählt.

    Das Entstehungsdatum eines Outputs taugt nur bei Zuflüssen von außen.
    Wechselgeld, Konsolidierungen und Eigenüberträge erzeugen neue Outputs aus
    Coins, die längst zum Bestand gehörten — dort läge die Frist sonst
    fälschlich neu an. Die Herkunftsanalyse liefert das richtige Datum.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name)
        self.ingress = self.cache / main.UTXO_INGRESS_CACHE_SUBDIR
        self.ingress.mkdir(parents=True)

    def herkunft_hinterlegen(self, marker, vout, datum):
        """Vollständige Herkunftsanalyse: datierter externer Zufluss."""
        zeit = datetime.strptime(datum, "%d.%m.%Y %H:%M")
        (self.ingress / f"{txid(marker)}_{vout}.json").write_text(
            json.dumps({
                "txid": txid(marker), "vout": vout,
                "youngest_time": zeit.strftime("%Y-%m-%d %H:%M"),
                "youngest_time_ts": int(zeit.timestamp()),
                "external_time_ts": int(zeit.timestamp()),
            }),
            encoding="utf-8",
        )

    def test_ohne_herkunft_gilt_das_output_datum(self):
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00")], immutable_cache_dir=self.cache
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertEqual(eintrag["datum"], "01.10.2026")
        self.assertFalse(eintrag["geprueft"])
        self.assertEqual(eintrag["grundlage_label"], "nur Output-Datum")

    def test_herkunft_schlaegt_das_output_datum(self):
        """
        Der Kernfall: Ein Wechselgeld-UTXO von 2026 aus Coins von 2020. Ohne
        Herkunft gälte die Frist als offen, obwohl sie längst erfüllt ist.
        """
        self.herkunft_hinterlegen("a1", 0, "15.03.2020 09:00")
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertEqual(eintrag["datum"], "15.03.2020")
        self.assertTrue(eintrag["geprueft"])
        self.assertTrue(eintrag["erfuellt"])

    def test_haltedauer_folgt_dem_anschaffungsdatum(self):
        self.herkunft_hinterlegen("a1", 0, "31.12.2024 12:00")
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        # Vom 31.12.2024 bis 31.12.2026 sind es zwei Jahre.
        self.assertGreater(ergebnis["eintraege"][0]["haltedauer_tage"], 700)

    def test_abweichendes_output_datum_wird_vermerkt(self):
        self.herkunft_hinterlegen("a1", 0, "15.03.2020 09:00")
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        self.assertIn("01.10.2026", ergebnis["eintraege"][0]["herkunft"])

    def test_kennzahl_zaehlt_die_ungepruefften(self):
        self.herkunft_hinterlegen("a1", 0, "15.03.2020 09:00")
        ergebnis = auswerten_zum_jahresende([
            utxo(1000, "01.10.2026 12:00", marker="a1"),
            utxo(2000, "01.11.2026 12:00", marker="b2"),
            utxo(4000, "01.12.2026 12:00", marker="c3"),
        ], immutable_cache_dir=self.cache)
        kennzahlen = ergebnis["kennzahlen"]
        self.assertEqual(kennzahlen["geprueft_count"], 1)
        self.assertEqual(kennzahlen["ungeprueft_count"], 2)
        self.assertEqual(kennzahlen["ungeprueft_sats"], 6000)

    def test_hinweis_nennt_die_richtung_des_fehlers(self):
        """
        Wichtig für den Leser: Der Fehler geht zu seinen Ungunsten. Er zahlt
        womöglich auf Gewinne, die längst steuerfrei wären.
        """
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00")], immutable_cache_dir=self.cache
        )
        text = " ".join(ergebnis["hinweise"])
        self.assertIn("unterschätzt", text)
        self.assertIn("Wechselgeld", text)

    def test_ohne_ungepruefte_kein_hinweis(self):
        self.herkunft_hinterlegen("a1", 0, "15.03.2020 09:00")
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        self.assertNotIn("unterschätzt", " ".join(ergebnis["hinweise"]))

    def test_kaputter_zeitstempel_faellt_auf_das_output_datum_zurueck(self):
        (self.ingress / f"{txid('a1')}_0.json").write_text(
            json.dumps({"txid": txid("a1"), "vout": 0,
                        "youngest_time_ts": "unsinn"}),
            encoding="utf-8",
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        self.assertEqual(ergebnis["eintraege"][0]["datum"], "01.10.2026")
        self.assertFalse(ergebnis["eintraege"][0]["geprueft"])

    def test_export_weist_die_grundlage_aus(self):
        self.herkunft_hinterlegen("a1", 0, "15.03.2020 09:00")
        ergebnis = auswerten_zum_jahresende([
            utxo(1000, "01.10.2026 12:00", marker="a1"),
            utxo(2000, "01.11.2026 12:00", marker="b2"),
        ], immutable_cache_dir=self.cache)

        csv_text = als_csv(ergebnis).decode("utf-8-sig")
        self.assertIn("Grundlage Anschaffungsdatum", csv_text)
        self.assertIn("Herkunft verfolgt", csv_text)
        self.assertIn("nur Output-Datum", csv_text)
        self.assertIn("ohne Herkunftsanalyse", csv_text)

        html = als_bericht(ergebnis).decode("utf-8")
        self.assertIn("Grundlage", html)
        self.assertIn("nur Output-Datum", html)


class TestExternerZuflussDatum(unittest.TestCase):
    """
    Steuerliches Anschaffungsdatum = jüngster externer Zufluss.

    Interne Überträge zwischen eigenen Wallets — auch über verschiedene
    XPUBs oder Seeds hinweg — verändern die Haltedauer nicht. Erst Geld von
    außen beginnt sie. Der Ingress-Cache trägt dafür external_time_ts; der
    ältere youngest_time_ts bleibt als Rückfall bestehen.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name)
        self.ingress = self.cache / main.UTXO_INGRESS_CACHE_SUBDIR
        self.ingress.mkdir(parents=True)

    def hinterlegen(self, marker, vout, **felder):
        payload = {"txid": txid(marker), "vout": vout}
        payload.update(felder)
        (self.ingress / f"{txid(marker)}_{vout}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_external_time_ts_schlaegt_wallet_eingang(self):
        """
        Kernfall Feature #1: Die Coins kamen 2020 von einer Börse (extern),
        wanderten danach nur noch zwischen eigenen Wallets — letzter interner
        Eingang 2026. Anschaffungsdatum muss 2020 bleiben, nicht 2026.
        """
        self.hinterlegen(
            "a1", 0,
            youngest_time_ts=zeitstempel("01.10.2026 12:00"),
            external_time_ts=zeitstempel("15.03.2020 09:00"),
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertEqual(eintrag["datum"], "15.03.2020")
        self.assertTrue(eintrag["geprueft"])
        self.assertTrue(eintrag["erfuellt"])
        self.assertFalse(eintrag["untergrenze"])

    def test_offensiv_nimmt_aeltesten_zufluss(self):
        """STEUER_ANSCHAFFUNG=aelteste: ältester externer Zufluss zählt."""
        self.hinterlegen(
            "a1", 0,
            external_time_ts=zeitstempel("15.06.2022 12:00"),
            external_oldest_time_ts=zeitstempel("01.03.2021 12:00"),
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
            anschaffung="aelteste",
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertEqual(eintrag["datum"], "01.03.2021")
        self.assertEqual(eintrag["anschaffung"], "aelteste")
        self.assertIn("offensiv", eintrag["grundlage_label"].lower())
        self.assertTrue(
            any("offensiv" in h.lower() for h in ergebnis["hinweise"])
        )

    def test_offensiv_ohne_oldest_faellt_auf_juengste_zurueck(self):
        self.hinterlegen(
            "a1", 0,
            external_time_ts=zeitstempel("15.06.2022 12:00"),
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
            anschaffung="aelteste",
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertEqual(eintrag["datum"], "15.06.2022")
        self.assertTrue(eintrag["offensiv_fallback"])

    def test_alte_cache_eintraege_fallen_auf_wallet_eingang_zurueck(self):
        """Cache-Einträge ohne external_time_ts verhalten sich wie bisher."""
        self.hinterlegen(
            "a1", 0,
            youngest_time_ts=zeitstempel("15.03.2020 09:00"),
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        self.assertEqual(ergebnis["eintraege"][0]["datum"], "15.03.2020")
        self.assertTrue(ergebnis["eintraege"][0]["geprueft"])

    def test_wallet_eingang_wird_als_eigene_grundlage_ausgewiesen(self):
        """
        Ohne datierten externen Zufluss (Esplora liefert keine Blockzeiten
        der Vorgänger) gilt der Wallet-Eingang. Das darf nicht als volle
        Herkunftsanalyse durchgehen — sonst sieht der Leser nicht, dass die
        Haltefrist unterschätzt sein kann.
        """
        self.hinterlegen(
            "a1", 0,
            youngest_time_ts=zeitstempel("15.03.2020 09:00"),
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertEqual(eintrag["grundlage"], tax.GRUNDLAGE_WALLET_EINGANG)
        self.assertEqual(
            eintrag["grundlage_label"], "Herkunft verfolgt (nur Wallet-Eingang)"
        )
        self.assertFalse(eintrag["untergrenze"])
        self.assertEqual(ergebnis["kennzahlen"]["wallet_eingang_count"], 1)
        self.assertEqual(ergebnis["kennzahlen"]["wallet_eingang_sats"], 1000)
        self.assertIn("Wallet-Eingang", " ".join(ergebnis["hinweise"]))

    def test_wallet_eingang_nennt_die_richtung_des_fehlers(self):
        """Der Fehler geht zu Lasten des Nutzers — das muss dastehen."""
        self.hinterlegen(
            "a1", 0, youngest_time_ts=zeitstempel("15.03.2020 09:00")
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        hinweis = " ".join(ergebnis["hinweise"])
        self.assertIn("unterschätzt", hinweis)
        self.assertIn("nie überschätzt", hinweis)

    def test_vollstaendige_herkunft_loest_keinen_wallet_hinweis_aus(self):
        self.hinterlegen(
            "a1", 0,
            youngest_time_ts=zeitstempel("01.10.2026 12:00"),
            external_time_ts=zeitstempel("15.03.2020 09:00"),
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        self.assertEqual(ergebnis["kennzahlen"]["wallet_eingang_count"], 0)
        self.assertNotIn("Wallet-Eingang", " ".join(ergebnis["hinweise"]))

    def test_csv_weist_beide_unsicherheiten_getrennt_aus(self):
        """
        Die zwei Unsicherheiten zeigen in entgegengesetzte Richtungen und
        dürfen im Export nicht zu einer verschmelzen.
        """
        self.hinterlegen(
            "a1", 0, youngest_time_ts=zeitstempel("15.03.2020 09:00")
        )
        self.hinterlegen(
            "b2", 0,
            external_time_ts=zeitstempel("15.03.2020 09:00"),
            external_untergrenze=True,
        )
        ergebnis = auswerten_zum_jahresende(
            [
                utxo(1000, "01.10.2026 12:00", marker="a1"),
                utxo(2000, "01.10.2026 12:00", marker="b2"),
            ],
            immutable_cache_dir=self.cache,
        )
        text = tax.als_csv(ergebnis).decode("utf-8-sig")
        self.assertIn("davon nur Wallet-Eingang", text)
        self.assertIn("davon Anschaffungsdatum als Untergrenze", text)
        self.assertIn("zu kurz ausgewiesen sein", text)
        self.assertIn("zu LANG ausgewiesen sein", text)

    def test_untergrenze_wird_markiert_und_erklaert(self):
        """
        Sammel-Transaktion: nicht alle externen Eingänge konnten aufgelöst
        werden — das Datum kann zu alt sein und muss das sagen.
        """
        self.hinterlegen(
            "a1", 0,
            external_time_ts=zeitstempel("15.03.2020 09:00"),
            external_untergrenze=True,
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        eintrag = ergebnis["eintraege"][0]
        self.assertTrue(eintrag["untergrenze"])
        self.assertIn("Untergrenze", eintrag["grundlage_label"])
        self.assertEqual(ergebnis["kennzahlen"]["untergrenze_count"], 1)
        self.assertIn("Untergrenze", " ".join(ergebnis["hinweise"]))

    def test_ohne_untergrenze_kein_hinweis(self):
        self.hinterlegen(
            "a1", 0,
            external_time_ts=zeitstempel("15.03.2020 09:00"),
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        self.assertNotIn("Untergrenze", " ".join(ergebnis["hinweise"]))

    def test_kaputter_external_ts_faellt_auf_wallet_eingang_zurueck(self):
        self.hinterlegen(
            "a1", 0,
            external_time_ts="unsinn",
            youngest_time_ts=zeitstempel("15.03.2020 09:00"),
        )
        ergebnis = auswerten_zum_jahresende(
            [utxo(1000, "01.10.2026 12:00", marker="a1")],
            immutable_cache_dir=self.cache,
        )
        self.assertEqual(ergebnis["eintraege"][0]["datum"], "15.03.2020")


class TestZeitstrahl(unittest.TestCase):
    """
    Positionen für die Zeitachse. Sie entstehen hier und nicht im JavaScript,
    damit sie prüfbar bleiben.
    """

    def strahl(self, utxos, jahr=2026, frist=1):
        return auswerten_zum_jahresende(utxos, jahr, haltefrist_jahre=frist)["zeitstrahl"]

    def test_ohne_eingaenge_nichts_zu_zeichnen(self):
        strahl = self.strahl([])
        self.assertFalse(strahl["vorhanden"])
        self.assertEqual(strahl["events"], [])

    def test_erster_eingang_liegt_am_anfang(self):
        strahl = self.strahl([
            utxo(1000, "14.09.2024 09:00", marker="a1"),
            utxo(2000, "19.05.2026 16:00", marker="b2"),
        ])
        self.assertEqual(strahl["events"][0]["pos"], 0.0)

    def test_positionen_steigen_mit_der_zeit(self):
        strahl = self.strahl([
            utxo(1, "01.01.2024 12:00", marker="a1"),
            utxo(2, "01.01.2025 12:00", marker="b2"),
            utxo(3, "01.06.2026 12:00", marker="c3"),
        ])
        positionen = [e["pos"] for e in strahl["events"]]
        self.assertEqual(positionen, sorted(positionen))

    def test_positionen_bleiben_im_bereich(self):
        strahl = self.strahl([
            utxo(1, "01.01.2020 12:00", marker="a1"),
            utxo(2, "31.12.2026 12:00", marker="b2"),
        ])
        for eintrag in strahl["events"]:
            self.assertGreaterEqual(eintrag["pos"], 0.0)
            self.assertLessEqual(eintrag["pos"], 100.0)

    def test_einzelner_eingang_beginnt_die_achse(self):
        """
        Liegt der einzige Eingang nach der Fristgrenze, beginnt die Achse
        bei ihm — nicht bei einem leeren Bündelpunkt.
        """
        strahl = self.strahl([utxo(1000, "01.06.2026 12:00")])
        self.assertTrue(strahl["vorhanden"])
        self.assertEqual(strahl["events"][0]["pos"], 0.0)
        self.assertEqual(strahl["von"], "01.06.2026")
        self.assertEqual(strahl["bis"], "31.12.2026")

    def test_eingang_genau_am_stichtag_ergibt_trotzdem_eine_spanne(self):
        """
        Fällt der einzige Eingang exakt auf den Stichtag, sind Anfang und Ende
        gleich — ohne künstliche Spanne käme es zur Division durch null.
        Direkt geprüft, weil sich dieser Fall über auswerten_zum_jahresende() nicht auf die
        Sekunde genau herstellen lässt.
        """
        from core.tax import Eingang, zeitstrahl

        ende = stichtag(2026)
        eintrag = Eingang(
            txid="a" * 64, vout=0, address="bc1q", wallet="W",
            value_sats=1000, zeitpunkt=ende, frist_ende=None,
            erfuellt=True, haltedauer_tage=0,
        )
        strahl = zeitstrahl([eintrag], ende, 1)
        self.assertTrue(strahl["vorhanden"])
        self.assertGreater(strahl["events"][0]["pos"], 0.0)
        self.assertLess(strahl["events"][0]["pos"], 100.0)

    def test_fristgrenze_wird_berechnet(self):
        strahl = self.strahl([
            utxo(1, "01.01.2024 12:00", marker="a1"),
            utxo(2, "01.06.2026 12:00", marker="b2"),
        ])
        self.assertIsNotNone(strahl["frist_pos"])
        self.assertEqual(strahl["frist_datum"], "31.12.2025")

    def test_fristgrenze_trennt_erfuellt_von_offen(self):
        strahl = self.strahl([
            utxo(1, "01.01.2024 12:00", marker="a1"),
            utxo(2, "01.06.2026 12:00", marker="b2"),
        ])
        grenze = strahl["frist_pos"]
        for eintrag in strahl["events"]:
            if eintrag["erfuellt"]:
                self.assertLessEqual(eintrag["pos"], grenze)
            else:
                self.assertGreaterEqual(eintrag["pos"], grenze)

    def test_keine_grenze_ohne_haltefrist(self):
        strahl = self.strahl([utxo(1, "01.01.2024 12:00")], frist=0)
        self.assertIsNone(strahl["frist_pos"])

    def test_grenze_ausserhalb_wird_nicht_gezeichnet(self):
        """
        Liegen alle Eingänge nach der Fristgrenze, läge die Linie außerhalb
        der Achse. Eine Linie am Rand würde etwas Falsches suggerieren.
        """
        strahl = self.strahl([utxo(1, "01.06.2026 12:00")], frist=10)
        self.assertIsNone(strahl["frist_pos"])

    def test_groessenklassen_nach_anteil(self):
        strahl = self.strahl([
            utxo(90_000_000, "01.03.2026 12:00", marker="a1"),
            utxo(5_000_000, "01.06.2026 12:00", marker="b2"),
            utxo(1000, "01.09.2026 12:00", marker="c3"),
        ])
        klassen = {e["datum"]: e["groesse"] for e in strahl["events"]}
        self.assertEqual(klassen["01.03.2026"], "gross")
        self.assertEqual(klassen["01.06.2026"], "mittel")
        self.assertEqual(klassen["01.09.2026"], "klein")

    def test_y_folgt_den_sats(self):
        """Der größte UTXO sitzt oben, die übrigen anteilig darunter."""
        strahl = self.strahl([
            utxo(1000, "01.03.2026 12:00", marker="a1"),
            utxo(4000, "01.06.2026 12:00", marker="b2"),
            utxo(2000, "01.09.2026 12:00", marker="c3"),
        ])
        nach_sats = {e["value_sats"]: e["y"] for e in strahl["events"]}
        self.assertEqual(nach_sats[4000], 100.0)
        self.assertEqual(nach_sats[2000], 50.0)
        self.assertEqual(nach_sats[1000], 25.0)
        self.assertEqual(strahl["max_sats"], 4000)

    def test_aeltere_sats_summiert_die_vorherigen(self):
        strahl = self.strahl([
            utxo(1000, "01.03.2026 12:00", marker="a1"),
            utxo(2000, "01.06.2026 12:00", marker="b2"),
            utxo(4000, "01.09.2026 12:00", marker="c3"),
        ])
        self.assertEqual(
            [e["aeltere_sats"] for e in strahl["events"]],
            [0, 1000, 3000],
        )

    def test_jeder_eintrag_traegt_seine_angaben(self):
        strahl = self.strahl([utxo(84_000_000, "14.09.2024 09:00")])
        eintrag = strahl["events"][0]
        self.assertEqual(eintrag["datum"], "14.09.2024")
        self.assertEqual(eintrag["value_sats"], 84_000_000)
        self.assertIn("wallet", eintrag)
        self.assertIn("erfuellt", eintrag)
        self.assertIn("geprueft", eintrag)
        self.assertIn("neuvermoegen", eintrag)

    def test_beschriftungen_der_achse(self):
        strahl = self.strahl([
            utxo(1, "01.01.2024 12:00", marker="a1"),
            utxo(2, "01.06.2026 12:00", marker="b2"),
        ])
        self.assertEqual(len(strahl["ticks"]), 5)
        self.assertEqual(strahl["ticks"][0]["pos"], 0.0)
        self.assertEqual(strahl["ticks"][-1]["pos"], 100.0)

    def test_zeitraum_wird_benannt(self):
        strahl = self.strahl([utxo(1, "01.06.2026 09:00")])
        self.assertIn("2026", strahl["von"])
        self.assertIn("2026", strahl["bis"])

    def test_alter_utxo_quetscht_den_aktuellen_rand_nicht(self):
        """
        2020 und 2026 auf einer Achse: der alte Coin sitzt am Quartalsbeginn
        vor der Fristgrenze, die Achse beginnt dort — nicht 2020.
        """
        strahl = self.strahl([
            utxo(1000, "01.01.2020 12:00", marker="a1"),
            utxo(2000, "01.06.2026 12:00", marker="b2"),
        ])
        self.assertEqual(strahl["von"], "01.10.2025")
        alt, jung = strahl["events"]
        self.assertEqual(alt["gruppe"], "haltefrist")
        self.assertEqual(alt["gruppe_n"], 1)
        self.assertIsNone(jung["gruppe"])
        self.assertGreater(jung["pos"] - alt["pos"], 40)

    def test_stichtag_buendelt_altbestand_getrennt(self):
        from datetime import date

        ergebnis = auswerten_zum_jahresende(
            [
                utxo(1000, "01.01.2020 12:00", marker="a1"),
                utxo(2000, "01.06.2024 12:00", marker="b2"),
                utxo(3000, "01.06.2026 12:00", marker="c3"),
            ],
            2026, haltefrist_jahre=1, stichtag=date(2021, 2, 28),
        )
        strahl = ergebnis["zeitstrahl"]
        nach_datum = {e["datum"]: e for e in strahl["events"]}
        self.assertEqual(nach_datum["01.01.2020"]["gruppe"], "stichtag")
        self.assertEqual(nach_datum["01.06.2024"]["gruppe"], "haltefrist")
        self.assertIsNone(nach_datum["01.06.2026"]["gruppe"])
        self.assertEqual(nach_datum["01.01.2020"]["gruppe_n"], 1)
        self.assertEqual(nach_datum["01.06.2024"]["gruppe_n"], 1)
        self.assertEqual(
            nach_datum["01.01.2020"]["pos"],
            nach_datum["01.06.2024"]["pos"],
        )

    def test_quartalsbeginn_vor_nimmt_das_letzte_quartal_davor(self):
        from datetime import date
        from core.tax import quartalsbeginn_vor

        self.assertEqual(quartalsbeginn_vor(date(2025, 8, 19)), date(2025, 7, 1))
        self.assertEqual(quartalsbeginn_vor(date(2025, 7, 1)), date(2025, 4, 1))
        self.assertEqual(quartalsbeginn_vor(date(2026, 1, 1)), date(2025, 10, 1))

    def test_anzahl_stimmt_mit_der_tabelle_ueberein(self):
        """Jüngere UTXOs bleiben einzeln; ältere werden zu einem Punkt."""
        utxos = [
            utxo(1000, "01.03.2026 12:00", marker="a1"),
            utxo(2000, "01.06.2026 12:00", marker="b2"),
            utxo(3000, "01.09.2026 12:00", marker="c3"),
        ]
        ergebnis = auswerten_zum_jahresende(utxos, 2026)
        self.assertEqual(
            len(ergebnis["zeitstrahl"]["events"]),
            ergebnis["kennzahlen"]["gesamt_count"],
        )

    def test_aeltere_werden_zu_einem_punkt(self):
        strahl = self.strahl([
            utxo(1000, "01.01.2020 12:00", marker="a1"),
            utxo(2000, "04.07.2025 12:00", marker="b2"),
            utxo(3000, "01.06.2026 12:00", marker="c3"),
        ])
        buendel = [e for e in strahl["events"] if e["gruppe"] == "haltefrist"]
        self.assertEqual(len(buendel), 1)
        self.assertEqual(buendel[0]["gruppe_n"], 2)
        self.assertEqual(buendel[0]["value_sats"], 3000)
        self.assertEqual(len(strahl["events"]), 2)


class TestCsvExport(unittest.TestCase):

    def setUp(self):
        self.auswertung = auswerten_zum_jahresende([
            utxo(84_000_000, "14.09.2024 09:00", marker="a1"),
            utxo(124_500, "28.11.2026 04:00", marker="c3"),
        ], 2026)
        self.rohdaten = als_csv(self.auswertung)

    def test_beginnt_mit_bom(self):
        """Ohne BOM zeigt Excel unter Windows Umlaute als Buchstabensalat."""
        self.assertTrue(self.rohdaten.startswith(b"\xef\xbb\xbf"))

    def test_semikolon_als_trenner(self):
        """Excel im deutschen Gebietsschema erwartet Semikolon, nicht Komma."""
        text = self.rohdaten.decode("utf-8-sig")
        self.assertIn(";", text.splitlines()[0] + text.splitlines()[1])

    def test_zeilenumbrueche_windows_tauglich(self):
        self.assertIn(b"\r\n", self.rohdaten)

    def test_betraege_mit_dezimalkomma(self):
        text = self.rohdaten.decode("utf-8-sig")
        self.assertIn("0,84000000", text)

    def test_alle_eintraege_enthalten(self):
        text = self.rohdaten.decode("utf-8-sig")
        zeilen = list(csv.reader(io.StringIO(text), delimiter=";"))
        datenzeilen = [z for z in zeilen if z and z[0].count(".") == 2]
        self.assertEqual(len(datenzeilen), 2)

    def test_kopfangaben_dabei(self):
        text = self.rohdaten.decode("utf-8-sig")
        self.assertIn("Steuerjahr 2026", text)
        self.assertIn("Stichtag", text)
        self.assertIn("Erstellt am", text)

    def test_hinweis_keine_beratung_im_export(self):
        text = self.rohdaten.decode("utf-8-sig")
        self.assertIn("keine Steuerberatung", text)
        self.assertIn("Börsenhistorien", text)
        self.assertIn("Kaufbelege", text)

    def test_summenzeilen(self):
        text = self.rohdaten.decode("utf-8-sig")
        self.assertIn("Summe", text)
        self.assertIn("davon Frist erfüllt", text)
        self.assertIn("davon Frist offen", text)

    def test_umlaute_lesbar(self):
        text = self.rohdaten.decode("utf-8-sig")
        self.assertIn("erfüllt", text)


class TestBericht(unittest.TestCase):

    def setUp(self):
        self.auswertung = auswerten_zum_jahresende(
            [utxo(84_000_000, "14.09.2024 09:00")], 2026
        )
        self.html = als_bericht(self.auswertung).decode("utf-8")

    def test_eigenstaendige_datei(self):
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        self.assertIn('<meta charset="utf-8">', self.html)

    def test_keine_externen_ressourcen(self):
        """Der Bericht muss offline und weitergegeben funktionieren."""
        for muster in ("http://", "https://", "<script"):
            self.assertNotIn(muster, self.html.lower())

    def test_kennzahlen_und_hinweise(self):
        self.assertIn("Steuerjahr 2026", self.html)
        self.assertIn("0,84000000", self.html)
        self.assertIn("keine Steuerberatung", self.html)
        self.assertIn("Börsenhistorien", self.html)
        self.assertIn(tax.HINWEIS_ONCHAIN, self.html)

    def test_html_wird_maskiert(self):
        boese = auswerten_zum_jahresende(
            [utxo(1000, "01.01.2024 12:00", adresse="<script>alert(1)</script>")],
            2026,
        )
        html = als_bericht(boese).decode("utf-8")
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)


class TestStandardwerte(unittest.TestCase):

    def test_stichtag_am_stichtag_zaehlt_noch_als_altbestand(self):
        from datetime import date
        ergebnis = auswerten_zum_jahresende(
            [utxo(100_000, "28.02.2021 23:00")], 2026,
            haltefrist_jahre=1, stichtag=date(2021, 2, 28),
        )
        self.assertFalse(ergebnis["eintraege"][0]["neuvermoegen"])
        self.assertTrue(ergebnis["eintraege"][0]["erfuellt"])

    def test_haltefrist_default_ist_ein_jahr(self):
        self.assertEqual(STANDARD_HALTEFRIST_JAHRE, 1)
        ergebnis = auswerten_zum_jahresende([utxo(1000, "01.01.2020 12:00")], 2026)
        self.assertEqual(ergebnis["haltefrist_jahre"], 1)


class TestSteuerEinstellungen(unittest.TestCase):

    def test_fehlender_schluessel_laesst_stichtag_leer(self):
        from core.tax import lese_steuer_einstellungen
        werte = lese_steuer_einstellungen({})
        self.assertEqual(werte["stichtag"], "")
        self.assertEqual(werte["haltefrist_jahre"], 1)

    def test_leerer_stichtag_schaltet_die_regel_aus(self):
        from core.tax import lese_steuer_einstellungen
        werte = lese_steuer_einstellungen({"STEUER_STICHTAG": ""})
        self.assertEqual(werte["stichtag"], "")
        self.assertEqual(werte["stichtag_iso"], "")

    def test_haltefrist_mehrjaehrig(self):
        from core.tax import lese_steuer_einstellungen
        werte = lese_steuer_einstellungen({"STEUER_HALTEFRIST_JAHRE": "7"})
        self.assertEqual(werte["haltefrist_jahre"], 7)
        self.assertIn(7, werte["haltefrist_jahre_auswahl"])

    def test_anschaffung_default_juengste(self):
        from core.tax import lese_steuer_einstellungen, STANDARD_ANSCHAFFUNG
        werte = lese_steuer_einstellungen({})
        self.assertEqual(werte["anschaffung"], STANDARD_ANSCHAFFUNG)
        self.assertEqual(werte["anschaffung"], "juengste")

    def test_anschaffung_aelteste(self):
        from core.tax import lese_steuer_einstellungen
        werte = lese_steuer_einstellungen({"STEUER_ANSCHAFFUNG": "aelteste"})
        self.assertEqual(werte["anschaffung"], "aelteste")


class TestKanonischerHinweis(unittest.TestCase):
    """Derselbe Absatz in Konstante, Export, Oberfläche und Doku."""

    def test_beratungshinweis_enthaelt_den_absatz(self):
        self.assertIn(tax.HINWEIS_ONCHAIN, tax.HINWEIS_KEINE_BERATUNG)
        self.assertTrue(tax.HINWEIS_KEINE_BERATUNG.startswith(
            "Diese Aufstellung ist keine Steuerberatung."
        ))

    def test_merker_liest_die_env(self):
        self.assertFalse(tax.hinweis_onchain_bestaetigt({}))
        self.assertFalse(tax.hinweis_onchain_bestaetigt(
            {tax.ENV_HINWEIS_ONCHAIN_BESTAETIGT: "0"}
        ))
        self.assertTrue(tax.hinweis_onchain_bestaetigt(
            {tax.ENV_HINWEIS_ONCHAIN_BESTAETIGT: "1"}
        ))

    def test_wortlaut_steht_in_doku_und_ui(self):
        wurzel = Path(__file__).resolve().parent.parent
        for rel in (
            "README.md",
            "doc/handbuch.html",
            "web/index.html",
            "specter_plugin/README.md",
        ):
            text = (wurzel / rel).read_text(encoding="utf-8")
            self.assertIn(tax.HINWEIS_ONCHAIN, text, rel)


if __name__ == "__main__":
    unittest.main()
