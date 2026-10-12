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


def _test_xpub() -> str:
    """Öffentlicher Testschlüssel aus einem festen kurzen Seed. Kein Wallet."""
    from embit.bip32 import HDKey

    return HDKey.from_seed(bytes(range(16))).to_public().to_string()


def _spk(xpub: str, change: int, index: int) -> bytes:
    from embit.bip32 import HDKey

    from core.bip158_wallet import _encoders_for_xpub

    child = HDKey.from_string(xpub).derive([change, index])
    return bytes(_encoders_for_xpub(xpub)[0](child.key).data)


class TestHistoriePraefix(unittest.TestCase):
    def test_hoechster_treffer_fuellt_die_luecke(self):
        from core.bip158_wallet import scripts_mit_gap_um_treffer

        xpub = _test_xpub()
        out = scripts_mit_gap_um_treffer(
            xpub, {_spk(xpub, 1, 119)}, gap_limit=20, max_index=200,
        )
        self.assertIn(_spk(xpub, 1, 50), out)
        self.assertIn(_spk(xpub, 1, 119), out)
        self.assertIn(_spk(xpub, 1, 139), out)
        self.assertNotIn(_spk(xpub, 1, 140), out)
        self.assertIn(_spk(xpub, 0, 19), out)
        self.assertNotIn(_spk(xpub, 0, 20), out)

    def test_ohne_treffer_nur_die_ersten_gap_indizes(self):
        from core.bip158_wallet import scripts_mit_gap_um_treffer

        xpub = _test_xpub()
        out = scripts_mit_gap_um_treffer(
            xpub, set(), gap_limit=20, max_index=200,
        )
        self.assertIn(_spk(xpub, 0, 0), out)
        self.assertIn(_spk(xpub, 1, 19), out)
        self.assertNotIn(_spk(xpub, 1, 20), out)
        self.assertNotIn(_spk(xpub, 0, 20), out)


class TestBestandGleicherBlock(unittest.TestCase):
    def test_ausgabe_im_selben_block_bleibt_draussen(self):
        from core.bip158_scan import _bestand_nach_block

        bestand = {"alt:0": "bleibt"}
        _bestand_nach_block(
            bestand,
            {"neu:1": "entsteht", "gleich:0": "entsteht-und-geht"},
            {"gleich:0": "spender", "alt:0": "spender"},
        )
        self.assertEqual(bestand, {"neu:1": "entsteht"})


class TestHistorieWaechst(unittest.TestCase):
    def test_zweiter_durchgang_nimmt_den_hoeheren_treffer_mit(self):
        from core.bip158_wallet import naechste_historie_scripts

        xpub = _test_xpub()
        erste = naechste_historie_scripts(
            xpub, set(), set(), gap_limit=20, max_index=200,
        )
        self.assertIn(_spk(xpub, 0, 19), erste)
        self.assertNotIn(_spk(xpub, 0, 20), erste)
        zweite = naechste_historie_scripts(
            xpub, {_spk(xpub, 0, 30)}, erste, gap_limit=20, max_index=200,
        )
        self.assertIn(_spk(xpub, 0, 50), zweite)
        self.assertNotIn(_spk(xpub, 0, 19), zweite)
        self.assertNotIn(_spk(xpub, 0, 51), zweite)
        self.assertEqual(
            naechste_historie_scripts(
                xpub, {_spk(xpub, 0, 30)}, erste | zweite,
                gap_limit=20, max_index=200,
            ),
            set(),
        )


class TestPeerLiefertBlock(unittest.TestCase):
    def test_network_ja_limited_nur_junge_bloecke(self):
        from types import SimpleNamespace

        from core.p2p import (
            NETWORK_LIMITED_BLOCKS,
            NODE_NETWORK,
            NODE_NETWORK_LIMITED,
            naechster_block_peer,
            peer_liefert_block,
        )

        voll = SimpleNamespace(
            services=NODE_NETWORK, start_height=100_000, historie_aus=False, tot=False,
        )
        limited = SimpleNamespace(
            services=NODE_NETWORK_LIMITED, start_height=100_000,
            historie_aus=False, tot=False,
        )
        self.assertTrue(peer_liefert_block(voll, 50_000))
        self.assertFalse(peer_liefert_block(limited, 50_000))
        self.assertTrue(
            peer_liefert_block(limited, 100_000 - NETWORK_LIMITED_BLOCKS + 1)
        )
        limited.historie_aus = True
        self.assertFalse(peer_liefert_block(limited, 50_000))
        voll.tot = True
        self.assertFalse(peer_liefert_block(voll, 90_000))
        a = SimpleNamespace(services=NODE_NETWORK_LIMITED, start_height=100_000)
        b = SimpleNamespace(services=NODE_NETWORK, start_height=100_000)
        self.assertIs(naechster_block_peer([a, b], 50_000, set()), b)
        self.assertIs(naechster_block_peer([a, b], 99_900, set()), b)


class TestErsatzPeerLock(unittest.TestCase):
    def test_neuer_peer_nach_abbruch_ist_kein_keyerror(self):
        from unittest.mock import patch

        from core.bip158_scan import verteile_cfilter_chunks

        class Tot:
            def fetch_cfilters(self, start, stop, expect):
                raise BrokenPipeError("tot")

            def close(self):
                pass

        class Frisch:
            def __init__(self):
                self.calls = 0

            def fetch_cfilters(self, start, stop, expect):
                self.calls += 1
                return [(b"\x22" * 32, b"\x00") for _ in range(expect)]

            def close(self):
                pass

        frisch = Frisch()
        logs: list[str] = []
        with patch(
            "core.p2p.verbinde_compact_filter_peers",
            return_value=[frisch],
        ), patch("core.bip158_scan._CoreBasicFilterMatcher") as matcher:
            matcher.return_value.match_any.return_value = False
            out = list(verteile_cfilter_chunks(
                [Tot(), Tot()],
                [(100, 101, b"\x11" * 32)],
                frozenset({b"\x01"}),
                on_log=logs.append,
                hole_bloecke=False,
            ))
        self.assertEqual(len(out), 1)
        self.assertEqual(frisch.calls, 1)
        self.assertTrue(any("BrokenPipeError" in z for z in logs))
        self.assertFalse(any("KeyError" in z for z in logs))


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
