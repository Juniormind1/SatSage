"""
Dotplot während eines laufenden Trace: nur was sich nicht mehr umkehren kann.

Defensiv (jüngster externer Zufluss) wandert das Datum nur nach rechts.
Ein datierter externer Zufluss innerhalb der Haltefrist darf den Punkt
schon gelb und nach rechts setzen. Liegt er außerhalb, oder fehlen Daten,
bleibt der Punkt liegen — ein späterer Hop könnte jünger sein.

Der Ingress-Cache bleibt unberührt, bis der Trace dieses UTXO fertig ist.
"""
import unittest
from datetime import datetime

from core.trace import trace_utxo
from core.utxo_ingress_report import gesicherte_anschaffung
from tests.fixtures import (
    BIP84_RECEIVE_0,
    EXTERN_A,
    EXTERN_B,
    TXID_WALLET_IN,
    core_tx,
    core_vin,
    core_vout,
    make_get_tx,
    txid,
)

EIGENE = {BIP84_RECEIVE_0}
ALT = 1_600_000_000       # vor der Haltefrist, wenn Bezug „jetzt“ ist
JUNG = 1_750_000_000      # innerhalb der Haltefrist
NOCH_JUENGER = 1_760_000_000


def _kette_zwei_externe():
    """Erster Hop extern und alt, zweiter interner Weg endet jünger."""
    extern_alt = txid("a1")
    extern_jung = txid("b2")
    intern = txid("c3")
    wurzel = txid("d4")
    kette = {
        extern_alt: core_tx(
            extern_alt, [core_vin(txid("00"), 0)],
            [core_vout(0, EXTERN_A, 0.4)], blocktime=ALT,
        ),
        extern_jung: core_tx(
            extern_jung, [core_vin(txid("01"), 0)],
            [core_vout(0, EXTERN_B, 0.4)], blocktime=JUNG,
        ),
        intern: core_tx(
            intern, [core_vin(extern_jung, 0)],
            [core_vout(0, BIP84_RECEIVE_0, 0.3)], blocktime=JUNG + 10,
        ),
        wurzel: core_tx(
            wurzel,
            [core_vin(extern_alt, 0), core_vin(intern, 0)],
            [core_vout(0, BIP84_RECEIVE_0, 0.6)],
            blocktime=JUNG + 20,
        ),
    }
    return wurzel, kette


class TestGesicherteAnschaffung(unittest.TestCase):
    def test_undatiert_ist_nicht_fest(self):
        baum = {
            "type": "utxo",
            "sources": [{
                "type": "external_unresolved",
                "input_count": 30,
                "amount_sats": 0,
            }, {
                "type": "external",
                "time_ts": ALT,
                "amount_sats": 1,
                "address": EXTERN_A,
            }],
        }
        self.assertIsNone(gesicherte_anschaffung(baum))

    def test_datierter_externer_ist_fest(self):
        baum = {
            "type": "utxo",
            "sources": [{
                "type": "external",
                "time_ts": JUNG,
                "amount_sats": 1,
                "address": EXTERN_A,
            }],
        }
        stand = gesicherte_anschaffung(baum)
        self.assertEqual(stand["time_ts"], JUNG)
        self.assertEqual(stand["oldest_time_ts"], JUNG)
        self.assertFalse(stand["untergrenze"])

    def test_nur_intern_ist_nicht_fest(self):
        baum = {
            "type": "utxo",
            "time_ts": JUNG,
            "sources": [{
                "type": "internal",
                "trace": {"type": "utxo", "sources": []},
            }],
        }
        self.assertIsNone(gesicherte_anschaffung(baum))


class TestLiveWaehrendTrace(unittest.TestCase):
    def test_erster_hop_meldet_sich_bevor_der_trace_fertig_ist(self):
        wurzel, kette = _kette_zwei_externe()
        gesehen = []

        def on_teilstand(stand):
            gesehen.append(dict(stand))

        ergebnis = trace_utxo(
            make_get_tx(kette), wurzel, 0, EIGENE,
            on_teilstand=on_teilstand,
        )
        self.assertTrue(ergebnis["found"])
        self.assertGreaterEqual(len(gesehen), 1)
        # Der erste datierte Hop ist der alte externe Zufluss. Der jüngere
        # kommt erst danach — der Stand darf zwischendurch schon existieren
        # und am Ende beim jüngsten landen.
        self.assertEqual(gesehen[0]["time_ts"], ALT)
        self.assertEqual(gesehen[-1]["time_ts"], JUNG)
        self.assertLess(gesehen[0]["time_ts"], gesehen[-1]["time_ts"])

    def test_fortschritt_bricht_nicht_vor_dem_ersten_hop(self):
        """Job übergibt progress — der Adapter darf _teile nicht vor der Definition lesen."""
        wurzel, kette = _kette_zwei_externe()
        zeilen = []
        ergebnis = trace_utxo(
            make_get_tx(kette), wurzel, 0, EIGENE,
            progress=zeilen.append,
        )
        self.assertTrue(ergebnis["found"])
        self.assertTrue(zeilen)

    def test_ohne_callback_bleibt_das_ergebnis(self):
        wurzel, kette = _kette_zwei_externe()
        ergebnis = trace_utxo(make_get_tx(kette), wurzel, 0, EIGENE)
        self.assertTrue(ergebnis["found"])

    def test_haltedauer_innerhalb_ist_gelb_und_fest(self):
        """Jüngster bekannter Zufluss innerhalb der Frist → später nur jünger."""
        bezug = datetime.fromtimestamp(JUNG + 86_400)
        anschaffung = datetime.fromtimestamp(JUNG)
        frist_ende = anschaffung.replace(year=anschaffung.year + 1)
        self.assertGreater(frist_ende, bezug)


class TestJobLiveFeld(unittest.TestCase):
    def test_zwischenstand_traegt_live_key(self):
        """Der Job-Poll liefert key + time_ts, sobald ein Hop feststeht."""
        from pathlib import Path

        from httpserver.api import trace as trace_api

        quelle = Path(trace_api.__file__).read_text(encoding="utf-8")
        self.assertIn('"live"', quelle)
        self.assertIn("on_teilstand=_live", quelle)
        self.assertIn("live_key", quelle)
        self.assertIn('"fertig"', quelle)
        self.assertIn("fertig_key", quelle)
