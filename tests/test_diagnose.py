"""
Wallet-Diagnose.

Zwei Zusicherungen: Der Befund muss stimmen, und die Ausgabe darf keine
vollständigen Schlüssel enthalten — sie ist ausdrücklich zum Weitergeben
gedacht.
"""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import diagnose
import main
from tests.fixtures import BIP84_AS_XPUB, BIP84_ZPUB


def _konten_aus_einem_seed(anzahl=2, version=b"\x04\xb2\x47\x46"):
    from embit import bip32, bip39

    seed = bip39.mnemonic_to_seed(
        "abandon abandon abandon abandon abandon abandon abandon abandon "
        "abandon abandon abandon about"
    )
    wurzel = bip32.HDKey.from_seed(seed)
    return [
        wurzel.derive(f"m/84h/0h/{i}h").to_public().to_string(version=version)
        for i in range(anzahl)
    ]


class DiagnoseBasis(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.cache = self.dir / "cache"
        self.cache.mkdir()
        self.env = self.dir / ".env"

    def schreibe_env(self, xpubs, namen, typen=None):
        typen = typen or ["segwit"] * len(xpubs)
        self.env.write_text(
            f"XPUBS={' '.join(xpubs)}\n"
            f"WALLET_NAMES={'|'.join(namen)}\n"
            f"SCRIPT_TYPES={'|'.join(typen)}\n"
            f"MAX_ADDRESSES_PER_XPUB={'|'.join(['4'] * len(xpubs))}\n",
            encoding="utf-8",
        )

    def lauf(self):
        puffer = io.StringIO()
        with redirect_stdout(puffer):
            code = diagnose.diagnose(self.env, self.cache)
        return code, puffer.getvalue()


class TestVerschiedeneKonten(DiagnoseBasis):

    def setUp(self):
        super().setUp()
        self.konten = _konten_aus_einem_seed(2)
        self.schreibe_env(self.konten, ["Konto 0", "Konto 1"])

    def test_befund_eigenstaendig(self):
        code, text = self.lauf()
        self.assertEqual(code, 0)
        self.assertIn("alle Wallets sind eigenständig", text)

    def test_verschiedene_pruefsummen(self):
        _, text = self.lauf()
        pruefsummen = [
            z.split()[-1] for z in text.splitlines() if "Schlüssel-Prüfsumme" in z
        ]
        self.assertEqual(len(pruefsummen), 2)
        self.assertNotEqual(pruefsummen[0], pruefsummen[1])

    def test_verschiedene_erste_adressen(self):
        _, text = self.lauf()
        adressen = [
            z.split()[-1] for z in text.splitlines() if "Erste Adresse" in z
        ]
        self.assertEqual(len(adressen), 2)
        self.assertNotEqual(adressen[0], adressen[1])

    def test_verschiedene_cache_dateien(self):
        _, text = self.lauf()
        dateien = [z.split()[-1] for z in text.splitlines() if "Cache-Datei" in z]
        self.assertNotEqual(dateien[0], dateien[1])

    def test_meldet_fehlenden_cache(self):
        _, text = self.lauf()
        self.assertIn("noch nie gescannt", text)

    def test_zeigt_utxo_bestand(self):
        adresse = sorted(
            main.derive_addresses(self.konten[0], 4, script_type="segwit")
        )[0]
        main.save_xpub_utxo_cache(self.konten[0], [{
            "txid": "a" * 64, "vout": 0, "address": adresse, "value": 135_124_500,
            "status": {"confirmed": True, "block_height": 800_000,
                       "block_time": 1_700_000_000},
        }], self.cache, 4)

        _, text = self.lauf()
        self.assertIn("1 Stück, 135.124.500 sats", text)


class TestGleicherSchluessel(DiagnoseBasis):

    def setUp(self):
        super().setUp()
        self.schreibe_env(
            [BIP84_ZPUB, BIP84_AS_XPUB], ["Konto A", "Konto B"],
            ["auto", "segwit"],
        )

    def test_befund_gleiches_schluesselmaterial(self):
        _, text = self.lauf()
        self.assertIn("gleiches Schlüsselmaterial", text)
        self.assertIn("Konto A und Konto B", text)

    def test_gleiche_pruefsumme(self):
        _, text = self.lauf()
        pruefsummen = [
            z.split()[-1] for z in text.splitlines() if "Schlüssel-Prüfsumme" in z
        ]
        self.assertEqual(pruefsummen[0], pruefsummen[1])

    def test_erklaert_den_unterschied_zu_mehreren_konten(self):
        """Der Punkt, an dem die frühere Meldung in die Irre führte."""
        _, text = self.lauf()
        self.assertIn("Verschiedene Konten aus einem Seed", text)

    def test_nennt_beide_cache_dateien_getrennt(self):
        """Gleicher Schlüssel, aber verschiedene Strings — zwei Cache-Dateien."""
        _, text = self.lauf()
        dateien = [z.split()[-1] for z in text.splitlines() if "Cache-Datei" in z]
        self.assertNotEqual(dateien[0], dateien[1])


class TestDatenschutz(DiagnoseBasis):
    """Die Ausgabe ist zum Weitergeben gedacht."""

    def test_keine_vollstaendigen_xpubs(self):
        konten = _konten_aus_einem_seed(2)
        self.schreibe_env(konten, ["A", "B"])
        _, text = self.lauf()
        for xpub in konten:
            self.assertNotIn(xpub, text)
            self.assertNotIn(xpub[10:40], text)

    def test_pruefsumme_ist_gekuerzt(self):
        from core.config import schluessel_kennung

        self.schreibe_env([BIP84_ZPUB], ["A"])
        _, text = self.lauf()
        voll = schluessel_kennung(BIP84_ZPUB)
        self.assertNotIn(voll, text)
        self.assertIn(voll[:12], text)

    def test_hinweis_auf_weitergabe(self):
        self.schreibe_env([BIP84_ZPUB], ["A"])
        _, text = self.lauf()
        self.assertIn("weitergegeben werden", text)


class TestRandfaelle(DiagnoseBasis):

    def test_ohne_wallets(self):
        self.env.write_text("# leer\n", encoding="utf-8")
        code, text = self.lauf()
        self.assertEqual(code, 1)
        self.assertIn("Keine Wallets konfiguriert", text)

    def test_unbrauchbarer_xpub_bricht_nicht_ab(self):
        self.schreibe_env(["unsinn"], ["Kaputt"], ["auto"])
        code, text = self.lauf()
        self.assertEqual(code, 0)
        self.assertIn("nicht ableitbar", text)


if __name__ == "__main__":
    unittest.main()
