"""Gate der Hart-Tests — läuft immer, ohne Node."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from tests import hart


def _env(**kwargs):
    neu = {k: v for k, v in os.environ.items() if k not in (
        "SATSAGE_HARD_TESTS", "GITHUB_BASE_REF", "GITHUB_REF",
    )}
    neu.update(kwargs)
    return mock.patch.dict(os.environ, neu, clear=True)


class TestHartGate(unittest.TestCase):
    def test_explizit_an(self):
        with _env(SATSAGE_HARD_TESTS="1"):
            self.assertTrue(hart.hart_pflicht())

    def test_explizit_aus(self):
        with _env(SATSAGE_HARD_TESTS="0", GITHUB_BASE_REF="main"):
            self.assertFalse(hart.hart_pflicht())

    def test_github_pr_nach_main(self):
        with _env(GITHUB_BASE_REF="main", GITHUB_REF="refs/pull/1/merge"):
            self.assertTrue(hart.hart_pflicht())

    def test_github_push_main(self):
        with _env(GITHUB_REF="refs/heads/main"):
            self.assertTrue(hart.hart_pflicht())

    def test_github_dev_branch(self):
        with _env(GITHUB_REF="refs/heads/dev-juniormind"):
            self.assertFalse(hart.hart_pflicht())

    def test_skip_text_nennt_die_variable(self):
        self.assertIn("SATSAGE_HARD_TESTS=1", hart.SKIP_TEXT)
        self.assertIn("dev-juniormind", hart.SKIP_TEXT)


if __name__ == "__main__":
    unittest.main()
