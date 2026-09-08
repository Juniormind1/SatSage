"""Session-JSON für GUI-Tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import gui_session as gs


class TestGuiSession(unittest.TestCase):
    def test_schreibe_und_lese(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "session.json"
            payload = gs.bau_payload(
                url="http://127.0.0.1:9/?t=abc",
                token="abc",
                port=9,
            )
            with mock.patch.object(gs, "print"):  # stdout-Zeile unterdrücken
                geschrieben = gs.schreibe_session(payload, pfad=pfad)
            self.assertEqual(geschrieben, pfad)
            data = gs.lese_session(pfad)
            self.assertIsNotNone(data)
            assert data is not None
            self.assertEqual(data["token"], "abc")
            self.assertEqual(data["port"], 9)
            self.assertTrue(pfad.is_file())
            # Mode idealerweise 0600 (plattformabhängig)
            mode = pfad.stat().st_mode & 0o777
            self.assertEqual(mode & 0o077, 0)  # keine group/other-Rechte

    def test_loesche(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "s.json"
            with mock.patch.object(gs, "print"):
                gs.schreibe_session(
                    gs.bau_payload(url="http://x/?t=1", token="1", port=1),
                    pfad=pfad,
                )
            gs.loesche_session(pfad)
            self.assertFalse(pfad.exists())


if __name__ == "__main__":
    unittest.main()
