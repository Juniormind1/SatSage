"""
Steuerjahr mit vollständigem Verlauf.

Ohne Verlauf kennt die Auswertung nur unverbrauchte UTXOs — für zurückliegende
Jahre ist sie damit eine Bestandsaufnahme von heute. Was 2023 empfangen und
2024 ausgegeben wurde, taucht nirgends auf, obwohl gerade die *Veräußerung*
der steuerlich maßgebliche Vorgang ist.

Liegen Verlaufsdaten vor (``spent``/``spent_time_ts``), unterscheidet die
Auswertung deshalb zwei Dinge: was am Stichtag noch im Bestand war, und was im
Jahr abgegangen ist.
"""
import unittest
from datetime import datetime

from core import tax

STICHTAG_2024 = datetime(2024, 12, 31, 23, 59, 59)


def eingang(marker: str, empfangen: str, *, sats: int = 100_000,
            ausgegeben: str | None = None) -> dict:
    """Ein Verlaufs-Eintrag; Daten als 'TT.MM.JJJJ'."""
    def stempel(text: str) -> int:
        return int(datetime.strptime(text, "%d.%m.%Y").timestamp())

    eintrag = {
        "txid": marker * 32,
        "vout": 0,
        "address": "bc1qtest",
        "value": sats,
        "status": {"confirmed": True, "block_time": stempel(empfangen)},
        "spent": ausgegeben is not None,
        "spent_txid": (marker * 31 + "f") if ausgegeben else None,
    }
    if ausgegeben:
        eintrag["spent_time_ts"] = stempel(ausgegeben)
    return eintrag


class TestOhneVerlaufUnveraendert(unittest.TestCase):
    """
    Einträge ohne Verlaufsfelder verhalten sich wie bisher — sonst würde eine
    bestehende Auswertung stillschweigend andere Zahlen liefern.
    """

    def test_bestand_wie_gehabt(self):
        utxo = {
            "txid": "a" * 64, "vout": 0, "address": "bc1q", "value": 50_000,
            "status": {"confirmed": True,
                       "block_time": int(datetime(2022, 5, 1).timestamp())},
        }
        auswertung = tax.auswerten([utxo], 2024, jetzt=STICHTAG_2024)
        self.assertEqual(auswertung["kennzahlen"]["gesamt_count"], 1)
        self.assertEqual(auswertung["kennzahlen"]["abgang_count"], 0)


class TestAbgaenge(unittest.TestCase):

    def test_vor_dem_stichtag_ausgegeben_zaehlt_nicht_zum_bestand(self):
        """
        Was im Mai verkauft wurde, lag am 31.12. nicht mehr im Wallet. Es
        weiterhin als Bestand zu führen wäre schlicht falsch.
        """
        auswertung = tax.auswerten(
            [eingang("a", "01.03.2022", ausgegeben="15.05.2024")],
            2024, jetzt=STICHTAG_2024,
        )
        self.assertEqual(auswertung["kennzahlen"]["gesamt_count"], 0)
        self.assertEqual(auswertung["kennzahlen"]["abgang_count"], 1)

    def test_abgang_wird_als_veraeusserung_ausgewiesen(self):
        auswertung = tax.auswerten(
            [eingang("a", "01.03.2022", sats=250_000, ausgegeben="15.05.2024")],
            2024, jetzt=STICHTAG_2024,
        )
        abgaenge = auswertung["abgaenge"]
        self.assertEqual(len(abgaenge), 1)
        self.assertEqual(abgaenge[0]["value_sats"], 250_000)
        self.assertEqual(abgaenge[0]["abgang_datum"], "15.05.2024")

    def test_haltefrist_bei_veraeusserung_erfuellt(self):
        """Über ein Jahr gehalten: nach § 23 EStG steuerfrei."""
        auswertung = tax.auswerten(
            [eingang("a", "01.03.2022", ausgegeben="15.05.2024")],
            2024, jetzt=STICHTAG_2024,
        )
        self.assertTrue(auswertung["abgaenge"][0]["frist_erfuellt"])

    def test_haltefrist_bei_veraeusserung_nicht_erfuellt(self):
        """Keine drei Monate gehalten — der Fall, auf den es ankommt."""
        auswertung = tax.auswerten(
            [eingang("a", "01.03.2024", ausgegeben="15.05.2024")],
            2024, jetzt=STICHTAG_2024,
        )
        abgang = auswertung["abgaenge"][0]
        self.assertFalse(abgang["frist_erfuellt"])
        self.assertEqual(abgang["haltedauer_tage"], 75)

    def test_abgang_in_anderem_jahr_taucht_nicht_auf(self):
        """Ein Verkauf von 2023 gehört nicht in die Aufstellung für 2024."""
        auswertung = tax.auswerten(
            [eingang("a", "01.03.2021", ausgegeben="10.06.2023")],
            2024, jetzt=STICHTAG_2024,
        )
        self.assertEqual(auswertung["abgaenge"], [])
        self.assertEqual(auswertung["kennzahlen"]["gesamt_count"], 0)

    def test_nach_dem_stichtag_ausgegeben_zaehlt_zum_bestand(self):
        """Am 31.12.2024 lag es noch da — der Verkauf kam erst 2025."""
        auswertung = tax.auswerten(
            [eingang("a", "01.03.2022", ausgegeben="20.02.2025")],
            2024, jetzt=STICHTAG_2024,
        )
        self.assertEqual(auswertung["kennzahlen"]["gesamt_count"], 1)
        self.assertEqual(auswertung["abgaenge"], [])

    def test_bestand_und_abgang_nebeneinander(self):
        auswertung = tax.auswerten(
            [
                eingang("a", "01.03.2022", sats=100_000),
                eingang("b", "01.04.2022", sats=200_000, ausgegeben="15.05.2024"),
            ],
            2024, jetzt=STICHTAG_2024,
        )
        self.assertEqual(auswertung["kennzahlen"]["gesamt_count"], 1)
        self.assertEqual(auswertung["kennzahlen"]["gesamt_sats"], 100_000)
        self.assertEqual(auswertung["kennzahlen"]["abgang_count"], 1)
        self.assertEqual(auswertung["kennzahlen"]["abgang_sats"], 200_000)


class TestHinweise(unittest.TestCase):

    def test_ohne_verlauf_steht_der_vorbehalt_da(self):
        utxo = {
            "txid": "a" * 64, "vout": 0, "address": "bc1q", "value": 50_000,
            "status": {"confirmed": True,
                       "block_time": int(datetime(2022, 5, 1).timestamp())},
        }
        hinweise = " ".join(tax.auswerten([utxo], 2024, jetzt=STICHTAG_2024)["hinweise"])
        self.assertIn("unverbrauchte", hinweise)

    def test_mit_verlauf_faellt_der_vorbehalt_weg(self):
        """
        Der Satz „nur unverbrauchte UTXOs" wäre dann unwahr — und ein falscher
        Vorbehalt ist schlimmer als keiner: Er lässt vollständige Zahlen
        unvollständig aussehen.
        """
        auswertung = tax.auswerten(
            [eingang("a", "01.03.2022", ausgegeben="15.05.2024")],
            2024, jetzt=STICHTAG_2024,
        )
        hinweise = " ".join(auswertung["hinweise"])
        self.assertNotIn("Erfasst sind ausschließlich", hinweise)
        self.assertIn("Verlauf", hinweise)



class TestExporte(unittest.TestCase):
    """
    Die Datei ist das Ergebnis — sie geht zum Steuerberater. Was nur auf dem
    Bildschirm steht, hilft dort niemandem.
    """

    def auswertung(self):
        return tax.auswerten(
            [
                eingang("a", "01.03.2022", sats=100_000),
                eingang("b", "01.04.2023", sats=250_000, ausgegeben="15.05.2024"),
                eingang("c", "01.03.2024", sats=70_000, ausgegeben="20.06.2024"),
            ],
            2024, jetzt=STICHTAG_2024,
        )

    def test_csv_enthaelt_die_veraeusserungen(self):
        text = tax.als_csv(self.auswertung()).decode("utf-8")
        self.assertIn("Veräußerungen im Steuerjahr 2024", text)
        self.assertIn("15.05.2024", text)
        self.assertIn("20.06.2024", text)

    def test_csv_nennt_die_fristerfuellung(self):
        text = tax.als_csv(self.auswertung()).decode("utf-8")
        self.assertIn("Summe Veräußerungen", text)
        self.assertIn("davon innerhalb der Haltefrist", text)

    def test_csv_ohne_verlauf_bleibt_unveraendert(self):
        """Ohne Abgänge darf kein leerer Block erscheinen."""
        ohne = tax.auswerten(
            [{"txid": "a" * 64, "vout": 0, "address": "bc1q", "value": 5000,
              "status": {"confirmed": True,
                         "block_time": int(datetime(2022, 5, 1).timestamp())}}],
            2024, jetzt=STICHTAG_2024,
        )
        self.assertNotIn("Veräußerungen", tax.als_csv(ohne).decode("utf-8"))

    def test_bericht_enthaelt_die_veraeusserungen(self):
        html = tax.als_bericht(self.auswertung()).decode("utf-8")
        self.assertIn("Veräußerungen im Steuerjahr", html)
        self.assertIn("15.05.2024", html)

    def test_bericht_hebt_steuerpflichtige_hervor(self):
        """
        Innerhalb der Frist veräußert heißt steuerlich relevant — das darf
        nicht in einer Tabellenspalte untergehen.
        """
        html = tax.als_bericht(self.auswertung()).decode("utf-8")
        self.assertIn("<b>nein</b>", html)
        self.assertIn("innerhalb der Haltefrist", html)

    def test_bericht_ohne_abgaenge_bleibt_sauber(self):
        ohne = tax.auswerten(
            [{"txid": "a" * 64, "vout": 0, "address": "bc1q", "value": 5000,
              "status": {"confirmed": True,
                         "block_time": int(datetime(2022, 5, 1).timestamp())}}],
            2024, jetzt=STICHTAG_2024,
        )
        self.assertNotIn("Veräußerungen", tax.als_bericht(ohne).decode("utf-8"))

if __name__ == "__main__":
    unittest.main()
