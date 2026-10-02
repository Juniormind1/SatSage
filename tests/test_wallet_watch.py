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

    def test_kein_electrs_bricht_nicht_ab(self):
        """Indexer weg: 15 s warten und weiter, nicht den Watcher beenden."""
        src = inspect.getsource(wallet_watch.WalletWatchService._lauf)
        self.assertIn("Reconnect in 15", src)
        self.assertIn("continue", src)
        self.assertNotIn(
            "nur Start-Tip-Nachzug, kein Dauer-Subscribe.",
            src,
        )


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


class TestAdressenAusCaches(unittest.TestCase):
    def test_liest_utxo_und_verlauf(self):
        svc = wallet_watch.WalletWatchService()
        entry = mock.Mock()
        entry.analyse_schluessel = "xpub-test"
        state = mock.Mock()
        state.analyse_entries = [entry]
        state.cache_dir = "cache"
        with mock.patch.object(
            wallet_watch.xpub_cache,
            "load_xpub_utxo_cache",
            return_value=[{"address": "bc1qtestutxo"}],
        ), mock.patch.object(
            wallet_watch.xpub_cache,
            "load_xpub_verlauf_cache",
            return_value=[{"address": "bc1qtestverlauf"}],
        ):
            mapping = svc._adressen_aus_caches(state)
        self.assertEqual(mapping["bc1qtestutxo"], {"xpub-test"})
        self.assertEqual(mapping["bc1qtestverlauf"], {"xpub-test"})


class TestEigenerWatchClient(unittest.TestCase):
    def test_lan_geht_nicht_ueber_onion_fallback(self):
        state = mock.Mock()
        state.env.return_value.values.return_value = {}
        state.args_namespace.return_value = object()
        with mock.patch(
            "core.chain_sources._resolve_own_lan_endpoint",
            return_value=("192.168.1.8", 50001, False),
        ), mock.patch(
            "core.fulcrum_client.connect_fulcrum",
            return_value=(None, "refused"),
        ) as conn, mock.patch(
            "core.chain_sources._try_own_fulcrum_client",
        ) as voll:
            self.assertIsNone(wallet_watch._eigener_watch_client(state))
        conn.assert_called()
        voll.assert_not_called()


class TestWalletWatchGuiLog(unittest.TestCase):
    def test_log_steht_im_status(self):
        svc = wallet_watch.WalletWatchService()
        svc._on_log = lambda _t: None
        svc._log("Wallet-Watch: Verbindung weg — Reconnect in 15 s…")
        st = svc.status()
        self.assertEqual(st["log"][-1]["text"], "Wallet-Watch: Verbindung weg — Reconnect in 15 s…")
        self.assertEqual(st["log"][-1]["seq"], 1)

    def test_log_behaelt_nur_die_letzten(self):
        svc = wallet_watch.WalletWatchService()
        svc._on_log = lambda _t: None
        for i in range(wallet_watch._GUI_LOG_MAX + 5):
            svc._log(f"Wallet-Watch: Zeile {i}")
        st = svc.status()
        self.assertEqual(len(st["log"]), wallet_watch._GUI_LOG_MAX)
        self.assertEqual(st["log"][0]["seq"], 6)
        self.assertEqual(st["log"][-1]["seq"], wallet_watch._GUI_LOG_MAX + 5)


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
