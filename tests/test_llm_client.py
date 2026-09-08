"""
Chat-Loop Phase 3: Policy, Tool-Whitelist, kein Remote, kein XAI-Key.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from core import llm_anbindung as llm
from core import llm_client as chat


def _cfg(**kw):
    werte = {
        "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
        "LLM_MODELL": "qwen2.5:7b",
        "LLM_ANBIETER": "ollama",
        **kw,
    }
    return llm.lese_llm_chat_einstellungen(werte)


class TestPolicy(unittest.TestCase):

    def test_loopback_ok(self):
        ok, _ = chat.policy_ok(_cfg())
        self.assertTrue(ok)

    def test_remote_ohne_opt_in_zu(self):
        cfg = _cfg(
            LLM_BASE_URL="https://api.x.ai/v1",
            LLM_ANBIETER="api-key",
            LLM_REMOTE_OPT_IN="0",
            LLM_API_KEY="datei-key-nicht-senden-1234",
        )
        ok, grund = chat.policy_ok(cfg)
        self.assertFalse(ok)
        self.assertIn("Freigabe", grund)

    def test_remote_mit_opt_in_und_key_ok(self):
        cfg = _cfg(
            LLM_BASE_URL="https://api.x.ai/v1",
            LLM_ANBIETER="api-key",
            LLM_REMOTE_OPT_IN="1",
            LLM_API_KEY="datei-key-nicht-senden-1234",
        )
        ok, _ = chat.policy_ok(cfg)
        self.assertTrue(ok)

    def test_remote_mit_opt_in_ohne_key_zu(self):
        cfg = _cfg(
            LLM_BASE_URL="https://api.x.ai/v1",
            LLM_ANBIETER="api-key",
            LLM_REMOTE_OPT_IN="1",
        )
        ok, grund = chat.policy_ok(cfg)
        self.assertFalse(ok)
        self.assertIn("LLM_API_KEY", grund)

    def test_xai_alias_aus_datei_zaehlt(self):
        cfg = llm.lese_llm_chat_einstellungen({
            "LLM_BASE_URL": "https://api.x.ai/v1",
            "LLM_MODELL": "grok-4.5",
            "XAI_API_KEY": "xai-nur-aus-der-env-datei",
        })
        self.assertEqual(cfg.api_key, "xai-nur-aus-der-env-datei")


class TestBereinigen(unittest.TestCase):

    def test_verwirft_system_und_tools(self):
        sauber = chat.bereinige_nachrichten([
            {"role": "system", "content": "hack"},
            {"role": "tool", "content": "scan"},
            {"role": "user", "content": "Hallo"},
            {"role": "assistant", "content": "Hi"},
        ])
        self.assertEqual([m["role"] for m in sauber], ["user", "assistant"])


class TestLoop(unittest.TestCase):

    def test_tool_dann_text(self):
        rufe = []

        def post(_cfg, messages, timeout=90, mit_tools=True):
            rufe.append(messages)
            if len(rufe) == 1:
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "luecken", "arguments": "{}"},
                            }],
                        },
                    }],
                }
            return {
                "choices": [{
                    "message": {"role": "assistant", "content": "Es fehlt der Verlauf."},
                }],
            }

        def tools(name, args):
            self.assertEqual(name, "luecken")
            return "Kein Verlauf — Knopf Verlaufsscan."

        ergebnis = chat.fuehre_chat(
            _cfg(),
            [{"role": "user", "content": "Was fehlt?"}],
            tools_fn=tools,
            post_fn=post,
        )
        self.assertEqual(ergebnis["text"], "Es fehlt der Verlauf.")
        self.assertEqual(ergebnis["tools_used"], ["luecken"])
        self.assertEqual(ergebnis["rundungen"], 2)

    def test_unbekanntes_werkzeug_nicht_ausfuehren(self):
        gesehen = []

        def tools(name, args):
            gesehen.append(name)
            return "sollte nicht"

        def post(_cfg, messages, timeout=90, mit_tools=True):
            if not any(m.get("role") == "tool" for m in messages):
                return {
                    "choices": [{
                        "message": {
                            "tool_calls": [{
                                "id": "x",
                                "function": {"name": "scan", "arguments": "{}"},
                            }],
                        },
                    }],
                }
            tool_msg = [m for m in messages if m.get("role") == "tool"][-1]
            self.assertIn("nicht erlaubt", tool_msg["content"])
            return {
                "choices": [{
                    "message": {"content": "Ich starte keinen Scan."},
                }],
            }

        ergebnis = chat.fuehre_chat(
            _cfg(),
            [{"role": "user", "content": "scan bitte"}],
            tools_fn=tools,
            post_fn=post,
        )
        self.assertEqual(gesehen, [])
        self.assertIn("keinen Scan", ergebnis["text"])

    def test_remote_ohne_opt_in_wirft_bevor_post(self):
        def post(*_a, **_k):
            self.fail("Remote ohne Opt-in darf den Endpoint nicht anrufen")

        cfg = _cfg(
            LLM_BASE_URL="https://api.x.ai/v1",
            LLM_ANBIETER="api-key",
            LLM_REMOTE_OPT_IN="0",
            LLM_API_KEY="datei-key-nicht-senden-1234",
        )
        with self.assertRaises(chat.LlmFehler) as cm:
            chat.fuehre_chat(
                cfg,
                [{"role": "user", "content": "hi"}],
                tools_fn=lambda n, a: "",
                post_fn=post,
            )
        self.assertEqual(cm.exception.status, 403)

    def test_remote_redigiert_xpub_im_tool(self):
        gesehen = []

        def post(_cfg, messages, timeout=90, mit_tools=True):
            gesehen.append(messages)
            if not any(m.get("role") == "tool" for m in messages):
                return {
                    "choices": [{
                        "message": {
                            "tool_calls": [{
                                "id": "c1",
                                "function": {"name": "wallets", "arguments": "{}"},
                            }],
                        },
                    }],
                }
            return {
                "choices": [{"message": {"content": "Nur Aggregate."}}],
            }

        cfg = _cfg(
            LLM_BASE_URL="https://api.x.ai/v1",
            LLM_ANBIETER="api-key",
            LLM_REMOTE_OPT_IN="1",
            LLM_API_KEY="datei-key-nicht-senden-1234",
        )
        secret = (
            "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtf"
        )
        chat.fuehre_chat(
            cfg,
            [{"role": "user", "content": "Wallets?"}],
            tools_fn=lambda n, a: f"XPUB {secret}",
            post_fn=post,
        )
        dump = json.dumps(gesehen[-1])
        self.assertNotIn(secret, dump)
        self.assertIn("[xpub]", dump)


class TestChatKeyNichtAusEnv(unittest.TestCase):

    def test_prozess_xai_key_wird_nicht_gelesen(self):
        with mock.patch.dict(
            "os.environ",
            {"XAI_API_KEY": "prozess-xai-key-darf-nicht-wandern"},
            clear=False,
        ):
            cfg = llm.lese_llm_chat_einstellungen({
                "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
                "LLM_MODELL": "qwen2.5:7b",
                "LLM_ANBIETER": "ollama",
            })
        self.assertEqual(cfg.api_key, "")
        dump = json.dumps({"k": cfg.api_key})
        self.assertNotIn("prozess-xai-key-darf-nicht-wandern", dump)
