"""Lokale Sparrow-/Wasabi-Suche."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from embit.networks import NETWORKS

import main
from core import wallet_discover as discover
from tests.fixtures import BIP84_ZPUB


def _xpub() -> str:
    hd = main._hdkey_for_xpub(BIP84_ZPUB)
    return hd.to_base58(version=NETWORKS["main"]["xpub"])


class TestWalletDiscover(unittest.TestCase):

    def test_wasabi_view_only_importierbar(self):
        xpub = _xpub()
        wallet = {
            "EncryptedSecret": None,
            "MasterFingerprint": "aabbccdd",
            "ExtPubKey": xpub,
            "AccountKeyPath": "84'/0'/0'",
            "HdPubKeys": [],
            "BlockchainState": {"Network": "Main"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "WalletWasabi" / "Client" / "Wallets"
            root.mkdir(parents=True)
            pfad = root / "Hardware.json"
            pfad.write_text(json.dumps(wallet), encoding="utf-8")
            treffer = discover.suche_lokale_wallets(wurzeln=[root])
            self.assertEqual(len(treffer), 1)
            self.assertEqual(treffer[0].app, "wasabi")
            self.assertTrue(treffer[0].importable)
            self.assertFalse(treffer[0].locked)
            self.assertTrue(treffer[0].descriptors)

    def test_wasabi_utf8_bom_importierbar(self):
        """Wasabi speichert Wallet-JSON mit UTF-8-BOM (ef bb bf)."""
        xpub = _xpub()
        wallet = {
            "EncryptedSecret": None,
            "MasterFingerprint": "aabbccdd",
            "ExtPubKey": xpub,
            "AccountKeyPath": "84'/0'/0'",
            "HdPubKeys": [],
            "BlockchainState": {"Network": "Main"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "WalletWasabi" / "Client" / "Wallets"
            root.mkdir(parents=True)
            pfad = root / "BomWallet.json"
            # Wie Wasabi auf Disk: BOM + JSON (encoding=utf-8-sig schreibt BOM)
            pfad.write_text(json.dumps(wallet), encoding="utf-8-sig")
            self.assertEqual(pfad.read_bytes()[:3], b"\xef\xbb\xbf")
            treffer = discover.suche_lokale_wallets(wurzeln=[root])
            self.assertEqual(len(treffer), 1)
            self.assertTrue(treffer[0].importable, treffer[0].reason)
            self.assertTrue(treffer[0].descriptors)
            self.assertNotEqual(treffer[0].reason, "Kein JSON")

    def test_wasabi_hot_nicht_importierbar(self):
        xpub = _xpub()
        wallet = {
            "EncryptedSecret": "6PYfakeSecretMaterialXXXX",
            "MasterFingerprint": "aabbccdd",
            "ExtPubKey": xpub,
            "AccountKeyPath": "84'/0'/0'",
            "HdPubKeys": [],
            "BlockchainState": {"Network": "Main"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "WalletWasabi" / "Client" / "Wallets"
            root.mkdir(parents=True)
            (root / "Hot.json").write_text(json.dumps(wallet), encoding="utf-8")
            treffer = discover.suche_lokale_wallets(wurzeln=[root])
            self.assertEqual(len(treffer), 1)
            self.assertFalse(treffer[0].importable)
            self.assertTrue(treffer[0].locked)
            self.assertIn("Passwort", treffer[0].reason)

    def test_sortierung_importierbar_vor_locked(self):
        xpub = _xpub()
        view = {
            "EncryptedSecret": None,
            "MasterFingerprint": "aabbccdd",
            "ExtPubKey": xpub,
            "AccountKeyPath": "84'/0'/0'",
            "HdPubKeys": [],
            "BlockchainState": {"Network": "Main"},
        }
        hot = dict(view)
        hot["EncryptedSecret"] = "6PYfake"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "WalletWasabi" / "Client" / "Wallets"
            root.mkdir(parents=True)
            (root / "Zulu.json").write_text(json.dumps(view), encoding="utf-8")
            (root / "Alpha.json").write_text(json.dumps(view), encoding="utf-8")
            (root / "BetaHot.json").write_text(json.dumps(hot), encoding="utf-8")
            treffer = discover.suche_lokale_wallets(wurzeln=[root])
            self.assertEqual(len(treffer), 3)
            self.assertTrue(treffer[0].importable)
            self.assertTrue(treffer[1].importable)
            self.assertFalse(treffer[2].importable)
            self.assertEqual(
                [t.name for t in treffer if t.importable],
                ["Alpha", "Zulu"],
            )

    def test_on_log_pro_app(self):
        xpub = _xpub()
        view = {
            "EncryptedSecret": None,
            "MasterFingerprint": "aabbccdd",
            "ExtPubKey": xpub,
            "AccountKeyPath": "84'/0'/0'",
            "HdPubKeys": [],
            "BlockchainState": {"Network": "Main"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            wasabi = base / "WalletWasabi" / "Client" / "Wallets"
            sparrow = base / "Sparrow" / "wallets"
            wasabi.mkdir(parents=True)
            sparrow.mkdir(parents=True)
            (wasabi / "W.json").write_text(json.dumps(view), encoding="utf-8")
            (sparrow / "S.mv.db").write_bytes(b"H:2,block:2" + b"\x00" * 20)
            logs: list[str] = []
            discover.suche_lokale_wallets(
                wurzeln=[sparrow, wasabi],
                on_log=logs.append,
                mit_core_rpc=False,
            )
            self.assertIn("Suche Sparrow…", logs)
            self.assertIn("Suche Wasabi…", logs)
            self.assertEqual(logs.index("Suche Sparrow…"), 0)
            # Nach jedem Block: „Suche X… n gefunden“
            self.assertTrue(
                any(z.startswith("Suche Sparrow…") and "gefunden" in z for z in logs)
            )
            self.assertTrue(
                any(z.startswith("Suche Wasabi…") and "gefunden" in z for z in logs)
            )
            # Wasabi: 1 Treffer in der Abschlusszeile
            self.assertIn("Suche Wasabi… 1 gefunden", logs)

    def test_schon_vorhanden_ausgeblendet(self):
        xpub = _xpub()
        wallet = {
            "EncryptedSecret": None,
            "MasterFingerprint": "aabbccdd",
            "ExtPubKey": xpub,
            "AccountKeyPath": "84'/0'/0'",
            "HdPubKeys": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "WalletWasabi" / "Client" / "Wallets"
            root.mkdir(parents=True)
            pfad = root / "HW.json"
            pfad.write_text(json.dumps(wallet), encoding="utf-8")
            treffer = discover.suche_lokale_wallets(wurzeln=[root])
            self.assertEqual(len(treffer), 1)
            wid = treffer[0].id
            leer = discover.suche_lokale_wallets(
                wurzeln=[root], vorhandene_wallet_ids={wid},
            )
            self.assertEqual(leer, [])

    def test_zpub_blendet_deskriptor_treffer_aus(self):
        """Bekannter zpub (andere ID als Deskriptor) → Specter/Wasabi-Fund weg."""
        from core.config import WalletEntry, schluessel_kennung
        from core import wallets as wallets_mod

        xpub = _xpub()
        zpub = BIP84_ZPUB
        # zpub-String-ID ≠ Deskriptor-Adress-ID, Schlüssel material gleich.
        self.assertNotEqual(
            wallets_mod.wallet_id(zpub),
            wallets_mod.wallet_id(
                f"wpkh([aabbccdd/84h/0h/0h]{xpub}/<0;1>/*)"
            ),
        )
        self.assertEqual(schluessel_kennung(zpub), schluessel_kennung(xpub))

        wallet = {
            "EncryptedSecret": None,
            "MasterFingerprint": "aabbccdd",
            "ExtPubKey": xpub,
            "AccountKeyPath": "84'/0'/0'",
            "HdPubKeys": [],
        }
        known = WalletEntry(name="Cash & Carry", xpub=zpub)
        ids, kenn = wallets_mod.vorhandene_abgleich([known])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "WalletWasabi" / "Client" / "Wallets"
            root.mkdir(parents=True)
            (root / "Cash+Carry.json").write_text(
                json.dumps(wallet), encoding="utf-8",
            )
            # Nur String-ID des zpub → Treffer bliebe (Regression).
            noch = discover.suche_lokale_wallets(
                wurzeln=[root],
                vorhandene_wallet_ids={wallets_mod.eintrag_id(known)},
                mit_core_rpc=False,
            )
            self.assertEqual(len(noch), 1, "ohne Abgleich-IDs muss Treffer bleiben")
            # Mit adressbasierter ID + Kennung → ausgeblendet.
            leer = discover.suche_lokale_wallets(
                wurzeln=[root],
                vorhandene_wallet_ids=ids,
                vorhandene_schluessel_kennungen=kenn,
                mit_core_rpc=False,
            )
            self.assertEqual(leer, [])

    def test_sparrow_mv_db_nicht_importierbar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Sparrow" / "wallets"
            root.mkdir(parents=True)
            pfad = root / "Test.mv.db"
            # Unverschlüsselt-anmutender H2-Kopf — für SatSage trotzdem Schloss
            # (natives DB-Format, kein Direktimport).
            pfad.write_bytes(b"H:2,block:2,blockSize" + b"\x00" * 100)
            treffer = discover.suche_lokale_wallets(wurzeln=[root])
            self.assertEqual(len(treffer), 1)
            self.assertEqual(treffer[0].app, "sparrow")
            self.assertFalse(treffer[0].importable)
            self.assertTrue(treffer[0].locked)
            self.assertIn("Descriptor-Export", treffer[0].reason)

    def test_sparrow_h2encrypt_schloss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Sparrow" / "wallets"
            root.mkdir(parents=True)
            pfad = root / "Secret.mv.db"
            pfad.write_bytes(b"H2encrypt" + b"\x00" * 50)
            treffer = discover.suche_lokale_wallets(wurzeln=[root])
            self.assertEqual(len(treffer), 1)
            self.assertTrue(treffer[0].locked)
            self.assertFalse(treffer[0].importable)


if __name__ == "__main__":
    unittest.main()
