"""Ökonomische P2P-Stockfehler: kein Bruteforce, kein Doppel-Download."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.bip158_scan import (
    _lade_cfilter_chunk,
    _zusammenhaengende_bereiche,
    plane_filter_passes,
)
from core.bip158_wallet import (
    block_bytes_hint,
    clear_p2p_block_cache,
    merke_block_bytes,
)
from core.p2p import HeaderChain, header_hash


class TestZusammenhaengendeBereiche(unittest.TestCase):
    def test_luecken_werden_intervalle(self):
        self.assertEqual(
            _zusammenhaengende_bereiche([5, 6, 7, 10, 20, 21]),
            [(5, 7), (10, 10), (20, 21)],
        )

    def test_leer(self):
        self.assertEqual(_zusammenhaengende_bereiche([]), [])


class TestTurboKeinLookaheadDurchHistorie(unittest.TestCase):
    def test_erstscan_historie_nur_gap(self):
        alle = {bytes([i]) for i in range(1, 80)}
        gap = {bytes([i]) for i in range(1, 5)}
        passe = plane_filter_passes(
            481_824, 900_000, alle, set(), gap_scripts=gap,
        )
        histo = [p for p in passe if p[0] == "historie"][0]
        self.assertEqual(histo[3], frozenset(gap))
        self.assertLess(len(histo[3]), len(alle))


class TestCfilterNurFehlendeSpannen(unittest.TestCase):
    def test_eine_luecke_holt_nicht_den_ganzen_chunk(self):
        hoehen = list(range(100, 110))
        bhash = {h: bytes([h]) + b"\x00" * 31 for h in hoehen}
        blob = b"\x01\x02"

        class FakePeer:
            def __init__(self):
                self.calls = []

            def fetch_cfilters(self, start, stop, expect):
                self.calls.append((start, expect))
                return [(bhash[start + i], blob) for i in range(expect)]

            def fetch_block(self, block_hash):
                raise AssertionError("kein Match")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from core.cfilter_cache import speichere_cfilter_blob

            for h in hoehen:
                if h == 105:
                    continue
                speichere_cfilter_blob(root, h, bhash[h], blob)
            peer = FakePeer()
            stats = {"geholt": 0, "gecacht": 0}
            with patch("core.bip158_scan._CoreBasicFilterMatcher") as matcher:
                matcher.return_value.match_any.return_value = False
                _lade_cfilter_chunk(
                    peer, 100, 109, bhash[109],
                    frozenset({b"\x01"}),
                    hash_at=lambda h: bhash[h],
                    cache_dir=root,
                    stats=stats,
                )
        self.assertEqual(peer.calls, [(105, 1)])
        self.assertEqual(stats["geholt"], 1)
        self.assertEqual(stats["gecacht"], 9)


class TestBlockSessionCache(unittest.TestCase):
    def setUp(self):
        clear_p2p_block_cache()

    def tearDown(self):
        clear_p2p_block_cache()

    def test_zweiter_abruf_ohne_peer(self):
        hsh = b"\x11" * 32
        roh = b"\x00" * 80
        merke_block_bytes(hsh, roh)
        self.assertEqual(block_bytes_hint(hsh), roh)

        client = MagicMock()
        client.start_height = 1
        client.cache_dir = None
        scanner = MagicMock()
        scanner._header_path = None
        client.scanner = scanner
        chain = MagicMock()
        chain.tip_height.return_value = 10
        chain.hash_at.return_value = hsh

        parsed_tx = MagicMock()
        parsed_tx.txid.return_value = bytes.fromhex("ab" * 32)
        parsed_tx.vin = []
        parsed_tx.vout = []

        with patch("core.p2p.HeaderChain", return_value=chain), \
             patch(
                 "core.bip158_wallet.parse_raw_block",
                 return_value=(b"\x00" * 80, [parsed_tx]),
             ), \
             patch("core.bip158_wallet._header_unixzeit", return_value=1), \
             patch(
                 "core.bip158_wallet._embit_tx_to_dict",
                 return_value={
                     "txid": "ab" * 32,
                     "vin": [],
                     "vout": [],
                     "status": {"block_height": 10, "block_time": 1},
                 },
             ):
            from core.bip158_wallet import fetch_tx_from_block_p2p

            out = fetch_tx_from_block_p2p(client, "ab" * 32, 10)
        scanner._ensure_peer.assert_not_called()
        self.assertEqual(out["txid"], "ab" * 32)


class TestHeaderOverlapIndex(unittest.TestCase):
    def _kette_aus(self, anzahl: int) -> HeaderChain:
        chain = HeaderChain(start_height=0)
        tip = chain.hash_at(chain.tip_height())
        for i in range(anzahl):
            nxt = bytes([i + 1, 0, 0, 0]) + tip + b"\x00" * 44
            chain.append(nxt)
            tip = header_hash(nxt)
        return chain

    def test_overlap_baut_index_nicht_jedes_mal_linear(self):
        chain = self._kette_aus(80)
        chain.hoehe_fuer_hash(chain.hash_at(80), max_tiefe=None)
        self.assertEqual(len(chain._hash_nach_hoehe), 81)
        batch = [chain.header_at(h) for h in range(60, 81)]
        chain.wende_header_batch_an(batch)
        self.assertEqual(chain.tip_height(), 80)
        self.assertEqual(chain._hash_nach_hoehe[chain.hash_at(80)], 80)


if __name__ == "__main__":
    unittest.main()
