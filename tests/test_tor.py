"""Lokaler Tor-Start ohne Browser-Fenster."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core import tor as tor_mod


class TestErkenneSocks(unittest.TestCase):

    def test_konfigurierter_port_gewinnt(self):
        with patch.object(tor_mod, "socks_erreichbar", side_effect=lambda h, p: p == 9150):
            self.assertEqual(
                tor_mod.erkenne_tor_socks(("127.0.0.1", 9150)),
                ("127.0.0.1", 9150),
            )

    def test_fallback_auf_browser_wenn_9050_tot(self):
        def _reach(host, port):
            return port == 9150

        with patch.object(tor_mod, "socks_erreichbar", side_effect=_reach):
            self.assertEqual(
                tor_mod.erkenne_tor_socks(("127.0.0.1", 9050)),
                ("127.0.0.1", 9150),
            )

    def test_nichts_da(self):
        with patch.object(tor_mod, "socks_erreichbar", return_value=False):
            self.assertIsNone(tor_mod.erkenne_tor_socks(("127.0.0.1", 9050)))


class TestBinarySuche(unittest.TestCase):

    def test_expliziter_pfad(self):
        hier = Path(__file__).resolve()
        self.assertEqual(tor_mod.finde_tor_binary(str(hier)), hier)

    def test_fehlender_expliziter_pfad_faellt_nicht_um(self):
        with patch.object(tor_mod.shutil, "which", return_value=None):
            with patch.object(tor_mod, "_kandidaten", return_value=[]):
                self.assertIsNone(tor_mod.finde_tor_binary(r"C:\gibt\es\nicht\tor.exe"))

    def test_name_erkennt_browser_nicht_utorrent(self):
        self.assertTrue(tor_mod._sieht_nach_tor_browser_aus("Tor Browser.app"))
        self.assertTrue(tor_mod._sieht_nach_tor_browser_aus("tor-browser"))
        self.assertTrue(tor_mod._sieht_nach_tor_browser_aus("tor-browser-macos-15.0.17"))
        self.assertFalse(tor_mod._sieht_nach_tor_browser_aus("qBittorrent.app"))
        self.assertFalse(tor_mod._sieht_nach_tor_browser_aus("uTorrent.app"))
        self.assertFalse(tor_mod._sieht_nach_tor_browser_aus("Anaconda-Navigator.app"))

    def test_unix_rel_enthaelt_macos_app_binary(self):
        app = Path("/Applications") / "Tor Browser.app"
        rels = tor_mod._unix_rel_tor(app)
        self.assertIn(app / "Contents" / "MacOS" / "Tor" / "tor", rels)

    def test_darwin_kandidaten_enthalten_applications(self):
        with patch.object(tor_mod.sys, "platform", "darwin"):
            texte = [str(p) for p in tor_mod._kandidaten()]
        erwartet = str(
            Path("/Applications") / "Tor Browser.app" / "Contents" / "MacOS" / "Tor" / "tor"
        )
        self.assertIn(erwartet, texte)

    def test_findet_kandidat_wenn_datei_existiert(self):
        hier = Path(__file__).resolve()
        with patch.object(tor_mod.shutil, "which", return_value=None):
            with patch.object(tor_mod, "_kandidaten", return_value=[hier]):
                self.assertEqual(tor_mod.finde_tor_binary(), hier)


class TestSocksCache(unittest.TestCase):

    def setUp(self):
        with tor_mod._socks_ok_lock:
            tor_mod._socks_ok_cache.clear()

    def test_cache_vermeidet_zweiten_log(self):
        logs: list[str] = []

        def log(t: str) -> None:
            logs.append(t)

        with patch.object(tor_mod, "erkenne_tor_socks", return_value=("127.0.0.1", 9050)):
            with patch.object(tor_mod, "socks_erreichbar", return_value=True):
                a = tor_mod.stelle_tor_socks_bereit(("127.0.0.1", 9050), log=log)
                b = tor_mod.stelle_tor_socks_bereit(("127.0.0.1", 9050), log=log)
        self.assertEqual(a, ("127.0.0.1", 9050))
        self.assertEqual(b, a)
        # Erster Aufruf loggt, zweiter (Cache) still.
        self.assertEqual(sum(1 for t in logs if "Prüfe Tor-SOCKS" in t), 1)
        self.assertEqual(sum(1 for t in logs if "erreichbar" in t), 1)


class TestAutostart(unittest.TestCase):

    def setUp(self):
        with tor_mod._socks_ok_lock:
            tor_mod._socks_ok_cache.clear()

    def test_standard_ist_an(self):
        self.assertTrue(tor_mod._autostart_erlaubt({}))
        self.assertTrue(tor_mod._autostart_erlaubt({"TOR_AUTOSTART": ""}))

    def test_aus(self):
        self.assertFalse(tor_mod._autostart_erlaubt({"TOR_AUTOSTART": "0"}))
        self.assertFalse(tor_mod._autostart_erlaubt({"TOR_AUTOSTART": "nein"}))

    def test_ohne_proxy_und_ohne_autostart_wirft(self):
        with patch.object(tor_mod, "erkenne_tor_socks", return_value=None):
            with self.assertRaises(tor_mod.TorFehler) as ctx:
                tor_mod.stelle_tor_socks_bereit(
                    ("127.0.0.1", 9050),
                    env={"TOR_AUTOSTART": "0"},
                )
        self.assertIn("Autostart aus", str(ctx.exception))

    def test_ohne_binary_wirft_hinweis(self):
        with patch.object(tor_mod, "erkenne_tor_socks", return_value=None):
            with patch.object(tor_mod, "finde_tor_binary", return_value=None):
                with self.assertRaises(tor_mod.TorFehler) as ctx:
                    tor_mod.stelle_tor_socks_bereit(("127.0.0.1", 9050), env={})
        self.assertIn("Kein Tor-Binary", str(ctx.exception))

    def test_log_prueft_socks_bevor_tor_startet(self):
        zeilen = []
        with patch.object(tor_mod, "erkenne_tor_socks", return_value=("127.0.0.1", 9050)):
            tor_mod.stelle_tor_socks_bereit(("127.0.0.1", 9050), log=zeilen.append)
        self.assertTrue(any("Prüfe Tor-SOCKS" in z for z in zeilen), zeilen)
        self.assertFalse(any("Starte Tor" in z for z in zeilen), zeilen)

    def test_log_sucht_binary_wenn_kein_socks(self):
        zeilen = []
        with patch.object(tor_mod, "erkenne_tor_socks", return_value=None):
            with patch.object(tor_mod, "finde_tor_binary", return_value=None):
                with self.assertRaises(tor_mod.TorFehler):
                    tor_mod.stelle_tor_socks_bereit(
                        ("127.0.0.1", 9050), env={}, log=zeilen.append,
                    )
        self.assertTrue(any("Prüfe Tor-SOCKS" in z for z in zeilen), zeilen)
        self.assertTrue(any("suche Binary" in z for z in zeilen), zeilen)
        self.assertFalse(any("Starte Tor" in z for z in zeilen), zeilen)


class TestKommando(unittest.TestCase):

    def test_socks_und_datadir(self):
        with patch.object(tor_mod, "_datenverzeichnis", return_value=Path("/tmp/tor_data")):
            cmd = tor_mod._tor_kommando(Path("/usr/bin/tor"), 9050)
        self.assertEqual(cmd[0], str(Path("/usr/bin/tor")))
        self.assertIn("--ignore-missing-torrc", cmd)
        self.assertIn("--ClientOnly", cmd)
        socks = cmd[cmd.index("--SocksPort") + 1]
        self.assertEqual(socks, "127.0.0.1:9050")
        self.assertIn(str(Path("/tmp/tor_data")), cmd)


class TestBootstrapStand(unittest.TestCase):

    def setUp(self):
        tor_mod._log_tail.clear()

    def test_prozent_aus_log(self):
        tor_mod._log_tail.extend([
            "Sep 17 Bootstrapped 0% (starting): Starting",
            "Sep 17 Bootstrapped 80% (reachable): Establishing a Tor circuit",
        ])
        self.assertEqual(tor_mod._bootstrap_prozent(), 80)
        self.assertFalse(tor_mod._bootstrap_fertig())
        tor_mod._log_tail.append(
            "Sep 17 Bootstrapped 100% (done): Done"
        )
        self.assertEqual(tor_mod._bootstrap_prozent(), 100)
        self.assertTrue(tor_mod._bootstrap_fertig())

    def test_starte_tor_wartet_auf_100(self):
        """SOCKS früh offen reicht nicht — erst Bootstrapped 100 %."""
        logs: list[str] = []
        fake = Mock()
        fake.poll.return_value = None
        fake.stdout = None
        fake.terminate = Mock()

        socks_calls = {"n": 0}
        bootstrap_seq = [0, 0, 50, 100]

        def fake_socks(_h, _p, timeout=2):
            socks_calls["n"] += 1
            return True

        def fake_prozent():
            if bootstrap_seq:
                return bootstrap_seq.pop(0)
            return 100

        with patch.object(tor_mod.subprocess, "Popen", return_value=fake):
            with patch.object(tor_mod, "socks_erreichbar", side_effect=fake_socks):
                with patch.object(tor_mod, "_bootstrap_prozent", side_effect=fake_prozent):
                    with patch.object(tor_mod.time, "sleep", return_value=None):
                        with patch.object(tor_mod, "_lese_stdout", return_value=None):
                            proc = tor_mod._starte_tor(
                                Path("/usr/bin/tor"), 9050, timeout=30,
                                log=logs.append,
                            )
        self.assertIs(proc, fake)
        self.assertTrue(any("100" in z or "Bootstrap" in z for z in logs), logs)
        self.assertGreaterEqual(socks_calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
