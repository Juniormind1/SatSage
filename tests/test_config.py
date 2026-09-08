"""
.env lesen und schreiben.

Diese Datei enthält beim Benutzer echte Node-Zugangsdaten. Die Tests arbeiten
deshalb ausschließlich in temporären Verzeichnissen — die echte .env wird
weder gelesen noch beschrieben.

Wichtigste Zusicherung: Ein Schreibvorgang aus der Oberfläche darf nichts
zerstören, was jemand von Hand eingetragen hat.
"""
import tempfile
import unittest
from pathlib import Path

import main
from core.config import (
    BestaetigungNoetig,
    EnvFile,
    WalletEntry,
    read_wallets,
    validate_wallets,
    wallet_updates,
    write_wallets,
)
from tests.fixtures import (
    BIP84_AS_XPUB,
    BIP84_RECEIVE_0,
    BIP84_ZPUB,
    ZWEITER_ALS_XPUB,
)

# Adressen aus 192.0.2.0/24 (RFC 5737, für Dokumentation reserviert) —
# damit in Testdaten nie das Heimnetz eines Benutzers landet.
BEISPIEL_ENV = """\
# Wallet (Default fuer --xpubs / --wallet-names ohne CLI)
# XPUBS=zpub6DeinXPUB zpub6ZweiterXPUB
XPUBS=zpub6AAA zpub6BBB
WALLET_NAMES=Erstes|Zweites

# Fulcrum / Electrum
FULCRUM_HOST=192.0.2.6
FULCRUM_PORT=50002
FULCRUM_SSL=false

# Bitcoin Core RPC
NODE_IP=192.0.2.100
RPCPASSWORD=geheim
"""


class EnvTestBasis(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.pfad = self.dir / ".env"
        self.pfad.write_text(BEISPIEL_ENV, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def neu_laden(self) -> EnvFile:
        return EnvFile.load(self.pfad)


class TestLesen(EnvTestBasis):

    def test_werte_werden_gelesen(self):
        env = self.neu_laden()
        self.assertEqual(env.get("FULCRUM_HOST"), "192.0.2.6")
        self.assertEqual(env.get("XPUBS"), "zpub6AAA zpub6BBB")

    def test_auskommentierte_zeilen_zaehlen_nicht(self):
        env = self.neu_laden()
        self.assertEqual(env.get("XPUBS"), "zpub6AAA zpub6BBB")
        self.assertNotIn("zpub6DeinXPUB", env.get("XPUBS"))

    def test_fehlender_schluessel_liefert_default(self):
        self.assertEqual(self.neu_laden().get("GIBTSNICHT", "x"), "x")

    def test_gleiche_auslegung_wie_das_cli(self):
        """core.config und main._load_dotenv dürfen nicht auseinanderlaufen."""
        self.assertEqual(self.neu_laden().values(), main._load_dotenv(self.pfad))


class TestStrukturErhalt(EnvTestBasis):

    def test_kommentare_ueberleben_einen_schreibvorgang(self):
        env = self.neu_laden()
        env.set("FULCRUM_SSL", "true")
        env.save()
        text = self.pfad.read_text(encoding="utf-8")
        self.assertIn("# Fulcrum / Electrum", text)
        self.assertIn("# XPUBS=zpub6DeinXPUB zpub6ZweiterXPUB", text)
        self.assertIn("# Bitcoin Core RPC", text)

    def test_fremde_schluessel_bleiben_unangetastet(self):
        env = self.neu_laden()
        env.set("XPUBS", "zpub6NEU")
        env.save()
        werte = self.neu_laden().values()
        self.assertEqual(werte["RPCPASSWORD"], "geheim")
        self.assertEqual(werte["NODE_IP"], "192.0.2.100")
        self.assertEqual(werte["FULCRUM_PORT"], "50002")

    def test_reihenfolge_bleibt_erhalten(self):
        vorher = [z for z in self.pfad.read_text().splitlines() if z.strip()]
        env = self.neu_laden()
        env.set("FULCRUM_PORT", "50001")
        env.save()
        nachher = [z for z in self.pfad.read_text().splitlines() if z.strip()]
        self.assertEqual(len(vorher), len(nachher))
        self.assertEqual(
            [z.split("=")[0] for z in vorher],
            [z.split("=")[0] for z in nachher],
        )

    def test_neuer_schluessel_wird_angehaengt(self):
        env = self.neu_laden()
        env.set("SCRIPT_TYPES", "segwit|auto")
        env.save()
        self.assertEqual(self.neu_laden().get("SCRIPT_TYPES"), "segwit|auto")
        self.assertIn("verwaltet", self.pfad.read_text())

    def test_wiederholtes_schreiben_haengt_nicht_doppelt_an(self):
        for wert in ("a", "b", "c"):
            env = self.neu_laden()
            env.set("SCRIPT_TYPES", wert)
            env.save()
        text = self.pfad.read_text()
        self.assertEqual(text.count("SCRIPT_TYPES="), 1)
        self.assertEqual(text.count("verwaltet"), 1)

    def test_unset_entfernt_den_schluessel(self):
        env = self.neu_laden()
        env.unset("RPCPASSWORD")
        env.save()
        self.assertNotIn("RPCPASSWORD", self.neu_laden().values())

    def test_sicherung_wird_angelegt(self):
        env = self.neu_laden()
        env.set("FULCRUM_PORT", "50001")
        sicherung = env.save()
        self.assertIsNotNone(sicherung)
        self.assertIn("FULCRUM_PORT=50002", sicherung.read_text())

    def test_keine_temporaere_datei_bleibt_liegen(self):
        env = self.neu_laden()
        env.set("FULCRUM_PORT", "50001")
        env.save()
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_datei_ohne_abschliessenden_umbruch(self):
        self.pfad.write_text("A=1", encoding="utf-8")
        env = self.neu_laden()
        env.set("B", "2")
        env.save()
        werte = self.neu_laden().values()
        self.assertEqual(werte["A"], "1")
        self.assertEqual(werte["B"], "2")

    def test_neue_datei_wird_angelegt(self):
        pfad = self.dir / "neu" / ".env"
        env = EnvFile.load(pfad)
        env.set("XPUBS", "zpub6AAA")
        self.assertIsNone(env.save())
        self.assertEqual(EnvFile.load(pfad).get("XPUBS"), "zpub6AAA")

    def test_verbindungsversuch_steht_vor_den_core_feldern(self):
        env = self.neu_laden()
        env.kommentar_vor(
            ("NODE_IP", "RPCPORT", "RPCUSER", "RPCPASSWORD"),
            "# Erfolgloser Verbindungsversuch am 19.08.2026 um 14:32",
        )
        text = "\n".join(env.lines)
        self.assertIn(
            "# Erfolgloser Verbindungsversuch am 19.08.2026 um 14:32\nNODE_IP=",
            text,
        )
        env.kommentar_vor(
            ("NODE_IP", "RPCPORT"),
            "# Erfolgreicher Verbindungsversuch am 19.08.2026 um 15:01",
        )
        text = "\n".join(env.lines)
        self.assertEqual(text.count("Verbindungsversuch"), 1)
        self.assertIn("Erfolgreicher Verbindungsversuch", text)
        self.assertNotIn("Erfolgloser Verbindungsversuch", text)


class TestWalletsLesen(EnvTestBasis):

    def test_namen_und_reihenfolge(self):
        wallets = read_wallets(self.neu_laden())
        self.assertEqual([w.xpub for w in wallets], ["zpub6AAA", "zpub6BBB"])
        self.assertEqual([w.name for w in wallets], ["Erstes", "Zweites"])

    def test_standardwerte_wenn_nichts_gesetzt_ist(self):
        wallets = read_wallets(self.neu_laden())
        self.assertEqual(wallets[0].script_type, "auto")
        self.assertEqual(wallets[0].max_addresses, main.DEFAULT_MAX_ADDRESSES)

    def test_skripttyp_und_tiefe_werden_uebernommen(self):
        env = self.neu_laden()
        env.set("SCRIPT_TYPES", "segwit|auto")
        env.set("MAX_ADDRESSES_PER_XPUB", "80|200")
        env.save()
        wallets = read_wallets(self.neu_laden())
        self.assertEqual(wallets[0].script_type, "segwit")
        self.assertEqual(wallets[0].max_addresses, 80)
        self.assertEqual(wallets[1].max_addresses, 200)

    def test_indizierte_schreibweise(self):
        pfad = self.dir / "indiziert.env"
        pfad.write_text(
            "XPUB_0=zpub6AAA\nXPUB_1=zpub6BBB\n"
            "WALLET_NAME_0=Kalt\nSCRIPT_TYPE_0=segwit\n",
            encoding="utf-8",
        )
        wallets = read_wallets(EnvFile.load(pfad))
        self.assertEqual(len(wallets), 2)
        self.assertEqual(wallets[0].name, "Kalt")
        self.assertEqual(wallets[0].script_type, "segwit")

    def test_leere_env_ergibt_keine_wallets(self):
        pfad = self.dir / "leer.env"
        pfad.write_text("# nichts\n", encoding="utf-8")
        self.assertEqual(read_wallets(EnvFile.load(pfad)), [])


class TestWalletsSchreiben(EnvTestBasis):

    def eintraege(self):
        return [
            WalletEntry(BIP84_ZPUB, "Cold Storage", "auto", 50),
            WalletEntry(ZWEITER_ALS_XPUB, "Ledger Alt", "segwit", 80),
        ]

    def test_rundlauf(self):
        env = self.neu_laden()
        write_wallets(env, self.eintraege())
        wieder = read_wallets(self.neu_laden())
        self.assertEqual([w.name for w in wieder], ["Cold Storage", "Ledger Alt"])
        self.assertEqual([w.script_type for w in wieder], ["auto", "segwit"])
        self.assertEqual([w.max_addresses for w in wieder], [50, 80])

    def test_zugangsdaten_bleiben_erhalten(self):
        env = self.neu_laden()
        write_wallets(env, self.eintraege())
        self.assertEqual(self.neu_laden().get("RPCPASSWORD"), "geheim")

    def test_indizierte_reste_werden_entfernt(self):
        """Sonst stünden XPUBS und XPUB_0 nebeneinander und widersprächen sich."""
        env = self.neu_laden()
        env.set("XPUB_0", "zpub6ALT")
        env.set("WALLET_NAME_0", "Alt")
        env.save()

        write_wallets(self.neu_laden(), self.eintraege())
        werte = self.neu_laden().values()
        self.assertNotIn("XPUB_0", werte)
        self.assertNotIn("WALLET_NAME_0", werte)

    def test_leere_liste_raeumt_auf(self):
        write_wallets(self.neu_laden(), [])
        werte = self.neu_laden().values()
        self.assertNotIn("XPUBS", werte)
        self.assertEqual(werte.get("RPCPASSWORD"), "geheim")

    def test_das_cli_liest_das_geschriebene(self):
        """
        Abnahme: was die Oberfläche schreibt, muss die CLI verstehen.

        Beide gehen über dieselbe Quelle — main.wallets_aus_env_datei liest
        das Blockformat. Die alten _*_from_env kennen es nicht mehr; genau
        deshalb darf der Startpfad sie nicht mehr allein benutzen.
        """
        write_wallets(self.neu_laden(), self.eintraege())
        gelesen = main.wallets_aus_env_datei(self.pfad)
        self.assertEqual(
            [e.xpub for e in gelesen], [BIP84_ZPUB, ZWEITER_ALS_XPUB]
        )
        self.assertEqual(
            [e.display_name for e in gelesen], ["Cold Storage", "Ledger Alt"]
        )
        self.assertEqual([e.script_type for e in gelesen], ["auto", "segwit"])
        self.assertEqual([e.max_addresses for e in gelesen], [50, 80])


class TestPruefung(unittest.TestCase):

    def test_gueltige_liste(self):
        self.assertEqual(
            validate_wallets([WalletEntry(BIP84_ZPUB, "Kalt")]), ([], [])
        )

    def test_unbrauchbarer_xpub(self):
        fehler, _ = validate_wallets([WalletEntry("kein-xpub", "Kaputt")])
        self.assertTrue(any("gültiger" in f for f in fehler))

    def test_derselbe_xpub_zweimal_ist_ein_fehler(self):
        fehler, _ = validate_wallets([
            WalletEntry(BIP84_ZPUB, "A"),
            WalletEntry(BIP84_ZPUB, "B"),
        ])
        self.assertTrue(any("bereits in der Liste" in f for f in fehler))

    def test_doppelter_name(self):
        fehler, _ = validate_wallets([
            WalletEntry(BIP84_ZPUB, "Gleich"),
            WalletEntry(ZWEITER_ALS_XPUB, "Gleich"),
        ])
        self.assertTrue(any("mehrfach vergeben" in f for f in fehler))

    def test_schreiben_wird_bei_fehlern_abgelehnt(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / ".env"
            pfad.write_text("A=1\n", encoding="utf-8")
            env = EnvFile.load(pfad)
            with self.assertRaises(ValueError):
                write_wallets(env, [WalletEntry("unsinn", "X")])
            self.assertEqual(pfad.read_text(), "A=1\n", "Datei wurde trotzdem verändert")


class TestMehrereKontenAusEinemSeed(unittest.TestCase):
    """
    Der wichtigste Fall aus der Praxis: Wer mehrere Konten aus einem Seed
    führt (m/84'/0'/0', m/84'/0'/1' …), muss sie alle eintragen können. Diese
    Konten haben unterschiedliche Schlüssel und dürfen nie beanstandet werden.
    """

    def setUp(self):
        from embit import bip32, bip39

        seed = bip39.mnemonic_to_seed(
            "abandon abandon abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon about"
        )
        wurzel = bip32.HDKey.from_seed(seed)
        self.konten = [
            wurzel.derive(pfad).to_public().to_string(version=b"\x04\x88\xb2\x1e")
            for pfad in ("m/84h/0h/0h", "m/84h/0h/1h", "m/84h/0h/2h")
        ]

    def test_konten_haben_verschiedene_kennungen(self):
        from core.config import schluessel_kennung

        kennungen = {schluessel_kennung(x) for x in self.konten}
        self.assertEqual(len(kennungen), len(self.konten))

    def test_mehrere_konten_werden_ohne_beanstandung_akzeptiert(self):
        eintraege = [
            WalletEntry(xpub, f"Konto {i}", "segwit")
            for i, xpub in enumerate(self.konten)
        ]
        fehler, warnungen = validate_wallets(eintraege)
        self.assertEqual(fehler, [], "Konten aus einem Seed wurden abgelehnt")
        self.assertEqual(warnungen, [], "Konten aus einem Seed wurden bemängelt")

    def test_verschiedene_ableitungsarten_ebenfalls(self):
        from embit import bip32, bip39

        seed = bip39.mnemonic_to_seed(
            "abandon abandon abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon about"
        )
        wurzel = bip32.HDKey.from_seed(seed)
        eintraege = [
            WalletEntry(
                wurzel.derive(pfad).to_public().to_string(version=b"\x04\x88\xb2\x1e"),
                name, typ,
            )
            for pfad, name, typ in (
                ("m/84h/0h/0h", "SegWit", "segwit"),
                ("m/49h/0h/0h", "Nested", "nested"),
                ("m/44h/0h/0h", "Legacy", "legacy"),
            )
        ]
        fehler, warnungen = validate_wallets(eintraege)
        self.assertEqual(fehler, [])
        self.assertEqual(warnungen, [])


class TestGleicherSchluesselZweiFassungen(unittest.TestCase):
    """
    Dasselbe Konto einmal als zpub und einmal als xpub. Beide leiten dieselben
    Adressen ab; Beträge würden doppelt gezählt. Das ist eine Warnung, kein
    Fehler — die Abwägung gehört dem Benutzer.
    """

    def eintraege(self):
        return [
            WalletEntry(BIP84_ZPUB, "Cold Storage"),
            WalletEntry(BIP84_AS_XPUB, "Ledger Alt", "segwit"),
        ]

    def test_wird_als_warnung_gemeldet_nicht_als_fehler(self):
        fehler, warnungen = validate_wallets(self.eintraege())
        self.assertEqual(fehler, [])
        self.assertEqual(len(warnungen), 1)

    def test_warnung_nennt_beide_wallets_beim_namen(self):
        _, warnungen = validate_wallets(self.eintraege())
        self.assertIn("Cold Storage", warnungen[0])
        self.assertIn("Ledger Alt", warnungen[0])

    def test_warnung_nennt_die_gemeinsame_adresse(self):
        """Damit sich von Hand nachsehen lässt, ob es dasselbe Konto ist."""
        _, warnungen = validate_wallets(self.eintraege())
        self.assertIn(BIP84_RECEIVE_0, warnungen[0])

    def test_warnung_grenzt_gegen_mehrere_konten_ab(self):
        """
        Wer mehrere Konten aus einem Seed führt, soll nicht glauben, das sei
        gemeint.
        """
        _, warnungen = validate_wallets(self.eintraege())
        self.assertIn("Seed", warnungen[0])

    def test_warnung_nennt_die_folge(self):
        _, warnungen = validate_wallets(self.eintraege())
        self.assertIn("doppelt", warnungen[0])

    def test_speichern_ohne_bestaetigung_wird_abgelehnt(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / ".env"
            pfad.write_text("A=1\n", encoding="utf-8")
            with self.assertRaises(BestaetigungNoetig):
                write_wallets(EnvFile.load(pfad), self.eintraege())
            self.assertEqual(pfad.read_text(), "A=1\n")

    def test_mit_bestaetigung_wird_gespeichert(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / ".env"
            pfad.write_text("A=1\n", encoding="utf-8")
            write_wallets(EnvFile.load(pfad), self.eintraege(), bestaetigt=True)
            werte = EnvFile.load(pfad).values()
            geschrieben = {werte["WALLET_0_XPUB"], werte["WALLET_1_XPUB"]}
            self.assertEqual(geschrieben, {BIP84_ZPUB, BIP84_AS_XPUB})

    def test_ausnahme_traegt_die_warnungen_mit(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / ".env"
            pfad.write_text("A=1\n", encoding="utf-8")
            try:
                write_wallets(EnvFile.load(pfad), self.eintraege())
                self.fail("keine Ausnahme")
            except BestaetigungNoetig as exc:
                self.assertEqual(len(exc.warnungen), 1)
                self.assertIn("Cold Storage", exc.warnungen[0])

    def test_kennung_ist_prefix_unabhaengig(self):
        from core.config import schluessel_kennung

        self.assertEqual(
            schluessel_kennung(BIP84_ZPUB), schluessel_kennung(BIP84_AS_XPUB)
        )


class TestMaskierung(unittest.TestCase):

    def test_xpub_wird_gekuerzt(self):
        maskiert = WalletEntry(BIP84_ZPUB, "Kalt").masked_xpub()
        self.assertTrue(maskiert.startswith("zpub6r"))
        self.assertIn("…", maskiert)
        self.assertLess(len(maskiert), 20)
        self.assertNotIn(BIP84_ZPUB[20:40], maskiert)

    def test_anzeigename_faellt_auf_hash_zurueck(self):
        eintrag = WalletEntry(BIP84_ZPUB, "")
        self.assertEqual(eintrag.display_name, main._default_wallet_name(BIP84_ZPUB))


if __name__ == "__main__":
    unittest.main()
