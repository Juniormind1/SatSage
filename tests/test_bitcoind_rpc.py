import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.bitcoind_rpc import (
    CoreRpcConfig,
    _unspent_to_utxo,
    config_from_env,
    config_utxo_from_env,
    descriptors_for_key,
    normalize_rpc_host,
    scantxoutset_status_prozent,
    scantxoutset_utxos,
)
from core.jobs import Fortschritt, Job


class TestBitcoindRpc(unittest.TestCase):
    def test_normalize_strips_user_and_scheme(self):
        self.assertEqual(
            normalize_rpc_host("https://alice@abc.onion/path"),
            "abc.onion",
        )
        self.assertEqual(normalize_rpc_host("user@192.168.1.5"), "192.168.1.5")

    def test_config_utxo_slot_vor_lookup(self):
        env = {
            "NODE_IP": "10.0.0.5",
            "RPCPORT": "8332",
            "RPCUSER": "lookup",
            "RPCPASSWORD": "lpw",
            "UTXO_RPC_HOST": "127.0.0.1",
            "UTXO_RPCPORT": "8332",
            "UTXO_RPCUSER": "__cookie__",
            "UTXO_RPCPASSWORD": "geheim",
        }
        lookup = config_from_env(env)
        utxo = config_utxo_from_env(env)
        self.assertEqual(lookup.host, "10.0.0.5")
        self.assertEqual(utxo.host, "127.0.0.1")
        self.assertEqual(utxo.user, "__cookie__")
        # Ohne UTXO-Slot: Fallback auf Lookup
        nur = {
            "NODE_IP": "10.0.0.5",
            "RPCUSER": "lookup",
            "RPCPASSWORD": "lpw",
        }
        self.assertEqual(config_utxo_from_env(nur).host, "10.0.0.5")

    def test_descriptors_zpub_wpkh_path_inside(self):
        # zpub from fixtures if available
        try:
            from tests.fixtures import BIP84_ZPUB
            z = BIP84_ZPUB
        except Exception:
            self.skipTest("no fixture")
        objs = descriptors_for_key(z, max_index=10, script_type="auto")
        self.assertTrue(objs)
        paths = set()
        for o in objs:
            d = o["desc"].split("#")[0]
            self.assertIn("wpkh(", d)
            # path must be inside parens: wpkh(xpub/0/*)
            self.assertRegex(d, r"wpkh\([^)]+/[01]/\*\)")
            self.assertEqual(o["range"], [0, 10])
            if "/0/*" in d:
                paths.add(0)
            if "/1/*" in d:
                paths.add(1)
        self.assertEqual(paths, {0, 1})

    def test_unspent_mapping(self):
        u = _unspent_to_utxo({
            "txid": "ab" * 32,
            "vout": 1,
            "amount": 0.00012345,
            "height": 800_000,
            "scriptPubKey": "0014" + "11" * 20,
        })
        self.assertEqual(u["vout"], 1)
        self.assertEqual(u["value"], 12345)
        self.assertEqual(u["status"]["block_height"], 800_000)
        self.assertTrue(u["address"])

    def test_status_prozent_aus_dict_und_null(self):
        self.assertIsNone(scantxoutset_status_prozent(None))
        self.assertIsNone(scantxoutset_status_prozent({}))
        self.assertEqual(scantxoutset_status_prozent({"progress": 42}), 42.0)
        self.assertEqual(scantxoutset_status_prozent({"progress": 0.5}), 50.0)
        self.assertEqual(scantxoutset_status_prozent(17), 17.0)

    def test_scantxoutset_pollt_status_parallel(self):
        """Während start blockiert, liefert status den Prozentstand ins Log."""
        try:
            from tests.fixtures import BIP84_ZPUB
            z = BIP84_ZPUB
        except Exception:
            self.skipTest("no fixture")

        cfg = CoreRpcConfig(
            host="127.0.0.1",
            port=8332,
            user="u",
            password="p",
            use_ssl=False,
        )
        status_calls = {"n": 0}
        barrier = threading.Event()

        def start_call(_method, params):
            action = params[0]
            if action == "abort":
                return True
            if action == "start":
                barrier.set()
                # genug Zeit für mindestens einen Status-Poll
                time.sleep(0.35)
                return {
                    "height": 800_000,
                    "unspents": [],
                }
            raise AssertionError(f"unerwartet: {params}")

        def status_call(_method, params):
            self.assertEqual(params, ["status"])
            status_calls["n"] += 1
            barrier.wait(timeout=2.0)
            return {"progress": 37}

        start_client = SimpleNamespace(
            cfg=cfg,
            timeout=60.0,
            call=MagicMock(side_effect=start_call),
        )
        status_client = SimpleNamespace(
            cfg=cfg,
            timeout=30.0,
            call=MagicMock(side_effect=status_call),
        )

        job = Job(id="t", kind="rescan", label="Test")
        stand = Fortschritt(job)
        self.addCleanup(stand.close)

        utxos, tip = scantxoutset_utxos(
            start_client,  # type: ignore[arg-type]
            [z],
            default_max_index=2,
            status_client=status_client,  # type: ignore[arg-type]
            status_interval_s=0.05,
        )

        self.assertEqual(utxos, [])
        self.assertEqual(tip, 800_000)
        self.assertGreaterEqual(status_calls["n"], 1)
        log = " ".join(job.as_dict()["log"])
        # 5 %-Schritt: 37 % steht damit im Log (diskret ab erstem Update)
        self.assertIn("37%", log)
        self.assertIn("UTXO-Set (Core)", log)


if __name__ == "__main__":
    unittest.main()
