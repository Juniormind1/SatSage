"""
Erzwingen baut neu, veraltete Bäume auch; alte Fassungen gelten als fehlend.

Release 1.0.1, Befund 1: „Herkunft erzwingen“ setzte auf dem gespeicherten
Rohbaum auf. Ein vollständiger Baum wurde unverändert übernommen — auch
dann, wenn er mit einer anderen Adressmenge (neues XPUB, höheres Gap-Limit)
oder mit falsch kodierten Adressen entstanden war. Eigene Eingänge galten
darin als extern, die Anschaffung fiel zu jung aus.
"""
import json
import tempfile
import unittest
from pathlib import Path

from core import trace_cache, xpub_cache
from core.trace import trace_utxo
from tests.fixtures import (
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    EXTERN_A,
    TXID_WALLET_IN,
    core_tx,
    core_vin,
    core_vout,
    make_get_tx,
    simple_chain,
    txid,
)

#: Eigener Hop: TXID_WALLET_IN:0 (RECEIVE_0) → TXID_HOP:0 (CHANGE_0).
TXID_HOP = txid("d4")
HOP_TS = 1_710_000_000


def _kette() -> dict:
    kette = simple_chain()
    hop = core_tx(
        TXID_HOP,
        [core_vin(TXID_WALLET_IN, 0)],
        [core_vout(0, BIP84_CHANGE_0, 0.59)],
        blocktime=HOP_TS,
    )
    kette[hop["txid"]] = hop
    return kette


class Basis(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.imm = Path(self._tmp.name) / "immutable_cache"
        self.imm.mkdir()
        self.get_tx = make_get_tx(_kette())

    def trace(self, eigene, *, resume=None):
        return trace_utxo(
            self.get_tx, TXID_HOP, 0, eigene,
            immutable_cache_dir=self.imm,
            resume_origin=resume,
        )

    def ingress(self):
        return xpub_cache.load_utxo_ingress_cache(TXID_HOP, 0, self.imm)


class TestSchema(Basis):

    def test_ingress_und_baum_tragen_die_fassung(self):
        self.trace({BIP84_RECEIVE_0, BIP84_CHANGE_0})
        roh = json.loads(
            xpub_cache._utxo_ingress_cache_path(TXID_HOP, 0, self.imm)
            .read_text(encoding="utf-8")
        )
        self.assertEqual(roh["schema"], xpub_cache.HERKUNFT_SCHEMA)
        baum = json.loads(trace_cache.pfad(TXID_HOP, 0, self.imm).read_text())
        self.assertEqual(baum["schema"], trace_cache.SCHEMA)
        meta = json.loads(trace_cache.meta_pfad(TXID_HOP, 0, self.imm).read_text())
        self.assertEqual(meta["schema"], trace_cache.SCHEMA)

    def _alt_machen(self):
        """Wie ein Cache vor 1.0.1: Dateien ohne ``schema``."""
        for pfad in (
            xpub_cache._utxo_ingress_cache_path(TXID_HOP, 0, self.imm),
            trace_cache.pfad(TXID_HOP, 0, self.imm),
            trace_cache.meta_pfad(TXID_HOP, 0, self.imm),
        ):
            daten = json.loads(pfad.read_text(encoding="utf-8"))
            daten.pop("schema", None)
            pfad.write_text(json.dumps(daten), encoding="utf-8")

    def test_alte_fassung_gilt_als_nicht_verfolgt(self):
        eigene = {BIP84_RECEIVE_0, BIP84_CHANGE_0}
        self.trace(eigene)
        self._alt_machen()
        self.assertIsNone(self.ingress())
        self.assertEqual(xpub_cache.iter_utxo_ingress_cache_entries(self.imm), [])
        self.assertIsNone(trace_cache.laden(TXID_HOP, 0, self.imm, eigene))
        self.assertIsNone(trace_cache.kopf(TXID_HOP, 0, self.imm, eigene))
        self.assertIsNone(
            trace_cache.fortsetzbarer_origin(TXID_HOP, 0, self.imm, eigene)
        )

    def test_neuer_lauf_ersetzt_die_alte_fassung(self):
        eigene = {BIP84_RECEIVE_0, BIP84_CHANGE_0}
        self.trace(eigene)
        self._alt_machen()
        self.trace(eigene)
        self.assertIsNotNone(self.ingress())
        self.assertTrue(trace_cache.kopf(TXID_HOP, 0, self.imm, eigene)["vollstaendig"])

    def test_steuer_faellt_bei_alter_fassung_auf_output_datum(self):
        from core import tax

        self.trace({BIP84_RECEIVE_0, BIP84_CHANGE_0})
        self._alt_machen()
        utxo = {
            "txid": TXID_HOP, "vout": 0, "address": BIP84_CHANGE_0,
            "value": 59_000_000,
            "status": {"confirmed": True, "block_time": HOP_TS},
        }
        eintrag = tax.auswerten([utxo], 2025, immutable_cache_dir=self.imm)["eintraege"][0]
        self.assertFalse(eintrag["geprueft"])
        self.assertEqual(eintrag["time_ts"], HOP_TS)


class TestFortsetzbar(Basis):

    def test_erzwingen_setzt_nie_fort(self):
        eigene = {BIP84_RECEIVE_0, BIP84_CHANGE_0}
        self.trace(eigene)
        self.assertIsNotNone(
            trace_cache.fortsetzbarer_origin(TXID_HOP, 0, self.imm, eigene)
        )
        self.assertIsNone(
            trace_cache.fortsetzbarer_origin(
                TXID_HOP, 0, self.imm, eigene, erzwingen=True,
            )
        )

    def test_scan_neu_setzt_fertigen_baum_nicht_fort(self):
        eigene = {BIP84_RECEIVE_0, BIP84_CHANGE_0}
        self.trace(eigene)
        self.assertIsNone(
            trace_cache.fortsetzbarer_origin(
                TXID_HOP, 0, self.imm, eigene, nur_unvollstaendig=True,
            )
        )

    def test_veralteter_baum_wird_neu_gebaut(self):
        """
        Erst ohne RECEIVE_0: der Hop-Eingang gilt als extern (jung, 2023-11).
        Mit RECEIVE_0 ist der Baum veraltet — er darf nicht fortgesetzt
        werden, sonst bliebe die junge Anschaffung stehen.
        """
        self.trace({BIP84_CHANGE_0})
        alt = self.ingress()["external_time_ts"]
        eigene = {BIP84_RECEIVE_0, BIP84_CHANGE_0}
        resume = trace_cache.fortsetzbarer_origin(TXID_HOP, 0, self.imm, eigene)
        self.assertIsNone(resume)
        # Gegenprobe: Fortsetzen übernähme den fertigen alten Baum.
        stale = trace_cache.laden(TXID_HOP, 0, self.imm, eigene)["baum"]["origin_tree"]
        self.trace(eigene, resume=stale)
        self.assertEqual(self.ingress()["external_time_ts"], alt)
        # Neu gebaut: der Eingang ist eigen, die Herkunft reicht weiter zurück.
        self.trace(eigene, resume=resume)
        self.assertLess(self.ingress()["external_time_ts"], alt)

    def test_eigenes_blatt_als_extern_wird_neu_gebaut(self):
        """
        Gleicher Fingerabdruck, aber ein externes Blatt ist eine eigene
        Adresse (so sahen die Bäume vor dem HRP-Fix aus).
        """
        eigene = {BIP84_RECEIVE_0, BIP84_CHANGE_0}
        self.trace({BIP84_CHANGE_0})
        geladen = trace_cache.laden(TXID_HOP, 0, self.imm)
        trace_cache._schreibe_nutzlast(
            trace_cache.pfad(TXID_HOP, 0, self.imm), TXID_HOP, 0,
            geladen["baum"],
            erstellt_ts=1, fingerprint=trace_cache.fingerabdruck(eigene),
            anzahl=len(eigene), immutable_cache_dir=self.imm,
        )
        origin = trace_cache.laden(TXID_HOP, 0, self.imm, eigene)["baum"]["origin_tree"]
        self.assertEqual(trace_cache.externes_blatt_eigen(origin, eigene), BIP84_RECEIVE_0)
        self.assertIsNone(
            trace_cache.fortsetzbarer_origin(TXID_HOP, 0, self.imm, eigene)
        )

    def test_fremdes_blatt_bleibt_fortsetzbar(self):
        eigene = {BIP84_RECEIVE_0, BIP84_CHANGE_0}
        self.trace(eigene)
        origin = trace_cache.laden(TXID_HOP, 0, self.imm, eigene)["baum"]["origin_tree"]
        self.assertIsNone(trace_cache.externes_blatt_eigen(origin, eigene))
        self.assertIsNone(trace_cache.externes_blatt_eigen(origin, {EXTERN_A + "x"}))


class TestOffenBasis(Basis):
    """``/trace/alle``: alte Fassung zählt wie „nie verfolgt“."""

    def test_alte_fassung_ist_offen(self):
        from types import SimpleNamespace

        from httpserver.trace_helpers import _trace_offen_basis

        eigene = {BIP84_RECEIVE_0, BIP84_CHANGE_0}
        self.trace(eigene)
        state = SimpleNamespace(immutable_cache_dir=self.imm)
        utxo = [{"txid": TXID_HOP, "vout": 0}]
        self.assertEqual(_trace_offen_basis(state, utxo, eigene), [])
        TestSchema._alt_machen(self)
        self.assertEqual(_trace_offen_basis(state, utxo, eigene), [(TXID_HOP, 0)])


if __name__ == "__main__":
    unittest.main()
