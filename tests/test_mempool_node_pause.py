"""Mempool-Abgleich: gescheiterte Verbindung zum eigenen Node wird gemerkt."""
from __future__ import annotations

import unittest
from unittest import mock

import server
from httpserver import empfang


class _Env:
    def __init__(self, werte):
        self.werte = werte

    def values(self):
        return self.werte


class _State:
    def __init__(self, werte):
        self._env = _Env(werte)

    def env(self):
        return self._env


class TestMempoolNodePause(unittest.TestCase):

    def setUp(self):
        self.jetzt = 1000.0
        uhr = mock.patch.object(empfang.time, "monotonic", side_effect=lambda: self.jetzt)
        uhr.start()
        self.addCleanup(uhr.stop)
        self.antwort = None
        node = mock.patch.object(
            server, "_eigener_fulcrum_client", side_effect=lambda _s: self.antwort,
        )
        self.node = node.start()
        self.addCleanup(node.stop)
        self.state = _State({"FULCRUM_HOST": "192.0.2.1", "FULCRUM_PORT": "50002"})

    def test_fehlschlag_pausiert_und_loggt_einmal(self):
        with self.assertLogs("satsage.server", level="INFO") as log:
            self.assertIsNone(empfang._mempool_node_client(self.state))
            self.jetzt += empfang.MEMPOOL_NODE_PAUSE_S - 1
            self.assertIsNone(empfang._mempool_node_client(self.state))
            self.assertEqual(self.node.call_count, 1)
            # Nach der Pause wieder ein Versuch — scheitert er, kein neuer Logeintrag.
            self.jetzt += 2
            self.assertIsNone(empfang._mempool_node_client(self.state))
            self.assertEqual(self.node.call_count, 2)
            self.jetzt += empfang.MEMPOOL_NODE_PAUSE_S + 1
            self.antwort = client = object()
            self.assertIs(empfang._mempool_node_client(self.state), client)
        self.assertEqual(len(log.records), 2)
        self.assertIn("nicht erreichbar", log.records[0].getMessage())
        self.assertIn("wieder erreichbar", log.records[1].getMessage())
        self.assertIsNone(self.state._mempool_node_pause)

    def test_neue_einstellung_beendet_die_pause(self):
        with self.assertLogs("satsage.server", level="INFO"):
            empfang._mempool_node_client(self.state)
        self.state.env().werte["FULCRUM_HOST"] = "192.0.2.7"
        with self.assertLogs("satsage.server", level="INFO"):
            empfang._mempool_node_client(self.state)
        self.assertEqual(self.node.call_count, 2)

    def test_lebende_verbindung_uebergeht_die_pause(self):
        with self.assertLogs("satsage.server", level="INFO"):
            empfang._mempool_node_client(self.state)
        self.state._empfang_fulcrum = object()
        self.antwort = self.state._empfang_fulcrum
        self.assertIs(empfang._mempool_node_client(self.state), self.antwort)

    def test_ohne_eigenen_node_keine_pause(self):
        state = _State({})
        self.assertIsNone(empfang._mempool_node_client(state))
        self.assertIsNone(getattr(state, "_mempool_node_pause", None))


if __name__ == "__main__":
    unittest.main()
