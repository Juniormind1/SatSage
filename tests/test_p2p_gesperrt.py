"""P2P bleibt zu, solange Compact Filter die Herkunft nicht tragen."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.p2p import P2pGesperrt, p2p_gesperrt, verbinde_peer
from core.source import describe_sources


class TestP2pGesperrt(unittest.TestCase):
    def test_socket_oeffnet_nicht(self):
        self.assertTrue(p2p_gesperrt())
        with patch("socket.create_connection") as conn:
            with self.assertRaises(P2pGesperrt):
                verbinde_peer("127.0.0.1", 18444, timeout=1)
            conn.assert_not_called()

    def test_datenquellen_blenden_p2p_aus(self):
        quelle = next(q for q in describe_sources({}) if q.key == "bip158")
        self.assertTrue(quelle.ausgeblendet)
        self.assertFalse(quelle.configured)
        self.assertTrue(quelle.as_dict()["ausgeblendet"])


if __name__ == "__main__":
    unittest.main()
