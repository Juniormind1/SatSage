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


if __name__ == "__main__":
    unittest.main()
