"""
Bündel-Fix: ungeklärte Eingänge einer Tx zählen als Zufluss zur Blockzeit
dieser Tx (Obergrenze, nie zu alt) — statt „Untergrenze“ mit dem jüngsten
*bekannten* Zufluss, der Jahre zu früh liegen konnte.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core import herkunftsnetz, selbstanzeige, tax, utxo_ingress_report, xpub_cache
from core.trace import trace_utxo
from tests.fixtures import (
    BIP84_CHANGE_0, BIP84_RECEIVE_0, BIP84_RECEIVE_1, EXTERN_A, EXTERN_B,
    core_tx, core_vin, core_vout, make_get_tx, txid,
)

EIGENE = {BIP84_RECEIVE_0, BIP84_CHANGE_0, BIP84_RECEIVE_1}
T_EXT_ALT = 1_550_000_000   # 2019
T_W = 1_580_000_000         # 2020: alter eigener Eingang
T_R = 1_700_000_000         # 14.11.2023: Sammel-Tx
JETZT = datetime(2024, 6, 1, 12)


def _kette(fall: str) -> dict:
    """Sammel-Tx d0 mit 25 Eingängen (über dem Auflöse-Limit 20)."""
    c = {}
    c[txid("e0")] = core_tx(txid("e0"), [core_vin(txid("00"), 0)],
                            [core_vout(0, EXTERN_A, 1.0)], blocktime=T_EXT_ALT)
    c[txid("a1")] = core_tx(txid("a1"), [core_vin(txid("e0"), 0)],
                            [core_vout(0, BIP84_RECEIVE_1, 0.9)], blocktime=T_W)
    fremde = []
    for i in range(24):
        f = txid(f"f{i:02x}")
        c[f] = core_tx(f, [core_vin(txid("01"), i)],
                       [core_vout(0, EXTERN_B, 0.01)], blocktime=T_EXT_ALT + i)
        fremde.append(core_vin(f, 0))
    if fall == "eigen_zuerst_dann_fremd":
        vins = [core_vin(txid("a1"), 0)] + fremde
    elif fall == "eigen_zuerst_dann_eigen":
        eig = []
        for i in range(24):
            e = txid(f"c{i:02x}")
            c[e] = core_tx(e, [core_vin(txid("e0"), 0)],
                           [core_vout(0, BIP84_CHANGE_0, 0.01)], blocktime=T_W + i)
            eig.append(core_vin(e, 0))
        vins = [core_vin(txid("a1"), 0)] + eig
    else:  # fremd_zuerst
        vins = fremde[:1] + [core_vin(txid("a1"), 0)] + fremde[1:]
    c[txid("d0")] = core_tx(txid("d0"), vins,
                            [core_vout(0, BIP84_RECEIVE_0, 1.0)], blocktime=T_R)
    return c


def _utxo(ts=T_R):
    return {"txid": txid("d0"), "vout": 0, "address": BIP84_RECEIVE_0,
            "value": 100_000_000, "status": {"block_time": ts, "confirmed": True}}


class _Lauf(unittest.TestCase):
    def _trace(self, get_tx):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.imm = Path(self._tmp.name)
        trace_utxo(get_tx, txid("d0"), 0, EIGENE, immutable_cache_dir=self.imm)
        return xpub_cache.load_utxo_ingress_cache(txid("d0"), 0, self.imm) or {}

    def _steuer(self, **kw):
        return tax.auswerten([_utxo()], 2024, immutable_cache_dir=self.imm,
                             jetzt=JETZT, **kw)


class TestSammelTx(_Lauf):

    def test_eigen_zuerst_dann_fremd_datum_ist_sammel_tx(self):
        ing = self._trace(make_get_tx(_kette("eigen_zuerst_dann_fremd")))
        self.assertEqual(ing["external_time_ts"], T_R)
        self.assertFalse(ing["external_untergrenze"])
        self.assertTrue(ing["external_buendel"])
        self.assertTrue(ing["external_buendel_obergrenze"])

    def test_eigen_zuerst_dann_eigen_vorsichtig(self):
        # Wahr wäre 2020; die Obergrenze T_R ist zu jung, aber nie zu alt.
        ing = self._trace(make_get_tx(_kette("eigen_zuerst_dann_eigen")))
        self.assertEqual(ing["external_time_ts"], T_R)
        self.assertTrue(ing["external_buendel_obergrenze"])

    def test_fremd_zuerst_exakt(self):
        ing = self._trace(make_get_tx(_kette("fremd_zuerst")))
        self.assertEqual(ing["external_time_ts"], T_R)
        self.assertFalse(ing["external_untergrenze"])
        # Ein exakter Zufluss trägt dieselbe Zeit: keine Obergrenze.
        self.assertFalse(ing["external_buendel_obergrenze"])
        self.assertTrue(ing["external_buendel"])

    def test_steuer_eigen_zuerst_nicht_erfuellt(self):
        """Stichtag 06/2024: Frist ab 14.11.2023 offen, kein Los grün."""
        self._trace(make_get_tx(_kette("eigen_zuerst_dann_fremd")))
        e = self._steuer()["eintraege"][0]
        self.assertEqual(e["datum"], datetime.fromtimestamp(T_R).strftime("%d.%m.%Y"))
        self.assertFalse(e["erfuellt"])
        self.assertFalse(e["untergrenze"])
        self.assertTrue(e["buendel_obergrenze"])
        self.assertFalse(e["sats_gruen"])
        self.assertIn("Bündel, vorsichtig", e["grundlage_label"])

    def test_steuer_hinweis_und_kennzahl(self):
        self._trace(make_get_tx(_kette("eigen_zuerst_dann_fremd")))
        erg = self._steuer()
        self.assertEqual(erg["kennzahlen"]["buendel_count"], 1)
        self.assertEqual(erg["kennzahlen"]["untergrenze_count"], 0)

    def test_offensiv_bleibt_bei_juengster(self):
        self._trace(make_get_tx(_kette("eigen_zuerst_dann_fremd")))
        e = self._steuer(anschaffung=tax.ANSCHAFFUNG_AELTESTE)["eintraege"][0]
        self.assertEqual(int(e["time_ts"]), T_R)
        self.assertFalse(e["erfuellt"])
        self.assertTrue(e["offensiv_fallback"])

    def test_selbstanzeige_label(self):
        self._trace(make_get_tx(_kette("eigen_zuerst_dann_fremd")))
        zeit, grundlage, ug, _addr, buendel = selbstanzeige._anschaffung_los(
            _utxo(), self.imm,
        )
        self.assertEqual(int(zeit.timestamp()), T_R)
        self.assertFalse(ug)
        self.assertTrue(buendel)
        self.assertEqual(
            tax._grundlage_label(grundlage, ug, buendel=buendel),
            "Herkunft verfolgt (Bündel, vorsichtig)",
        )


class TestFehlenderVorgaenger(_Lauf):
    """Eigener Eingang, dessen Erzeuger-Tx nicht ladbar ist (error)."""

    def _get_tx(self):
        c = {}
        c[txid("e0")] = core_tx(txid("e0"), [core_vin(txid("00"), 0)],
                                [core_vout(0, EXTERN_A, 1.0)], blocktime=T_EXT_ALT)
        c[txid("a1")] = core_tx(txid("a1"), [core_vin(txid("e0"), 0)],
                                [core_vout(0, BIP84_RECEIVE_1, 0.9)], blocktime=T_W)
        c[txid("d0")] = core_tx(
            txid("d0"), [core_vin(txid("a1"), 0), core_vin(txid("99"), 0)],
            [core_vout(0, BIP84_RECEIVE_0, 1.0)], blocktime=T_R,
        )
        basis = make_get_tx(c)

        def get_tx(t):
            if t == txid("99"):
                raise RuntimeError("nicht verfügbar")
            return basis(t)
        return get_tx

    def test_datum_ist_tx_mit_luecke(self):
        ing = self._trace(self._get_tx())
        self.assertEqual(ing["external_time_ts"], T_R)
        self.assertTrue(ing["external_buendel_obergrenze"])

    def test_lose_nicht_gruen(self):
        self._trace(self._get_tx())
        e = self._steuer()["eintraege"][0]
        self.assertEqual(int(e["time_ts"]), T_R)
        self.assertFalse(e["erfuellt"])
        self.assertFalse(e["sats_gruen"])


class TestExtrema(unittest.TestCase):
    """Reine Logik an Hand-Bäumen."""

    def test_unbestaetigte_tx_bleibt_untergrenze(self):
        baum = {"type": "utxo", "time_ts": None, "sources": [
            {"type": "external", "time_ts": T_W, "amount_sats": 5,
             "address": EXTERN_A},
            {"type": "external_unresolved", "input_count": 30},
        ]}
        ex = utxo_ingress_report._external_ingress_extrema(baum)
        self.assertTrue(ex["untergrenze"])
        self.assertEqual(ex["youngest"]["time_ts"], T_W)
        self.assertIsNone(utxo_ingress_report.gesicherte_anschaffung(baum))

    def test_bestaetigte_sammel_tx_obergrenze(self):
        baum = {"type": "utxo", "time_ts": T_R, "sources": [
            {"type": "external", "time_ts": T_W, "amount_sats": 5,
             "address": EXTERN_A},
            {"type": "external_unresolved", "input_count": 30},
        ]}
        ex = utxo_ingress_report._external_ingress_extrema(baum)
        self.assertFalse(ex["untergrenze"])
        self.assertTrue(ex["buendel_obergrenze"])
        self.assertEqual(ex["youngest"]["time_ts"], T_R)
        # Offensiv: die älteste bleibt der exakte Zufluss.
        self.assertEqual(ex["oldest"]["time_ts"], T_W)
        self.assertIsNone(utxo_ingress_report.gesicherte_anschaffung(baum))

    def test_ui_blatt_traegt_eingangszeit(self):
        """Stempel aus dem UI-Baum: Blatt ohne Eltern, Zeit am Blatt."""
        baum = {"type": "utxo", "sources": [
            {"type": "external_unresolved", "eingang_time_ts": T_R},
            {"type": "external", "time_ts": T_W, "amount_sats": 1,
             "address": EXTERN_A},
        ]}
        ex = utxo_ingress_report._external_ingress_extrema(baum)
        self.assertEqual(ex["youngest"]["time_ts"], T_R)
        self.assertFalse(ex["untergrenze"])


class TestHerkunftsnetzBuendel(unittest.TestCase):

    def _buendel(self, kinder, eltern):
        erfasst = {}

        class _S:
            def y(self, _v):
                return 0.0

        herkunftsnetz._buendel(
            kinder, "fokus", 0.0, 1, 100,
            neu=lambda k, d, _a: erfasst.setdefault(k, d),
            kante=lambda *a: None,
            zeitfelder=lambda z: {"zeit": z},
            skala=_S(), block_zeit=None, eltern=eltern,
        )
        return erfasst["buendel:fokus"]["zeit"]

    def test_unaufgeloest_nimmt_tx_zeit(self):
        kinder = [
            {"type": "internal", "time_ts": T_W, "amount_sats": 10,
             "wallet": "w"},
            {"type": "external_unresolved", "input_count": 24},
        ]
        zeit = self._buendel(kinder, {"time_ts": T_R})
        self.assertEqual(int(zeit.timestamp()), T_R)

    def test_coinjoin_buendel_unveraendert(self):
        kinder = [
            {"type": "internal", "time_ts": T_W, "amount_sats": 10,
             "wallet": "w"},
            {"type": "external", "time_ts": T_W + 5, "amount_sats": 10},
        ]
        zeit = self._buendel(kinder, {"time_ts": T_R, "tx_class": "whirlpool"})
        self.assertEqual(int(zeit.timestamp()), T_W + 5)


if __name__ == "__main__":
    unittest.main()
