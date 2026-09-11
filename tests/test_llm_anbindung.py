"""
LLM-Anbindung Phase 0: Einstufung, Pille, Status ohne Key-Leak.

Unit-Tests laufen ohne Netz. Zusätzlich schlagen Live-Tests gegen ein
laufendes Ollama auf 127.0.0.1:11434 zu — fehlen sie, werden sie übersprungen.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import server
from core import llm_anbindung as llm
from tests.fixtures import BIP84_ZPUB, ZWEITER_ALS_XPUB

OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_V1 = f"{OLLAMA_URL}/v1"


def _ollama_laeuft(timeout: float = 1.5) -> bool:
    """True, wenn der lokale Ollama-Prozess antwortet (Modelle dürfen leer sein)."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as ant:
            return 200 <= ant.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _ollama_hat_modell(name: str = "qwen2.5:7b", timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as ant:
            daten = json.loads(ant.read() or b"{}")
        namen = [m.get("name") or m.get("model") for m in daten.get("models") or []]
        return name in namen
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False


OLLAMA_DA = _ollama_laeuft()
OLLAMA_QWEN7B = OLLAMA_DA and _ollama_hat_modell("qwen2.5:7b")


class TestKlassifikation(unittest.TestCase):

    def test_loopback_hosts(self):
        for host in ("127.0.0.1", "::1", "localhost"):
            self.assertEqual(llm.klassifiziere_host(host), "loopback", host)

    def test_lan_und_remote(self):
        self.assertEqual(llm.klassifiziere_host("192.168.1.10"), "lan")
        self.assertEqual(llm.klassifiziere_host("10.0.0.2"), "lan")
        self.assertEqual(llm.klassifiziere_host("100.64.1.2"), "lan")
        self.assertEqual(llm.klassifiziere_host("api.x.ai"), "remote")
        self.assertEqual(llm.klassifiziere_host("8.8.8.8"), "remote")
        self.assertEqual(llm.klassifiziere_host("xyz.onion"), "onion")

    def test_anbieter_port_heuristik(self):
        cfg = llm.LlmConfig(
            base_url="http://127.0.0.1:11434/v1",
            api_key="",
            modell="llama3.2",
            anbieter="",
            betrieb_deklaration="",
            remote_opt_in=False,
        )
        self.assertEqual(llm.rate_anbieter(cfg, "127.0.0.1", 11434), "ollama")
        cfg_lm = llm.LlmConfig(
            "http://127.0.0.1:1234/v1", "", "x", "", "", False,
        )
        self.assertEqual(llm.rate_anbieter(cfg_lm, "127.0.0.1", 1234), "lmstudio")

    def test_widerspruch_loopback_deklaration(self):
        cfg = llm.LlmConfig(
            "https://api.x.ai/v1", "geheim", "grok", "api-key", "loopback", False,
        )
        betrieb, hinweis = llm.betrieb_effektiv(cfg, "api.x.ai")
        self.assertEqual(betrieb, "remote")
        self.assertIsNotNone(hinweis)


class TestPille(unittest.TestCase):

    def test_unkonfiguriert_grau(self):
        stufe, label = llm.pille_zustand(
            configured=False, checked=False, reachable=None, betrieb="",
        )
        self.assertEqual(stufe, "neutral")
        self.assertEqual(label, "LLM aus")

    def test_konfiguriert_ohne_check_grau(self):
        stufe, _ = llm.pille_zustand(
            configured=True, checked=False, reachable=None, betrieb="loopback",
        )
        self.assertEqual(stufe, "neutral")

    def test_offline_rot(self):
        stufe, label = llm.pille_zustand(
            configured=True, checked=True, reachable=False, betrieb="loopback",
        )
        self.assertEqual(stufe, "krit")
        self.assertEqual(label, "LLM offline")

    def test_lokal_gruen(self):
        stufe, label = llm.pille_zustand(
            configured=True, checked=True, reachable=True, betrieb="loopback",
        )
        self.assertEqual(stufe, "gut")
        self.assertEqual(label, "LLM lokal")

    def test_remote_gelb(self):
        for betrieb in ("remote", "lan", "onion"):
            stufe, label = llm.pille_zustand(
                configured=True, checked=True, reachable=True, betrieb=betrieb,
            )
            self.assertEqual(stufe, "warn", betrieb)
            self.assertEqual(label, "LLM remote")


class TestStatusDict(unittest.TestCase):

    def test_leer(self):
        s = llm.status_dict({})
        self.assertFalse(s["configured"])
        self.assertEqual(s["pille"], "neutral")
        self.assertEqual(s["datenmodus"], llm.DATENMODUS)
        self.assertFalse(s["api_key_set"])
        self.assertFalse(s["checked"])

    def test_ollama_ohne_probe(self):
        s = llm.status_dict({
            "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
            "LLM_MODELL": "llama3.2",
            "LLM_ANBIETER": "ollama",
        })
        self.assertTrue(s["configured"])
        self.assertEqual(s["anbieter"], "ollama")
        self.assertEqual(s["betrieb"], "loopback")
        self.assertEqual(s["privacy_stufe"], "hoch")
        self.assertEqual(s["pille"], "neutral")
        self.assertIn("Ollama", s["banner"])
        self.assertIn("llama3.2", s["banner"])
        self.assertIn("nur Cache", s["banner"])

    def test_api_key_nie_im_status(self):
        geheim = "xpq-llm-geheimnis-9c4e1b"
        s = llm.status_dict({
            "LLM_BASE_URL": "https://api.x.ai/v1",
            "LLM_API_KEY": geheim,
            "LLM_MODELL": "grok-4.5",
            "LLM_ANBIETER": "api-key",
            "LLM_REMOTE_OPT_IN": "1",
        })
        dump = json.dumps(s)
        self.assertNotIn(geheim, dump)
        self.assertTrue(s["api_key_set"])
        self.assertEqual(s["betrieb"], "remote")
        self.assertEqual(s["privacy_stufe"], "niedrig")
        self.assertIn("API-Key zu", s["banner"])

    def test_check_lokal_erreichbar(self):
        def fake_probe(cfg, timeout=2.5):
            return True, ""

        s = llm.status_dict(
            {
                "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
                "LLM_MODELL": "llama3.2",
            },
            check=True,
            probe_fn=fake_probe,
        )
        self.assertTrue(s["checked"])
        self.assertTrue(s["reachable"])
        self.assertEqual(s["pille"], "gut")
        self.assertEqual(s["pille_label"], "LLM lokal")

    def test_check_remote_erreichbar(self):
        s = llm.status_dict(
            {
                "LLM_BASE_URL": "https://api.x.ai/v1",
                "LLM_API_KEY": "k",
                "LLM_MODELL": "grok-4.5",
                "LLM_REMOTE_OPT_IN": "1",
            },
            check=True,
            probe_fn=lambda cfg, timeout=2.5: (True, ""),
        )
        self.assertEqual(s["pille"], "warn")
        self.assertEqual(s["pille_label"], "LLM remote")

    def test_check_offline(self):
        s = llm.status_dict(
            {"LLM_BASE_URL": "http://127.0.0.1:11434/v1", "LLM_MODELL": "x"},
            check=True,
            probe_fn=lambda cfg, timeout=2.5: (False, "timed out"),
        )
        self.assertEqual(s["pille"], "krit")
        self.assertIn("timed out", s["probe_error"])


class TestApiLlmStatus(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        wurzel = Path(self._tmp.name)
        self.env_pfad = wurzel / ".env"
        self.env_pfad.write_text(
            f"XPUBS={BIP84_ZPUB} {ZWEITER_ALS_XPUB}\n"
            "WALLET_NAMES=A|B\n"
            "MAX_ADDRESSES_PER_XPUB=6|6\n"
            "FULCRUM_HOST=192.0.2.1\n"
            "LLM_BASE_URL=http://127.0.0.1:11434/v1\n"
            "LLM_MODELL=llama3.2\n"
            "LLM_API_KEY=xpq-llm-api-key-soll-nicht-raus\n",
            encoding="utf-8",
        )
        cache = wurzel / "utxo_cache"
        cache.mkdir()
        immutable = wurzel / "immutable_cache"
        immutable.mkdir()
        sanktionen = wurzel / "sanctioned_cache"
        sanktionen.mkdir()
        self.state = server.AppState(
            self.env_pfad, cache, immutable, sanctions_dir=sanktionen,
        )
        server.Handler.state = self.state
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01},
            daemon=True,
        ).start()
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)

    def anfrage(self, pfad, methode="GET", daten=None):
        url = f"http://127.0.0.1:{self.port}{pfad}"
        körper = None
        headers = {
            "Host": f"127.0.0.1:{self.port}",
            "X-Satsage-Token": self.state.token,
        }
        if daten is not None:
            körper = json.dumps(daten).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=körper, method=methode, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as antwort:
                return antwort.status, json.loads(antwort.read() or b"{}")
        except urllib.error.HTTPError as exc:
            roh = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(roh) if roh else {}
            except json.JSONDecodeError:
                parsed = {"error": roh}
            return exc.code, parsed

    def test_status_ohne_check(self):
        status, körper = self.anfrage("/api/llm/status")
        self.assertEqual(status, 200)
        self.assertTrue(körper["configured"])
        self.assertEqual(körper["pille"], "neutral")
        self.assertFalse(körper["checked"])
        dump = json.dumps(körper)
        self.assertNotIn("xpq-llm-api-key-soll-nicht-raus", dump)
        self.assertTrue(körper["api_key_set"])

    def test_status_mit_check_mock(self):
        with mock.patch(
            "core.llm_anbindung.probe_erreichbar",
            return_value=(True, ""),
        ):
            status, körper = self.anfrage("/api/llm/status?check=1")
        self.assertEqual(status, 200)
        self.assertTrue(körper["reachable"])
        self.assertEqual(körper["pille"], "gut")

    def test_config_enthaelt_llm_ohne_key(self):
        status, körper = self.anfrage("/api/config")
        self.assertEqual(status, 200)
        self.assertIn("llm", körper)
        self.assertTrue(körper["llm"]["configured"])
        self.assertTrue(körper["llm"]["api_key_set"])
        dump = json.dumps(körper)
        self.assertNotIn("xpq-llm-api-key-soll-nicht-raus", dump)
        self.assertFalse(körper["llm"]["checked"])

    def test_save_ollama_ohne_key_und_ohne_xai_alias(self):
        status, körper = self.anfrage(
            "/api/config/llm",
            methode="PUT",
            daten={
                "base_url": "http://127.0.0.1:11434/v1",
                "modell": "qwen2.5:7b",
                "anbieter": "ollama",
                "remote_opt_in": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(körper["saved"])
        self.assertEqual(körper["llm"]["modell"], "qwen2.5:7b")
        self.assertEqual(körper["llm"]["anbieter"], "ollama")
        self.assertEqual(körper["llm"]["betrieb"], "loopback")
        werte = self.state.env().values()
        self.assertEqual(werte.get("LLM_MODELL"), "qwen2.5:7b")
        self.assertNotIn("XAI_API_KEY", werte)
        # Leeres Key-Feld ändert einen vorhandenen Key nicht — und legt
        # keinen XAI-Alias an.
        self.assertEqual(
            werte.get("LLM_API_KEY"), "xpq-llm-api-key-soll-nicht-raus",
        )

    def test_save_leerer_key_laesst_vorhandenen(self):
        status, körper = self.anfrage(
            "/api/config/llm",
            methode="PUT",
            daten={
                "base_url": "http://127.0.0.1:11434/v1",
                "modell": "qwen2.5:7b",
                "anbieter": "ollama",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(körper["llm"]["api_key_set"])
        self.assertEqual(
            self.state.env().values().get("LLM_API_KEY"),
            "xpq-llm-api-key-soll-nicht-raus",
        )

    def test_save_lehnt_xai_api_key_feld_ab(self):
        status, körper = self.anfrage(
            "/api/config/llm",
            methode="PUT",
            daten={
                "base_url": "http://127.0.0.1:11434/v1",
                "anbieter": "ollama",
                "XAI_API_KEY": "darf-nicht-angenommen-werden",
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("XAI_API_KEY", körper.get("error", ""))
        self.assertNotIn("XAI_API_KEY", self.state.env().values())

    def test_context_luecken_ohne_cache(self):
        status, körper = self.anfrage("/api/llm/context/luecken")
        self.assertEqual(status, 200)
        self.assertIn("punkte", körper)
        self.assertIn("text", körper)
        self.assertTrue(körper["ohne_cache"])
        dump = json.dumps(körper)
        self.assertNotIn("xpq-llm-api-key-soll-nicht-raus", dump)
        self.assertNotIn(BIP84_ZPUB, dump)

    def test_context_wallets_und_steuer(self):
        status, wallets = self.anfrage("/api/llm/context/wallets")
        self.assertEqual(status, 200)
        self.assertIn("wallets", wallets)
        status, steuer = self.anfrage("/api/llm/context/steuer?jahr=2023")
        self.assertEqual(status, 200)
        self.assertEqual(steuer["jahr"], 2023)
        self.assertIn("kennzahlen", steuer)
        self.assertNotIn("eintraege", steuer)
        status, legende = self.anfrage("/api/llm/context/export?art=legende&jahr=2023")
        self.assertEqual(status, 200)
        self.assertEqual(legende["art"], "legende")
        self.assertIn("text", legende)
        status, md = self.anfrage("/api/llm/context/export?art=markdown&jahr=2023")
        self.assertEqual(status, 200)
        self.assertEqual(md["art"], "markdown")
        status, brief = self.anfrage("/api/llm/context/export?art=brief&jahr=2023")
        self.assertEqual(status, 200)
        self.assertEqual(brief["art"], "brief")
        self.assertNotIn(BIP84_ZPUB, json.dumps(brief))

    def test_context_nur_get(self):
        status, körper = self.anfrage(
            "/api/llm/context/luecken", methode="POST", daten={},
        )
        self.assertEqual(status, 405)
        self.assertIn("keine Jobs", körper.get("error", ""))
        status, _ = self.anfrage("/api/llm/context/scan")
        self.assertEqual(status, 404)

    def test_chat_remote_ohne_opt_in_bleibt_zu(self):
        self.anfrage(
            "/api/config/llm",
            methode="PUT",
            daten={
                "base_url": "https://api.x.ai/v1",
                "modell": "grok-4.5",
                "anbieter": "api-key",
                "remote_opt_in": False,
            },
        )
        with mock.patch.object(self.state.jobs, "start") as start:
            status, körper = self.anfrage(
                "/api/llm/chat",
                methode="POST",
                daten={"messages": [{"role": "user", "content": "hi"}]},
            )
        self.assertEqual(status, 403)
        self.assertIn("Freigabe", körper.get("error", ""))
        start.assert_not_called()

    def test_chat_remote_mit_opt_in_nur_gemockt(self):
        self.anfrage(
            "/api/config/llm",
            methode="PUT",
            daten={
                "base_url": "https://api.x.ai/v1",
                "modell": "grok-4.5",
                "anbieter": "api-key",
                "remote_opt_in": True,
            },
        )
        with mock.patch(
            "server.llm_chat.fuehre_chat",
            return_value={"text": "Remote-Mock.", "tools_used": [], "rundungen": 1},
        ) as fn, mock.patch.object(self.state.jobs, "start") as start:
            status, körper = self.anfrage(
                "/api/llm/chat",
                methode="POST",
                daten={"messages": [{"role": "user", "content": "hi"}]},
            )
        self.assertEqual(status, 200)
        self.assertEqual(körper["text"], "Remote-Mock.")
        start.assert_not_called()
        fn.assert_called_once()

    def test_chat_loopback_mock_ohne_job(self):
        with mock.patch(
            "server.llm_chat.fuehre_chat",
            return_value={"text": "Hallo aus dem Cache.", "tools_used": ["luecken"], "rundungen": 1},
        ) as fn, mock.patch.object(self.state.jobs, "start") as start:
            status, körper = self.anfrage(
                "/api/llm/chat",
                methode="POST",
                daten={"messages": [{"role": "user", "content": "Was fehlt?"}]},
            )
        self.assertEqual(status, 200)
        self.assertEqual(körper["text"], "Hallo aus dem Cache.")
        self.assertEqual(körper["tools_used"], ["luecken"])
        start.assert_not_called()
        fn.assert_called_once()

    def test_save_liest_keinen_prozess_xai_key(self):
        with mock.patch.dict(
            "os.environ",
            {"XAI_API_KEY": "prozess-xai-key-darf-nicht-wandern"},
            clear=False,
        ):
            status, körper = self.anfrage(
                "/api/config/llm",
                methode="PUT",
                daten={
                    "base_url": "http://127.0.0.1:11434/v1",
                    "modell": "qwen2.5:7b",
                    "anbieter": "ollama",
                },
            )
        self.assertEqual(status, 200)
        werte = self.state.env().values()
        self.assertNotIn("XAI_API_KEY", werte)
        dump = json.dumps(körper)
        self.assertNotIn("prozess-xai-key-darf-nicht-wandern", dump)


@unittest.skipUnless(OLLAMA_DA, "Kein laufendes Ollama auf 127.0.0.1:11434")
class TestOllamaLive(unittest.TestCase):
    """Echte Probe gegen installiertes Ollama — kein Mock."""

    def test_probe_erreichbar(self):
        cfg = llm.LlmConfig(
            base_url=OLLAMA_V1,
            api_key="",
            modell="",
            anbieter="ollama",
            betrieb_deklaration="",
            remote_opt_in=False,
        )
        ok, fehler = llm.probe_erreichbar(cfg)
        self.assertTrue(ok, fehler)
        self.assertEqual(fehler, "")

    def test_probe_ohne_v1_suffix(self):
        """Auch die Native-URL ohne /v1 muss greifen (api/tags-Fallback)."""
        cfg = llm.LlmConfig(
            base_url=OLLAMA_URL,
            api_key="",
            modell="",
            anbieter="ollama",
            betrieb_deklaration="",
            remote_opt_in=False,
        )
        ok, fehler = llm.probe_erreichbar(cfg)
        self.assertTrue(ok, fehler)

    @unittest.skipUnless(OLLAMA_QWEN7B, "Ollama ohne qwen2.5:7b")
    def test_qwen_ist_geladen(self):
        """Der Hotel-Testlauf erwartet qwen2.5:7b in Ollama — sonst Skip bleibt."""
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as ant:
            daten = json.loads(ant.read() or b"{}")
        namen = [m.get("name") or m.get("model") for m in daten.get("models") or []]
        self.assertIn("qwen2.5:7b", namen)

    @unittest.skipUnless(OLLAMA_QWEN7B, "Ollama ohne qwen2.5:7b")
    def test_status_check_gruene_pille(self):
        s = llm.status_dict(
            {
                "LLM_BASE_URL": OLLAMA_V1,
                "LLM_ANBIETER": "ollama",
                "LLM_MODELL": "qwen2.5:7b",
            },
            check=True,
        )
        self.assertTrue(s["checked"])
        self.assertTrue(s["reachable"])
        self.assertEqual(s["betrieb"], "loopback")
        self.assertEqual(s["anbieter"], "ollama")
        self.assertEqual(s["pille"], "gut")
        self.assertEqual(s["pille_label"], "LLM lokal")
        self.assertEqual(s["privacy_stufe"], "hoch")
        self.assertEqual(s["probe_error"], "")
        self.assertEqual(s["modell"], "qwen2.5:7b")
        self.assertIn("qwen2.5:7b", s["banner"])

    def test_api_status_check_live(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wurzel = Path(tmp.name)
        env_pfad = wurzel / ".env"
        env_pfad.write_text(
            f"XPUBS={BIP84_ZPUB} {ZWEITER_ALS_XPUB}\n"
            "WALLET_NAMES=A|B\n"
            "MAX_ADDRESSES_PER_XPUB=6|6\n"
            "FULCRUM_HOST=192.0.2.1\n"
            f"LLM_BASE_URL={OLLAMA_V1}\n"
            "LLM_ANBIETER=ollama\n"
            "LLM_MODELL=qwen2.5:7b\n",
            encoding="utf-8",
        )
        cache = wurzel / "utxo_cache"
        cache.mkdir()
        immutable = wurzel / "immutable_cache"
        immutable.mkdir()
        sanktionen = wurzel / "sanctioned_cache"
        sanktionen.mkdir()
        state = server.AppState(
            env_pfad, cache, immutable, sanctions_dir=sanktionen,
        )
        server.Handler.state = state
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = httpd.server_address[1]
        threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.01},
            daemon=True,
        ).start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)

        url = f"http://127.0.0.1:{port}/api/llm/status?check=1"
        req = urllib.request.Request(url)
        req.add_header("Host", f"127.0.0.1:{port}")
        req.add_header("X-Satsage-Token", state.token)
        with urllib.request.urlopen(req, timeout=10) as antwort:
            körper = json.loads(antwort.read() or b"{}")
        self.assertTrue(körper["reachable"])
        self.assertEqual(körper["pille"], "gut")
        self.assertEqual(körper["anbieter"], "ollama")
        self.assertFalse(körper["api_key_set"])

    @unittest.skipUnless(OLLAMA_QWEN7B, "Ollama ohne qwen2.5:7b")
    def test_chat_loopback_live(self):
        from core import llm_client as chat_mod

        cfg = llm.lese_llm_chat_einstellungen({
            "LLM_BASE_URL": OLLAMA_V1,
            "LLM_ANBIETER": "ollama",
            "LLM_MODELL": "qwen2.5:7b",
        })
        ergebnis = chat_mod.fuehre_chat(
            cfg,
            [{"role": "user", "content": "Antworte mit genau einem Wort: bereit"}],
            tools_fn=lambda name, args: "Testdaten: keine Wallets im Cache.",
            timeout=90,
        )
        self.assertTrue(ergebnis["text"].strip())
        self.assertNotIn("scan", ergebnis["tools_used"])


if __name__ == "__main__":
    unittest.main()
