"""Wallet-Watch: Reconnect und Tip-Nachzug-Vormerkung."""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

from core import wallet_watch


class TestWalletWatchReconnect(unittest.TestCase):
    def test_lauf_setzt_on_disconnect_nicht_auf_stop(self):
        """
        Quelltext-Vertrag: Disconnect darf _stop nicht setzen — sonst stirbt
        der Watcher bei Electrs-Hänger und reconnectet nie (Nacht-Symptom).
        """
        src = inspect.getsource(wallet_watch.WalletWatchService._lauf)
        self.assertIn("on_disconnect=None", src)
        self.assertNotIn("on_disconnect=lambda: self._stop.set()", src)
        self.assertIn("Reconnect", src)


class TestWalletWatchTipPending(unittest.TestCase):
    def test_flush_header_merkt_nach_wenn_job_laeuft(self):
        svc = wallet_watch.WalletWatchService()
        svc._state = object()
        svc._stop.clear()
        with mock.patch(
            "server.starte_wallet_aktualisierung", return_value=None
        ), mock.patch(
            "server.tip_sync_laeuft", return_value=True
        ):
            svc._flush_header()
        self.assertTrue(svc._tip_nachzug_offen)

    def test_versuch_startet_wenn_frei(self):
        svc = wallet_watch.WalletWatchService()
        svc._state = object()
        svc._tip_nachzug_offen = True
        with mock.patch(
            "server.tip_sync_laeuft", return_value=False
        ), mock.patch(
            "server.starte_wallet_aktualisierung",
            return_value={"id": "j1"},
        ) as start:
            svc._versuch_offenen_tip_nachzug()
        start.assert_called_once()
        self.assertFalse(svc._tip_nachzug_offen)

    def test_job_beendet_triggert_nachzug(self):
        svc = wallet_watch.WalletWatchService()
        svc._tip_nachzug_offen = True
        with mock.patch.object(svc, "_versuch_offenen_tip_nachzug") as versuch:
            svc.tip_nachzug_job_beendet()
        versuch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
