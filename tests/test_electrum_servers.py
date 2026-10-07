"""Lokale Electrum-Serverliste: Alter und Nachziehen."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from core.electrum_servers import (
    electrum_servers_brauchen_update,
    lade_oder_aktualisiere_electrum_servers,
)


class TestElectrumServersAlter(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ziel = Path(self._tmp.name) / "electrum_servers.json"

    def _schreibe(self, daten, *, alter_sekunden=0):
        self.ziel.write_text(json.dumps(daten), encoding="utf-8")
        if alter_sekunden:
            stamp = time.time() - alter_sekunden
            os.utime(self.ziel, (stamp, stamp))

    def test_fehlt_braucht_update(self):
        self.assertTrue(electrum_servers_brauchen_update(self.ziel))

    def test_frisch_braucht_kein_update(self):
        self._schreibe({"a.example": {"s": "50002"}})
        self.assertFalse(electrum_servers_brauchen_update(self.ziel))

    def test_einen_tag_alt_braucht_update(self):
        self._schreibe({"a.example": {"s": "50002"}}, alter_sekunden=86400)
        self.assertTrue(electrum_servers_brauchen_update(self.ziel))

    def test_unter_einem_tag_bleibt(self):
        self._schreibe({"a.example": {"s": "50002"}}, alter_sekunden=23 * 3600)
        self.assertFalse(electrum_servers_brauchen_update(self.ziel))

    def test_lade_frisch_ohne_download(self):
        daten = {"a.example": {"s": "50002"}}
        self._schreibe(daten)
        with mock.patch(
            "core.electrum_servers.fetch_electrum_servers_json",
            side_effect=AssertionError("kein Download"),
        ):
            servers, refreshed = lade_oder_aktualisiere_electrum_servers(self.ziel)
        self.assertEqual(servers, daten)
        self.assertFalse(refreshed)

    def test_lade_alt_zieht_neu(self):
        self._schreibe({"alt.example": {"s": "50002"}}, alter_sekunden=2 * 86400)
        neu = {"neu.example": {"s": "50002"}}

        def fake(dest, url=None):
            Path(dest).write_text(json.dumps(neu), encoding="utf-8")
            return neu

        with mock.patch(
            "core.electrum_servers.fetch_electrum_servers_json",
            side_effect=fake,
        ):
            servers, refreshed = lade_oder_aktualisiere_electrum_servers(self.ziel)
        self.assertEqual(servers, neu)
        self.assertTrue(refreshed)

    def test_lade_alt_behaelt_lokal_wenn_download_scheitert(self):
        daten = {"alt.example": {"s": "50002"}}
        self._schreibe(daten, alter_sekunden=2 * 86400)
        with mock.patch(
            "core.electrum_servers.fetch_electrum_servers_json",
            side_effect=RuntimeError("offline"),
        ):
            servers, refreshed = lade_oder_aktualisiere_electrum_servers(self.ziel)
        self.assertEqual(servers, daten)
        self.assertFalse(refreshed)

    def test_lade_ohne_datei_reicht_download_fehler_weiter(self):
        with mock.patch(
            "core.electrum_servers.fetch_electrum_servers_json",
            side_effect=RuntimeError("offline"),
        ):
            with self.assertRaises(RuntimeError):
                lade_oder_aktualisiere_electrum_servers(self.ziel)


if __name__ == "__main__":
    unittest.main()
