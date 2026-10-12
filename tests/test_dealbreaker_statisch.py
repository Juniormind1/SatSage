"""Dealbreaker T1 / T6 / T13 — statisch, ohne Node.

Auf ``dev-juniormind`` optional (Skip), auf ``main`` Pflicht.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse

from tests.hart import skip_wenn_dev

WURZEL = Path(__file__).resolve().parents[1]
WEB = WURZEL / "web"
PLUGIN = WURZEL / "specter_plugin" / "src"
LERN = WEB / "lernhinweise.json"
HANDBUCH = WURZEL / "doc" / "handbuch.html"

T1_EINGABE = re.compile(
    r"<(?:input|textarea)\b[^>]*(?:name|id|placeholder|aria-label)\s*=\s*"
    r"""['"][^'"]*(?:mnemonic|xprv|\bwif\b|seed[-\s]?phrase|"""
    r"wiederherstellungs(?:satz|phrase)|recovery[-\s]?phrase)[^'\"]*['\"]",
    re.I,
)
T1_FREITEXT = re.compile(
    r"\b(?:enter|eingabe|eingeben|paste|einfügen)\b.{0,40}\b"
    r"(?:mnemonic|seed phrase|xprv|\bwif\b|wiederherstellungssatz)\b"
    r"|"
    r"\b(?:mnemonic|seed phrase|xprv|\bwif\b)\b.{0,40}\b"
    r"(?:enter|eingabe|eingeben|paste|einfügen)\b",
    re.I,
)
T1_DATEIEN = (
    WEB / "index.html",
    WEB / "locales" / "de.json",
    WEB / "locales" / "en.json",
)

SCRIPT_SRC = re.compile(
    r"""<script\b[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""",
    re.I,
)
EVAL_AUFRUF = re.compile(r"\beval\s*\(")
NEW_FUNCTION = re.compile(r"\bnew\s+Function\s*\(")
IMPORT_HTTP = re.compile(
    r"""\bimport\s*\(\s*['"]https?://""",
    re.I,
)

ALTCOIN = re.compile(
    r"ethereum|\beth\b|solana|cardano|shitcoin|altcoin|\bcrypto\s+casino",
    re.I,
)
STARTPFAD = {
    "", "/", "/en", "/en/", "/de", "/de/",
    "/thek", "/thek/", "/learn", "/learn/",
    "/shop", "/shop/", "/store", "/store/",
}


def _web_texte() -> list[tuple[str, str]]:
    out = []
    for p in list(WEB.rglob("*")) + list(PLUGIN.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".html", ".js", ".jinja", ".json"}:
            continue
        if any(teil in p.parts for teil in ("__pycache__", "node_modules")):
            continue
        try:
            out.append((p.relative_to(WURZEL).as_posix(), p.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return out


@skip_wenn_dev()
class TestT1KeineSeedEingabe(unittest.TestCase):
    def test_keine_seed_felder_in_der_ui(self):
        fehler = []
        for pfad in T1_DATEIEN:
            text = pfad.read_text(encoding="utf-8")
            if T1_EINGABE.search(text) or T1_FREITEXT.search(text):
                fehler.append(pfad.relative_to(WURZEL).as_posix())
        for rel, text in _web_texte():
            if rel.endswith("lernhinweise.json"):
                continue
            if T1_EINGABE.search(text):
                fehler.append(rel)
        self.assertEqual(
            fehler, [],
            "Dealbreaker T1: Seed/Mnemonic/xprv/WIF-Eingabe in " + ", ".join(fehler),
        )


@skip_wenn_dev()
class TestT6KeinRemoteJs(unittest.TestCase):
    def test_script_src_nur_lokal(self):
        fehler = []
        for rel, text in _web_texte():
            if not rel.endswith((".html", ".jinja")):
                continue
            for src in SCRIPT_SRC.findall(text):
                if src.startswith(("http://", "https://", "//")):
                    fehler.append(f"{rel}: {src}")
        self.assertEqual(
            fehler, [],
            "Dealbreaker T6: Remote-<script src> — " + "; ".join(fehler),
        )

    def test_kein_eval_ausser_vendor(self):
        fehler = []
        for rel, text in _web_texte():
            if "/vendor/" in rel.replace("\\", "/"):
                continue
            if not rel.endswith((".js", ".html", ".jinja")):
                continue
            if EVAL_AUFRUF.search(text) or NEW_FUNCTION.search(text) or IMPORT_HTTP.search(text):
                fehler.append(rel)
        self.assertEqual(
            fehler, [],
            "Dealbreaker T6: eval/new Function/Remote-import in " + ", ".join(fehler),
        )


def _ok_themen(daten: dict) -> list[dict]:
    return [
        t for t in daten.get("themen") or []
        if str(t.get("status") or "").strip().lower() in ("ok", "vorschlag")
    ]


def _url_ist_startseite(url: str) -> bool:
    parsed = urlparse(url)
    pfad = parsed.path.rstrip("/") or "/"
    if pfad == "/":
        return True
    norm = parsed.path if parsed.path.endswith("/") else parsed.path
    return norm.rstrip("/") in {p.rstrip("/") for p in STARTPFAD if p not in ("", "/")}


@skip_wenn_dev()
class TestT13Lernhinweise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daten = json.loads(LERN.read_text(encoding="utf-8"))
        cls.handbuch = HANDBUCH.read_text(encoding="utf-8")

    def test_schema_und_status(self):
        self.assertEqual(self.daten.get("schema"), 1)
        erlaubt = {"ok", "vorschlag", "verworfen"}
        for thema in self.daten.get("themen") or []:
            self.assertIn(thema.get("status"), erlaubt, thema.get("id"))

    def test_ok_urls_https_bitcoin_only_keine_startseite(self):
        fehler = []
        for thema in _ok_themen(self.daten):
            tid = thema.get("id")
            for lang in ("de", "en"):
                block = thema.get(lang) or {}
                url = str(block.get("url") or "").strip()
                titel = str(block.get("titel") or "")
                if not url:
                    fehler.append(f"{tid}.{lang}: URL fehlt")
                    continue
                parsed = urlparse(url)
                if parsed.scheme != "https":
                    fehler.append(f"{tid}.{lang}: nicht https ({url})")
                if ALTCOIN.search(url) or ALTCOIN.search(titel):
                    fehler.append(f"{tid}.{lang}: Altcoin-Verdacht ({url})")
                if _url_ist_startseite(url):
                    fehler.append(f"{tid}.{lang}: Anbieter-Startseite ({url})")
        self.assertEqual(fehler, [], "Dealbreaker T13:\n" + "\n".join(fehler))

    def test_handbuch_paragraf_14_zieht_ok_urls_mit(self):
        fehlend = []
        for thema in _ok_themen(self.daten):
            for lang in ("de", "en"):
                url = str((thema.get(lang) or {}).get("url") or "").strip()
                if url and url not in self.handbuch:
                    fehlend.append(f"{thema.get('id')}.{lang}: {url}")
        self.assertEqual(
            fehlend, [],
            "Handbuch §14 ohne kuratierte URL:\n" + "\n".join(fehlend),
        )


if __name__ == "__main__":
    unittest.main()
