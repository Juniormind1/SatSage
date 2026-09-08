"""
Gespeicherte Herkunftsbäume.

Die Vorgeschichte eines bestätigten Outputs ändert sich nie — ein einmal
gebauter Baum bleibt gültig und muss beim nächsten Seitenaufruf nicht neu
erhoben werden.

Mit einer Einschränkung, um die es hier vor allem geht: Ob ein Zweig als
*intern* oder *extern* gilt, hängt davon ab, welche Adressen als eigene
bekannt sind. Kommt ein XPUB dazu oder reicht ein Scan tiefer, kann aus einem
externen Zufluss ein interner werden. Der gespeicherte Baum wird deshalb mit
einem Fingerabdruck der Adressmenge abgelegt und beim Laden dagegen geprüft.
"""
import tempfile
import unittest
from pathlib import Path

from core import trace_cache
from tests.fixtures import BIP84_CHANGE_0, BIP84_RECEIVE_0, EXTERN_A, txid

BAUM = {
    "found": True,
    "root": {"id": "0", "txid": txid("a1"), "vout": 0, "amount_sats": 1000},
    "children": [{"id": "0.0", "type": "external", "address": EXTERN_A}],
    "summary": {"external_sats": 1000},
}

EIGENE = {BIP84_RECEIVE_0, BIP84_CHANGE_0}


class TraceCacheBasis(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)


class TestRundlauf(TraceCacheBasis):

    def test_ohne_eintrag_nichts(self):
        self.assertIsNone(trace_cache.laden(txid("a1"), 0, self.dir, EIGENE))

    def test_gespeichertes_kommt_zurueck(self):
        trace_cache.speichern(txid("a1"), 0, BAUM, self.dir, EIGENE)
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        self.assertIsNotNone(geladen)
        self.assertEqual(geladen["baum"]["root"]["txid"], txid("a1"))
        self.assertFalse(geladen["veraltet"])

    def test_erstellzeitpunkt_wird_festgehalten(self):
        trace_cache.speichern(txid("a1"), 0, BAUM, self.dir, EIGENE)
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        self.assertIsInstance(geladen["erstellt_ts"], int)
        self.assertGreater(geladen["erstellt_ts"], 0)

    def test_falsches_utxo_wird_nicht_verwechselt(self):
        """Die Datei nennt ihr eigenes Ziel — ein Fehlgriff fliegt auf."""
        trace_cache.speichern(txid("a1"), 0, BAUM, self.dir, EIGENE)
        pfad = trace_cache.pfad(txid("a1"), 0, self.dir)
        pfad.rename(trace_cache.pfad(txid("b2"), 0, self.dir))
        self.assertIsNone(trace_cache.laden(txid("b2"), 0, self.dir, EIGENE))

    def test_erneutes_speichern_ueberschreibt(self):
        trace_cache.speichern(txid("a1"), 0, BAUM, self.dir, EIGENE)
        neuer = dict(BAUM, summary={"external_sats": 7})
        trace_cache.speichern(txid("a1"), 0, neuer, self.dir, EIGENE)
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        self.assertEqual(geladen["baum"]["summary"]["external_sats"], 7)

    def test_kaputte_datei_fuehrt_nicht_zum_absturz(self):
        pfad = trace_cache.pfad(txid("a1"), 0, self.dir)
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text("{kaputt", encoding="utf-8")
        self.assertIsNone(trace_cache.laden(txid("a1"), 0, self.dir, EIGENE))

    def test_ohne_verzeichnis_wird_nichts_geschrieben(self):
        """Ein Trace zum bloßen Ansehen soll keine Spuren hinterlassen."""
        self.assertIsNone(
            trace_cache.speichern(txid("a1"), 0, BAUM, None, EIGENE)
        )


class TestVollstaendigkeit(TraceCacheBasis):

    def test_externes_ende_ist_vollstaendig(self):
        self.assertTrue(trace_cache.baum_ist_vollstaendig(BAUM))

    def test_unaufgeloeste_eingaenge_sind_unvollstaendig(self):
        baum = dict(BAUM, summary={"external_sats": 1000, "unresolved_inputs": 4})
        self.assertFalse(trace_cache.baum_ist_vollstaendig(baum))

    def test_leere_interne_blaetter_sind_unvollstaendig(self):
        """
        external_count > 0 reicht nicht: grüne Blätter ohne Kinder (Raute/
        abgebrochener Ast) halten den Baum unvollständig — Entwirren muss
        weiterlaufen bis rot/lila.
        """
        baum = {
            "found": True,
            "children": [
                {"type": "external", "children": []},
                {
                    "type": "internal",
                    "from_utxo": f"{txid('m1')}:0",
                    "children": [],
                },
            ],
            "summary": {
                "external_count": 1,
                "unresolved_inputs": 0,
                "coinbase": False,
            },
        }
        self.assertFalse(trace_cache.baum_ist_vollstaendig(baum))

    def test_nur_externe_und_coinbase_blaetter_sind_vollstaendig(self):
        baum = {
            "found": True,
            "children": [
                {
                    "type": "internal",
                    "children": [
                        {"type": "external", "children": []},
                        {"type": "coinbase", "children": []},
                    ],
                }
            ],
            "summary": {"external_count": 1, "unresolved_inputs": 0, "coinbase": True},
        }
        self.assertTrue(trace_cache.baum_ist_vollstaendig(baum))

    def test_kopf_meldet_vollstaendig(self):
        baum = dict(
            BAUM,
            summary={"external_count": 1, "unresolved_inputs": 0},
        )
        trace_cache.speichern(txid("a1"), 0, baum, self.dir, EIGENE)
        kopf = trace_cache.kopf(txid("a1"), 0, self.dir, EIGENE)
        self.assertTrue(kopf["vollstaendig"])

    def test_veralteter_baum_kann_trotzdem_vollstaendig_sein(self):
        """Neue Adressen machen unsicher, nicht lückenhaft."""
        baum = dict(
            BAUM,
            summary={"external_count": 1, "unresolved_inputs": 0},
        )
        trace_cache.speichern(txid("a1"), 0, baum, self.dir, EIGENE)
        kopf = trace_cache.kopf(txid("a1"), 0, self.dir, EIGENE | {EXTERN_A})
        self.assertTrue(kopf["veraltet"])
        self.assertTrue(kopf["vollstaendig"])


class TestVeraltet(TraceCacheBasis):
    """Geänderte Adressmenge: anzeigen, aber die Unsicherheit dranschreiben."""

    def setUp(self):
        super().setUp()
        trace_cache.speichern(txid("a1"), 0, BAUM, self.dir, EIGENE)

    def test_gleiche_adressen_sind_nicht_veraltet(self):
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        self.assertFalse(geladen["veraltet"])

    def test_neue_adresse_macht_veraltet(self):
        geladen = trace_cache.laden(
            txid("a1"), 0, self.dir, EIGENE | {EXTERN_A}
        )
        self.assertTrue(geladen["veraltet"])

    def test_veralteter_baum_wird_trotzdem_geliefert(self):
        """Verwerfen wäre Datenverlust — die Warnung steht am Baum."""
        geladen = trace_cache.laden(
            txid("a1"), 0, self.dir, EIGENE | {EXTERN_A}
        )
        self.assertEqual(geladen["baum"]["root"]["txid"], txid("a1"))

    def test_zahl_der_neuen_adressen_wird_genannt(self):
        geladen = trace_cache.laden(
            txid("a1"), 0, self.dir, EIGENE | {EXTERN_A}
        )
        self.assertEqual(geladen["adressen_seither"], 1)

    def test_ohne_adressmenge_keine_aussage(self):
        """
        Wer die eigenen Adressen nicht kennt, darf nichts behaupten — weder
        „aktuell" noch „veraltet".
        """
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, None)
        self.assertFalse(geladen["veraltet"])
        self.assertIsNone(geladen["adressen_seither"])


class TestUeberTraceUtxo(unittest.TestCase):
    """
    Der Weg, den die Oberfläche geht: einmal verfolgen, danach ohne jede
    Abfrage wiederfinden.
    """

    def setUp(self):
        from core.trace import trace_utxo
        from tests.fixtures import TXID_WALLET_IN, make_get_tx, simple_chain

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.immutable = Path(self._tmp.name) / "immutable_cache"
        self.ziel = TXID_WALLET_IN

        trace_utxo(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE,
            immutable_cache_dir=self.immutable,
        )

    def test_baum_liegt_danach_vor(self):
        self.assertTrue(
            trace_cache.vorhanden(self.ziel, 0, self.immutable)
        )

    def test_baum_kommt_ohne_get_tx_zurueck(self):
        geladen = trace_cache.laden(self.ziel, 0, self.immutable, EIGENE)
        self.assertIsNotNone(geladen)
        self.assertTrue(geladen["baum"]["found"])
        self.assertEqual(geladen["baum"]["root"]["txid"], self.ziel)
        self.assertTrue(geladen["baum"]["children"])

    def test_fehlgeschlagene_analyse_wird_nicht_abgelegt(self):
        """
        Ein gespeichertes „nicht gefunden" würde beim nächsten Aufruf einen
        Fehler zeigen, statt es noch einmal zu versuchen.
        """
        from core.trace import trace_utxo

        def kaputt(_txid):
            raise KeyError("unbekannt")

        trace_utxo(
            kaputt, txid("cc"), 0, EIGENE,
            immutable_cache_dir=self.immutable,
        )
        self.assertFalse(trace_cache.vorhanden(txid("cc"), 0, self.immutable))


class TestFingerabdruck(unittest.TestCase):

    def test_reihenfolge_ist_egal(self):
        a = trace_cache.fingerabdruck({"x", "y", "z"})
        b = trace_cache.fingerabdruck({"z", "x", "y"})
        self.assertEqual(a, b)

    def test_andere_menge_anderer_abdruck(self):
        a = trace_cache.fingerabdruck({"x", "y"})
        b = trace_cache.fingerabdruck({"x", "y", "z"})
        self.assertNotEqual(a, b)

    def test_leere_menge_ohne_abdruck(self):
        self.assertEqual(trace_cache.fingerabdruck(set()), "")


if __name__ == "__main__":
    unittest.main()
