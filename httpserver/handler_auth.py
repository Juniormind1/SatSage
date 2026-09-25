"""Login/Session/CSRF/Rate-Limit/Host-Checks — Mixin für server.Handler.

Aus server.py extrahiert (Modularisierung). Einstieg bleibt server.Handler.
Server-Symbole werden lazy gebunden, um Import-Zyklen zu vermeiden.
"""

from __future__ import annotations

import ipaddress
import json
import secrets
import time
from http.cookies import SimpleCookie, CookieError
from urllib.parse import urlparse

_BOUND = False
_SERVER_NAMES = (
    'ApiError',
    'LOGIN_MAX_FAILURES',
    'LOGIN_PAGE_CSS',
    'LOGIN_PAGE_JS',
    'LOGIN_WINDOW',
    'SESSION_COOKIE',
    'SESSION_TTL',
    '_LOGIN_TEXTE',
    '_LOOPBACK_HOSTS',
    '_clear_password_hash',
    '_client_ip',
    '_env_scramble_status',
    '_env_setting',
    '_host_allowlist',
    '_host_pattern_ok',
    '_login_js_texte',
    '_normalisiere_host',
    '_password_hash',
    '_password_is_set',
    '_scramble_change_password',
    '_scramble_disable_for_password',
    '_scramble_enable_for_password',
    '_scramble_unlock',
    '_start9_proxy_authenticated',
    '_ui_lang_fuer_web',
    '_unlock_needed_after_auth',
    '_verify_password',
    '_write_password_hash',
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


class HandlerAuthMixin:
    def _request_host(self) -> str:
        _ensure_server_names()
        trust_proxy = _env_setting(self.state, "SATSAGE_TRUST_PROXY") == "1"
        forwarded = self.headers.get("X-Forwarded-Host") if trust_proxy else None
        return _normalisiere_host(forwarded or self.headers.get("Host"))

    def _host_value_ok(self, host: str) -> bool:
        _ensure_server_names()
        if host in _LOOPBACK_HOSTS:
            return True
        try:
            address = ipaddress.ip_address(host)
            if address.is_loopback:
                return True
            # StartOS terminates TLS and forwards the UI request to the app.
            # When that trust is explicitly enabled, the forwarded Host can be
            # the node's LAN address rather than a DNS name in the allowlist.
            if _env_setting(self.state, "SATSAGE_TRUST_PROXY") == "1" and (
                address.is_private or address.is_link_local
            ):
                return True
        except ValueError:
            pass
        return any(_host_pattern_ok(host, pattern) for pattern in _host_allowlist(self.state))

    def _host_ok(self) -> bool:
        _ensure_server_names()
        return self._host_value_ok(self._request_host())

    def _loopback_request(self) -> bool:
        _ensure_server_names()
        # Host allein ist bei einem öffentlichen Bind spoofbar. Deshalb müssen
        # Peer-Adresse und effektiver Host beide Loopback sein. Hinter einem
        # Start9-Proxy bleibt ein Remote-Host damit bewusst im Passwortmodus.
        try:
            peer_loopback = ipaddress.ip_address(_client_ip(self)).is_loopback
        except ValueError:
            peer_loopback = False
        host = self._request_host()
        return peer_loopback and (host in _LOOPBACK_HOSTS or self._host_value_is_loopback(host))

    @staticmethod
    def _host_value_is_loopback(host: str) -> bool:
        _ensure_server_names()
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def _secure_cookie(self) -> bool:
        _ensure_server_names()
        if _env_setting(self.state, "SATSAGE_TRUST_PROXY") == "1":
            return (self.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower() == "https"
        return (urlparse(self.path).scheme or "").lower() == "https"

    def _set_session_cookie(self, value: str, *, delete: bool = False) -> None:
        _ensure_server_names()
        parts = [f"{SESSION_COOKIE}={value}", "Path=/", "HttpOnly", "SameSite=Lax"]
        if self._secure_cookie():
            parts.append("Secure")
        if delete:
            parts.extend(("Max-Age=0", "Expires=Thu, 01 Jan 1970 00:00:00 GMT"))
        self._pending_cookie = "; ".join(parts)

    def _new_session(self) -> None:
        _ensure_server_names()
        sid = secrets.token_urlsafe(32)
        with self.state._auth_lock:
            self.state.sessions[sid] = time.time() + SESSION_TTL
        self._set_session_cookie(sid)

    def _session_id(self) -> str:
        _ensure_server_names()
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else ""
        except (CookieError, ValueError):
            return ""

    def _session_ok(self) -> bool:
        _ensure_server_names()
        sid = self._session_id()
        if not sid:
            return False
        now = time.time()
        with self.state._auth_lock:
            expiry = self.state.sessions.get(sid, 0)
            if expiry <= now:
                self.state.sessions.pop(sid, None)
                return False
        return True

    def _has_valid_token_header(self) -> bool:
        _ensure_server_names()
        value = self.headers.get("X-Satsage-Token", "")
        return bool(value) and secrets.compare_digest(value, self.state.token)

    def _token_ok(self, query: dict) -> bool:
        _ensure_server_names()
        # Passwort gesetzt → nur Login-Session (Cookie). Weder ?t= noch
        # X-Satsage-Token ersetzen die Passwort-Abfrage — auch nicht auf
        # Loopback (sonst öffnet server.py die GUI ohne Login).
        if _password_is_set(self.state):
            return False
        if self._has_valid_token_header():
            return True
        gestellt = (query.get("t") or [""])[0]
        if not gestellt or not secrets.compare_digest(gestellt, self.state.token):
            return False
        # Query-Token: Bootstrap ohne Passwort → Session anlegen.
        self._new_session()
        return True

    def _auth_ok(self, query: dict) -> bool:
        _ensure_server_names()
        if self._session_ok():
            return True
        if self._token_ok(query):
            return True
        if _start9_proxy_authenticated(self.state, self.headers):
            # StartOS Basic Auth already checked uiPassword; persist that
            # result in the same session form as the SatSage login.
            self._new_session()
            return True
        return False

    def _origin_ok(self) -> bool:
        _ensure_server_names()
        raw = self.headers.get("Origin") or self.headers.get("Referer")
        if not raw or raw.lower() == "null":
            return False
        try:
            parsed = urlparse(raw)
            origin_host = _normalisiere_host(parsed.netloc)
        except ValueError:
            return False
        if not origin_host or not self._host_value_ok(origin_host):
            return False
        return origin_host == self._request_host()

    def _csrf_ok(self, methode: str) -> bool:
        _ensure_server_names()
        if methode not in ("POST", "PUT", "DELETE"):
            return True
        if self._has_valid_token_header():
            return True
        if not _password_is_set(self.state) and _env_setting(self.state, "SATSAGE_TRUST_PROXY") != "1":
            return True
        return self._origin_ok()

    def _rate_limited(self) -> bool:
        _ensure_server_names()
        now = time.time()
        ip = _client_ip(self)
        with self.state._auth_lock:
            values = [stamp for stamp in self.state._login_failures.get(ip, []) if now - stamp < LOGIN_WINDOW]
            self.state._login_failures[ip] = values
            return len(values) >= LOGIN_MAX_FAILURES

    def _record_login_failure(self) -> None:
        _ensure_server_names()
        now = time.time()
        ip = _client_ip(self)
        with self.state._auth_lock:
            values = [stamp for stamp in self.state._login_failures.get(ip, []) if now - stamp < LOGIN_WINDOW]
            values.append(now)
            self.state._login_failures[ip] = values

    def _login_succeeded(self) -> None:
        _ensure_server_names()
        with self.state._auth_lock:
            self.state._login_failures.pop(_client_ip(self), None)
        self._new_session()

    def _login_page(self) -> None:
        _ensure_server_names()
        if self._auth_ok({}):
            self._redirect("/")
            return
        password_set = _password_is_set(self.state)
        lang = _ui_lang_fuer_web(
            self.state.env().values(), self.headers.get("Accept-Language")
        )
        t = _LOGIN_TEXTE[lang]
        setup = ""
        if not password_set:
            setup = (
                f"<h2>{t['ersteinrichtung']}</h2>"
                f"<p>{t['nur_loopback']}</p>"
                '<form id="setup-form" action="/api/auth/setup" method="post">'
                f'<label for="new-password">{t["neues_passwort"]}</label>'
                '<input id="new-password" name="password" type="password" '
                'autocomplete="new-password" required autofocus>'
                f'<label for="confirm-password">{t["wiederholen"]}</label>'
                '<input id="confirm-password" name="confirm" type="password" '
                'autocomplete="new-password" required>'
                f'<button type="submit">{t["passwort_setzen"]}</button></form>'
            )
        if password_set:
            if self.state.managed_by == "start9":
                plattform_hinweis = f'<p class="hinweis">{t["hinweis_start9"]}</p>'
            elif self.state.managed_by == "umbrel":
                plattform_hinweis = f'<p class="hinweis">{t["hinweis_umbrel"]}</p>'
            else:
                plattform_hinweis = ""
            inhalt = (
                f"<h1>{t['anmelden']}</h1>"
                f"<p>{t['passwort_eingeben']}</p>"
                f"{plattform_hinweis}"
                '<form id="login-form" action="/api/auth/login" method="post">'
                f'<label for="password">{t["passwort"]}</label>'
                '<input id="password" name="password" type="password" '
                'autocomplete="current-password" required autofocus>'
                f'<button type="submit">{t["anmelden"]}</button></form>'
            )
        else:
            inhalt = (
                f"<h1>{t['willkommen']}</h1>"
                f"<p>{t['noch_kein_passwort']}</p>"
            )
        js = LOGIN_PAGE_JS.replace(
            "__LOGIN_T__",
            json.dumps(_login_js_texte(t), ensure_ascii=False),
        )
        body = (
            f'<!doctype html><html lang="{lang}">'
            "<head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"color-scheme\" content=\"light dark\">"
            f"<title>{t['titel']}</title>"
            "<link rel=\"icon\" type=\"image/png\" sizes=\"32x32\" href=\"/img/favicon-32.png\">"
            "<link rel=\"apple-touch-icon\" href=\"/img/apple-touch-icon.png\">"
            "<script>(function(){try{var t=localStorage.getItem('satsage-ui-theme');"
            "document.documentElement.setAttribute('data-theme',t==='dark'?'dark':'light');"
            "}catch(e){document.documentElement.setAttribute('data-theme','light');}})();</script>"
            f"<style>{LOGIN_PAGE_CSS}</style></head><body>"
            "<main class=\"karte\">"
            "<div class=\"marke\">"
            "<img class=\"marke-logo\" src=\"/img/sat-logo.png\" width=\"44\" height=\"44\" "
            "alt=\"SatSage\" decoding=\"async\">"
            "<div class=\"marke-text\">"
            "<span class=\"marke-name\">SatSage</span>"
            "<span class=\"marke-zusatz\">know your sats</span>"
            "</div></div>"
            f"{inhalt}{setup}"
            '<p id="login-meldung" class="meldung" hidden role="status" aria-live="polite"></p>'
            f'<p class="fuss"><a href="/api/health">{t["status_pruefen"]}</a></p>'
            "</main>"
            f"<script>{js}</script>"
            "</body></html>"
        ).encode("utf-8")
        self._send(200, body, "text/html; charset=utf-8")

    def _auth_status(self) -> dict:
        _ensure_server_names()
        # The status endpoint must establish the same session as initial HTML.
        authenticated = self._auth_ok({})
        return {
            "password_set": _password_is_set(self.state),
            "authenticated": authenticated,
            "setup_required": not _password_is_set(self.state),
        }

    def _auth_api(self, methode: str, pfad: str) -> bool:
        _ensure_server_names()
        if pfad == "/api/auth/status" and methode == "GET":
            self._json(200, self._auth_status())
            return True
        if pfad == "/api/auth/login" and methode == "POST":
            if not _password_is_set(self.state):
                self._fehler(409, "Noch kein Passwort gesetzt.")
                return True
            if self._rate_limited():
                self._fehler(429, "Zu viele Fehlversuche. Später erneut versuchen.")
                return True
            try:
                body = self._body()
                password = str(body.get("password") or "")
                phase = str(body.get("phase") or "full").strip().lower()
            except ApiError as exc:
                self._fehler(exc.status, exc.message)
                return True
            is_form = (
                (self.headers.get("Content-Type") or "").split(";", 1)[0].lower()
                == "application/x-www-form-urlencoded"
            )
            # phase=unlock: Session aus phase=auth; Passwort nur für File-Key
            # (kein zweites Argon2 — spart Zeit im PyInstaller-Build).
            if phase == "unlock":
                if not self._session_ok():
                    self._fehler(403, "Anmeldung erforderlich.")
                    return True
                if not password:
                    self._fehler(400, "Passwort fehlt.")
                    return True
                try:
                    _scramble_unlock(self.state, password)
                except Exception as exc:
                    self._fehler(403, f"Konfiguration entsperren fehlgeschlagen: {exc}")
                    return True
                self._json(200, {
                    "ok": True,
                    "authenticated": True,
                    "unlocked": True,
                    "env_scramble": _env_scramble_status(self.state),
                })
                return True
            if not _verify_password(password, _password_hash(self.state)):
                self._record_login_failure()
                self._fehler(403, "Passwort ist falsch.")
                return True
            self._login_succeeded()
            # JSON phase=auth: Session sofort, Unlock folgt als zweiter Request
            # (Login-Dialog kann „Passwort korrekt — Entschlüsselung…“ zeigen).
            # Form-POST und phase=full: Unlock im selben Schritt (kein JS / API).
            defer_unlock = (not is_form) and phase == "auth"
            if not defer_unlock:
                try:
                    _scramble_unlock(self.state, password)
                except Exception as exc:
                    self._fehler(403, f"Konfiguration entsperren fehlgeschlagen: {exc}")
                    return True
            if is_form:
                self._redirect("/")
            else:
                scramble = _env_scramble_status(self.state)
                unlock_needed = defer_unlock and _unlock_needed_after_auth(self.state)
                self._json(200, {
                    "ok": True,
                    "authenticated": True,
                    "unlock_needed": unlock_needed,
                    "env_scramble": scramble,
                })
            return True
        if pfad == "/api/auth/setup" and methode == "POST":
            if _password_is_set(self.state):
                self._fehler(409, "Passwort ist bereits gesetzt.")
                return True
            if not self._loopback_request():
                self._fehler(403, "Passwort-Ersteinrichtung nur über Loopback.")
                return True
            try:
                body = self._body()
                password = str(body.get("password") or body.get("new_password") or "")
                confirm = str(body.get("confirm") or body.get("password_confirm") or password)
            except ApiError as exc:
                self._fehler(exc.status, exc.message)
                return True
            if not password or password != confirm:
                self._fehler(400, "Passwörter stimmen nicht überein oder sind leer.")
                return True
            _write_password_hash(self.state, password)
            try:
                _scramble_enable_for_password(self.state, password)
            except Exception as exc:
                self._fehler(400, f"env-scramble: {exc}")
                return True
            self._login_succeeded()
            if (self.headers.get("Content-Type") or "").split(";", 1)[0].lower() == "application/x-www-form-urlencoded":
                self._redirect("/")
            else:
                self._json(201, {
                    "ok": True,
                    "authenticated": True,
                    "env_scramble": _env_scramble_status(self.state),
                })
            return True
        if pfad == "/api/auth/logout" and methode in ("POST", "DELETE"):
            sid = self._session_id()
            if sid:
                with self.state._auth_lock:
                    self.state.sessions.pop(sid, None)
            try:
                from core import env_scramble as sc_mod
                sc_mod.clear_session_key()
            except Exception:
                pass
            self.state.env_scramble_unlocked = False
            self._set_session_cookie("", delete=True)
            self._json(200, {"ok": True, "authenticated": False})
            return True
        if pfad == "/api/auth/password" and methode in ("POST", "PUT"):
            if not self._auth_ok({}):
                self._fehler(403, "Anmeldung erforderlich.")
                return True
            if not self._csrf_ok(methode):
                self._fehler(403, "Origin/Referer fehlt oder ist nicht erlaubt.")
                return True
            try:
                body = self._body()
                current = str(body.get("current_password") or body.get("old_password") or "")
                password = str(body.get("new_password") or body.get("password") or "")
                confirm = str(body.get("confirm") or body.get("password_confirm") or password)
            except ApiError as exc:
                self._fehler(exc.status, exc.message)
                return True
            stored = _password_hash(self.state)
            if stored and not _verify_password(current, stored) and not self._loopback_request():
                self._fehler(403, "Aktuelles Passwort ist falsch.")
                return True
            # Auch lokal: bei gesetztem Passwort muss das aktuelle stimmen
            # (Einstellungen-UI), außer Ersteinrichtung ohne Hash.
            if stored and not _verify_password(current, stored):
                self._fehler(403, "Aktuelles Passwort ist falsch.")
                return True
            if not password or password != confirm:
                self._fehler(400, "Passwörter stimmen nicht überein oder sind leer.")
                return True
            # Hash zuerst (atomar), dann Scramble — siehe api_save_app_password.
            try:
                _write_password_hash(self.state, password)
            except Exception as exc:
                self._fehler(500, f"Passwort-Hash fehlgeschlagen: {exc}")
                return True
            try:
                from core import env_scramble as sc_mod

                if stored and sc_mod.is_scramble_file_present(self.state.env_path):
                    _scramble_change_password(self.state, current, password)
                else:
                    # Ersteinrichtung oder Hash ohne Cipher (Feature neu): enable.
                    _scramble_enable_for_password(self.state, password)
            except Exception as exc:
                self._fehler(400, f"env-scramble: {exc}")
                return True
            with self.state._auth_lock:
                self.state.sessions.clear()
            self._login_succeeded()
            self._json(200, {
                "ok": True,
                "authenticated": True,
                "password_set": True,
                "env_scramble": _env_scramble_status(self.state),
            })
            return True
        if pfad == "/api/auth/password" and methode == "DELETE":
            if not self._auth_ok({}):
                self._fehler(403, "Anmeldung erforderlich.")
                return True
            if not self._csrf_ok(methode):
                self._fehler(403, "Origin/Referer fehlt oder ist nicht erlaubt.")
                return True
            try:
                body = self._body()
                current = str(
                    body.get("current_password") or body.get("old_password") or ""
                )
            except ApiError as exc:
                self._fehler(exc.status, exc.message)
                return True
            if not _password_is_set(self.state):
                self._json(200, {
                    "ok": True,
                    "password_set": False,
                    "env_scramble": _env_scramble_status(self.state),
                })
                return True
            if not current or not _verify_password(current, _password_hash(self.state)):
                self._fehler(403, "Aktuelles Passwort ist falsch.")
                return True
            try:
                _scramble_disable_for_password(self.state, current)
            except Exception as exc:
                self._fehler(400, f"env-scramble: {exc}")
                return True
            _clear_password_hash(self.state)
            with self.state._auth_lock:
                self.state.sessions.clear()
            # Nach Entfernen: Session neu (Token bleibt Session-Cookie-Flow).
            self._login_succeeded()
            self._json(200, {
                "ok": True,
                "password_set": False,
                "env_scramble": _env_scramble_status(self.state),
            })
            return True
        if pfad == "/api/auth/unlock-env" and methode == "POST":
            # Nach Serverstart: gobbledigook öffnen (File-Key nur RAM).
            if not self._auth_ok({}) and not self._loopback_request():
                self._fehler(403, "Anmeldung erforderlich.")
                return True
            if not self._csrf_ok(methode) and not self._loopback_request():
                self._fehler(403, "Origin/Referer fehlt oder ist nicht erlaubt.")
                return True
            try:
                body = self._body()
                password = str(body.get("password") or body.get("current_password") or "")
            except ApiError as exc:
                self._fehler(exc.status, exc.message)
                return True
            if not password:
                self._fehler(400, "Passwort fehlt.")
                return True
            if _password_is_set(self.state) and not _verify_password(
                password, _password_hash(self.state),
            ):
                self._fehler(403, "Passwort ist falsch.")
                return True
            try:
                _scramble_unlock(self.state, password)
            except Exception as exp:
                self._fehler(403, f"Unlock fehlgeschlagen: {exp}")
                return True
            if not self._session_ok():
                self._login_succeeded()
            self._json(200, {
                "ok": True,
                "env_scramble": _env_scramble_status(self.state),
            })
            return True
        return False
