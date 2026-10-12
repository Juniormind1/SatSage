"""Anwendungsversion aus VERSION."""
from __future__ import annotations

import unittest
from pathlib import Path
import unittest.mock
from unittest.mock import patch

from core import version as version_mod


class TestVersion(unittest.TestCase):
    def tearDown(self):
        version_mod.version.cache_clear()

    def test_liest_repo_version(self):
        text = (Path(__file__).resolve().parents[1] / "VERSION").read_text(
            encoding="utf-8"
        ).strip()
        self.assertEqual(version_mod.datei_version(), text)
        self.assertRegex(text, r"^\d+\.\d+")

    def test_fallback_wenn_datei_fehlt(self):
        version_mod.version.cache_clear()
        with patch.object(version_mod, "resource_dir", return_value=Path("/tmp/fehlt-nix")), \
                patch.object(version_mod, "git_version", return_value=None):
            self.assertEqual(version_mod.version(), "0.9")

    def test_git_describe_ohne_v(self):
        fake = unittest.mock.Mock(stdout="v1.0.0-3-gabc1234-dirty\n")
        with patch.object(version_mod.subprocess, "run", return_value=fake), \
                patch.object(version_mod.sys, "frozen", False, create=True):
            self.assertEqual(version_mod.git_version(Path(__file__).resolve().parents[1]),
                             "1.0.0-3-gabc1234-dirty")

    def test_ohne_repo_datei(self):
        version_mod.version.cache_clear()
        with patch.object(version_mod, "git_version", return_value=None):
            self.assertEqual(version_mod.version(), version_mod.datei_version())

    def test_git_hat_vorrang(self):
        version_mod.version.cache_clear()
        with patch.object(version_mod, "git_version", return_value="1.2.3"):
            self.assertEqual(version_mod.version(), "1.2.3")


if __name__ == "__main__":
    unittest.main()
