"""
Wallet-Blöcke in der .env: WALLET_0_NAME, WALLET_0_XPUB, …

Die alte Schreibweise legte alles in Sammelzeilen ab — XPUBS, WALLET_NAMES,
SCRIPT_TYPES parallel und positionsgebunden. Ein Name mit Leerzeichen, ein
fehlender Eintrag in einer der Zeilen, und die Zuordnung verschob sich still.

Das neue Format hält zusammen, was zusammengehört, und macht Platz für
Multisig im selben Namensraum. Gelesen wird beides: Eine bestehende .env läuft
ohne Zutun weiter und wird beim nächsten Speichern überführt.
"""
import tempfile
import unittest
from pathlib import Path

import main
from core.config import (
    EnvFile,
    WalletEntry,
    bloecke_nach_luecke,
    erste_empfangsadresse,
    read_wallets,
    validate_wallets,
    wallet_updates,
    write_wallets,
)
from tests.fixtures import BIP84_ZPUB, ZWEITER_ALS_XPUB

#: Drei gültige Schlüssel für Multisig-Tests.
COSIGNER = [BIP84_ZPUB, ZWEITER_ALS_XPUB]


class EnvBasis(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pfad = Path(self._tmp.name) / ".env"

    def schreibe(self, text: str) -> EnvFile:
        self.pfad.write_text(text, encoding="utf-8")
        return EnvFile.load(self.pfad)

    def neu_laden(self) -> EnvFile:
        return EnvFile.load(self.pfad)


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------


class TestLegacyLesen(EnvBasis):
    """Bestehende Konfigurationen müssen ohne Migration weiterlaufen."""

    def test_sammelzeile_wird_gelesen(self):
        env = self.schreibe(
            f"XPUBS={BIP84_ZPUB} {ZWEITER_ALS_XPUB}\n"
            "WALLET_NAMES=Wasabi|Ledger\n"
            "SCRIPT_TYPES=segwit|auto\n"
            "MAX_ADDRESSES_PER_XPUB=50|80\n"
        )
        wallets = read_wallets(env)
        self.assertEqual([w.xpub for w in wallets], [BIP84_ZPUB, ZWEITER_ALS_XPUB])
        self.assertEqual([w.name for w in wallets], ["Wasabi", "Ledger"])
        self.assertEqual([w.script_type for w in wallets], ["segwit", "auto"])
        self.assertEqual([w.max_addresses for w in wallets], [50, 80])

    def test_indizierte_schreibweise_wird_gelesen(self):
        env = self.schreibe(
            f"XPUB_0={BIP84_ZPUB}\n"
            "WALLET_NAME_0=Erstes\n"
            "SCRIPT_TYPE_0=segwit\n"
            f"XPUB_1={ZWEITER_ALS_XPUB}\n"
            "WALLET_NAME_1=Zweites\n"
        )
        wallets = read_wallets(env)
        self.assertEqual([w.xpub for w in wallets], [BIP84_ZPUB, ZWEITER_ALS_XPUB])
        self.assertEqual([w.name for w in wallets], ["Erstes", "Zweites"])


class TestBloeckeLesen(EnvBasis):

    def test_einfacher_block(self):
        env = self.schreibe(
            "WALLET_0_NAME=Mein Wallet mit Leerzeichen\n"
            f"WALLET_0_XPUB={BIP84_ZPUB}\n"
            "WALLET_0_SCRIPT=segwit\n"
            "WALLET_0_MAX_ADDRESSES=120\n"
        )
        wallets = read_wallets(env)
        self.assertEqual(len(wallets), 1)
        self.assertEqual(wallets[0].name, "Mein Wallet mit Leerzeichen")
        self.assertEqual(wallets[0].xpub, BIP84_ZPUB)
        self.assertEqual(wallets[0].script_type, "segwit")
        self.assertEqual(wallets[0].max_addresses, 120)
        self.assertFalse(wallets[0].is_multisig)

    def test_bloecke_verdraengen_die_alten_zeilen(self):
        """
        Stehen beide Schreibweisen in der Datei, gilt allein die neue. Sonst
        widersprächen sich zwei Wahrheiten in derselben Datei.
        """
        env = self.schreibe(
            f"XPUBS={ZWEITER_ALS_XPUB}\n"
            "WALLET_NAMES=Alt\n"
            "WALLET_0_NAME=Neu\n"
            f"WALLET_0_XPUB={BIP84_ZPUB}\n"
        )
        wallets = read_wallets(env)
        self.assertEqual([w.name for w in wallets], ["Neu"])
        self.assertEqual([w.xpub for w in wallets], [BIP84_ZPUB])

    def test_luecke_beendet_die_liste(self):
        env = self.schreibe(
            f"WALLET_0_XPUB={BIP84_ZPUB}\n"
            "WALLET_0_NAME=Erstes\n"
            f"WALLET_2_XPUB={ZWEITER_ALS_XPUB}\n"
            "WALLET_2_NAME=Drittes\n"
        )
        wallets = read_wallets(env)
        self.assertEqual([w.name for w in wallets], ["Erstes"])

    def test_uebersprungene_bloecke_sind_abfragbar(self):
        """
        Die Lücke darf nicht still bleiben — sonst fehlt ein Wallet und
        niemand erfährt davon.
        """
        env = self.schreibe(
            f"WALLET_0_XPUB={BIP84_ZPUB}\n"
            f"WALLET_2_XPUB={ZWEITER_ALS_XPUB}\n"
            f"WALLET_5_XPUB={BIP84_ZPUB}\n"
        )
        self.assertEqual(bloecke_nach_luecke(env.values()), [2, 5])

    def test_hohe_nummern_ohne_luecke_werden_gelesen(self):
        """Kein `range(20)`: Auch eine lange Liste muss vollständig ankommen."""
        zeilen = [
            f"WALLET_{n}_XPUB={BIP84_ZPUB if n % 2 == 0 else ZWEITER_ALS_XPUB}"
            for n in range(30)
        ]
        env = self.schreibe("\n".join(zeilen) + "\n")
        self.assertEqual(len(read_wallets(env)), 30)

    def test_standardtiefe_greift(self):
        env = self.schreibe(
            f"WALLET_0_XPUB={BIP84_ZPUB}\nMAX_ADDRESSES=64\n"
        )
        self.assertEqual(read_wallets(env)[0].max_addresses, 64)


class TestMultisigLesen(EnvBasis):

    def test_felder(self):
        env = self.schreibe(
            "WALLET_0_NAME=Tresor\n"
            "WALLET_0_M=2\n"
            "WALLET_0_SCRIPT=wsh\n"
            f"WALLET_0_XPUBS={COSIGNER[0]} {COSIGNER[1]}\n"
            "WALLET_0_MAX_ADDRESSES=50\n"
        )
        wallet = read_wallets(env)[0]
        self.assertTrue(wallet.is_multisig)
        self.assertEqual(wallet.threshold, 2)
        self.assertEqual(wallet.script_type, "wsh")
        self.assertEqual(wallet.xpubs, COSIGNER)
        self.assertEqual(wallet.cosigner_count, 2)

    def test_deskriptor_liefert_schluessel_und_schwelle(self):
        env = self.schreibe(
            "WALLET_0_NAME=Tresor\n"
            f"WALLET_0_DESC=wsh(sortedmulti(2,[ab12cd34/48h/0h/0h/2h]{COSIGNER[0]}/<0;1>/*,"
            f"[ef56ab78/48h/0h/0h/2h]{COSIGNER[1]}/<0;1>/*))#pqrs\n"
        )
        wallet = read_wallets(env)[0]
        self.assertTrue(wallet.is_multisig)
        self.assertEqual(wallet.threshold, 2)
        self.assertEqual(wallet.script_type, "wsh")
        self.assertEqual(wallet.xpubs, COSIGNER)

    def test_deskriptor_mit_pruefsumme_bleibt_vollstaendig(self):
        """Das `#checksum` gehört zum Wert — der Parser darf es nicht abschneiden."""
        desc = f"wsh(sortedmulti(1,{COSIGNER[0]}))#abcdefgh"
        env = self.schreibe(f"WALLET_0_NAME=T\nWALLET_0_DESC={desc}\n")
        self.assertEqual(read_wallets(env)[0].descriptor, desc)

    def test_sh_wsh_wird_erkannt(self):
        env = self.schreibe(
            "WALLET_0_NAME=T\n"
            f"WALLET_0_DESC=sh(wsh(sortedmulti(1,{COSIGNER[0]})))\n"
        )
        self.assertEqual(read_wallets(env)[0].script_type, "sh-wsh")

    def test_keine_empfangsadresse(self):
        """
        Die Adresse ergibt sich aus allen Cosignern zusammen. Die eines
        einzelnen zu zeigen wäre falsch — dort läge das Geld bei ihm allein.
        """
        wallet = WalletEntry(name="T", xpubs=COSIGNER, threshold=2, script_type="wsh")
        self.assertEqual(erste_empfangsadresse(wallet), "")

    def test_kennung_haengt_nicht_an_der_reihenfolge(self):
        a = WalletEntry(name="T", xpubs=[COSIGNER[0], COSIGNER[1]], threshold=2,
                        script_type="wsh")
        b = WalletEntry(name="T", xpubs=[COSIGNER[1], COSIGNER[0]], threshold=2,
                        script_type="wsh")
        self.assertEqual(a.wallet_id(), b.wallet_id())

    def test_kennung_unterscheidet_sich_vom_cosigner(self):
        multisig = WalletEntry(name="T", xpubs=COSIGNER, threshold=2, script_type="wsh")
        einzeln = WalletEntry(xpub=COSIGNER[0])
        self.assertNotEqual(multisig.wallet_id(), einzeln.wallet_id())


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------


class TestSchreiben(EnvBasis):

    def eintraege(self):
        return [
            WalletEntry(xpub=BIP84_ZPUB, name="Cold Storage", max_addresses=50),
            WalletEntry(xpub=ZWEITER_ALS_XPUB, name="Ledger Alt",
                        script_type="segwit", max_addresses=80),
        ]

    def test_schreibt_bloecke(self):
        self.schreibe("RPCPASSWORD=geheim\n")
        write_wallets(self.neu_laden(), self.eintraege())
        werte = self.neu_laden().values()
        self.assertEqual(werte["WALLET_0_NAME"], "Cold Storage")
        self.assertEqual(werte["WALLET_0_XPUB"], BIP84_ZPUB)
        self.assertEqual(werte["WALLET_1_NAME"], "Ledger Alt")
        self.assertEqual(werte["WALLET_1_SCRIPT"], "segwit")
        self.assertEqual(werte["WALLET_1_MAX_ADDRESSES"], "80")

    def test_alte_zeilen_verschwinden(self):
        self.schreibe(
            f"XPUBS={BIP84_ZPUB}\nWALLET_NAMES=Alt\nSCRIPT_TYPES=auto\n"
            "MAX_ADDRESSES_PER_XPUB=50\n"
        )
        write_wallets(self.neu_laden(), self.eintraege())
        werte = self.neu_laden().values()
        for key in ("XPUBS", "WALLET_NAMES", "SCRIPT_TYPES",
                    "MAX_ADDRESSES_PER_XPUB"):
            self.assertNotIn(key, werte)

    def test_alte_indizes_verschwinden_auch_jenseits_von_20(self):
        """
        Ein `range(20)` ließe XPUB_23 stehen — beim nächsten Lesen stünden
        zwei Wahrheiten in der Datei.
        """
        self.schreibe(
            f"XPUB_0={BIP84_ZPUB}\nXPUB_23={ZWEITER_ALS_XPUB}\n"
            "WALLET_NAME_23=Uralt\nSCRIPT_TYPE_23=segwit\n"
        )
        write_wallets(self.neu_laden(), self.eintraege())
        werte = self.neu_laden().values()
        for key in ("XPUB_0", "XPUB_23", "WALLET_NAME_23", "SCRIPT_TYPE_23"):
            self.assertNotIn(key, werte)

    def test_kuerzere_liste_laesst_keine_leichen(self):
        self.schreibe("")
        write_wallets(self.neu_laden(), self.eintraege())
        write_wallets(self.neu_laden(), self.eintraege()[:1])
        werte = self.neu_laden().values()
        self.assertIn("WALLET_0_XPUB", werte)
        self.assertNotIn("WALLET_1_XPUB", werte)
        self.assertNotIn("WALLET_1_NAME", werte)

    def test_rundlauf(self):
        self.schreibe("")
        write_wallets(self.neu_laden(), self.eintraege())
        gelesen = read_wallets(self.neu_laden())
        self.assertEqual([w.xpub for w in gelesen], [BIP84_ZPUB, ZWEITER_ALS_XPUB])
        self.assertEqual([w.name for w in gelesen], ["Cold Storage", "Ledger Alt"])
        self.assertEqual([w.script_type for w in gelesen], ["auto", "segwit"])
        self.assertEqual([w.max_addresses for w in gelesen], [50, 80])

    def test_kommentare_und_fremde_schluessel_ueberleben(self):
        self.schreibe(
            "# Meine Notiz\n"
            "RPCPASSWORD=geheim\n"
            f"XPUBS={BIP84_ZPUB}\n"
            "FULCRUM_HOST=192.168.1.50\n"
        )
        write_wallets(self.neu_laden(), self.eintraege())
        text = self.pfad.read_text(encoding="utf-8")
        self.assertIn("# Meine Notiz", text)
        werte = self.neu_laden().values()
        self.assertEqual(werte["RPCPASSWORD"], "geheim")
        self.assertEqual(werte["FULCRUM_HOST"], "192.168.1.50")

    def test_multisig_rundlauf(self):
        self.schreibe("")
        multisig = WalletEntry(name="Tresor", xpubs=COSIGNER, threshold=2,
                               script_type="wsh", max_addresses=60)
        write_wallets(self.neu_laden(), [multisig])
        werte = self.neu_laden().values()
        # Gespeichert wird der Deskriptor — die Kurzform kann Taproot und
        # Miniscript nicht ausdrücken, zwei Darstellungen wären zwei Wahrheiten.
        desc = werte["WALLET_0_DESC"]
        self.assertTrue(desc.startswith("wsh(sortedmulti(2,"), desc[:40])
        for cosigner in COSIGNER:
            self.assertIn(cosigner, desc)
        self.assertNotIn("WALLET_0_M", werte)
        self.assertNotIn("WALLET_0_XPUBS", werte)
        self.assertNotIn("WALLET_0_XPUB", werte)

        gelesen = read_wallets(self.neu_laden())[0]
        self.assertTrue(gelesen.is_multisig)
        self.assertEqual(gelesen.threshold, 2)
        self.assertEqual(gelesen.xpubs, COSIGNER)
        self.assertEqual(gelesen.max_addresses, 60)

    def test_deskriptor_rundlauf(self):
        self.schreibe("")
        desc = f"wsh(sortedmulti(1,{COSIGNER[0]}))#abcdefgh"
        write_wallets(self.neu_laden(), [WalletEntry(name="T", descriptor=desc)])
        werte = self.neu_laden().values()
        self.assertEqual(werte["WALLET_0_DESC"], desc)
        self.assertEqual(read_wallets(self.neu_laden())[0].descriptor, desc)

    def test_leere_liste_raeumt_auf(self):
        self.schreibe(f"XPUBS={BIP84_ZPUB}\nRPCPASSWORD=geheim\n")
        write_wallets(self.neu_laden(), [])
        werte = self.neu_laden().values()
        self.assertNotIn("XPUBS", werte)
        self.assertNotIn("WALLET_0_XPUB", werte)
        self.assertEqual(werte["RPCPASSWORD"], "geheim")

    def test_updates_ohne_bestand_raeumen_die_sammelzeilen(self):
        """wallet_updates ohne .env-Werte kennt zumindest die festen Namen."""
        updates = wallet_updates([])
        for key in ("XPUBS", "WALLET_NAMES", "SCRIPT_TYPES",
                    "MAX_ADDRESSES_PER_XPUB"):
            self.assertIsNone(updates[key])


# ---------------------------------------------------------------------------
# CLI-Pfad
# ---------------------------------------------------------------------------


class TestCliSicht(EnvBasis):
    """Was die Oberfläche schreibt, muss die CLI sehen — und umgekehrt."""

    def test_cli_liest_bloecke(self):
        self.schreibe("")
        write_wallets(
            self.neu_laden(),
            [WalletEntry(xpub=BIP84_ZPUB, name="Eins", script_type="segwit")],
        )
        wallets = main.wallets_aus_env_datei(self.pfad)
        self.assertEqual([w.xpub for w in wallets], [BIP84_ZPUB])
        self.assertEqual([w.display_name for w in wallets], ["Eins"])

    def test_multisig_geht_ueber_den_deskriptor_in_die_analyse(self):
        """
        Die Wallet wird analysiert — aber als Ganzes, über ihren Deskriptor.
        Die einzelnen Cosigner dürfen nie als eigene Einträge auftauchen: Sie
        wären leere Wallets, und das sähe aus wie „kein Guthaben".
        """
        self.schreibe(
            "WALLET_0_NAME=Tresor\n"
            "WALLET_0_M=2\n"
            "WALLET_0_SCRIPT=wsh\n"
            f"WALLET_0_XPUBS={COSIGNER[0]} {COSIGNER[1]}\n"
        )
        wallets = main.wallets_aus_env_datei(self.pfad)
        schluessel = [w.analyse_schluessel for w in wallets]
        self.assertEqual(len(schluessel), 1)
        self.assertIn("sortedmulti", schluessel[0])
        for cosigner in COSIGNER:
            self.assertNotIn(cosigner, schluessel)
        self.assertTrue(main.derive_addresses(schluessel[0], max_addresses=4))


# ---------------------------------------------------------------------------
# Prüfung
# ---------------------------------------------------------------------------


class TestPruefung(unittest.TestCase):

    def test_schwelle_groesser_als_cosigner(self):
        fehler, _ = validate_wallets([
            WalletEntry(name="T", xpubs=COSIGNER, threshold=4, script_type="wsh")
        ])
        self.assertTrue(any("nicht möglich" in f for f in fehler))

    def test_fehlende_schwelle(self):
        fehler, _ = validate_wallets([
            WalletEntry(name="T", xpubs=COSIGNER, script_type="wsh")
        ])
        self.assertTrue(any("WALLET_n_M" in f for f in fehler))

    def test_unbekannter_multisig_skripttyp(self):
        fehler, _ = validate_wallets([
            WalletEntry(name="T", xpubs=COSIGNER, threshold=2, script_type="tr")
        ])
        self.assertTrue(any("Skripttyp" in f for f in fehler))

    def test_cosigner_zusaetzlich_als_einzelwallet(self):
        """Sonst zählten seine Beträge doppelt — einzeln und als Teil der Multisig."""
        fehler, _ = validate_wallets([
            WalletEntry(xpub=COSIGNER[0], name="Einzeln"),
            WalletEntry(name="Tresor", xpubs=COSIGNER, threshold=2,
                        script_type="wsh"),
        ])
        self.assertTrue(any("doppelt" in f for f in fehler), fehler)

    def test_doppelte_namen(self):
        fehler, _ = validate_wallets([
            WalletEntry(xpub=BIP84_ZPUB, name="Gleich"),
            WalletEntry(xpub=ZWEITER_ALS_XPUB, name="Gleich"),
        ])
        self.assertTrue(any("mehrfach vergeben" in f for f in fehler))

    def test_gueltige_multisig_ohne_fehler(self):
        fehler, _ = validate_wallets([
            WalletEntry(name="T", xpubs=COSIGNER, threshold=2, script_type="wsh")
        ])
        self.assertEqual(fehler, [])


if __name__ == "__main__":
    unittest.main()
