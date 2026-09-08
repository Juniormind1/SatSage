"""Port-Übernahme und SatSage-Prozess-Erkennung."""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from core import single_instance as si
from tests.fixtures import BIP84_ZPUB


class TestIstSatsageProzess(unittest.TestCase):
    def test_eigene_pid_nein(self):
        self.assertFalse(si.ist_satsage_prozess(os.getpid()))

    def test_cmdline_erkennung(self):
        with mock.patch.object(
            si, "_cmdline", return_value="/tmp/dist/satsage-webgui --port 8730"
        ):
            self.assertTrue(si.ist_satsage_prozess(12345))
        with mock.patch.object(
            si, "_cmdline", return_value="python3 server.py --plain-console"
        ):
            self.assertTrue(si.ist_satsage_prozess(99))
        with mock.patch.object(si, "_cmdline", return_value="/usr/bin/nginx"):
            self.assertFalse(si.ist_satsage_prozess(99))


class _LeerHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: ARG002
        return


class TestHttpdBinden(unittest.TestCase):
    def test_uebernimmt_belegten_port_nach_freigabe(self):
        """_httpd_binden gibt Port frei und bindet erneut — ohne hängendes shutdown."""
        import server

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wurzel = Path(tmp.name)
        env = wurzel / ".env"
        env.write_text(
            f"WALLET_0_NAME=A\nWALLET_0_XPUB={BIP84_ZPUB}\nWALLET_0_MAX_ADDRESSES=2\n",
            encoding="utf-8",
        )
        for name in ("utxo_cache", "immutable_cache", "sanctioned_cache"):
            (wurzel / name).mkdir()

        state = server.AppState(
            env,
            wurzel / "utxo_cache",
            wurzel / "immutable_cache",
            sanctions_dir=wurzel / "sanctioned_cache",
        )
        server.Handler.state = state

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        # Leichter Server (nicht Handler) — nur Port belegen
        erster = ThreadingHTTPServer(("127.0.0.1", port), _LeerHandler)
        thread = threading.Thread(target=erster.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)

        def free(p, host="127.0.0.1", nur_satsage=True):  # noqa: ARG001
            erster.shutdown()
            erster.server_close()
            thread.join(timeout=2.0)
            time.sleep(0.15)
            return [4242]

        with mock.patch.object(si, "port_freigeben_satsage", side_effect=free):
            httpd2 = server._httpd_binden(port)
            try:
                self.assertEqual(httpd2.server_address[1], port)
            finally:
                # serve_forever läuft nicht auf httpd2 → nur close, kein shutdown
                httpd2.server_close()


if __name__ == "__main__":
    unittest.main()
