"""Zieladresse fürs FIFO-Spend: Kodierung, Netz, eigenes Wallet."""
import unittest

from embit import bech32
from embit.networks import NETWORKS

import main
from core.adresse_werkzeug import (
    adress_merkmale,
    aktuelles_adress_netz,
    pruefe_zieladresse,
)
from httpserver.api.tools import api_address_owner
from tests.fixtures import BIP84_CHANGE_0, BIP84_RECEIVE_0, BIP84_ZPUB

#: BIP-173/350-Testvektoren (Mainnet).
P2WPKH_MAIN = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
P2TR_MAIN = "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"
#: v1-Programm mit bech32- statt bech32m-Prüfsumme (BIP-350: ungültig).
P2TR_FALSCHE_PRUEFSUMME = "bc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7k7grplx"
P2PKH_MAIN = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
P2SH_MAIN = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
P2PKH_TEST = "mipcBbFg9gMiCh81Kj8tqqdgoZub1ZJRfn"
P2WPKH_TEST = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"


def _regtest(addr_main: str) -> str:
    """Gleiches Witness-Programm, Regtest-HRP."""
    _, hrp, _ = bech32.bech32_decode(addr_main)
    ver, prog = bech32.decode(hrp, addr_main)
    return bech32.encode("bcrt", ver, prog)


class _State:
    def __init__(self, wallet, bereit=True):
        self.wallet_ctx = wallet
        self._bereit = bereit

    def context_bereit(self):
        return self._bereit


class TestAdressMerkmale(unittest.TestCase):

    def test_kodierungen(self):
        self.assertEqual(adress_merkmale(P2WPKH_MAIN)["art"], "bech32")
        self.assertEqual(adress_merkmale(P2TR_MAIN)["art"], "bech32m")
        self.assertEqual(adress_merkmale(P2PKH_MAIN)["art"], "base58")
        self.assertEqual(adress_merkmale(P2SH_MAIN)["typ"], "p2sh")
        self.assertEqual(adress_merkmale(P2WPKH_MAIN.upper())["art"], "bech32")

    def test_ungueltig(self):
        for falsch in (
            "", "hallo", P2WPKH_MAIN[:-1] + "5", P2TR_FALSCHE_PRUEFSUMME,
            P2PKH_MAIN[:-1] + "3", "bc1QW508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        ):
            self.assertIsNone(adress_merkmale(falsch), falsch)

    def test_netze(self):
        self.assertEqual(adress_merkmale(P2WPKH_MAIN)["netze"], ["main"])
        self.assertEqual(sorted(adress_merkmale(P2WPKH_TEST)["netze"]), ["signet", "test"])
        self.assertEqual(adress_merkmale(_regtest(P2WPKH_MAIN))["netze"], ["regtest"])
        # Base58: Testnet, Regtest und Signet teilen die Versionsbytes.
        self.assertIn("regtest", adress_merkmale(P2PKH_TEST)["netze"])


class TestZieladresse(unittest.TestCase):

    def tearDown(self):
        main.set_chain_network("main")

    def _ctx(self):
        return main.build_wallet_context(
            [BIP84_ZPUB], wallet_names=["Cold Storage"],
            max_addresses_per_xpub=[6], script_types=["segwit"],
        )

    def test_netz_zur_laufzeit(self):
        main.set_chain_network("regtest")
        self.assertEqual(aktuelles_adress_netz(), "regtest")
        main.set_chain_network("main")
        self.assertEqual(aktuelles_adress_netz(), "main")
        main.set_chain_network("testnet")
        self.assertEqual(aktuelles_adress_netz(), "test")

    def test_mainnet_eigen_fremd_ungueltig(self):
        main.set_chain_network("main")
        ctx = self._ctx()
        empfang = pruefe_zieladresse(ctx, BIP84_RECEIVE_0)
        self.assertEqual(empfang["status"], "meine")
        self.assertEqual(empfang["wallet"], "Cold Storage")
        self.assertEqual(pruefe_zieladresse(ctx, BIP84_CHANGE_0)["status"], "meine")
        self.assertEqual(pruefe_zieladresse(ctx, P2TR_MAIN)["status"], "fremd")
        self.assertEqual(pruefe_zieladresse(ctx, P2PKH_MAIN)["status"], "fremd")
        self.assertEqual(pruefe_zieladresse(ctx, "kaputt")["status"], "ungueltig")
        self.assertEqual(pruefe_zieladresse(ctx, P2TR_FALSCHE_PRUEFSUMME)["status"], "ungueltig")
        self.assertEqual(pruefe_zieladresse(None, P2TR_MAIN)["status"], "keine_wallets")

    def test_falsches_netz(self):
        main.set_chain_network("regtest")
        ctx = self._ctx()
        erg = pruefe_zieladresse(ctx, P2WPKH_MAIN)
        self.assertEqual(erg["status"], "falsches_netz")
        self.assertEqual(erg["netz"], "regtest")
        self.assertEqual(erg["adress_netze"], ["main"])
        self.assertEqual(pruefe_zieladresse(ctx, P2WPKH_TEST)["status"], "falsches_netz")
        self.assertEqual(pruefe_zieladresse(ctx, _regtest(P2TR_MAIN))["status"], "fremd")
        self.assertEqual(pruefe_zieladresse(ctx, P2PKH_TEST)["status"], "fremd")
        main.set_chain_network("main")
        self.assertEqual(
            pruefe_zieladresse(self._ctx(), _regtest(P2WPKH_MAIN))["status"], "falsches_netz")

    def test_regtest_eigene_adresse(self):
        main.set_chain_network("regtest")
        ctx = self._ctx()
        from core.derivation import derive_address_at_index
        eigene = derive_address_at_index(BIP84_ZPUB, 1, 2)  # Wechsel, Index 2
        self.assertTrue(eigene.startswith("bcrt1"))
        erg = pruefe_zieladresse(ctx, eigene)
        self.assertEqual(erg["status"], "meine")
        self.assertEqual(erg["wallet"], "Cold Storage")

    def test_antwort_ohne_schluesselmaterial(self):
        main.set_chain_network("main")
        erg = pruefe_zieladresse(self._ctx(), BIP84_RECEIVE_0)
        text = repr(erg)
        self.assertNotIn(BIP84_ZPUB, text)
        self.assertNotIn("pub", text.lower())
        self.assertEqual(set(erg), {"status", "address", "art", "netz", "wallet"})

    def test_api(self):
        main.set_chain_network("main")
        state = _State(self._ctx())
        erg = api_address_owner(state, {"addr": [f"  bitcoin:{BIP84_RECEIVE_0}?amount=1 "]})
        self.assertEqual(erg["status"], "meine")
        self.assertEqual(api_address_owner(state, {})["status"], "ungueltig")
        from server import ApiError
        with self.assertRaises(ApiError):
            api_address_owner(_State(None, bereit=False), {"addr": [P2TR_MAIN]})
        with self.assertRaises(ApiError):
            api_address_owner(state, {"addr": ["x" * 201]})


if __name__ == "__main__":
    unittest.main()
