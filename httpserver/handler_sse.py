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


class _StromZu(Exception):
    """Der Browser hat den NDJSON-Strom geschlossen."""


class HandlerSseMixin:
    def _will_ndjson(self) -> bool:
        _ensure_server_names()
        accept = (self.headers.get("Accept") or "").lower()
        return "application/x-ndjson" in accept

    def _ndjson_zeile(self, obj: dict) -> bool:
        _ensure_server_names()
        # HTTP/1.0 ohne Content-Length: der Körper endet mit der Verbindung.
        # flush(), damit die Oberfläche die Zeile sieht, noch während Tor startet.
        roh = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(roh)
            self.wfile.flush()
        except Exception as exc:
            if _client_weg(exc):
                return False
            raise
        return True

    def _stream_tax_lots(self, query: dict) -> None:
        """Lot-Farben Punkt für Punkt, nachdem der Plot schon steht."""
        _ensure_server_names()
        from core.steuer_fenster import kennzahlen_ts, klaeren_keys
        from httpserver.api.tax import steuer_auswertung_merken
        from server import _steuer_auswertung, _ui_lang_fuer_web

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

        client_lang = self.headers.get("X-Satsage-Lang")
        accept = self.headers.get("Accept-Language")
        if client_lang is None and accept is None:
            sprache = "de"
        else:
            sprache = _ui_lang_fuer_web(
                self.state.env().values(), accept, client_lang,
            )

        def on_lot(zeile: dict) -> None:
            if not self._ndjson_zeile(zeile):
                raise _StromZu()

        try:
            auswertung = _steuer_auswertung(
                self.state, query, lang=sprache, mit_lots=True, on_lot=on_lot,
            )
            steuer_auswertung_merken(self.state, query, sprache, auswertung)
            strahl = auswertung.get("zeitstrahl") or {}
            self._ndjson_zeile({
                "done": True,
                "lots_fertig": True,
                "kennzahlen": auswertung.get("kennzahlen") or {},
                "kennzahlen_ts": kennzahlen_ts(auswertung),
                "geister_saldo": strahl.get("geister_saldo"),
                **klaeren_keys(auswertung),
            })
        except _StromZu:
            return
        except Exception as exc:
            if _shutdown_rauschen(exc) or _client_weg(exc) or _server_faehrt_runter(self.state):
                return
            LOGGER.exception("Steuer-Lots fehlgeschlagen")
            try:
                self._ndjson_zeile({"error": "Interner Serverfehler.", "done": True})
            except Exception as exc2:
                if _client_weg(exc2) or _shutdown_rauschen(exc2):
                    return

    def _stream_boot_log(self) -> None:
        _ensure_server_names()
        """Start-Log Zeile für Zeile, sobald sie entsteht — nicht erst am Ende."""
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

        def on_zeile(eintrag: dict) -> None:
            try:
                zeile = {
                    "log": eintrag.get("text") or "",
                    "wallet": eintrag.get("wallet") or "",
                }
                extra = eintrag.get("extra") or {}
                if extra.get("wallet"):
                    zeile["wallet_summary"] = extra["wallet"]
                self._ndjson_zeile(zeile)
            except Exception as exc:
                if _client_weg(exc):
                    return
                raise

        log = getattr(self.state, "boot_log", None)
        if log is None:
            self._ndjson_zeile({"done": True, "context_bereit": self.state.context_bereit()})
            return
        abmelden = log.abonniere(on_zeile)
        try:
            while not _server_faehrt_runter(self.state):
                log.warte(30.0)
                if getattr(log, "_bereit", False):
                    break
            self._ndjson_zeile({
                "done": True,
                "context_bereit": self.state.context_bereit(),
            })
        except Exception as exc:
            if _shutdown_rauschen(exc) or _client_weg(exc) or _server_faehrt_runter(self.state):
                return
            LOGGER.exception("Start-Log fehlgeschlagen")
        finally:
            abmelden()

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

