"""
Abgleich gegen Sanktions- und Blacklists.

Der heikelste Punkt ist nicht das Finden, sondern die Unterscheidung zwischen
„nichts gefunden" und „nicht nachgesehen". Beides darf in der Anzeige nie
gleich aussehen — sonst liest jemand aus einem fehlenden Cache eine
Unbedenklichkeit heraus.
"""
import json
import tempfile
import unittest
from pathlib import Path

from core.sanctions import (
    lade_adressen,
    markiere_utxos,
    pruefe_adressen,
    status,
    treffer_details,
)
from tests.fixtures import BIP84_CHANGE_0, BIP84_RECEIVE_0, EXTERN_A, txid

GELISTET = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"


def utxo_eintrag(sats, adresse, marker="a1", vout=0):
    return {
        "txid": txid(marker), "vout": vout, "address": adresse,
        "value_sats": sats, "key": f"{txid(marker)}:{vout}",
    }


class SanktionsBasis(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def schreibe_listen(self, adressen, *, index=None, meta=None):
        (self.dir / "sanctioned_addresses_XBT.json").write_text(
            json.dumps(adressen), encoding="utf-8"
        )
        (self.dir / "sanctioned_addresses_XBT.meta.json").write_text(
            json.dumps(meta or {"updated_at": "2026-07-01",
                                "sources": {"OFAC SDN": 2, "Badd-Boyz": 1}}),
            encoding="utf-8",
        )
        if index is not None:
            (self.dir / "sanctioned_address_index.json").write_text(
                json.dumps(index), encoding="utf-8"
            )


class TestOhneListen(SanktionsBasis):
    """Der gefährliche Zustand: nichts im Cache."""

    def test_status_meldet_fehlende_listen(self):
        zustand = status(self.dir)
        self.assertFalse(zustand.vorhanden)
        self.assertEqual(zustand.adressen, 0)

    def test_pruefung_meldet_nicht_geprueft(self):
        befund = pruefe_adressen([BIP84_RECEIVE_0], cache_dir=self.dir)
        self.assertFalse(befund["geprueft"])
        self.assertEqual(befund["treffer"], [])

    def test_grund_wird_genannt(self):
        befund = pruefe_adressen([BIP84_RECEIVE_0], cache_dir=self.dir)
        self.assertIn("Keine Listen", befund["grund"])

    def test_nicht_geprueft_ist_nicht_dasselbe_wie_sauber(self):
        """
        Der Unterschied, auf den es ankommt: Ohne Listen darf das Ergebnis
        nicht wie ein bestandener Abgleich aussehen.
        """
        ohne = pruefe_adressen([BIP84_RECEIVE_0], cache_dir=self.dir)
        self.schreibe_listen([GELISTET])
        mit = pruefe_adressen([BIP84_RECEIVE_0], cache_dir=self.dir)

        self.assertEqual(ohne["treffer"], mit["treffer"])
        self.assertNotEqual(ohne["geprueft"], mit["geprueft"])

    def test_utxos_werden_nicht_markiert(self):
        eintraege = [utxo_eintrag(1000, GELISTET)]
        markiere_utxos(eintraege, cache_dir=self.dir)
        self.assertFalse(eintraege[0]["flagged"])


class TestMitListen(SanktionsBasis):

    def setUp(self):
        super().setUp()
        self.schreibe_listen(
            [GELISTET, EXTERN_A],
            index={GELISTET: {
                "person": "Beispiel Person",
                "reason": "Testeintrag",
                "sources": ["OFAC SDN"],
                "listed": "2024-01-15",
            }},
        )

    def test_status_meldet_bestand(self):
        zustand = status(self.dir)
        self.assertTrue(zustand.vorhanden)
        self.assertEqual(zustand.adressen, 2)
        self.assertEqual(zustand.stand, "2026-07-01")

    def test_quellen_werden_aufgeschluesselt(self):
        namen = [q["name"] for q in status(self.dir).quellen]
        self.assertIn("OFAC SDN", namen)
        self.assertIn("Badd-Boyz", namen)

    def test_bestandskarte_erklaert_die_zahlen_statt_der_pruefung(self):
        """
        Die Karte zeigt den Listen-*Bestand* — dort wird nichts geprüft und es
        gibt keinen Treffer. Text über Treffer und rechtliche Feststellung
        gehört ans Prüfergebnis, nicht hierher. Erklärt werden muss stattdessen,
        warum die Summe der Quellen über der Gesamtzahl liegen kann.
        """
        self.schreibe_listen(
            [GELISTET, EXTERN_A],
            meta={
                "fetched_at": "2026-07-22T05:25:39+00:00",
                "sources": [
                    {"name": "OFAC SDN XML", "address_count": 2},
                    {"name": "ransomwhe.re", "address_count": 1},
                ],
            },
        )
        hinweise = " ".join(status(self.dir).as_dict()["hinweise"])
        self.assertNotIn("Treffer", hinweise)
        self.assertNotIn("rechtliche Feststellung", hinweise)
        self.assertIn("mehreren Listen", hinweise)

    def test_ohne_mehrfachlistung_kein_ueberhang_hinweis(self):
        """Deckt sich die Summe mit der Gesamtzahl, gibt es nichts zu erklären."""
        self.schreibe_listen(
            [GELISTET, EXTERN_A],
            meta={
                "fetched_at": "2026-07-22T05:25:39+00:00",
                "sources": [{"name": "OFAC SDN XML", "address_count": 2}],
            },
        )
        hinweise = " ".join(status(self.dir).as_dict()["hinweise"])
        self.assertNotIn("mehreren Listen", hinweise)

    def test_echtes_metaformat_liefert_zahlen(self):
        """
        So schreibt sanctioned.update_sanctioned_lists die Metadaten wirklich:
        eine Liste von Quellen, die Anzahl unter ``address_count``. Wurde nur
        nach ``count``/``addresses`` gesucht, stand in der Oberfläche neben
        jeder Quelle eine 0, obwohl die Listen geladen waren.
        """
        self.schreibe_listen(
            [GELISTET, EXTERN_A],
            meta={
                "fetched_at": "2026-07-22T05:25:39+00:00",
                "count": 11868,
                "sources": [
                    {"id": "ofac_0xb10c", "name": "OFAC SDN (0xB10C)",
                     "category": "sanction", "address_count": 521},
                    {"id": "opensanctions_ransomwhere",
                     "name": "ransomwhe.re (OpenSanctions)",
                     "category": "ransomware", "address_count": 11186},
                ],
            },
        )
        quellen = {q["name"]: q["adressen"] for q in status(self.dir).quellen}
        self.assertEqual(quellen["OFAC SDN (0xB10C)"], 521)
        self.assertEqual(quellen["ransomwhe.re (OpenSanctions)"], 11186)

    def test_treffer_wird_gefunden(self):
        befund = pruefe_adressen([BIP84_RECEIVE_0, GELISTET], cache_dir=self.dir)
        self.assertTrue(befund["geprueft"])
        self.assertEqual(len(befund["treffer"]), 1)
        self.assertEqual(befund["treffer"][0]["address"], GELISTET)

    def test_treffer_traegt_die_begruendung(self):
        befund = pruefe_adressen([GELISTET], cache_dir=self.dir)
        treffer = befund["treffer"][0]
        self.assertEqual(treffer["person"], "Beispiel Person")
        self.assertEqual(treffer["grund"], "Testeintrag")
        self.assertEqual(treffer["gelistet_am"], "2024-01-15")

    def test_saubere_adressen_ergeben_keinen_treffer(self):
        befund = pruefe_adressen(
            [BIP84_RECEIVE_0, BIP84_CHANGE_0], cache_dir=self.dir
        )
        self.assertTrue(befund["geprueft"])
        self.assertEqual(befund["treffer"], [])
        self.assertEqual(befund["geprueft_count"], 2)

    def test_doppelte_adressen_zaehlen_einmal(self):
        befund = pruefe_adressen(
            [BIP84_RECEIVE_0, BIP84_RECEIVE_0], cache_dir=self.dir
        )
        self.assertEqual(befund["geprueft_count"], 1)

    def test_details_zu_unbekannter_adresse(self):
        self.assertEqual(treffer_details(BIP84_RECEIVE_0, self.dir)["person"], "")

    def test_adressmenge_wird_geladen(self):
        self.assertIn(GELISTET, lade_adressen(self.dir))


class TestUtxoMarkierung(SanktionsBasis):

    def setUp(self):
        super().setUp()
        self.schreibe_listen([GELISTET])

    def test_markiert_nur_die_treffer(self):
        eintraege = [
            utxo_eintrag(84_000_000, BIP84_RECEIVE_0, "a1"),
            utxo_eintrag(1000, GELISTET, "b2"),
        ]
        markiere_utxos(eintraege, cache_dir=self.dir)
        self.assertFalse(eintraege[0]["flagged"])
        self.assertTrue(eintraege[1]["flagged"])

    def test_befund_nennt_anzahl_und_betrag(self):
        eintraege = [
            utxo_eintrag(84_000_000, BIP84_RECEIVE_0, "a1"),
            utxo_eintrag(1000, GELISTET, "b2"),
            utxo_eintrag(2000, GELISTET, "c3"),
        ]
        befund = markiere_utxos(eintraege, cache_dir=self.dir)
        self.assertEqual(befund["flagged_count"], 2)
        self.assertEqual(befund["flagged_sats"], 3000)

    def test_ohne_treffer_bleiben_die_zahlen_bei_null(self):
        eintraege = [utxo_eintrag(1000, BIP84_RECEIVE_0)]
        befund = markiere_utxos(eintraege, cache_dir=self.dir)
        self.assertEqual(befund["flagged_count"], 0)
        self.assertEqual(befund["flagged_sats"], 0)
        self.assertTrue(befund["geprueft"])

    def test_leere_liste(self):
        befund = markiere_utxos([], cache_dir=self.dir)
        self.assertEqual(befund["flagged_count"], 0)


class TestHinweise(SanktionsBasis):

    def test_status_traegt_die_vorbehalte_der_bestandskarte(self):
        """
        Die Karte zeigt den Bestand, nicht ein Prüfergebnis. Ihre Vorbehalte
        müssen sich deshalb auf die Listen selbst beziehen — dass sie Fehler
        enthalten und veralten. Die Sätze über Treffer und Herkunftsanalyse
        stehen am Prüfergebnis, wo tatsächlich etwas geprüft wurde.
        """
        self.schreibe_listen([GELISTET])
        hinweise = " ".join(status(self.dir).as_dict()["hinweise"])
        self.assertIn("veralten", hinweise)
        self.assertNotIn("Herkunftsanalyse", hinweise)
        self.assertNotIn("keine rechtliche Feststellung", hinweise)

    def test_kaputte_dateien_fuehren_nicht_zum_absturz(self):
        (self.dir / "sanctioned_addresses_XBT.json").write_text(
            "{kaputt", encoding="utf-8"
        )
        zustand = status(self.dir)
        self.assertFalse(zustand.vorhanden)


if __name__ == "__main__":
    unittest.main()
