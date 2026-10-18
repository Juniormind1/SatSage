"""Bestand am Stichtag gegen die Kette — Lab-Prüfung ohne Node."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "lab" / "regtest" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stichtag_chain import (  # noqa: E402
    abgeschlossene_jahre,
    als_verlauf,
    bestand_soll,
    chain_wahrheit,
    pruefe_stichtage,
)

T1 = int(datetime(2023, 3, 1, 12).timestamp())
T2 = int(datetime(2025, 2, 10, 12).timestamp())
T3 = int(datetime(2025, 8, 1, 12).timestamp())
EIGEN = {"bcrt1qa", "bcrt1qb", "bcrt1qc"}


def _tx(txid, vin, vout):
    return {"txid": txid, "vin": vin, "vout": vout}


def _vin(txid, n, adresse):
    return {"txid": txid, "vout": n,
            "prevout": {"scriptPubKey": {"address": adresse}}}


def _vout(n, adresse, btc):
    return {"n": n, "value": btc, "scriptPubKey": {"address": adresse}}


A, B, C = "a" * 64, "b" * 64, "c" * 64
BLOECKE = [
    # 2023: fremd → A
    {"time": T1, "tx": [_tx(A, [_vin("f" * 64, 0, "bcrt1qfremd")],
                            [_vout(0, "bcrt1qa", 1.0)])]},
    # 2025: A → B (Umschichtung, Gebühr geht ab)
    {"time": T2, "tx": [_tx(B, [_vin(A, 0, "bcrt1qa")],
                            [_vout(0, "bcrt1qb", 0.99)])]},
    # 2025: fremd → C, zusammen mit B
    {"time": T3, "tx": [_tx(C, [_vin("e" * 64, 1, "bcrt1qfremd"),
                                _vin(B, 0, "bcrt1qb")],
                            [_vout(1, "bcrt1qc", 1.5)])]},
]


def _rpc(name, *args):
    if name == "getblockcount":
        return len(BLOECKE) - 1
    if name == "getblockhash":
        return f"h{args[0]}"
    if name == "getblock":
        return BLOECKE[int(args[0][1:])]
    raise AssertionError(name)


class TestChainWahrheit(unittest.TestCase):

    def setUp(self):
        self.w = chain_wahrheit(_rpc, EIGEN)

    def test_eigene_outputs_mit_ausgabe(self):
        self.assertEqual(sorted(self.w), [f"{A}:0", f"{B}:0", f"{C}:1"])
        self.assertEqual(self.w[f"{A}:0"]["spent_txid"], B)
        self.assertEqual(self.w[f"{A}:0"]["spent_time"], T2)
        self.assertIsNone(self.w[f"{C}:1"]["spent_txid"])
        self.assertEqual(self.w[f"{B}:0"]["value"], 99_000_000)

    def test_anschaffung_ist_empfang_von_aussen(self):
        # Interner Hop erbt den Empfang von 2023.
        self.assertEqual(self.w[f"{B}:0"]["juengste"], T1)
        # Gemischt: jüngster Empfang ist die Tx mit dem fremden Eingang.
        self.assertEqual(self.w[f"{C}:1"]["juengste"], T3)
        self.assertEqual(self.w[f"{C}:1"]["aelteste"], T1)

    def test_bestand_nach_entstehung(self):
        self.assertEqual(sorted(bestand_soll(self.w, 2024)), [f"{A}:0"])
        self.assertEqual(sorted(bestand_soll(self.w, 2025)), [f"{C}:1"])
        self.assertEqual(
            abgeschlossene_jahre(self.w, datetime(2026, 5, 1)), [2023, 2025],
        )

    def test_verlauf_form(self):
        zeilen = {z["txid"]: z for z in als_verlauf(self.w)}
        self.assertTrue(zeilen[A]["spent"])
        self.assertEqual(zeilen[A]["spent_time_ts"], T2)
        self.assertEqual(zeilen[C]["status"]["block_time"], T3)


class TestPruefeStichtage(unittest.TestCase):
    """SatSage gegen die Kette — mit Herkunft, die älter ist als der Output."""

    def test_alte_herkunft_zaehlt_nicht_im_vorjahr(self):
        from core import xpub_cache

        w = chain_wahrheit(_rpc, EIGEN)
        with tempfile.TemporaryDirectory() as tmp:
            imm = Path(tmp)
            for key in (f"{B}:0", f"{C}:1"):
                txid, vout = key.split(":")
                xpub_cache.save_utxo_ingress_cache(
                    txid, int(vout),
                    {"youngest_time_ts": w[key]["juengste"],
                     "external_time_ts": w[key]["juengste"]},
                    imm,
                )
            fehler, zeilen = pruefe_stichtage(
                w, imm=imm, jahre=[2023, 2024, 2025],
            )
        self.assertEqual(fehler, [])
        self.assertEqual(
            [(z["jahr"], z["ist_count"], z["ist_sats"]) for z in zeilen],
            [(2023, 1, 100_000_000), (2024, 1, 100_000_000),
             (2025, 1, 150_000_000)],
        )

    def test_anschaffung_vor_dem_empfang_faellt_auf(self):
        """Prevout-Datum (vor dem Empfang von außen) ist ein Fehler."""
        from core import xpub_cache

        w = chain_wahrheit(_rpc, EIGEN)
        zu_frueh = T1 - 30 * 86_400   # fremder Prevout lag schon länger
        with tempfile.TemporaryDirectory() as tmp:
            imm = Path(tmp)
            xpub_cache.save_utxo_ingress_cache(
                A, 0,
                {"youngest_time_ts": zu_frueh, "external_time_ts": zu_frueh},
                imm,
            )
            fehler, zeilen = pruefe_stichtage(w, imm=imm, jahre=[2024])
        self.assertEqual(zeilen[0]["anschaffung_geprueft"], 1)
        self.assertEqual(zeilen[0]["anschaffung_falsch"], 1)
        self.assertTrue(any("Anschaffung 31.12.2024" in f for f in fehler))

    def test_anschaffung_am_empfang_ist_richtig(self):
        w = chain_wahrheit(_rpc, EIGEN)
        from core import xpub_cache

        with tempfile.TemporaryDirectory() as tmp:
            imm = Path(tmp)
            xpub_cache.save_utxo_ingress_cache(
                A, 0, {"youngest_time_ts": T1, "external_time_ts": T1}, imm,
            )
            fehler, zeilen = pruefe_stichtage(w, imm=imm, jahre=[2024])
        self.assertEqual(fehler, [])
        self.assertEqual(zeilen[0]["anschaffung_geprueft"], 1)
        self.assertEqual(zeilen[0]["anschaffung_falsch"], 0)

if __name__ == "__main__":
    unittest.main()
