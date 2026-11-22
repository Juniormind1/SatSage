"""Touch-ID-API (nur macOS, nur Loopback, opt-in).

Routen:

- ``POST /api/auth/touchid``: Login und Entsperren. Holt das Passwort über
  Touch ID aus dem Schlüsselbund und schickt es durch denselben Weg wie
  ein getipptes (``_verify_password`` → ``_scramble_unlock``).
- ``POST /api/auth/touchid/enroll``: Touch ID aktivieren. Verlangt Sitzung
  und das getippte Passwort.
- ``DELETE /api/auth/touchid`` (oder ``POST /api/auth/touchid/remove``):
  Touch ID deaktivieren.

Gates: kein StartOS/Umbrel/Specter, Peer und Host Loopback, Backend
verfügbar (macOS mit Hilfsprogramm), Origin/CSRF, Rate-Limit wie beim
Passwort-Login, nur ein Dialog gleichzeitig.

Diagnose: jede Route schreibt über ``touchid.log_event`` Gate-Entscheidung,
Rate-Limit, Ergebnis-Code und Dauer. Nie Passwort, Länge oder Body.
"""
from __future__ import annotations

import time

from core import touchid

_PLATTFORM_OHNE_TOUCHID = frozenset({"start9", "umbrel", "specter"})

#: HTTP-Status je Fehlercode des Hilfsprogramms.
_STATUS = {
    "cancelled": 403,
    "failed": 403,
    "not_available": 404,
    "helper_missing": 404,
    "locked_out": 423,
    "invalidated": 409,
    "not_found": 409,
    "not_enrolled": 409,
    "stale": 409,
    "busy": 409,
    "timeout": 408,
    "keychain": 500,
    "error": 500,
}

_MELDUNG = {
    "cancelled": "Touch ID abgebrochen.",
    "failed": "Fingerabdruck nicht erkannt.",
    "not_available": "Touch ID ist auf diesem Mac nicht verfügbar.",
    "helper_missing": "Touch ID ist auf diesem Mac nicht verfügbar.",
    "locked_out": "Touch ID ist gesperrt. Bitte Passwort eingeben.",
    "invalidated": "Fingerabdrücke wurden geändert. Touch ID ist aus, bitte mit Passwort anmelden.",
    "not_found": "Touch ID ist nicht mehr eingerichtet. Bitte mit Passwort anmelden.",
    "not_enrolled": "Touch ID ist nicht aktiviert.",
    "stale": "Gespeichertes Passwort passt nicht mehr. Touch ID ist aus.",
    "busy": "Ein Touch-ID-Dialog läuft bereits.",
    "timeout": "Touch ID nicht rechtzeitig bestätigt.",
    "keychain": "Schlüsselbund-Fehler.",
    "error": "Touch ID fehlgeschlagen.",
    "remote": "Touch ID nur am Mac, auf dem SatSage läuft.",
}

#: Begründung im macOS-Dialog. macOS setzt den Programmnamen davor.
_GRUND = {
    "de": {
        "unlock": "die SatSage-Anmeldung freizugeben",
        "enroll": "Touch ID für SatSage zu aktivieren",
    },
    "en": {
        "unlock": "unlock your SatSage sign-in",
        "enroll": "turn on Touch ID for SatSage",
    },
}


def _server():
    import server

    return server


def _fehler(handler, code: str, *, status: int | None = None, message: str = "") -> None:
    handler._json(status or _STATUS.get(code, 500), {
        "error": message or _MELDUNG.get(code, _MELDUNG["error"]),
        "code": code,
    })


def _lang(handler) -> str:
    srv = _server()
    try:
        werte = handler.state.env().values()
    except Exception:
        werte = {}
    try:
        lang = srv._ui_lang_fuer_web(werte, handler.headers.get("Accept-Language"))
    except Exception:
        lang = "de"
    return lang if lang in _GRUND else "de"


def _grund(handler, art: str) -> str:
    return _GRUND[_lang(handler)][art]


def _plattform_ok(handler) -> bool:
    return getattr(handler.state, "managed_by", None) not in _PLATTFORM_OHNE_TOUCHID


def _verfuegbar(handler) -> bool:
    """Ohne Seiteneffekt außer dem (gecachten) Probe-Aufruf am Mac."""
    if not _plattform_ok(handler) or not handler._loopback_request():
        return False
    try:
        return bool(touchid.get_backend().available())
    except Exception:
        return False


def status_fuer(handler) -> dict:
    """``{"available", "enrolled"}`` für Login-Seite, Status und Einstellungen."""
    verfuegbar = _verfuegbar(handler)
    return {
        "available": verfuegbar,
        "enrolled": bool(verfuegbar and touchid.is_enrolled(handler.state.env_path)),
    }


def _gate(handler, route: str) -> str | None:
    """Gate prüfen und die Entscheidung loggen (Loopback ja/nein, Plattform)."""
    verwaltung = getattr(handler.state, "managed_by", None) or "-"
    try:
        loopback = bool(handler._loopback_request())
    except Exception:
        loopback = False
    if not _plattform_ok(handler):
        code = "not_available"
    elif not loopback:
        code = "remote"
    elif not _verfuegbar(handler):
        code = "not_available"
    else:
        code = None
    touchid.log_event(
        "gate", warnung=code == "remote", route=route,
        entscheidung=code or "ok", loopback=loopback, verwaltung=str(verwaltung),
    )
    return code


class _Lauf:
    """Ergebnis einer Route mit Dauer loggen."""

    def __init__(self, route: str) -> None:
        self.route = route
        self.start = time.monotonic()

    def ende(self, ergebnis: str, *, status: int, warnung: bool = False, **felder) -> None:
        touchid.log_event(
            "route", warnung=warnung, route=self.route, ergebnis=ergebnis, http=status,
            dauer_ms=int((time.monotonic() - self.start) * 1000), **felder,
        )


def _rate_limit(handler, lauf: _Lauf) -> bool:
    if handler._rate_limited():
        lauf.ende("rate_limit", status=429, warnung=True, rate_limit=True)
        handler._fehler(429, "Zu viele Fehlversuche. Später erneut versuchen.")
        return True
    return False


def _login(handler) -> None:
    srv = _server()
    state = handler.state
    lauf = _Lauf("login")
    code = _gate(handler, "login")
    if code:
        status = 403 if code == "remote" else _STATUS.get(code, 500)
        lauf.ende(code, status=status)
        _fehler(handler, code, status=status)
        return
    if not handler._origin_ok():
        lauf.ende("origin_abgelehnt", status=403, warnung=True)
        handler._fehler(403, "Origin/Referer fehlt oder ist nicht erlaubt.")
        return
    if not srv._password_is_set(state):
        lauf.ende("kein_passwort", status=409)
        handler._fehler(409, "Noch kein Passwort gesetzt.")
        return
    if not touchid.is_enrolled(state.env_path):
        lauf.ende("not_enrolled", status=409)
        _fehler(handler, "not_enrolled")
        return
    if _rate_limit(handler, lauf):
        return
    account = touchid.account_for(state.env_path)
    konto = touchid.konto_kurz(account)
    try:
        with touchid.dialog_slot():
            password = touchid.get_backend().unlock(account, _grund(handler, "unlock"))
    except touchid.TouchIdError as exc:
        if exc.code in ("invalidated", "not_found"):
            touchid.invalidate(state.env_path, grund=f"unlock_{exc.code}")
        elif exc.code == "failed":
            handler._record_login_failure()
        lauf.ende(
            exc.code, status=_STATUS.get(exc.code, 500),
            warnung=exc.code not in ("cancelled",), konto=konto,
            fehlversuch=exc.code == "failed", **touchid.helper_diag(exc),
        )
        _fehler(handler, exc.code)
        return
    try:
        if not srv._verify_password(password, srv._password_hash(state)):
            # Kopie passt nicht (Passwort anderswo geändert): Eintrag weg.
            touchid.invalidate(state.env_path, grund="stale")
            lauf.ende("stale", status=409, warnung=True, konto=konto)
            _fehler(handler, "stale")
            return
        handler._login_succeeded()
        try:
            srv._scramble_unlock(state, password)
        except Exception as exc:
            # Keine Ausnahmetexte: nur der Typ ins Log, generische Meldung.
            lauf.ende(
                "entsperren_fehler", status=403, warnung=True,
                ausnahme=type(exc).__name__, konto=konto,
            )
            handler._fehler(403, "Konfiguration entsperren fehlgeschlagen.")
            return
    finally:
        del password
    lauf.ende("ok", status=200, konto=konto)
    handler._json(200, {
        "ok": True,
        "authenticated": True,
        "unlock_needed": False,
        "env_scramble": srv._env_scramble_status(state),
    })


def _enroll(handler) -> None:
    srv = _server()
    state = handler.state
    lauf = _Lauf("enroll")
    if not handler._auth_ok({}):
        lauf.ende("keine_sitzung", status=403, warnung=True)
        handler._fehler(403, "Anmeldung erforderlich.")
        return
    code = _gate(handler, "enroll")
    if code:
        status = 403 if code == "remote" else _STATUS.get(code, 500)
        lauf.ende(code, status=status)
        _fehler(handler, code, status=status)
        return
    if not handler._origin_ok():
        lauf.ende("origin_abgelehnt", status=403, warnung=True)
        handler._fehler(403, "Origin/Referer fehlt oder ist nicht erlaubt.")
        return
    if not srv._password_is_set(state):
        lauf.ende("kein_passwort", status=409)
        handler._fehler(409, "Noch kein Passwort gesetzt.")
        return
    if _rate_limit(handler, lauf):
        return
    try:
        body = handler._body()
        password = str(body.get("password") or body.get("current_password") or "")
    except srv.ApiError as exc:
        lauf.ende("body_fehler", status=exc.status, warnung=True)
        handler._fehler(exc.status, exc.message)
        return
    finally:
        body = None
    try:
        if not password or not srv._verify_password(password, srv._password_hash(state)):
            handler._record_login_failure()
            # Nur „leer“ oder „falsch“, nie die Länge.
            lauf.ende(
                "passwort_falsch", status=403, warnung=True, fehlversuch=True,
                passwort_leer=not password,
            )
            handler._fehler(403, "Passwort ist falsch.")
            return
        account = touchid.account_for(state.env_path)
        konto = touchid.konto_kurz(account)
        try:
            with touchid.dialog_slot():
                touchid.get_backend().enroll(account, password, _grund(handler, "enroll"))
        except touchid.TouchIdError as exc:
            lauf.ende(
                exc.code, status=_STATUS.get(exc.code, 500),
                warnung=exc.code != "cancelled", konto=konto, **touchid.helper_diag(exc),
            )
            _fehler(handler, exc.code)
            return
    finally:
        del password
    touchid.write_marker(state.env_path)
    lauf.ende("ok", status=200, konto=konto, marker=True)
    handler._json(200, {"ok": True, "touchid": status_fuer(handler)})


def _remove(handler, methode: str) -> None:
    state = handler.state
    lauf = _Lauf("remove")
    if not handler._auth_ok({}):
        lauf.ende("keine_sitzung", status=403, warnung=True)
        handler._fehler(403, "Anmeldung erforderlich.")
        return
    if not handler._csrf_ok(methode):
        lauf.ende("origin_abgelehnt", status=403, warnung=True)
        handler._fehler(403, "Origin/Referer fehlt oder ist nicht erlaubt.")
        return
    try:
        touchid.remove_entry(state.env_path)
    except Exception as exc:
        lauf.ende("fehler", status=500, warnung=True, ausnahme=type(exc).__name__)
        handler._fehler(500, "Touch ID deaktivieren fehlgeschlagen.")
        return
    lauf.ende("ok", status=200)
    handler._json(200, {"ok": True, "touchid": status_fuer(handler)})


def handle(handler, methode: str, pfad: str) -> bool:
    """Dispatch aus ``HandlerAuthMixin._auth_api``. True, wenn beantwortet."""
    if pfad == "/api/auth/touchid" and methode == "POST":
        _login(handler)
        return True
    if pfad == "/api/auth/touchid/enroll" and methode == "POST":
        _enroll(handler)
        return True
    if (pfad == "/api/auth/touchid" and methode == "DELETE") or (
        pfad == "/api/auth/touchid/remove" and methode == "POST"
    ):
        _remove(handler, methode)
        return True
    return False
