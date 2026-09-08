"""Regtest HRP vs mainnet address: Verlauf darf scriptPubKey matchen."""
import unittest

from embit import script
from embit.networks import NETWORKS

from fulcrum import (
    address_to_scripthash,
    fetch_address_history_fulcrum,
)
from tests.fixtures import core_tx, core_vin, core_vout, txid
from tests.test_fulcrum_verlauf import FakeFulcrumClient


class HrpMismatchVerlaufTest(unittest.TestCase):
    def test_regtest_vout_address_matches_mainnet_query_address(self):
        # Same witness program: bc1 (query) vs bcrt1 (chain).
        from embit.ec import PrivateKey
        pk = PrivateKey(b"\x01" * 32)
        pub = pk.get_public_key()
        spk = script.p2wpkh(pub)
        main_addr = spk.address()
        reg_addr = spk.address(NETWORKS["regtest"])
        self.assertNotEqual(main_addr, reg_addr)
        self.assertTrue(main_addr.startswith("bc1"))
        self.assertTrue(reg_addr.startswith("bcrt1"))

        tid_in = txid("hrp1")
        tid_prev = txid("hrp0")
        tx = core_tx(
            tid_in,
            vin=[core_vin(tid_prev, 0)],
            vout=[core_vout(0, reg_addr, 1.0)],
            confirmations=1,
        )
        # Real hex so scriptPubKey match works (fixtures leave hex empty).
        tx["vout"][0]["scriptPubKey"]["hex"] = spk.data.hex()

        client = FakeFulcrumClient(
            history_by_scripthash={
                address_to_scripthash(main_addr): [
                    {"tx_hash": tid_in, "height": 0},
                ],
            },
            tx_by_id={tid_in: tx},
        )
        eintraege = fetch_address_history_fulcrum(
            client, main_addr, address_to_scripthash(main_addr),
        )
        self.assertEqual(len(eintraege), 1)
        self.assertEqual(eintraege[0]["txid"], tid_in.lower())
        self.assertEqual(eintraege[0]["value"], 100_000_000)


if __name__ == "__main__":
    unittest.main()
