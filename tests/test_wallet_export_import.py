"""Wallet-Export: Sparrow + Wasabi Auto-Erkennung."""
from __future__ import annotations

import json
import unittest

from embit.networks import NETWORKS

import main
from core.wallet_export_import import parse_wallet_export_dateien
from tests.fixtures import BIP84_ZPUB


def _xpub() -> str:
    hd = main._hdkey_for_xpub(BIP84_ZPUB)
    return hd.to_base58(version=NETWORKS["main"]["xpub"])


def _wpkh() -> str:
    xpub = _xpub()
    hd = main._hdkey_for_xpub(BIP84_ZPUB)
    return f"wpkh([{hd.fingerprint.hex()}/84h/0h/0h]{xpub}/<0;1>/*)"


class TestSparrowWeiterhin(unittest.TestCase):

    def test_deskriptor(self):
        d = _wpkh()
        r = parse_wallet_export_dateien([{"name": "w.txt", "text": d}])
        self.assertTrue(r.ok, r.fehler)
        self.assertIn("sparrow", r.formate)
        self.assertTrue(r.descriptor.startswith("wpkh("))


class TestWasabiViewOnly(unittest.TestCase):

    def test_hardware_wallet_json(self):
        xpub = _xpub()
        hd = main._hdkey_for_xpub(BIP84_ZPUB)
        fp = hd.fingerprint.hex()
        wallet = {
            "EncryptedSecret": None,
            "ChainCode": None,
            "MasterFingerprint": fp,
            "ExtPubKey": xpub,
            "TaprootExtPubKey": None,
            "PasswordVerified": True,
            "MinGapLimit": 21,
            "AccountKeyPath": "84'/0'/0'",
            "TaprootAccountKeyPath": "86'/0'/0'",
            "BlockchainState": {"Network": "Main", "Height": "800000"},
            "HdPubKeys": [],
        }
        r = parse_wallet_export_dateien([
            {"name": "Coldcard.json", "text": json.dumps(wallet)},
        ])
        self.assertTrue(r.ok, r.fehler)
        self.assertIn("wasabi", r.formate)
        self.assertEqual(len(r.descriptors), 1)
        self.assertIn("wpkh(", r.descriptors[0])
        self.assertIn(xpub, r.descriptors[0])
        self.assertIn(f"[{fp}/84h/0h/0h]", r.descriptors[0])
        self.assertEqual(r.namen[0], "Coldcard")

    def test_hardware_wallet_json_with_bom(self):
        xpub = _xpub()
        wallet = {
            "EncryptedSecret": None,
            "MasterFingerprint": "aabbccdd",
            "ExtPubKey": xpub,
            "AccountKeyPath": "84'/0'/0'",
            "HdPubKeys": [],
        }
        # Browser/Datei-Upload kann BOM als U+FEFF im Text behalten.
        r = parse_wallet_export_dateien([
            {"name": "HW.json", "text": "\ufeff" + json.dumps(wallet)},
        ])
        self.assertTrue(r.ok, r.fehler)
        self.assertIn("wasabi", r.formate)
        self.assertEqual(len(r.descriptors), 1)

    def test_segwit_und_taproot_zwei_konten(self):
        xpub = _xpub()
        # Zweiter xpub: andere Ableitung simulieren (gleicher Key reicht für Parse-Test
        # nur wenn ableitbar — verwende denselben, Deskriptor-Form muss tr() sein).
        wallet = {
            "EncryptedSecret": None,
            "MasterFingerprint": "aabbccdd",
            "ExtPubKey": xpub,
            "TaprootExtPubKey": xpub,
            "AccountKeyPath": "84'/0'/0'",
            "TaprootAccountKeyPath": "86'/0'/0'",
            "HdPubKeys": [],
        }
        r = parse_wallet_export_dateien([
            {"name": "HW.json", "text": json.dumps(wallet)},
        ])
        self.assertTrue(r.ok, r.fehler)
        self.assertEqual(len(r.descriptors), 2)
        kinds = sorted(
            "tr" if d.startswith("tr(") else "wpkh"
            for d in r.descriptors
        )
        self.assertEqual(kinds, ["tr", "wpkh"])
        self.assertEqual(sorted(r.namen), ["HW SegWit", "HW Taproot"])

    def test_hot_wallet_secret_abgelehnt(self):
        xpub = _xpub()
        wallet = {
            "EncryptedSecret": "6PR…fake",
            "MasterFingerprint": "11223344",
            "ExtPubKey": xpub,
            "AccountKeyPath": "84'/0'/0'",
            "HdPubKeys": [],
        }
        r = parse_wallet_export_dateien([
            {"name": "Hot.json", "text": json.dumps(wallet)},
        ])
        self.assertFalse(r.ok)
        self.assertIn("passwort", (r.fehler or "").lower())
        self.assertEqual(r.descriptors, [])

    def test_listunspentcoins_rpc(self):
        xpub = _xpub()
        d = _wpkh()
        txid = "ab" * 32
        coins = {
            "result": [{
                "txid": txid,
                "index": 2,
                "amount": 50_000,
                "anonymityScore": 1,
                "confirmed": True,
                "confirmations": 10,
                "label": "kyc",
                "keyPath": "84'/0'/0'/0/1",
                "address": "bc1qtest",
                "excludedFromCoinjoin": False,
            }],
        }
        r = parse_wallet_export_dateien([
            {"name": "w.txt", "text": d},
            {"name": "coins.json", "text": json.dumps(coins)},
        ])
        self.assertTrue(r.ok, r.fehler)
        self.assertEqual(len(r.utxos), 1)
        self.assertEqual(r.utxos[0]["txid"], txid)
        self.assertEqual(r.utxos[0]["vout"], 2)
        self.assertEqual(r.utxos[0]["value"], 50_000)
        self.assertIn("wasabi", r.formate)

    def test_gethistory_rpc(self):
        d = _wpkh()
        hist = [{
            "datetime": "2019-10-01T12:31:57+00:00",
            "height": 597871,
            "amount": -2110090,
            "label": "out",
            "tx": "cd" * 32,
            "islikelycoinjoin": "false",
        }]
        r = parse_wallet_export_dateien([
            {"name": "d.txt", "text": d},
            {"name": "hist.json", "text": json.dumps(hist)},
        ])
        self.assertTrue(r.ok, r.fehler)
        self.assertEqual(len(r.verlauf), 1)
        self.assertTrue(r.verlauf[0]["spent"])
        self.assertEqual(r.verlauf[0]["value"], 2110090)


if __name__ == "__main__":
    unittest.main()
