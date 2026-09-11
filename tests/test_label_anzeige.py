"""
Kommt die Beschriftung dort an, wo sie hingehört?

Das Nachschlagen selbst prüft test_labels. Hier geht es um die Verdrahtung:
Ein Label, das nur im Modul existiert und nie an der Oberfläche ankommt, wäre
unsichtbar — und ein fehlender Schlüssel im Knoten fällt erst im Browser auf.
"""
import json
import struct
import tempfile
import unittest
from pathlib import Path

import labels
from core import trace as trace_mod
from core import utxos as utxos_mod
from tests.test_labels import baue_filter, baue_index

BOERSE = "1BoerseAAA"


class LabelBestand(unittest.TestCase):
    """Legt einen kleinen Bestand an und macht ihn zum aktiven."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / labels.FILTER_NAME).write_bytes(baue_filter([BOERSE]))
        (self.dir / labels.INDEX_NAME).write_bytes(
            baue_index([(BOERSE, "Kraken", "exchange")])
        )
        labels.setze_verzeichnis(self.dir)
        self.addCleanup(labels.setze_verzeichnis, None)


class TestHerkunftsbaum(LabelBestand):

    def knoten(self, adresse: str) -> dict:
        return trace_mod._kind_knoten(
            {"type": "external", "address": adresse, "amount_sats": 50_000},
            None, "0", 1,
        )

    def test_externer_knoten_wird_beschriftet(self):
        knoten = self.knoten(BOERSE)
        self.assertIsNotNone(knoten["label"])
        self.assertEqual(knoten["label"]["name"], "Kraken")
        self.assertEqual(knoten["label"]["kategorie_label"], "Börse")

    def test_unbekannte_adresse_bekommt_kein_label(self):
        self.assertIsNone(self.knoten("1Unbekannt999")["label"])

    def test_der_schluessel_fehlt_nie(self):
        """
        Die Oberfläche liest ``knoten.label`` unbesehen. Fehlt der Schlüssel
        bei einem Typ ganz, wäre das ein Unterschied zwischen „unbekannt" und
        „nicht nachgeschaut", den niemand sieht.
        """
        for typ in ("internal", "coinbase", "external_unresolved"):
            knoten = trace_mod._kind_knoten(
                {"type": typ, "address": BOERSE, "amount_sats": 1}, None, "0", 1
            )
            self.assertIn("label", knoten, typ)
            self.assertIsNone(knoten["label"], typ)


class TestUtxoListe(LabelBestand):

    def eintrag(self, externe_adresse: str) -> dict:
        """Legt einen Ingress-Cache an und liest den UTXO-Eintrag daraus."""
        immutable = self.dir / "immutable"
        ziel = immutable / "utxo_ingress"
        ziel.mkdir(parents=True, exist_ok=True)
        txid = "a" * 64
        (ziel / f"{txid}_0.json").write_text(json.dumps({
            "txid": txid, "vout": 0,
            "youngest_time": "01.03.2022 10:00",
            "external_address": externe_adresse,
            "external_time_ts": 1_646_130_000,
        }), encoding="utf-8")

        return utxos_mod.utxo_as_dict(
            {"txid": txid, "vout": 0, "address": "bc1qeigen", "value": 100_000,
             "status": {"confirmed": True, "block_time": 1_646_130_000}},
            immutable_cache_dir=immutable,
        )

    def test_herkunftsadresse_wird_beschriftet(self):
        eintrag = self.eintrag(BOERSE)
        self.assertIsNotNone(eintrag["herkunft_label"])
        self.assertEqual(eintrag["herkunft_label"]["name"], "Kraken")

    def test_ohne_treffer_bleibt_das_feld_leer(self):
        self.assertIsNone(self.eintrag("1Unbekannt999")["herkunft_label"])

    def test_ohne_ingress_cache_gibt_es_das_feld_trotzdem(self):
        eintrag = utxos_mod.utxo_as_dict(
            {"txid": "b" * 64, "vout": 0, "address": "bc1qeigen",
             "value": 1, "status": {"confirmed": True}}
        )
        self.assertIn("herkunft_label", eintrag)
        self.assertIsNone(eintrag["herkunft_label"])


class TestOberflaeche(unittest.TestCase):
    """Die Anzeige muss beide Arten unterscheiden."""

    def setUp(self):
        web = Path(__file__).resolve().parent.parent / "web"
        self.js = (web / "app.js").read_text(encoding="utf-8")
        self.html = (web / "index.html").read_text(encoding="utf-8")

    def test_erwaehnung_wird_anders_formuliert_als_ein_dienst(self):
        marke = self.js[self.js.index("function labelMarke"):]
        marke = marke[:marke.index("\nfunction ")]
        self.assertIn('label.art === "erwaehnung"', marke)
        self.assertIn('t("labels.mentionedOn"', marke)
        self.assertIn("kategorie_label", marke)
        de = (Path(__file__).resolve().parent.parent / "web" / "locales" / "de.json")
        self.assertIn("erwähnt", de.read_text(encoding="utf-8"))

    def test_datenstand_steht_im_hilfetext(self):
        marke = self.js[self.js.index("function labelMarke"):]
        marke = marke[:marke.index("\nfunction ")]
        self.assertIn('t("labels.dataHint")', marke)

    def test_einstellungen_haben_die_karte(self):
        for kennung in ("label-laden", "label-verwerfen", "label-variante",
                        "label-status"):
            self.assertIn(f'id="{kennung}"', self.html)


if __name__ == "__main__":
    unittest.main()
