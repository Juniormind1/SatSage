"""
Stdout-/Job-Log-Zeilen DE→EN.

Muster aus ``web/locales/log_patterns.json`` (gleiche Quelle wie
``web/log_i18n.js``). Bei UI-Sprache DE unverändert.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TextIO

from core import i18n
from core.paths import resource_dir

_MUSTER: list[tuple[re.Pattern[str], str]] | None = None
_stdout_wrapped = False


def _lade() -> list[tuple[re.Pattern[str], str]]:
    global _MUSTER
    if _MUSTER is not None:
        return _MUSTER
    pfad = resource_dir() / "web" / "locales" / "log_patterns.json"
    roh: list[tuple[str, str]] = []
    if pfad.is_file():
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
            for eintrag in data:
                if not isinstance(eintrag, dict):
                    continue
                pattern = eintrag.get("re")
                en = eintrag.get("en")
                if isinstance(pattern, str) and isinstance(en, str):
                    roh.append((pattern, en))
        except (OSError, json.JSONDecodeError, TypeError):
            roh = []
    muster: list[tuple[re.Pattern[str], str]] = []
    for pattern, en in roh:
        try:
            muster.append((re.compile(pattern), en))
        except re.error:
            continue
    _MUSTER = muster
    return _MUSTER


def translate_line(text: str) -> str:
    """Eine Log-/Stdout-Zeile in die UI-Sprache bringen."""
    roh = str(text or "")
    if not roh or i18n.lang() != "en":
        return roh
    out = roh
    for pattern, repl in _lade():
        if pattern.search(out):
            out = pattern.sub(repl, out, count=1)
    out = (
        out.replace("fehlgeschlagen", "failed")
        .replace("abgebrochen", "cancelled")
        .replace("über Tor", "via Tor")
        .replace("ohne TLS", "without TLS")
        .replace("mit TLS", "with TLS")
        .replace("Moment noch", "Still working")
    )
    out = re.sub(r"noch (\d+) von (\d+)", r"\1 of \2 remaining", out)
    return out


class TranslatingTextIO:
    """
    Wrapper um stdout/stderr: vollständige Zeilen durch ``translate_line``.
    Unvollständige Zeilen (ohne \\n) bleiben im Puffer.
    """

    def __init__(self, original: TextIO):
        self._original = original
        self._buf = ""
        self._lock = __import__("threading").Lock()

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            data = str(data)
        if not data:
            return 0
        with self._lock:
            gebündelt = self._buf + data
            teile = gebündelt.split("\n")
            self._buf = teile[-1]
            for stueck in teile[:-1]:
                self._original.write(translate_line(stueck) + "\n")
            # Ohne Zeilenende: Rohtext durchreichen (Progress ohne \\n selten)
            # — nur puffern, nichts schreiben, bis \\n kommt.
        return len(data)

    def flush(self) -> None:
        with self._lock:
            if self._buf:
                self._original.write(translate_line(self._buf))
                self._buf = ""
            self._original.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._original, "isatty", lambda: False)())

    @property
    def encoding(self) -> str:
        return getattr(self._original, "encoding", None) or "utf-8"

    def fileno(self) -> int:
        return self._original.fileno()

    def __getattr__(self, name: str):
        return getattr(self._original, name)


def install_stdout_translation(*, force: bool = False) -> None:
    """Hängt Übersetzer an sys.stdout (idempotent). Nur wirksam bei EN."""
    global _stdout_wrapped
    if i18n.lang() != "en":
        return
    if _stdout_wrapped and not force:
        return
    if isinstance(sys.stdout, TranslatingTextIO):
        _stdout_wrapped = True
        return
    sys.stdout = TranslatingTextIO(sys.stdout)  # type: ignore[assignment]
    _stdout_wrapped = True
