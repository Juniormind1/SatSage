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


class TestSubscribeAddresses(unittest.TestCase):
    def test_ohne_watcher_false(self):
        svc = wallet_watch.WalletWatchService()
        self.assertFalse(svc.subscribe_addresses(["bc1qtest"], "zpub-test"))

    def test_modul_wrapper_delegiert(self):
        with mock.patch.object(
            wallet_watch.WalletWatchService,
            "subscribe_addresses",
            return_value=True,
        ) as meth:
            ok = wallet_watch.subscribe_addresses(["bc1qabc"], "zpub1")
        self.assertTrue(ok)
        meth.assert_called_once_with(["bc1qabc"], "zpub1")

    def test_laufend_ruft_subscribe_extra(self):
        svc = wallet_watch.WalletWatchService()
        svc._session = object()
        with mock.patch.object(
            wallet_watch.WalletWatchService, "laeuft", new_callable=mock.PropertyMock
        ) as laeuft, mock.patch.object(svc, "_subscribe_extra") as extra:
            laeuft.return_value = True
            ok = svc.subscribe_addresses(["bc1qxyz"], "zpub2")
        self.assertTrue(ok)
        extra.assert_called_once_with(["bc1qxyz"], "zpub2")


if __name__ == "__main__":
    unittest.main()
