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


def _node(zustand: dict, aufruf: str) -> object:
    skript = (
        "function uiSprache() { return 'de'; }\n"
        f"const Zustand = {json.dumps(zustand)};\n"
        + NAV
        + f"\nprocess.stdout.write(JSON.stringify({aufruf}));"
    )
    aus = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(aus.stdout)


def _einstieg(zustand: dict) -> object:
    return _node(zustand, "einstiegsWalletId()")


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

    def test_nav_sortiert_alphabetisch_ohne_config_umzubauen(self):
        """Anlege-Reihenfolge in der Config; Navigation A–Z, Umlaute nach DE."""
        wallets = [
            {"id": "z", "name": "Zeta"},
            {"id": "a", "name": "alpha"},
            {"id": "o", "name": "Österreich"},
            {"id": "b", "name": "Beta"},
            {"id": "a2", "name": "Alpha"},
        ]
        ids = _node(
            {"config": {"wallets": wallets}},
            "walletsFuerNav(Zustand.config.wallets).map((w) => w.id)",
        )
        self.assertEqual(ids, ["a", "a2", "b", "o", "z"])
        self.assertEqual(
            [w["id"] for w in wallets],
            ["z", "a", "o", "b", "a2"],
        )


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
