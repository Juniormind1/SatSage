"""Speicher Fassung 2: Re-Import, Konflikt, Migration v1, kein Dateiname."""
from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from core.boerse.kraken import parse_ledgers
from core.boerse.modell import Art, Buchung, ParseErgebnis, Quarantaene
from core.boerse.speicher import (
    DATEI_QUELLEN,
    FASSUNG,
    datei_schon_importiert,
    importiere_ergebnis,
    ist_v2,
    kurzinfo,
    lies_buchungen,
    lies_labels,
    lies_quellen,
    lies_quarantaene,
    loesche_v2,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "boerse"


def _buchung(**kw) -> Buchung:
    werte = dict(
        konto="kraken",
        ref="LSYN01-00000-000099",
        gruppe=None,
        zeit_ts=1_700_000_000,
        zeit_zone_belegt=True,
        art=Art.KAUF,
        sats=100_000,
        gebuehr_sats=0,
        fiat=Decimal("-50"),
        fiat_gebuehr=Decimal("1"),
        waehrung="EUR",
        kurs=Decimal("50000"),
        txid=None,
        adresse=None,
        lightning=False,
        roh_typ="trade",
        roh_subtyp=None,
        datei="abc",
        zeile=2,
    )
    werte.update(kw)
    return Buchung(**werte)


def _ergebnis(*buchungen: Buchung, datei="abc", quarantaene=()) -> ParseErgebnis:
    return ParseErgebnis(
        buchungen=tuple(buchungen),
        quarantaene=tuple(quarantaene),
        variante="ledgers",
        datei_hash=datei,
    )


class SpeicherTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_import_und_reimport_idempotent(self):
        text = (FIXTURES / "ledgers_grund.csv").read_text(encoding="utf-8")
        geparst = parse_ledgers(text)
        erst = importiere_ergebnis(geparst, name="Kraken", slug="kraken", cache_dir=self.dir)
        self.assertFalse(erst["schon_importiert"])
        self.assertGreater(erst["neu"], 0)
        self.assertEqual(erst["doppelt"], 0)
        self.assertEqual(erst["konflikte"], 0)
        self.assertTrue(ist_v2("kraken", self.dir))

        nochmal = importiere_ergebnis(geparst, name="Kraken", slug="kraken", cache_dir=self.dir)
        self.assertTrue(nochmal["schon_importiert"])
        self.assertEqual(nochmal["neu"], 0)
        self.assertEqual(nochmal["buchungen"], erst["buchungen"])
        self.assertEqual(len(lies_buchungen("kraken", self.dir)), erst["buchungen"])

    def test_gleicher_schluessel_gleicher_inhalt_ohne_dateihash(self):
        # Gleicher Inhalt, anderer Datei-Hash: idempotent, nicht schon_importiert.
        a = importiere_ergebnis(
            _ergebnis(_buchung(datei="eins"), datei="eins"),
            name="Kraken", slug="kraken", cache_dir=self.dir,
        )
        b = importiere_ergebnis(
            _ergebnis(_buchung(datei="zwei", zeile=9), datei="zwei"),
            name="Kraken", slug="kraken", cache_dir=self.dir,
        )
        self.assertFalse(b["schon_importiert"])
        self.assertEqual(b["neu"], 0)
        self.assertEqual(b["doppelt"], 1)
        self.assertEqual(b["buchungen"], a["buchungen"])

    def test_konflikt_wird_nicht_ueberschrieben(self):
        importiere_ergebnis(
            _ergebnis(_buchung(sats=100_000), datei="eins"),
            name="Kraken", slug="kraken", cache_dir=self.dir,
        )
        bericht = importiere_ergebnis(
            _ergebnis(_buchung(sats=200_000, datei="zwei"), datei="zwei"),
            name="Kraken", slug="kraken", cache_dir=self.dir,
        )
        self.assertEqual(bericht["konflikte"], 1)
        self.assertEqual(bericht["neu"], 0)
        gespeichert = lies_buchungen("kraken", self.dir)
        self.assertEqual(len(gespeichert), 1)
        self.assertEqual(gespeichert[0].sats, 100_000)
        konflikte = [q for q in lies_quarantaene("kraken", self.dir) if q["grund"] == "Konflikt gleicher Schlüssel"]
        self.assertEqual(len(konflikte), 1)
        self.assertEqual(konflikte[0]["bestand"]["sats"], 100_000)
        self.assertEqual(konflikte[0]["neu"]["sats"], 200_000)

    def test_quellen_enthaelt_keinen_dateinamen(self):
        text = (FIXTURES / "ledgers_grund.csv").read_text(encoding="utf-8")
        geparst = parse_ledgers(text)
        importiere_ergebnis(geparst, name="Kraken", slug="kraken", cache_dir=self.dir)
        roh = (self.dir / "kraken" / DATEI_QUELLEN).read_text(encoding="utf-8")
        self.assertNotIn("ledgers_grund.csv", roh)
        self.assertNotIn("filename", roh)
        self.assertNotIn("dateiname", roh)
        quellen = lies_quellen("kraken", self.dir)
        self.assertEqual(quellen["fassung"], FASSUNG)
        self.assertTrue(quellen["quellen"][0]["datei"])
        self.assertNotIn("filename", quellen["quellen"][0])

    def test_labels_aus_auszahlung(self):
        from tests.fixtures import BIP84_RECEIVE_0, txid
        kette = txid("c1")
        importiere_ergebnis(
            _ergebnis(_buchung(
                art=Art.BTC_AUSGANG, sats=-50_000, ref="STSYN-0004",
                txid=kette, adresse=BIP84_RECEIVE_0, konto="strike",
            ), datei="s1"),
            name="Strike", slug="strike", cache_dir=self.dir,
        )
        labels = lies_labels("strike", self.dir)
        self.assertIn(BIP84_RECEIVE_0, labels["addresses"])
        self.assertIn(kette, labels["txids"])
        self.assertEqual(labels["txids"][kette]["quelle"], "v2")

    def test_ersetzen_setzt_buchungen_zurueck(self):
        importiere_ergebnis(
            _ergebnis(_buchung(ref="A"), _buchung(ref="B", sats=1), datei="eins"),
            name="Kraken", slug="kraken", cache_dir=self.dir,
        )
        bericht = importiere_ergebnis(
            _ergebnis(_buchung(ref="C", sats=3), datei="zwei"),
            name="Kraken", slug="kraken", cache_dir=self.dir, ersetzen=True,
        )
        self.assertEqual(bericht["buchungen"], 1)
        self.assertEqual(lies_buchungen("kraken", self.dir)[0].ref, "C")

    def test_loesche_v2(self):
        importiere_ergebnis(_ergebnis(_buchung(), datei="x"), name="K", slug="kraken", cache_dir=self.dir)
        self.assertTrue(loesche_v2("kraken", self.dir))
        self.assertFalse(ist_v2("kraken", self.dir))
        self.assertFalse(loesche_v2("kraken", self.dir))

    def test_kurzinfo(self):
        importiere_ergebnis(_ergebnis(_buchung(), datei="x"), name="Kraken", slug="kraken", cache_dir=self.dir)
        info = kurzinfo("kraken", self.dir)
        self.assertEqual(info["name"], "Kraken")
        self.assertEqual(info["fassung"], 2)
        self.assertEqual(info["buchungen"], 1)


class MigrationV1Test(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_v1_bleibt_lesbar_nach_v2_import(self):
        from core import exchange_reports as boerse
        from tests.fixtures import BIP84_RECEIVE_0, txid
        v1 = boerse.importiere_csv(
            f"address,txid,type,asset\n{BIP84_RECEIVE_0},{txid('c1')},withdrawal,BTC\n",
            name="Kraken",
            filename="soll-nicht-nach-v2.json",
            cache_dir=self.dir,
        )
        self.assertEqual(v1["addresses"], 1)
        self.assertTrue((self.dir / "kraken.json").is_file())

        text = (FIXTURES / "ledgers_grund.csv").read_text(encoding="utf-8")
        # Über die Fassade: erkanntes Format schreibt v2, v1-Datei bleibt.
        bericht = boerse.importiere_csv(text, name="Kraken", filename="geheim.csv", cache_dir=self.dir)
        self.assertEqual(bericht.get("fassung"), FASSUNG)
        self.assertTrue((self.dir / "kraken.json").is_file())
        self.assertTrue(ist_v2("kraken", self.dir))
        quellen = (self.dir / "kraken" / DATEI_QUELLEN).read_text(encoding="utf-8")
        self.assertNotIn("geheim.csv", quellen)
        self.assertNotIn("soll-nicht-nach-v2.json", quellen)

        stand = boerse.status(self.dir)
        ein = next(e for e in stand["exchanges"] if e["slug"] == "kraken")
        self.assertTrue(ein.get("v1_vorhanden"))
        self.assertEqual(ein.get("fassung"), 2)

        # Labels aus v1 und v2 stehen beide zur Verfügung.
        treffer = boerse.beschrifte(adresse=BIP84_RECEIVE_0, cache_dir=self.dir)
        self.assertIsNotNone(treffer)



class VorschauTest(unittest.TestCase):
    def test_kraken_zaehlt_arten(self):
        from core import exchange_reports as boerse
        text = (FIXTURES / "ledgers_grund.csv").read_text(encoding="utf-8")
        vor = boerse.vorschau(text)
        self.assertTrue(vor["erkannt"])
        self.assertEqual(vor["boerse"], "kraken")
        self.assertGreater(vor["buchungen"], 0)
        self.assertIn("kauf", vor["nach_art"])
        self.assertEqual(vor["saldo_luecken"], [])
        self.assertFalse(vor["schon_importiert"])

    def test_unbekannt_mit_v1_treffern(self):
        from core import exchange_reports as boerse
        from tests.fixtures import BIP84_RECEIVE_0, txid
        vor = boerse.vorschau(
            f"address,txid,type,asset\n{BIP84_RECEIVE_0},{txid('c1')},withdrawal,BTC\n"
        )
        self.assertFalse(vor["erkannt"])
        self.assertTrue(vor.get("v1"))
        self.assertEqual(vor["addresses"], 1)


if __name__ == "__main__":
    unittest.main()


class ApiVorschauTest(unittest.TestCase):
    def test_api_vorschau_und_import(self):
        from types import SimpleNamespace
        from httpserver.api.labels_sanctions_exchange import (
            api_exchange_reports_import,
            api_exchange_reports_vorschau,
            api_exchange_reports,
        )
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        state = SimpleNamespace(exchange_reports_dir=Path(self._tmp.name))
        text = (FIXTURES / "ledgers_grund.csv").read_text(encoding="utf-8")
        vor = api_exchange_reports_vorschau(state, {"csv": text})
        self.assertTrue(vor["erkannt"])
        self.assertEqual(vor["boerse"], "kraken")
        self.assertEqual(api_exchange_reports(state, {}), {"exchanges": [], "count": 0, "addresses": 0, "txids": 0})
        importiert = api_exchange_reports_import(state, {"name": "Kraken", "csv": text})
        self.assertEqual(importiert["fassung"], 2)
        self.assertGreater(importiert["neu"], 0)
        stand = api_exchange_reports(state, {})
        self.assertEqual(stand["count"], 1)
        self.assertEqual(stand["exchanges"][0]["fassung"], 2)
        # Re-Import derselben Datei.
        nochmal = api_exchange_reports_import(state, {"name": "Kraken", "csv": text})
        self.assertTrue(nochmal["schon_importiert"])
