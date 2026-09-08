"""Terminal-Steuerung: Job-Log-Spiegel und Menü-Hilfen."""
from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import jobs as jobs_mod
from core.jobs import Job, JobRegistry, setze_log_spiegel
from core.terminal_steuerung import (
    FUSS_ZEILEN,
    Fussleiste,
    LogPuffer,
    StdoutTee,
    _job_kurzzeile,
    format_job_log_zeile,
    steuerung_sinnvoll,
)


class TestLogSpiegel(unittest.TestCase):
    def tearDown(self):
        setze_log_spiegel(None)

    def test_haenge_log_ruft_spiegel(self):
        gesehen: list[tuple[str, str]] = []

        def spiegel(job, text):
            gesehen.append((job.label, text))

        setze_log_spiegel(spiegel)
        job = Job(id="abc", kind="rescan", label="Cash+Carry")
        job._haenge_log_an("Verbinde mit der Datenquelle…")
        self.assertEqual(gesehen, [("Cash+Carry", "Verbinde mit der Datenquelle…")])
        self.assertEqual(job.as_dict()["log"], ["Verbinde mit der Datenquelle…"])

    def test_ersetze_log_spiegelt_neue_zeile(self):
        gesehen: list[str] = []
        setze_log_spiegel(lambda _j, t: gesehen.append(t))
        job = Job(id="x", kind="rescan", label="W")
        job._haenge_log_an("Filter 100 — hole Block…")
        job.ersetze_log_mit_praefix("Filter 100", "Filter 100 — +2 UTXO")
        self.assertEqual(gesehen[-1], "Filter 100 — +2 UTXO")
        self.assertEqual(job.as_dict()["log"], ["Filter 100 — +2 UTXO"])

    def test_spiegel_aus_nach_none(self):
        gesehen = []
        setze_log_spiegel(lambda _j, t: gesehen.append(t))
        setze_log_spiegel(None)
        Job(id="y", kind="t", label="L")._haenge_log_an("nix")
        self.assertEqual(gesehen, [])


class TestLogPufferUndTee(unittest.TestCase):
    def test_puffer_ring(self):
        p = LogPuffer(max_zeilen=3)
        for i in range(5):
            p.anhaengen(f"z{i}")
        self.assertEqual(p.letzte(10), ["z2", "z3", "z4"])

    def test_tee_puffert_zeilen(self):
        ziel = io.StringIO()
        puffer = LogPuffer()
        tee = StdoutTee(ziel, puffer)
        tee.write("Hallo\nWelt\n")
        tee.flush()
        self.assertEqual(ziel.getvalue(), "Hallo\nWelt\n")
        self.assertEqual(puffer.letzte(), ["Hallo", "Welt"])

    def test_format_job_log_zeile(self):
        job = SimpleNamespace(label="Test-Wallet", kind="verlauf")
        z = format_job_log_zeile(job, "Gap-Scan…")
        self.assertIn("Test-Wallet", z)
        self.assertIn("Gap-Scan…", z)
        self.assertIn(" · ", z)


class TestJobKurzzeile(unittest.TestCase):
    def test_auto_header_gekennzeichnet(self):
        job = Job(id="h", kind="headers", label="Block-Header ab SegWit")
        job.message = "Frage Header…"
        z = _job_kurzzeile(job)
        self.assertIn("headers", z)
        self.assertIn("[auto]", z)
        self.assertIn("Block-Header", z)

    def test_nutzer_scan_ohne_auto(self):
        job = Job(id="r", kind="rescan", label="UTXO-Scan A")
        z = _job_kurzzeile(job)
        self.assertIn("rescan", z)
        self.assertNotIn("[auto]", z)


class TestSteuerungSinnvoll(unittest.TestCase):
    def test_plain_console_aus(self):
        self.assertFalse(steuerung_sinnvoll(plain_console=True))

    def test_ohne_tty_aus(self):
        with patch("sys.stdin") as inp, patch("sys.stdout") as out:
            inp.isatty.return_value = False
            out.isatty.return_value = True
            self.assertFalse(steuerung_sinnvoll(plain_console=False))


class TestBeendenBestaetigung(unittest.TestCase):
    """3 + Enter darf die j-Nachfrage nicht sofort verwerfen."""

    def test_schleife_j_beendet_trotz_newline_nach_3(self):
        from core import terminal_steuerung as ts

        job = Job(id="s", kind="wallet_sync", label="Start-Sync")
        state = SimpleNamespace(
            jobs=SimpleNamespace(list=lambda: [job], get=lambda _i: job),
            entries=[],
            env_path=".",
            cache_dir=".",
            header_job_id=None,
            wallet_sync_job_id="s",
        )
        httpd = MagicMock()
        tasten = iter(["3", "\n", "j"])  # Enter nach 3, dann j

        def lese(_timeout=0.25):
            try:
                return next(tasten)
            except StopIteration:
                # Falls j nicht greift: Test hängt sonst ewig
                raise AssertionError("Schleife endete nicht nach j")

        puffer = LogPuffer()
        fuss = MagicMock()
        fuss.zeichnen = MagicMock()
        fuss.setze_hinweis = MagicMock()
        with patch.object(ts, "_lese_taste", side_effect=lese), patch.object(
            ts, "_drain_stdin"
        ), patch.object(ts, "_CbreakStdin") as cbreak:
            cbreak.return_value.__enter__ = lambda s: s
            cbreak.return_value.__exit__ = lambda *_a: None
            # _schleife_ansi wraps cbreak then calls tasten-loop
            code = ts._schleife_ansi(
                state, httpd, "http://127.0.0.1:8730/", puffer, fuss
            )
        self.assertEqual(code, 0)
        httpd.shutdown.assert_called()
        self.assertTrue(job.cancelled)


class TestFussleiste(unittest.TestCase):
    def test_fuss_zeilen_enthalten_menue(self):
        state = SimpleNamespace(
            jobs=SimpleNamespace(list=lambda: []),
            entries=[],
        )
        stream = io.StringIO()
        fuss = Fussleiste(stream, "http://127.0.0.1:8730/?t=x", state)
        zeilen = fuss._fuss_zeilen(2)
        self.assertEqual(len(zeilen), FUSS_ZEILEN)
        self.assertTrue(any("1 Status" in z for z in zeilen))
        self.assertTrue(any("Jobs: 2" in z for z in zeilen))
        self.assertTrue(any("8730" in z for z in zeilen))

    def test_fuss_zeilen_url_vor_menue_mit_doppelpunkt(self):
        """Vorletzte Zeile URL, letzte Zeile Menü mit ':' am Ende."""
        state = SimpleNamespace(
            jobs=SimpleNamespace(list=lambda: []),
            entries=[],
        )
        stream = io.StringIO()
        adresse = "http://127.0.0.1:8730/?t=x"
        fuss = Fussleiste(stream, adresse, state)
        zeilen = fuss._fuss_zeilen(0)
        self.assertEqual(len(zeilen), 3)
        self.assertIn("8730", zeilen[1])
        self.assertIn("1 Status", zeilen[2])
        self.assertTrue(zeilen[2].rstrip().endswith(":"))
        self.assertNotIn("1 Status", zeilen[1])

    def test_aktivieren_ohne_tty_scheitert(self):
        state = SimpleNamespace(jobs=SimpleNamespace(list=lambda: []), entries=[])
        stream = io.StringIO()  # kein TTY
        fuss = Fussleiste(stream, "http://127.0.0.1:8730/?t=x", state)
        self.assertFalse(fuss.aktivieren())


class TestMainCliFlag(unittest.TestCase):
    def test_plain_console_in_argumenten(self):
        import server

        p = server.build_argumente()
        args = p.parse_args(["--plain-console", "--no-browser"])
        self.assertTrue(args.plain_console)
        self.assertTrue(args.no_browser)


if __name__ == "__main__":
    unittest.main()
