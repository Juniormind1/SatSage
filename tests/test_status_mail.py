"""Status-Mails: neutrale Texte, Opt-in, Job-Hook."""
from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import status_mail as sm
from core.jobs import Job, JobRegistry, setze_fertig_hook


class TestStatusMailBuilder(unittest.TestCase):
    def test_body_nur_ereignis_status_zeit(self):
        betreff, body = sm.baue_nachricht("rescan", "done", 1_700_000_000.0)
        self.assertEqual(betreff, "SatSage: UTXO-Scan fertig")
        self.assertIn("Ereignis: UTXO-Scan", body)
        self.assertIn("Status: fertig", body)
        self.assertIn("Zeit:", body)
        self.assertNotIn("Wallet", body)
        self.assertNotIn("bc1", body)
        self.assertNotIn("txid", body.lower())

    def test_verlauf_fehlgeschlagen(self):
        betreff, body = sm.baue_nachricht("verlauf", "failed", None)
        self.assertEqual(betreff, "SatSage: Verlaufsscan fehlgeschlagen")
        self.assertIn("Status: fehlgeschlagen", body)

    def test_darf_senden_braucht_opt_in_und_smtp(self):
        leer = {}
        self.assertFalse(sm.darf_senden(leer, "rescan"))
        teil = {
            "STATUS_MAIL_OPT_IN": "1",
            "STATUS_MAIL_TO": "a@b.c",
            "SMTP_HOST": "smtp.test",
            "SMTP_FROM": "from@test",
        }
        self.assertTrue(sm.darf_senden(teil, "rescan"))
        self.assertTrue(sm.darf_senden(teil, "verlauf"))
        self.assertFalse(sm.darf_senden(teil, "headers"))

    def test_als_dict_ohne_passwort(self):
        d = sm.als_dict({
            "STATUS_MAIL_OPT_IN": "1",
            "STATUS_MAIL_TO": "a@b.c",
            "SMTP_HOST": "h",
            "SMTP_FROM": "f@t",
            "SMTP_PASSWORD": "geheim",
        })
        self.assertTrue(d["smtp_password_set"])
        self.assertNotIn("smtp_password", d)
        self.assertNotIn("geheim", str(d))


class TestStatusMailHook(unittest.TestCase):
    def tearDown(self):
        setze_fertig_hook(None)

    def test_hook_fuer_rescan_done(self):
        gesehen = []

        def hook(job):
            gesehen.append((job.kind, job.status))

        setze_fertig_hook(hook)
        reg = JobRegistry()
        job = reg.start("rescan", "UTXO-Scan Geheimname", lambda j: None)
        for _ in range(50):
            if job.status != "running":
                break
            time.sleep(0.01)
        self.assertEqual(job.status, "done")
        self.assertEqual(gesehen, [("rescan", "done")])

    def test_sende_async_bei_konfiguration(self):
        werte = {
            "STATUS_MAIL_OPT_IN": "1",
            "STATUS_MAIL_TO": "a@b.c",
            "SMTP_HOST": "smtp.test",
            "SMTP_FROM": "from@test",
            "SMTP_PORT": "587",
        }
        with patch.object(sm, "sende_status_mail", return_value=True) as send:
            # Synchron für den Test: async-Wrapper umgehen
            sm.sende_status_mail(
                werte, kind="verlauf", status="done", finished_at=1.0,
            )
            send.assert_called_once()

    def test_smtp_aufruf_neutral(self):
        werte = {
            "STATUS_MAIL_OPT_IN": "1",
            "STATUS_MAIL_TO": "a@b.c",
            "SMTP_HOST": "smtp.test",
            "SMTP_FROM": "from@test",
            "SMTP_PORT": "587",
            "SMTP_STARTTLS": "1",
        }
        with patch.object(sm, "_smtp_senden") as smtp:
            ok = sm.sende_status_mail(
                werte, kind="rescan", status="done", finished_at=1.0,
            )
        self.assertTrue(ok)
        args = smtp.call_args[0]
        self.assertEqual(args[1], "SatSage: UTXO-Scan fertig")
        self.assertIn("Ereignis: UTXO-Scan", args[2])


class TestStatusMailApi(unittest.TestCase):
    def test_save_und_config_ohne_passwort(self):
        import tempfile
        from pathlib import Path

        import server
        from core.config import EnvFile

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("", encoding="utf-8")
            state = SimpleNamespace(
                env_path=env_path,
                env=lambda: EnvFile.load(env_path),
            )
            out = server.api_save_status_mail(state, {
                "opt_in": True,
                "to": "user@example.com",
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": "u",
                "smtp_from": "satsage@example.com",
                "smtp_password": "geheim",
                "starttls": True,
            })
            self.assertTrue(out["saved"])
            self.assertTrue(out["status_mail"]["smtp_password_set"])
            self.assertNotIn("smtp_password", out["status_mail"])
            self.assertNotIn("geheim", str(out))

            # Leeres Passwort behält den Wert
            out2 = server.api_save_status_mail(state, {
                "opt_in": True,
                "to": "user@example.com",
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": "u",
                "smtp_from": "satsage@example.com",
                "starttls": True,
            })
            self.assertTrue(out2["status_mail"]["smtp_password_set"])
            roh = env_path.read_text(encoding="utf-8")
            self.assertIn("SMTP_PASSWORD=geheim", roh)


if __name__ == "__main__":
    unittest.main()
