"""Electrum JSON-RPC-Batch nur für eigenen Electrs über Tor."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

import fulcrum
from tests.fixtures import BIP84_RECEIVE_0, BIP84_RECEIVE_1, BIP84_CHANGE_0


class TestRequestBatch(unittest.TestCase):

    def _client_tor(self) -> fulcrum.FulcrumClient:
        c = fulcrum.FulcrumClient(
            "electrs.onion", 50002, use_ssl=True, timeout=5,
            tor_proxy=("127.0.0.1", 9050),
        )
        c._sock = MagicMock()
        c._handshaked = True
        return c

    def test_ohne_tor_kein_batch_wire(self):
        c = fulcrum.FulcrumClient("127.0.0.1", 50001, use_ssl=False)
        c._handshaked = True
        c.request = MagicMock(side_effect=[1, 2, 3])  # type: ignore
        out = c.request_batch([
            ("blockchain.scripthash.listunspent", ["a"]),
            ("blockchain.scripthash.listunspent", ["b"]),
            ("blockchain.scripthash.listunspent", ["c"]),
        ])
        self.assertEqual(out, [1, 2, 3])
        self.assertEqual(c.request.call_count, 3)

    def test_tor_batch_eine_nachricht_array_antwort(self):
        c = self._client_tor()
        gesendet: list[bytes] = []

        def sendall(data: bytes) -> None:
            gesendet.append(data)

        c._sock.sendall = sendall  # type: ignore

        def recv(_n: int) -> bytes:
            # Eine Array-Antwort mit beiden ids
            # ids werden 1 und 2 (request_id startet bei 0, +1 je Call)
            return (
                json.dumps([
                    {"jsonrpc": "2.0", "id": 1, "result": [{"tx_hash": "aa" * 32, "tx_pos": 0, "value": 100, "height": 1}]},
                    {"jsonrpc": "2.0", "id": 2, "result": []},
                ]) + "\n"
            ).encode()

        c._sock.recv = recv  # type: ignore
        c._request_id = 0
        out = c.request_batch([
            (fulcrum._LISTUNSPENT_METHOD, ["sh1"]),
            (fulcrum._LISTUNSPENT_METHOD, ["sh2"]),
        ])
        self.assertEqual(len(gesendet), 1)
        body = json.loads(gesendet[0].decode().strip())
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["method"], fulcrum._LISTUNSPENT_METHOD)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][0]["value"], 100)
        self.assertEqual(out[1], [])

    def test_tor_batch_sinnvoll(self):
        c = self._client_tor()
        self.assertTrue(c.tor_batch_sinnvoll(2))
        self.assertFalse(c.tor_batch_sinnvoll(1))
        lan = fulcrum.FulcrumClient("10.0.0.1", 50001, use_ssl=False)
        self.assertFalse(lan.tor_batch_sinnvoll(100))


class TestFetchUtxosTorBatch(unittest.TestCase):

    def test_wallet_utxos_nutzt_batch_ueber_tor(self):
        c = fulcrum.FulcrumClient(
            "x.onion", 50002, tor_proxy=("127.0.0.1", 9050), use_ssl=False,
        )
        c._handshaked = True
        batches: list[int] = []

        def fake_batch(calls):
            batches.append(len(calls))
            return [[] for _ in calls]

        c.request_batch = fake_batch  # type: ignore
        addrs = {BIP84_RECEIVE_0, BIP84_RECEIVE_1, BIP84_CHANGE_0}
        out = fulcrum.fetch_wallet_utxos_fulcrum(c, addrs)
        self.assertEqual(out, [])
        self.assertEqual(sum(batches), 3)
        self.assertGreaterEqual(len(batches), 1)

    def test_wallet_utxos_lan_kein_batch(self):
        c = fulcrum.FulcrumClient("192.168.1.2", 50001, use_ssl=False)
        c.request_batch = MagicMock(side_effect=AssertionError("kein batch"))  # type: ignore
        c.request = MagicMock(return_value=[])  # type: ignore
        # fetch_address uses request listunspent
        out = fulcrum.fetch_wallet_utxos_fulcrum(c, {BIP84_RECEIVE_0})
        self.assertEqual(out, [])
        c.request_batch.assert_not_called()


class TestFirstSeenTorBatch(unittest.TestCase):

    def test_first_seen_batch_ueber_tor(self):
        c = fulcrum.FulcrumClient(
            "x.onion", 50002, tor_proxy=("127.0.0.1", 9050), use_ssl=False,
        )
        batches: list[int] = []

        def fake_batch(calls):
            batches.append(len(calls))
            # eine Adresse mit History-Höhe 700000
            return [
                [{"height": 700_000, "tx_hash": "ab" * 32}],
                [],
            ][: len(calls)]

        c.request_batch = fake_batch  # type: ignore
        hoehe = fulcrum.first_seen_height_fulcrum(
            c, [BIP84_RECEIVE_0, BIP84_RECEIVE_1],
        )
        self.assertEqual(hoehe, 700_000)
        self.assertEqual(sum(batches), 2)


if __name__ == "__main__":
    unittest.main()
