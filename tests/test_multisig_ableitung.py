"""
Adressableitung für Multisig — über den Output-Deskriptor.

Ein eigener Encoder für ``wsh(sortedmulti(…))`` hätte genau eine Form gekonnt
und wäre für Taproot und Miniscript neu zu bauen gewesen. embit bringt einen
vollständigen Deskriptor-Parser mit; damit deckt derselbe Weg Legacy,
Nested SegWit, Native SegWit, Taproot und Policies mit Zeitschloss ab.

Der Deskriptor ist deshalb die kanonische Form. ``_M``/``_SCRIPT``/``_XPUBS``
bleibt als Eingabe erlaubt und wird in einen Deskriptor überführt — ausdrücken
kann die Kurzform ohnehin nur ``sortedmulti``.
"""
import unittest

from embit.networks import NETWORKS

import main
from core.config import WalletEntry, deskriptor_aus_kurzform, validate_wallets
from tests.fixtures import (
    BIP84_CHANGE_0,
    BIP84_RECEIVE_0,
    BIP84_RECEIVE_1,
    BIP84_ZPUB,
)


def _testschluessel(anzahl: int = 4) -> list[str]:
    """
    Eigenständige, gültige XPUBs aus dem öffentlichen BIP-84-Testvektor.

    Abgeleitete Kinder — echte Schlüssel, aber zu einem allgemein bekannten
    Mnemonic („abandon … about"). Nichts davon ist schützenswert.
    """
    hd = main._hdkey_for_xpub(BIP84_ZPUB)
    return [
        hd.derive([1000 + i]).to_base58(version=NETWORKS["main"]["xpub"])
        for i in range(anzahl)
    ]


K = _testschluessel()
XPUB = main._hdkey_for_xpub(BIP84_ZPUB).to_base58(version=NETWORKS["main"]["xpub"])


class TestGegenTestvektoren(unittest.TestCase):
    """
    Die Ableitung muss dieselben Adressen liefern wie der bisherige Weg —
    sonst wären alle Bestände falsch zugeordnet.
    """

    def test_single_sig_ueber_deskriptor_trifft_bip84(self):
        adressen = main.derive_addresses(f"wpkh({XPUB}/<0;1>/*)", max_addresses=10)
        self.assertIn(BIP84_RECEIVE_0, adressen)
        self.assertIn(BIP84_RECEIVE_1, adressen)
        self.assertIn(BIP84_CHANGE_0, adressen)

    def test_sortedmulti_ist_reihenfolgeunabhaengig(self):
        """BIP-67: Die Cosigner werden sortiert, bevor das Skript entsteht."""
        a = main.derive_addresses(
            f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*,{K[2]}/<0;1>/*))",
            max_addresses=4,
        )
        b = main.derive_addresses(
            f"wsh(sortedmulti(2,{K[2]}/<0;1>/*,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))",
            max_addresses=4,
        )
        self.assertEqual(a, b)

    def test_multi_ist_reihenfolgeabhaengig(self):
        """Ohne „sorted" zählt die Reihenfolge — auch das muss stimmen."""
        a = main.derive_addresses(
            f"wsh(multi(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))", max_addresses=4
        )
        b = main.derive_addresses(
            f"wsh(multi(2,{K[1]}/<0;1>/*,{K[0]}/<0;1>/*))", max_addresses=4
        )
        self.assertNotEqual(a, b)


class TestFormen(unittest.TestCase):
    """Jede Form, die im Umlauf ist — und eine, die es nicht gibt."""

    def ableiten(self, descriptor: str, anzahl: int = 6) -> set:
        return main.derive_addresses(descriptor, max_addresses=anzahl)

    def test_legacy_p2sh(self):
        adressen = self.ableiten(f"sh(multi(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))")
        self.assertTrue(adressen)
        self.assertTrue(all(a.startswith("3") for a in adressen))

    def test_nested_segwit(self):
        adressen = self.ableiten(
            f"sh(wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*)))"
        )
        self.assertTrue(all(a.startswith("3") for a in adressen))

    def test_native_segwit(self):
        adressen = self.ableiten(
            f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))"
        )
        self.assertTrue(all(a.startswith("bc1q") for a in adressen))

    def test_taproot_multi_a(self):
        adressen = self.ableiten(
            f"tr({K[0]}/<0;1>/*,multi_a(2,{K[1]}/<0;1>/*,{K[2]}/<0;1>/*))"
        )
        self.assertTrue(all(a.startswith("bc1p") for a in adressen))

    def test_taproot_mehrere_blaetter(self):
        adressen = self.ableiten(
            f"tr({K[0]}/<0;1>/*,{{multi_a(2,{K[1]}/<0;1>/*,{K[2]}/<0;1>/*),"
            f"multi_a(2,{K[2]}/<0;1>/*,{K[3]}/<0;1>/*)}})"
        )
        self.assertTrue(all(a.startswith("bc1p") for a in adressen))

    def test_liana_wsh_mit_zeitschloss(self):
        """Primärschlüssel sofort, Recovery nach Sperrfrist."""
        adressen = self.ableiten(
            f"wsh(or_d(pk({K[0]}/<0;1>/*),"
            f"and_v(v:pkh({K[1]}/<0;1>/*),older(65535))))"
        )
        self.assertTrue(all(a.startswith("bc1q") for a in adressen))

    def test_liana_taproot_mit_recovery(self):
        adressen = self.ableiten(
            f"tr({K[0]}/<0;1>/*,{{and_v(v:pk({K[1]}/<0;1>/*),older(52560)),"
            f"multi_a(2,{K[2]}/<0;1>/*,{K[3]}/<0;1>/*)}})"
        )
        self.assertTrue(all(a.startswith("bc1p") for a in adressen))

    def test_drei_von_fuenf(self):
        schluessel = _testschluessel(5)
        kern = ",".join(f"{k}/<0;1>/*" for k in schluessel)
        self.assertTrue(self.ableiten(f"wsh(sortedmulti(3,{kern}))"))

    def test_musig_wird_nicht_erfunden(self):
        """
        Aggregierte Taproot-Schlüssel kann der Parser nicht. Lieber gar keine
        Adresse als eine falsche — auf eine falsche würde jemand einzahlen.
        """
        self.assertEqual(
            self.ableiten(f"tr(musig({K[0]},{K[1]})/<0;1>/*)"), set()
        )


class TestZweige(unittest.TestCase):

    def test_empfang_und_change_getrennt(self):
        adressen = main.derive_addresses(
            f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))", max_addresses=10
        )
        self.assertEqual(len(adressen), 10)

    def test_ein_zweig_liefert_keine_duplikate(self):
        """
        Ohne ``<0;1>`` gibt es nur eine Kette. embit lieferte für den zweiten
        Zweig stillschweigend dieselben Adressen noch einmal — die Ableitung
        darf das nicht als Change ausgeben.
        """
        adressen = main.derive_addresses(
            f"wsh(sortedmulti(2,{K[0]}/0/*,{K[1]}/0/*))", max_addresses=10
        )
        self.assertEqual(len(adressen), 10)

    def test_ohne_wildcard_genau_eine_adresse(self):
        adressen = main.derive_addresses(
            f"wsh(sortedmulti(2,{K[0]},{K[1]}))", max_addresses=50
        )
        self.assertEqual(len(adressen), 1)


class TestKurzform(unittest.TestCase):

    def test_wird_zum_deskriptor(self):
        desc = deskriptor_aus_kurzform(2, "wsh", [K[0], K[1], K[2]])
        self.assertTrue(desc.startswith("wsh(sortedmulti(2,"))
        self.assertIn("#", desc, "Die Prüfsumme fehlt.")

    def test_sh_wsh(self):
        desc = deskriptor_aus_kurzform(2, "sh-wsh", [K[0], K[1]])
        self.assertTrue(desc.startswith("sh(wsh(sortedmulti(2,"))

    def test_unbekannter_typ_wird_nicht_stillschweigend_wsh(self):
        """
        Wer „tr" schreibt, meint Taproot. Ein wortloses Ausweichen auf wsh
        ergäbe andere Adressen als erwartet — und die Wallet fände nichts.
        """
        self.assertEqual(deskriptor_aus_kurzform(2, "tr", [K[0], K[1]]), "")

    def test_eintrag_aus_kurzform_leitet_ab(self):
        eintrag = WalletEntry(
            name="Tresor", threshold=2, script_type="wsh", xpubs=[K[0], K[1]]
        )
        self.assertTrue(eintrag.is_multisig)
        self.assertTrue(eintrag.is_valid())
        self.assertTrue(main.derive_addresses(eintrag.analyse_schluessel,
                                              max_addresses=4))

    def test_taproot_kurzform_wird_als_fehler_gemeldet(self):
        eintrag = WalletEntry(
            name="T", threshold=2, script_type="tr", xpubs=[K[0], K[1]]
        )
        fehler, _ = validate_wallets([eintrag])
        self.assertTrue(any("WALLET_n_DESC" in f for f in fehler), fehler)


class TestEintrag(unittest.TestCase):

    def eintrag(self, descriptor: str) -> WalletEntry:
        return WalletEntry(name="T", descriptor=descriptor)

    def test_taproot_eintrag_ist_gueltig(self):
        e = self.eintrag(
            f"tr({K[0]}/<0;1>/*,multi_a(2,{K[1]}/<0;1>/*,{K[2]}/<0;1>/*))"
        )
        self.assertTrue(e.is_multisig)
        self.assertTrue(e.is_valid())
        self.assertEqual(e.threshold, 2)

    def test_liana_hat_kein_m_von_n(self):
        """
        Bei mehreren Ausgabepfaden gibt es kein „m von n". Eine Zahl zu
        erfinden wäre schlimmer als keine.
        """
        e = self.eintrag(
            f"wsh(or_d(pk({K[0]}/<0;1>/*),"
            f"and_v(v:pkh({K[1]}/<0;1>/*),older(65535))))"
        )
        self.assertTrue(e.is_valid())
        self.assertIsNone(e.threshold)

    def test_musig_eintrag_ist_ungueltig(self):
        e = self.eintrag(f"tr(musig({K[0]},{K[1]})/<0;1>/*)")
        self.assertFalse(e.is_valid())

    def test_kennung_folgt_den_adressen_nicht_dem_text(self):
        """
        Dieselben Cosigner in anderer Reihenfolge sind dieselbe Wallet — sie
        sollen denselben Cache behalten.
        """
        a = self.eintrag(f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))")
        b = self.eintrag(f"wsh(sortedmulti(2,{K[1]}/<0;1>/*,{K[0]}/<0;1>/*))")
        self.assertEqual(a.wallet_id(), b.wallet_id())

    def test_wsh_und_tr_teilen_sich_keinen_cache(self):
        """Gleiche Schlüssel, andere Adressen — also eine andere Wallet."""
        a = self.eintrag(f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))")
        b = self.eintrag(f"tr({K[0]}/<0;1>/*,multi_a(2,{K[1]}/<0;1>/*,{K[2]}/<0;1>/*))")
        self.assertNotEqual(a.wallet_id(), b.wallet_id())

    def test_analyse_schluessel_ist_der_deskriptor(self):
        e = self.eintrag(f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))")
        self.assertEqual(e.analyse_schluessel, e.descriptor)

    def test_single_sig_bleibt_beim_xpub(self):
        e = WalletEntry(xpub=BIP84_ZPUB, name="Einzeln")
        self.assertFalse(e.is_multisig)
        self.assertEqual(e.analyse_schluessel, BIP84_ZPUB)


class TestWalletContext(unittest.TestCase):
    """Multisig muss im Analyse-Stack ankommen — mit dem Wallet-Namen."""

    def test_adressen_werden_dem_wallet_zugeordnet(self):
        desc = f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))"
        ctx = main.build_wallet_context(
            [desc], wallet_names=["Tresor"], max_addresses_per_xpub=[6]
        )
        self.assertTrue(ctx.address_to_wallet)
        self.assertEqual(set(ctx.address_to_wallet.values()), {"Tresor"})

    def test_cosigner_gelten_nicht_als_eigene_wallets(self):
        """
        Die einzelnen Cosigner dürfen nie in den Stack — sie wären leere
        Wallets, und das sähe aus wie „kein Guthaben".
        """
        desc = f"wsh(sortedmulti(2,{K[0]}/<0;1>/*,{K[1]}/<0;1>/*))"
        ctx = main.build_wallet_context(
            [desc], wallet_names=["Tresor"], max_addresses_per_xpub=[6]
        )
        einzeln = main.derive_addresses(K[0], max_addresses=6)
        self.assertFalse(
            einzeln & set(ctx.address_to_wallet),
            "Eine Single-Sig-Adresse eines Cosigners wurde mitgeführt.",
        )


if __name__ == "__main__":
    unittest.main()
