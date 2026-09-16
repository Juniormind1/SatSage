"""Hop-Semantik der Sanktions-Vorgeschichte (Fake-Tx-Graph)."""
from __future__ import annotations

import os
import unittest

from analyze import scan_external_sanction_hops
from tests.fixtures import (
    BIP84_RECEIVE_0,
    EXTERN_A,
    core_tx,
    core_vin,
    core_vout,
    make_get_tx,
    txid,
)

SANC = "bc1qsancxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx01"
MID = "bc1qmidxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx02"
OWN = BIP84_RECEIVE_0


def linear_chain(hops: int, *, listed_start: str = SANC) -> tuple[dict, str, int]:
    """
    listed_start → mid* → OWN.

    Rückgabe: (chain_dict, wallet_in_txid, wallet_vout).
    Scan-Hop N trifft listed_start bei max_hops >= N.
    """
    if hops < 1:
        raise ValueError("hops >= 1")
    chain: dict = {}
    # Genesis: listed_start wird „von Coinbase“ gefüttert (nicht gescannt als Hit-Quelle nötig)
    # Nur Hex-Marker — main._normalize_txid / Cache-Pfade verlangen das.
    funding = txid("aa")
    chain[funding] = core_tx(
        funding,
        [{"coinbase": "00", "sequence": 0}],
        [core_vout(0, listed_start, 1.0)],
    )
    prev_txid, prev_vout = funding, 0
    addrs = [listed_start] + [f"{MID}{i:02d}"[:42].ljust(42, "x") for i in range(hops - 1)]
    # hops-1 Intermediate-Txs + final to OWN
    for i in range(hops - 1):
        tid = txid(f"{i:02x}")
        next_addr = addrs[i + 1]
        chain[tid] = core_tx(
            tid,
            [core_vin(prev_txid, prev_vout)],
            [core_vout(0, next_addr, 0.9)],
        )
        prev_txid, prev_vout = tid, 0
    wallet_in = txid("bb")
    chain[wallet_in] = core_tx(
        wallet_in,
        [core_vin(prev_txid, prev_vout)],
        [core_vout(0, OWN, 0.8)],
    )
    return chain, wallet_in, 0


class TestSanctionHopKalibrierung(unittest.TestCase):
    def test_hop1_trifft_bei_depth_1(self):
        chain, win, vout = linear_chain(1)
        hits = scan_external_sanction_hops(
            make_get_tx(chain),
            win,
            vout,
            {OWN},
            frozenset({SANC}),
            max_hops=1,
            abort_on_hit=False,
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["hop"], 1)
        self.assertEqual(hits[0]["address"], SANC)

    def test_hop10_cutoff_bei_3(self):
        chain, win, vout = linear_chain(10)
        hits = scan_external_sanction_hops(
            make_get_tx(chain),
            win,
            vout,
            {OWN},
            frozenset({SANC}),
            max_hops=3,
            abort_on_hit=False,
        )
        self.assertEqual(hits, [])

    def test_hop10_treffer_bei_10(self):
        chain, win, vout = linear_chain(10)
        hits = scan_external_sanction_hops(
            make_get_tx(chain),
            win,
            vout,
            {OWN},
            frozenset({SANC}),
            max_hops=10,
            abort_on_hit=False,
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["hop"], 10)
        self.assertEqual(hits[0]["address"], SANC)

    def test_clean_kein_treffer(self):
        chain, win, vout = linear_chain(10, listed_start=EXTERN_A)
        hits = scan_external_sanction_hops(
            make_get_tx(chain),
            win,
            vout,
            {OWN},
            frozenset({SANC}),
            max_hops=10,
            abort_on_hit=False,
        )
        self.assertEqual(hits, [])

    def test_xpub_blind_folgt_eigenen_hops(self):
        """
        Drittperspektive: Zwischenhop auf eigener Adresse darf die Kette
        nicht abschneiden — sonst bliebe listed hinter Eigenübertrag unsichtbar.
        """
        # listed → OWN (mid) → OWN_B (UTXO)
        own_b = "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el"  # BIP84_CHANGE_0
        funding = txid("cc")
        mid = txid("dd")
        win = txid("ee")
        chain = {
            funding: core_tx(
                funding,
                [{"coinbase": "00", "sequence": 0}],
                [core_vout(0, SANC, 1.0)],
            ),
            mid: core_tx(
                mid,
                [core_vin(funding, 0)],
                [core_vout(0, OWN, 0.9)],
            ),
            win: core_tx(
                win,
                [core_vin(mid, 0)],
                [core_vout(0, own_b, 0.8)],
            ),
        }
        # Mit XPUB-Filter (alt) wäre OWN übersprungen und SANC unsichtbar.
        # xpub-blind: Hop1=OWN, Hop2=SANC.
        hits = scan_external_sanction_hops(
            make_get_tx(chain),
            win,
            0,
            {OWN, own_b},
            frozenset({SANC}),
            max_hops=2,
            abort_on_hit=False,
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["hop"], 2)
        self.assertEqual(hits[0]["address"], SANC)
        # Zu flach: noch kein Treffer
        hits_flach = scan_external_sanction_hops(
            make_get_tx(chain),
            win,
            0,
            {OWN, own_b},
            frozenset({SANC}),
            max_hops=1,
            abort_on_hit=False,
        )
        self.assertEqual(hits_flach, [])


class TestSanktionHopCap(unittest.TestCase):
    def test_default_cap_20(self):
        from core.sanctions import (
            DEFAULT_SANKTION_MAX_HOPS_CAP,
            clamp_sanktion_max_hops,
            sanktion_max_hops_cap,
        )

        os.environ.pop("SANKTION_MAX_HOPS_CAP", None)
        self.assertEqual(sanktion_max_hops_cap(), DEFAULT_SANKTION_MAX_HOPS_CAP)
        self.assertEqual(clamp_sanktion_max_hops(99), DEFAULT_SANKTION_MAX_HOPS_CAP)

    def test_lab_cap_override(self):
        from core.sanctions import clamp_sanktion_max_hops, sanktion_max_hops_cap

        os.environ["SANKTION_MAX_HOPS_CAP"] = "100"
        try:
            self.assertEqual(sanktion_max_hops_cap(), 100)
            self.assertEqual(clamp_sanktion_max_hops(99), 99)
            self.assertEqual(clamp_sanktion_max_hops(250), 100)
        finally:
            os.environ.pop("SANKTION_MAX_HOPS_CAP", None)


class TestSanctionWalkCache(unittest.TestCase):
    """Zweiter Lauf bedient den Graph aus dem Cache — get_tx wird nicht gerufen."""

    def test_zweiter_lauf_ohne_get_tx(self):
        import tempfile
        from pathlib import Path

        import analyze
        from core import trace_cache

        chain, win, vout = linear_chain(1)
        counter: list[str] = []
        get_tx = make_get_tx(chain, counter=counter)
        utxo = {"txid": win, "vout": vout, "address": OWN, "value": 80_000_000}

        with tempfile.TemporaryDirectory() as tmp:
            imm = Path(tmp) / "immutable_cache"
            imm.mkdir()
            hits1, n1, _, _cj1 = analyze.check_wallet_utxos_sanctions(
                get_tx,
                [utxo],
                {OWN},
                frozenset({SANC}),
                max_hops=3,
                abort_on_hit=False,
                immutable_cache_dir=imm,
            )
            self.assertEqual(n1, 1)
            self.assertEqual(len(hits1), 1)
            self.assertTrue(counter, "erster Lauf braucht get_tx")
            walk = trace_cache.sanction_walk_laden(win, vout, imm)
            self.assertIsNotNone(walk)
            self.assertTrue(walk["complete"])
            self.assertIn("coinjoins", walk)

            counter.clear()

            def get_tx_verboten(_txid: str):
                raise AssertionError("Cache-Hit darf get_tx nicht rufen")

            hits2, n2, _, _cj2 = analyze.check_wallet_utxos_sanctions(
                get_tx_verboten,
                [utxo],
                {OWN},
                frozenset({SANC}),
                max_hops=3,
                abort_on_hit=False,
                immutable_cache_dir=imm,
            )
            self.assertEqual(n2, 1)
            self.assertEqual(len(hits2), 1)
            self.assertEqual(hits2[0]["address"], SANC)
            self.assertEqual(counter, [])


class TestSanctionCoinJoinHinweis(unittest.TestCase):
    """CoinJoin-Form im Hop-Fenster wird hervorgehoben (kein Sanktionstreffer)."""

    def test_whirlpool_im_walk(self):
        import analyze
        from tests.fixtures import core_vin, core_vout, core_tx, make_get_tx, txid

        # Whirlpool-like 5×5 equal outs → Hop 0 der Wallet-UTXO-Tx
        peers = [
            "bc1qpeer0xxxxxxxxxxxxxxxxxxxxxxxxxxxxx0",
            "bc1qpeer1xxxxxxxxxxxxxxxxxxxxxxxxxxxxx1",
            "bc1qpeer2xxxxxxxxxxxxxxxxxxxxxxxxxxxxx2",
            "bc1qpeer3xxxxxxxxxxxxxxxxxxxxxxxxxxxxx3",
            "bc1qpeer4xxxxxxxxxxxxxxxxxxxxxxxxxxxxx4",
        ]
        cj_tid = txid("c1")
        denom = 0.01
        # Prevouts für die 5 Ins (einfache Funding-Txs)
        chain: dict = {}
        vins = []
        for i, addr in enumerate(peers):
            ft = txid(f"f{i+1:02x}")
            chain[ft] = core_tx(
                ft,
                [{"coinbase": "00", "sequence": 0}],
                [core_vout(0, addr, denom)],
            )
            vins.append(core_vin(ft, 0))
        outs = [core_vout(i, peers[i], denom) for i in range(5)]
        chain[cj_tid] = core_tx(cj_tid, vins, outs, blocktime=1_700_000_000)

        utxo = {
            "txid": cj_tid,
            "vout": 0,
            "address": peers[0],
            "value": int(denom * 1e8),
        }
        # Dummy-Liste ohne Treffer (Adresse nicht gelistet)
        hits, n, abort, coinjoins = analyze.check_wallet_utxos_sanctions(
            make_get_tx(chain),
            [utxo],
            set(peers),
            frozenset({SANC}),
            max_hops=2,
            abort_on_hit=False,
        )
        self.assertEqual(n, 1)
        self.assertEqual(hits, [])
        self.assertIsNone(abort)
        self.assertTrue(coinjoins, "Whirlpool-Form sollte erkannt werden")
        self.assertEqual(coinjoins[0]["kind"], "whirlpool")
        self.assertEqual(coinjoins[0]["hop"], 0)
        self.assertIn("Whirlpool", coinjoins[0].get("label") or "")


if __name__ == "__main__":
    unittest.main()
