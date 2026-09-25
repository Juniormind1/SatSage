"""Sparrow-Klartext-Exporte parsen (Deskriptor + CSV)."""
from __future__ import annotations

import unittest

from embit.networks import NETWORKS

import main
from core.sparrow_import import parse_sparrow_dateien
from tests.fixtures import BIP84_ZPUB


def _wpkh() -> str:
    hd = main._hdkey_for_xpub(BIP84_ZPUB)
    xpub = hd.to_base58(version=NETWORKS["main"]["xpub"])
    return f"wpkh([{hd.fingerprint.hex()}/84h/0h/0h]{xpub}/<0;1>/*)"


class TestSparrowDeskriptor(unittest.TestCase):

    def test_nur_deskriptor(self):
        d = _wpkh()
        r = parse_sparrow_dateien([{"name": "Wallet-descriptor.txt", "text": d}])
        self.assertTrue(r.ok)
        self.assertIn("wpkh(", r.descriptor)
        self.assertEqual(r.name_vorschlag, "Wallet")
        self.assertEqual(r.namen[0], "Wallet")
        self.assertEqual(r.utxos, [])

    def test_privkey_abgelehnt(self):
        r = parse_sparrow_dateien([{
            "name": "bad.txt",
            "text": "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi",
        }])
        self.assertFalse(r.ok)
        self.assertIn("privat", r.fehler.lower())

    def test_ohne_deskriptor_nur_csv(self):
        r = parse_sparrow_dateien([{
            "name": "utxos.csv",
            "text": "Date,Output,Address,Label,Value\n"
                    "2024-01-01,aaaa" + "bb" * 30 + ":0,bc1qtest,,0.001\n",
        }])
        self.assertFalse(r.ok)
        self.assertIn("Deskriptor", r.fehler)


class TestSparrowCsv(unittest.TestCase):

    def test_utxo_und_tx_csv(self):
        d = _wpkh()
        txid = "ab" * 32
        utxo_csv = (
            "Date (UTC),Output,Address,Label,Value\n"
            f"2024-06-01 12:00:00,{txid}:1,bc1qabc,Sparbuch,0.00010000\n"
        )
        tx_csv = (
            "Date,Label,Value,Balance,Fee,Txid\n"
            f"2024-06-01,in,0.00010000,0.00010000,,{txid}\n"
            f"2024-07-01,out,-0.00005000,0.00005000,0.00000100,{'cd' * 32}\n"
        )
        r = parse_sparrow_dateien([
            {"name": "w.txt", "text": f"# Receive\n{d}\n"},
            {"name": "utxos.csv", "text": utxo_csv},
            {"name": "transactions.csv", "text": tx_csv},
        ])
        self.assertTrue(r.ok, r.fehler)
        self.assertEqual(len(r.utxos), 1)
        self.assertEqual(r.utxos[0]["txid"], txid)
        self.assertEqual(r.utxos[0]["vout"], 1)
        self.assertEqual(r.utxos[0]["value"], 10_000)
        self.assertEqual(r.utxos[0]["address"], "bc1qabc")
        self.assertEqual(len(r.verlauf), 2)
        abgang = [e for e in r.verlauf if e.get("spent")]
        self.assertEqual(len(abgang), 1)
        self.assertEqual(abgang[0]["value"], 5_000)


if __name__ == "__main__":
    unittest.main()
