"""Fulcrum-Anfragen bei Timeout neu verbinden und wiederholen."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import fulcrum


class TestFulcrumRequestRetry(unittest.TestCase):
    def test_timeout_wird_retried(self):
        client = fulcrum.FulcrumClient("127.0.0.1", 50001, use_ssl=False, timeout=1)
        client._sock = MagicMock()
        # Handshake schon erledigt — sonst zählt server.version mit (libbitcoin: 1×).
        client._handshaked = True
        n = {"i": 0}

        def once(method, params=None):
            n["i"] += 1
            if n["i"] < 3:
                raise TimeoutError("timed out")
            return {"ok": True}

        client._request_once = once  # type: ignore[method-assign]
        client.connect = MagicMock()
        client.close = MagicMock()
        self.assertEqual(client.request("blockchain.transaction.get", ["ab" * 32]), {"ok": True})
        self.assertEqual(n["i"], 3)
        self.assertEqual(client.connect.call_count, 2)

    def test_nach_max_retries_timeout_error(self):
        client = fulcrum.FulcrumClient("127.0.0.1", 50001, use_ssl=False, timeout=1)
        client._sock = MagicMock()
        client._handshaked = True
        client._request_once = MagicMock(side_effect=TimeoutError("timed out"))
        client.connect = MagicMock()
        client.close = MagicMock()
        with self.assertRaises(TimeoutError) as ctx:
            client.request("blockchain.transaction.get", ["cd" * 32])
        self.assertIn("3 Versuchen", str(ctx.exception))

    def test_zweites_server_version_kein_zweiter_rpc(self):
        """libbitcoin: nur ein Handshake pro Session."""
        client = fulcrum.FulcrumClient("127.0.0.1", 50001, use_ssl=False, timeout=1)
        client._sock = MagicMock()
        client._request_once = MagicMock(return_value=["/libbitcoin:4.0.0/", "1.4"])
        self.assertEqual(client.handshake()[0], "/libbitcoin:4.0.0/")
        self.assertEqual(client.server_software, "libbitcoin")
        self.assertEqual(client.handshake()[0], "/libbitcoin:4.0.0/")
        self.assertEqual(client.request("server.version"), ["/libbitcoin:4.0.0/", "1.4"])
        self.assertEqual(client._request_once.call_count, 1)

    def test_nicht_verbunden_wird_neu_verbunden(self):
        client = fulcrum.FulcrumClient("127.0.0.1", 50001, use_ssl=False, timeout=1)
        client._handshaked = True
        n = {"i": 0}

        def once(method, params=None):
            n["i"] += 1
            if n["i"] < 2:
                raise RuntimeError("Fulcrum-Client nicht verbunden")
            return []

        client._request_once = once  # type: ignore[method-assign]
        client.connect = MagicMock()
        client.close = MagicMock()
        self.assertEqual(
            client.request("blockchain.scripthash.get_history", ["00"]),
            [],
        )
        self.assertEqual(n["i"], 2)
        client.connect.assert_called()

    def test_nicht_verbunden_bei_abbruch_cancelled(self):
        from core.jobs import Cancelled

        client = fulcrum.FulcrumClient("127.0.0.1", 50001, use_ssl=False, timeout=1)
        client._handshaked = True
        client._request_once = MagicMock(
            side_effect=RuntimeError("Fulcrum-Client nicht verbunden"),
        )
        client.connect = MagicMock()
        client.close = MagicMock()
        with patch("display.is_list_abort_requested", return_value=True):
            with self.assertRaises(Cancelled):
                client.request("blockchain.scripthash.get_history", ["00"])
        client.connect.assert_not_called()

    def test_rotation_nimmt_naechsten_wenn_nicht_verbunden(self):
        tot = MagicMock()
        tot.request.side_effect = RuntimeError("Fulcrum-Client nicht verbunden")
        tot.close = MagicMock()
        tot.connect = MagicMock()
        lebend = MagicMock()
        lebend.request.return_value = [{"tx_hash": "ab", "height": 1}]
        pool = fulcrum.RotatingFulcrumPool([tot, lebend])
        self.assertEqual(
            pool.request("blockchain.scripthash.get_history", ["00"]),
            [{"tx_hash": "ab", "height": 1}],
        )
        tot.close.assert_called()
        lebend.request.assert_called()


class TestNotifySessionTimeout(unittest.TestCase):
    def test_lan_nimmt_connect_timeout_nicht_60s(self):
        import queue

        sess = fulcrum.FulcrumNotifySession(
            "127.0.0.1", 50001, use_ssl=False, timeout=8,
        )
        sess._sock = MagicMock()
        gesehen = {}

        def fake_get(_self, timeout=None):
            gesehen["timeout"] = timeout
            raise queue.Empty

        with unittest.mock.patch("queue.Queue.get", fake_get):
            with self.assertRaises(TimeoutError):
                sess.request("blockchain.headers.subscribe")
        self.assertEqual(gesehen["timeout"], 8.0)

    def test_onion_nimmt_onion_timeout(self):
        import queue

        sess = fulcrum.FulcrumNotifySession(
            "example.onion", 50001, use_ssl=True, timeout=8,
            tor_proxy=("127.0.0.1", 9050),
        )
        sess._sock = MagicMock()
        gesehen = {}

        def fake_get(_self, timeout=None):
            gesehen["timeout"] = timeout
            raise queue.Empty

        with unittest.mock.patch("queue.Queue.get", fake_get):
            with self.assertRaises(TimeoutError):
                sess.request("blockchain.headers.subscribe")
        self.assertEqual(gesehen["timeout"], float(fulcrum.FULCRUM_ONION_TIMEOUT))


class TestNotifySessionHandshake(unittest.TestCase):
    def test_start_sendet_server_version(self):
        sess = fulcrum.FulcrumNotifySession(
            "127.0.0.1", 50001, use_ssl=False, timeout=8,
        )
        sess._sock = MagicMock()
        sess._sock.recv.return_value = b""
        sess.request = MagicMock(return_value=["/libbitcoin:4.0.0/", "1.4"])
        try:
            sess.start()
            sess.request.assert_called_once()
            self.assertEqual(sess.request.call_args[0][0], "server.version")
            self.assertEqual(sess.request.call_args[0][1], ["SatSage", "1.4"])
            self.assertTrue(sess._handshaked)
            self.assertEqual(sess.server_software, "libbitcoin")
        finally:
            sess.stop()

    def test_handshake_nur_einmal(self):
        sess = fulcrum.FulcrumNotifySession(
            "127.0.0.1", 50001, use_ssl=False, timeout=8,
        )
        sess._sock = MagicMock()
        sess.request = MagicMock(return_value=["/libbitcoin:4.0.0/", "1.4"])
        sess.handshake()
        sess.handshake()
        sess.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
