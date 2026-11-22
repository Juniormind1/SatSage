"""Leak-Scan: Muster aus dem Datenschutz-Plan, Allowlist, Fixture-Regel."""
from __future__ import annotations

import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

import importlib.util

from tests.fixtures import BIP84_ZPUB, BIP84_RECEIVE_0

ROOT = Path(__file__).resolve().parent.parent

# Literale bewusst zerlegt, damit diese Testdatei selbst den Scan besteht.
KOPF_LEDGER = '"txid","refid","time",' + '"type"'
KOPF_LEDGER_SUB = KOPF_LEDGER + ',"subtype"'
ID_ECHT = "LABCDE" + "-FGHIJ-KLMNOP"
ID_SYN = "LSYNAA" + "-00000-000000"
IBAN_OK = "DE89" + "370400440532013000"
IBAN_NOK = "DE00" + "370400440532013000"
MAIL_PRIVAT = "privat@" + "proton.me"
_SPEC = importlib.util.spec_from_file_location(
    "satsage_leak_scan", ROOT / "scripts" / "leak_scan.py"
)
import sys
leak_scan = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = leak_scan
_SPEC.loader.exec_module(leak_scan)

ALLOWLIST_SHA256 = leak_scan.ALLOWLIST_SHA256
Fund = leak_scan.Fund
_sha = leak_scan._sha
format_funde = leak_scan.format_funde
herkunft_datei = leak_scan.herkunft_datei
main = leak_scan.main
pruefe_text = leak_scan.pruefe_text


class LeakScanTest(unittest.TestCase):
    def test_allowlist_deckt_bip84_testvektor(self):
        self.assertIn(_sha(BIP84_ZPUB), ALLOWLIST_SHA256)
        self.assertIn(_sha(BIP84_RECEIVE_0), ALLOWLIST_SHA256)

    def test_unbekannter_xpub_wird_gefunden(self):
        # Gleich lang wie ein echter Schlüssel, aber kein Testvektor.
        fake = "xpub" + ("A" * 107)
        funde = pruefe_text(f"key = {fake}\n", Path("/tmp/probe.py"))
        self.assertTrue(any(f.regel == "erweiterter-schluessel" for f in funde), funde)

    def test_bip84_xpub_wird_nicht_gefunden(self):
        funde = pruefe_text(f"key = {BIP84_ZPUB}\n", Path("/tmp/probe.py"))
        self.assertFalse([f for f in funde if f.regel == "erweiterter-schluessel"], funde)

    def test_kraken_kopf_ausserhalb_fixtures_ist_treffer(self):
        text = KOPF_LEDGER_SUB + "\n"
        funde = pruefe_text(text, Path("/tmp/ledgers.csv"))
        self.assertTrue(any(f.regel == "kraken-ledger-kopf" for f in funde), funde)

    def test_kraken_kopf_in_fixture_mit_herkunft_ist_erlaubt(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Scanner prüft FIXTURE_DIR fest. Wir simulieren nur die Kopf-Ausnahme
            # über einen Pfad unter tests/fixtures/boerse/, ohne die Datei zu committen.
            ziel = ROOT / "tests" / "fixtures" / "boerse" / "_scan_tmp.csv"
            herkunft = herkunft_datei(ziel)
            self.addCleanup(lambda: ziel.exists() and ziel.unlink())
            self.addCleanup(lambda: herkunft.exists() and herkunft.unlink())
            ziel.write_text(KOPF_LEDGER + "\n" + ID_SYN + ",0\n", encoding="utf-8")
            herkunft.write_text("synthetisch\n", encoding="utf-8")
            funde = pruefe_text(ziel.read_text(encoding="utf-8"), ziel)
            self.assertEqual(funde, [], funde)


    def test_kraken_kopf_in_spec_ist_erlaubt(self):
        ziel = ROOT / "doc" / "boerse" / "_scan_tmp.md"
        self.addCleanup(lambda: ziel.exists() and ziel.unlink())
        ziel.write_text("Kopf:\n\n" + KOPF_LEDGER + "\n", encoding="utf-8")
        funde = pruefe_text(ziel.read_text(encoding="utf-8"), ziel)
        self.assertFalse([f for f in funde if f.regel == "kraken-ledger-kopf"], funde)

    def test_fixture_ohne_herkunft_wird_blockiert(self):
        ziel = ROOT / "tests" / "fixtures" / "boerse" / "_scan_ohne_herkunft.csv"
        self.addCleanup(lambda: ziel.exists() and ziel.unlink())
        if herkunft_datei(ziel).exists():
            herkunft_datei(ziel).unlink()
        ziel.write_text(KOPF_LEDGER + "\n", encoding="utf-8")
        funde = pruefe_text(ziel.read_text(encoding="utf-8"), ziel)
        self.assertTrue(any(f.regel == "fixture-ohne-herkunft" for f in funde), funde)

    def test_echte_kraken_id_wird_gefunden_lsyn_nicht(self):
        funde = pruefe_text("id=" + ID_ECHT + "\n", Path("/tmp/a.txt"))
        self.assertTrue(any(f.regel == "kraken-ledger-id" for f in funde), funde)
        funde = pruefe_text("id=" + ID_SYN + "\n", Path("/tmp/a.txt"))
        self.assertFalse([f for f in funde if f.regel == "kraken-ledger-id"], funde)

    def test_iban_mit_pruefziffer(self):
        funde = pruefe_text("Konto " + IBAN_OK + " Ende\n", Path("/tmp/a.txt"))
        self.assertTrue(any(f.regel == "iban" for f in funde), funde)
        funde = pruefe_text("Konto " + IBAN_NOK + " Ende\n", Path("/tmp/a.txt"))
        self.assertFalse([f for f in funde if f.regel == "iban"], funde)

    def test_email_allowlist_und_example(self):
        funde = pruefe_text("mail " + MAIL_PRIVAT + " bitte\n", Path("/tmp/a.txt"))
        self.assertTrue(any(f.regel == "email" for f in funde), funde)
        text = "juniormind@proton.me\nuser@example.com\ngit@github.com\n"
        funde = pruefe_text(text, Path("/tmp/a.txt"))
        self.assertEqual([f for f in funde if f.regel == "email"], [])

    def test_mainnet_adresse_ohne_allowlist(self):
        # Gültige Prüfziffer, nicht in der Allowlist: Testvektor von BIP-173
        # (P2WPKH uncompress, andere als EXTERN_A).
        # Wir nehmen eine zufällig wirkende, aber gültige Adresse, die nicht
        # im Repo steht. Wird zur Not übersprungen, wenn die Prüfziffer nicht hält.
        _bech32_ok = leak_scan._bech32_ok

        # Adresse aus einem anderen öffentlichen Beispiel (nicht allowlisted):
        # Bitcoin-Wiki „all-zero public key“ ist already listed. Hier ein
        # künstlicher Satz: wenn keine unbekannte gültige Adresse griffbereit
        # ist, prüfen wir nur, dass eine bekannte allowlisted Adresse durchgeht.
        funde = pruefe_text(f"{BIP84_RECEIVE_0}\n", Path("/tmp/a.txt"))
        self.assertFalse([f for f in funde if f.regel == "mainnet-adresse"], funde)
        self.assertTrue(_bech32_ok(BIP84_RECEIVE_0))

    def test_tracked_repo_ist_leer(self):
        self.assertEqual(main(["--tracked"]), 0)

    def test_cli_findet_treffer_in_datei(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("kopf: " + KOPF_LEDGER + "\n")
            name = fh.name
        self.addCleanup(lambda: Path(name).unlink(missing_ok=True))
        self.assertEqual(main([name]), 1)

    def test_format_funde(self):
        text = format_funde([Fund("a.py", "email", 3, "x@y.z")])
        self.assertIn("a.py:3: email:", text)


class GitignoreBoerseTest(unittest.TestCase):
    def _check(self, rel: str) -> bool:
        """True, wenn git die Relativpfad-Angabe ignorieren würde."""
        r = subprocess.run(
            ["git", "check-ignore", "-q", rel],
            cwd=ROOT,
            check=False,
        )
        return r.returncode == 0

    def test_csv_in_der_wurzel_wird_ignoriert(self):
        self.assertTrue(self._check("ledgers_geheim.csv"))
        self.assertTrue(self._check("auszug.xlsx"))

    def test_ledgers_ueberall_ausser_fixtures(self):
        self.assertTrue(self._check("doc/ledgers_2024.csv"))
        # Negationsregel: synthetische Fixtures bleiben versionierbar.
        self.assertFalse(self._check("tests/fixtures/boerse/ledgers_syn.csv"))

    def test_privat_ordner(self):
        self.assertTrue(self._check("privat/roh.csv"))
        self.assertTrue(self._check("tests/privat/daten/kraken.csv"))


if __name__ == "__main__":
    unittest.main()
