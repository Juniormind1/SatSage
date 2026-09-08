"""
Phase 5: Härtung des Assistenten — DoD ohne Netz und ohne echten Cloud-Key.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main
from core import llm_anbindung as llm
from core import llm_context as ctx
from core import tax as tax_mod
from tests.fixtures import BIP84_RECEIVE_0, BIP84_ZPUB, txid
from tests.test_steuer_grundlage import utxo

WEB = Path(__file__).resolve().parent.parent / "web"
HANDBUCH = Path(__file__).resolve().parent.parent / "doc" / "handbuch.html"
GUI_JINJA = (
    Path(__file__).resolve().parent.parent
    / "specter_plugin/src/satsage/specterext/satsage/templates/satsage/gui.jinja"
)

BLOCKLISTE = (
    "scan", "rescan", "verlauf", "herkunft", "sanktion", "sync", "fetch",
    "exec", "shell", "python", "eval", "system",
    "env", "xpub", "key", "seed", "token", "api-key",
    "delete", "cache-loeschen", "danger", "reset-all",
    "send", "broadcast", "sign", "psbt",
    "url", "http", "curl", "download",
)


class TestSlashBlockliste(unittest.TestCase):

    def test_alle_gesperrten_befehle_stehen_im_client(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        for befehl in BLOCKLISTE:
            self.assertIn(f'"{befehl}"', js, befehl)
        self.assertIn("ist gesperrt", js)
        self.assertNotIn("/v1/chat/completions", js)


class TestStatusOhneSecrets(unittest.TestCase):

    def test_status_enthaelt_keinen_key(self):
        geheim = "xpq-haertung-key-nicht-im-status"
        s = llm.status_dict({
            "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
            "LLM_MODELL": "qwen2.5:7b",
            "LLM_API_KEY": geheim,
        })
        dump = json.dumps(s, ensure_ascii=False)
        self.assertNotIn(geheim, dump)
        self.assertTrue(s["api_key_set"])
        self.assertIn("nur Cache", s["banner"])


class TestSteuerZahlenAusCache(unittest.TestCase):

    def test_kompakt_nimmt_kennzahlen_unverändert(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache = Path(tmp.name) / "utxo_cache"
        cache.mkdir()
        immutable = Path(tmp.name) / "immutable"
        immutable.mkdir()
        eintrag = utxo("a1", 250_000)
        main.save_xpub_utxo_cache(BIP84_ZPUB, [eintrag], cache, "test")
        auswertung = tax_mod.auswerten(
            [eintrag], 2023,
            haltefrist_jahre=1,
            immutable_cache_dir=immutable,
        )
        kompakt = ctx.steuer_kompakt(auswertung)
        self.assertEqual(kompakt["kennzahlen"], auswertung["kennzahlen"])
        csv = tax_mod.als_csv(auswertung)
        self.assertIn(b"Steuerjahr", csv)
        self.assertIn(b"250000", csv.replace(b".", b"").replace(b",", b""))
        brief = ctx.export_brief(auswertung)
        self.assertNotIn(BIP84_RECEIVE_0, brief["text"])
        self.assertNotIn(txid("a1"), brief["text"])


class TestHandbuchUndSpecter(unittest.TestCase):

    def test_handbuch_abschnitt_assistent(self):
        html = HANDBUCH.read_text(encoding="utf-8")
        self.assertIn('id="assistent"', html)
        self.assertIn("/luecken", html)
        self.assertIn("Keine Scans aus dem Chat", html)
        self.assertIn("LLM_API_KEY", html)
        self.assertIn("/api/llm/status", html)
        self.assertIn("/api/llm/chat", html)

    def test_specter_iframe_laesst_dock_zu(self):
        jinja = GUI_JINJA.read_text(encoding="utf-8")
        self.assertIn("xpq-gui-frame", jinja)
        treffer = re.search(r"min-height:(\d+)px", jinja)
        self.assertIsNotNone(treffer)
        self.assertGreaterEqual(int(treffer.group(1)), 640)


class TestChatStartetKeinenJob(unittest.TestCase):

    def test_werkzeug_scan_ruft_jobs_nicht(self):
        import server

        class Dummy:
            jobs = mock.Mock()
            analyse_entries = []
            cache_dir = Path("/tmp")
            immutable_cache_dir = Path("/tmp")

        text = server._llm_werkzeug(Dummy(), "scan", {})
        self.assertIn("nicht erlaubt", text)
        Dummy.jobs.start.assert_not_called()
