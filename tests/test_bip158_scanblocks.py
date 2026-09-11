"""TurboSync: ungenutzte Keys nicht durch die Historie jagen."""
from __future__ import annotations

import unittest

from bip158_scanner import (
    TURBO_WINDOW,
    _filter_prozent_text,
    _filter_umfang,
    plane_filter_passes,
    verteile_cfilter_chunks,
)
from core.p2p import (
    GENESIS_HEADER,
    HeaderChain,
    checkpoint_fuer,
    decode_cfilter,
    encode_getcfilters,
    encode_message,
    encode_version,
    hash_to_hex,
    header_hash,
)


class TestTurboPasses(unittest.TestCase):

    def test_erstscan_ohne_used_ist_turbo_dann_historie(self):
        """Wasabi-Erstscan: Turbo(all) zuerst, Historie nur Gap — kein Full-All-Keys."""
        alle = {b"\x01", b"\x02", b"\x03"}
        gap = {b"\x01"}
        tip = 900_000
        passe = plane_filter_passes(481_824, tip, alle, set(), gap_scripts=gap)
        self.assertEqual(len(passe), 2)
        turbo, histo = passe
        self.assertEqual(turbo[0], "turbo")
        self.assertEqual(turbo[1], tip - TURBO_WINDOW + 1)
        self.assertEqual(turbo[2], tip)
        self.assertEqual(turbo[3], frozenset(alle))
        self.assertEqual(histo[0], "historie")
        self.assertEqual(histo[1], 481_824)
        self.assertEqual(histo[2], turbo[1] - 1)
        self.assertEqual(histo[3], frozenset(gap))
        self.assertNotEqual(histo[3], frozenset(alle))

    def test_abbruch_zwischenstand_deaktiviert_turbo_nicht(self):
        """Partial-Cache ohne Fullscan-Flag → used leer → Turbo-Erstscan."""
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import main
        from bip158_scanner import _used_scripts_aus_cache

        self.assertFalse(main.bip158_fullscan_ist_fertig({}))
        self.assertFalse(
            main.bip158_fullscan_ist_fertig(
                {"bip158_fullscan_ok": False, "utxos": [{"address": "x"}]}
            )
        )
        self.assertTrue(main.bip158_fullscan_ist_fertig({"bip158_fullscan_ok": True}))
        self.assertTrue(main.bip158_fullscan_ist_fertig({"scan_tip_height": 800_000}))
        self.assertFalse(main.bip158_fullscan_ist_fertig({"scan_tip_height": 0}))

        xpub = (
            "xpub6D4BDPcP2GT577Vvch3R8wDkScZWzQzMMUm3PWbmWvVJrZwQY4VUNgqFJPMM3N"
            "o2dFDFGTsxxpG5uJh7n7epu4trkrX7x7DogT5Uf1nxASY"
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            # Zwischenstand nach Abbruch: UTXOs da, Fullscan nicht ok.
            main.save_xpub_utxo_cache(
                xpub,
                [{
                    "txid": "ab" * 32,
                    "vout": 0,
                    "value": 1000,
                    "address": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
                }],
                cache,
                "bip158",
                bip158_fullscan_ok=False,
            )
            self.assertEqual(_used_scripts_aus_cache(xpub, cache), set())
            # Fertig: Flag + Tip → used aus Cache (Mock der Adress→Script-Map).
            main.save_xpub_utxo_cache(
                xpub,
                [{
                    "txid": "ab" * 32,
                    "vout": 0,
                    "value": 1000,
                    "address": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
                }],
                cache,
                "bip158",
                scan_tip_height=900_000,
                bip158_fullscan_ok=True,
            )
            with patch(
                "bip158_scanner.addresses_to_script_pubkeys",
                return_value={b"\x01\x02": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"},
            ):
                self.assertEqual(_used_scripts_aus_cache(xpub, cache), {b"\x01\x02"})
            # Zwischenstand nach Fullscan behält ok.
            main.schreibe_utxo_zwischenstand(
                xpub,
                [{
                    "txid": "cd" * 32,
                    "vout": 0,
                    "value": 500,
                    "address": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
                }],
                cache,
                "bip158",
            )
            ein = main.load_xpub_cache_entry(xpub, cache)
            self.assertTrue(ein["raw"].get("bip158_fullscan_ok"))

    def test_erstscan_ohne_gap_historie_leer(self):
        alle = {b"\x01", b"\x02"}
        passe = plane_filter_passes(481_824, 900_000, alle, set())
        self.assertEqual(passe[0][0], "turbo")
        self.assertEqual(passe[1][0], "historie")
        self.assertEqual(passe[1][3], frozenset())

    def test_used_keys_historie_lookahead_nur_turbo(self):
        used = {b"\x01"}
        alle = {b"\x01", b"\x02", b"\x03"}
        tip = 900_000
        passe = plane_filter_passes(481_824, tip, alle, used)
        self.assertEqual(len(passe), 2)
        histo, turbo = passe
        self.assertEqual(histo[0], "historie")
        self.assertEqual(histo[3], frozenset(used))
        self.assertNotIn(b"\x02", histo[3])
        self.assertEqual(turbo[0], "turbo")
        self.assertEqual(turbo[1], tip - TURBO_WINDOW + 1)
        self.assertEqual(turbo[3], frozenset(alle))
        self.assertLess(histo[2], turbo[1])

    def test_kurzer_bereich_nur_turbo(self):
        used = {b"\x01"}
        alle = {b"\x01", b"\x02"}
        passe = plane_filter_passes(899_000, 900_000, alle, used)
        self.assertEqual(len(passe), 1)
        self.assertEqual(passe[0][0], "turbo")
        self.assertEqual(passe[0][3], frozenset(alle))

    def test_filter_umfang_ist_nach_den_paessen_bekannt(self):
        alle = {b"\x01"}
        erst = plane_filter_passes(481_824, 900_000, alle, set(), gap_scripts=alle)
        self.assertEqual(_filter_umfang(erst), 900_000 - 481_824 + 1)
        zwei = plane_filter_passes(481_824, 900_000, alle, {b"\x01"})
        self.assertEqual(
            _filter_umfang(zwei),
            sum(bis - von + 1 for _n, von, bis, _s in zwei),
        )
        self.assertGreater(_filter_umfang(zwei), 0)

    def test_filter_prozent_text(self):
        self.assertEqual(_filter_prozent_text(0, 0), "")
        self.assertEqual(
            _filter_prozent_text(0, 481_375),
            "0/481.375 (0,0 %)",
        )
        self.assertIn("(2,5 %)", _filter_prozent_text(12_035, 481_375))
        self.assertIn("(100 %)", _filter_prozent_text(481_375, 481_375))
        self.assertIn("(12 %)", _filter_prozent_text(60_000, 481_375))


class TestFilterParallel(unittest.TestCase):

    def test_verteile_nutzt_mehrere_peers_in_reihenfolge(self):
        import threading
        import time

        class FakePeer:
            def __init__(self):
                self.starts: list[int] = []
                self._lock = threading.Lock()

            def fetch_cfilters(self, start, stop, expect):
                with self._lock:
                    self.starts.append(start)
                time.sleep(0.02)
                leer = b"\x00"
                h = bytes([start % 256]) + b"\x00" * 31
                return [(h, leer) for _ in range(expect)]

            def fetch_block(self, block_hash):
                raise AssertionError("leerer Filter braucht keinen Block")

        a, b = FakePeer(), FakePeer()
        chunks = [(i * 2, i * 2 + 1, b"\x11" * 32) for i in range(8)]
        logs: list[str] = []
        out = list(verteile_cfilter_chunks(
            [a, b], chunks, frozenset({b"\x01"}), on_log=logs.append,
        ))
        self.assertEqual(len(out), 8)
        for i, zeilen in enumerate(out):
            self.assertEqual(zeilen[0][0], i * 2)
            self.assertIsNone(zeilen[0][3])
        self.assertTrue(a.starts, "Peer A ohne Auftrag")
        self.assertTrue(b.starts, "Peer B ohne Auftrag")
        self.assertTrue(any("parallel" in z for z in logs), logs)

    def test_vorab_header_achtet_auf_abschalten(self):
        from bip158_scanner import vorab_block_header

        logs: list[str] = []
        tip = vorab_block_header(
            {"BIP158_P2P": "0"}, on_log=logs.append,
        )
        self.assertEqual(tip, 0)
        self.assertTrue(any("BIP158_P2P=0" in z for z in logs))

    def test_ein_peer_bleibt_sequentiell(self):
        class FakePeer:
            def fetch_cfilters(self, start, stop, expect):
                h = bytes([start % 256]) + b"\x00" * 31
                return [(h, b"\x00") for _ in range(expect)]

            def fetch_block(self, block_hash):
                raise AssertionError("kein Block")

        logs: list[str] = []
        out = list(verteile_cfilter_chunks(
            [FakePeer()],
            [(10, 11, b"\x11" * 32)],
            frozenset({b"\x01"}),
            on_log=logs.append,
        ))
        self.assertEqual(out[0][0][0], 10)
        self.assertFalse(any("parallel" in z for z in logs))

    def test_filter_treffer_loggt_bevor_der_block_kommt(self):
        from unittest.mock import patch

        from bip158_scanner import _BLOCK_PENDING, _lade_cfilter_chunk
        import queue

        logs: list[str] = []
        q: queue.Queue = queue.Queue()

        class FakePeer:
            def fetch_cfilters(self, start, stop, expect):
                return [(b"\x11" * 32, b"\x01")]

            def fetch_block(self, block_hash):
                raise AssertionError("async: kein Sync-Fetch im Filter-Worker")

        peer = FakePeer()
        with patch("bip158_scanner._CoreBasicFilterMatcher") as matcher:
            matcher.return_value.match_any.return_value = True
            zeilen = _lade_cfilter_chunk(
                peer, 850_123, 850_123, b"\x22" * 32,
                frozenset({b"\x01"}), on_log=logs.append,
                block_queue=q,
            )
        self.assertTrue(
            any("Filter-Treffer Block 850.123 — hole Block" in z for z in logs),
            logs,
        )
        self.assertIs(zeilen[0][3], _BLOCK_PENDING)
        hoehe, bhash = q.get_nowait()
        self.assertEqual(hoehe, 850_123)
        self.assertEqual(bhash, b"\x11" * 32)

    def test_filter_treffer_sync_ohne_queue(self):
        from unittest.mock import patch

        from bip158_scanner import _lade_cfilter_chunk

        logs: list[str] = []

        class FakePeer:
            def fetch_cfilters(self, start, stop, expect):
                return [(b"\x11" * 32, b"\x01")]

            def fetch_block(self, block_hash):
                self.gesehen = list(logs)
                self.hash = block_hash
                return b"\x00" * 80

        peer = FakePeer()
        with patch("bip158_scanner._CoreBasicFilterMatcher") as matcher:
            matcher.return_value.match_any.return_value = True
            zeilen = _lade_cfilter_chunk(
                peer, 850_123, 850_123, b"\x22" * 32,
                frozenset({b"\x01"}), on_log=logs.append,
            )
        self.assertTrue(any("hole Block" in z for z in peer.gesehen), peer.gesehen)
        self.assertEqual(peer.hash, b"\x11" * 32)
        self.assertIsNotNone(zeilen[0][3])
        self.assertIsNot(zeilen[0][3], object())

    def test_cfilter_cache_zweiter_scan_ohne_netz(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from bip158_scanner import _lade_cfilter_chunk
        from core.cfilter_cache import speichere_cfilter_blob

        hoehe = 850_100
        bhash = b"\xab" * 32
        blob = b"\x01\x02\x03"

        class FakePeer:
            def __init__(self):
                self.fetches = 0

            def fetch_cfilters(self, start, stop, expect):
                self.fetches += 1
                raise AssertionError("Cache warm — kein getcfilters")

            def fetch_block(self, block_hash):
                raise AssertionError("kein Match")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            speichere_cfilter_blob(root, hoehe, bhash, blob)
            peer = FakePeer()
            stats = {"geholt": 0, "gecacht": 0}
            with patch("bip158_scanner._CoreBasicFilterMatcher") as matcher:
                matcher.return_value.match_any.return_value = False
                zeilen = _lade_cfilter_chunk(
                    peer, hoehe, hoehe, bhash,
                    frozenset({b"\x01"}),
                    hash_at=lambda h: bhash,
                    cache_dir=root,
                    stats=stats,
                )
            self.assertEqual(peer.fetches, 0)
            self.assertEqual(stats["gecacht"], 1)
            self.assertEqual(stats["geholt"], 0)
            self.assertEqual(zeilen[0][2], blob)

    def test_filter_hit_enqueued_block_fetch_async(self):
        """Treffer geht in die Queue; Block-Worker holt nach Filter-Match."""
        import threading
        import time
        from unittest.mock import patch

        from bip158_scanner import verteile_cfilter_chunks

        fetch_block_calls: list = []
        filter_done = threading.Event()

        class FakePeer:
            def fetch_cfilters(self, start, stop, expect):
                time.sleep(0.02)
                filter_done.set()
                return [(b"\x11" * 32, b"\x01") for _ in range(expect)]

            def fetch_block(self, block_hash):
                fetch_block_calls.append((block_hash, filter_done.is_set()))
                time.sleep(0.05)
                return b"\x00" * 80

        peer = FakePeer()
        with patch("bip158_scanner._CoreBasicFilterMatcher") as matcher:
            matcher.return_value.match_any.return_value = True
            out = list(verteile_cfilter_chunks(
                [peer],
                [(100, 100, b"\x22" * 32)],
                frozenset({b"\x01"}),
            ))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0][3], b"\x00" * 80)
        self.assertEqual(len(fetch_block_calls), 1)
        self.assertTrue(fetch_block_calls[0][1], "Filter-Match vor Block-Fetch")

    def test_beschreibe_block_treffer_nennt_utxos_und_fp(self):
        from bip158_scanner import MatchedOutput, _beschreibe_block_treffer

        leer = _beschreibe_block_treffer(481_824, {}, set())
        self.assertEqual(
            leer, "Filter-Treffer Block 481.824 — False Positive"
        )
        out = MatchedOutput(
            txid="ab" * 32,
            vout=0,
            value_sats=45_000,
            address="bc1qabcdefghijklmnopqrstuvwxyz012345",
            script_pubkey_hex="00",
            block_height=850_123,
            block_hash="cd" * 32,
        )
        text = _beschreibe_block_treffer(
            850_123, {"ab:0": out}, {"xy:1"},
        )
        self.assertTrue(
            text.startswith("Filter-Treffer Block 850.123 — "), text
        )
        self.assertIn("+1 UTXO", text)
        self.assertIn("45,000 sats", text)
        self.assertIn("bc1qabcd…2345", text)
        self.assertIn("1 Output ausgegeben", text)

    def test_header_unixzeit_genesis(self):
        from bip158_scanner import _header_unixzeit

        self.assertEqual(_header_unixzeit(GENESIS_HEADER), 1_231_006_505)

    def test_block_verlauf_empfang_dann_abgang(self):
        from bip158_scanner import (
            MatchedOutput,
            _uebernehme_block_verlauf,
        )

        out = MatchedOutput(
            txid="aa" * 32,
            vout=0,
            value_sats=100_000,
            address="bc1qtest",
            script_pubkey_hex="00",
            block_height=800_000,
            block_hash="bb" * 32,
        )
        verlauf: dict = {}
        _uebernehme_block_verlauf(
            verlauf, {"aa" * 32 + ":0": out}, {},
            hoehe=800_000, block_time=1_700_000_000,
        )
        key = "aa" * 32 + ":0"
        self.assertFalse(verlauf[key]["spent"])
        self.assertEqual(verlauf[key]["value"], 100_000)
        self.assertEqual(verlauf[key]["status"]["block_time"], 1_700_000_000)
        _uebernehme_block_verlauf(
            verlauf, {}, {key: "cc" * 32},
            hoehe=800_100, block_time=1_700_100_000,
        )
        self.assertTrue(verlauf[key]["spent"])
        self.assertEqual(verlauf[key]["spent_txid"], "cc" * 32)
        self.assertEqual(verlauf[key]["spent_height"], 800_100)
        self.assertEqual(verlauf[key]["spent_time_ts"], 1_700_100_000)

    def test_merke_bip158_verlauf_mischt_ohne_unspend(self):
        import tempfile
        from pathlib import Path

        import main
        from tests.fixtures import BIP84_ZPUB

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            main.save_xpub_verlauf_cache(BIP84_ZPUB, [
                {
                    "txid": "aa" * 32, "vout": 0, "value": 1,
                    "spent": True, "spent_txid": "bb" * 32,
                    "address": "bc1qalt",
                },
            ], cache)
            main.merke_bip158_verlauf(BIP84_ZPUB, [
                {
                    "txid": "aa" * 32, "vout": 0, "value": 1,
                    "spent": False, "spent_txid": None,
                    "address": "bc1qalt",
                },
                {
                    "txid": "cc" * 32, "vout": 1, "value": 2,
                    "spent": False, "spent_txid": None,
                    "address": "bc1qneu",
                },
            ], cache)
            geladen = main.load_xpub_verlauf_cache(BIP84_ZPUB, cache)
        by_txid = {e["txid"]: e for e in geladen}
        self.assertTrue(by_txid["aa" * 32]["spent"])
        self.assertEqual(by_txid["aa" * 32]["spent_txid"], "bb" * 32)
        self.assertEqual(by_txid["cc" * 32]["value"], 2)


class TestP2pCodec(unittest.TestCase):

    def test_message_rundreise(self):
        roh = encode_message("verack")
        self.assertTrue(roh.startswith(b"\xf9\xbe\xb4\xd9"))
        self.assertEqual(len(roh), 24)

    def test_getcfilters_und_cfilter(self):
        stop = b"\x11" * 32
        payload = encode_getcfilters(481_824, stop)
        self.assertEqual(payload[0], 0)
        self.assertEqual(int.from_bytes(payload[1:5], "little"), 481_824)
        cfilter = b"\x00" + stop + b"\x03abc"
        h, blob = decode_cfilter(cfilter)
        self.assertEqual(h, stop)
        self.assertEqual(blob, b"abc")

    def test_genesis_header_hash(self):
        display = hash_to_hex(header_hash(GENESIS_HEADER))
        self.assertTrue(display.startswith("000000000019d668"))

    def test_p2p_peers_from_env_nimmt_lan_zuerst(self):
        from core.p2p import p2p_peers_from_env

        paare = p2p_peers_from_env({
            "FULCRUM_HOST": "192.168.1.50",
            "BIP158_PEERS": "198.51.100.1:8333",
        })
        self.assertEqual(paare[0], ("192.168.1.50", 8333))
        self.assertEqual(paare[1], ("198.51.100.1", 8333))

    def test_lan_host_ohne_filter_faellt_auf_dns_zurueck(self):
        from unittest.mock import MagicMock, patch

        import core.p2p as p2p_mod
        from core.p2p import probe_compact_filter_peer

        p2p_mod._FILTER_PEER_CACHE.clear()
        p2p_mod._FILTER_PEER_LOADED = True
        logs: list[str] = []

        def fake_verbinde(host, port, **kwargs):
            if host.startswith("192.168."):
                raise ConnectionError("bietet keine Compact Filter")
            return MagicMock()

        with patch("core.p2p.verbinde_peer", side_effect=fake_verbinde), patch(
            "core.p2p.dns_seed_hosts", return_value=[("192.0.2.9", 8333)],
        ), patch("core.p2p.clearnet_p2p_port_blockiert", return_value=False), patch(
            "core.p2p._speichere_filter_peers_datei",
        ):
            found = probe_compact_filter_peer(
                peers=[("192.168.1.50", 8333)],
                on_log=logs.append,
            )
        self.assertEqual(found, ("192.0.2.9", 8333))
        self.assertTrue(any("DNS-Seeds" in z for z in logs))
        self.assertTrue(
            any("192.168.1.50" in z and "fehlgeschlagen" in z for z in logs),
            logs,
        )
        p2p_mod._FILTER_PEER_CACHE.clear()

    def test_legt_header_archiv_aus_wenn_cache_fehlt(self):
        import gzip
        import json
        import struct
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from core.p2p import HEADER_FILE_MAGIC, GENESIS_HEADER, header_hash, lege_header_archiv_aus

        prev = header_hash(GENESIS_HEADER)
        fake = b"\x01\x00\x00\x00" + prev + b"\x00" * 44
        blob = HEADER_FILE_MAGIC + struct.pack("<I", 0) + prev + fake
        with tempfile.TemporaryDirectory() as tmp:
            ordner = Path(tmp)
            gz = ordner / "p2p_headers_segwit.bin.gz"
            gz.write_bytes(gzip.compress(blob))
            (ordner / "p2p_headers_segwit.meta.json").write_text(
                json.dumps({"tip_height": 1}), encoding="utf-8",
            )
            dest = ordner / "cache.bin"
            logs: list[str] = []
            with patch("core.p2p.header_archiv_pfad", return_value=gz):
                tip = lege_header_archiv_aus(dest, on_log=logs.append)
                nochmal = lege_header_archiv_aus(dest, on_log=logs.append)
            self.assertEqual(tip, 1)
            self.assertIsNone(nochmal)
            self.assertTrue(dest.is_file())
            self.assertTrue(any("Archiv aus" in z for z in logs))

    def test_header_cache_leer_ohne_datei(self):
        from pathlib import Path

        from core.p2p import header_cache_leer, header_datei_tip

        self.assertTrue(header_cache_leer(Path("/tmp/gibt-es-nicht-xpq.bin")))
        self.assertIsNone(header_datei_tip(None))

    def test_headerchain_startet_bei_genesis(self):
        chain = HeaderChain()
        self.assertEqual(chain.tip_height(), 0)
        self.assertEqual(chain.header_at(0), GENESIS_HEADER)

    def test_checkpoint_fuer_scanhoehe(self):
        hoehe, intern = checkpoint_fuer(850_000)
        self.assertEqual(hoehe, 850_000)
        self.assertEqual(
            hash_to_hex(intern),
            "00000000000000000002a0b5db2a7f8d9087464c2586b546be7bce8eb53b8187",
        )
        self.assertEqual(checkpoint_fuer(849_999)[0], 800_000)
        self.assertEqual(checkpoint_fuer(0)[0], 0)
        self.assertEqual(checkpoint_fuer(481_824)[0], 481_824)

    def test_genesis_checkpoint_stimmt_mit_header(self):
        hoehe, intern = checkpoint_fuer(0)
        self.assertEqual(hoehe, 0)
        self.assertEqual(intern, header_hash(GENESIS_HEADER))

    def test_headerchain_springt_auf_checkpoint(self):
        chain = HeaderChain(start_height=850_000)
        self.assertEqual(chain.tip_height(), 850_000)
        self.assertEqual(chain.hash_at(850_000), checkpoint_fuer(850_000)[1])
        self.assertEqual(chain.locator()[-1], checkpoint_fuer(850_000)[1])

    def test_headerchain_speichert_und_laedt_anker(self):
        import tempfile
        from pathlib import Path

        prev = checkpoint_fuer(850_000)[1]
        fake = b"\x01\x00\x00\x00" + prev + b"\x00" * 44
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "p2p_headers.bin"
            chain = HeaderChain(pfad, start_height=850_000)
            chain.append(fake)
            chain.save()
            again = HeaderChain(pfad, start_height=850_000)
            self.assertEqual(again.tip_height(), 850_001)
            self.assertEqual(again.hash_at(850_000), prev)
            self.assertEqual(again.header_at(850_001), fake)

    def test_altes_genesis_file_wird_gelesen(self):
        import tempfile
        from pathlib import Path

        fake = b"\x01\x00\x00\x00" + header_hash(GENESIS_HEADER) + b"\x00" * 44
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "p2p_headers.bin"
            pfad.write_bytes(GENESIS_HEADER + fake)
            chain = HeaderChain(pfad, start_height=850_000)
            # Tip 1 liegt unter dem Checkpoint → Sprung auf 850000
            self.assertEqual(chain.tip_height(), 850_000)

    def test_genesis_cache_bis_tip_bleibt(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "p2p_headers.bin"
            chain = HeaderChain(pfad)
            tip = header_hash(GENESIS_HEADER)
            for _ in range(3):
                nxt = b"\x01\x00\x00\x00" + tip + b"\x00" * 44
                chain.append(nxt)
                tip = header_hash(nxt)
            # Datei im alten Rohformat (Genesis + Header)
            pfad.write_bytes(GENESIS_HEADER + bytes(chain._data))
            geladen = HeaderChain(pfad)
            self.assertEqual(geladen.tip_height(), 3)
            self.assertEqual(geladen.header_at(0), GENESIS_HEADER)

    def _kette_aus(self, anzahl: int, *, start_height: int = 0) -> HeaderChain:
        chain = HeaderChain(start_height=start_height)
        tip = chain.hash_at(chain.tip_height())
        for i in range(anzahl):
            nxt = bytes([i + 1, 0, 0, 0]) + tip + b"\x00" * 44
            chain.append(nxt)
            tip = header_hash(nxt)
        return chain

    def test_header_batch_ueberspringt_bekannte(self):
        chain = self._kette_aus(3)
        tip_vorher = chain.tip_height()
        # Peer hinter uns: dieselben drei Header nochmal.
        batch = [chain.header_at(h) for h in range(1, tip_vorher + 1)]
        chain.wende_header_batch_an(batch)
        self.assertEqual(chain.tip_height(), tip_vorher)

    def test_header_batch_haengt_nach_overlap_an(self):
        chain = self._kette_aus(2)
        bekannt = [chain.header_at(1), chain.header_at(2)]
        tip = chain.hash_at(2)
        neu = b"\x0a\x00\x00\x00" + tip + b"\x00" * 44
        chain.wende_header_batch_an(bekannt + [neu])
        self.assertEqual(chain.tip_height(), 3)
        self.assertEqual(chain.header_at(3), neu)

    def test_header_batch_reorg_kuerzt_und_ersetzt(self):
        chain = self._kette_aus(3)
        # Gabel ab Höhe 1: anderer Nachfolger als unser #2/#3.
        eltern = chain.hash_at(1)
        gabel = b"\xff\x00\x00\x00" + eltern + b"\x00" * 44
        weiter = b"\xfe\x00\x00\x00" + header_hash(gabel) + b"\x00" * 44
        chain.wende_header_batch_an([gabel, weiter])
        self.assertEqual(chain.tip_height(), 3)
        self.assertEqual(chain.header_at(2), gabel)
        self.assertEqual(chain.header_at(3), weiter)

    def test_header_batch_ohne_anschluss_wirft(self):
        chain = self._kette_aus(1)
        fremd = b"\x01\x00\x00\x00" + (b"\xab" * 32) + b"\x00" * 44
        with self.assertRaises(ConnectionError):
            chain.wende_header_batch_an([fremd])

    def test_version_payload_hat_user_agent(self):
        payload = encode_version(nonce=1)
        self.assertIn(b"/SatSage:1.0/", payload)

    def test_zaehle_compact_filter_peers(self):
        from unittest.mock import MagicMock, patch

        import core.p2p as p2p_mod
        from core.p2p import zaehle_compact_filter_peers

        p2p_mod._GELOGGTE_FILTER_PEERS.clear()

        def fake_verbinde(host, port, **kwargs):
            if host.endswith(".1"):
                raise ConnectionError("nein")
            return MagicMock()

        logs: list[str] = []
        with patch("core.p2p.verbinde_peer", side_effect=fake_verbinde):
            n = zaehle_compact_filter_peers(
                peers=[("192.0.2.1", 8333), ("192.0.2.2", 8333), ("192.0.2.3", 8333)],
                versuche=3,
                dns_fallback=False,
                on_log=logs.append,
            )
        self.assertEqual(n, ["192.0.2.2:8333", "192.0.2.3:8333"])
        # Knapp: nur Erfolgszeilen je neuem Peer, kein Kandidaten-/Fehler-Spam.
        self.assertFalse(any("Verbinde mit" in z for z in logs), logs)
        self.assertFalse(any("fehlgeschlagen" in z for z in logs), logs)
        self.assertIn("Verbunden. Compact-Filter-Peer 192.0.2.2:8333.", logs)
        self.assertIn("Verbunden. Compact-Filter-Peer 192.0.2.3:8333.", logs)
        self.assertEqual(len([z for z in logs if z.startswith("Verbunden.")]), 2)

    def test_timeouts_an_wenigen_hosts_sind_firewall(self):
        from unittest.mock import patch

        from core.p2p import (
            clearnet_p2p_port_blockiert,
            reset_clearnet_port_block_cache,
        )

        reset_clearnet_port_block_cache()
        hosts = [
            ("198.51.100.1", 8333),
            ("198.51.100.2", 8333),
            ("203.0.113.9", 8333),
        ]
        logs: list[str] = []
        with patch(
            "core.p2p._stichprobe_clearnet_hosts", return_value=hosts,
        ), patch(
            "core.p2p._tcp_connect_fehler",
            return_value=TimeoutError("timed out"),
        ):
            self.assertTrue(clearnet_p2p_port_blockiert(on_log=logs.append))
        self.assertTrue(any("Prüfe Port 8333" in z for z in logs), logs)
        self.assertTrue(any("wirkt blockiert" in z for z in logs), logs)

        logs2: list[str] = []
        with patch("core.p2p._tcp_connect_fehler") as tcp:
            self.assertTrue(clearnet_p2p_port_blockiert(on_log=logs2.append))
        tcp.assert_not_called()
        self.assertTrue(any("bereits geprüft" in z for z in logs2), logs2)
        reset_clearnet_port_block_cache()

    def test_ein_offenes_tcp_ist_kein_block(self):
        from unittest.mock import patch

        from core.p2p import (
            clearnet_p2p_port_blockiert,
            reset_clearnet_port_block_cache,
        )

        reset_clearnet_port_block_cache()
        hosts = [
            ("198.51.100.1", 8333),
            ("198.51.100.2", 8333),
            ("203.0.113.9", 8333),
        ]
        n = {"i": 0}

        def fake_tcp(*_a, **_k):
            n["i"] += 1
            if n["i"] == 2:
                return None
            return TimeoutError("timed out")

        logs: list[str] = []
        with patch(
            "core.p2p._stichprobe_clearnet_hosts", return_value=hosts,
        ), patch("core.p2p._tcp_connect_fehler", side_effect=fake_tcp):
            self.assertFalse(clearnet_p2p_port_blockiert(on_log=logs.append))
        self.assertTrue(any("ist erreichbar" in z for z in logs), logs)
        reset_clearnet_port_block_cache()

    def test_connection_refused_ist_kein_block(self):
        from unittest.mock import patch

        from core.p2p import (
            clearnet_p2p_port_blockiert,
            reset_clearnet_port_block_cache,
        )

        reset_clearnet_port_block_cache()
        hosts = [("198.51.100.1", 8333), ("198.51.100.2", 8333)]
        with patch(
            "core.p2p._stichprobe_clearnet_hosts", return_value=hosts,
        ), patch(
            "core.p2p._tcp_connect_fehler",
            return_value=ConnectionRefusedError("refused"),
        ):
            self.assertFalse(clearnet_p2p_port_blockiert())
        reset_clearnet_port_block_cache()

    def test_zaehle_ueberspringt_dns_wenn_8333_blockiert(self):
        from unittest.mock import patch

        import core.p2p as p2p_mod
        from core.p2p import (
            reset_clearnet_port_block_cache,
            zaehle_compact_filter_peers,
        )

        reset_clearnet_port_block_cache()
        p2p_mod._FILTER_PEER_CACHE.clear()
        p2p_mod._FILTER_PEER_LOADED = True
        logs: list[str] = []
        with patch(
            "core.p2p.clearnet_p2p_port_blockiert", return_value=True,
        ), patch("core.p2p.dns_seed_hosts") as dns, patch(
            "core.p2p.verbinde_peer",
        ) as verb:
            n = zaehle_compact_filter_peers(
                on_log=logs.append, dns_fallback=True,
            )
        self.assertEqual(n, [])
        dns.assert_not_called()
        verb.assert_not_called()
        self.assertEqual(logs, [])
        reset_clearnet_port_block_cache()

    def test_verbinde_ruhig_unterdrueckt_hostzeilen(self):
        from unittest.mock import MagicMock, patch

        import core.p2p as p2p_mod
        from core.p2p import verbinde_compact_filter_peers

        p2p_mod._GELOGGTE_FILTER_PEERS.clear()
        logs: list[str] = []

        def fake_peer(host, port, **kwargs):
            m = MagicMock()
            m.host = host
            m.port = port
            return m

        with patch("core.p2p.verbinde_peer", side_effect=fake_peer), patch(
            "core.p2p.clearnet_p2p_port_blockiert", return_value=False,
        ):
            live = verbinde_compact_filter_peers(
                peers=[
                    ("192.0.2.1", 8333),
                    ("192.0.2.2", 8333),
                    ("192.0.2.3", 8333),
                    ("192.0.2.4", 8333),
                ],
                limit=4,
                versuche=4,
                dns_fallback=False,
                ruhig=True,
                on_log=logs.append,
            )
        self.assertEqual(len(live), 4)
        self.assertFalse(any("Verbinde mit" in z for z in logs), logs)
        self.assertFalse(any("DNS-Seed" in z for z in logs), logs)
        # Unter 3 Peers Log, ab 3 Stille — bei 4 Treffern also genau 3 Zeilen.
        self.assertEqual(
            len([z for z in logs if z.startswith("Verbunden. Compact-Filter-Peer ")]),
            3,
            logs,
        )
        self.assertFalse(any(z.startswith("Nur ") for z in logs), logs)

    def test_verbinde_ruhig_warnt_unter_drei_peers(self):
        from unittest.mock import MagicMock, patch

        import core.p2p as p2p_mod
        from core.p2p import verbinde_compact_filter_peers

        p2p_mod._GELOGGTE_FILTER_PEERS.clear()
        logs: list[str] = []

        def fake_peer(host, port, **kwargs):
            m = MagicMock()
            m.host = host
            m.port = port
            return m

        with patch("core.p2p.verbinde_peer", side_effect=fake_peer), patch(
            "core.p2p.clearnet_p2p_port_blockiert", return_value=False,
        ):
            live = verbinde_compact_filter_peers(
                peers=[("192.0.2.1", 8333), ("192.0.2.2", 8333)],
                limit=4,
                versuche=2,
                dns_fallback=False,
                ruhig=True,
                on_log=logs.append,
            )
        self.assertEqual(len(live), 2)
        self.assertTrue(
            any(
                "Nur 2 Compact-Filter-Peers" in z and "langsamer" in z
                for z in logs
            ),
            logs,
        )

    def test_verbinde_log_sagt_ueber_tor(self):
        from unittest.mock import MagicMock, patch

        import core.p2p as p2p_mod
        from core.p2p import zaehle_compact_filter_peers

        p2p_mod._GELOGGTE_FILTER_PEERS.clear()
        with patch("core.p2p.verbinde_peer", return_value=MagicMock()) as verb:
            zaehle_compact_filter_peers(
                peers=[("198.51.100.9", 8333)],
                versuche=1,
                dns_fallback=False,
                tor_proxy=("127.0.0.1", 9150),
                on_log=None,
            )
        verb.assert_called()
        kwargs = verb.call_args.kwargs
        self.assertEqual(kwargs.get("tor_proxy"), ("127.0.0.1", 9150))

    def test_lan_peer_auch_mit_tor_proxy_direkt(self):
        from unittest.mock import MagicMock, patch

        import core.p2p as p2p_mod
        from core.p2p import zaehle_compact_filter_peers

        p2p_mod._GELOGGTE_FILTER_PEERS.clear()
        with patch("core.p2p.verbinde_peer", return_value=MagicMock()) as verb:
            zaehle_compact_filter_peers(
                peers=[("192.168.1.50", 8333)],
                versuche=1,
                dns_fallback=False,
                tor_proxy=("127.0.0.1", 9150),
                on_log=None,
            )
        verb.assert_called()
        # LAN bleibt direkt — tor_proxy wird an verbinde_peer durchgereicht,
        # die Peer-Klasse verbindet LAN trotzdem ohne Tor (host_ist_lan).
        self.assertEqual(
            verb.call_args.kwargs.get("tor_proxy"), ("127.0.0.1", 9150),
        )

    def test_stelle_p2p_tor_prueft_laufenden_socks(self):
        from unittest.mock import patch

        from core.p2p import parse_p2p_tor_proxy, stelle_p2p_tor_bereit

        self.assertEqual(parse_p2p_tor_proxy({}), ("127.0.0.1", 9050))
        self.assertEqual(
            parse_p2p_tor_proxy({"FULCRUM_TOR_PROXY": "127.0.0.1:9150"}),
            ("127.0.0.1", 9150),
        )
        logs: list[str] = []
        with patch(
            "core.tor.stelle_tor_socks_bereit",
            return_value=("127.0.0.1", 9150),
        ) as socks:
            proxy = stelle_p2p_tor_bereit({}, on_log=logs.append)
        self.assertEqual(proxy, ("127.0.0.1", 9150))
        socks.assert_called_once()
        self.assertEqual(socks.call_args.args[0], ("127.0.0.1", 9050))

    def test_scanner_clearnet_fehlschlag_nimmt_tor(self):
        from unittest.mock import MagicMock, patch

        from bip158_scanner import BIP158Scanner

        peer = MagicMock()
        peer.host = "198.51.100.9"
        peer.port = 8333
        logs: list[str] = []

        def verbinde(*, tor_proxy=None, **kwargs):
            if tor_proxy:
                return [peer]
            return []

        scanner = BIP158Scanner(peers=[("198.51.100.9", 8333)], env={})
        scanner._log = logs.append
        with patch(
            "core.p2p.verbinde_compact_filter_peers", side_effect=verbinde,
        ), patch(
            "core.p2p.stelle_p2p_tor_bereit",
            return_value=("127.0.0.1", 9150),
        ) as tor:
            live = scanner._ensure_peers(limit=1)
        tor.assert_called_once()
        self.assertEqual(live, [peer])
        self.assertEqual(scanner._tor_proxy, ("127.0.0.1", 9150))
        self.assertTrue(any("versuche über Tor" in z for z in logs), logs)

    def test_dns_seed_fragt_compact_filter_zuerst(self):
        import socket
        from unittest.mock import patch

        from core.p2p import dns_seed_hosts

        gefragt: list[str] = []

        def fake_ga(name, port, family):
            gefragt.append(name)
            ip = "192.0.2.40" if name.startswith("x40.") else "192.0.2.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 8333))]

        logs: list[str] = []
        with patch("core.p2p.socket.getaddrinfo", side_effect=fake_ga):
            hosts = dns_seed_hosts(on_log=logs.append)
        self.assertTrue(any(n.startswith("x40.") for n in gefragt), gefragt)
        self.assertTrue(any("x40." in z for z in logs))
        self.assertEqual(hosts[0][0], "192.0.2.40")

    def test_bekannte_filter_peers_stehen_vor_dns(self):
        from core.p2p import (
            _FILTER_PEER_CACHE,
            _FILTER_PEER_LOADED,
            _kandidaten_ohne_dns,
            merke_filter_peer,
        )
        import core.p2p as p2p_mod

        p2p_mod._FILTER_PEER_CACHE.clear()
        p2p_mod._FILTER_PEER_LOADED = True  # kein Disk-Load in Unit-Test
        merke_filter_peer("192.0.2.77", 8333)
        logs: list[str] = []
        kandidaten = _kandidaten_ohne_dns(
            [("192.168.1.50", 8333)],
            on_log=logs.append,
        )
        self.assertEqual(kandidaten[0], ("192.168.1.50", 8333))
        self.assertIn(("192.0.2.77", 8333), kandidaten)
        self.assertTrue(any("Merk-Liste" in z for z in logs), logs)
        p2p_mod._FILTER_PEER_CACHE.clear()

    def test_filter_peers_persistenz_runde(self):
        """Merk-Liste überlebt Prozess-Neustart (Disk)."""
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import core.p2p as p2p_mod

        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "p2p_filter_peers.json"
            p2p_mod._FILTER_PEER_CACHE.clear()
            p2p_mod._FILTER_PEER_LOADED = True
            with patch.object(p2p_mod, "_filter_peer_pfad", return_value=pfad):
                p2p_mod.merke_filter_peer("198.51.100.9", 8333)
                p2p_mod.merke_filter_peer("198.51.100.8", 8333)
                self.assertTrue(pfad.is_file())
                # Simuliere Neustart
                p2p_mod._FILTER_PEER_CACHE.clear()
                p2p_mod._FILTER_PEER_LOADED = False
                bekannt = p2p_mod.bekannte_filter_peers()
            self.assertEqual(bekannt[0], ("198.51.100.8", 8333))
            self.assertIn(("198.51.100.9", 8333), bekannt)
            p2p_mod._FILTER_PEER_CACHE.clear()
            p2p_mod._FILTER_PEER_LOADED = False

    def test_verbinde_nutzt_merk_liste_vor_dns(self):
        """Phase 1: bekannte Peers, DNS nur wenn zu wenig."""
        from unittest.mock import MagicMock, patch

        import core.p2p as p2p_mod

        p2p_mod._FILTER_PEER_CACHE.clear()
        p2p_mod._FILTER_PEER_LOADED = True
        p2p_mod._FILTER_PEER_CACHE[:] = [("192.0.2.1", 8333)]
        logs: list[str] = []
        peer = MagicMock()
        peer.host = "192.0.2.1"
        peer.port = 8333
        dns_calls = {"n": 0}

        def fake_dns(*_a, **_k):
            dns_calls["n"] += 1
            return [("203.0.113.1", 8333)]

        with patch.object(p2p_mod, "verbinde_peer", return_value=peer), \
             patch.object(p2p_mod, "dns_seed_hosts", side_effect=fake_dns), \
             patch.object(p2p_mod, "clearnet_p2p_port_blockiert", return_value=False), \
             patch.object(p2p_mod, "_speichere_filter_peers_datei"):
            live = p2p_mod.verbinde_compact_filter_peers(
                limit=1, on_log=logs.append, ruhig=False,
            )
        self.assertEqual(len(live), 1)
        self.assertEqual(dns_calls["n"], 0)  # kein DNS bei genug Merk-Peers
        self.assertTrue(any("Merk-Liste" in z for z in logs), logs)
        p2p_mod._FILTER_PEER_CACHE.clear()

    def test_dns_seed_loggt_vor_der_abfrage(self):
        import socket
        from unittest.mock import patch

        from core.p2p import dns_seed_hosts

        logs: list[str] = []
        fake = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.9", 8333))]
        with patch("core.p2p.socket.getaddrinfo", return_value=fake) as ga:
            hosts = dns_seed_hosts("seed.example.test", on_log=logs.append)
        ga.assert_called()
        self.assertEqual(logs[0], "Frage DNS-Seed seed.example.test…")
        self.assertIn("DNS-Seed seed.example.test: 1 Adresse", logs)
        self.assertEqual(hosts[0][0], "192.0.2.9")
        self.assertLess(
            logs.index("Frage DNS-Seed seed.example.test…"),
            logs.index("DNS-Seed seed.example.test: 1 Adresse"),
        )


if __name__ == "__main__":
    unittest.main()
