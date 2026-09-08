"""Hintergrund-Start der Web-GUI (Specter-iframe / Einbettung)."""
from __future__ import annotations

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

import server
from tests.fixtures import BIP84_ZPUB, ZWEITER_ALS_XPUB


class TestStarteImHintergrund(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        wurzel = Path(self._tmp.name)
        self.env = wurzel / ".env"
        self.env.write_text(
            f"XPUBS={BIP84_ZPUB}\nWALLET_NAMES=Test\nMAX_ADDRESSES_PER_XPUB=4\n",
            encoding="utf-8",
        )
        self.cache = wurzel / "utxo_cache"
        self.cache.mkdir()
        self.immutable = wurzel / "immutable_cache"
        self.immutable.mkdir()
        self.sanktionen = wurzel / "sanctioned_cache"
        self.sanktionen.mkdir()

    def test_liefert_url_mit_token_und_antwortet(self):
        state = server.AppState(
            self.env, self.cache, self.immutable, sanctions_dir=self.sanktionen,
        )
        # Port 0 erzwingen: belegter Default darf den Test nicht stören —
        # starte_im_hintergrund fällt bei OSError selbst auf 0 zurück; hier
        # direkt freien Port, indem wir einen belegten vortäuschen ist unnötig.
        eingebettet = server.starte_im_hintergrund(state, port=0)
        self.addCleanup(eingebettet.stop)

        self.assertIn("://127.0.0.1:", eingebettet.url)
        self.assertIn(f"t={eingebettet.token}", eingebettet.url)
        self.assertGreater(eingebettet.port, 0)

        req = urllib.request.Request(
            f"http://127.0.0.1:{eingebettet.port}/api/config",
            headers={"X-Satsage-Token": eingebettet.token},
        )
        with urllib.request.urlopen(req, timeout=5) as antwort:
            daten = json.loads(antwort.read())
        self.assertEqual(len(daten["wallets"]), 1)
        self.assertEqual(daten["wallets"][0]["name"], "Test")

    def test_belegter_port_weicht_aus(self):
        state_a = server.AppState(
            self.env, self.cache, self.immutable, sanctions_dir=self.sanktionen,
        )
        erster = server.starte_im_hintergrund(state_a, port=0)
        self.addCleanup(erster.stop)

        # Zweite Instanz will denselben Port — OSError → freier Port.
        env2 = Path(self._tmp.name) / "b.env"
        env2.write_text(
            f"XPUBS={ZWEITER_ALS_XPUB}\nWALLET_NAMES=Zwei\nMAX_ADDRESSES_PER_XPUB=4\n",
            encoding="utf-8",
        )
        state_b = server.AppState(
            env2, self.cache, self.immutable, sanctions_dir=self.sanktionen,
        )
        zweiter = server.starte_im_hintergrund(state_b, port=erster.port)
        self.addCleanup(zweiter.stop)

        self.assertNotEqual(erster.port, zweiter.port)
        self.assertNotEqual(erster.token, zweiter.token)


if __name__ == "__main__":
    unittest.main()
