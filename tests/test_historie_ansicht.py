"""
Bereits ausgegebene Outputs in der Herkunftsansicht.

Ein UTXO verschwindet aus dem Cache, sobald es ausgegeben wurde. Wer nachsehen
will, woher die Sats kamen, die das Gerät längst verlassen haben, findet sie
dort nicht mehr — und genau das ist der häufige Fall: Man erinnert sich an
einen Abgang und will wissen, was da eigentlich weggegangen ist.

Der Verlauf kennt sie. Diese Schicht bringt sie in dieselbe Form wie UTXOs,
damit die Ansicht sie ohne Sonderweg zeigen und tracen kann.
"""
import unittest

from core.utxos import historische_eintraege, utxo_key
from tests.fixtures import BIP84_RECEIVE_0, BIP84_RECEIVE_1, txid


def eintrag(marker: str, sats: int, *, ausgegeben_ts: int | None = None,
            adresse: str = BIP84_RECEIVE_0) -> dict:
    daten = {
        "txid": txid(marker), "vout": 0, "address": adresse, "value": sats,
        "status": {"confirmed": True, "block_time": 1_700_000_000},
        "spent": ausgegeben_ts is not None,
        "spent_txid": txid("ff") if ausgegeben_ts else None,
    }
    if ausgegeben_ts:
        daten["spent_time_ts"] = ausgegeben_ts
    return daten


class TestAuswahl(unittest.TestCase):

    def test_nur_ausgegebene(self):
        """Unverbrauchtes steht schon in der oberen Liste — hier wäre es doppelt."""
        ergebnis = historische_eintraege([
            eintrag("a1", 100_000),
            eintrag("a2", 200_000, ausgegeben_ts=1_760_000_000),
        ])
        self.assertEqual(ergebnis["total_count"], 1)
        self.assertEqual(ergebnis["utxos"][0]["value_sats"], 200_000)

    def test_leerer_verlauf(self):
        ergebnis = historische_eintraege([])
        self.assertEqual(ergebnis["total_count"], 0)
        self.assertEqual(ergebnis["utxos"], [])
        self.assertEqual(ergebnis["addresses"], [])

    def test_summe_ueber_alle_nicht_nur_angezeigte(self):
        """
        Wie in der UTXO-Liste: Aus einer gekürzten Ansicht darf man keinen
        falschen Gesamtbetrag ablesen.
        """
        verlauf = [
            eintrag(f"{i:02x}", 10_000, ausgegeben_ts=1_760_000_000 + i)
            for i in range(10)
        ]
        ergebnis = historische_eintraege(verlauf, limit=3)
        self.assertEqual(ergebnis["shown_count"], 3)
        self.assertEqual(ergebnis["total_count"], 10)
        self.assertEqual(ergebnis["total_sats"], 100_000)


class TestSortierung(unittest.TestCase):

    def test_juengster_abgang_zuerst(self):
        """Gesucht wird meist das zuletzt Bewegte."""
        ergebnis = historische_eintraege([
            eintrag("a1", 1, ausgegeben_ts=1_700_000_000),
            eintrag("a3", 3, ausgegeben_ts=1_800_000_000),
            eintrag("a2", 2, ausgegeben_ts=1_750_000_000),
        ])
        self.assertEqual(
            [e["value_sats"] for e in ergebnis["utxos"]], [3, 2, 1]
        )

    def test_ohne_abgangszeit_ans_ende(self):
        ergebnis = historische_eintraege([
            {"txid": txid("b1"), "vout": 0, "address": BIP84_RECEIVE_0,
             "value": 5, "status": {"confirmed": True}, "spent": True,
             "spent_txid": txid("ff")},
            eintrag("a1", 9, ausgegeben_ts=1_800_000_000),
        ])
        self.assertEqual([e["value_sats"] for e in ergebnis["utxos"]], [9, 5])


class TestForm(unittest.TestCase):
    """Dieselbe Form wie ein UTXO — sonst bräuchte die Ansicht einen Sonderweg."""

    def ergebnis(self):
        return historische_eintraege([
            eintrag("a1", 250_000, ausgegeben_ts=1_760_000_000)
        ])

    def test_traegt_einen_schluessel_zum_tracen(self):
        eintrag_dict = self.ergebnis()["utxos"][0]
        self.assertEqual(eintrag_dict["key"], f"{txid('a1')}:0")
        self.assertEqual(eintrag_dict["key"], utxo_key(eintrag_dict))

    def test_ist_als_ausgegeben_gekennzeichnet(self):
        eintrag_dict = self.ergebnis()["utxos"][0]
        self.assertTrue(eintrag_dict["spent"])
        self.assertEqual(eintrag_dict["spent_txid"], txid("ff"))
        self.assertEqual(eintrag_dict["spent_time_ts"], 1_760_000_000)

    def test_hat_die_ueblichen_felder(self):
        eintrag_dict = self.ergebnis()["utxos"][0]
        for feld in ("txid", "vout", "address", "value_sats", "time_label"):
            self.assertIn(feld, eintrag_dict)

    def test_nach_adressen_gruppiert(self):
        ergebnis = historische_eintraege([
            eintrag("a1", 1, ausgegeben_ts=1, adresse=BIP84_RECEIVE_0),
            eintrag("a2", 2, ausgegeben_ts=2, adresse=BIP84_RECEIVE_0),
            eintrag("a3", 3, ausgegeben_ts=3, adresse=BIP84_RECEIVE_1),
        ])
        gruppen = {g["address"]: g["utxo_count"] for g in ergebnis["addresses"]}
        self.assertEqual(gruppen[BIP84_RECEIVE_0], 2)
        self.assertEqual(gruppen[BIP84_RECEIVE_1], 1)


if __name__ == "__main__":
    unittest.main()
