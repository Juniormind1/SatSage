"""
Alter eines Wallets: wann eine seiner Adressen zum ersten Mal benutzt wurde.

Der UTXO-Cache kennt nur Unverbrauchtes und taugt dafür nicht — ein Wallet von
2019, das alles ausgegeben und 2026 neu befüllt wurde, sähe dort jung aus.
Maßgeblich ist deshalb die Transaktions-*Historie* der Adressen, und darin die
älteste bestätigte Transaktion.

Erhoben wird das einmalig: Die älteste Transaktion eines Wallets kann sich
nicht mehr ändern.
"""
import unittest

import fulcrum


class FakeClient:
    """
    Antwortet auf get_history und block.header aus vorgegebenen Daten.

    *historien* bildet Adresse → Liste von Historieneinträgen ab, wie sie ein
    Electrum-Server liefert: ``{"tx_hash": …, "height": …}``.
    """

    def __init__(self, historien: dict, zeiten: dict | None = None):
        self.historien = historien
        self.zeiten = zeiten or {}
        self.aufrufe: list[str] = []

    def request(self, method: str, params: list | None = None):
        self.aufrufe.append(method)
        if method == "blockchain.scripthash.get_history":
            for adresse, eintraege in self.historien.items():
                if fulcrum.address_to_scripthash(adresse) == params[0]:
                    return eintraege
            return []
        if method == "blockchain.block.header":
            hoehe = int(params[0])
            zeit = self.zeiten.get(hoehe)
            if zeit is None:
                return None
            # 80-Byte-Header; die Blockzeit steht in Byte 68..71 (little endian).
            roh = bytearray(80)
            roh[68:72] = int(zeit).to_bytes(4, "little")
            return roh.hex()
        raise AssertionError(f"Unerwarteter Aufruf: {method}")


A = "bc1qjqqrke2clt34nculph7v3mjndr6lagx2cjkp3v"
B = "bc1q8gmffzjl395m2xk6djp7ndsc3p7ezvh9r427aj"
C = "bc1qchpx38fyq7fkzyxsvzp6tsjc4y2rnhqcvfnpsx"


class TestAeltesteHoehe(unittest.TestCase):

    def test_ohne_adressen_kein_alter(self):
        client = FakeClient({})
        self.assertIsNone(fulcrum.first_seen_height_fulcrum(client, []))

    def test_unbenutzte_adressen_kein_alter(self):
        client = FakeClient({A: [], B: []})
        self.assertIsNone(fulcrum.first_seen_height_fulcrum(client, [A, B]))

    def test_eine_adresse(self):
        client = FakeClient({A: [{"tx_hash": "aa", "height": 800_000}]})
        self.assertEqual(fulcrum.first_seen_height_fulcrum(client, [A]), 800_000)

    def test_kleinste_hoehe_ueber_alle_adressen(self):
        """
        Das Wallet ist so alt wie seine älteste Transaktion — egal, auf welcher
        Adresse sie lag. Die erste Empfangsadresse muss nicht die erste
        benutzte sein.
        """
        client = FakeClient({
            A: [{"tx_hash": "aa", "height": 850_000}],
            B: [{"tx_hash": "bb", "height": 700_123}],
            C: [{"tx_hash": "cc", "height": 800_000}],
        })
        self.assertEqual(
            fulcrum.first_seen_height_fulcrum(client, [A, B, C]), 700_123
        )

    def test_mehrere_eintraege_je_adresse(self):
        client = FakeClient({
            A: [
                {"tx_hash": "aa", "height": 900_000},
                {"tx_hash": "bb", "height": 750_500},
                {"tx_hash": "cc", "height": 810_000},
            ],
        })
        self.assertEqual(fulcrum.first_seen_height_fulcrum(client, [A]), 750_500)

    def test_unbestaetigte_werden_uebergangen(self):
        """
        Electrum meldet unbestätigte Transaktionen mit Höhe 0 oder −1. Als
        „ältestes" gewertet ergäbe das ein Wallet-Alter von heute.
        """
        client = FakeClient({
            A: [{"tx_hash": "aa", "height": 0},
                {"tx_hash": "bb", "height": -1},
                {"tx_hash": "cc", "height": 820_000}],
        })
        self.assertEqual(fulcrum.first_seen_height_fulcrum(client, [A]), 820_000)

    def test_nur_unbestaetigte_ergeben_kein_alter(self):
        client = FakeClient({A: [{"tx_hash": "aa", "height": 0}]})
        self.assertIsNone(fulcrum.first_seen_height_fulcrum(client, [A]))

    def test_fehler_einer_adresse_stoppt_nicht(self):
        """Eine unerreichbare Adresse darf das Ergebnis nicht verhindern."""
        class Wackelig(FakeClient):
            def request(self, method, params=None):
                if method == "blockchain.scripthash.get_history" and \
                        params[0] == fulcrum.address_to_scripthash(A):
                    raise OSError("Verbindung weg")
                return super().request(method, params)

        client = Wackelig({A: [{"tx_hash": "aa", "height": 1}],
                           B: [{"tx_hash": "bb", "height": 770_000}]})
        self.assertEqual(
            fulcrum.first_seen_height_fulcrum(client, [A, B]), 770_000
        )

    def test_fortschritt_meldet_erste_und_letzte_adresse(self):
        """Sonst steht nach dem UTXO-Lauf minutenlang „Prüfe 101 von 101“."""
        client = FakeClient({
            A: [{"tx_hash": "aa", "height": 800_000}],
            B: [],
        })
        gesehen = []
        fulcrum.first_seen_height_fulcrum(
            client, [A, B], on_progress=gesehen.append
        )
        self.assertEqual(
            gesehen,
            [
                "Wallet-Alter: Adresse 1 von 2…",
                "Wallet-Alter: Adresse 2 von 2…",
            ],
        )


class TestAlsZeitpunkt(unittest.TestCase):
    """Höhe allein sagt niemandem etwas — gebraucht wird das Datum."""

    def setUp(self):
        # fulcrum hält Blockzeiten in einem Modul-Cache und liest sonst vom
        # Immutable-Cache der Platte. Beides muss hier draußen bleiben, sonst
        # sieht ein Test die Werte des vorigen — oder die des Benutzers.
        self._sicherung = dict(fulcrum._HEADER_TIME_CACHE)
        fulcrum._HEADER_TIME_CACHE.clear()
        self.addCleanup(self._wiederherstellen)

    def _wiederherstellen(self):
        fulcrum._HEADER_TIME_CACHE.clear()
        fulcrum._HEADER_TIME_CACHE.update(self._sicherung)

    def test_liefert_hoehe_und_zeit(self):
        client = FakeClient(
            {A: [{"tx_hash": "aa", "height": 800_000}]},
            zeiten={800_000: 1_690_000_000},
        )
        ergebnis = fulcrum.first_seen_fulcrum(client, [A])
        self.assertEqual(ergebnis["height"], 800_000)
        self.assertEqual(ergebnis["time_ts"], 1_690_000_000)

    def test_ohne_benutzte_adresse_nichts(self):
        client = FakeClient({A: []})
        self.assertIsNone(fulcrum.first_seen_fulcrum(client, [A]))

    def test_ohne_blockzeit_bleibt_die_hoehe(self):
        """
        Die Höhe ist der Befund, die Zeit nur ihre Übersetzung. Fällt der
        Header-Abruf aus, wird die Höhe trotzdem gemeldet — sonst ginge eine
        gesicherte Angabe wegen einer Nebensache verloren.

        Die Höhe hier ist absichtlich unrund: Ein glatter Wert stünde
        womöglich im Blockzeit-Cache des Benutzers und käme von dort zurück.
        """
        client = FakeClient({A: [{"tx_hash": "aa", "height": 799_997}]})
        ergebnis = fulcrum.first_seen_fulcrum(client, [A])
        self.assertEqual(ergebnis["height"], 799_997)
        self.assertIsNone(ergebnis["time_ts"])


class TestSpeicherung(unittest.TestCase):
    """Einmal erhoben, nie wieder — und ein Rescan darf es nicht verlieren."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from tests.fixtures import BIP84_ZPUB

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name)
        self.xpub = BIP84_ZPUB

    def test_ohne_angabe_bleibt_das_alter_unbekannt(self):
        import main

        main.save_xpub_utxo_cache(self.xpub, [], self.cache, "fulcrum")
        self.assertIsNone(main.xpub_first_seen(self.xpub, self.cache))

    def test_wird_gespeichert_und_gelesen(self):
        import main

        main.save_xpub_utxo_cache(
            self.xpub, [], self.cache, "fulcrum",
            first_seen={"height": 800_123, "time_ts": 1_690_000_000},
        )
        gelesen = main.xpub_first_seen(self.xpub, self.cache)
        self.assertEqual(gelesen["height"], 800_123)
        self.assertEqual(gelesen["time_ts"], 1_690_000_000)

    def test_alter_ueberlebt_das_loeschen_des_utxo_caches(self):
        import main

        main.save_xpub_utxo_cache(
            self.xpub, [], self.cache, "fulcrum",
            first_seen={"height": 800_123, "time_ts": 1_690_000_000},
        )
        main._xpub_cache_path(self.xpub, self.cache).unlink()
        gelesen = main.xpub_first_seen(self.xpub, self.cache)
        self.assertEqual(gelesen["height"], 800_123)
        self.assertTrue(main._xpub_alter_path(self.xpub, self.cache).is_file())

    def test_rescan_ohne_angabe_verliert_es_nicht(self):
        """
        Der zweite Aufruf übergibt kein first_seen — der gespeicherte Wert muss
        trotzdem stehen bleiben, sonst wäre er nach jedem Rescan weg.
        """
        import main

        main.save_xpub_utxo_cache(
            self.xpub, [], self.cache, "fulcrum",
            first_seen={"height": 800_123, "time_ts": 1_690_000_000},
        )
        main.save_xpub_utxo_cache(self.xpub, [], self.cache, "fulcrum")
        gelesen = main.xpub_first_seen(self.xpub, self.cache)
        self.assertEqual(gelesen["height"], 800_123)

    def test_vorhandenes_alter_loest_keine_erhebung_aus(self):
        import main

        main.save_xpub_utxo_cache(
            self.xpub, [], self.cache, "fulcrum",
            first_seen={"height": 800_123, "time_ts": 1_690_000_000},
        )
        client = FakeClient({A: [{"tx_hash": "aa", "height": 1}]})
        ergebnis = main.ermittle_first_seen(self.xpub, [A], self.cache, client)
        self.assertEqual(ergebnis["height"], 800_123)
        self.assertEqual(client.aufrufe, [], "Es darf nicht erneut gefragt werden.")

    def test_ohne_electrum_kein_alter_und_kein_fehler(self):
        """Esplora oder BIP-158: kein Client, also kein Alter — kein Absturz."""
        import main

        self.assertIsNone(
            main.ermittle_first_seen(self.xpub, [A], self.cache, None)
        )

    def test_ziel_scan_verliert_das_alter_nicht(self):
        """
        _mark_address_scanned baut seinen Cache-Payload selbst zusammen und
        umgeht save_xpub_utxo_cache. Ohne Übernahme fiel das Alter dort wieder
        heraus — erhoben wird es aber nur ein einziges Mal.
        """
        import main

        main.save_xpub_utxo_cache(
            self.xpub, [], self.cache, "fulcrum",
            first_seen={"height": 800_123, "time_ts": 1_690_000_000},
        )
        main._mark_address_scanned(self.xpub, A, self.cache, "fulcrum")
        gelesen = main.xpub_first_seen(self.xpub, self.cache)
        self.assertIsNotNone(gelesen, "Das Alter darf beim Ziel-Scan nicht wegfallen.")
        self.assertEqual(gelesen["height"], 800_123)
        self.assertEqual(gelesen["time_ts"], 1_690_000_000)

    def test_ziel_scan_ohne_vorheriges_alter(self):
        import main

        main.save_xpub_utxo_cache(self.xpub, [], self.cache, "fulcrum")
        main._mark_address_scanned(self.xpub, A, self.cache, "fulcrum")
        self.assertIsNone(main.xpub_first_seen(self.xpub, self.cache))

    def test_erhebung_beim_ersten_mal(self):
        import main

        client = FakeClient(
            {A: [{"tx_hash": "aa", "height": 770_000}]},
            zeiten={770_000: 1_650_000_000},
        )
        ergebnis = main.ermittle_first_seen(self.xpub, [A], self.cache, client)
        self.assertEqual(ergebnis["height"], 770_000)
        self.assertIn("blockchain.scripthash.get_history", client.aufrufe)

    def test_erhebung_kuendigt_sich_im_fortschritt_an(self):
        import main

        gesehen = []

        def fortschritt(text, *, sofort=False):
            gesehen.append((text, sofort))

        client = FakeClient({A: [{"tx_hash": "aa", "height": 770_000}]})
        main.ermittle_first_seen(
            self.xpub, [A], self.cache, client, on_progress=fortschritt
        )
        self.assertEqual(gesehen[0], ("Ermittle Wallet-Alter…", True))
        self.assertTrue(
            any(t.startswith("Wallet-Alter:") for t, _ in gesehen),
            gesehen,
        )


class TestUebersicht(unittest.TestCase):
    """Das Alter muss bis in die Oberfläche durchkommen."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from core.config import WalletEntry
        from tests.fixtures import BIP84_ZPUB

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name)
        self.entry = WalletEntry(xpub=BIP84_ZPUB, name="Testwallet")

    def zusammenfassung(self):
        from core.wallets import summarize

        return summarize([self.entry], self.cache)[0].as_dict()

    def test_ohne_erhebung_bleibt_es_leer(self):
        import main

        main.save_xpub_utxo_cache(self.entry.xpub, [], self.cache, "fulcrum")
        daten = self.zusammenfassung()
        self.assertIsNone(daten["first_seen_ts"])
        self.assertIsNone(daten["first_seen_height"])

    def test_wird_durchgereicht(self):
        import main

        main.save_xpub_utxo_cache(
            self.entry.xpub, [], self.cache, "fulcrum",
            first_seen={"height": 800_123, "time_ts": 1_690_000_000},
        )
        daten = self.zusammenfassung()
        self.assertEqual(daten["first_seen_height"], 800_123)
        self.assertEqual(daten["first_seen_ts"], 1_690_000_000)

    def test_ohne_cache_kein_absturz(self):
        daten = self.zusammenfassung()
        self.assertFalse(daten["has_cache"])
        self.assertIsNone(daten["first_seen_ts"])
        self.assertIsNone(daten["cache_mtime"])

    def test_cache_mtime_kommt_von_der_datei(self):
        import time
        import main

        main.save_xpub_utxo_cache(self.entry.xpub, [], self.cache, "fulcrum")
        daten = self.zusammenfassung()
        self.assertTrue(daten["has_cache"])
        self.assertIsNotNone(daten["cache_mtime"])
        self.assertLess(abs(daten["cache_mtime"] - time.time()), 10)


class TestBeschriftung(unittest.TestCase):

    def test_datum_wenn_blockzeit_bekannt(self):
        import main

        label = main._first_seen_label({"height": 800_000, "time_ts": 1_690_000_000})
        self.assertRegex(label, r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$")

    def test_hoehe_wenn_blockzeit_fehlt(self):
        import main

        self.assertEqual(
            main._first_seen_label({"height": 800_123, "time_ts": None}),
            "Block 800.123",
        )

    def test_ohne_angabe_unbekannt(self):
        import main

        self.assertEqual(main._first_seen_label(None), "unbekannt")


if __name__ == "__main__":
    unittest.main()
