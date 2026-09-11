"""Specter-Plugin: GUI-Server speist Wallets ohne echte Specter-Instanz."""
from __future__ import annotations

import urllib.error
import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from tests.fixtures import BIP84_ZPUB

_PLUGIN_SRC = (
    Path(__file__).resolve().parent.parent / "specter_plugin" / "src"
)
if str(_PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_SRC))


class TestGuiServer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # gui_server schreibt unter Repo/specter_plugin/.specter_dev — für den
        # Test auf Temporäres umbiegen.
        self.dev = Path(self._tmp.name) / ".specter_dev"
        self.dev.mkdir()

    def test_ensure_schreibt_env_und_startet_server(self):
        from satsage.specterext.satsage import gui_server
        from satsage.specterext.satsage.bridge import (
            SpecterWalletInfo,
            SatSageContext,
        )

        ctx = SatSageContext(
            wallets=[
                SpecterWalletInfo(
                    name="Specter Cold",
                    alias="cold",
                    xpubs=[BIP84_ZPUB],
                )
            ]
        )

        with mock.patch.object(gui_server, "_specter_dev_dir", return_value=self.dev), \
             mock.patch.object(gui_server, "build_context", return_value=ctx), \
             mock.patch.object(
                 gui_server, "context_fingerprint", return_value="fp-test"
             ), \
             mock.patch.object(gui_server, "_seed_caches", return_value={}), \
             mock.patch.object(gui_server, "_server", None), \
             mock.patch.object(gui_server, "_fingerprint", ""):
            # Modul-Globals zurücksetzen, falls andere Tests liefen.
            gui_server._server = None
            gui_server._fingerprint = ""
            info = gui_server.ensure_gui_server(specter=object())
            self.addCleanup(lambda: gui_server._server and gui_server._server.stop())

        self.assertTrue(info["neu_gestartet"])
        self.assertEqual(info["wallet_count"], 1)
        self.assertTrue((self.dev / "satsage.env").is_file())

        req = urllib.request.Request(
            f"http://127.0.0.1:{info['port']}/api/config",
            headers={"X-Satsage-Token": info["token"]},
        )
        with urllib.request.urlopen(req, timeout=5) as antwort:
            daten = json.loads(antwort.read())
        namen = [w["name"] for w in daten["wallets"]]
        self.assertEqual(daten["managed_by"], "specter")
        req_write = urllib.request.Request(
            f"http://127.0.0.1:{info['port']}/api/config/wallets",
            data=b"{}", method="PUT",
            headers={"X-Satsage-Token": info["token"], "Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as write_error:
            urllib.request.urlopen(req_write, timeout=5)
        self.assertEqual(write_error.exception.code, 403)
        self.assertIn("Specter", daten["managed_hint"])
        self.assertIn("Wallets", daten["managed_hint"])
        self.assertIn("Specter Cold", namen)


if __name__ == "__main__":
    unittest.main()
