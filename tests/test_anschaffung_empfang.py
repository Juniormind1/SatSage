"""
Anschaffung = Empfang durch das Wallet (Release 1.0.1).

Ein externer Zufluss gilt als angeschafft, wenn die Sats auf der eigenen
Adresse ankommen: Blockzeit der Tx, in der der fremde Input ins Wallet
eingeht. Bis 1.0.0 zählte die Blockzeit des fremden Prevouts — also seit
wann die Sats beim Absender lagen. Die Haltefrist begann dadurch zu früh.

Kette (simple_chain + eigener Hop):

    TXID_EXTERN 1_690_000_000 (fremd, EXTERN_A)
      → TXID_WALLET_IN:0 1_700_000_000 (RECEIVE_0, Empfang)
      → TXID_HOP:0 1_710_000_000 (CHANGE_0, interner Übertrag)
"""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core import tax, xpub_cache
from core.trace import trace_utxo
from tests.fixtures import (
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    TXID_WALLET_IN,
    core_tx,
    core_vin,
    core_vout,
    make_get_tx,
    simple_chain,
    txid,
)

TXID_HOP = txid("d4")
PREVOUT_TS = 1_690_000_000   # 22.07.2023 — beim Absender
EMPFANG_TS = 1_700_000_000   # 14.11.2023 — im Wallet angekommen
HOP_TS = 1_710_000_000       # 09.03.2024 — interner Übertrag
EIGENE = {BIP84_RECEIVE_0, BIP84_CHANGE_0}


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


def _externe_blaetter(knoten: dict) -> list[dict]:
    treffer = []
    if knoten.get("type") == "external":
        treffer.append(knoten)
    for kind in knoten.get("children") or []:
        treffer.extend(_externe_blaetter(kind))
    return treffer


class Basis(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.imm = Path(self._tmp.name) / "immutable_cache"
        self.imm.mkdir()
        self.ergebnis = trace_utxo(
            make_get_tx(_kette()), TXID_HOP, 0, EIGENE,
            immutable_cache_dir=self.imm,
        )

    def utxo(self):
        return {
            "txid": TXID_HOP,
            "vout": 0,
            "address": BIP84_CHANGE_0,
            "value": 59_000_000,
            "status": {"block_time": HOP_TS, "confirmed": True},
        }


class TestEmpfangszeit(Basis):

    def test_ingress_ist_der_empfang_nicht_der_prevout(self):
        ingress = xpub_cache.load_utxo_ingress_cache(TXID_HOP, 0, self.imm)
        self.assertEqual(ingress["external_time_ts"], EMPFANG_TS)

    def test_blatt_traegt_empfang_und_zeigt_den_prevout(self):
        blaetter = []
        for kind in self.ergebnis["children"]:
            blaetter.extend(_externe_blaetter(kind))
        self.assertEqual(len(blaetter), 1)
        blatt = blaetter[0]
        self.assertEqual(blatt["block_time"], EMPFANG_TS)
        self.assertEqual(blatt["funding_txid"], TXID_WALLET_IN)
        self.assertEqual(blatt["prevout_time_ts"], PREVOUT_TS)

    def test_steuerjahr_datiert_auf_den_empfang(self):
        aus = tax.auswerten(
            [self.utxo()], 2026, immutable_cache_dir=self.imm,
        )
        eintrag = aus["eintraege"][0]
        self.assertEqual(eintrag["grundlage"], tax.GRUNDLAGE_HERKUNFT)
        self.assertEqual(eintrag["datum"], "14.11.2023")

    def test_haltefrist_beginnt_mit_dem_empfang(self):
        """
        Bezug 01.08.2024 (laufendes Jahr): Seit dem Prevout wäre mehr als ein
        Jahr um, seit dem Empfang nicht. Beide Modi sehen dasselbe.
        """
        for modus in ("juengste", "aelteste"):
            with self.subTest(anschaffung=modus):
                aus = tax.auswerten(
                    [self.utxo()], 2024,
                    anschaffung=modus,
                    immutable_cache_dir=self.imm,
                    jetzt=datetime(2024, 8, 1, 12, 0),
                )
                eintrag = aus["eintraege"][0]
                self.assertFalse(eintrag["erfuellt"])
                self.assertEqual(eintrag["sats_gruen"], 0)
                self.assertEqual(
                    eintrag["sats_gruen"] + eintrag["sats_orange"],
                    59_000_000,
                )

    def test_nach_einem_jahr_ab_empfang_erfuellt(self):
        aus = tax.auswerten(
            [self.utxo()], 2024,
            immutable_cache_dir=self.imm,
            jetzt=datetime(2024, 11, 20, 12, 0),
        )
        eintrag = aus["eintraege"][0]
        self.assertTrue(eintrag["erfuellt"])
        self.assertEqual(eintrag["sats_gruen"], 59_000_000)


if __name__ == "__main__":
    unittest.main()
