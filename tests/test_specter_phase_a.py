import sys
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_SRC = Path(__file__).resolve().parent.parent / "specter_plugin" / "src"
if str(PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SRC))


class TestSpecterPhaseA(unittest.TestCase):
    def test_build_env_like_maps_chain_and_node_types(self):
        from satsage.specterext.satsage.bridge import SpecterNodeInfo, build_env_like

        core = SpecterNodeInfo(
            host="core", port=18443, user="bitcoin", password="secret",
            chain="regtest", node_type="bitcoind",
        )
        env = build_env_like(core, [])
        self.assertEqual(env["NETWORK"], "regtest")
        self.assertEqual(env["BIP158_P2P"], "1")
        self.assertNotIn("FULCRUM_HOST", env)
        self.assertEqual(env["RPCPORT"], "18443")

        electrum = SpecterNodeInfo(
            host="electrs", port=50002, chain="testnet", node_type="electrum",
            ssl=True,
        )
        env = build_env_like(electrum, [])
        self.assertEqual(env["NETWORK"], "test")
        self.assertEqual(env["FULCRUM_HOST"], "electrs")
        self.assertEqual(env["FULCRUM_SSL"], "true")
        self.assertNotIn("BIP158_P2P", env)

    def test_recv_descriptor_is_written_as_desc_wallet(self):
        from satsage.specterext.satsage.bridge import SatSageContext, SpecterWalletInfo
        from satsage.specterext.satsage import gui_server

        descriptor = "wpkh(xpub661MyMwAqRbcFh9x7sYJfP7B6v9h5x7fR7aQ4fVY8y3dL5uW7mL4wB7dT4fL8qQ9vM2nT5kP3rF6sV8xY2zA4bC6dE8fG0hJ2kL4mN6pQ8rS0tV2wX4yZ6/84h/0h/0h/0/*)"
        wallet = SpecterWalletInfo(name="Descriptor", alias="desc", recv_descriptor=descriptor)
        with mock.patch.object(gui_server, "ensure_satsage_on_path"), mock.patch(
            "core.config.WalletEntry.is_valid", return_value=True
        ):
            entries = gui_server._wallet_entries_aus_kontext(SatSageContext(wallets=[wallet]))
        self.assertEqual(entries[0].descriptor, descriptor)
        self.assertTrue(entries[0].is_multisig)


    def test_managed_api_blocks_wallet_and_source_writes(self):
        import server
        state = object.__new__(server.AppState)
        state.managed_by = "specter"
        with self.assertRaises(server.ApiError) as wallet_error:
            server.api_save_wallets(state, {})
        self.assertEqual(wallet_error.exception.status, 403)
        self.assertIn("Specter", wallet_error.exception.message)
        with self.assertRaises(server.ApiError) as source_error:
            server.api_save_source(state, {})
        self.assertEqual(source_error.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
