"""Fulcrum-Anfragen bei Timeout neu verbinden und wiederholen."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

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


if __name__ == "__main__":
    unittest.main()
