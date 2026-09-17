"""
Deskriptoren aus dem herausziehen, was Wallets tatsächlich exportieren.

Sparrow, Specter und Bitcoin Core geben Deskriptoren in unterschiedlicher
Verpackung heraus: als nackte Zeile, in JSON, einzeln oder als Paar aus
Empfangs- und Change-Kette. Wer das von Hand zusammensetzt, verliert leicht
die Change-Kette — und damit die Hälfte seiner Adressen.

Diese Schicht nimmt den Text, wie er kommt, und liefert eine Form, aus der
sich beide Ketten ableiten lassen.
"""
import json
import unittest

from embit.networks import NETWORKS

import main
from core.config import deskriptoren_aus_text
from tests.fixtures import BIP84_ZPUB


def _keys(anzahl: int = 3) -> list[str]:
    hd = main._hdkey_for_xpub(BIP84_ZPUB)
    return [
        hd.derive([3000 + i]).to_base58(version=NETWORKS["main"]["xpub"])
        for i in range(anzahl)
    ]


K = _keys()


class TestNackterDeskriptor(unittest.TestCase):

    def test_einfache_zeile(self):
        roh = f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))"
        self.assertEqual(deskriptoren_aus_text(roh), [roh])

    def test_mit_pruefsumme(self):
        roh = f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))#abcdefgh"
        self.assertEqual(deskriptoren_aus_text(roh), [roh])

    def test_umgebende_leerzeichen_und_zeilen(self):
        roh = f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))"
        self.assertEqual(deskriptoren_aus_text(f"\n  {roh}  \n\n"), [roh])

    def test_leerer_text(self):
        self.assertEqual(deskriptoren_aus_text(""), [])
        self.assertEqual(deskriptoren_aus_text("   \n "), [])

    def test_text_ohne_deskriptor(self):
        self.assertEqual(deskriptoren_aus_text("nur ein Satz ohne alles"), [])


class TestJsonExporte(unittest.TestCase):

    def test_specter_stil(self):
        roh = f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))#abcdefgh"
        text = json.dumps({
            "label": "Tresor", "blockheight": 800000, "descriptor": roh,
        })
        self.assertEqual(deskriptoren_aus_text(text), [roh])

    def test_specter_ohne_wildcard_erhaelt_standardableitung(self):
        """
        Specter-Export auf Kontoebene: [fp/48h/…]xpub ohne /0/* —
        Empfang/Change erst durch /<0;1>/*.
        """
        roh = f"wsh(sortedmulti(2,{K[0]},{K[1]},{K[2]}))"
        text = json.dumps({
            "label": "mk4test", "blockheight": 961911, "descriptor": roh,
        })
        gefunden = deskriptoren_aus_text(text)
        self.assertEqual(len(gefunden), 1)
        self.assertIn("/<0;1>/*", gefunden[0])
        self.assertTrue(main.derive_addresses(gefunden[0], max_addresses=6))
        # Ohne Ergänzung wäre is_wildcard falsch und die Adresse die der
        # Kontoebene — nicht die Empfangsadresse #0 der Wallet.
        ohne = main.derive_descriptor_addresses(roh, max_addresses=2)
        mit = main.derive_descriptor_addresses(gefunden[0], max_addresses=2)
        self.assertTrue(mit)
        self.assertNotEqual(sorted(ohne), sorted(mit))

    def test_bitcoin_core_listdescriptors(self):
        """Core liefert eine Liste; die inaktiven gehören nicht dazu."""
        empfang = f"wsh(sortedmulti(2,{K[0]}/0/*,{K[1]}/0/*))#aaaaaaaa"
        change = f"wsh(sortedmulti(2,{K[0]}/1/*,{K[1]}/1/*))#bbbbbbbb"
        text = json.dumps({"wallet_name": "t", "descriptors": [
            {"desc": empfang, "active": True, "internal": False},
            {"desc": change, "active": True, "internal": True},
        ]})
        gefunden = deskriptoren_aus_text(text)
        self.assertEqual(len(gefunden), 1, "Paar sollte vereinigt werden")
        self.assertIn("<0;1>", gefunden[0])

    def test_sparrow_stil_verschachtelt(self):
        roh = f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))"
        text = json.dumps({"wallet": {"policy": {"descriptor": roh}}})
        self.assertEqual(deskriptoren_aus_text(text), [roh])


class TestPaarVereinigen(unittest.TestCase):
    """
    Zwei Deskriptoren, die sich nur in /0/* und /1/* unterscheiden, sind
    dieselbe Wallet. Getrennt gelesen fiele die Change-Kette unter den Tisch —
    und mit ihr das Wechselgeld, also oft der größere Teil des Bestands.
    """

    def test_empfang_und_change_werden_zusammengefuehrt(self):
        empfang = f"wsh(sortedmulti(2,{K[0]}/0/*,{K[1]}/0/*))"
        change = f"wsh(sortedmulti(2,{K[0]}/1/*,{K[1]}/1/*))"
        gefunden = deskriptoren_aus_text(f"{empfang}\n{change}")
        self.assertEqual(len(gefunden), 1)
        self.assertIn("<0;1>", gefunden[0])

    def test_vereinigtes_paar_leitet_beide_ketten_ab(self):
        empfang = f"wsh(sortedmulti(2,{K[0]}/0/*,{K[1]}/0/*))"
        change = f"wsh(sortedmulti(2,{K[0]}/1/*,{K[1]}/1/*))"
        vereint = deskriptoren_aus_text(f"{empfang}\n{change}")[0]

        aus_vereint = main.derive_addresses(vereint, max_addresses=8)
        nur_empfang = main.derive_addresses(empfang, max_addresses=8)
        nur_change = main.derive_addresses(change, max_addresses=8)
        self.assertTrue(nur_empfang & aus_vereint)
        self.assertTrue(nur_change & aus_vereint)

    def test_reihenfolge_egal(self):
        empfang = f"wsh(sortedmulti(2,{K[0]}/0/*,{K[1]}/0/*))"
        change = f"wsh(sortedmulti(2,{K[0]}/1/*,{K[1]}/1/*))"
        a = deskriptoren_aus_text(f"{empfang}\n{change}")
        b = deskriptoren_aus_text(f"{change}\n{empfang}")
        self.assertEqual(a, b)

    def test_verschiedene_wallets_bleiben_getrennt(self):
        eins = f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))"
        zwei = f"wsh(sortedmulti(2,{K[1]}/<0;1>/*,{K[2]}/<0;1>/*))"
        self.assertEqual(len(deskriptoren_aus_text(f"{eins}\n{zwei}")), 2)

    def test_bereits_mehrpfadig_bleibt_unveraendert(self):
        roh = f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))"
        self.assertEqual(deskriptoren_aus_text(roh), [roh])

    def test_sortedmulti_vertauschte_cosigner_werden_gepaart(self):
        """Gleiche Keys, andere Reihenfolge — trotzdem eine Wallet."""
        empfang = f"wsh(sortedmulti(2,{K[0]}/0/*,{K[1]}/0/*,{K[2]}/0/*))"
        change = f"wsh(sortedmulti(2,{K[2]}/1/*,{K[0]}/1/*,{K[1]}/1/*))"
        gefunden = deskriptoren_aus_text(f"{empfang}\n{change}")
        self.assertEqual(len(gefunden), 1)
        self.assertIn("<0;1>", gefunden[0])


class TestBitkeyExport(unittest.TestCase):
    """
    Bitkey exportiert Watch-only als beschriftetes Paar:

        External: wsh(sortedmulti(2,…/0/*,…))
        Internal: wsh(sortedmulti(2,…/1/*,…))

    (siehe ExportWatchingDescriptorServiceImpl). Ohne Zusammenführung wären
    Empfang und Change zwei Wallets — oder die Change-Kette fehlt.
    """

    def _bitkey_text(self, *, reorder_internal: bool = False) -> str:
        fps = ("34eae6a8", "3bef7db3", "aabbccdd")
        # Bitkey nutzt Apostroph-Pfade und oft keine Prüfsumme.
        ext_keys = ",".join(
            f"[{fps[i]}/84'/0'/0']{K[i]}/0/*" for i in range(3)
        )
        order = (2, 0, 1) if reorder_internal else (0, 1, 2)
        int_keys = ",".join(
            f"[{fps[i]}/84'/0'/0']{K[i]}/1/*" for i in order
        )
        external = f"wsh(sortedmulti(2,{ext_keys}))"
        internal = f"wsh(sortedmulti(2,{int_keys}))"
        return f"External: {external}\n\nInternal: {internal}"

    def test_external_internal_werden_eine_wallet(self):
        gefunden = deskriptoren_aus_text(self._bitkey_text())
        self.assertEqual(len(gefunden), 1)
        self.assertIn("/<0;1>/*", gefunden[0])
        self.assertTrue(main.derive_addresses(gefunden[0], max_addresses=6))

    def test_empfang_index_null_nicht_change(self):
        """Vergleichsadresse = Empfang #0, wie im Bitkey-QR — nicht Change."""
        from core.config import WalletEntry, erste_empfangsadresse

        vereint = deskriptoren_aus_text(self._bitkey_text())[0]
        empfang = erste_empfangsadresse(WalletEntry(descriptor=vereint))
        self.assertEqual(empfang, main.derive_address_at_index(vereint, 0, 0))
        self.assertNotEqual(empfang, main.derive_address_at_index(vereint, 1, 0))

    def test_internal_zuerst_und_leere_zeile(self):
        fps = ("34eae6a8", "3bef7db3", "aabbccdd")
        ext = (
            f"wsh(sortedmulti(2,"
            f"[{fps[0]}/84'/0'/0']{K[0]}/0/*,"
            f"[{fps[1]}/84'/0'/0']{K[1]}/0/*,"
            f"[{fps[2]}/84'/0'/0']{K[2]}/0/*))"
        )
        intr = (
            f"wsh(sortedmulti(2,"
            f"[{fps[0]}/84'/0'/0']{K[0]}/1/*,"
            f"[{fps[1]}/84'/0'/0']{K[1]}/1/*,"
            f"[{fps[2]}/84'/0'/0']{K[2]}/1/*))"
        )
        text = f"Internal: {intr}\n\nExternal: {ext}\n"
        gefunden = deskriptoren_aus_text(text)
        self.assertEqual(len(gefunden), 1)
        self.assertIn("<0;1>", gefunden[0])

    def test_vertauschte_cosigner_im_bitkey_export(self):
        gefunden = deskriptoren_aus_text(self._bitkey_text(reorder_internal=True))
        self.assertEqual(len(gefunden), 1)


class TestTaproot(unittest.TestCase):

    def test_taproot_wird_erkannt(self):
        roh = f"tr({K[0]}/<0;1>/*,multi_a(2,{K[1]}/<0;1>/*,{K[2]}/<0;1>/*))"
        self.assertEqual(deskriptoren_aus_text(roh), [roh])

    def test_taproot_paar_wird_vereinigt(self):
        empfang = f"tr({K[0]}/0/*,multi_a(2,{K[1]}/0/*,{K[2]}/0/*))"
        change = f"tr({K[0]}/1/*,multi_a(2,{K[1]}/1/*,{K[2]}/1/*))"
        gefunden = deskriptoren_aus_text(f"{empfang}\n{change}")
        self.assertEqual(len(gefunden), 1)
        self.assertTrue(main.derive_addresses(gefunden[0], max_addresses=6))


class TestUnbrauchbares(unittest.TestCase):

    def test_kaputter_deskriptor_wird_nicht_geliefert(self):
        """
        Was sich nicht ableiten lässt, taugt nicht — lieber nichts anbieten
        als etwas, das später still keine Adressen ergibt.
        """
        self.assertEqual(deskriptoren_aus_text("wsh(sortedmulti(2,abc,def))"), [])

    def test_musig_wird_abgelehnt(self):
        self.assertEqual(
            deskriptoren_aus_text(f"tr(musig({K[0]},{K[1]})/<0;1>/*)"), []
        )

    def test_privater_schluessel_wird_abgelehnt(self):
        """
        Ein xprv gehört nie in dieses Werkzeug. Er würde Ausgaben ermöglichen —
        SatSage schaut nur zu.
        """
        # Absichtlich ungültiger xprv-ähnlicher String (kein BIP32-Testvektor).
        text = "wpkh(xprv11111111111111111111111111111111111111111111111111111111111111111111111111111111/0/*)"
        self.assertEqual(deskriptoren_aus_text(text), [])


class TestWasabiWpkhPolicy(unittest.TestCase):
    """Wasabi „WPKH Wallet Policy“ — Single-Sig, nicht Multisig."""

    def test_wpkh_mit_origin_ist_single_sig(self):
        from core.config import WalletEntry
        from embit.descriptor.checksum import add_checksum
        from embit.networks import NETWORKS

        xpub = main._hdkey_for_xpub(BIP84_ZPUB).to_base58(
            version=NETWORKS["main"]["xpub"]
        )
        policy = add_checksum(f"wpkh([abcd1234/84h/0h/0h]{xpub}/<0;1>/*)")
        gefunden = deskriptoren_aus_text(policy)
        self.assertEqual(len(gefunden), 1)
        e = WalletEntry(name="Wasabi", descriptor=gefunden[0])
        self.assertFalse(e.is_multisig)
        self.assertEqual(e.script_type, "segwit")
        self.assertTrue(e.is_valid())
        self.assertEqual(e.analyse_schluessel, e.descriptor)
        self.assertTrue(main.derive_addresses(e.analyse_schluessel, max_addresses=4))

    def test_specter_diy_geschweifte_klammern(self):
        from embit.networks import NETWORKS

        xpub = main._hdkey_for_xpub(BIP84_ZPUB).to_base58(
            version=NETWORKS["main"]["xpub"]
        )
        diy = f"wpkh([abcd1234/84h/0h/0h]{xpub}/{{0,1}}/*)"
        gefunden = deskriptoren_aus_text(diy)
        self.assertEqual(len(gefunden), 1)
        self.assertIn("<0;1>", gefunden[0])


if __name__ == "__main__":
    unittest.main()
