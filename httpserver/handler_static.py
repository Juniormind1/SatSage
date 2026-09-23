"""Statische Dateien und Handbuch — Mixin für server.Handler.

Aus server.py extrahiert (Modularisierung). Einstieg bleibt server.Handler.
Server-Symbole werden lazy gebunden, um Import-Zyklen zu vermeiden.
"""

from __future__ import annotations

import mimetypes

_BOUND = False
_SERVER_NAMES = (
    'HANDBUCH_PFAD',
    'WEB_DIR',
)


def _ensure_server_names() -> None:
    global _BOUND
    if _BOUND:
        return
    import server as _server

    g = globals()
    for name in _SERVER_NAMES:
        g[name] = getattr(_server, name)
    _BOUND = True


class HandlerStaticMixin:
    def _sende_handbuch(self) -> None:
        _ensure_server_names()
        """Das Handbuch liegt unter doc/, nicht in web/."""
        if not HANDBUCH_PFAD.is_file():
            self._send(404, b"Nicht gefunden", "text/plain; charset=utf-8")
            return
        self._send(
            200,
            HANDBUCH_PFAD.read_bytes(),
            "text/html; charset=utf-8",
        )

    def _statisch(self, pfad: str) -> None:
        _ensure_server_names()
        name = "index.html" if pfad in ("/", "") else pfad.lstrip("/")
        # Rückwärtsschrägstriche zählen unter Windows ebenfalls als Trenner und
        # müssten sonst gesondert abgefangen werden.
        name = name.replace("\\", "/")
        try:
            ziel = (WEB_DIR / name).resolve()
            # is_relative_to statt String-Vergleich: Letzterer wäre unter
            # Windows von der Groß-/Kleinschreibung abhängig und würde
            # /web fälschlich auch auf /website passen lassen.
            drin = ziel.is_relative_to(WEB_DIR.resolve())
        except (OSError, ValueError):
            drin = False
        if not drin or not ziel.is_file():
            self._send(404, b"Nicht gefunden", "text/plain; charset=utf-8")
            return
        typ = mimetypes.guess_type(ziel.name)[0] or "application/octet-stream"
        if typ.startswith("text/") or typ == "application/javascript":
            typ += "; charset=utf-8"
        self._send(200, ziel.read_bytes(), typ)

