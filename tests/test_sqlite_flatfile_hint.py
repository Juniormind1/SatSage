"""Hinweis wenn immutable tx/ingress-Flatfiles die SQLite-Schwelle erreichen."""
from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

import core.xpub_cache as xpub_cache
import main


class TestSqliteFlatfileHint(unittest.TestCase):
    def setUp(self):
        xpub_cache._sqlite_flatfile_hint_emitted = False
        xpub_cache._sqlite_flatfile_save_ticks.clear()
        xpub_cache._sqlite_flatfile_last_count.clear()
        main._sqlite_flatfile_hint_emitted = False

    def test_hinweis_ab_schwellwert_einmalig(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "tx"
            sub.mkdir()
            for i in range(5):
                (sub / f"{i:064x}.json").write_text("{}", encoding="utf-8")
            buf = StringIO()
            with mock.patch.object(xpub_cache, "_SQLITE_FLATFILE_HINT_THRESHOLD", 5):
                with mock.patch("sys.stdout", buf):
                    main._maybe_log_sqlite_flatfile_hint(sub, kind="tx")
                    main._maybe_log_sqlite_flatfile_hint(sub, kind="tx")
            text = buf.getvalue()
            self.assertEqual(text.count("Cache wächst"), 1)
            self.assertIn("sqlite ab jetzt sinnvoll", text)
            self.assertIn("GitHub-Issue", text)
            self.assertTrue(main._sqlite_flatfile_hint_emitted)

    def test_unter_schwellwert_kein_hinweis(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "tx"
            sub.mkdir()
            (sub / ("a" * 64 + ".json")).write_text("{}", encoding="utf-8")
            buf = StringIO()
            with mock.patch.object(xpub_cache, "_SQLITE_FLATFILE_HINT_THRESHOLD", 5):
                with mock.patch("sys.stdout", buf):
                    main._maybe_log_sqlite_flatfile_hint(sub, kind="tx")
            self.assertEqual(buf.getvalue(), "")
            self.assertFalse(main._sqlite_flatfile_hint_emitted)


if __name__ == "__main__":
    unittest.main()
