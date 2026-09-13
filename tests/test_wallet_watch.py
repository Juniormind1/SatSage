"""Wallet-Watch: Reconnect und Tip-Nachzug-Vormerkung."""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

from core import wallet_watch


class TestHeaderHoehe(unittest.TestCase):
    def test_dict_height(self):
        self.assertEqual(wallet_watch._header_hoehe({"height": 840001}), 840001)

    def test_int(self):
        self.assertEqual(wallet_watch._header_hoehe(100), 100)

    def test_ungueltig(self):
        self.assertIsNone(wallet_watch._header_hoehe(None))
        self.assertIsNone(wallet_watch._header_hoehe({"hex": "aa"}))


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
    def test_flush_header_skip_wenn_subscribe_greift(self):
        svc = wallet_watch.WalletWatchService()
        svc._state = object()
        svc._stop.clear()
        svc._session = object()
        svc._sh_to_addr = {"abc": "bc1q"}
        with mock.patch(
            "server.starte_wallet_aktualisierung",
        ) as start:
            svc._flush_header()
        start.assert_not_called()
        self.assertFalse(svc._tip_nachzug_offen)

    def test_flush_header_still_wenn_subscribe_fehlt(self):
        svc = wallet_watch.WalletWatchService()
        svc._state = object()
        svc._stop.clear()
        svc._session = None
        svc._sh_to_addr = {}
        with mock.patch(
            "server.starte_wallet_aktualisierung", return_value=None
        ) as start, mock.patch(
            "server.tip_sync_laeuft", return_value=True
        ):
            svc._flush_header()
        start.assert_called_once()
        self.assertTrue(start.call_args.kwargs.get("still"))
        self.assertTrue(svc._tip_nachzug_offen)

    def test_versuch_startet_still_wenn_frei(self):
        svc = wallet_watch.WalletWatchService()
        svc._state = object()
        svc._tip_nachzug_offen = True
        svc._session = None
        with mock.patch(
            "server.tip_sync_laeuft", return_value=False
        ), mock.patch(
            "server.starte_wallet_aktualisierung",
            return_value={"id": "j1"},
        ) as start:
            svc._versuch_offenen_tip_nachzug()
        start.assert_called_once()
        self.assertTrue(start.call_args.kwargs.get("still"))
        self.assertFalse(svc._tip_nachzug_offen)

    def test_versuch_verwirft_wenn_subscribe_greift(self):
        svc = wallet_watch.WalletWatchService()
        svc._state = object()
        svc._tip_nachzug_offen = True
        svc._session = object()
        svc._sh_to_addr = {"x": "bc1q"}
        with mock.patch(
            "server.starte_wallet_aktualisierung",
        ) as start:
            svc._versuch_offenen_tip_nachzug()
        start.assert_not_called()
        self.assertFalse(svc._tip_nachzug_offen)

    def test_job_beendet_triggert_nachzug(self):
        svc = wallet_watch.WalletWatchService()
        svc._tip_nachzug_offen = True
        with mock.patch.object(svc, "_versuch_offenen_tip_nachzug") as versuch:
            svc.tip_nachzug_job_beendet()
        versuch.assert_called_once()

    def test_on_header_erhoeht_seq(self):
        svc = wallet_watch.WalletWatchService()
        svc._stop.clear()
        with mock.patch.object(svc, "_header_timer", None):
            svc._on_header({"height": 100})
            svc._on_header({"height": 100})  # gleich → keine neue Seq
            svc._on_header({"height": 101})
        self.assertEqual(svc._last_block_height, 101)
        self.assertEqual(svc._last_block_seq, 2)
        st = svc.status()
        self.assertEqual(st["last_block_height"], 101)
        self.assertEqual(st["last_block_seq"], 2)
        # Timer aufräumen
        if svc._header_timer:
            svc._header_timer.cancel()
            svc._header_timer = None


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
