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
from core.xpub_cache import hoehe_fuer_blockhash, hoehe_zur_blockzeit


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


if __name__ == "__main__":
    unittest.main()
