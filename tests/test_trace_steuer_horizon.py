"""Steuer-Horizont vs. voller Trace bis extern/Coinbase."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import analyze
import main
from core import tax, trace_cache
from core.trace import trace_utxo
from tests.fixtures import (
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    EXTERN_A,
    EXTERN_B,
    TXID_EXTERN,
    TXID_WALLET_IN,
    core_tx,
    core_vin,
    core_vout,
    make_get_tx,
    simple_chain,
    txid,
)

EIGENE = {BIP84_RECEIVE_0, BIP84_CHANGE_0}

# Längere Kette: Extern → alt intern → junges Wallet-UTXO
TXID_ALT = txid("a0")
TXID_JUNG = txid("a2")
# Alt-Hop: 2020 — klar vor 1-Jahres-Haltefrist eines Bezugs 2025.
TS_ALT = 1_577_836_800  # 2020-01-01
TS_JUNG = 1_735_689_600  # 2025-01-01
TS_EXTERN = 1_514_764_800  # 2018-01-01


def lange_kette() -> dict[str, dict]:
    """
    Extern (2018) → ALT intern (2020, receive) → JUNG (2025, change) als UTXO.
    """
    t_ext = core_tx(
        TXID_EXTERN,
        [core_vin(txid("c0"), 0)],
        [core_vout(0, EXTERN_A, 1.0)],
        blocktime=TS_EXTERN,
    )
    t_alt = core_tx(
        TXID_ALT,
        [core_vin(TXID_EXTERN, 0)],
        [core_vout(0, BIP84_RECEIVE_0, 0.9)],
        blocktime=TS_ALT,
    )
    t_jung = core_tx(
        TXID_JUNG,
        [core_vin(TXID_ALT, 0)],
        [core_vout(0, BIP84_CHANGE_0, 0.85), core_vout(1, EXTERN_B, 0.04)],
        blocktime=TS_JUNG,
    )
    return {t["txid"]: t for t in (t_ext, t_alt, t_jung)}


class TestStopBeforeTs(unittest.TestCase):
    def test_haltefrist_anfang_ohne_stichtag(self):
        # Bezug 31.12.2025, 1 Jahr → Horizont ~31.12.2024
        ts = tax.stop_before_ts_fuer_steuer(2025, 1, None)
        self.assertIsNotNone(ts)
        # 2020-Hop muss darunter liegen, 2025-Hop darüber
        self.assertLess(TS_ALT, ts)
        self.assertGreater(TS_JUNG, ts)

    def test_ohne_frist_und_stichtag_kein_horizont(self):
        self.assertIsNone(tax.stop_before_ts_fuer_steuer(2025, 0, None))


class TestSteuerHorizonTrace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name) / "utxo_cache"
        self.cache.mkdir()
        self.imm = main.resolve_immutable_cache_dir(utxo_cache_dir=self.cache)
        self.chain = lange_kette()
        self.get_tx = make_get_tx(self.chain)
        self.counter: list[str] = []
        self.get_tx_count = make_get_tx(self.chain, counter=self.counter)

    def test_steuer_stoppt_vor_alt_hop(self):
        stop = tax.stop_before_ts_fuer_steuer(2025, 1, None)
        node = analyze.trace_utxo_origin(
            self.get_tx, TXID_JUNG, 0, EIGENE, stop_before_ts=stop,
        )
        self.assertIsNotNone(node)
        # Junges Root wird expandiert; ALT-Hop ist Horizont (≤ stop).
        self.assertFalse(node.get("tax_horizon"))
        quellen = node.get("sources") or []
        self.assertTrue(quellen)
        intern = next(s for s in quellen if s.get("type") == "internal")
        kind = intern.get("trace") or {}
        self.assertTrue(kind.get("tax_horizon"), kind)
        # Mit Zähler: nur JUNG + ALT — Extern wird nicht geladen.
        counter: list[str] = []
        analyze.trace_utxo_origin(
            make_get_tx(self.chain, counter=counter),
            TXID_JUNG, 0, EIGENE, stop_before_ts=stop,
        )
        self.assertIn(TXID_JUNG, counter)
        self.assertIn(TXID_ALT, counter)
        self.assertNotIn(TXID_EXTERN, counter)

    def test_voll_geht_bis_extern(self):
        counter: list[str] = []
        node = analyze.trace_utxo_origin(
            make_get_tx(self.chain, counter=counter),
            TXID_JUNG, 0, EIGENE, stop_before_ts=None,
        )
        self.assertIn(TXID_EXTERN, counter)
        self.assertFalse(analyze._hat_tax_horizon(node))

    def test_resume_baut_auf_steuer_teilbaum(self):
        stop = tax.stop_before_ts_fuer_steuer(2025, 1, None)
        # 1) Steuer-Lauf speichert Teilbaum
        ergebnis = trace_utxo(
            self.get_tx, TXID_JUNG, 0, EIGENE,
            cache_dir=self.cache,
            stop_before_ts=stop,
        )
        self.assertTrue(ergebnis.get("found"))
        self.assertTrue(ergebnis.get("steuer_ausreichend"))
        self.assertFalse(ergebnis.get("verfolgt_vollstaendig"))
        origin = ergebnis.get("origin_tree")
        self.assertTrue(analyze._hat_tax_horizon(origin))

        kopf = trace_cache.kopf(TXID_JUNG, 0, self.imm, EIGENE)
        self.assertTrue(kopf.get("steuer_ausreichend"))
        self.assertFalse(kopf.get("vollstaendig"))

        # 2) Voll-Lauf mit Resume — darf nicht alles neu von JUNG starten
        counter: list[str] = []
        voll = trace_utxo(
            make_get_tx(self.chain, counter=counter),
            TXID_JUNG, 0, EIGENE,
            cache_dir=self.cache,
            stop_before_ts=None,
            resume_origin=origin,
        )
        self.assertTrue(voll.get("verfolgt_vollstaendig"))
        self.assertFalse(analyze._hat_tax_horizon(voll.get("origin_tree")))
        # Resume startet am Horizont (ALT), lädt ALT erneut + EXTERN
        self.assertIn(TXID_EXTERN, counter)
        # JUNG muss nicht nochmal geladen werden (Resume am ALT-Blatt)
        # (vertiefe lädt ALT und darunter EXTERN; JUNG bleibt im Teilbaum)
        self.assertNotIn(TXID_JUNG, counter)


class TestSimpleChainUnveraendert(unittest.TestCase):
    """Kurze Kette: Steuer-Stop ändert nichts, weil Extern vor Root liegt."""

    def test_simple_bleibt_voll(self):
        stop = tax.stop_before_ts_fuer_steuer(2025, 1, None)
        # Root TXID_WALLET_IN blocktime 1_700_000_000 ~ 2023-11 — vor 2024-12
        # → Root selbst kann Horizont sein wenn ≤ stop
        node = analyze.trace_utxo_origin(
            make_get_tx(simple_chain()), TXID_WALLET_IN, 0, EIGENE,
            stop_before_ts=stop,
        )
        # 1.7e9 < stop (~2024-12) → tax_horizon auf Root
        if node.get("time_ts") and int(node["time_ts"]) <= stop:
            self.assertTrue(node.get("tax_horizon"))
        else:
            self.assertFalse(analyze._hat_tax_horizon(node) and not any(
                s.get("type") == "external" for s in (node.get("sources") or [])
            ))


if __name__ == "__main__":
    unittest.main()
