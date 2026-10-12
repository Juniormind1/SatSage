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
        """Der Job-Poll liefert die offene Menge und die vollen Abschlüsse."""
        from pathlib import Path

        from httpserver.api import trace as trace_api

        quelle = Path(trace_api.__file__).read_text(encoding="utf-8")
        self.assertIn('"live"', quelle)
        self.assertIn("on_teilstand=_live", quelle)
        self.assertIn("live_key", quelle)
        self.assertIn("offen_keys", quelle)
        self.assertIn("vollstaendig_keys", quelle)
        self.assertNotIn("fertig_key", quelle)
        herkunft = (
            Path(__file__).resolve().parents[1] / "web" / "views" / "herkunft.js"
        ).read_text(encoding="utf-8")
        self.assertIn("traceMarkenAusJob", herkunft)
        self.assertNotIn("traceFrageAn", herkunft)
        plot = (
            Path(__file__).resolve().parents[1] / "web" / "views" / "steuerjahr.js"
        ).read_text(encoding="utf-8")
        self.assertIn("function traceFragenSetzen", plot)
        self.assertIn("function traceWartenPruefen", plot)
        self.assertIn("TRACE_AUSRUF_MS = 1600", plot)
        self.assertIn("function steuerPlotNachEinzelTrace", plot)
        self.assertIn("fensterBehalten", plot)
        self.assertIn("steuerPlotNachEinzelTrace", herkunft)
        # Nur der Abschluss von „vervollständigen“ / „Scan neu“, nicht jedes Aufklappen.
        self.assertIn("(force || followup)", herkunft)


class TestPlotNachEinzelTrace(unittest.TestCase):
    """Voller Einzel-Trace nimmt den roten Ring sofort und lädt den Plot neu."""

    def test_voller_baum_nimmt_ring_und_behaelt_fenster(self):
        import shutil
        import subprocess

        if not shutil.which("node"):
            self.skipTest("node fehlt")
        from pathlib import Path

        quelle = (
            Path(__file__).resolve().parents[1] / "web" / "views" / "steuerjahr.js"
        ).read_text(encoding="utf-8")
        start = quelle.index("function steuerPlotNachEinzelTrace(")
        ende = quelle.index("\nfunction ", start + 10)
        funktion = quelle[start:ende]
        skript = r"""
const geladen = [];
function ladeSteuerjahr(optionen) { geladen.push(optionen || {}); return Promise.resolve(); }
function t(key) { return key === "tax.plotIncomplete" ? "Herkunft unvollständig" : key; }
const tip = { textContent: "01.01.2024\n1 sat\nWallet\nHerkunft unvollständig" };
const punkt = {
  classList: { removed: [], remove(name) { this.removed.push(name); } },
  querySelector() { return tip; },
};
function tracePunktImPlot(key) { return key === "aa:0" ? punkt : null; }
const event = { key: "aa:0", herkunft_offen: true };
const anderer = { key: "bb:0", herkunft_offen: true };
const Zustand = {
  ansicht: "steuerjahr",
  steuer: { zeitstrahl: { events: [event, anderer] } },
};
""" + funktion + r"""
steuerPlotNachEinzelTrace("aa:0", { found: true, verfolgt_vollstaendig: false });
const unvoll = {
  ring: punkt.classList.removed.slice(),
  offen: event.herkunft_offen,
  laden: geladen.length,
};
steuerPlotNachEinzelTrace("aa:0", { found: true, verfolgt_vollstaendig: true });
console.log(JSON.stringify({
  unvoll,
  ring: punkt.classList.removed,
  offen: event.herkunft_offen,
  anderer: anderer.herkunft_offen,
  tip: tip.textContent,
  laden: geladen,
}));
"""
        aus = subprocess.run(
            ["node", "-e", skript], capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(aus.returncode, 0, aus.stderr)
        import json
        roh = json.loads(aus.stdout)
        self.assertEqual(roh["unvoll"]["ring"], [])
        self.assertTrue(roh["unvoll"]["offen"])
        self.assertEqual(roh["unvoll"]["laden"], 1)
        self.assertEqual(roh["ring"], ["herkunft-offen-marke"])
        self.assertFalse(roh["offen"])
        self.assertTrue(roh["anderer"])
        self.assertNotIn("Herkunft unvollständig", roh["tip"])
        self.assertEqual(
            roh["laden"],
            [{"fensterBehalten": True}, {"fensterBehalten": True}],
        )
