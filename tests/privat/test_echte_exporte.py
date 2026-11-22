"""Opt-in-Test gegen echte Exporte auf dem Maintainer-Rechner.

Läuft nur mit SATSAGE_PRIVAT_DIR (Roh-CSVs außerhalb des Repos).
In CI (CI oder GITHUB_ACTIONS gesetzt) wird er immer übersprungen.
Gibt nur Aggregate aus, niemals Zeileninhalt, Beträge oder IDs.
"""
from __future__ import annotations

import os
import unittest


def _in_ci() -> bool:
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


@unittest.skipIf(_in_ci(), "Echte Exporte laufen nie in CI")
@unittest.skipUnless(
    os.environ.get("SATSAGE_PRIVAT_DIR"),
    "SATSAGE_PRIVAT_DIR ist nicht gesetzt",
)
class EchteExporteTest(unittest.TestCase):
    def test_placeholder_noch_ohne_parser(self):
        # Der Parser kommt in M2/M3. Dieser Test bleibt bis dahin ein Tor,
        # das in CI geschlossen ist.
        self.assertTrue(os.environ.get("SATSAGE_PRIVAT_DIR"))


if __name__ == "__main__":
    unittest.main()
