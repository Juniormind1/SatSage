"""Beschreibbare Caches liegen im Binary neben der Executable, nicht in _MEIPASS."""
from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

WURZEL = Path(__file__).resolve().parent.parent


class TestCachePfadeBinary(unittest.TestCase):
    def _neu_laden(self):
        import labels
        import sanctioned

        return importlib.reload(sanctioned), importlib.reload(labels)

    def tearDown(self):
        self._neu_laden()

    def test_quellbetrieb_unveraendert(self):
        sanctioned, labels = self._neu_laden()
        self.assertEqual(sanctioned.SANCTIONED_CACHE_DIR, WURZEL / "sanctioned_cache")
        self.assertEqual(labels.LABEL_CACHE_DIR, WURZEL / "label_cache")

    def test_binary_neben_executable(self):
        with tempfile.TemporaryDirectory() as bin_dir, tempfile.TemporaryDirectory() as mei:
            exe = Path(bin_dir) / "satsage-linux"
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "_MEIPASS", mei, create=True), \
                    patch.object(sys, "executable", str(exe)):
                sanctioned, labels = self._neu_laden()
                ziel = Path(bin_dir).resolve()
                self.assertEqual(sanctioned.SANCTIONED_CACHE_DIR, ziel / "sanctioned_cache")
                self.assertEqual(labels.LABEL_CACHE_DIR, ziel / "label_cache")
                self.assertNotIn(mei, str(sanctioned.SANCTIONED_CACHE_DIR))

                import consolidate

                self.assertEqual(consolidate.write_consolidation_psbts([]), [])
                self.assertTrue((ziel / "psbt_out").is_dir())


if __name__ == "__main__":
    unittest.main()
