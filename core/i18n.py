"""
CLI- und Terminal-Sprache (UI_LANG).

Web-GUI hat eigene Catalogs unter web/locales/. Hier: gemeinsame
Sprachwahl, t() für Menütexte und Anbindung an Log-Übersetzung.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.paths import resource_dir

_lang: str | None = None
_catalog: dict[str, str] | None = None
_fallback: dict[str, str] | None = None

SUPPORTED = ("de", "en")


def normalize_lang(roh: str | None) -> str:
    w = str(roh or "").strip().lower()
    if w.startswith("en"):
        return "en"
    if w.startswith("de"):
        return "de"
    return "de"


def set_lang(code: str | None) -> str:
    """Setzt die UI-Sprache und leert den Catalog-Cache."""
    global _lang, _catalog, _fallback
    _lang = normalize_lang(code)
    _catalog = None
    _fallback = None
    return _lang


def lang() -> str:
    global _lang
    if _lang is None:
        # UI_LANG aus .env wird vom Aufrufer oft schon in os.environ gelegt;
        # sonst Default Deutsch.
        env_lang = os.environ.get("UI_LANG") or ""
        if not env_lang:
            # grobe System-Locale nur als Hinweis, kein Override von DE-Default
            # ohne UI_LANG — SatSage bleibt DE-first.
            env_lang = "de"
        set_lang(env_lang)
    return _lang or "de"


def init_from_env(values: dict[str, str] | None = None) -> str:
    """Sprache aus .env-Werten oder os.environ."""
    roh = ""
    if values:
        roh = str(values.get("UI_LANG") or "").strip()
    if not roh:
        roh = os.environ.get("UI_LANG", "").strip()
    code = set_lang(roh or "de")
    os.environ["UI_LANG"] = code
    return code


def _locale_path(code: str) -> Path:
    return resource_dir() / "web" / "locales" / f"{code}.json"


def _load_json(code: str) -> dict[str, str]:
    pfad = _locale_path(code)
    if not pfad.is_file():
        return {}
    try:
        data = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}


def _ensure_catalogs() -> None:
    global _catalog, _fallback
    if _catalog is not None:
        return
    code = lang()
    _fallback = _load_json("de")
    if code == "de":
        _catalog = _fallback
    else:
        _catalog = _load_json(code)


def t(key: str, **vars: Any) -> str:
    """Catalog-Lookup; fehlende EN-Keys fallen auf DE zurück."""
    if not key:
        return ""
    _ensure_catalogs()
    text = ""
    if _catalog and key in _catalog and _catalog[key] != "":
        text = _catalog[key]
    elif _fallback and key in _fallback and _fallback[key] != "":
        text = _fallback[key]
    else:
        text = key
    if vars:
        for name, wert in vars.items():
            text = text.replace("{" + name + "}", str(wert))
    return text


def ja_nein(wert: bool) -> str:
    return t("common.yes") if wert else t("common.no")
