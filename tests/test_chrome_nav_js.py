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
        "function t(key, vars) {\n"
        "  const katalog = {\n"
        "    'wallet.historyScanShort': 'Historie…',\n"
        "    'wallet.navUtxoMany': '{n} UTXOs…',\n"
        "    'wallet.navUtxoOne': '1 UTXO…',\n"
        "    'wallet.utxoScanShort': 'Scan…',\n"
        "  };\n"
        "  let s = katalog[key] || key;\n"
        "  if (vars) {\n"
        "    for (const [k, v] of Object.entries(vars)) {\n"
        "      s = s.split('{' + k + '}').join(String(v ?? ''));\n"
        "    }\n"
        "  }\n"
        "  return s;\n"
        "}\n"
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

    def test_leere_bestaende_landen_im_dachboden(self):
        """Cache gelesen und 0 UTXOs → Dachboden. Unbekannt bleibt oben."""
        wallets = [
            {"id": "leer", "name": "Zeta", "has_cache": True, "utxo_count": 0},
            {"id": "voll", "name": "Alpha", "has_cache": True, "utxo_count": 2},
            {"id": "neu", "name": "Mitte", "has_cache": False, "utxo_count": 0},
            {"id": "historie", "name": "Beta", "has_cache": True, "utxo_count": 0},
        ]
        teile = _node(
            {"config": {"wallets": wallets}, "rescanJob": None},
            "teileWalletsFuerNav(Zustand.config.wallets)",
        )
        self.assertEqual([w["id"] for w in teile["oben"]], ["voll", "neu"])
        self.assertEqual([w["id"] for w in teile["dachboden"]], ["historie", "leer"])

    def test_scan_mit_fund_verlaesst_den_dachboden(self):
        wallets = [
            {"id": "scan", "name": "Scan", "has_cache": True, "utxo_count": 0},
        ]
        teile = _node(
            {
                "config": {"wallets": wallets},
                "rescanJob": {"id": "j"},
                "scanWalletId": "scan",
                "scanUtxoZahl": 3,
            },
            "teileWalletsFuerNav(Zustand.config.wallets)",
        )
        self.assertEqual([w["id"] for w in teile["oben"]], ["scan"])
        self.assertEqual(teile["dachboden"], [])

    def test_alle_scan_pille_je_wallet(self):
        """Sammelscan: Pille nach Stand je Wallet, nicht eine Zahl für alle."""
        wallets = [
            {"id": "a", "name": "Alpha", "has_cache": True, "utxo_count": 0},
            {"id": "b", "name": "Beta", "has_cache": True, "utxo_count": 4},
        ]
        zustand = {
            "config": {"wallets": wallets},
            "rescanJob": "job-1",
            "scanWalletId": "alle",
            "scanArt": "utxo",
            "scanUtxoZahl": 7,
            "scanUtxoJeWallet": {"a": 3, "b": 4},
        }
        texte = _node(
            zustand,
            "Zustand.config.wallets.map((w) => navScanMarkerText(w))",
        )
        self.assertEqual(texte, ["3 UTXOs…", "4 UTXOs…"])
        teile = _node(zustand, "teileWalletsFuerNav(Zustand.config.wallets)")
        self.assertEqual([w["id"] for w in teile["oben"]], ["a", "b"])
        self.assertEqual(teile["dachboden"], [])

    def test_alle_scan_ohne_live_zahl_nimmt_cache(self):
        wallet = {"id": "a", "name": "Alpha", "has_cache": True, "utxo_count": 2}
        text = _node(
            {
                "config": {"wallets": [wallet]},
                "rescanJob": "job-1",
                "scanWalletId": "alle",
                "scanArt": "utxo",
                "scanUtxoZahl": 9,
                "scanUtxoJeWallet": {},
            },
            "navScanMarkerText(Zustand.config.wallets[0])",
        )
        self.assertEqual(text, "2 UTXOs…")

    def test_alle_scan_leer_ist_scan_pille(self):
        wallet = {"id": "leer", "name": "Leer", "has_cache": True, "utxo_count": 0}
        text = _node(
            {
                "config": {"wallets": [wallet]},
                "rescanJob": "job-1",
                "scanWalletId": "alle",
                "scanArt": "utxo",
                "scanUtxoZahl": 5,
                "scanUtxoJeWallet": {"leer": 0},
            },
            "navScanMarkerText(Zustand.config.wallets[0])",
        )
        self.assertEqual(text, "Scan…")


class TestEinbindung(unittest.TestCase):

    def test_jobs_poll_nimmt_wallet_watch_log(self):
        self.assertIn("function nimmWalletWatchLog(", NAV)
        self.assertIn("nimmWalletWatchLog(daten)", NAV)
        self.assertIn("daten.wallet_watch.log", NAV)

    def test_jobs_takt_haengt_die_nav_ohne_reload_um(self):
        self.assertIn("function nimmWalletNavStaende(", NAV)
        self.assertIn("nimmWalletNavStaende(daten)", NAV)
        self.assertIn("daten.wallet_nav", NAV)
        self.assertIn("nimmScanUtxoJeWallet", NAV)
        self.assertIn("function navScanMarkerText(", NAV)

    def test_start_fragt_den_einstieg(self):
        start = CHROME.index("async function start()")
        rumpf = CHROME[start:]
        self.assertIn("einstiegsWalletId()", rumpf)
        self.assertNotIn("zeigeWallet(Zustand.config.wallets[0].id", rumpf)
        self.assertIn("meldeGuiBereit()", rumpf)
        self.assertLess(rumpf.index("zeigeWallet("), rumpf.index("meldeGuiBereit()"))


if __name__ == "__main__":
    unittest.main()
