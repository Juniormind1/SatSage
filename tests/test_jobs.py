"""Fortschritt langer Jobs: Phasen sofort, Zwischenstand spätestens alle 10s."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import main
from core import jobs as jobs_mod
from core.jobs import Fortschritt, Job, JobRegistry
from display import (
    Bip158ProgressLine,
    format_block_height_with_date,
    melde_zwischenstand,
)


class TestFortschritt(unittest.TestCase):

    def setUp(self):
        jobs_mod._reset_herzschlag_stand_fuer_tests()
        self.job = Job(id="t", kind="rescan", label="Test")
        self.stand = Fortschritt(self.job)
        self.addCleanup(self.stand.close)
        self.addCleanup(jobs_mod._reset_herzschlag_stand_fuer_tests)

    def test_phase_steht_sofort_im_log(self):
        self.stand.phase("Verbinde…")
        self.assertEqual(self.job.message, "Verbinde…")
        self.assertEqual(self.job.as_dict()["log"], ["Verbinde…"])

    def test_tick_innerhalb_von_zehn_sekunden_nicht_ins_log(self):
        self.stand.phase("Verbinde…")
        self.stand.tick("Gap-Scan Index #3…")
        self.assertEqual(self.job.message, "Gap-Scan Index #3…")
        self.assertEqual(self.job.as_dict()["log"], ["Verbinde…"])

    def test_tick_nach_zehn_sekunden_schreibt_eine_zeile(self):
        start = 1000.0

        def _jetzt():
            return _jetzt.wert

        _jetzt.wert = start
        with patch("core.jobs.time.monotonic", side_effect=_jetzt):
            jobs_mod._reset_herzschlag_stand_fuer_tests(start)
            stand = Fortschritt(self.job)
            stand.phase("Verbinde…")
            _jetzt.wert = start + 10.0
            stand.tick("Gap-Scan Index #40…")
            stand.close()
        self.assertEqual(
            self.job.as_dict()["log"],
            ["Verbinde…", "Gap-Scan Index #40…"],
        )

    def test_herzschlag_bei_gleichem_stand_schreibt_moment_noch(self):
        """Dieselbe Arbeitszeile nicht nochmal — nur ein Lebenszeichen."""
        start = 1000.0

        def _jetzt():
            return _jetzt.wert

        _jetzt.wert = start
        with patch("core.jobs.time.monotonic", side_effect=_jetzt):
            jobs_mod._reset_herzschlag_stand_fuer_tests(start)
            stand = Fortschritt(self.job)
            stand.phase("Prüfe Adresse 101 von 101…")
            _jetzt.wert = start + 10.0
            stand.tick()
            _jetzt.wert = start + 20.0
            stand.tick()
            stand.close()
        self.assertEqual(
            self.job.as_dict()["log"],
            ["Prüfe Adresse 101 von 101…", "Moment noch", "Moment noch"],
        )
        self.assertEqual(self.job.message, "Prüfe Adresse 101 von 101…")

    def test_phase_setzt_herzschlag_zurueck(self):
        """Filter-Treffer (phase) zählt als Meldung — kein „Moment noch“ nach 10s ab Start."""
        start = 1000.0

        def _jetzt():
            return _jetzt.wert

        _jetzt.wert = start
        with patch("core.jobs.time.monotonic", side_effect=_jetzt):
            jobs_mod._reset_herzschlag_stand_fuer_tests(start)
            stand = Fortschritt(self.job)
            stand.phase("Filter 0/481.375 (0,0 %)")
            _jetzt.wert = start + 6.0
            stand.phase("Filter-Treffer Block 850.123 — hole Block…")
            _jetzt.wert = start + 10.0
            stand.tick()
            stand.close()
        log = self.job.as_dict()["log"]
        self.assertNotIn("Moment noch", log)
        self.assertEqual(
            log[-1],
            "Filter-Treffer Block 850.123 — hole Block…",
        )

    def test_herzschlag_wartet_nach_jeder_log_zeile(self):
        """
        „Moment noch“ erst 10s nach der letzten Log-Meldung — auch wenn die
        Zeile nicht über phase/tick kam (direkter Job-Log).
        """
        start = 1000.0

        def _jetzt():
            return _jetzt.wert

        _jetzt.wert = start
        with patch("core.jobs.time.monotonic", side_effect=_jetzt):
            jobs_mod._reset_herzschlag_stand_fuer_tests(start)
            stand = Fortschritt(self.job)
            stand.phase("Start…")
            _jetzt.wert = start + 9.0
            # Frische Log-Zeile außerhalb von Fortschritt — setzt Stille zurück.
            self.job.progress("Zwischenergebnis…", log=True)
            _jetzt.wert = start + 12.0  # nur 3s nach der Log-Zeile
            stand.tick()
            self.assertNotIn("Moment noch", self.job.as_dict()["log"])
            _jetzt.wert = start + 19.0  # 10s nach Zwischenergebnis
            stand.tick()
            stand.close()
        self.assertEqual(
            self.job.as_dict()["log"],
            ["Start…", "Zwischenergebnis…", "Moment noch"],
        )

    def test_herzschlag_global_ueber_parallele_jobs(self):
        """
        Zwei stille Jobs: nur *eine* „Moment noch“-Zeile insgesamt — die Zeile
        nennt keinen Job, also kein Spam pro Job.
        """
        start = 1000.0

        def _jetzt():
            return _jetzt.wert

        _jetzt.wert = start
        job_a = Job(id="a", kind="rescan", label="A")
        job_b = Job(id="b", kind="trace", label="B")
        with patch("core.jobs.time.monotonic", side_effect=_jetzt):
            jobs_mod._reset_herzschlag_stand_fuer_tests(start)
            sa = Fortschritt(job_a)
            sb = Fortschritt(job_b)
            sa.phase("A arbeitet…")
            sb.phase("B arbeitet…")
            _jetzt.wert = start + 10.0
            sa.tick()
            sb.tick()
            sa.close()
            sb.close()
        log_a = job_a.as_dict()["log"]
        log_b = job_b.as_dict()["log"]
        moment_a = sum(1 for z in log_a if z == "Moment noch")
        moment_b = sum(1 for z in log_b if z == "Moment noch")
        self.assertEqual(moment_a + moment_b, 1, (log_a, log_b))

    def test_herzschlag_durch_anderen_job_unterdrueckt(self):
        """Ausgabe von Job B verhindert Herzschlag von Job A."""
        start = 1000.0

        def _jetzt():
            return _jetzt.wert

        _jetzt.wert = start
        job_a = Job(id="a", kind="rescan", label="A")
        job_b = Job(id="b", kind="trace", label="B")
        with patch("core.jobs.time.monotonic", side_effect=_jetzt):
            jobs_mod._reset_herzschlag_stand_fuer_tests(start)
            sa = Fortschritt(job_a)
            sb = Fortschritt(job_b)
            sa.phase("A start…")
            _jetzt.wert = start + 9.0
            sb.phase("B meldet…")  # globale Stille zurück
            _jetzt.wert = start + 12.0  # nur 3s nach B
            sa.tick()
            sa.close()
            sb.close()
        self.assertNotIn("Moment noch", job_a.as_dict()["log"])

    def test_filter_treffer_wird_in_place_ersetzt(self):
        """False Positive / Fund überschreibt „hole Block…“, hängt nicht an."""
        self.stand.phase("Filter-Treffer Block 850.123 — hole Block…")
        self.stand.phase("andere Zeile")
        self.stand.ersetze(
            "Filter-Treffer Block 850.123",
            "Filter-Treffer Block 850.123 — False Positive",
        )
        self.assertEqual(
            self.job.as_dict()["log"],
            [
                "Filter-Treffer Block 850.123 — False Positive",
                "andere Zeile",
            ],
        )
        self.assertEqual(
            self.job.message,
            "Filter-Treffer Block 850.123 — False Positive",
        )

    def test_ersetze_ohne_treffer_haengt_an(self):
        self.stand.phase("Start")
        self.stand.ersetze(
            "Filter-Treffer Block 1",
            "Filter-Treffer Block 1 — False Positive",
        )
        self.assertEqual(
            self.job.as_dict()["log"],
            ["Start", "Filter-Treffer Block 1 — False Positive"],
        )

    def test_neuer_stand_nach_intervall_steht_ausgeschrieben(self):
        start = 1000.0

        def _jetzt():
            return _jetzt.wert

        _jetzt.wert = start
        with patch("core.jobs.time.monotonic", side_effect=_jetzt):
            stand = Fortschritt(self.job)
            stand.phase("Prüfe Adresse 94 von 101…")
            _jetzt.wert = start + 10.0
            stand.tick("Prüfe Adresse 101 von 101…")
            stand.close()
        self.assertEqual(
            self.job.as_dict()["log"],
            ["Prüfe Adresse 94 von 101…", "Prüfe Adresse 101 von 101…"],
        )


class TestBip158ImJobLog(unittest.TestCase):

    def setUp(self):
        self.job = Job(id="b", kind="rescan", label="BIP-158")
        self.stand = Fortschritt(self.job)
        self.addCleanup(self.stand.close)

    def test_melde_zwischenstand_schreibt_ins_log(self):
        melde_zwischenstand("BIP-158-Scan …")
        self.assertIn("BIP-158-Scan …", self.job.as_dict()["log"])

    def test_filter_treffer_aus_worker_thread_landet_im_log(self):
        """ContextVar gilt nicht in Filter-Peers — Fallback muss greifen."""
        import threading

        from core.jobs import aktueller_zwischenstand

        gesehen = []

        def arbeit():
            self.assertIsNotNone(aktueller_zwischenstand())
            melde_zwischenstand("Filter-Treffer Block 850.123 — hole Block…")
            gesehen.append(True)

        t = threading.Thread(target=arbeit)
        t.start()
        t.join(timeout=5)
        self.assertTrue(gesehen)
        self.assertIn(
            "Filter-Treffer Block 850.123 — hole Block…",
            self.job.as_dict()["log"],
        )

    def test_progress_line_landet_im_log(self):
        """Dieselben Scan-Zeilen wie auf stdout sollen im Web-Log stehen."""
        with patch.object(Bip158ProgressLine, "_tty", False, create=True):
            line = Bip158ProgressLine(verbose=True)
            line._tty = False
            line.update(850_000, "aa" * 32 + ":0")
            line.update(850_100, "aa" * 32 + ":0")  # unter 2000 Blöcken → nur tick
            line.update(852_000, "aa" * 32 + ":0")
        log = self.job.as_dict()["log"]
        self.assertTrue(any("Scanne UTXO" in z and "850,000" in z for z in log), log)
        self.assertTrue(any("852,000" in z for z in log), log)
        self.assertTrue(any("≈" in z for z in log), log)
        self.assertEqual(self.job.message.count("Scanne UTXO"), 1)

    def test_blockhoehe_traegt_geschaetztes_datum(self):
        text = format_block_height_with_date(850_000)
        self.assertIn("850,000", text)
        self.assertRegex(text, r"≈ \d{2}\.\d{2}\.\d{4}")

    def test_blockdatum_vom_tip_ist_treffsicherer(self):
        """Rückwärts vom Tip: 850 000 ≈ Juni 2024, nicht die Genesis-Schätzung."""
        from datetime import datetime, timezone
        tip_ts = int(datetime(2026, 8, 18, tzinfo=timezone.utc).timestamp())
        text = format_block_height_with_date(
            850_000, tip_height=963_080, tip_time=tip_ts,
        )
        self.assertIn("≈ 23.06.2024", text)


class TestDatenquelleImJobLog(unittest.TestCase):
    """
    Im Log-Bereich steht „Datenquelle:“ nur für die wirklich gewählte Quelle.
    Eine fehlgeschlagene P2P-Probe darf nicht als Datenquelle gelten.
    """

    def setUp(self):
        main._reset_quelle_log()
        self.job = Job(id="q", kind="rescan", label="Quelle")
        self.stand = Fortschritt(self.job)
        self.addCleanup(self.stand.close)
        self.args = SimpleNamespace(bip158_start=None)

    def zeilen(self):
        return self.job.as_dict()["log"]

    def datenquellen(self):
        return [z for z in self.zeilen() if z.startswith("Datenquelle:")]

    def test_clearnet_meldet_electrum_als_datenquelle(self):
        client = object()
        pool = MagicMock()
        pool.__len__.return_value = 1
        pool.client_at.return_value = client
        with patch.object(
            main, "resolve_sanctions_clearnet_pool", return_value=(pool, False)
        ):
            backend = main._setup_public_clearnet_fulcrum(self.args, {})
        self.assertIsNotNone(backend)
        self.assertEqual(
            self.datenquellen(),
            ["Datenquelle: öffentliche Electrum-Server (Clearnet, 1 Server)"],
        )

    def test_probe_p2p_ist_keine_datenquelle_wenn_unerreichbar(self):
        with patch(
            "bip158_scanner.create_bip158_client_from_env", return_value=MagicMock()
        ), patch(
            "bip158_scanner.verify_p2p_filters",
            side_effect=RuntimeError("kein Peer"),
        ):
            with self.assertRaises(RuntimeError):
                main._setup_bip158_client(self.args, {}, raise_on_error=False)
        self.assertTrue(any("Prüfe P2P-BIP-158" in z for z in self.zeilen()))
        self.assertEqual(self.datenquellen(), [])

    def test_probe_p2p_meldet_datenquelle_erst_nach_erfolg(self):
        client = MagicMock()
        client.scanner._tor_proxy = None
        with patch(
            "bip158_scanner.create_bip158_client_from_env", return_value=client
        ), patch("bip158_scanner.verify_p2p_filters", return_value=900_000):
            main._setup_bip158_client(self.args, {}, raise_on_error=False)
        self.assertTrue(any("Prüfe P2P-BIP-158" in z for z in self.zeilen()))
        self.assertEqual(
            self.datenquellen(),
            ["Datenquelle: Bitcoin-P2P (BIP-158 Compact Filter)"],
        )

    def test_p2p_abgeschaltet_keine_probe(self):
        with patch.object(main, "_setup_bip158_client") as setup:
            self.assertIsNone(
                main._try_bip158_backend(self.args, {"BIP158_P2P": "0"})
            )
        setup.assert_not_called()
        self.assertEqual(self.zeilen(), [])

    def test_ohne_onion_eintraege_keine_onion_meldung(self):
        """Nicht konfiguriert ≠ fehlgeschlagen — sonst steht die Zeile dreimal im Log."""
        with patch.object(main, "_setup_public_onion_rotation") as setup:
            self.assertIsNone(main._try_public_onion_fulcrum(self.args, {}))
        setup.assert_not_called()
        self.assertFalse(
            any("Onion-Server nicht nutzbar" in z for z in self.zeilen())
        )

    def test_kette_ohne_eigenen_node_ohne_bestaetigung_keine_oeffentlichen(self):
        with patch.object(main, "_try_own_fulcrum_client", return_value=None), patch.object(
            main, "_try_bip158_backend", return_value=None
        ), patch.object(
            main, "_try_public_onion_fulcrum"
        ) as onion, patch.object(
            main, "_setup_public_clearnet_fulcrum"
        ) as clear:
            self.assertIsNone(
                main._try_data_source_priority_chain(
                    self.args, {}, include_bip158=True
                )
            )
        onion.assert_not_called()
        clear.assert_not_called()
        self.assertTrue(
            any("Bestätigung fehlt" in z for z in self.zeilen())
        )

    def test_kette_ohne_eigenen_node_mit_bestaetigung_landet_bei_clearnet(self):
        client = object()
        pool = MagicMock()
        pool.__len__.return_value = 1
        pool.client_at.return_value = client
        with patch.object(main, "_try_own_fulcrum_client", return_value=None), patch.object(
            main, "_try_bip158_backend", return_value=None
        ), patch.object(
            main, "_try_public_onion_fulcrum", return_value=None
        ), patch.object(
            main, "resolve_sanctions_clearnet_pool", return_value=(pool, False)
        ):
            quelle, backend, _ = main._try_data_source_priority_chain(
                self.args, {"OEFFENTLICHE_ELECTRUM": "1"}, include_bip158=True
            )
        self.assertEqual(quelle, "fulcrum")
        self.assertIsNotNone(backend)
        self.assertEqual(
            self.datenquellen(),
            ["Datenquelle: öffentliche Electrum-Server (Clearnet, 1 Server)"],
        )
        self.assertFalse(any("BIP-158" in z for z in self.zeilen()))

    def test_kette_fragt_interaktiv_nach_oeffentlichen(self):
        client = object()
        pool = MagicMock()
        pool.__len__.return_value = 1
        pool.client_at.return_value = client
        with patch.object(main, "_try_own_fulcrum_client", return_value=None), patch.object(
            main, "_try_bip158_backend", return_value=None
        ), patch.object(
            main, "_try_public_onion_fulcrum", return_value=None
        ), patch.object(
            main, "resolve_sanctions_clearnet_pool", return_value=(pool, False)
        ), patch("interact.prompt_yes_no", return_value=True):
            quelle, backend, _ = main._try_data_source_priority_chain(
                self.args, {}, include_bip158=True, interactive_onion=True
            )
        self.assertEqual(quelle, "fulcrum")
        self.assertTrue(self.args.oeffentliche_electrum)

    def test_datenquelle_zeile_wird_nicht_doppelt_geloggt(self):
        """Watch/Reconnect darf dieselbe Datenquelle nicht spam-loggen."""
        main._reset_quelle_log()
        text = "Datenquelle: eigener Electrum-Server (LAN) 127.0.0.1:50001"
        main._log_quelle("Automatische Datenquellen-Priorität…")
        main._log_quelle(text)
        main._log_quelle(text)
        main._log_quelle(text)
        main._log_quelle("Automatische Datenquellen-Priorität…")
        main._log_quelle(text)
        self.assertEqual(
            self.zeilen(),
            ["Automatische Datenquellen-Priorität…", text],
        )
        # Andere Quelle darf wieder durch
        neu = "Datenquelle: Bitcoin-P2P (BIP-158 Compact Filter)"
        main._log_quelle(neu)
        self.assertEqual(self.datenquellen(), [text, neu])


class TestJobRegistry(unittest.TestCase):

    def test_systemexit_beendet_den_job(self):
        """Sonst bleibt der UTXO-Scan auf running, letzte Zeile klebt."""
        registry = JobRegistry()

        def tot(_job):
            raise SystemExit(
                "Keine Datenquelle erreichbar (eigener Electrum-Server, BIP-158). "
                "Öffentliche Electrum-Server nur nach Bestätigung."
            )

        job = registry.start("rescan", "Cash+Carry", tot)
        for _ in range(80):
            if job.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(job.status, "failed")
        self.assertFalse(job.as_dict()["running"])
        self.assertIn("Keine Datenquelle erreichbar", job.error)
        self.assertIn("Keine Datenquelle erreichbar", job.message)
        self.assertIsNotNone(job.finished_at)


if __name__ == "__main__":
    unittest.main()
