"""
Normalisierung zwischen den Transaktionsformaten.

Bitcoin Core liefert Beträge als float in BTC, Esplora als int in Satoshis.
Eine Verwechslung an dieser Stelle verschiebt jeden Betrag um Faktor 100
Millionen, ohne dass irgendetwas abstürzt — deshalb hier besonders gründlich.
"""
import unittest

import main
from tests.fixtures import (
    BIP84_RECEIVE_0,
    EXTERN_A,
    TXID_EXTERN,
    core_tx,
    core_vin,
    core_vout,
    esplora_tx,
    esplora_vin,
    esplora_vout,
)


class TestAdressExtraktion(unittest.TestCase):

    def test_esplora_format(self):
        vout = esplora_vout(BIP84_RECEIVE_0, 60_000_000)
        self.assertEqual(main._extract_addresses(vout), [BIP84_RECEIVE_0])

    def test_core_rpc_format(self):
        vout = core_vout(0, BIP84_RECEIVE_0, 0.6)
        self.assertEqual(main._extract_addresses(vout), [BIP84_RECEIVE_0])

    def test_alte_core_variante_mit_addresses_liste(self):
        """Bitcoin Core vor 22.0 lieferte scriptPubKey.addresses als Liste."""
        vout = {"n": 0, "value": 0.6, "scriptPubKey": {"addresses": [BIP84_RECEIVE_0]}}
        self.assertEqual(main._extract_addresses(vout), [BIP84_RECEIVE_0])

    def test_output_ohne_adresse(self):
        """OP_RETURN und unbekannte Skripttypen haben keine Adresse."""
        vout = {"n": 0, "value": 0.0, "scriptPubKey": {"type": "nulldata"}}
        self.assertEqual(main._extract_addresses(vout), [])

    def test_leere_esplora_adresse_wird_verworfen(self):
        vout = {"scriptpubkey_address": None, "value": 0}
        self.assertEqual(main._extract_addresses(vout), [])


class TestBetragsExtraktion(unittest.TestCase):

    def test_core_rechnet_btc_in_sats(self):
        vout = core_vout(0, BIP84_RECEIVE_0, 0.6)
        self.assertEqual(main._extract_value_sats(vout), 60_000_000)

    def test_esplora_uebernimmt_sats_direkt(self):
        vout = esplora_vout(BIP84_RECEIVE_0, 60_000_000)
        self.assertEqual(main._extract_value_sats(vout), 60_000_000)

    def test_beide_formate_ergeben_denselben_betrag(self):
        self.assertEqual(
            main._extract_value_sats(core_vout(0, BIP84_RECEIVE_0, 1.23456789)),
            main._extract_value_sats(esplora_vout(BIP84_RECEIVE_0, 123_456_789)),
        )

    def test_float_rundung_verliert_keine_sats(self):
        """0.1 + 0.2 lässt grüßen: float-BTC muss sauber gerundet werden."""
        self.assertEqual(
            main._extract_value_sats(core_vout(0, BIP84_RECEIVE_0, 0.00000001)), 1
        )
        self.assertEqual(
            main._extract_value_sats(core_vout(0, BIP84_RECEIVE_0, 20.99999999)),
            2_099_999_999,
        )

    def test_btc_variante_ist_konsistent(self):
        vout = core_vout(0, BIP84_RECEIVE_0, 0.6)
        self.assertAlmostEqual(main._extract_value_btc(vout), 0.6, places=8)


class TestBlockhoehe(unittest.TestCase):

    def test_esplora_status(self):
        tx = esplora_tx(
            TXID_EXTERN,
            [esplora_vin(TXID_EXTERN, 0, EXTERN_A, 100)],
            [esplora_vout(BIP84_RECEIVE_0, 90)],
            block_height=857_930,
        )
        self.assertEqual(main._tx_block_height(tx), 857_930)

    def test_unbestaetigte_tx_hat_keine_hoehe(self):
        tx = {"txid": TXID_EXTERN, "status": {"confirmed": False}, "vin": [], "vout": []}
        self.assertIsNone(main._tx_block_height(tx))

    def test_core_tx_ohne_hoehenfeld(self):
        """Core liefert blocktime, aber keine Höhe — das ist kein Fehler."""
        tx = core_tx(TXID_EXTERN, [core_vin(TXID_EXTERN, 0)], [])
        self.assertIsNone(main._tx_block_height(tx))


class TestTxidNormalisierung(unittest.TestCase):

    def test_grossschreibung_und_leerzeichen(self):
        roh = "  " + "AB" * 32 + "  "
        self.assertEqual(main._normalize_txid(roh), "ab" * 32)


if __name__ == "__main__":
    unittest.main()
