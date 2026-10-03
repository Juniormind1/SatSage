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
import json
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

    def test_loeschen_entfernt_baum_und_meta(self):
        """„Scan neu“ muss den alten Stand verwerfen können."""
        trace_cache.speichern(txid("a1"), 0, BAUM, self.dir, EIGENE)
        self.assertTrue(trace_cache.vorhanden(txid("a1"), 0, self.dir))
        self.assertTrue(trace_cache.loeschen(txid("a1"), 0, self.dir))
        self.assertFalse(trace_cache.vorhanden(txid("a1"), 0, self.dir))
        self.assertIsNone(trace_cache.laden(txid("a1"), 0, self.dir, EIGENE))
        self.assertFalse(trace_cache.loeschen(txid("a1"), 0, self.dir))

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

    def test_vervollstaendigen_behaelt_fingerabdruck(self):
        trace_cache.speichern(txid("a1"), 0, BAUM, self.dir, EIGENE)
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        erstellt = geladen["erstellt_ts"]
        baum = geladen["baum"]
        baum["children"][0]["time_label"] = "01.01.2020 12:00:00"
        baum["children"][0]["block_time"] = 1_577_880_000
        self.assertIsNotNone(
            trace_cache.vervollstaendigen(
                txid("a1"), 0, baum, self.dir,
            )
        )
        danach = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        self.assertEqual(danach["erstellt_ts"], erstellt)
        self.assertFalse(danach["veraltet"])
        self.assertEqual(
            danach["baum"]["children"][0]["block_time"], 1_577_880_000,
        )

    def test_vervollstaendigen_legt_keine_neue_datei_an(self):
        baum = dict(BAUM)
        self.assertIsNone(
            trace_cache.vervollstaendigen(txid("a1"), 0, baum, self.dir)
        )
        self.assertFalse(trace_cache.vorhanden(txid("a1"), 0, self.dir))


class TestBaumZeitenNachziehen(TraceCacheBasis):

    def test_tx_cache_schreibt_zeit_in_den_baum(self):
        from core import xpub_cache
        from core.trace import baum_zeiten_nachziehen

        baum = {
            "found": True,
            "root": {"id": "0", "txid": txid("a1"), "vout": 0, "amount_sats": 1000},
            "children": [{
                "id": "0.0",
                "type": "external",
                "from_utxo": f"{txid('e1')}:0",
                "amount_sats": 1000,
                "time_label": "",
                "children": [],
            }],
        }
        trace_cache.speichern(txid("a1"), 0, baum, self.dir, EIGENE)
        ts = 1_577_880_000
        xpub_cache.save_cached_tx(txid("e1"), {
            "txid": txid("e1"),
            "status": {
                "confirmed": True,
                "block_height": 800_000,
                "block_time": ts,
            },
        }, self.dir, "test")
        n = baum_zeiten_nachziehen(
            baum, self.dir, txid=txid("a1"), vout=0,
        )
        self.assertEqual(n, 1)
        self.assertEqual(baum["children"][0]["block_time"], ts)
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        self.assertEqual(geladen["baum"]["children"][0]["block_time"], ts)
        self.assertFalse(geladen["veraltet"])

    def test_vollstaendig_schreibt_nicht(self):
        from core.trace import baum_zeiten_nachziehen

        baum = {
            "found": True,
            "root": {
                "id": "0", "txid": txid("a1"), "vout": 0, "amount_sats": 1000,
                "time_label": "01.01.2020 12:00:00", "block_time": 1_577_880_000,
            },
            "children": [{
                "id": "0.0",
                "type": "external",
                "from_utxo": f"{txid('e1')}:0",
                "time_label": "01.01.2020 12:00:00",
                "block_time": 1_577_880_000,
                "children": [],
            }],
        }
        trace_cache.speichern(txid("a1"), 0, baum, self.dir, EIGENE)
        pfad = trace_cache.pfad(txid("a1"), 0, self.dir)
        vorher = pfad.read_bytes()
        self.assertEqual(
            baum_zeiten_nachziehen(baum, self.dir, txid=txid("a1"), vout=0),
            0,
        )
        self.assertEqual(pfad.read_bytes(), vorher)


class TestExterneBlockzeiten(TraceCacheBasis):
    """Gelb zieht fehlende Blockzeiten externer Blätter nach, ohne den Walk."""

    def _baum(self, **blatt):
        kind = {
            "id": "0.0",
            "type": "external",
            "from_utxo": f"{txid('e1')}:0",
            "amount_sats": 1000,
            "time_label": "",
            "children": [],
        }
        kind.update(blatt)
        return {
            "found": True,
            "root": {"id": "0", "txid": txid("a1"), "vout": 0, "amount_sats": 1000},
            "children": [kind],
        }

    def test_fehlende_tx_wird_datiert_und_gespeichert(self):
        from core.trace import externe_blockzeiten_speichern, hat_extern_ohne_zeit

        baum = self._baum()
        trace_cache.speichern(txid("a1"), 0, baum, self.dir, EIGENE)
        self.assertTrue(hat_extern_ohne_zeit(baum))
        ts = 1_579_564_800

        def get_tx(tx_id):
            self.assertEqual(tx_id, txid("e1"))
            return {
                "txid": tx_id,
                "status": {"confirmed": True, "block_height": 613_836, "block_time": ts},
            }

        n = externe_blockzeiten_speichern(txid("a1"), 0, get_tx, self.dir)
        self.assertEqual(n, 1)
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        kind = geladen["baum"]["children"][0]
        self.assertEqual(kind["block_time"], ts)
        self.assertTrue(kind["time_label"])
        self.assertFalse(hat_extern_ohne_zeit(geladen["baum"]))

    def test_mindesthoehe_setzt_kein_datum(self):
        from core.trace import externe_blockzeiten_nachziehen

        baum = self._baum()

        def get_tx(_tx_id):
            return {
                "status": {
                    "confirmed": False,
                    "mindesthoehe": True,
                    "block_time": 1_700_000_000,
                },
            }

        self.assertEqual(externe_blockzeiten_nachziehen(baum, get_tx), 0)
        self.assertFalse(baum["children"][0].get("block_time"))

    def test_interner_knoten_ohne_datum_bleibt(self):
        from core.trace import externe_blockzeiten_nachziehen, hat_extern_ohne_zeit

        baum = self._baum(type="internal")
        self.assertFalse(hat_extern_ohne_zeit(baum))

        def get_tx(_tx_id):
            return {"status": {"confirmed": True, "block_time": 1_579_564_800}}

        self.assertEqual(externe_blockzeiten_nachziehen(baum, get_tx), 0)


class TestKnotenTabelle(TraceCacheBasis):
    """ISSUES P2 Schritt 6: Rauten stehen nur einmal in der Datei (DAG)."""

    @staticmethod
    def _raute():
        # Derselbe Vorgänger über zwei Wege: gleicher Teilbaum, andere ids.
        def vorfahr(pfad, tiefe):
            return {
                "id": pfad, "type": "internal", "depth": tiefe,
                "txid": txid("c3"), "vout": 1, "amount_sats": 5,
                "children": [{
                    "id": pfad + ".0", "type": "external", "depth": tiefe + 1,
                    "address": EXTERN_A, "amount_sats": 5,
                }],
            }
        weg = lambda i: {
            "id": f"0.{i}", "type": "internal", "depth": 1,
            "txid": txid(f"d{i}"), "vout": 0, "amount_sats": 5,
            "children": [vorfahr(f"0.{i}.0", 2)],
        }
        return {
            "found": True,
            "root": {"id": 0, "txid": txid("a1"), "vout": 0},
            "children": [weg(0), weg(1)],
            "summary": {"external_sats": 10},
            "origin_tree": {"sources": [
                {"trace": {"txid": txid("c3"), "vout": 1, "sources": []}},
                {"trace": {"txid": txid("c3"), "vout": 1, "sources": []}},
            ]},
        }

    def test_neues_format_rundlauf_exakt(self):
        baum = self._raute()
        trace_cache.speichern(txid("a1"), 0, baum, self.dir, EIGENE)
        roh = json.loads(trace_cache.pfad(txid("a1"), 0, self.dir).read_text())
        self.assertEqual(roh["version"], trace_cache.VERSION_KNOTEN)
        self.assertIn("knoten", roh)
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        self.assertEqual(geladen["baum"], baum)
        # Jede Stelle ist ein eigenes Objekt (keine geteilten Mutationen).
        k = geladen["baum"]["children"]
        self.assertIsNot(k[0]["children"][0], k[1]["children"][0])

    def test_raute_steht_einmal_in_der_datei(self):
        trace_cache.speichern(txid("a1"), 0, self._raute(), self.dir, EIGENE)
        text = trace_cache.pfad(txid("a1"), 0, self.dir).read_text()
        # Ohne Tabelle 4× (zwei Wege × Anzeige-/Rohbaum), jetzt je Form 1×.
        self.assertEqual(json.dumps(self._raute()).count(txid("c3")), 4)
        self.assertEqual(text.count(txid("c3")), 2)
        self.assertNotIn('"0.1.0"', text)

    def test_alte_dateien_bleiben_lesbar(self):
        ziel = trace_cache.pfad(txid("a1"), 0, self.dir)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(json.dumps({
            "version": 1, "txid": txid("a1"), "vout": 0, "erstellt_ts": 5,
            "adressen_fingerprint": "", "adressen_anzahl": 0,
            "baum": self._raute(),
        }))
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        self.assertEqual(geladen["baum"], self._raute())
        self.assertEqual(geladen["erstellt_ts"], 5)

    def test_ungewoehnliche_ids_bleiben_erhalten(self):
        """Nicht ableitbare id/depth werden gespeichert statt geraten."""
        baum = self._raute()
        baum["children"][1]["id"] = "x"
        del baum["children"][0]["depth"]
        trace_cache.speichern(txid("a1"), 0, baum, self.dir, EIGENE)
        geladen = trace_cache.laden(txid("a1"), 0, self.dir, EIGENE)
        self.assertEqual(geladen["baum"], baum)
        roh = json.loads(trace_cache.pfad(txid("a1"), 0, self.dir).read_text())
        # Fehlendes depth ist nicht rekonstruierbar → altes Format.
        self.assertEqual(roh["version"], trace_cache.VERSION)

    def test_kaputte_tabelle_fuehrt_zu_none(self):
        trace_cache.speichern(txid("a1"), 0, self._raute(), self.dir, EIGENE)
        ziel = trace_cache.pfad(txid("a1"), 0, self.dir)
        roh = json.loads(ziel.read_text())
        roh["knoten"] = roh["knoten"][:1]
        ziel.write_text(json.dumps(roh))
        self.assertIsNone(trace_cache.laden(txid("a1"), 0, self.dir, EIGENE))


class TestVollstaendigkeit(TraceCacheBasis):

    def test_externes_ende_ist_vollstaendig(self):
        self.assertTrue(trace_cache.baum_ist_vollstaendig(BAUM))

    def test_buendel_braucht_luecken_schliessen(self):
        baum = dict(BAUM, summary={"unresolved_inputs": 4})
        self.assertTrue(trace_cache.luecken_brauchen_buendel(baum))
        blatt = {
            "found": True,
            "children": [{"type": "external_unresolved", "children": []}],
            "summary": {},
        }
        self.assertTrue(trace_cache.luecken_brauchen_buendel(blatt))
        self.assertFalse(trace_cache.luecken_brauchen_buendel(BAUM))

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
