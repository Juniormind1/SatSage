"""Anwendungsversion aus VERSION."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from core import version as version_mod


class TestVersion(unittest.TestCase):
    def tearDown(self):
        version_mod.version.cache_clear()

    def test_liest_repo_version(self):
        text = (Path(__file__).resolve().parents[1] / "VERSION").read_text(
            encoding="utf-8"
        ).strip()
        self.assertEqual(version_mod.version(), text)
        self.assertEqual(version_mod.version(), "0.9")

    def test_fallback_wenn_datei_fehlt(self):
        version_mod.version.cache_clear()
        with patch.object(version_mod, "resource_dir", return_value=Path("/tmp/fehlt-nix")):
            self.assertEqual(version_mod.version(), "0.9")


if __name__ == "__main__":
    unittest.main()
