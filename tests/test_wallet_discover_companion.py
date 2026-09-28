"""Ledger-Live- und BitBox-Suche: nur Bitcoin, ein Konto je Treffer."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from embit.networks import NETWORKS

import main
from core import wallet_discover as discover
from core.config import WalletEntry, schluessel_kennung
from tests.fixtures import BIP84_ZPUB


def _xpub(salt: str = "") -> str:
    """Account-xpub im xpub-Prefix. Ledger speichert so auch Native SegWit."""
    hd = main._hdkey_for_xpub(BIP84_ZPUB)
    index = 1 if salt else 0
    account = hd.derive([index])
    return account.to_base58(version=NETWORKS["main"]["xpub"])


def _ledger(konten: list[dict]) -> dict:
    return {"data": {"accounts": konten}}


class TestLedgerBitbox(unittest.TestCase):

    def test_ledger_zwei_btc_eth_faellt_weg(self):
        xpub = _xpub()
        xpub_tap = _xpub("tap")
        data = _ledger([
            {
                "id": f"js:2:bitcoin:{xpub}:",
                "name": "Sparen",
                "currencyId": "bitcoin",
                "derivationMode": "native_segwit",
                "index": 0,
                "xpub": xpub,
            },
            {
                "id": "js:2:bitcoin:anderes:",
                "name": "Tap",
                "currency": "btc",
                "derivationMode": "taproot",
                "index": 1,
                "xpub": xpub_tap,
            },
            {
                "id": "js:2:ethereum:0xabc:",
                "name": "ETH",
                "currencyId": "ethereum",
                "xpub": xpub,
            },
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Ledger Live"
            root.mkdir()
            (root / "app.json").write_text(json.dumps(data), encoding="utf-8")
            treffer = discover.suche_lokale_wallets(wurzeln=[root], mit_core_rpc=False)
        self.assertEqual(len(treffer), 2)
        self.assertTrue(all(t.app == "ledger" and t.importable for t in treffer))
        self.assertEqual({t.name for t in treffer}, {"Sparen", "Tap"})
        self.assertTrue(any(t.path.endswith("#js:2:bitcoin:" + xpub + ":") for t in treffer))

    def test_ledger_native_segwit_trotz_xpub_prefix(self):
        xpub = _xpub()
        self.assertTrue(xpub.startswith("xpub"))
        data = _ledger([{
            "id": "konto-0",
            "name": "Native",
            "currencyId": "bitcoin",
            "derivationMode": "native_segwit",
            "index": 0,
            "xpub": xpub,
        }])
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "app.json"
            pfad.write_text(json.dumps(data), encoding="utf-8")
            treffer = discover._analysiere_ledger(pfad)
        self.assertEqual(len(treffer), 1)
        desc = treffer[0].descriptors[0]
        self.assertTrue(desc.startswith("wpkh("), desc)
        self.assertNotIn("pkh(", desc.split("(", 1)[0])
        self.assertIn(xpub, desc)

    def test_ledger_verschluesselt(self):
        data = {"encryption": {"ciphertext": "abc"}, "version": 1}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Ledger Wallet"
            root.mkdir()
            (root / "app.json").write_text(json.dumps(data), encoding="utf-8")
            treffer = discover.suche_lokale_wallets(wurzeln=[root], mit_core_rpc=False)
        self.assertEqual(len(treffer), 1)
        self.assertTrue(treffer[0].locked)
        self.assertFalse(treffer[0].importable)
        self.assertIn("Passwort", treffer[0].reason)

    def test_bitbox_remember_wallet(self):
        xpub = _xpub()
        data = {"accounts": [{
            "name": "BitBox Bitcoin",
            "code": "btc-p2wpkh-0",
            "coinCode": "btc-p2wpkh",
            "signingConfigurations": {
                "hw": {
                    "keypath": "m/84'/0'/0'",
                    "extendedPublicKey": xpub,
                    "xpubFingerprint": "aabbccdd",
                },
            },
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bitbox"
            root.mkdir()
            (root / "accounts.json").write_text(json.dumps(data), encoding="utf-8")
            (root / "config.json").write_text("{}", encoding="utf-8")
            treffer = discover.suche_lokale_wallets(wurzeln=[root], mit_core_rpc=False)
        self.assertEqual(len(treffer), 1)
        self.assertEqual(treffer[0].app, "bitbox")
        self.assertTrue(treffer[0].importable)
        self.assertTrue(treffer[0].descriptors[0].startswith("wpkh("), treffer[0].descriptors)
        self.assertIn("aabbccdd/84h", treffer[0].descriptors[0])
        self.assertEqual(treffer[0].name, "BitBox Bitcoin")

    def test_bitbox_nur_fremde_coins(self):
        data = {"accounts": [
            {"name": "LTC", "coinCode": "ltc", "code": "ltc-0"},
            {"name": "ETH", "coinCode": "eth", "code": "eth-0"},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "accounts.json"
            pfad.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(discover._analysiere_bitbox(pfad), [])

    def test_fragment_import_legt_kontonamen_an(self):
        xpub = _xpub()
        data = _ledger([
            {
                "id": "sparen",
                "name": "Sparen",
                "currencyId": "bitcoin",
                "derivationMode": "native_segwit",
                "index": 0,
                "xpub": xpub,
            },
            {
                "id": "tap",
                "name": "Tap",
                "currencyId": "bitcoin",
                "derivationMode": "taproot",
                "index": 1,
                "xpub": xpub,
            },
        ])
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "app.json"
            pfad.write_text(json.dumps(data), encoding="utf-8")
            parsed = discover.importiere_pfade([f"{pfad}#sparen"])
        self.assertTrue(parsed.ok, parsed.fehler)
        self.assertEqual(parsed.namen, ["Sparen"])
        self.assertEqual(len(parsed.descriptors), 1)
        self.assertTrue(parsed.descriptors[0].startswith("wpkh("))

    def test_duplikat_ueber_schluesselkennung(self):
        xpub = _xpub()
        data = _ledger([{
            "id": "sparen",
            "name": "Sparen",
            "currencyId": "bitcoin",
            "derivationMode": "native_segwit",
            "index": 0,
            "xpub": xpub,
        }])
        kennung = schluessel_kennung(xpub)
        self.assertTrue(kennung)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Ledger Live"
            root.mkdir()
            (root / "app.json").write_text(json.dumps(data), encoding="utf-8")
            leer = discover.suche_lokale_wallets(
                wurzeln=[root],
                vorhandene_schluessel_kennungen={kennung},
                mit_core_rpc=False,
            )
        self.assertEqual(leer, [])

    def test_log_reihenfolge(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in ("Sparrow/wallets", "Ledger Live", "bitbox"):
                (base / name).mkdir(parents=True)
            logs: list[str] = []
            discover.suche_lokale_wallets(
                wurzeln=[
                    base / "Sparrow" / "wallets",
                    base / "Ledger Live",
                    base / "bitbox",
                ],
                on_log=logs.append,
                mit_core_rpc=False,
            )
        self.assertLess(logs.index("Suche Sparrow…"), logs.index("Suche Ledger…"))
        self.assertLess(logs.index("Suche Ledger…"), logs.index("Suche BitBox…"))
        self.assertIn("Suche Ledger… 0 gefunden", logs)
        self.assertIn("Suche BitBox… 0 gefunden", logs)

    def test_anzeige(self):
        self.assertEqual(discover._app_anzeige("ledger"), "Ledger")
        self.assertEqual(discover._app_anzeige("bitbox"), "BitBox")
        self.assertTrue(WalletEntry)
