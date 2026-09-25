"""NDJSON/SSE-Streams — Mixin für server.Handler.

Aus server.py extrahiert (Modularisierung). Einstieg bleibt server.Handler.
Server-Symbole werden lazy gebunden, um Import-Zyklen zu vermeiden.
"""

from __future__ import annotations

import json

_BOUND = False
_SERVER_NAMES = (
    'ApiError',
    'LOGGER',
    '_client_weg',
    '_redact_url',
    '_server_faehrt_runter',
    '_shutdown_rauschen',
    'api_source_status',
    'api_wallet_export_suchen',
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


class HandlerSseMixin:
    def _will_ndjson(self) -> bool:
        _ensure_server_names()
        accept = (self.headers.get("Accept") or "").lower()
        return "application/x-ndjson" in accept

    def _ndjson_zeile(self, obj: dict) -> None:
        _ensure_server_names()
        # HTTP/1.0 ohne Content-Length: der Körper endet mit der Verbindung.
        # flush(), damit die Oberfläche die Zeile sieht, noch während Tor startet.
        roh = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(roh)
            self.wfile.flush()
        except Exception as exc:
            if _client_weg(exc):
                return
            raise

    def _stream_wallet_export_suchen(self) -> None:
        _ensure_server_names()
        """Wallet-Suche: Log-Zeilen live („Suche Sparrow…“), danach Ergebnis."""
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
        except Exception as exc:
            if _client_weg(exc):
                return
            raise

        def on_log(text: str) -> None:
            try:
                self._ndjson_zeile({"log": text})
            except Exception as exc:
                if _client_weg(exc):
                    return
                raise

        try:
            payload = api_wallet_export_suchen(self.state, on_log=on_log)
            self._ndjson_zeile(payload)
        except ApiError as exc:
            try:
                self._ndjson_zeile({"error": str(exc)})
            except Exception as exc2:
                if _client_weg(exc2):
                    return
        except Exception as exc:
            if _shutdown_rauschen(exc) or _server_faehrt_runter(self.state):
                return
            LOGGER.exception("wallet-export-suchen fehlgeschlagen")
            try:
                self._ndjson_zeile({"error": "Interner Serverfehler."})
            except Exception as exc2:
                if _client_weg(exc2) or _shutdown_rauschen(exc2):
                    return

    def _stream_source_status(self, query: dict) -> None:
        _ensure_server_names()
        """
        Schreibt Log-Zeilen, sobald sie entstehen — nicht erst nach Tor-Start.

        Ohne diesen Weg sähe die Oberfläche bis zum Ende der Prüfung nichts,
        obwohl „Starte Tor" schon längst auf dem Server stand.
        """
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
        except Exception as exc:
            if _client_weg(exc):
                return
            raise

        def on_log(text: str) -> None:
            try:
                self._ndjson_zeile({"log": text})
            except Exception as exc:
                if _client_weg(exc):
                    return
                raise

        if _server_faehrt_runter(self.state):
            return
        try:
            payload = api_source_status(self.state, query, on_log=on_log)
            self._ndjson_zeile(payload)
        except Exception as exc:
            if _shutdown_rauschen(exc) or _server_faehrt_runter(self.state):
                return
            LOGGER.exception("Quellstatus fehlgeschlagen: %s", _redact_url(self.path))
            try:
                self._ndjson_zeile({"error": "Interner Serverfehler."})
            except Exception as exc2:
                if _shutdown_rauschen(exc2):
                    return

