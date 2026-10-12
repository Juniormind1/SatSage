"""Blockhöhe einer Tx: eine Abfrage, dann die lokale Header-Datei.

Keine echten Adressen oder TxIDs. Die Header-Kette ist ein Mini-Mainnet
aus drei Blöcken über einem festen Anker.
"""
import struct
import tempfile
import unittest
from pathlib import Path

from core import fulcrum_history as fh
from core.derivation import script_address
from core.p2p import (
    GENESIS_HEADER,
    HEADER_FILE_MAGIC,
    HeaderChain,
    header_hash,
    hash_to_hex,
)
from core.xpub_cache import (
    BLOCK_HEADER_CACHE_SUBDIR,
    hoehe_fuer_blockhash,
    hoehe_zur_blockzeit,
    p2p_header_ntime,
    p2p_header_tip_stand,
)


def _adresse(n: int) -> str:
    from embit.script import Script

    return script_address(Script(b"\x00\x14" + bytes([n]) * 20))


def _header(prev: bytes, zeit: int) -> bytes:
    kopf = GENESIS_HEADER[:4] + prev + GENESIS_HEADER[36:68]
    return kopf + struct.pack("<I", zeit) + GENESIS_HEADER[72:]


class _Client:
    def __init__(self, antworten: dict):
        self.antworten = antworten
        self.aufrufe: list[tuple[str, list]] = []

    def request(self, method, params=None):
        self.aufrufe.append((method, list(params or [])))
        if method not in self.antworten:
            raise RuntimeError(f"unknown method {method}")
        wert = self.antworten[method]
        if isinstance(wert, Exception):
            raise wert
        return wert


class TestHoeheAusHeaderdatei(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.kette = HeaderChain()
        self.kette._anchor_height = 700_000
        self.kette._anchor_hash = header_hash(GENESIS_HEADER)
        self.h1 = _header(self.kette._anchor_hash, 1_638_000_000)
        self.h2 = _header(header_hash(self.h1), 1_638_000_600)
        self.kette._data = bytearray(self.h1 + self.h2)
        pfad = self.root / "p2p_headers.bin"
        blob = (
            HEADER_FILE_MAGIC
            + struct.pack("<I", self.kette._anchor_height)
            + self.kette._anchor_hash
            + bytes(self.kette._data)
        )
        pfad.write_bytes(blob)
        self._chain = _Patch(self.root)
        self.addCleanup(self._chain.stop)

    def test_hash_trifft_die_hoehe(self):
        blockhash = hash_to_hex(header_hash(self.h2))
        self.assertEqual(hoehe_fuer_blockhash(blockhash, self.root), 700_002)

    def test_zeit_halbierung_trifft_den_block(self):
        self.assertEqual(hoehe_zur_blockzeit(1_638_000_600, self.root), 700_002)
        self.assertEqual(hoehe_zur_blockzeit(1_638_000_000, self.root), 700_001)

    def test_zeit_ueber_dem_tip_bleibt_offen(self):
        self.assertIsNone(hoehe_zur_blockzeit(1_700_000_000, self.root))

    def test_unbekannter_hash_bleibt_offen(self):
        self.assertIsNone(hoehe_fuer_blockhash("ab" * 32, self.root))

    def test_p2p_header_ntime_ist_der_header(self):
        self.assertEqual(p2p_header_ntime(700_001, self.root), 1_638_000_000)
        self.assertEqual(p2p_header_ntime(700_002, self.root), 1_638_000_600)
        self.assertIsNone(p2p_header_ntime(700_000, self.root))
        self.assertIsNone(p2p_header_ntime(0, self.root))

    def test_p2p_header_ntime_schreibt_kein_json(self):
        p2p_header_ntime(700_001, self.root)
        cache_dir = self.root / BLOCK_HEADER_CACHE_SUBDIR
        self.assertFalse(cache_dir.is_dir() and any(cache_dir.glob("*.json")))

    def test_p2p_header_tip_stand(self):
        self.assertEqual(p2p_header_tip_stand(self.root), (700_002, 1_638_000_600))


class _Patch:
    def __init__(self, root: Path):
        from unittest.mock import patch

        self._p = patch(
            "core.xpub_cache._p2p_header_chain",
            lambda *_a, **_k: HeaderChain(root / "p2p_headers.bin"),
        )
        self._p.start()

    def stop(self):
        self._p.stop()


class TestHoehePerTxid(unittest.TestCase):
    def setUp(self):
        fh._TX_HEIGHT_CACHE.clear()
        fh._VERBOSE_TX_CACHE.clear()
        fh._HISTORY_CACHE.clear()
        fh.setze_eigene_adressen(None)
        self.txid = "cd" * 32

    def test_get_height_reicht_und_fragt_keine_adresse(self):
        client = _Client({"blockchain.transaction.get_height": 712_000})
        hoehe = fh._lookup_tx_height(client, self.txid, [{
            "scriptPubKey": {"address": _adresse(1)},
        }])
        self.assertEqual(hoehe, 712_000)
        self.assertEqual(
            [name for name, _ in client.aufrufe],
            ["blockchain.transaction.get_height"],
        )

    def test_blockhash_aus_der_datei_ohne_adresshistorie(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        kette = HeaderChain()
        kette._anchor_height = 712_000
        kette._anchor_hash = header_hash(GENESIS_HEADER)
        header = _header(kette._anchor_hash, 1_638_370_000)
        pfad = root / "p2p_headers.bin"
        pfad.write_bytes(
            HEADER_FILE_MAGIC
            + struct.pack("<I", 712_000)
            + kette._anchor_hash
            + header
        )
        blockhash = hash_to_hex(header_hash(header))
        patch = _Patch(root)
        self.addCleanup(patch.stop)
        client = _Client({
            "blockchain.transaction.get": {
                "blockhash": blockhash,
                "blocktime": 1_638_370_000,
            },
        })
        hoehe = fh._hoehe_per_txid(client, self.txid, [{
            "scriptPubKey": {"address": _adresse(2)},
        }])
        self.assertEqual(hoehe, 712_001)
        self.assertFalse(any(
            name == "blockchain.scripthash.get_history" for name, _ in client.aufrufe
        ))

    def test_eigene_adresse_vor_fremden_outputs(self):
        eigene = _adresse(9)
        fh.setze_eigene_adressen({eigene})
        client = _Client({
            "blockchain.scripthash.get_history": [
                {"tx_hash": self.txid, "height": 640_000},
            ],
        })
        vouts = [
            {"scriptPubKey": {"address": _adresse(20 + i)}}
            for i in range(5)
        ]
        vouts.append({"scriptPubKey": {"address": eigene}})
        hoehe = fh._hoehe_per_txid(client, self.txid, vouts)
        self.assertEqual(hoehe, 640_000)
        self.assertEqual(len(client.aufrufe), 3)
        self.assertEqual(
            client.aufrufe[-1][0], "blockchain.scripthash.get_history",
        )

    def test_ohne_eigene_adresse_bleiben_die_outputs(self):
        client = _Client({
            "blockchain.scripthash.get_history": [
                {"tx_hash": self.txid, "height": 640_001},
            ],
        })
        hoehe = fh._hoehe_per_txid(client, self.txid, [
            {"scriptPubKey": {"address": _adresse(3)}},
        ])
        self.assertEqual(hoehe, 640_001)
        self.assertEqual(
            client.aufrufe[-1][0], "blockchain.scripthash.get_history",
        )

    def test_electrs_tote_methoden_nur_beim_ersten_txid(self):
        andere = "ab" * 32
        client = _Client({
            "blockchain.transaction.get_height": RuntimeError(
                "unknown method blockchain.transaction.get_height"
            ),
            "blockchain.transaction.get": RuntimeError(
                "verbose transactions are currently unsupported"
            ),
            "blockchain.scripthash.get_history": [
                {"tx_hash": self.txid, "height": 640_000},
                {"tx_hash": andere, "height": 640_001},
            ],
        })
        vout = [{"scriptPubKey": {"address": _adresse(4)}}]
        self.assertEqual(fh._hoehe_per_txid(client, self.txid, vout), 640_000)
        erste = [name for name, _ in client.aufrufe]
        self.assertEqual(erste.count("blockchain.transaction.get_height"), 1)
        self.assertEqual(erste.count("blockchain.transaction.get"), 1)
        client.aufrufe.clear()
        self.assertEqual(fh._hoehe_per_txid(client, andere, vout), 640_001)
        zweite = [name for name, _ in client.aufrufe]
        self.assertNotIn("blockchain.transaction.get_height", zweite)
        self.assertNotIn("blockchain.transaction.get", zweite)

    def test_verbose_blockzeit_ohne_hoehe_und_ohne_fremde_historie(self):
        """Electrs-Regtest: kein get_height, Hash nicht in der Header-Datei."""
        fh.setze_eigene_adressen({_adresse(3)})
        self.addCleanup(fh.setze_eigene_adressen, None)
        client = _Client({
            "blockchain.transaction.get_height": RuntimeError(
                "method not found blockchain.transaction.get_height"
            ),
            "blockchain.transaction.get": {
                "blockhash": "ab" * 32,
                "blocktime": 1_790_606_384,
                "confirmations": 38,
            },
        })
        tx = fh._enrich_tx_block_info(client, {
            "txid": self.txid,
            "vout": [{"scriptPubKey": {"address": _adresse(4)}}],
            "confirmations": 0,
        })
        self.assertEqual(tx.get("blocktime"), 1_790_606_384)
        self.assertEqual(tx["status"]["block_time"], 1_790_606_384)
        self.assertFalse(any(
            name == "blockchain.scripthash.get_history" for name, _ in client.aufrufe
        ))

    def test_fremde_outputs_bleiben_unangetastet(self):
        fh.setze_eigene_adressen({_adresse(9)})
        client = _Client({
            "blockchain.scripthash.get_history": [
                {"tx_hash": self.txid, "height": 640_000},
            ],
        })
        hoehe = fh._hoehe_per_txid(client, self.txid, [
            {"scriptPubKey": {"address": _adresse(20)}},
        ])
        self.assertIsNone(hoehe)
        self.assertFalse(any(
            name == "blockchain.scripthash.get_history" for name, _ in client.aufrufe
        ))


class TestBlockzeitUndTip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        kette = HeaderChain()
        kette._anchor_height = 700_000
        kette._anchor_hash = header_hash(GENESIS_HEADER)
        self.h1 = _header(kette._anchor_hash, 1_638_000_000)
        self.h2 = _header(header_hash(self.h1), 1_638_000_600)
        (self.root / "p2p_headers.bin").write_bytes(
            HEADER_FILE_MAGIC
            + struct.pack("<I", 700_000)
            + kette._anchor_hash
            + self.h1
            + self.h2
        )
        self._chain = _Patch(self.root)
        self.addCleanup(self._chain.stop)
        from unittest.mock import patch

        p_dir = patch("core.xpub_cache.IMMUTABLE_CACHE_DIR", self.root)
        p_dir.start()
        self.addCleanup(p_dir.stop)
        fh._HEADER_TIME_CACHE.clear()
        fh._TIP_HEIGHT_CACHE.clear()
        self.addCleanup(fh._HEADER_TIME_CACHE.clear)
        self.addCleanup(fh._TIP_HEIGHT_CACHE.clear)

    def test_hoehe_unter_dem_anker_fragt_den_server(self):
        kopf = _header(header_hash(GENESIS_HEADER), 1_600_000_000).hex()
        client = _Client({"blockchain.block.header": kopf})
        zeit = fh._block_time_for_height(client, 100)
        self.assertEqual(zeit, 1_600_000_000)
        self.assertTrue(any(
            name == "blockchain.block.header" for name, _ in client.aufrufe
        ))

    def test_bekannte_hoehe_liest_zeit_ohne_block_header(self):
        client = _Client({})
        zeit = fh._block_time_for_height(client, 700_002)
        self.assertEqual(zeit, 1_638_000_600)
        self.assertFalse(any(
            name == "blockchain.block.header" for name, _ in client.aufrufe
        ))

    def test_tip_aus_subscribe_ohne_block_header(self):
        client = _Client({
            "blockchain.headers.subscribe": {"height": 800_000},
        })
        self.assertEqual(fh.get_chain_tip_height(client, force=True), 800_000)
        self.assertEqual(
            [name for name, _ in client.aufrufe],
            ["blockchain.headers.subscribe"],
        )

    def test_tip_aus_headerdatei_ohne_server(self):
        client = _Client({})
        self.assertEqual(fh.get_chain_tip_height(client, force=True), 700_002)
        self.assertFalse(any(
            name == "blockchain.block.header" for name, _ in client.aufrufe
        ))


if __name__ == "__main__":
    unittest.main()
