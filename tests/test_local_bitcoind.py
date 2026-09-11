"""MVP: lokalen bitcoind per Cookie/Loopback erkennen."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import local_bitcoind as local_core


class TestLocalBitcoindDiscovery(unittest.TestCase):
    def test_cookie_lesen(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie = Path(tmp) / ".cookie"
            cookie.write_text("__cookie__:geheim", encoding="utf-8")
            self.assertEqual(
                local_core._read_cookie(cookie),
                ("__cookie__", "geheim"),
            )

    def test_core_already_configured(self):
        self.assertFalse(local_core.core_already_configured({}))
        self.assertTrue(
            local_core.core_already_configured(
                {"NODE_IP": "127.0.0.1", "RPCUSER": "u", "RPCPASSWORD": "p"}
            )
        )
        self.assertTrue(
            local_core.core_already_configured(
                {"NODE_IP": "127.0.0.1", "RPC_COOKIE_FILE": "/x/.cookie"}
            )
        )

    def test_discover_mit_mock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cookie = root / ".cookie"
            cookie.write_text("__cookie__:secret", encoding="utf-8")
            with mock.patch.object(
                local_core, "default_bitcoin_datadirs", return_value=[root]
            ):
                with mock.patch.object(local_core, "_tcp_open", return_value=True):
                    with mock.patch.object(
                        local_core,
                        "_probe_rpc",
                        return_value={
                            "chain": "main",
                            "blocks": 800000,
                            "pruned": True,
                        },
                    ):
                        hit = local_core.discover_local_bitcoind()
            self.assertIsNotNone(hit)
            self.assertEqual(hit.port, 8332)
            self.assertTrue(hit.pruned)
            pub = hit.as_public_dict()
            self.assertNotIn("password", pub)
            updates = local_core.env_updates_from_hit(hit)
            self.assertEqual(updates["LOCAL_CORE_OPT_IN"], "1")
            self.assertEqual(updates["NODE_IP"], "127.0.0.1")
            self.assertEqual(updates["UTXO_RPC_HOST"], "127.0.0.1")
            self.assertIn("UTXO_RPC_COOKIE_FILE", updates)
            self.assertIn("RPC_COOKIE_FILE", updates)
            self.assertEqual(updates["BIP158_HOST"], "127.0.0.1:8333")
            self.assertNotIn("BIP158_P2P", updates)
            self.assertEqual(hit.p2p_port, 8333)
            only_utxo = local_core.env_updates_from_hit(
                hit, lookup_core_already=True
            )
            self.assertIn("UTXO_RPC_HOST", only_utxo)
            self.assertNotIn("NODE_IP", only_utxo)
            self.assertNotIn("BIP158_P2P", only_utxo)

    def test_opt_in_flag(self):
        self.assertTrue(local_core.local_core_opt_in_enabled({"LOCAL_CORE_OPT_IN": "1"}))
        self.assertFalse(local_core.local_core_opt_in_enabled({}))

    def test_utxo_rpc_dedicated(self):
        self.assertFalse(local_core.utxo_rpc_dedicated({}))
        self.assertTrue(
            local_core.utxo_rpc_dedicated({"UTXO_RPC_HOST": "127.0.0.1"})
        )
        self.assertTrue(
            local_core.utxo_rpc_dedicated(
                {"UTXO_RPC_COOKIE_FILE": "/tmp/.cookie"}
            )
        )


if __name__ == "__main__":
    unittest.main()
