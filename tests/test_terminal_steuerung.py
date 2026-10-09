"""Terminal-Steuerung: Job-Log-Spiegel und Menü-Hilfen."""
from __future__ import annotations

import io
import time
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
    _ausgabe_ist_stumm,
    _job_kurzzeile,
    _loese_terminal_fuss,
    _reset_hartes_prozessende_fuer_tests,
    _stdout_nach_ende,
    format_job_log_zeile,
    httpd_stopp_ohne_join,
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

    def tearDown(self):
        _reset_hartes_prozessende_fuer_tests()

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
        ), patch.object(ts, "_CbreakStdin") as cbreak, patch(
            "core.outbound_policy.stoppe_oeffentliche_electrum_suche",
        ) as stoppe, patch.object(ts, "plane_hartes_prozessende"):
            cbreak.return_value.__enter__ = lambda s: s
            cbreak.return_value.__exit__ = lambda *_a: None
            # _schleife_ansi wraps cbreak then calls tasten-loop
            code = ts._schleife_ansi(
                state, httpd, "http://127.0.0.1:8730/", puffer, fuss
            )
        self.assertEqual(code, 0)
        httpd.shutdown.assert_called()
        stoppe.assert_called_with(prozess_ende=True)
        self.assertTrue(job.cancelled)

    def test_beende_server_kehrt_zurueck_wenn_shutdown_haengt(self):
        from core import terminal_steuerung as ts

        state = SimpleNamespace(
            jobs=SimpleNamespace(list=lambda: []),
            entries=[],
        )
        httpd = MagicMock()
        httpd.shutdown.side_effect = lambda: time.sleep(30)

        with patch.object(ts, "plane_hartes_prozessende"):
            t0 = time.monotonic()
            ts._beende_server(state, httpd)
            dauer = time.monotonic() - t0
        self.assertLess(dauer, 3.0)
        httpd.server_close.assert_called()


class TestHartesProzessende(unittest.TestCase):
    def tearDown(self):
        _reset_hartes_prozessende_fuer_tests()

    def test_atexit_ruft_kein_os_exit(self):
        from core import terminal_steuerung as ts

        with patch.object(ts.os, "_exit") as hart:
            ts._hartes_ende_atexit()
        hart.assert_not_called()

    def test_plane_unterdrueckt_executor_join(self):
        import concurrent.futures.thread as ft
        import threading
        from core import terminal_steuerung as ts

        ts._reset_hartes_prozessende_fuer_tests()

        class _Merk:  # weakrefbar, im Gegensatz zu object()
            pass

        dummy = _Merk()
        ft._threads_queues[dummy] = None
        with patch("core.terminal_steuerung.atexit.unregister") as unreg, patch(
            "core.terminal_steuerung.atexit.register",
        ) as reg:
            ts.plane_hartes_prozessende()
        unreg.assert_called_with(ft._python_exit)
        reg.assert_called_with(ts._hartes_ende_atexit)
        self.assertEqual(len(ft._threads_queues), 0)
        atexits = getattr(threading, "_threading_atexits", [])
        for cb in atexits:
            for cell in getattr(cb, "__closure__", None) or ():
                self.assertIsNot(cell.cell_contents, ft._python_exit)


class TestHttpdStoppOhneJoin(unittest.TestCase):
    def test_timeout_wenn_shutdown_blockiert(self):
        httpd = MagicMock()
        httpd.shutdown.side_effect = lambda: time.sleep(30)
        t0 = time.monotonic()
        httpd_stopp_ohne_join(httpd, timeout_s=0.2)
        self.assertLess(time.monotonic() - t0, 2.0)
        httpd.server_close.assert_called()


class TestFussleiste(unittest.TestCase):
    def tearDown(self):
        _loese_terminal_fuss()
        _reset_hartes_prozessende_fuer_tests()

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

    def test_deaktivieren_loescht_fuss_und_scrollregion(self):
        state = SimpleNamespace(jobs=SimpleNamespace(list=lambda: []), entries=[])
        stream = io.StringIO()
        fuss = Fussleiste(stream, "http://127.0.0.1:8730/?t=x", state)
        fuss._aktiv = True
        fuss.deaktivieren()
        text = stream.getvalue()
        self.assertIn("\033[1;", text)
        self.assertIn("r", text)
        self.assertIn("\033[2K", text)
        self.assertIn("\033[?25h", text)
        self.assertFalse(fuss._aktiv)
        stream.truncate(0)
        stream.seek(0)
        fuss.zeichnen(erzwingen=True)
        self.assertEqual(stream.getvalue(), "")

    def test_log_nach_deaktivieren_ohne_esc_restore(self):
        state = SimpleNamespace(jobs=SimpleNamespace(list=lambda: []), entries=[])
        stream = io.StringIO()
        fuss = Fussleiste(stream, "http://127.0.0.1:8730/?t=x", state)
        fuss._aktiv = True
        fuss._cursor_auf_menue = True
        fuss.deaktivieren()
        stream.truncate(0)
        stream.seek(0)
        fuss.schreibe_log_text("spaete zeile\n")
        self.assertEqual(stream.getvalue(), "spaete zeile\n")
        self.assertNotIn("\033[u", stream.getvalue())

    def test_reset_bytes_volle_scrollregion(self):
        from core.terminal_steuerung import _ansi_reset_bytes

        roh = _ansi_reset_bytes(24).decode("ascii")
        self.assertTrue(roh.startswith("\033[s\033[1;24r"), roh)
        self.assertIn("\033[?25h", roh)
        self.assertTrue(roh.endswith("\033[u"))
        self.assertNotIn("\033[?1049l", roh)
        self.assertNotIn("\033[24;1H\n", roh)

    def test_beende_server_loest_fuss_vor_weiterem_log(self):
        from core import terminal_steuerung as ts

        state = SimpleNamespace(
            jobs=SimpleNamespace(list=lambda: []),
            entries=[],
        )
        stream = io.StringIO()
        fuss = Fussleiste(stream, "http://127.0.0.1:8730/?t=x", state)
        fuss._aktiv = True
        tee = StdoutTee(stream, LogPuffer())
        tee.setze_fussleiste(fuss)
        tee.setze_nach_zeile(lambda: fuss.zeichnen(erzwingen=True))
        ts._aktive_fussleiste = fuss
        ts._aktive_tees = (tee,)
        httpd = MagicMock()
        with patch.object(ts, "plane_hartes_prozessende"):
            ts._beende_server(state, httpd)
        self.assertFalse(fuss._aktiv)
        self.assertIsNone(ts._aktive_fussleiste)
        self.assertIsNone(tee._fuss)
        self.assertIsNone(tee._nach_zeile)
        self.assertTrue(_ausgabe_ist_stumm())

    def test_beende_server_verschluckt_spaete_clearnet_probe_zeile(self):
        """Taste 3: „…9050) — erreichbar“ darf die Konsole nicht mehr treffen."""
        from core import terminal_steuerung as ts

        state = SimpleNamespace(
            jobs=SimpleNamespace(list=lambda: []),
            entries=[],
        )
        stream = io.StringIO()
        fuss = Fussleiste(stream, "http://127.0.0.1:8730/?t=x", state)
        fuss._aktiv = True
        tee = StdoutTee(stream, LogPuffer())
        tee.setze_fussleiste(fuss)
        ts._aktive_fussleiste = fuss
        ts._aktive_tees = (tee,)
        httpd = MagicMock()
        with patch.object(ts, "plane_hartes_prozessende"):
            ts._beende_server(state, httpd)
        stream.truncate(0)
        stream.seek(0)
        tee.write(
            "  → [0] öffentlicher Server: x.example:50002 "
            "(SSL, via Tor 127.0.0.1:9050) — erreichbar\n"
        )
        fuss.schreibe_log_text("9050) — erreichbar\n")
        self.assertEqual(stream.getvalue(), "")
        stumm = _stdout_nach_ende(stream)
        stumm.write("9050) — erreichbar\n")
        self.assertEqual(stream.getvalue(), "")

    def test_beende_server_schliesst_fulcrum_sockets(self):
        from core import terminal_steuerung as ts

        state = SimpleNamespace(
            jobs=SimpleNamespace(list=lambda: []),
            entries=[],
        )
        httpd = MagicMock()
        with patch.object(ts, "plane_hartes_prozessende"), patch(
            "core.fulcrum_transport.schliesse_offene_fulcrum_sockets",
            return_value=2,
        ) as schliesse:
            ts._beende_server(state, httpd)
        schliesse.assert_called_once()


class TestMainCliFlag(unittest.TestCase):
    def test_plain_console_in_argumenten(self):
        import server

        p = server.build_argumente()
        args = p.parse_args(["--plain-console", "--no-browser"])
        self.assertTrue(args.plain_console)
        self.assertTrue(args.no_browser)


if __name__ == "__main__":
    unittest.main()
