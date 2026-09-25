"""Steuer-/Selbstanzeige-Downloads — Mixin für server.Handler.

Aus server.py extrahiert (Modularisierung). Einstieg bleibt server.Handler.
Server-Symbole werden lazy gebunden, um Import-Zyklen zu vermeiden.
"""

from __future__ import annotations

import json

_BOUND = False
_SERVER_NAMES = (
    'ApiError',
    '_selbstanzeige_report',
    '_steuer_auswertung',
    '_ui_theme_aus_env',
    'tax_mod',
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


class HandlerDownloadMixin:
    def _download(self, pfad: str, query: dict) -> None:
        _ensure_server_names()
        """
        Liefert CSV bzw. Bericht als Datei-Download.

        Eigener Weg statt JSON, damit der Browser einen Dateinamen bekommt und
        die Datei direkt speichert.
        """
        auswertung = _steuer_auswertung(self.state, query)
        jahr = auswertung["jahr"]
        from core import herkunft_bericht as hb_mod
        try:
            theme_roh = (query.get("theme") or [""])[0]
        except (TypeError, IndexError):
            theme_roh = ""
        if not theme_roh:
            theme_roh = _ui_theme_aus_env(self.state.env().values())
        theme = hb_mod.normalize_bericht_theme(theme_roh)

        if pfad.endswith(".csv"):
            inhalt = tax_mod.als_csv(auswertung)
            typ = "text/csv; charset=utf-8"
            name = f"satsage-steuerjahr-{jahr}.csv"
        else:
            inhalt = tax_mod.als_bericht(
                auswertung,
                immutable_cache_dir=self.state.immutable_cache_dir,
                theme=theme,
            )
            typ = "text/html; charset=utf-8"
            name = f"satsage-steuerjahr-{jahr}.html"

        self.send_response(200)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(inhalt)))
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(inhalt)

    def _download_selbstanzeige(self, pfad: str, query: dict) -> None:
        _ensure_server_names()
        """Bericht Sat-Geschichte als HTML oder CSV (Query: jahr, frist, txids)."""
        from core import selbstanzeige as sa

        try:
            jahr = int(query.get("jahr", ["0"])[0])
        except (ValueError, TypeError, IndexError):
            jahr = 0
        try:
            frist = int(query.get("frist", ["1"])[0])
        except (ValueError, TypeError, IndexError):
            frist = 1
        roh = query.get("txids", [""])[0] or ""
        txids = [t.strip() for t in roh.replace(";", ",").split(",") if t.strip()]
        roh_u = query.get("utxos", [""])[0] or ""
        utxo_keys = [
            t.strip() for t in roh_u.replace(";", ",").split(",") if t.strip()
        ]
        try:
            report = _selbstanzeige_report(
                self.state,
                {
                    "jahr": jahr,
                    "haltefrist_jahre": frist,
                    "txids": txids,
                    "utxos": utxo_keys,
                },
            )
        except ApiError as exc:
            # Browser-Tab erwartet HTML — JSON wirkt wie „leere/kaputte Seite“.
            if pfad.endswith(".html"):
                body = (
                    "<!DOCTYPE html><html lang=de><meta charset=utf-8>"
                    f"<title>Report-Fehler</title><body style='font-family:system-ui;"
                    f"max-width:36rem;margin:2rem auto;padding:0 1rem'>"
                    f"<h1>Report nicht erzeugbar</h1><p>{tax_mod._html_escape(exc.message)}</p>"
                    f"<p style='color:#666'>Fenster schließen und in SatSage "
                    f"TxID/Jahr prüfen.</p></body></html>"
                ).encode("utf-8")
                self._send(exc.status, body, "text/html; charset=utf-8")
            else:
                self._send(
                    exc.status,
                    json.dumps({"error": exc.message}).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
            return
        except Exception as exc:
            msg = f"Interner Serverfehler: {exc}"
            if pfad.endswith(".html"):
                body = (
                    "<!DOCTYPE html><html lang=de><meta charset=utf-8>"
                    f"<title>Report-Fehler</title><body style='font-family:system-ui;"
                    f"max-width:36rem;margin:2rem auto;padding:0 1rem'>"
                    f"<h1>Report fehlgeschlagen</h1>"
                    f"<p>{tax_mod._html_escape(msg)}</p></body></html>"
                ).encode("utf-8")
                self._send(500, body, "text/html; charset=utf-8")
            else:
                self._send(
                    500,
                    json.dumps({"error": msg}).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
            return
        jahr = report["jahr"]
        from core import herkunft_bericht as hb_mod
        try:
            theme_roh = (query.get("theme") or [""])[0]
        except (TypeError, IndexError):
            theme_roh = ""
        if not theme_roh:
            theme_roh = _ui_theme_aus_env(self.state.env().values())
        theme = hb_mod.normalize_bericht_theme(theme_roh)

        if pfad.endswith(".csv"):
            inhalt = sa.als_csv(report)
            typ = "text/csv; charset=utf-8"
            name = f"satsage-trace-{jahr}.csv"
            # CSV immer als Download — im Tab wäre es nur Rohtext.
            disposition = f'attachment; filename="{name}"'
        else:
            inhalt = sa.als_html(
                report,
                immutable_cache_dir=self.state.immutable_cache_dir,
                theme=theme,
            )
            typ = "text/html; charset=utf-8"
            name = f"satsage-trace-{jahr}.html"
            # inline: Tab zeigt den Report (Druck → PDF). Die Oberfläche
            # löst parallel noch einen Datei-Download aus.
            disposition = f'inline; filename="{name}"'
        if isinstance(inhalt, str):
            inhalt = inhalt.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(inhalt)))
        self.send_header("Content-Disposition", disposition)
        self.send_header("X-Content-Type-Options", "nosniff")
        # Report ist standalone HTML — kein CSP der App-Shell (bricht sonst
        # eingebettetes CSS / Druck-@page).
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(inhalt)

