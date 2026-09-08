"""
Eigenübertrag oder Veräußerung?

Wer ein großes UTXO in kleine aufteilt oder viele kleine zusammenlegt, gibt
Outputs aus — verkauft aber nichts. Beides als „Veräußerung" auszuweisen wäre
in einer Steueraufstellung grob falsch: Aus einer Wallet-Umsortierung würde
ein steuerpflichtiger Vorgang.

Maßgeblich ist, was **netto abgeflossen** ist: was hineinging, minus was
wieder auf eigenen Adressen landete. Bleibt davon nur die Netzwerkgebühr, war
es ein Eigenübertrag.
"""
import unittest
from datetime import datetime

from core import tax

STICHTAG = datetime(2026, 12, 31, 23, 59, 59)


def stempel(text: str) -> int:
    return int(datetime.strptime(text, "%d.%m.%Y").timestamp())


def eintrag(marker: str, sats: int, empfangen: str, *,
            ausgegeben_in: str | None = None, ausgegeben_am: str | None = None,
            adresse: str = "bc1qeigen") -> dict:
    daten = {
        "txid": marker * 64 if len(marker) == 1 else marker,
        "vout": 0, "address": adresse, "value": sats,
        "status": {"confirmed": True, "block_time": stempel(empfangen)},
        "spent": ausgegeben_in is not None,
        "spent_txid": ausgegeben_in,
    }
    if ausgegeben_am:
        daten["spent_time_ts"] = stempel(ausgegeben_am)
    return daten


class TestAufteilung(unittest.TestCase):
    """
    Der gemeldete Fall: ein großes UTXO in drei kleine aufgeteilt. Es fließt
    nur die Gebühr ab.
    """

    def auswertung(self):
        SPLIT = "5" * 64
        return tax.auswerten([
            eintrag("a", 80_000_028, "01.03.2022",
                    ausgegeben_in=SPLIT, ausgegeben_am="01.08.2026"),
            # Was aus der Split-Transaktion zurück auf eigene Adressen kam
            eintrag(SPLIT, 40_000_000, "01.08.2026"),
            dict(eintrag(SPLIT, 30_000_000, "01.08.2026"), vout=1),
            dict(eintrag(SPLIT, 9_999_632, "01.08.2026"), vout=2),
        ], 2026, jetzt=STICHTAG)

    def test_gilt_nicht_als_veraeusserung(self):
        self.assertEqual(self.auswertung()["abgaenge"], [])

    def test_wird_als_eigenuebertrag_gezaehlt(self):
        kennzahlen = self.auswertung()["kennzahlen"]
        self.assertEqual(kennzahlen["eigenuebertrag_count"], 1)

    def test_die_neuen_utxos_stehen_im_bestand(self):
        """Nach dem Aufteilen liegt dasselbe Geld da, nur anders geschnitten."""
        kennzahlen = self.auswertung()["kennzahlen"]
        self.assertEqual(kennzahlen["gesamt_count"], 3)
        self.assertEqual(kennzahlen["gesamt_sats"], 79_999_632)

    def test_hinweis_nennt_die_eigenuebertraege(self):
        hinweise = " ".join(self.auswertung()["hinweise"])
        self.assertIn("Eigenübertr", hinweise)


class TestKonsolidierung(unittest.TestCase):
    """Umgekehrt: viele kleine zu einem großen — ebenfalls kein Verkauf."""

    def test_gilt_nicht_als_veraeusserung(self):
        SAMMEL = "6" * 64
        auswertung = tax.auswerten([
            *[
                dict(eintrag(f"{i:064x}", 100_000, "01.10.2022",
                             ausgegeben_in=SAMMEL, ausgegeben_am="30.07.2025"))
                for i in range(19)
            ],
            eintrag(SAMMEL, 1_897_332, "30.07.2025"),
        ], 2025, jetzt=STICHTAG)
        self.assertEqual(auswertung["abgaenge"], [])
        self.assertEqual(auswertung["kennzahlen"]["eigenuebertrag_count"], 1)


class TestEchteVeraeusserung(unittest.TestCase):
    """Was tatsächlich weggeht, muss weiterhin erscheinen."""

    def test_ohne_rueckfluss_ist_es_eine_veraeusserung(self):
        auswertung = tax.auswerten([
            eintrag("a", 500_000, "01.03.2022",
                    ausgegeben_in="9" * 64, ausgegeben_am="15.05.2026"),
        ], 2026, jetzt=STICHTAG)
        self.assertEqual(len(auswertung["abgaenge"]), 1)
        self.assertEqual(auswertung["abgaenge"][0]["value_sats"], 500_000)

    def test_teilweiser_rueckfluss_meldet_den_abgeflossenen_teil(self):
        """
        Verkauf mit Wechselgeld: Ein Teil geht weg, der Rest kommt zurück.
        Gemeldet gehört, was tatsächlich abgeflossen ist.
        """
        ZAHLUNG = "8" * 64
        auswertung = tax.auswerten([
            eintrag("a", 1_000_000, "01.03.2022",
                    ausgegeben_in=ZAHLUNG, ausgegeben_am="15.05.2026"),
            eintrag(ZAHLUNG, 600_000, "15.05.2026"),
        ], 2026, jetzt=STICHTAG)
        abgaenge = auswertung["abgaenge"]
        self.assertEqual(len(abgaenge), 1)
        self.assertEqual(abgaenge[0]["value_sats"], 400_000)

    def test_haltefrist_gilt_weiterhin(self):
        auswertung = tax.auswerten([
            eintrag("a", 500_000, "01.03.2026",
                    ausgegeben_in="9" * 64, ausgegeben_am="15.05.2026"),
        ], 2026, jetzt=STICHTAG)
        self.assertFalse(auswertung["abgaenge"][0]["frist_erfuellt"])


class TestGrenzfaelle(unittest.TestCase):

    def test_ohne_verlauf_keine_abgaenge(self):
        utxo = {
            "txid": "a" * 64, "vout": 0, "address": "bc1q", "value": 50_000,
            "status": {"confirmed": True, "block_time": stempel("01.05.2022")},
        }
        auswertung = tax.auswerten([utxo], 2026, jetzt=STICHTAG)
        self.assertEqual(auswertung["abgaenge"], [])
        self.assertEqual(auswertung["kennzahlen"]["eigenuebertrag_count"], 0)

    def test_rueckfluss_groesser_als_einsatz(self):
        """
        Eine Transaktion kann fremde Eingänge mitbringen (CoinJoin). Dann
        kommt mehr zurück, als von uns hineinging — abgeflossen ist nichts.
        """
        CJ = "7" * 64
        auswertung = tax.auswerten([
            eintrag("a", 5_000_000, "01.03.2022",
                    ausgegeben_in=CJ, ausgegeben_am="15.12.2026"),
            eintrag(CJ, 80_000_028, "15.12.2026"),
        ], 2026, jetzt=STICHTAG)
        self.assertEqual(auswertung["abgaenge"], [])


if __name__ == "__main__":
    unittest.main()
