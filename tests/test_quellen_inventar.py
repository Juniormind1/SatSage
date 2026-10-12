"""Isolation der Labor-Quellen 1–3, ohne Node."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "lab" / "regtest" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from verify_quellen_inventar import (  # noqa: E402
    electrs_nach_klaeren_ok,
    geplante_quellen,
    isolierte_env,
    leere_ram_caches,
    p2p_nach_klaeren_ok,
    utxo_ist_voll_geklaert,
)


def _basis() -> dict[str, str]:
    return {
        "WALLET_0_NAME": "Lab Alpha",
        "WALLET_0_XPUB": "xpub-dummy",
        "WALLET_0_SCRIPT": "wpkh",
        "NETWORK": "regtest",
        "FULCRUM_HOST": "127.0.0.1",
        "FULCRUM_PORT": "50001",
        "FULCRUM_SSL": "false",
        "FULCRUM_TOR": "abc.onion",
        "NODE_IP": "127.0.0.1",
        "RPCPORT": "18443",
        "RPCUSER": "bitcoin",
        "RPCPASSWORD": "secret",
        "BIP158_P2P": "1",
        "BIP158_PEERS": "127.0.0.1:18444",
        "OEFFENTLICHE_ELECTRUM": "1",
    }


class TestQuellenIsolation(unittest.TestCase):
    def test_reihenfolge_ohne_p2p(self):
        self.assertEqual(
            geplante_quellen(p2p_an=False),
            ["own_fulcrum", "own_utxo_core", "own_core"],
        )

    def test_reihenfolge_mit_p2p(self):
        self.assertEqual(
            geplante_quellen(p2p_an=True),
            ["own_fulcrum", "own_utxo_core", "own_core", "bip158"],
        )

    def test_electrum_ohne_core(self):
        env = isolierte_env(_basis(), "own_fulcrum")
        self.assertEqual(env["FULCRUM_HOST"], "127.0.0.1")
        self.assertNotIn("NODE_IP", env)
        self.assertNotIn("UTXO_RPC_HOST", env)
        self.assertNotIn("FULCRUM_TOR", env)
        self.assertEqual(env["BIP158_P2P"], "0")
        self.assertEqual(env["OEFFENTLICHE_ELECTRUM"], "0")
        self.assertIn("WALLET_0_XPUB", env)

    def test_pruned_node_ohne_lookup_und_electrum(self):
        env = isolierte_env(_basis(), "own_utxo_core")
        self.assertEqual(env["UTXO_RPC_HOST"], "127.0.0.1")
        self.assertEqual(env["UTXO_RPCPORT"], "18443")
        self.assertNotIn("NODE_IP", env)
        self.assertNotIn("FULCRUM_HOST", env)
        self.assertEqual(env["BIP158_P2P"], "0")

    def test_core_rpc_ohne_utxo_slot_und_electrum(self):
        env = isolierte_env(_basis(), "own_core")
        self.assertEqual(env["NODE_IP"], "127.0.0.1")
        self.assertNotIn("UTXO_RPC_HOST", env)
        self.assertNotIn("FULCRUM_HOST", env)
        self.assertEqual(env["RPCUSER"], "bitcoin")

    def test_p2p_ohne_electrum_und_core(self):
        env = isolierte_env(_basis(), "bip158")
        self.assertEqual(env["BIP158_P2P"], "1")
        self.assertEqual(env["BIP158_PEERS"], "127.0.0.1:18444")
        self.assertNotIn("FULCRUM_HOST", env)
        self.assertNotIn("NODE_IP", env)


class TestP2pKlaeren(unittest.TestCase):
    def test_p2p_braucht_roten_ring(self):
        ok, grund = p2p_nach_klaeren_ok(rote=0)
        self.assertFalse(ok)
        self.assertIn("rote", grund)
        self.assertEqual(p2p_nach_klaeren_ok(rote=3), (True, ""))

    def test_leere_ram_caches(self):
        from core import bip158_wallet, xpub_cache

        xpub_cache._immutable_tx_memory["x" * 64] = {"txid": "x"}
        bip158_wallet._BLOCK_BYTES[b"k"] = b"v"
        geleert = leere_ram_caches()
        self.assertEqual(xpub_cache._immutable_tx_memory, {})
        self.assertEqual(bip158_wallet._BLOCK_BYTES, {})
        self.assertIn("core.xpub_cache._immutable_tx_memory", geleert)
    def test_electrs_raeumt_ringe_und_grau(self):
        ok, _grund = electrs_nach_klaeren_ok(
            rote=1, grau=[], lot=[], offen=[],
        )
        self.assertFalse(ok)
        ok, _grund = electrs_nach_klaeren_ok(
            rote=0, grau=["a:0"], lot=[], offen=[],
        )
        self.assertFalse(ok)
        ok, _grund = electrs_nach_klaeren_ok(
            rote=0, grau=[], lot=[], offen=["a:0"],
        )
        self.assertFalse(ok)
        ok, grund = electrs_nach_klaeren_ok(
            rote=0, grau=[], lot=[], offen=[],
        )
        self.assertTrue(ok)
        self.assertEqual(grund, "")

    def test_alt_ohne_baum_ist_geklaert_jung_unvollstaendig_nicht(self):
        alt = {"unvollstaendig": False, "verfolgt": False}
        self.assertTrue(utxo_ist_voll_geklaert(
            alt, {"geprueft": False, "erfuellt": True},
        ))
        jung = {
            "unvollstaendig": True,
            "verfolgt": True,
            "verfolgt_vollstaendig": False,
        }
        self.assertFalse(utxo_ist_voll_geklaert(
            jung, {"geprueft": True, "erfuellt": False},
        ))
        voll = {
            "unvollstaendig": False,
            "verfolgt": True,
            "verfolgt_vollstaendig": True,
        }
        self.assertTrue(utxo_ist_voll_geklaert(voll, {
            "geprueft": True,
            "erfuellt": False,
            "sats_grau": 0,
            "sats_ohne_datum": 0,
            "herkunft_offen": False,
        }))


class InventarTipTest(unittest.TestCase):
    def _schreibe(self, tip):
        import json
        import tempfile

        d = tempfile.mkdtemp()
        p = Path(d) / "inv.json"
        p.write_text(json.dumps({"tip_height": tip, "utxos": []}), encoding="utf-8")
        return p

    def test_veraltet_bricht_ab(self):
        from herkunft_inventar import pruefe_inventar_tip

        with self.assertRaisesRegex(RuntimeError, "Inventar veraltet"):
            pruefe_inventar_tip(291, self._schreibe(259))

    def test_ohne_tip_bricht_ab(self):
        from herkunft_inventar import pruefe_inventar_tip

        with self.assertRaisesRegex(RuntimeError, "Inventar veraltet"):
            pruefe_inventar_tip(291, self._schreibe(None))

    def test_aktuell_ok(self):
        from herkunft_inventar import pruefe_inventar_tip

        pruefe_inventar_tip(291, self._schreibe(291))


if __name__ == "__main__":
    unittest.main()
