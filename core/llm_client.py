"""
OpenAI-kompatibler Chat-Loop für den Assistenten.

Loopback/LAN immer. Remote/Onion nur nach ``LLM_REMOTE_OPT_IN``.
Werkzeuge sind Cache-Reader und deterministische Report-Renderer. Kein Job-Start.
"""
from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Callable

from core import llm_anbindung as llm
from outbound_policy import OutboundPolicyError, ensure_url_allowed

CHAT_TIMEOUT_S = 90
MAX_TOOL_RUNDEN = 4
MAX_NACHRICHTEN = 12
MAX_CONTENT = 4000

ERLAUBTE_TOOLS = frozenset({
    "luecken", "wallets", "steuer",
    "export", "export_legende", "export_markdown", "export_brief",
})

_XPUB_RE = re.compile(r"\b[xyzvt]pub[1-9A-HJ-NP-Za-km-z]{20,}\b", re.I)
_TXID_RE = re.compile(r"\b[0-9a-f]{64}\b", re.I)
_BECH32_RE = re.compile(r"\bbc1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{20,}\b", re.I)
_LEGACY_RE = re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")

SYSTEM_PROMPT = """Du bist der lokale Assistent von SatSage.
Du liest nur den lokalen Cache über die Werkzeuge luecken, wallets, steuer und export.
export.art ist legende, markdown oder brief — die Zahlen kommen aus dem Cache, nicht von dir.
Du startest keine Scans, keine Jobs und keine Netzwerkabfragen.
Zahlen und Bestände nennst du nur, wenn ein Werkzeug sie geliefert hat — nichts erfinden.
Fehlt Cache, Verlauf oder Herkunft: sag den passenden Knopf und dass es dauern kann (Kaffee).
Keine Steuerberatung, keine Rechtsfolgen, kein „du musst“.
On-Chain-Daten ersetzen keine Börsenhistorien, Kaufbelege oder Kontoauszüge — sie ergänzen sie nur.
Keine XPUBs, Seeds, API-Keys, vollen Adressen oder TxIDs.
Antworten auf Deutsch, knapp, mit Quellenbezug („laut Cache“ / „laut Steuerjahr-Auswertung“).
"""

SYSTEM_REMOTE = (
    "\nDu läufst remote (Cloud). Schicke nur Aggregate und Wallet-Namen. "
    "Keine Adressen, TxIDs, XPUBs. Der maßgebliche Steuer-Export bleibt CSV/HTML."
)

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "luecken",
            "description": (
                "Was im lokalen Cache fehlt und welche Knöpfe das füllen. "
                "Kein Scan."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wallets",
            "description": "Wallet-Namen und grober Cache-Stand (UTXO/Verlauf).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "steuer",
            "description": (
                "Kennzahlen der Steuerjahr-Auswertung aus dem Cache. "
                "Keine Beratung."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "jahr": {
                        "type": "integer",
                        "description": "Steuerjahr, z. B. 2024. Leer = Vorgabe.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export",
            "description": (
                "Deterministischer Text aus der Steuerauswertung: "
                "legende, markdown oder brief. Kein neuer autoritativer Report."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "art": {
                        "type": "string",
                        "enum": ["legende", "markdown", "brief"],
                    },
                    "jahr": {"type": "integer", "description": "Steuerjahr, optional."},
                },
                "additionalProperties": False,
            },
        },
    },
]


class LlmFehler(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def policy_ok(cfg: llm.LlmConfig) -> tuple[bool, str]:
    """Ob dieser Endpoint sprechen darf. Remote nur mit Opt-in und Key."""
    if not cfg.configured:
        return False, "Assistent nicht konfiguriert."
    betrieb = llm.betrieb_von(cfg)
    if betrieb in ("remote", "onion"):
        if not cfg.remote_opt_in:
            return False, (
                "Remote nur nach ausdrücklicher Freigabe "
                "(Einstellungen → Assistent)."
            )
        if not cfg.api_key:
            return False, (
                "Remote braucht LLM_API_KEY in der .env "
                "(eigener Key, nicht der der laufenden Sitzung)."
            )
    elif betrieb not in ("loopback", "lan"):
        return False, "Assistent nicht konfiguriert."
    if not cfg.modell:
        return False, "Kein Modell gesetzt (LLM_MODELL)."
    if not llm.basis_url(cfg):
        return False, "LLM_BASE_URL fehlt."
    return True, ""


def ist_remote(cfg: llm.LlmConfig) -> bool:
    return llm.betrieb_von(cfg) in ("remote", "onion")


def redigiere_remote(text: str) -> str:
    """Entfernt XPUBs, TxIDs und typische Adressen vor dem Remote-Prompt."""
    if not text:
        return text
    text = _XPUB_RE.sub("[xpub]", text)
    text = _TXID_RE.sub("[txid]", text)
    text = _BECH32_RE.sub("[adresse]", text)
    text = _LEGACY_RE.sub("[adresse]", text)
    return text


def _chat_url(cfg: llm.LlmConfig) -> str:
    base = llm.basis_url(cfg)
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def bereinige_nachrichten(roh: Any) -> list[dict[str, str]]:
    """Nur user/assistant, gekürzt. Keine System-/Tool-Rollen vom Client."""
    if not isinstance(roh, list):
        return []
    sauber: list[dict[str, str]] = []
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            continue
        rolle = str(eintrag.get("role") or "").strip().lower()
        if rolle not in ("user", "assistant"):
            continue
        text = str(eintrag.get("content") or "").strip()
        if not text:
            continue
        if len(text) > MAX_CONTENT:
            text = text[:MAX_CONTENT]
        sauber.append({"role": rolle, "content": text})
    return sauber[-MAX_NACHRICHTEN:]


def _parse_args(roh: Any) -> dict[str, Any]:
    if isinstance(roh, dict):
        return roh
    if isinstance(roh, str) and roh.strip():
        try:
            wert = json.loads(roh)
        except json.JSONDecodeError:
            return {}
        return wert if isinstance(wert, dict) else {}
    return {}


def _fuehre_tool(
    name: str,
    args: dict[str, Any],
    tools_fn: Callable[[str, dict[str, Any]], str],
) -> str:
    if name not in ERLAUBTE_TOOLS:
        return f"Werkzeug „{name}“ ist nicht erlaubt. Ich starte keine Scans."
    try:
        text = tools_fn(name, args)
    except Exception as exc:  # noqa: BLE001 — Modell bekommt den Fehler als Text
        return f"Werkzeug fehlgeschlagen: {type(exc).__name__}"
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    if len(text) > 8000:
        text = text[:8000] + "…"
    return text


def _post_chat(
    cfg: llm.LlmConfig,
    messages: list[dict[str, Any]],
    *,
    timeout: float,
    mit_tools: bool = True,
) -> dict[str, Any]:
    url = _chat_url(cfg)
    try:
        ensure_url_allowed(url, service="llm", values={"LLM_REMOTE_OPT_IN": "1" if cfg.remote_opt_in else "0"})
    except OutboundPolicyError as exc:
        raise LlmFehler(403, str(exc)) from exc
    körper: dict[str, Any] = {
        "model": cfg.modell,
        "messages": messages,
        "stream": False,
    }
    if mit_tools:
        körper["tools"] = TOOL_SCHEMAS
        körper["tool_choice"] = "auto"
    roh = json.dumps(körper).encode("utf-8")
    req = urllib.request.Request(url, data=roh, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if cfg.api_key:
        req.add_header("Authorization", f"Bearer {cfg.api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as antwort:
            daten = json.loads(antwort.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            exc.read()
        except Exception:  # noqa: BLE001
            pass
        raise LlmFehler(502, f"Modell antwortete HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        grund = getattr(exc, "reason", exc)
        raise LlmFehler(502, f"Modell nicht erreichbar: {grund}") from exc
    except json.JSONDecodeError as exc:
        raise LlmFehler(502, "Modell lieferte kein JSON.") from exc
    if not isinstance(daten, dict):
        raise LlmFehler(502, "Unerwartete Modell-Antwort.")
    # Key darf nie in Fehlern landen.
    if cfg.api_key and len(cfg.api_key) >= 8:
        dump = json.dumps(daten)
        if cfg.api_key in dump:
            raise LlmFehler(502, "Modell-Antwort verworfen (unerwarteter Inhalt).")
    return daten


def fuehre_chat(
    cfg: llm.LlmConfig,
    nachrichten: Any,
    *,
    tools_fn: Callable[[str, dict[str, Any]], str],
    timeout: float = CHAT_TIMEOUT_S,
    post_fn=None,
) -> dict[str, Any]:
    """
    Eine Nutzerrunde: Modell + serverseitige Cache-Tools.

    ``post_fn`` nur für Tests. Liefert ``text``, ``tools_used``, ``rundungen``.
    """
    ok, grund = policy_ok(cfg)
    if not ok:
        status = 403 if "Freigabe" in grund or "gesperrt" in grund else 400
        raise LlmFehler(status, grund)

    historie = bereinige_nachrichten(nachrichten)
    if not historie or historie[-1]["role"] != "user":
        raise LlmFehler(400, "Es fehlt eine Nutzerfrage.")

    remote = ist_remote(cfg)
    if remote:
        historie = [
            {**m, "content": redigiere_remote(m["content"])} for m in historie
        ]
    system = SYSTEM_PROMPT + (SYSTEM_REMOTE if remote else "")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        *historie,
    ]
    benutzt: list[str] = []
    post = post_fn or _post_chat

    for runde in range(1, MAX_TOOL_RUNDEN + 1):
        antwort = post(cfg, messages, timeout=timeout, mit_tools=True)
        wahl = (antwort.get("choices") or [{}])[0]
        nachricht = wahl.get("message") if isinstance(wahl, dict) else None
        if not isinstance(nachricht, dict):
            raise LlmFehler(502, "Modell lieferte keine Nachricht.")
        aufrufe = nachricht.get("tool_calls") or []
        if aufrufe:
            messages.append({
                "role": "assistant",
                "content": nachricht.get("content") or "",
                "tool_calls": aufrufe,
            })
            for aufruf in aufrufe:
                if not isinstance(aufruf, dict):
                    continue
                fn = aufruf.get("function") or {}
                name = str((fn.get("name") if isinstance(fn, dict) else "") or "")
                args = _parse_args(fn.get("arguments") if isinstance(fn, dict) else {})
                if name:
                    benutzt.append(name)
                ergebnis = _fuehre_tool(name, args, tools_fn)
                if remote:
                    ergebnis = redigiere_remote(ergebnis)
                messages.append({
                    "role": "tool",
                    "tool_call_id": str(aufruf.get("id") or name or "tool"),
                    "content": ergebnis,
                })
            continue
        text = str(nachricht.get("content") or "").strip()
        if not text:
            raise LlmFehler(502, "Modell lieferte keinen Text.")
        return {
            "text": text,
            "tools_used": benutzt,
            "rundungen": runde,
        }

    raise LlmFehler(502, "Zu viele Werkzeug-Runden — Abbruch.")
