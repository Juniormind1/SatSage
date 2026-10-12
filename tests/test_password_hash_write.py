"""Gleichzeitiges Schreiben des Login-Hashs darf nicht an derselben .tmp scheitern."""

from __future__ import annotations

import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path

import server


class _EnvState:
    def __init__(self, env_path: Path) -> None:
        self.env_path = env_path

    def env(self):
        raise OSError("kein Env-Lesen in diesem Test")


class TestPasswordHashWrite(unittest.TestCase):
    def test_parallele_schreibvorgaenge_hinterlassen_eine_datei(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = _EnvState(Path(tmp) / "satsage.env")
            fehler: list[BaseException] = []

            def lauf(kennzeichen: int) -> None:
                try:
                    server._write_password_hash(state, f"parallel-{kennzeichen}")
                except Exception as exc:
                    fehler.append(exc)

            threads = [
                threading.Thread(target=lauf, args=(i,))
                for i in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(fehler, [])
            ziel = Path(tmp) / ".satsage-password"
            self.assertTrue(ziel.is_file())
            self.assertEqual(list(Path(tmp).glob(".satsage-password*.tmp")), [])
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(ziel.stat().st_mode), 0o600)
            gespeichert = server._password_hash(state)
            self.assertTrue(
                any(
                    server._verify_password(f"parallel-{i}", gespeichert)
                    for i in range(8)
                )
            )


if __name__ == "__main__":
    unittest.main()
