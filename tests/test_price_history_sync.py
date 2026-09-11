"""Nachzug der Kurs-Historie: Lücke, Overlap, Diskrepanz, Smoothing."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from core import price as price_mod
from core import price_history_sync as sync


def _serie_csv(tage: dict[str, float]) -> str:
    zeilen = ["date,price"]
    for d, p in sorted(tage.items()):
        zeilen.append(f"{d},{p}")
    return "\n".join(zeilen) + "\n"


class TestHistorieNachzug(unittest.TestCase):
    def test_luecke_wenn_serie_hinter_gestern(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            price_mod.schreibe_kurs_csv(
                root / "btc_price" / "EUR.csv",
                {"2026-08-27": 67000.0},
                currency="EUR",
                quelle="test",
            )
            luecke = sync.historie_luecke_bis(
                root, "EUR", bis=date(2026, 9, 10),
            )
            self.assertEqual(luecke, date(2026, 8, 28))

    def test_keine_luecke_wenn_aktuell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            price_mod.schreibe_kurs_csv(
                root / "btc_price" / "EUR.csv",
                {"2026-09-10": 66000.0},
                currency="EUR",
                quelle="test",
            )
            self.assertIsNone(
                sync.historie_luecke_bis(root, "EUR", bis=date(2026, 9, 10))
            )

    def test_merge_ohne_diskrepanz_haengt_luecke_an(self):
        lokal = {f"2026-08-{d:02d}": 100.0 + d for d in range(1, 28)}
        lokal["2026-08-27"] = 200.0
        remote = dict(lokal)
        remote["2026-08-28"] = 201.0
        remote["2026-08-29"] = 202.0
        # leichte Abweichung in Overlap (< 1.5%)
        remote["2026-08-27"] = 200.5
        logs: list[str] = []
        merged, meta = sync.merge_historie_mit_overlap(
            lokal,
            remote,
            luecke_ab=date(2026, 8, 28),
            bis=date(2026, 8, 29),
            on_log=logs.append,
        )
        self.assertFalse(meta["diskrepanz"])
        self.assertEqual(merged["2026-08-27"], 200.0)  # lokal behalten
        self.assertEqual(merged["2026-08-28"], 201.0)
        self.assertEqual(meta["neu_tage"], 2)

    def test_merge_diskrepanz_nimmt_remote_in_overlap(self):
        lokal = {}
        remote = {}
        for i in range(28):
            tag = date(2026, 8, 1) + __import__("datetime").timedelta(days=i)
            lokal[tag.isoformat()] = 100.0
            remote[tag.isoformat()] = 110.0  # +10%
        remote["2026-08-29"] = 111.0
        logs: list[str] = []
        merged, meta = sync.merge_historie_mit_overlap(
            lokal,
            remote,
            luecke_ab=date(2026, 8, 29),
            bis=date(2026, 8, 29),
            on_log=logs.append,
        )
        self.assertTrue(meta["diskrepanz"])
        self.assertGreater(meta["diskrepanz_median_pct"], 1.5)
        self.assertEqual(merged["2026-08-28"], 110.0)
        self.assertTrue(any("Diskrepanz" in z for z in logs))

    def test_smooth_bei_sprung(self):
        lokal = {"2026-08-27": 100.0}
        remote = {
            "2026-08-27": 100.0,
            "2026-08-28": 200.0,
            "2026-08-29": 200.0,
            "2026-08-30": 200.0,
            "2026-08-31": 200.0,
            "2026-09-01": 200.0,
            "2026-09-02": 200.0,
            "2026-09-03": 200.0,
            "2026-09-04": 200.0,
        }
        logs: list[str] = []
        merged, meta = sync.merge_historie_mit_overlap(
            lokal,
            remote,
            luecke_ab=date(2026, 8, 28),
            bis=date(2026, 9, 4),
            on_log=logs.append,
        )
        self.assertTrue(meta["smooth"])
        # Tag 1/7: näher am Anker 100 als an 200
        self.assertLess(merged["2026-08-28"], 200.0)
        self.assertGreater(merged["2026-08-28"], 100.0)
        # Letzter Smooth-Tag ≈ remote
        self.assertAlmostEqual(merged["2026-09-03"], 200.0, places=4)

    def test_nachziehen_ohne_opt_in_nur_hinweis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            price_mod.schreibe_kurs_csv(
                root / "btc_price" / "EUR.csv",
                {"2026-08-27": 67000.0},
                currency="EUR",
                quelle="test",
            )
            logs: list[str] = []
            jetzt = int(datetime(2026, 9, 11, tzinfo=timezone.utc).timestamp())

            def fetch(url, timeout):
                raise AssertionError("kein Netz ohne Opt-in")

            ergebnis = sync.historie_nachziehen(
                root,
                "EUR",
                values={},
                on_log=logs.append,
                fetch=fetch,
                jetzt=jetzt,
                force=True,
            )
            self.assertFalse(ergebnis["ok"])
            self.assertEqual(ergebnis["reason"], "opt_in")
            self.assertTrue(any("SATSAGE_PRICE_HISTORY_OPT_IN" in z for z in logs))

    def test_nachziehen_mit_opt_in_fuellt_luecke(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            price_mod.schreibe_kurs_csv(
                root / "btc_price" / "EUR.csv",
                {"2026-08-27": 67000.0},
                currency="EUR",
                quelle="test",
            )
            remote_tage = {"2026-08-27": 67000.0}
            for i in range(1, 15):
                tag = date(2026, 8, 27) + __import__("datetime").timedelta(days=i)
                remote_tage[tag.isoformat()] = 67000.0 + i

            def fetch(url, timeout):
                self.assertIn("Bitstamp_BTCEUR", url)
                return (
                    "https://www.cryptodatadownload.com\n"
                    + _serie_csv(remote_tage)
                )

            logs: list[str] = []
            jetzt = int(datetime(2026, 9, 11, tzinfo=timezone.utc).timestamp())
            ergebnis = sync.historie_nachziehen(
                root,
                "EUR",
                values={"SATSAGE_PRICE_HISTORY_OPT_IN": "1"},
                on_log=logs.append,
                fetch=fetch,
                jetzt=jetzt,
                force=True,
            )
            self.assertTrue(ergebnis["ok"])
            self.assertGreater(ergebnis["neu_tage"], 0)
            stand = price_mod.historie_status(root, "EUR")
            self.assertEqual(stand["to"], "2026-09-10")
            self.assertEqual(stand["source"], "cache")


if __name__ == "__main__":
    unittest.main()
