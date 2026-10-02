"""Einstieg nach /api/config (web/chrome_nav.js) — Node-Stub plus Einbindung in start()."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
NAV = (WEB / "chrome_nav.js").read_text(encoding="utf-8")
CHROME = (WEB / "chrome.js").read_text(encoding="utf-8")


def _einstieg(zustand: dict) -> object:
    skript = (
        f"const Zustand = {json.dumps(zustand)};\n"
        + NAV
        + "\nprocess.stdout.write(JSON.stringify(einstiegsWalletId()));"
    )
    aus = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(aus.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestEinstiegsWallet(unittest.TestCase):

    WALLETS = {"wallets": [{"id": "a", "name": "Alpha"}, {"id": "b", "name": "Beta"}]}

    def test_ohne_wahl_das_erste(self):
        self.assertEqual(_einstieg({"config": self.WALLETS, "walletId": None}), "a")

    def test_angeklicktes_wallet_bleibt(self):
        """Klick während der Vorbereitung: der Start holt nicht zum ersten zurück."""
        self.assertIsNone(_einstieg({"config": self.WALLETS, "walletId": "b"}))

    def test_unbekannte_wahl_zaehlt_nicht(self):
        self.assertEqual(_einstieg({"config": self.WALLETS, "walletId": "weg"}), "a")

    def test_ohne_wallets_nichts(self):
        self.assertIsNone(_einstieg({"config": {"wallets": []}, "walletId": None}))


class TestEinbindung(unittest.TestCase):

    def test_jobs_poll_nimmt_wallet_watch_log(self):
        self.assertIn("function nimmWalletWatchLog(", NAV)
        self.assertIn("nimmWalletWatchLog(daten)", NAV)
        self.assertIn("daten.wallet_watch.log", NAV)

    def test_start_fragt_den_einstieg(self):
        start = CHROME.index("async function start()")
        rumpf = CHROME[start:]
        self.assertIn("einstiegsWalletId()", rumpf)
        self.assertNotIn("zeigeWallet(Zustand.config.wallets[0].id", rumpf)
        self.assertIn("meldeGuiBereit()", rumpf)
        self.assertLess(rumpf.index("zeigeWallet("), rumpf.index("meldeGuiBereit()"))


if __name__ == "__main__":
    unittest.main()
