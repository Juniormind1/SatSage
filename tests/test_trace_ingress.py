"""
Herkunftsanalyse muss ihr Ergebnis in den Ingress-Cache schreiben.

Die Steuerjahr-Auswertung liest das Anschaffungsdatum ausschließlich von dort
(`core.tax._anschaffung`). Verfolgt eine Oberfläche die Herkunft, ohne den
Eintrag zu hinterlassen, sieht die Auswertung anschließend nichts davon und
fällt auf das Entstehungsdatum des Outputs zurück — die Zeile behauptet dann
"nur Output-Datum", obwohl die Herkunft längst bekannt ist.

Das CLI schreibt den Eintrag seit jeher. Diese Tests halten fest, dass der Weg
über `core.trace` — also die Web-Oberfläche — dasselbe tut.
"""
import tempfile
import unittest
from pathlib import Path

import main
import server
from core import tax
from core.trace import trace_utxo
from tests.fixtures import (
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    TXID_WALLET_IN,
    make_get_tx,
    simple_chain,
)

EIGENE = {BIP84_RECEIVE_0, BIP84_CHANGE_0}

#: Blockzeit des externen Zuflusses in simple_chain (TXID_EXTERN).
EXTERN_TS = 1_690_000_000


class TestIngressWirdGeschrieben(unittest.TestCase):
    """core.trace hinterlässt denselben Eintrag wie das CLI."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Eine Ebene tiefer: resolve_immutable_cache_dir legt den
        # Immutable-Cache neben dem UTXO-Cache an (parent/immutable_cache).
        # Läge self.cache direkt auf /tmp, teilten sich alle Tests
        # /tmp/immutable_cache und sähen gegenseitig ihre Einträge.
        self.cache = Path(self._tmp.name) / "utxo_cache"
        self.cache.mkdir()

    def trace(self):
        return trace_utxo(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE,
            cache_dir=self.cache,
        )

    def test_eintrag_entsteht(self):
        self.trace()
        eintrag = main.load_utxo_ingress_cache(
            TXID_WALLET_IN, 0, main.resolve_immutable_cache_dir(
                utxo_cache_dir=self.cache
            )
        )
        self.assertIsNotNone(
            eintrag,
            "Nach dem Tracen muss ein Ingress-Eintrag vorliegen — sonst zeigt "
            "das Steuerjahr weiterhin 'nur Output-Datum'.",
        )

    def test_externes_anschaffungsdatum_steht_drin(self):
        self.trace()
        eintrag = main.load_utxo_ingress_cache(
            TXID_WALLET_IN, 0, main.resolve_immutable_cache_dir(
                utxo_cache_dir=self.cache
            )
        )
        self.assertEqual(eintrag["external_time_ts"], EXTERN_TS)

    def test_ohne_cache_dir_wird_nichts_geschrieben(self):
        """Ein Trace ohne Cache-Verzeichnis darf nirgends hinschreiben."""
        ergebnis = trace_utxo(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE
        )
        self.assertTrue(ergebnis["found"])
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_eigenes_immutable_verzeichnis_gewinnt(self):
        """
        Mit --immutable-cache-dir liest der Server aus einem Verzeichnis, das
        nicht neben dem UTXO-Cache liegt. Würde das Schreibziel weiterhin aus
        cache_dir abgeleitet, liefe der Eintrag daran vorbei — und die
        Steuerjahr-Tabelle bliebe bei "nur Output-Datum".
        """
        eigenes = Path(self._tmp.name) / "woanders"
        trace_utxo(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE,
            cache_dir=self.cache,
            immutable_cache_dir=eigenes,
        )
        self.assertIsNotNone(
            main.load_utxo_ingress_cache(TXID_WALLET_IN, 0, eigenes),
            "Der Eintrag muss im ausdrücklich benannten Verzeichnis liegen.",
        )
        abgeleitet = main.resolve_immutable_cache_dir(utxo_cache_dir=self.cache)
        self.assertIsNone(
            main.load_utxo_ingress_cache(TXID_WALLET_IN, 0, abgeleitet),
            "Und nicht im aus cache_dir abgeleiteten Verzeichnis.",
        )


class TestVeralteteEintraege(unittest.TestCase):
    """
    „Herkunft aller UTXOs" muss Einträge aus der Zeit vor dem externen
    Anschaffungsdatum erneut verfolgen — sonst bleiben sie für immer bei
    „nur Wallet-Eingang".
    """

    def test_fehlender_eintrag_ist_offen(self):
        self.assertTrue(server._ingress_veraltet(None))

    def test_alter_eintrag_ohne_externes_feld_ist_offen(self):
        alt = {
            "txid": TXID_WALLET_IN, "vout": 0,
            "youngest_time_ts": 1_724_342_731,
            "youngest_wallet": "Pocket",
        }
        self.assertTrue(server._ingress_veraltet(alt))

    def test_neuer_eintrag_mit_datum_ist_fertig(self):
        neu = {"txid": TXID_WALLET_IN, "vout": 0,
               "external_time_ts": EXTERN_TS}
        self.assertFalse(server._ingress_veraltet(neu))

    def test_neuer_eintrag_ohne_datum_ist_ebenfalls_fertig(self):
        """
        Der Schlüssel ist da, der Wert leer: Die Datenquelle gab keine
        Blockzeiten her. Ein weiterer Lauf brächte dasselbe — nicht erneut
        verfolgen.
        """
        neu = {"txid": TXID_WALLET_IN, "vout": 0, "external_time_ts": None}
        self.assertFalse(server._ingress_veraltet(neu))


class TestSteuerjahrSiehtDieHerkunft(unittest.TestCase):
    """
    Der eigentliche Befund: Nach dem Tracen darf die Grundlage nicht mehr
    "nur Output-Datum" sein.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Eine Ebene tiefer: resolve_immutable_cache_dir legt den
        # Immutable-Cache neben dem UTXO-Cache an (parent/immutable_cache).
        # Läge self.cache direkt auf /tmp, teilten sich alle Tests
        # /tmp/immutable_cache und sähen gegenseitig ihre Einträge.
        self.cache = Path(self._tmp.name) / "utxo_cache"
        self.cache.mkdir()
        self.immutable = main.resolve_immutable_cache_dir(
            utxo_cache_dir=self.cache
        )

    def utxo(self):
        return {
            "txid": TXID_WALLET_IN,
            "vout": 0,
            "address": BIP84_RECEIVE_0,
            "value": 60_000_000,
            # Der Output selbst entstand deutlich später als der externe
            # Zufluss — genau der Unterschied, um den es geht.
            "status": {"block_time": 1_700_000_000, "confirmed": True},
        }

    def test_grundlage_vor_dem_tracen(self):
        auswertung = tax.auswerten(
            [self.utxo()], 2026, immutable_cache_dir=self.immutable
        )
        eintrag = auswertung["eintraege"][0]
        self.assertEqual(eintrag["grundlage"], tax.GRUNDLAGE_OUTPUT)

    def test_grundlage_nach_dem_tracen(self):
        trace_utxo(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE,
            cache_dir=self.cache,
        )
        auswertung = tax.auswerten(
            [self.utxo()], 2026, immutable_cache_dir=self.immutable
        )
        eintrag = auswertung["eintraege"][0]
        self.assertEqual(
            eintrag["grundlage"], tax.GRUNDLAGE_HERKUNFT,
            "Nach dem Tracen muss die Grundlage 'Herkunft verfolgt' sein.",
        )
        self.assertEqual(eintrag["datum"], "22.07.2023")


if __name__ == "__main__":
    unittest.main()
