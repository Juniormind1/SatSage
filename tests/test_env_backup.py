"""Start-Rotation .env.backup0 … .env.backup9 — keine Laufzeit-Zyklen."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from core.config import (
    ENV_BACKUP_SLOTS,
    EnvFile,
    env_backup_path,
    rotate_env_backups_at_start,
)
from tests.env_scramble_helpers import (
    clear_scramble_session,
    read_env_plaintext,
    write_env_scrambled,
)


class TestEnvBackupRotation(unittest.TestCase):
    def setUp(self):
        clear_scramble_session()
        self.addCleanup(clear_scramble_session)

    def test_rotation_schiebt_aeltere_zurueck(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            write_env_scrambled(env, "A=1\n")
            for i in range(3):
                write_env_scrambled(env_backup_path(env, i), f"OLD={i}\n")

            ziel = rotate_env_backups_at_start(env, slots=4)
            self.assertEqual(ziel, env_backup_path(env, 0))
            self.assertEqual(read_env_plaintext(env_backup_path(env, 0)), "A=1\n")
            self.assertEqual(read_env_plaintext(env_backup_path(env, 1)), "OLD=0\n")
            self.assertEqual(read_env_plaintext(env_backup_path(env, 2)), "OLD=1\n")
            self.assertEqual(read_env_plaintext(env_backup_path(env, 3)), "OLD=2\n")
            # Original unverändert (Kopie, kein Move)
            self.assertEqual(read_env_plaintext(env), "A=1\n")

    def test_ohne_env_keine_sicherung(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            self.assertIsNone(rotate_env_backups_at_start(env))

    def test_save_legt_kein_backup_an(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            write_env_scrambled(env, "A=1\n")
            datei = EnvFile.load(env)
            datei.set("B", "2")
            self.assertIsNone(datei.save(backup=True))
            self.assertFalse(env_backup_path(env, 0).exists())
            self.assertFalse((Path(tmp) / ".env.bak").exists())
            self.assertIn("B=2", read_env_plaintext(env))

    def test_slots_konstante(self):
        self.assertEqual(ENV_BACKUP_SLOTS, 10)


class TestEnvModusBackupSlots(unittest.TestCase):
    def setUp(self):
        clear_scramble_session()
        self.addCleanup(clear_scramble_session)

    def test_chmod_auch_fuer_backup_slots(self):
        import sys

        if sys.platform == "win32":
            self.skipTest("chmod 0600 greift unter Windows nicht zuverlässig")
        import server

        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            write_env_scrambled(env, "NETWORK=regtest\n")
            b0 = env_backup_path(env, 0)
            write_env_scrambled(b0, "NETWORK=regtest\n")
            os.chmod(env, 0o644)
            os.chmod(b0, 0o644)
            server._pruefe_env_modus(env)
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(b0.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
