"""
Adressableitung aus XPUBs.

Der Kern dieser Datei ist die Regression zu Befund 3 aus dem Linux-Testlauf (Skripttyp/SegWit):
Ein Schlüssel mit generischem xpub-Prefix, dessen Adressen tatsächlich natives
SegWit sind, darf nicht länger stillschweigend nur Legacy und Taproot ableiten.
"""
import unittest

import main
from tests.fixtures import (
    BIP84_AS_XPUB,
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    BIP84_RECEIVE_1,
    BIP84_ZPUB,
    VERSION_YPUB,
    reencode_xpub,
)


class TestBip84Vector(unittest.TestCase):
    """Gegen den öffentlichen Testvektor der BIP-84-Spezifikation."""

    def test_zpub_liefert_die_vektor_adressen(self):
        addresses = main.derive_addresses(BIP84_ZPUB, max_addresses=6)
        self.assertIn(BIP84_RECEIVE_0, addresses)
        self.assertIn(BIP84_RECEIVE_1, addresses)
        self.assertIn(BIP84_CHANGE_0, addresses)

    def test_zpub_liefert_ausschliesslich_native_segwit(self):
        addresses = main.derive_addresses(BIP84_ZPUB, max_addresses=10)
        self.assertTrue(addresses)
        for address in addresses:
            self.assertTrue(
                address.startswith("bc1q"),
                f"{address} ist kein natives SegWit",
            )

    def test_beide_ketten_werden_abgeleitet(self):
        """max_addresses teilt sich auf Receive- und Change-Kette auf."""
        addresses = main.derive_addresses(BIP84_ZPUB, max_addresses=6)
        self.assertEqual(len(addresses), 6)
        self.assertIn(BIP84_RECEIVE_0, addresses)  # Kette 0
        self.assertIn(BIP84_CHANGE_0, addresses)   # Kette 1

    def test_start_index_setzt_fort(self):
        """Light-Rescan: ab start_index werden andere Adressen abgeleitet."""
        erste = main.derive_addresses(BIP84_ZPUB, max_addresses=4, start_index=0)
        spaetere = main.derive_addresses(BIP84_ZPUB, max_addresses=4, start_index=10)
        self.assertFalse(erste & spaetere)

    def test_unbrauchbarer_schluessel_liefert_leere_menge(self):
        self.assertEqual(main.derive_addresses("kein-xpub"), set())


class TestPrefixErkennung(unittest.TestCase):
    """SLIP-132-Prefixe bestimmen den Skripttyp, solange nichts anderes gesetzt ist."""

    def test_ypub_liefert_nested_segwit(self):
        ypub = reencode_xpub(BIP84_ZPUB, VERSION_YPUB)
        addresses = main.derive_addresses(ypub, max_addresses=6)
        self.assertTrue(addresses)
        for address in addresses:
            self.assertTrue(address.startswith("3"), f"{address} ist kein P2SH")


class TestSkripttypUeberschreiben(unittest.TestCase):
    """
    Befund 3: Wallets ohne SLIP-132 exportieren immer 'xpub' — unabhängig vom
    tatsächlichen Ableitungspfad. Ohne Override findet das Werkzeug für solche
    Schlüssel keine UTXOs, obwohl Guthaben vorhanden ist.
    """

    def test_xpub_mit_segwit_findet_dieselben_adressen_wie_zpub(self):
        erwartet = main.derive_addresses(BIP84_ZPUB, max_addresses=6)
        tatsaechlich = main.derive_addresses(
            BIP84_AS_XPUB, max_addresses=6, script_type="segwit"
        )
        self.assertEqual(erwartet, tatsaechlich)
        self.assertIn(BIP84_RECEIVE_0, tatsaechlich)

    def test_xpub_automatik_probiert_auch_native_segwit(self):
        """
        Ohne Override soll die Automatik für xpub alle gängigen Typen abdecken,
        statt natives SegWit auszulassen.
        """
        addresses = main.derive_addresses(BIP84_AS_XPUB, max_addresses=8)
        self.assertIn(
            BIP84_RECEIVE_0,
            addresses,
            "xpub-Automatik lässt natives SegWit aus — Befund 3 ist offen",
        )

    def test_expliziter_typ_schlaegt_prefix(self):
        """Ein zpub, der ausdrücklich als Legacy geführt wird, liefert Legacy."""
        addresses = main.derive_addresses(
            BIP84_ZPUB, max_addresses=4, script_type="legacy"
        )
        self.assertTrue(addresses)
        for address in addresses:
            self.assertTrue(address.startswith("1"), f"{address} ist kein P2PKH")

    def test_auto_verhaelt_sich_wie_ohne_angabe(self):
        ohne = main.derive_addresses(BIP84_ZPUB, max_addresses=6)
        mit_auto = main.derive_addresses(BIP84_ZPUB, max_addresses=6, script_type="auto")
        self.assertEqual(ohne, mit_auto)


class TestSkripttypRegistry(unittest.TestCase):
    """
    Der Skripttyp liegt in einer Modul-Registry, damit auch Aufrufstellen ohne
    WalletContext ihn sehen (derive_address_at_index, _address_belongs_to_xpub,
    consolidate.py). Globaler Zustand — deshalb hier ausdrücklich geprüft.
    """

    def setUp(self):
        self._sicherung = dict(main._script_type_by_xpub)
        main._script_type_by_xpub.clear()

    def tearDown(self):
        main._script_type_by_xpub.clear()
        main._script_type_by_xpub.update(self._sicherung)

    def test_ohne_registrierung_gilt_auto(self):
        self.assertEqual(main.script_type_for_xpub(BIP84_AS_XPUB), "auto")

    def test_wallet_context_registriert_den_typ(self):
        ctx = main.build_wallet_context(
            [BIP84_AS_XPUB], wallet_names=["Ledger"], max_addresses=6,
            script_types=["segwit"],
        )
        self.assertEqual(ctx.script_type_for(BIP84_AS_XPUB), "segwit")
        self.assertEqual(main.script_type_for_xpub(BIP84_AS_XPUB), "segwit")

    def test_registrierter_typ_wirkt_auf_adressableitung_ohne_parameter(self):
        main.build_wallet_context(
            [BIP84_AS_XPUB], max_addresses=6, script_types=["segwit"]
        )
        # Ohne script_type-Argument — der Typ kommt aus der Registry.
        addresses = main.derive_addresses(BIP84_AS_XPUB, max_addresses=6)
        self.assertEqual(addresses, main.derive_addresses(BIP84_ZPUB, max_addresses=6))

    def test_wallet_context_ordnet_adressen_dem_richtigen_wallet_zu(self):
        ctx = main.build_wallet_context(
            [BIP84_AS_XPUB], wallet_names=["Ledger Alt"], max_addresses=6,
            script_types=["segwit"],
        )
        self.assertEqual(ctx.address_to_wallet.get(BIP84_RECEIVE_0), "Ledger Alt")

    def test_unbekannter_typ_faellt_auf_auto_zurueck(self):
        self.assertEqual(main.normalize_script_type("quatsch"), "auto")
        self.assertEqual(main.normalize_script_type(None), "auto")
        self.assertEqual(main.normalize_script_type(""), "auto")

    def test_gaengige_schreibweisen_werden_erkannt(self):
        for eingabe, erwartet in [
            ("SegWit", "segwit"), ("bip84", "segwit"), ("p2wpkh", "segwit"),
            ("BIP49", "nested"), ("p2sh-p2wpkh", "nested"),
            ("bip44", "legacy"), ("P2PKH", "legacy"),
            ("p2tr", "taproot"), ("bip86", "taproot"),
        ]:
            self.assertEqual(main.normalize_script_type(eingabe), erwartet, eingabe)


class TestChainNetwork(unittest.TestCase):
    def tearDown(self):
        main.set_chain_network(None)

    def test_regtest_adressen_haben_bcrt_hrp(self):
        main.set_chain_network("regtest")
        self.assertTrue(all(a.startswith("bcrt1") for a in main.derive_addresses(BIP84_ZPUB, max_addresses=6)))
        self.assertTrue(main.derive_address_at_index(BIP84_ZPUB, 0, 0).startswith("bcrt1"))

    def test_mainnet_adressen_haben_bc_hrp(self):
        main.set_chain_network(None)
        self.assertTrue(all(a.startswith("bc1") for a in main.derive_addresses(BIP84_ZPUB, max_addresses=6)))

if __name__ == "__main__":
    unittest.main()
