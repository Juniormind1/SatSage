#!/usr/bin/env python3
"""
Lokale Web-Oberfläche für SatSage.

Start:  python3 server.py

Bindet ausschließlich an 127.0.0.1 und verlangt für jeden API-Aufruf ein
Sitzungs-Token, das beim Start ausgegeben wird. Grund: Sobald XPUBs durch
einen Browser laufen, kann jede beliebige besuchte Webseite versuchen, mit
diesem Server zu sprechen. Das Token und die Host-Prüfung verhindern das.

Kein Framework — Standardbibliothek, wie der Rest des Projekts.
"""
from __future__ import annotations

import sys

# Tk-Splash-Kind: vor schweren Imports, damit das Fenster früh erscheint.
if __name__ == "__main__" and "--splash-only" in sys.argv:
    from core.splash_ui import lauf_splash_kind

    raise SystemExit(lauf_splash_kind(sys.argv))

import argparse
import errno
import fnmatch
import hashlib
import hmac
import ipaddress
import json
import logging
import stat
import mimetypes
import os
import re
import secrets
import shutil
import socket
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse, urlsplit, urlunsplit, urlencode

try:
    from argon2 import PasswordHasher
    from argon2 import Type as ArgonType
except ImportError:
    PasswordHasher = None
    ArgonType = None

import analyze
import labels
import main
import sanctioned
from core import llm_anbindung as llm_mod
from core import llm_client as llm_chat
from core import llm_context as llm_ctx
from core import price as price_mod
from core import sanctions as sanctions_mod
from core import gui_session as gui_session_mod
from core import single_instance as single_mod
from core import source as source_mod
from core import splash_ui as splash_ui_mod
from core import status_mail as status_mail_mod
from core import tax as tax_mod
from core import trace as trace_mod
from core import trace_cache
from core import utxos as utxos_mod
from core import wallets as wallets_mod
from core.bitcoind_rpc import rpc_credentials_from_env
from core import config as config_mod
from core.config import (
    BestaetigungNoetig,
    bloecke_nach_luecke,
    mempool_info,
    normalize_mempool_url,
    EnvFile,
    WalletEntry,
    read_wallets,
    write_wallets,
)
from core.jobs import (
    Cancelled,
    JobRegistry,
    JobQuotaExceeded,
    ScanQueue,
    ScanSchonGeplant,
    setze_fertig_hook,
)
from core.paths import resource_dir
import outbound_policy

WEB_DIR = resource_dir() / "web"
HANDBUCH_PFAD = resource_dir() / "doc" / "handbuch.html"
DEFAULT_PORT = 8730
BIND_HOST = "127.0.0.1"
SESSION_COOKIE = "satsage_session"
SESSION_TTL = 7 * 24 * 60 * 60
LOGIN_WINDOW = 15 * 60
LOGIN_MAX_FAILURES = 5
DEFAULT_MAX_PARALLEL_JOBS = 3
LOGGER = logging.getLogger("satsage.server")
_SENSITIVE_QUERY_KEYS = frozenset(("t", "token", "password", "secret", "key"))
# Branding for /login without opening the rest of the UI shell (H4).
LOGIN_PUBLIC_ASSETS = frozenset((
    "/img/sat-logo.png",
    "/img/logo-mark.png",
    "/img/favicon-32.png",
    "/img/apple-touch-icon.png",
))
LOGIN_PAGE_CSS = """
:root,html[data-theme=light]{
  color-scheme:light;
  --grund:#E7EAE7;--flaeche:#F7F9F6;--flaeche-2:#EDF0EC;--linie:#CBD2CD;
  --text:#18222A;--gedaempft:#5F6B74;--blass:#8A959C;
  --akzent:#B25834;--akzent-zart:#F1DDD3;--auf-akzent:#FFFFFF;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
  --mono:ui-monospace,"JetBrains Mono",SFMono-Regular,Menlo,Consolas,monospace;
  --r:3px;
}
html[data-theme=dark]{
  color-scheme:dark;
  --grund:#1A1E22;--flaeche:#22272C;--flaeche-2:#2A3036;--linie:#3D464E;
  --text:#E8ECEB;--gedaempft:#A8B2B8;--blass:#8A949A;
  --akzent:#D7815A;--akzent-zart:#3A2318;--auf-akzent:#1A1008;
}
*{box-sizing:border-box}
html{color-scheme:light dark}
body{
  margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
  padding:24px;background:var(--grund);color:var(--text);font:14px/1.55 var(--sans);
  -webkit-font-smoothing:antialiased;
}
.karte{
  width:min(26rem,100%);background:var(--flaeche);border:1px solid var(--linie);
  border-radius:4px;padding:28px 26px;box-shadow:0 18px 48px rgba(24,34,42,.28);
}
.marke{display:flex;align-items:center;gap:12px;margin:0 0 22px}
.marke-logo{
  width:44px;height:44px;border-radius:10px;object-fit:contain;flex-shrink:0;
  box-shadow:0 0 0 1px var(--linie);background:#F0F3F0;
}
.marke-text{display:flex;flex-direction:column;gap:2px;line-height:1.15}
.marke-name{font-family:var(--mono);font-weight:700;letter-spacing:-.01em;font-size:18px}
.marke-zusatz{
  font-family:var(--mono);font-size:10px;letter-spacing:.08em;
  text-transform:lowercase;color:var(--blass);
}
h1{font-family:var(--mono);font-size:18px;margin:0 0 8px;font-weight:700}
h2{font-family:var(--mono);font-size:14px;margin:22px 0 8px;font-weight:700}
p{margin:0 0 12px;color:var(--gedaempft)}
.hinweis{
  margin:0 0 16px;padding:10px 12px;background:var(--flaeche-2);
  border:1px solid var(--linie);border-radius:var(--r);font-size:12px;color:var(--gedaempft);
}
label{display:block;margin:.85rem 0 .35rem;font-size:12px;color:var(--gedaempft)}
input{
  width:100%;padding:.65rem .7rem;border:1px solid var(--linie);border-radius:var(--r);
  background:var(--flaeche-2);color:var(--text);font:inherit;
}
input:focus{outline:2px solid var(--akzent);outline-offset:1px}
button{
  margin-top:1rem;width:100%;padding:.7rem .9rem;border:1px solid var(--akzent);
  border-radius:var(--r);background:var(--akzent);color:var(--auf-akzent);
  font-family:var(--mono);font-size:12px;font-weight:600;letter-spacing:.03em;cursor:pointer;
}
button:hover{filter:brightness(1.08)}
button:disabled{opacity:.65;cursor:wait;filter:none}
.meldung{
  margin:14px 0 0;padding:10px 12px;border-radius:var(--r);font-size:13px;line-height:1.45;
  border:1px solid var(--linie);background:var(--flaeche-2);color:var(--gedaempft);
}
.meldung[hidden]{display:none!important}
.meldung-krit{
  border-color:#c45c4a;background:rgba(196,92,74,.12);color:var(--text);font-weight:600;
}
.meldung-gut{
  border-color:#3d8f6e;background:rgba(61,143,110,.12);color:var(--text);
}
.meldung-warn{
  border-color:var(--akzent);background:var(--akzent-zart);color:var(--text);
}
.fuss{margin-top:18px;font-size:12px}
.fuss a{color:var(--akzent);text-decoration:none}
.fuss a:hover{text-decoration:underline}
""".strip()

# Login ohne app.js: Form per fetch, Fehler im Dialog, Fortschritt bei Unlock.
LOGIN_PAGE_JS = r"""
(function () {
  var T = __LOGIN_T__;
  function safeNext() {
    try {
      var n = new URLSearchParams(location.search).get("next") || "/";
      if (n.charAt(0) !== "/" || n.indexOf("//") === 0) return "/";
      return n;
    } catch (e) {
      return "/";
    }
  }
  function $(sel, root) {
    return (root || document).querySelector(sel);
  }
  function setMsg(el, text, art) {
    if (!el) return;
    el.hidden = !text;
    el.textContent = text || "";
    el.className = "meldung" + (art ? " meldung-" + art : "");
  }
  function mapError(msg) {
    var s = String(msg || "");
    if (/falsch|wrong|incorrect|invalid password/i.test(s)) return T.passwort_falsch;
    if (/viele|rate|later|später|spaeter/i.test(s)) return T.zu_viele;
    if (/überein|ueberein|match|leer|empty/i.test(s)) return T.mismatch;
    return s || T.fehler;
  }
  async function postJson(url, body) {
    var res = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body || {}),
    });
    var data = {};
    try {
      data = await res.json();
    } catch (e) {
      data = {};
    }
    if (!res.ok) {
      var err = new Error((data && data.error) || res.statusText || T.fehler);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }
  function bindLogin(form) {
    if (!form) return;
    var msg = $("#login-meldung");
    var btn = form.querySelector('button[type="submit"]');
    var pw = form.querySelector("#password");
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var password = pw ? String(pw.value || "") : "";
      if (!password) {
        setMsg(msg, T.passwort_falsch, "krit");
        return;
      }
      if (btn) btn.disabled = true;
      setMsg(msg, T.pruefen, "warn");
      postJson("/api/auth/login", { password: password, phase: "auth" })
        .then(function (data) {
          var need =
            data &&
            (data.unlock_needed === true ||
              (data.env_scramble && data.env_scramble.locked));
          if (need) {
            setMsg(msg, T.entschluesseln, "gut");
            return postJson("/api/auth/login", {
              password: password,
              phase: "unlock",
            });
          }
          return data;
        })
        .then(function () {
          setMsg(msg, T.fertig, "gut");
          location.href = safeNext();
        })
        .catch(function (err) {
          setMsg(msg, mapError(err && err.message), "krit");
          if (btn) btn.disabled = false;
          if (pw) {
            pw.focus();
            try {
              pw.select();
            } catch (e) {}
          }
        });
    });
  }
  function bindSetup(form) {
    if (!form) return;
    var msg = $("#login-meldung");
    var btn = form.querySelector('button[type="submit"]');
    var a = form.querySelector("#new-password");
    var b = form.querySelector("#confirm-password");
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var password = a ? String(a.value || "") : "";
      var confirm = b ? String(b.value || "") : "";
      if (!password || password !== confirm) {
        setMsg(msg, T.mismatch, "krit");
        return;
      }
      if (btn) btn.disabled = true;
      setMsg(msg, T.einrichten, "warn");
      postJson("/api/auth/setup", { password: password, confirm: confirm })
        .then(function () {
          setMsg(msg, T.fertig, "gut");
          location.href = safeNext();
        })
        .catch(function (err) {
          setMsg(msg, mapError(err && err.message), "krit");
          if (btn) btn.disabled = false;
        });
    });
  }
  bindLogin($("#login-form"));
  bindSetup($("#setup-form"));
})();
""".strip()


_LOOPBACK_HOSTS = frozenset(("127.0.0.1", "localhost", "::1"))

# Plattformen, die Node- und Indexer-Adressen per Prozess-Env vorgeben und
# deren Datenquellen-Felder deshalb in der UI gesperrt sind.
_NODE_MANAGED = frozenset(("start9", "umbrel"))
# Alle Modi, in denen SatSage nicht allein über die eigene .env konfiguriert wird.
_MANAGED_MODI = frozenset(("specter", "start9", "umbrel"))
# Anzeigename je Modus für Hinweise und Fehlermeldungen.
_MANAGED_PLATTFORM = {"start9": "Start9", "umbrel": "Umbrel", "specter": "Specter"}


def _managed_by_from_env(explicit: str | None, env_path: Path) -> str | None:
    if explicit in _MANAGED_MODI:
        return explicit
    try:
        values = EnvFile.load(env_path).values()
    except (OSError, UnicodeError):
        values = {}
    managed = str(
        os.environ.get("SATSAGE_MANAGED_BY") or values.get("SATSAGE_MANAGED_BY", "")
    ).strip().lower()
    if managed in _NODE_MANAGED:
        return managed
    flag = os.environ.get("SATSAGE_START9")
    if flag is None:
        flag = values.get("SATSAGE_START9", "")
    if str(flag).strip().lower() in ("1", "true", "yes", "ja", "on"):
        return "start9"
    return "specter" if explicit == "specter" else None


def _managed_mode(state: AppState) -> bool:
    return state.managed_by in _MANAGED_MODI


def _env_setting(state: AppState | None, key: str) -> str:
    value = os.environ.get(key)
    if value is not None:
        return value.strip()
    if state is not None:
        try:
            return str(state.env().values().get(key, "") or "").strip()
        except (OSError, AttributeError):
            pass
    return ""


def _max_parallel_jobs(state=None, env_values=None) -> int:
    raw = os.environ.get("SATSAGE_MAX_PARALLEL_JOBS")
    if raw is None and env_values is not None:
        raw = env_values.get("SATSAGE_MAX_PARALLEL_JOBS")
    if raw is None and state is not None:
        raw = _env_setting(state, "SATSAGE_MAX_PARALLEL_JOBS")
    try:
        return max(1, min(int(str(raw or DEFAULT_MAX_PARALLEL_JOBS).strip()), 32))
    except (TypeError, ValueError):
        return DEFAULT_MAX_PARALLEL_JOBS


def _pruefe_env_modus(env_path: Path) -> None:
    """
    Sichert .env und Start-Backups (backup0–9, legacy .bak) gegen Mitlesen.

    POSIX: Dateimodus ``0600``. Unter **Windows** greift ``chmod`` faktisch
    nicht (``stat`` bleibt oft ``0666``) — Warnungen wären Dauer-Spam ohne
    Nutzen; NTFS-ACLs steuern den Zugriff. Deshalb hier still übersprungen.
    """
    if sys.platform == "win32":
        return

    from core.config import ENV_BACKUP_SLOTS, env_backup_path

    kandidaten = [env_path, env_path.with_suffix(env_path.suffix + ".bak")]
    for i in range(ENV_BACKUP_SLOTS):
        kandidaten.append(env_backup_path(env_path, i))
    for pfad in kandidaten:
        try:
            if not pfad.is_file() or not stat.S_ISREG(pfad.stat().st_mode):
                continue
            modus = stat.S_IMODE(pfad.stat().st_mode)
            if modus == 0o600:
                continue
            os.chmod(pfad, 0o600)
            neu = stat.S_IMODE(pfad.stat().st_mode)
            if neu != 0o600:
                # chmod wirkungslos (seltenes FS) — nicht jeden Start spammen
                continue
            # Nur stderr — LOGGER + print doppelte die Zeile in der Konsole.
            print(
                f"Warnung: Modus von {pfad.name} war {modus:04o}; auf 0600 korrigiert.",
                file=sys.stderr,
                flush=True,
            )
        except OSError as exc:
            LOGGER.warning("Konnte Modus von %s nicht prüfen/korrigieren: %s", pfad, exc)


def _redact_url(value: str) -> str:
    """Entfernt Geheimnisse aus Request-Zielen, bevor sie geloggt werden."""
    try:
        parsed = urlsplit(str(value or ""))
        pairs = []
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
            pairs.extend((key, "[redigiert]" if key.lower() in _SENSITIVE_QUERY_KEYS else item) for item in values)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs), parsed.fragment))
    except (TypeError, ValueError):
        return "[ungültiges Request-Ziel]"


def _bind_host(bind: str | None = None, *, state=None, args=None) -> str:
    if bind is not None and str(bind).strip():
        return str(bind).strip()
    cli_bind = getattr(args, "bind", None) if args is not None else None
    if cli_bind:
        return str(cli_bind).strip()
    return _env_setting(state, "SATSAGE_BIND") or BIND_HOST


def _ist_local_only(state=None) -> bool:
    """Ob der Listener tatsächlich nur über Loopback erreichbar ist.

    Hinter Umbrels ``app_proxy`` bindet SatSage an ``0.0.0.0`` und ist aus
    dem ganzen LAN erreichbar — die Fußzeile darf dann nicht das Gegenteil
    behaupten.
    """
    try:
        return ipaddress.ip_address(_bind_host(state=state)).is_loopback
    except ValueError:
        return False


#: Die Anmeldeseite wird vom Server gerendert und erreicht die Kataloge unter
#: ``web/locales/`` nicht. Sie ist außerdem das Erste, was ein Nutzer aus dem
#: App Store sieht — sie darf nicht einsprachig sein.
_LOGIN_TEXTE = {
    "de": {
        "titel": "SatSage – Anmeldung",
        "anmelden": "Anmelden",
        "passwort": "Passwort",
        "passwort_eingeben": "Bitte Passwort eingeben.",
        "willkommen": "Willkommen",
        "noch_kein_passwort": (
            "Noch kein Passwort — unten einrichten, "
            "oder mit Token von der Konsole öffnen."
        ),
        "ersteinrichtung": "Ersteinrichtung",
        "nur_loopback": "Ohne Passwort ist die Einrichtung nur über Loopback möglich.",
        "neues_passwort": "Neues Passwort",
        "wiederholen": "Wiederholen",
        "passwort_setzen": "Passwort setzen",
        "status_pruefen": "Status prüfen",
        "hinweis_start9": (
            "StartOS: Benutzername <strong>admin</strong>. Bei gestopptem Dienst "
            "finden oder rotieren Sie das Passwort unter "
            "<strong>Actions &amp; Config</strong>."
        ),
        "hinweis_umbrel": "Umbrel zeigt dieses Passwort in den App-Details von SatSage an.",
        # Client-JS (Login-Dialog, kein app.js)
        "passwort_falsch": "Passwort falsch.",
        "pruefen": "Passwort wird geprüft…",
        "entschluesseln": "Passwort korrekt — Entschlüsselung läuft…",
        "fertig": "Bereit — öffne SatSage…",
        "einrichten": "Passwort wird gesetzt und Konfiguration geschützt…",
        "zu_viele": "Zu viele Fehlversuche. Später erneut versuchen.",
        "mismatch": "Passwörter stimmen nicht überein oder sind leer.",
        "fehler": "Anmeldung fehlgeschlagen.",
    },
    "en": {
        "titel": "SatSage – Sign in",
        "anmelden": "Sign in",
        "passwort": "Password",
        "passwort_eingeben": "Please enter your password.",
        "willkommen": "Welcome",
        "noch_kein_passwort": (
            "No password yet — set one below, "
            "or open with the token from the console."
        ),
        "ersteinrichtung": "First-time setup",
        "nur_loopback": "Without a password, setup is only possible over loopback.",
        "neues_passwort": "New password",
        "wiederholen": "Repeat",
        "passwort_setzen": "Set password",
        "status_pruefen": "Check status",
        "hinweis_start9": (
            "StartOS: username <strong>admin</strong>. While the service is "
            "stopped you can find or rotate the password under "
            "<strong>Actions &amp; Config</strong>."
        ),
        "hinweis_umbrel": "Umbrel shows this password in the SatSage app details.",
        "passwort_falsch": "Wrong password.",
        "pruefen": "Checking password…",
        "entschluesseln": "Password correct — decrypting…",
        "fertig": "Ready — opening SatSage…",
        "einrichten": "Setting password and protecting configuration…",
        "zu_viele": "Too many failed attempts. Try again later.",
        "mismatch": "Passwords do not match or are empty.",
        "fehler": "Sign-in failed.",
    },
}


def _login_js_texte(t: dict) -> dict:
    """Untermenge der Login-Texte für das eingebettete Anmelde-Skript."""
    keys = (
        "passwort_falsch",
        "pruefen",
        "entschluesseln",
        "fertig",
        "einrichten",
        "zu_viele",
        "mismatch",
        "fehler",
    )
    return {k: t[k] for k in keys if k in t}


def _unlock_needed_after_auth(state) -> bool:
    """Ob nach Login-Auth noch File-Key/Scramble-Unlock nötig ist."""
    if not _env_scramble_erlaubt(state):
        return False
    st = _env_scramble_status(state)
    if st.get("locked"):
        return True
    # Passwort gesetzt, .env noch Klartext → Unlock scramblt nach.
    if st.get("allowed") and st.get("plain_env_present"):
        return True
    return False


def _sprache_aus_accept_language(header: str | None) -> str | None:
    """Beste unterstützte Sprache aus einem ``Accept-Language``-Header.

    Unterstützt werden nur ``de`` und ``en``. ``*`` zählt nicht als Treffer,
    weil sich daraus keine Absicht ablesen lässt, und ``q=0`` heißt
    ausdrücklich „nicht akzeptabel“. Ohne Treffer ``None``.
    """
    beste: tuple[float, str] | None = None
    for eintrag in str(header or "").split(","):
        tag, _, parameter = eintrag.strip().partition(";")
        tag = tag.strip().lower()
        if tag.startswith("en"):
            code = "en"
        elif tag.startswith("de"):
            code = "de"
        else:
            continue
        gewicht = 1.0
        for param in parameter.split(";"):
            name, _, wert = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    gewicht = float(wert.strip())
                except ValueError:
                    gewicht = 0.0
        if gewicht <= 0:
            continue
        if beste is None or gewicht > beste[0]:
            beste = (gewicht, code)
    return beste[1] if beste else None


class ApiError(Exception):
    """Fehler mit HTTP-Status und Meldung für die Oberfläche."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _normalisiere_host(value: str) -> str:
    raw = str(value or "").strip().split(",", 1)[0].strip().lower()
    if raw.startswith("["):
        ende = raw.find("]")
        if ende > 0:
            raw = raw[1:ende]
    elif raw.count(":") == 1:
        raw = raw.partition(":")[0]
    try:
        return ipaddress.ip_address(raw).compressed.lower()
    except ValueError:
        return raw.rstrip(".")


def _host_pattern_ok(host: str, pattern: str) -> bool:
    pattern = _normalisiere_host(pattern)
    if not pattern:
        return False
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return host.endswith(suffix) and host != suffix[1:]
    if pattern.startswith("."):
        return host.endswith(pattern) and host != pattern[1:]
    return host == pattern or fnmatch.fnmatchcase(host, pattern)


def _host_allowlist(state) -> list[str]:
    values = []
    process_value = os.environ.get("SATSAGE_HOST_ALLOWLIST")
    if process_value is not None:
        values.append(process_value)
    if state is not None:
        try:
            values.append(state.env().values().get("SATSAGE_HOST_ALLOWLIST", ""))
        except (OSError, AttributeError):
            pass
    return [item.strip() for value in values for item in str(value or "").split(",") if item.strip()]

def api_health(state) -> dict:
    from core.version import version as app_version

    return {
        "ok": True,
        "version": app_version(),
        "managed_by": state.managed_by,
    }


def _auth_file(state) -> Path:
    """Liefert die Passwortdatei, niemals einen Pfad in der .env selbst."""
    configured = _env_setting(state, "SATSAGE_PASSWORD_FILE")
    return Path(configured).expanduser() if configured else state.env_path.parent / ".satsage-password"


def _password_hash(state) -> str:
    path = _auth_file(state)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        value = ""
    # Für Tests/Bootstrap erlaubt, aber nicht empfohlen: ein bereits gehashter
    # Wert aus der Umgebung. Niemals ein Klartext-Passwort daraus lesen.
    return value or _env_setting(state, "SATSAGE_PASSWORD_HASH")


def _password_is_set(state) -> bool:
    return bool(_password_hash(state))


def _hash_password(password: str) -> str:
    if PasswordHasher is not None:
        hasher = PasswordHasher(
            time_cost=3,
            memory_cost=64 * 1024,
            parallelism=2,
            type=ArgonType.ID,
        )
        return hasher.hash(password)
    # Dokumentierter Fallback für Minimal-Installationen ohne argon2-cffi.
    # scrypt ist ebenfalls ein speicherharter Passwort-KDF und wird mit
    # zufälligem Salt gespeichert; neue Pakete sollten argon2-cffi installieren.
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 15, 8, 1
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024)
    return "scrypt${}${}${}${}${}".format(n, r, p, salt.hex(), digest.hex())


def _verify_password(password: str, stored: str) -> bool:
    if not password or not stored:
        return False
    if stored.startswith("$argon2") and PasswordHasher is not None:
        try:
            return bool(PasswordHasher().verify(stored, password))
        except Exception:
            return False
    if stored.startswith("scrypt$"):
        try:
            _, n, r, p, salt_hex, digest_hex = stored.split("$", 5)
            candidate = hashlib.scrypt(
                password.encode("utf-8"),
                salt=bytes.fromhex(salt_hex),
                n=int(n), r=int(r), p=int(p), maxmem=128 * 1024 * 1024,
            )
            return hmac.compare_digest(candidate.hex(), digest_hex)
        except (ValueError, TypeError, UnicodeError):
            return False
    return False


def _write_password_hash(state, password: str) -> None:
    """Schreibt den Login-Hash atomar (tmp + replace), ohne fd-chmod-APIs."""
    path = _auth_file(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = (_hash_password(password) + "\n").encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    if tmp.is_file() and os.name == "nt":
        try:
            os.chmod(tmp, 0o666)
        except OSError:
            pass
    tmp.write_bytes(value)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    if path.is_file() and os.name == "nt":
        try:
            os.chmod(path, 0o666)
        except OSError:
            pass
    try:
        os.replace(tmp, path)
    except PermissionError:
        if path.is_file():
            try:
                os.chmod(path, 0o666)
            except OSError:
                pass
            path.unlink()
        os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _clear_password_hash(state) -> None:
    """Entfernt die Passwortdatei (optionales App-Passwort). Env-Hash unberührt."""
    path = _auth_file(state)
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        # Python < 3.8 missing_ok — hier 3.10+
        if path.is_file():
            path.unlink()
    except OSError:
        if path.is_file():
            path.unlink()


def _env_scramble_erlaubt(state) -> bool:
    """Phase 1: kein Scramble unter Umbrel/Start9/Specter-managed."""
    return getattr(state, "managed_by", None) not in _NODE_MANAGED and (
        getattr(state, "managed_by", None) != "specter"
    )


def _env_scramble_status(state) -> dict:
    try:
        from core import env_scramble as sc

        scrambled = sc.is_scramble_file_present(state.env_path)
        path = Path(state.env_path)
        plain = path.is_file() and not sc.is_env_scrambled(path)
        locked = scrambled and sc.get_session_key() is None
        return {
            "active": scrambled,
            "locked": locked,
            "plain_env_present": plain,
            "allowed": _env_scramble_erlaubt(state),
        }
    except Exception:
        return {
            "active": False,
            "locked": False,
            "plain_env_present": Path(state.env_path).is_file(),
            "allowed": False,
        }


def _scramble_enable_for_password(state, password: str) -> None:
    """Nach Passwort-Setzen: ``.env`` scrambled (eine Datei)."""
    if not _env_scramble_erlaubt(state):
        return
    from core import env_scramble as sc

    try:
        env = state.env()
        plain = env.render()
    except Exception:
        plain = ""
    if not plain.strip() and Path(state.env_path).is_file():
        plain = Path(state.env_path).read_text(encoding="utf-8")
    if not plain.strip() and sc.is_scramble_file_present(state.env_path):
        sc.change_scramble_password(state.env_path, password, password)
        state.env_scramble_unlocked = True
        try:
            state.reload()
        except Exception:
            pass
        return
    if not plain.strip():
        plain = "\n"
    sc.enable_scramble(state.env_path, plain, password)
    state.env_scramble_unlocked = True
    try:
        state.reload()
    except Exception:
        pass


def _scramble_change_password(state, old_password: str, new_password: str) -> None:
    if not _env_scramble_erlaubt(state):
        return
    from core import env_scramble as sc

    if sc.is_scramble_file_present(state.env_path):
        sc.change_scramble_password(state.env_path, old_password, new_password)
        state.env_scramble_unlocked = True
        try:
            state.reload()
        except Exception:
            pass
        return
    _scramble_enable_for_password(state, new_password)


def _scramble_disable_for_password(state, password: str) -> None:
    if not _env_scramble_erlaubt(state):
        return
    from core import env_scramble as sc

    if not sc.is_scramble_file_present(state.env_path):
        sc.clear_session_key()
        state.env_scramble_unlocked = True
        return
    sc.disable_scramble(state.env_path, password)
    state.env_scramble_unlocked = True
    try:
        state.reload()
    except Exception:
        pass


def _scramble_unlock(state, password: str) -> None:
    """File-Key aus Passwort + Config neu laden (auch Dual-Write-Migration)."""
    from core import env_scramble as sc

    if not _env_scramble_erlaubt(state):
        state.env_scramble_unlocked = True
        return
    if not sc.is_scramble_file_present(state.env_path) and not Path(state.env_path).is_file():
        state.env_scramble_unlocked = True
        return
    sc.unlock_with_password(state.env_path, password)
    state.env_scramble_unlocked = True
    state.reload()


def _seed_managed_password(state) -> None:
    """Keep the platform password and the app hash in sync.

    On StartOS (uiPassword) and Umbrel (``APP_PASSWORD``) the platform value is
    the single source of truth for the SatSage login. Re-hash whenever the
    bootstrap value no longer verifies, e.g. after a password rotation while
    SatSage was stopped.
    """
    bootstrap = os.environ.get("SATSAGE_BOOTSTRAP_PASSWORD", "")
    if state.managed_by not in _NODE_MANAGED and not bootstrap:
        return
    path = _auth_file(state)
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("SatSage-Passwortdatei kann nicht gelesen werden") from exc
    if not bootstrap:
        if state.managed_by in _NODE_MANAGED and not existing:
            plattform = _MANAGED_PLATTFORM.get(state.managed_by, state.managed_by)
            raise RuntimeError(f"{plattform}-Bootstrap-Passwort fehlt")
        return
    if existing and _verify_password(bootstrap, existing):
        os.environ.pop("SATSAGE_BOOTSTRAP_PASSWORD", None)
        return

    _write_password_hash(state, bootstrap)
    # Do not retain the cleartext bootstrap value in the process environment.
    os.environ.pop("SATSAGE_BOOTSTRAP_PASSWORD", None)


def _client_ip(handler) -> str:
    try:
        return str(handler.client_address[0])
    except (AttributeError, IndexError):
        return "unknown"


def _start9_proxy_authenticated(state, headers) -> bool:
    """Return whether StartOS Basic Auth already authenticated this request."""
    if (
        state.managed_by != "start9"
        or _env_setting(state, "SATSAGE_TRUST_PROXY") != "1"
        or not _password_is_set(state)
    ):
        return False
    proto = str(headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
    user = str(headers.get("X-Forwarded-User") or "").split(",", 1)[0].strip()
    # StartOS sets this only after its Basic Auth middleware has accepted the
    # request.  It does not forward X-Forwarded-Host, so the user header is
    # the authoritative proof that the outer login already happened.
    return proto == "https" and bool(user)


class AppState:
    """Gemeinsamer Zustand aller Anfragen."""

    def __init__(self, env_path: Path, cache_dir: Path,
                 immutable_cache_dir: Path, sanctions_dir: Path | None = None,
                 label_dir: Path | None = None, managed_by: str | None = None):
        self.env_path = env_path
        # Vor dem ersten Laufzeit-Schreiben: vorgefundene .env rotieren.
        try:
            from core.config import rotate_env_backups_at_start

            sicherung = rotate_env_backups_at_start(self.env_path)
            if sicherung is not None:
                meldung = ".env in .env.backup[0-9] gesichert."
                print(meldung, flush=True)
                LOGGER.info("%s (%s)", meldung, sicherung.name)
        except OSError as exc:
            LOGGER.warning("env-backup Rotation fehlgeschlagen: %s", exc)
        _pruefe_env_modus(self.env_path)
        self.cache_dir = cache_dir
        self.immutable_cache_dir = immutable_cache_dir
        self.sanctions_dir = sanctions_dir
        self.label_dir = label_dir or labels.LABEL_CACHE_DIR
        # Börsen-CSV-Reports (Klarname Ein-/Auszahlung) neben dem App-Verzeichnis.
        from core import exchange_reports as boerse_mod
        from core.paths import app_dir as _app_dir

        self.exchange_reports_dir = Path(_app_dir()) / "exchange_reports"
        boerse_mod.setze_verzeichnis(self.exchange_reports_dir)
        # None bedeutet eigenständige Desktop-GUI; der Plugin-Einstieg setzt
        # dieses Merkmal ausdrücklich, nicht über eine fremde .env.
        self.managed_by = _managed_by_from_env(managed_by, env_path)
        # Beschriftet wird tief in der Auswertung — einmal hier gesetzt, gilt
        # das Verzeichnis für alle Aufrufe dieses Laufs.
        labels.setze_verzeichnis(self.label_dir)
        self.token = secrets.token_urlsafe(24)
        # Opaque Sessions liegen nur im Prozessspeicher; der dauerhafte
        # Geheimnisbestand ist ausschließlich der Passwort-Hash im Volume.
        self.sessions: dict[str, float] = {}
        self._login_failures: dict[str, list[float]] = {}
        self._auth_lock = threading.Lock()
        # File-Key für .env.gobbledigook nur RAM (core.env_scramble Session).
        self.env_scramble_unlocked = False
        try:
            env0 = EnvFile.load(self.env_path)
            env_vals = env0.values()
            self.env_scramble_unlocked = not bool(getattr(env0, "scramble_locked", False))
        except Exception:
            env_vals = {}
            self.env_scramble_unlocked = True
        self.max_parallel_jobs = _max_parallel_jobs(env_values=env_vals)
        self.jobs = JobRegistry(max_parallel_heavy=self.max_parallel_jobs)
        self.scan_queue = ScanQueue(self.jobs)
        self.header_job_id: str | None = None
        self.wallet_sync_job_id: str | None = None
        # Letzter Quellen-Check (dicts) — fuer /api/config ohne erneute Probe.
        self.sources_last: list[dict] | None = None
        #: monotonic: nächster erlaubter Header-Tip-Check (Cooldown-Spam).
        self.header_vorab_naechstes: float = 0.0
        self._lock = threading.Lock()
        self._wallet_ctx = None
        self._entries: list[WalletEntry] = []
        # Nächste Empfangsadresse je Wallet — sofort beim Wechsel, ohne Netz.
        self.empfang_cache: dict[str, dict] = {}
        # Wiederverwendeter Electrs-Client nur für Empfangs-QR (eigen oder öffentlich).
        self._empfang_fulcrum = None
        self._empfang_public_fulcrum = None
        self._empfang_fulcrum_lock = threading.Lock()
        # Öffentliches Electrum: pro Serverstart neu fragen (keine Dauer-.env).
        source_mod.setze_oeffentliche_electrum_session(False)
        self._streiche_dauerhafte_oeffentliche_electrum()
        self.reload()

    def _streiche_dauerhafte_oeffentliche_electrum(self) -> None:
        """
        Altes ``OEFFENTLICHE_ELECTRUM=1`` aus der ``.env`` nehmen.

        Die Web-GUI speichert die Freigabe nur sitzungsweise; sonst bliebe
        „Privatsphäre gering“ nach Neustart still freigegeben.
        """
        try:
            env = EnvFile.load(self.env_path)
        except OSError:
            return
        if not (env.values().get("OEFFENTLICHE_ELECTRUM") or "").strip():
            return
        env.apply({"OEFFENTLICHE_ELECTRUM": None})
        try:
            env.save()
            LOGGER.info(
                "OEFFENTLICHE_ELECTRUM aus .env entfernt "
                "(Opt-in gilt pro Serverstart)."
            )
        except OSError as exc:
            LOGGER.warning(
                "OEFFENTLICHE_ELECTRUM konnte nicht aus .env entfernt werden: %s",
                exc,
            )

    def set_managed_by(self, value: str | None) -> None:
        """Setzt die Herkunft der Konfiguration für diesen Serverlauf."""
        self.managed_by = _managed_by_from_env(value, self.env_path)

    # -- Konfiguration ------------------------------------------------------

    def env(self) -> EnvFile:
        env = EnvFile.load(self.env_path)
        if self.managed_by in _NODE_MANAGED:
            # Daemon env from the platform (StartOS bridges, Umbrel compose)
            # is process env, not .env — promote it into runtime_values without
            # overriding a value the user set in their own .env.
            for key in (
                "BITCOIND_HOST",
                "ELECTRS_HOST",
                "NODE_IP",
                "RPCHOST",
                "BITCOIN_RPC_HOST",
                "RPCPORT",
                "RPCUSER",
                "RPCPASSWORD",
                "RPC_SSL",
                "RPC_COOKIE_FILE",
                "FULCRUM_HOST",
                "FULCRUM_PORT",
                "FULCRUM_SSL",
                "SATSAGE_ELECTRUM_INDEXER",
                "MEMPOOL_URL",
                "LLM_BASE_URL",
                "LLM_ANBIETER",
                "LLM_MODELL",
            ):
                proc = (os.environ.get(key) or "").strip()
                if proc and key not in env.values():
                    env.runtime_values[key] = proc
            values = env.values()
            # Prefer explicit FULCRUM_* from the platform (StartOS daemon or the
            # Umbrel electrs dependency). Only fall back to ELECTRS_HOST when
            # FULCRUM_HOST is empty.
            if not (values.get("FULCRUM_HOST") or "").strip():
                bridge = (values.get("ELECTRS_HOST") or "electrs").strip()
                if bridge:
                    env.runtime_values["FULCRUM_HOST"] = bridge
            if not (values.get("NODE_IP") or values.get("RPCHOST") or "").strip():
                bridge = (values.get("BITCOIND_HOST") or "bitcoind").strip()
                if bridge:
                    env.runtime_values["NODE_IP"] = bridge
            # StartOS mounts bitcoind's cookie read-only, Umbrel passes RPC
            # credentials as compose env. Keep them runtime-only; never write
            # them into the user's .env file.
            cookie_user, cookie_password = rpc_credentials_from_env(values)
            if cookie_user and not (values.get("RPCUSER") or "").strip():
                env.runtime_values["RPCUSER"] = cookie_user
            if cookie_password and not (values.get("RPCPASSWORD") or "").strip():
                env.runtime_values["RPCPASSWORD"] = cookie_password
        elif self.managed_by not in _MANAGED_MODI:
            # Desktop: lokaler bitcoind → UTXO-Slot (still); Lookup nur wenn leer.
            _apply_local_core_runtime(env)
        return env

    def reload(self) -> None:
        """Liest die .env neu und baut den WalletContext auf."""
        with self._lock:
            env = self.env()
            main.set_chain_network(env.values().get("NETWORK"))
            self._entries = read_wallets(env)
            self._wallet_ctx = self._build_context(self._entries)
            # UTXO-/Resolution-Cache → Mapping: sonst resolve_address je
            # ungeseedeter Adresse MAX_TRACE_ADDRESS_SEARCH Ableitungen
            # (Herkunftsliste mit 30+ UTXOs: Sekunden).
            if self._wallet_ctx is not None:
                schluessel = [
                    e.analyse_schluessel for e in self._entries if e.is_valid()
                ]
                try:
                    main.seed_wallet_addresses_from_utxo_cache(
                        self._wallet_ctx, schluessel, self.cache_dir,
                    )
                except Exception:
                    pass
                try:
                    main.seed_wallet_addresses_from_resolution_cache(
                        self._wallet_ctx, schluessel,
                    )
                except Exception:
                    pass
            # Empfangs-QR neu ableiten (Indizes/Adressen können sich geändert haben).
            self.empfang_cache.clear()
            with getattr(self, "_empfang_fulcrum_lock", threading.Lock()):
                alt = getattr(self, "_empfang_fulcrum", None)
                alt_pub = getattr(self, "_empfang_public_fulcrum", None)
                self._empfang_fulcrum = None
                self._empfang_public_fulcrum = None
            for client in (alt, alt_pub):
                if client is None:
                    continue
                try:
                    client.close()
                except Exception:
                    pass

    @staticmethod
    def _build_context(entries: list[WalletEntry]):
        # Single-Sig wie Multisig. Der Stack führt seine Wallets über einen
        # Zeichenketten-Schlüssel: bei Single-Sig der XPUB, bei Multisig der
        # Deskriptor. Aus beiden lassen sich Adressen ableiten — mehr braucht
        # er nicht zu wissen. Die *einzelnen* Cosigner dürfen dagegen nie
        # hinein, sonst gälten sie als eigene, leere Wallets.
        gueltig = [e for e in entries if e.is_valid()]
        if not gueltig:
            return None
        return main.build_wallet_context(
            [e.analyse_schluessel for e in gueltig],
            wallet_names=[e.display_name for e in gueltig],
            max_addresses_per_xpub=[e.max_addresses for e in gueltig],
            script_types=[e.script_type for e in gueltig],
        )

    @property
    def entries(self) -> list[WalletEntry]:
        with self._lock:
            return list(self._entries)

    @property
    def analyse_entries(self) -> list[WalletEntry]:
        """
        Die Wallets, für die sich Adressen ableiten lassen.
        Ausgeschlossen bleibt nur, was der Deskriptor-Parser nicht lesen kann
        (etwa aggregierte Taproot-Schlüssel) — dort gäbe es keine Adressen,
        und ein Eintrag ohne Adressen sähe im Bestand aus wie ein leeres
        Wallet.
        """
        return [e for e in self.entries if e.is_valid()]

    @property
    def unlesbare_entries(self) -> list[WalletEntry]:
        """Konfiguriert, aber nicht ableitbar — muss gesagt werden."""
        return [e for e in self.entries if not e.is_valid()]

    @property
    def multisig_entries(self) -> list[WalletEntry]:
        return [e for e in self.entries if e.is_multisig]

    @property
    def wallet_ctx(self):
        with self._lock:
            return self._wallet_ctx

    # -- Datenquelle --------------------------------------------------------

    def args_namespace(self) -> SimpleNamespace:
        """
        Baut das argparse-ähnliche Objekt, das die bestehenden Funktionen in
        main erwarten. So bleiben deren Signaturen unverändert.
        """
        entries = self.analyse_entries
        return SimpleNamespace(
            xpubs=[e.analyse_schluessel for e in entries],
            wallet_names=[e.display_name for e in entries],
            script_types=[e.script_type for e in entries],
            max_addresses_per_xpub=[e.max_addresses for e in entries],
            max_addresses=main.DEFAULT_MAX_ADDRESSES,
            cache_dir=str(self.cache_dir),
            immutable_cache_dir=str(self.immutable_cache_dir),
            rpc_only=False,
            bip158=False,
            bip158_start=None,
            rescan=False,
            no_verbose=True,
            cli=False,
            txid=None,
            address=None,
            utxo=None,
            top_utxos=10,
            rpchost=None,
            rpcport=None,
            rpcuser=None,
            rpcpass=None,
            fulcrum_host=None,
            fulcrum_port=None,
            fulcrum_no_ssl=(
                str(self.env().values().get("FULCRUM_SSL", "true")).strip().lower()
                in ("0", "false", "no", "off")
            ),
            oeffentliche_electrum=source_mod.oeffentliche_electrum_session_aktiv(),
        )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _eigene_adressen(state: AppState) -> set | None:
    """
    Die derzeit bekannten eigenen Adressen — Grundlage jeder Intern/Extern-
    Unterscheidung. None, solange kein gültiges Wallet konfiguriert ist; dann
    lässt sich über gespeicherte Bäume weder „aktuell" noch „veraltet" sagen.
    """
    ctx = state.wallet_ctx
    return set(ctx.address_to_wallet) if ctx else None


def _ordner_leeren(pfad: Path, *, behalten: tuple[str, ...] = ()) -> int:
    """Löscht den Inhalt, behält den Ordner. Rückgabe: entfernte Einträge."""
    if not pfad.is_dir():
        return 0
    anzahl = 0
    for kind in list(pfad.iterdir()):
        # Wallet-Alter bleibt: die älteste Transaktion ändert sich nicht.
        if kind.is_file() and kind.name.endswith("_alter.json"):
            continue
        if kind.name in behalten:
            continue
        if kind.is_dir():
            shutil.rmtree(kind)
        else:
            kind.unlink()
        anzahl += 1
    return anzahl


def _header_pfad(state: AppState) -> Path:
    from core.p2p import p2p_headers_path

    return p2p_headers_path(state.immutable_cache_dir)


def _header_tip(state: AppState) -> int | None:
    from core.p2p import header_datei_tip

    return header_datei_tip(_header_pfad(state))


def _datei_loeschen(pfad: Path | None) -> int:
    if pfad is None or not pfad.is_file():
        return 0
    pfad.unlink()
    return 1


def _datei_groesse(pfad: Path | None) -> int:
    if pfad is None or not pfad.is_file():
        return 0
    try:
        return int(pfad.stat().st_size)
    except OSError:
        return 0


def _format_de_zahl(wert: float, *, max_nk: int = 2) -> str:
    """
    Deutsche Zahl: Punkt als Tausendertrenner, Komma als Dezimal.
    Höchstens *max_nk* Nachkommastellen, trailing zeros weg.
    """
    if max_nk < 0:
        max_nk = 0
    gerundet = round(float(wert), max_nk)
    if max_nk == 0:
        ganz = int(gerundet)
        return f"{ganz:,}".replace(",", ".")
    # Feste NK, dann Nullen am Ende streichen (1,50 → 1,5; 1,00 → 1).
    roh = f"{gerundet:.{max_nk}f}"
    if "." in roh:
        ganz_s, nk_s = roh.split(".", 1)
        nk_s = nk_s.rstrip("0")
    else:
        ganz_s, nk_s = roh, ""
    try:
        ganz_fmt = f"{int(ganz_s):,}".replace(",", ".")
    except ValueError:
        ganz_fmt = ganz_s
    if nk_s:
        return f"{ganz_fmt},{nk_s}"
    return ganz_fmt


def format_dateigroesse(bytes_anzahl: int) -> str:
    """
    Lesbare Cache-/Dateigröße.

    Ab 1000 MB → GB (max. 2 Nachkommastellen). Darunter MB/KB/B wie bisher
    (MB mit 1 NK). Tausendertrenner bei großen Zahlen.
    """
    n = int(bytes_anzahl or 0)
    if n <= 0:
        return "0 MB"
    mb = n / (1024 * 1024)
    if mb >= 1000:
        gb = n / (1024 * 1024 * 1024)
        return f"{_format_de_zahl(gb, max_nk=2)} GB"
    if mb >= 0.1:
        return f"{_format_de_zahl(mb, max_nk=1)} MB"
    if n >= 1024:
        kb = n / 1024
        return (
            f"{_format_de_zahl(kb, max_nk=1)} KB "
            f"({_format_de_zahl(mb, max_nk=3)} MB)"
        )
    return f"{n} B ({_format_de_zahl(mb, max_nk=3)} MB)"


def _cache_utxo_schluessel(eintrag: dict) -> tuple[str, int] | None:
    txid = eintrag.get("txid")
    if not txid:
        return None
    try:
        return str(txid), int(eintrag.get("vout", 0))
    except (TypeError, ValueError):
        return None


def _wallet_cache_pfade(
    state: AppState,
    entry,
    *,
    mit_alter: bool = False,
) -> list[Path]:
    """
    Dateien, die zum Analyse-Cache dieses Wallets gehören.

    *mit_alter*: Altersdatei mitnehmen — bei Wallet-Entfernung ja (sonst
    bleibt sie verwaist), beim normalen Cache-Löschen nein (First-seen bleibt).
    """
    schluessel = entry.analyse_schluessel
    pfade: list[Path] = []
    for pfad in (
        main._xpub_cache_path(schluessel, state.cache_dir),
        main._xpub_verlauf_cache_path(schluessel, state.cache_dir),
    ):
        if pfad.is_file():
            pfade.append(pfad)
    if mit_alter:
        alter = main._xpub_alter_path(schluessel, state.cache_dir)
        if alter.is_file():
            pfade.append(alter)

    utxos = utxos_mod.load_cached_utxos(schluessel, state.cache_dir) or []
    verlauf = main.load_xpub_verlauf_cache(schluessel, state.cache_dir) or []
    gesehen: set[tuple[str, int]] = set()
    for eintrag in list(utxos) + list(verlauf):
        paar = _cache_utxo_schluessel(eintrag)
        if paar is None or paar in gesehen:
            continue
        gesehen.add(paar)
        txid, vout = paar
        for pfad in (
            main._utxo_ingress_cache_path(txid, vout, state.immutable_cache_dir),
            trace_cache.pfad(txid, vout, state.immutable_cache_dir),
        ):
            if pfad is not None and pfad.is_file():
                pfade.append(pfad)
    return pfade


def _wallet_cache_umfang(
    state: AppState,
    entry,
    *,
    mit_alter: bool = False,
) -> dict:
    pfade = _wallet_cache_pfade(state, entry, mit_alter=mit_alter)
    bytes_anzahl = sum(_datei_groesse(p) for p in pfade)
    return {
        "wallet_id": wallets_mod.eintrag_id(entry),
        "wallet_name": entry.display_name,
        "dateien": len(pfade),
        "bytes": bytes_anzahl,
        "groesse_label": format_dateigroesse(bytes_anzahl),
    }


def _wallet_cache_loeschen(
    state: AppState,
    entry,
    *,
    mit_alter: bool = False,
    on_log=None,
) -> dict:
    """Löscht den Analyse-Cache eines Wallets. Siehe ``_wallet_cache_pfade``."""
    name = entry.display_name or wallets_mod.eintrag_id(entry)

    def _log(text: str) -> None:
        if on_log:
            try:
                on_log(text)
            except Exception:
                pass

    _log(f"Lösche {name}")
    # Teuer bei Import-Wallets: UTXO+Verlauf laden, je Tx Ingress/Trace-Pfad.
    pfade = _wallet_cache_pfade(state, entry, mit_alter=mit_alter)
    bytes_anzahl = sum(_datei_groesse(p) for p in pfade)
    utxo_n = 0
    verlauf_n = 0
    herkunft_n = 0
    alter_n = 0
    n_pfade = len(pfade)
    for i, pfad in enumerate(pfade, start=1):
        if pfad.parent == state.cache_dir:
            if pfad.name.endswith("_verlauf.json"):
                verlauf_n += _datei_loeschen(pfad)
            elif pfad.name.endswith("_alter.json"):
                alter_n += _datei_loeschen(pfad)
            else:
                utxo_n += _datei_loeschen(pfad)
        else:
            herkunft_n += _datei_loeschen(pfad)
        # Fortschritt nur bei vielen Herkunftsdateien (sonst Rauschen).
        if n_pfade >= 50 and (i == 1 or i == n_pfade or i % 100 == 0):
            _log(f"Lösche {name}: Datei {i}/{n_pfade}…")
    _log("Löschen beendet")
    return {
        "wallet_id": wallets_mod.eintrag_id(entry),
        "wallet_name": entry.display_name,
        "dateien": utxo_n + verlauf_n + herkunft_n + alter_n,
        "bytes": bytes_anzahl,
        "groesse_label": format_dateigroesse(bytes_anzahl),
        "utxo_eintraege": utxo_n,
        "verlauf_eintraege": verlauf_n,
        "herkunft_eintraege": herkunft_n,
        "alter_eintraege": alter_n,
    }


def api_cache_leeren(state: AppState) -> dict:
    """
    Löscht den Analyse-Cache: UTXOs, Verlauf, Herkunftsbäume, Tx- und
    Block-Dateien. Sanktionslisten und Adress-Labels bleiben — die haben
    eigene Knöpfe.
    """
    utxo = _ordner_leeren(state.cache_dir)
    unveraenderlich = _ordner_leeren(
        state.immutable_cache_dir,
        behalten=("p2p_headers.bin", "p2p_headers.bin.tmp"),
    )
    return {
        "ok": True,
        "utxo_eintraege": utxo,
        "immutable_eintraege": unveraenderlich,
    }


def _cache_kennung_hat_dateien(state: AppState, kennung: str) -> bool:
    base = state.cache_dir
    if not base.is_dir():
        return False
    for name in (
        f"{kennung}.json",
        f"{kennung}_verlauf.json",
        f"{kennung}_alter.json",
    ):
        if (base / name).is_file():
            return True
    return False


def _wallet_cache_pfade_kennung(
    state: AppState,
    kennung: str,
    *,
    mit_alter: bool = False,
) -> list[Path]:
    """Cache-Dateien zu einer 16-hex-Kennung (auch ohne WalletEntry)."""
    kid = (kennung or "").strip().lower()
    pfade: list[Path] = []
    base = state.cache_dir
    for name in (f"{kid}.json", f"{kid}_verlauf.json"):
        p = base / name
        if p.is_file():
            pfade.append(p)
    if mit_alter:
        alter = base / f"{kid}_alter.json"
        if alter.is_file():
            pfade.append(alter)

    orphan_refs: set[tuple[str, int]] = set()
    for p in list(pfade):
        orphan_refs |= _utxo_refs_aus_datei(p)
    noch_aktiv = _aktive_utxo_refs(state)
    for txid, vout in orphan_refs - noch_aktiv:
        for pfad in (
            main._utxo_ingress_cache_path(txid, vout, state.immutable_cache_dir),
            trace_cache.pfad(txid, vout, state.immutable_cache_dir),
        ):
            if pfad is not None and pfad.is_file():
                pfade.append(pfad)
    return pfade


def _wallet_cache_loeschen_kennung(
    state: AppState,
    kennung: str,
    *,
    name: str = "",
    mit_alter: bool = False,
    on_log=None,
) -> dict:
    anzeige = name or f"Cache {kennung[:8]}…"

    def _log(text: str) -> None:
        if on_log:
            try:
                on_log(text)
            except Exception:
                pass

    _log(f"Lösche {anzeige}")
    pfade = _wallet_cache_pfade_kennung(state, kennung, mit_alter=mit_alter)
    bytes_anzahl = sum(_datei_groesse(p) for p in pfade)
    utxo_n = 0
    verlauf_n = 0
    herkunft_n = 0
    alter_n = 0
    n_pfade = len(pfade)
    for i, pfad in enumerate(pfade, start=1):
        if pfad.parent == state.cache_dir:
            if pfad.name.endswith("_verlauf.json"):
                verlauf_n += _datei_loeschen(pfad)
            elif pfad.name.endswith("_alter.json"):
                alter_n += _datei_loeschen(pfad)
            else:
                utxo_n += _datei_loeschen(pfad)
        else:
            herkunft_n += _datei_loeschen(pfad)
        if n_pfade >= 50 and (i == 1 or i == n_pfade or i % 100 == 0):
            _log(f"Lösche {anzeige}: Datei {i}/{n_pfade}…")
    _log("Löschen beendet")
    return {
        "wallet_id": kennung,
        "wallet_name": anzeige,
        "dateien": utxo_n + verlauf_n + herkunft_n + alter_n,
        "bytes": bytes_anzahl,
        "groesse_label": format_dateigroesse(bytes_anzahl),
        "utxo_eintraege": utxo_n,
        "verlauf_eintraege": verlauf_n,
        "herkunft_eintraege": herkunft_n,
        "alter_eintraege": alter_n,
    }


#: utxo_cache/{16 hex}.json | _verlauf.json | _alter.json
_CACHE_DATEI_KENNUNG = re.compile(
    r"^([0-9a-f]{16})(?:_verlauf|_alter)?\.json$",
    re.IGNORECASE,
)


def _cache_datei_kennung(name: str) -> str | None:
    treffer = _CACHE_DATEI_KENNUNG.match(name or "")
    return treffer.group(1).lower() if treffer else None


def _aktive_cache_kennungen(state: AppState) -> set[str]:
    return {
        main._xpub_cache_key(entry.analyse_schluessel)
        for entry in state.entries
    }


def _utxo_refs_aus_datei(pfad: Path) -> set[tuple[str, int]]:
    """txid:vout aus einer UTXO- oder Verlaufs-JSON."""
    if not pfad.is_file():
        return set()
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return set()
    refs: set[tuple[str, int]] = set()
    if isinstance(roh, dict):
        eintraege = (
            roh.get("utxos")
            or roh.get("eintraege")
            or roh.get("entries")
            or []
        )
    elif isinstance(roh, list):
        eintraege = roh
    else:
        eintraege = []
    for eintrag in eintraege:
        if not isinstance(eintrag, dict):
            continue
        paar = _cache_utxo_schluessel(eintrag)
        if paar is not None:
            refs.add(paar)
    return refs


def _aktive_utxo_refs(state: AppState) -> set[tuple[str, int]]:
    refs: set[tuple[str, int]] = set()
    for entry in state.entries:
        schluessel = entry.analyse_schluessel
        for liste in (
            utxos_mod.load_cached_utxos(schluessel, state.cache_dir) or [],
            main.load_xpub_verlauf_cache(schluessel, state.cache_dir) or [],
        ):
            for eintrag in liste:
                paar = _cache_utxo_schluessel(eintrag)
                if paar is not None:
                    refs.add(paar)
    return refs


def _unreferenzierte_cache_pfade(state: AppState) -> list[Path]:
    """
    Cache-Dateien ohne passendes Wallet in der .env.

    UTXO/Verlauf/Alter verwaisten Kennungen; Herkunft nur, wenn kein
    verbleibendes Wallet denselben Output noch referenziert.
    """
    aktiv = _aktive_cache_kennungen(state)
    cache_dir = state.cache_dir
    if not cache_dir.is_dir():
        return []

    pfade: list[Path] = []
    orphan_refs: set[tuple[str, int]] = set()
    for kind in cache_dir.iterdir():
        if not kind.is_file():
            continue
        kennung = _cache_datei_kennung(kind.name)
        if kennung is None or kennung in aktiv:
            continue
        pfade.append(kind)
        name = kind.name.lower()
        if name == f"{kennung}.json" or name.endswith("_verlauf.json"):
            orphan_refs |= _utxo_refs_aus_datei(kind)

    if orphan_refs:
        noch_aktiv = _aktive_utxo_refs(state)
        for txid, vout in orphan_refs - noch_aktiv:
            for pfad in (
                main._utxo_ingress_cache_path(
                    txid, vout, state.immutable_cache_dir
                ),
                trace_cache.pfad(txid, vout, state.immutable_cache_dir),
            ):
                if pfad is not None and pfad.is_file():
                    pfade.append(pfad)
    return pfade


def _unreferenzierter_cache_bericht(state: AppState) -> dict:
    pfade = _unreferenzierte_cache_pfade(state)
    bytes_anzahl = sum(_datei_groesse(p) for p in pfade)
    kennungen: dict[str, int] = {}
    for pfad in pfade:
        if pfad.parent == state.cache_dir:
            k = _cache_datei_kennung(pfad.name)
            if k:
                kennungen[k] = kennungen.get(k, 0) + 1
    return {
        "vorhanden": len(pfade) > 0,
        "dateien": len(pfade),
        "kennungen": len(kennungen),
        "bytes": bytes_anzahl,
        "groesse_mb": round(bytes_anzahl / (1024 * 1024), 3),
        "groesse_label": format_dateigroesse(bytes_anzahl),
    }


def api_cache_unreferenziert(state: AppState) -> dict:
    """Stand der verwaisten Cache-Dateien (ohne Wallet in der .env)."""
    return _unreferenzierter_cache_bericht(state)


def api_cache_unreferenziert_loeschen(state: AppState) -> dict:
    """
    Löscht verwaiste Cache-Dateien. Kein Danger: ohne Wallet greift die
    Oberfläche sie ohnehin nicht mehr an.
    """
    pfade = _unreferenzierte_cache_pfade(state)
    bytes_anzahl = sum(_datei_groesse(p) for p in pfade)
    geloescht = 0
    for pfad in pfade:
        geloescht += _datei_loeschen(pfad)
    return {
        "ok": True,
        "dateien": geloescht,
        "bytes": bytes_anzahl,
        "groesse_mb": round(bytes_anzahl / (1024 * 1024), 3),
        "groesse_label": format_dateigroesse(bytes_anzahl),
    }


def _cache_baum_stats(pfad: Path) -> dict:
    """Dateien und Bytes unter *pfad* (rekursiv). Fehlender Ordner → 0."""
    dateien = 0
    bytes_anzahl = 0
    if not pfad.is_dir():
        return {
            "dateien": 0,
            "bytes": 0,
            "groesse_label": format_dateigroesse(0),
        }
    for wurzel, _dirs, namen in os.walk(pfad):
        for name in namen:
            kind = Path(wurzel) / name
            try:
                bytes_anzahl += int(kind.stat().st_size)
            except OSError:
                continue
            dateien += 1
    return {
        "dateien": dateien,
        "bytes": bytes_anzahl,
        "groesse_label": format_dateigroesse(bytes_anzahl),
    }


def _cache_datei_stats(pfad: Path) -> dict:
    groesse = _datei_groesse(pfad)
    return {
        "vorhanden": pfad.is_file(),
        "bytes": groesse,
        "groesse_label": format_dateigroesse(groesse),
    }


def _platte_cache_stats(cache_dir: Path) -> dict:
    """Belegung der Platte, auf der die Caches liegen (kein Zugriffszähler)."""
    try:
        ziel = main._cache_disk_target(cache_dir)
        usage = shutil.disk_usage(ziel)
    except OSError:
        return {
            "free_bytes": None,
            "total_bytes": None,
            "free_ratio": None,
            "free_label": "—",
            "total_label": "—",
            "write_blocked": bool(main.is_cache_disk_write_blocked()),
            "ampel": "warn",
        }
    free = int(usage.free)
    total = int(usage.total)
    ratio = (free / total) if total > 0 else 0.0
    blocked = free < main.MIN_FREE_DISK_BYTES and ratio < main.MIN_FREE_DISK_RATIO
    if blocked or main.is_cache_disk_write_blocked():
        ampel = "krit"
    elif free < 2 * main.MIN_FREE_DISK_BYTES or ratio < 0.10:
        ampel = "warn"
    else:
        ampel = "gut"
    return {
        "free_bytes": free,
        "total_bytes": total,
        "free_ratio": round(ratio, 4),
        "free_label": format_dateigroesse(free),
        "total_label": format_dateigroesse(total),
        "write_blocked": bool(blocked or main.is_cache_disk_write_blocked()),
        "ampel": ampel,
        "schwelle_ratio": main.MIN_FREE_DISK_RATIO,
        "schwelle_bytes": main.MIN_FREE_DISK_BYTES,
    }


def _wallet_cache_belegung(state: AppState, entry) -> dict:
    """Belegung eines Wallets: Dateigrößen und Abdeckung, keine Hits."""
    schluessel = entry.analyse_schluessel
    zusammen = wallets_mod.summarize([entry], state.cache_dir)[0]
    utxo_pfad = main._xpub_cache_path(schluessel, state.cache_dir)
    verlauf_pfad = main._xpub_verlauf_cache_path(schluessel, state.cache_dir)
    alter_pfad = main._xpub_alter_path(schluessel, state.cache_dir)
    verlauf = main.load_xpub_verlauf_cache(schluessel, state.cache_dir) or []
    utxos = utxos_mod.load_cached_utxos(schluessel, state.cache_dir) or []

    gesehen: set[tuple[str, int]] = set()
    herkunft_treffer = 0
    herkunft_bytes = 0
    for eintrag in list(utxos) + list(verlauf):
        paar = _cache_utxo_schluessel(eintrag)
        if paar is None or paar in gesehen:
            continue
        gesehen.add(paar)
        txid, vout = paar
        try:
            ingress = main._utxo_ingress_cache_path(
                txid, vout, state.immutable_cache_dir
            )
        except (TypeError, ValueError):
            continue
        if ingress.is_file():
            herkunft_treffer += 1
            herkunft_bytes += _datei_groesse(ingress)

    referenzen = len(gesehen)
    tip = _header_tip(state)
    scan_tip = zusammen.scan_tip_height
    tip_lag = None
    if tip is not None and scan_tip is not None:
        tip_lag = max(0, int(tip) - int(scan_tip))

    max_addr = int(entry.max_addresses or 0)
    scan_end = zusammen.scan_end_index
    gap_ratio = None
    if max_addr > 0 and scan_end is not None:
        try:
            gap_ratio = min(1.0, max(0.0, int(scan_end) / float(max_addr)))
        except (TypeError, ValueError):
            gap_ratio = None

    utxo_bytes = _datei_groesse(utxo_pfad)
    verlauf_bytes = _datei_groesse(verlauf_pfad)
    alter_bytes = _datei_groesse(alter_pfad)
    eigen_bytes = utxo_bytes + verlauf_bytes + alter_bytes + herkunft_bytes

    return {
        "wallet_id": wallets_mod.eintrag_id(entry),
        "wallet_name": entry.display_name,
        "has_cache": zusammen.has_cache,
        "utxo_count": zusammen.utxo_count,
        "total_sats": zusammen.total_sats,
        "utxo_bytes": utxo_bytes,
        "verlauf_count": len(verlauf),
        "verlauf_bytes": verlauf_bytes,
        "alter_vorhanden": alter_pfad.is_file(),
        "alter_bytes": alter_bytes,
        "first_seen_height": zusammen.first_seen_height,
        "first_seen_ts": zusammen.first_seen_ts,
        "scan_end_index": scan_end,
        "max_addresses": max_addr,
        "gap_ratio": gap_ratio,
        "scan_tip_height": scan_tip,
        "header_tip": tip,
        "tip_lag": tip_lag,
        "herkunft_referenzen": referenzen,
        "herkunft_treffer": herkunft_treffer,
        "herkunft_bytes": herkunft_bytes,
        "herkunft_ratio": (
            round(herkunft_treffer / referenzen, 4) if referenzen else None
        ),
        "bytes": eigen_bytes,
        "groesse_label": format_dateigroesse(eigen_bytes),
    }


def api_cache_stats(state: AppState) -> dict:
    """
    Cache-Belegung fürs Dashboard (Größe/Abdeckung, keine Zugriffe).

    Pro Wallet und Summe; Schwellen für Platte und Flatfile-Warnung.
    """
    utxo = _cache_baum_stats(state.cache_dir)
    immutable = _cache_baum_stats(state.immutable_cache_dir)
    tx = _cache_baum_stats(state.immutable_cache_dir / main.TX_IMMUTABLE_CACHE_SUBDIR)
    ingress = _cache_baum_stats(
        state.immutable_cache_dir / main.UTXO_INGRESS_CACHE_SUBDIR
    )
    block_header = _cache_baum_stats(
        state.immutable_cache_dir / main.BLOCK_HEADER_CACHE_SUBDIR
    )
    headers = _cache_datei_stats(_header_pfad(state))
    price = _cache_baum_stats(state.immutable_cache_dir / "btc_price")
    external = _cache_datei_stats(state.cache_dir / "external_addresses.json")
    sanktionen_dir = state.sanctions_dir
    if sanktionen_dir is None:
        sanktionen_dir = state.cache_dir.parent / "sanctioned_cache"
    sanktionen = _cache_baum_stats(sanktionen_dir)

    schwelle = int(main._SQLITE_FLATFILE_HINT_THRESHOLD)
    tx_n = int(tx["dateien"])
    ingress_n = int(ingress["dateien"])
    if tx_n >= schwelle or ingress_n >= schwelle:
        flat_ampel = "krit"
    elif tx_n >= max(1000, schwelle // 5) or ingress_n >= max(1000, schwelle // 5):
        flat_ampel = "warn"
    else:
        flat_ampel = "gut"

    wallets = [_wallet_cache_belegung(state, e) for e in state.entries]
    summe = (
        int(utxo["bytes"])
        + int(immutable["bytes"])
        + int(sanktionen["bytes"])
    )
    platte = _platte_cache_stats(state.cache_dir)
    return {
        "ok": True,
        "platte": platte,
        "summe_bytes": summe,
        "summe_label": format_dateigroesse(summe),
        "utxo_cache": utxo,
        "immutable_cache": immutable,
        "tx": {**tx, "schwelle": schwelle, "ampel": flat_ampel},
        "utxo_ingress": {**ingress, "schwelle": schwelle, "ampel": flat_ampel},
        "block_header": block_header,
        "p2p_headers": {**headers, "tip": _header_tip(state)},
        "btc_price": price,
        "external_addresses": external,
        "sanctioned_cache": sanktionen,
        "wallets": wallets,
    }


def _wallets_config_gesperrt(state: AppState) -> None:
    """Verhindert lokale Wallet-Änderungen im Specter-Modus."""
    if state.managed_by == "specter":
        raise ApiError(403, "Wallets werden von Specter verwaltet und können hier nicht geändert werden.")


_BRIDGE_QUELLEN = frozenset(("own_fulcrum", "own_core"))
_BRIDGE_SCHLUESSEL = frozenset((
    "FULCRUM_HOST", "FULCRUM_TOR", "FULCRUM_PORT", "FULCRUM_SSL",
    "FULCRUM_TOR_PORT", "FULCRUM_TOR_SSL",
    "NODE_IP", "RPCHOST", "BITCOIN_RPC_HOST", "RPCPORT", "RPCUSER",
    "RPCPASSWORD", "RPC_SSL", "RPC_COOKIE_FILE", "BITCOIN_RPC_COOKIE",
))


def _electrum_indexer(werte: dict | None) -> str:
    """``electrs`` oder ``fulcrum`` aus Plattform-Env.

    StartOS setzt den Wert über die Action „Select Indexer“, Umbrel über die
    gewählte ``electrs``-Dependency. Ohne Angabe bleibt es bei ``electrs``.
    """
    roh = str((werte or {}).get("SATSAGE_ELECTRUM_INDEXER") or "").strip().lower()
    if roh in ("fulcrum", "electrs"):
        return roh
    # Legacy: nur ELECTRS_HOST / FULCRUM_HOST ohne Indexer-Flag → electrs-Default.
    return "electrs"


def _specter_labels_for_api(state: AppState) -> dict[str, str]:
    """Nutzer-Labels aus Specter-Seed (``utxo_cache/specter_address_labels.json``)."""
    path = Path(state.cache_dir) / "specter_address_labels.json"
    if not path.is_file():
        return {}
    try:
        roh = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(roh, dict):
        return {}
    return {str(k): str(v) for k, v in roh.items() if k and v}


_local_core_probe_cache: tuple[float, object | None] | None = None
_local_core_hint_logged = False


_local_core_runtime_logged = False


def _apply_local_core_runtime(env) -> None:
    """Lokalen Qt still in den UTXO-Slot legen; Lookup-Core (Start9) nicht anfassen.

    Nur Desktop (Aufrufer schließt Specter/Start9 aus).

    - Immer: leere ``UTXO_RPC_*`` + ``BIP158_HOST`` aus Discovery.
    - Nur wenn kein Lookup-Core: zusätzlich ``NODE_IP``/``RPC*`` (leere Keys).
    - ``BIP158_P2P`` wird nicht erzwungen.
    - **Persistenz in die .env**, damit Scan-Jobs (``main._load_dotenv``) den
      UTXO-Slot sehen — Runtime allein reicht nicht.
    """
    global _local_core_runtime_logged
    from core import local_bitcoind as local_core

    values = env.values()
    hit = _discover_local_core_cached(values)
    if hit is None:
        return
    already = local_core.core_already_configured(values)
    updates = local_core.env_updates_from_hit(hit, lookup_core_already=already)
    schreiben: dict[str, str] = {}
    for key, val in updates.items():
        if key == "BIP158_P2P":
            continue
        if key == "LOCAL_CORE_OPT_IN":
            # Merker setzen, auch wenn schon andere Keys da sind.
            if (values.get(key) or "").strip():
                continue
            schreiben[key] = val
            continue
        if (values.get(key) or "").strip():
            continue
        schreiben[key] = val
    if not schreiben:
        return
    env.apply(schreiben)
    try:
        env.save(backup=True)
    except OSError as exc:
        print(f"Lokaler Bitcoin Core: .env nicht speicherbar — {exc}", flush=True)
        # Fallback: wenigstens Runtime für API/Config.
        for key, val in schreiben.items():
            env.runtime_values[key] = val
        return
    if not _local_core_runtime_logged:
        _local_core_runtime_logged = True
        basis = (
            f"{hit.host}:{hit.port} ({hit.chain}, "
            f"{'pruned' if hit.pruned else 'vollständig'}, ~{hit.blocks} Blöcke)"
        )
        if already:
            print(
                f"Lokaler Bitcoin Core → UTXO-Set-Slot in .env (+ Prefer-Peer): "
                f"{basis}. Lookup-NODE_IP unverändert. "
                f"Nächster UTXO-Scan nutzt scantxoutset lokal.",
                flush=True,
            )
        else:
            print(
                f"Lokaler Bitcoin Core → UTXO-Set- und Lookup-Slot in .env "
                f"(+ Prefer-Peer): {basis}.",
                flush=True,
            )


def _discover_local_core_cached(werte: dict | None = None):
    """Kurzes Cache-TTL, damit api_config nicht bei jedem Poll neu scannt."""
    global _local_core_probe_cache
    import time

    from core import local_bitcoind as local_core

    now = time.monotonic()
    if _local_core_probe_cache is not None:
        ts, hit = _local_core_probe_cache
        if now - ts < 30.0:
            return hit
    preferred = None
    if werte:
        preferred = (werte.get("NETWORK") or "").strip() or None
    hit = local_core.discover_local_bitcoind(preferred_network=preferred)
    _local_core_probe_cache = (now, hit)
    return hit


def _local_core_status_for_api(state: AppState) -> dict | None:
    """Erkennung für die Datenquellen-UI — ohne Secrets, ohne Managed-Modi."""
    if state.managed_by in _MANAGED_MODI:
        return None
    from core import local_bitcoind as local_core

    werte = state.env().values()
    configured = local_core.core_already_configured(werte)
    opt_in = local_core.local_core_opt_in_enabled(werte)
    hit = _discover_local_core_cached(werte)
    if hit is None and not configured:
        return {
            "detected": False,
            "configured": configured,
            "opt_in": opt_in,
        }
    utxo_slot = local_core.utxo_rpc_dedicated(werte)
    out: dict = {
        "detected": hit is not None,
        "configured": configured,
        "opt_in": opt_in,
        "utxo_slot": utxo_slot,
        # Persistenz-Hinweis: Runtime-Fill reicht; Banner nur wenn nichts greift.
        "needs_opt_in": bool(
            hit is not None and not utxo_slot and not configured and not opt_in
        ),
    }
    if hit is not None:
        out["hit"] = hit.as_public_dict()
    return out


def _log_local_core_hint_once(state: AppState) -> None:
    global _local_core_hint_logged
    if _local_core_hint_logged:
        return
    status = _local_core_status_for_api(state)
    if not status or not status.get("needs_opt_in"):
        return
    _local_core_hint_logged = True
    hit = status.get("hit") or {}
    pruned = "pruned" if hit.get("pruned") else "vollständig"
    p2p = hit.get("p2p_port") or 8333
    print(
        f"Lokaler Bitcoin Core erkannt ({hit.get('host')}:{hit.get('port')}, "
        f"{hit.get('chain')}, {pruned}, ~{hit.get('blocks')} Blöcke). "
        f"UTXO-Set-Slot wird still genutzt; Prefer-Peer "
        f"BIP158_HOST={hit.get('host')}:{p2p} "
        f"(P2P-Schalter unverändert). Lookup-NODE_IP bleibt, falls gesetzt.",
        flush=True,
    )


def _managed_hint(state: AppState, werte: dict | None) -> str | None:
    if state.managed_by == "specter":
        return (
            "Wallets (XPUBs/Deskriptoren) und Node/Electrum kommen aus Specter — "
            "hier nicht doppelt pflegen. UTXOs, Verlauf und Labels werden aus "
            "Specters Cache gesedet; Herkunft läuft weiter über SatSage."
        )
    if state.managed_by == "start9":
        indexer = _electrum_indexer(werte)
        label = "Fulcrum" if indexer == "fulcrum" else "Electrs"
        return (
            f"{label} und Core RPC kommen aus Start9-Dependencies "
            f"(Indexer: {indexer}; Wechsel über StartOS-Action „Select Indexer“); "
            "Wallets und übrige Einstellungen werden hier konfiguriert."
        )
    if state.managed_by == "umbrel":
        indexer = _electrum_indexer(werte)
        label = "Fulcrum" if indexer == "fulcrum" else "Electrs"
        return (
            f"{label} und Bitcoin Core kommen aus den auf diesem Umbrel "
            "installierten Apps — hier nicht doppelt pflegen. Wallets und "
            "übrige Einstellungen werden hier konfiguriert."
        )
    return None


def _datenquellen_config_gesperrt(
    state: AppState,
    *,
    quelle: str | None = None,
    werte: dict | None = None,
    aktion: str = "speichern",
) -> None:
    """Schützt Specter komplett, StartOS/Umbrel nur ihre Bridge-Quellen."""
    if state.managed_by == "specter":
        raise ApiError(403, "Datenquellen werden von Specter verwaltet und können hier nicht geändert werden.")
    if state.managed_by not in _NODE_MANAGED:
        return
    if state.managed_by == "umbrel":
        quelle_text = "Electrum-Server und Bitcoin Core kommen aus den Umbrel-Apps"
        schluessel_text = "Electrum-/Core-Bridge-Schlüssel werden von den Umbrel-Apps verwaltet."
    else:
        quelle_text = "Electrs und Core RPC werden von Start9-Dependencies verwaltet"
        schluessel_text = "Electrs/Core-Bridge-Schlüssel werden von Start9-Dependencies verwaltet."

    if quelle in _BRIDGE_QUELLEN or (
        aktion == "verwerfen" and quelle in _BRIDGE_QUELLEN
    ):
        raise ApiError(403, f"{quelle_text} und können hier nicht geändert werden.")
    if werte:
        gesperrt = sorted(set(werte) & _BRIDGE_SCHLUESSEL)
        if gesperrt:
            raise ApiError(403, schluessel_text)


def api_config(state: AppState, query: dict, accept_language: str | None = None) -> dict:
    from core.version import version as app_version
    from core import selbstanzeige as sa_mod

    entries = state.entries
    zusammenfassung = wallets_mod.summarize(entries, state.cache_dir)
    werte = state.env().values()
    quellen = source_mod.anreichere_live_p2p(
        source_mod.mergere_erreichbarkeit(
            source_mod.describe_sources(werte),
            getattr(state, "sources_last", None),
        )
    )
    return {
        "version": app_version(),
        "wallets": [z.as_dict() for z in zusammenfassung],
        "sources": [q.as_dict() for q in quellen],
        "script_types": [
            {"value": t, "label": wallets_mod.SCRIPT_TYPE_LABELS[t]}
            for t in main.SCRIPT_TYPE_CHOICES
        ],
        "sanktion_max_hops_cap": sanctions_mod.sanktion_max_hops_cap(),
        "env_path": str(state.env_path),
        "cache_dir": str(state.cache_dir),
        "rpc_password_set": bool((werte.get("RPCUSER") or "").strip() and (werte.get("RPCPASSWORD") or "").strip()),
        "mempool": mempool_info(werte.get("MEMPOOL_URL", "")),
        "steuer": tax_mod.lese_steuer_einstellungen(werte),
        "person": sa_mod.lese_steuer_person(werte),
        "wallets_beim_start_aktualisieren": (
            main.resolve_wallets_beim_start_aktualisieren(werte)
        ),
        "wallets_immer_aktuell": (
            main.resolve_wallets_beim_start_aktualisieren(werte)
        ),
        "wallets_nur_bekannte_utxos": (
            main.resolve_wallets_nur_bekannte_utxos(werte)
        ),
        "oeffentliche_electrum": source_mod.oeffentliche_electrum_erlaubt(werte),
        # Explizit: Web-Opt-in ist sitzungsweise (nach Neustart wieder false).
        "oeffentliche_electrum_session": (
            source_mod.oeffentliche_electrum_session_aktiv()
        ),
        "wallet_watch": _wallet_watch_status(),

        "hinweis_onchain": tax_mod.HINWEIS_ONCHAIN,
        "hinweis_onchain_bestaetigt": tax_mod.hinweis_onchain_bestaetigt(werte),
        # Wallet-Blöcke hinter einer Lücke werden nicht gelesen. Das muss die
        # Oberfläche sagen können, sonst fehlt ein Wallet ohne jeden Hinweis.
        "uebersprungene_bloecke": bloecke_nach_luecke(werte),
        "multisig_hinweis": (
            main.UNLESBAR_HINWEIS.format(anzahl=len(state.unlesbare_entries))
            if state.unlesbare_entries else ""
        ),
        "header_job_id": state.header_job_id,
        "header_tip": _header_tip(state),
        # Nur melden, wenn der Job wirklich noch läuft (stale ID → null).
        "wallet_sync_job_id": (
            state.wallet_sync_job_id if tip_sync_laeuft(state) else None
        ),
        "live_p2p_peers": _live_p2p_peers(),
        # Ohne Netzprobe — die Pille bleibt grau, bis /api/llm/status?check=1.
        "llm": llm_mod.status_dict(werte, check=False),
        "status_mail": status_mail_mod.als_dict(werte),
        "ui_lang": _ui_lang_fuer_web(werte, accept_language),
        # Hinter Umbrels app_proxy bindet SatSage an 0.0.0.0 — die Fußzeile
        # darf dann nicht "nur lokal erreichbar" behaupten.
        "local_only": _ist_local_only(state),
        "ui_theme": _ui_theme_aus_env(werte),
        "lernhinweise_plebs": _lernhinweise_plebs_aus_env(werte),
        "network": (werte.get("NETWORK") or "main").strip().lower() or "main",
        "managed_by": state.managed_by,
        "managed_hint": _managed_hint(state, werte),
        "electrum_indexer": (
            _electrum_indexer(werte) if state.managed_by in _NODE_MANAGED else None
        ),
        "specter_labels": (
            _specter_labels_for_api(state) if state.managed_by == "specter" else None
        ),
        "local_core": _local_core_status_for_api(state),
        # App-Passwort (Hash in .satsage-password) — UI Einstellungen; Scrambling später.
        "password_set": _password_is_set(state),
        "env_scramble": _env_scramble_status(state),
    }


def _ui_lang_aus_env(werte: dict) -> str:
    """``de`` oder ``en`` aus UI_LANG; Default Deutsch (CLI/Terminal)."""
    roh = str((werte or {}).get("UI_LANG") or "").strip().lower()
    if roh.startswith("en"):
        return "en"
    return "de"


def _ui_lang_fuer_web(werte: dict, accept_language: str | None = None) -> str:
    """``de`` oder ``en`` für die Weboberfläche.

    Eine ausdrückliche Wahl (``UI_LANG``) gewinnt immer. Ohne sie entscheidet
    der Browser über ``Accept-Language`` — umbrelOS reicht seine eigene
    Spracheinstellung nicht an Apps durch, das ist also das einzige Signal.
    Gibt auch der nichts her, ist Englisch die Vorgabe: die Web-GUI hat im
    App Store internationales Publikum. CLI und Terminal-Menü bleiben davon
    unberührt und antworten weiter auf Deutsch.
    """
    roh = str((werte or {}).get("UI_LANG") or "").strip().lower()
    if roh.startswith("en"):
        return "en"
    if roh.startswith("de"):
        return "de"
    return _sprache_aus_accept_language(accept_language) or "en"


def _ui_theme_aus_env(werte: dict) -> str:
    """``light`` oder ``dark`` aus UI_THEME; Default Hell."""
    roh = str((werte or {}).get("UI_THEME") or "").strip().lower()
    if roh in ("dark", "dunkel"):
        return "dark"
    return "light"


def api_save_app_password(state: AppState, payload: dict) -> dict:
    """
    Einstellungen · Passwort setzen/ändern (Token-API, wie übrige Config).

    Reihenfolge: zuerst Login-Hash (atomar), dann Scramble
    (``.env`` als Cipher).
    """
    current = str(payload.get("current_password") or payload.get("old_password") or "")
    password = str(payload.get("new_password") or payload.get("password") or "")
    confirm = str(
        payload.get("confirm") or payload.get("password_confirm") or password
    )
    stored = _password_hash(state)
    if stored and not _verify_password(current, stored):
        raise ApiError(403, "Aktuelles Passwort ist falsch.")
    if not password or password != confirm:
        raise ApiError(400, "Passwörter stimmen nicht überein oder sind leer.")
    try:
        _write_password_hash(state, password)
    except OSError as exc:
        raise ApiError(500, f"Passwort-Hash konnte nicht geschrieben werden: {exc}") from exc
    except Exception as exc:
        raise ApiError(500, f"Passwort-Hash fehlgeschlagen: {exc}") from exc
    try:
        from core import env_scramble as sc_mod

        if stored and sc_mod.is_scramble_file_present(state.env_path):
            _scramble_change_password(state, current, password)
        else:
            _scramble_enable_for_password(state, password)
    except Exception as exc:
        raise ApiError(400, f"env-scramble: {exc}") from exc
    return {
        "ok": True,
        "password_set": True,
        "env_scramble": _env_scramble_status(state),
    }


def api_delete_app_password(state: AppState, payload: dict) -> dict:
    """Einstellungen · Passwort entfernen + Klartext-.env wiederherstellen."""
    current = str(payload.get("current_password") or payload.get("old_password") or "")
    if not _password_is_set(state):
        return {
            "ok": True,
            "password_set": False,
            "env_scramble": _env_scramble_status(state),
        }
    if not current or not _verify_password(current, _password_hash(state)):
        raise ApiError(403, "Aktuelles Passwort ist falsch.")
    try:
        _scramble_disable_for_password(state, current)
    except Exception as exc:
        raise ApiError(400, f"env-scramble: {exc}") from exc
    _clear_password_hash(state)
    return {
        "ok": True,
        "password_set": False,
        "env_scramble": _env_scramble_status(state),
    }


def api_unlock_env(state: AppState, payload: dict) -> dict:
    """Nach Neustart: gobbledigook mit Passwort öffnen (File-Key nur RAM)."""
    password = str(payload.get("password") or payload.get("current_password") or "")
    if not password:
        raise ApiError(400, "Passwort fehlt.")
    if _password_is_set(state) and not _verify_password(password, _password_hash(state)):
        raise ApiError(403, "Passwort ist falsch.")
    try:
        _scramble_unlock(state, password)
    except Exception as exp:
        raise ApiError(403, f"Unlock fehlgeschlagen: {exp}") from exp
    return {"ok": True, "env_scramble": _env_scramble_status(state)}


def api_save_ui_lang(state: AppState, payload: dict) -> dict:
    """Speichert die UI-Sprache in der .env (``UI_LANG``)."""
    roh = payload.get("ui_lang", payload.get("lang", "de"))
    lang = "en" if str(roh).strip().lower().startswith("en") else "de"
    env = state.env()
    env.apply({"UI_LANG": lang})
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    return {"saved": True, "ui_lang": lang}


def api_save_ui_theme(state: AppState, payload: dict) -> dict:
    """Speichert den Farbmodus in der .env (``UI_THEME``)."""
    roh = str(payload.get("ui_theme", payload.get("theme", "light")) or "").strip().lower()
    theme = "dark" if roh in ("dark", "dunkel") else "light"
    env = state.env()
    env.apply({"UI_THEME": theme})
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    return {"saved": True, "ui_theme": theme}


def _lernhinweise_plebs_aus_env(werte: dict) -> bool:
    """``LERNHINWEISE_PLEBS=1`` — Experiment Neugier-Tooltips/Lern-QR; Default aus."""
    roh = str((werte or {}).get("LERNHINWEISE_PLEBS") or "").strip().lower()
    return roh in ("1", "true", "yes", "ja", "on")


def api_save_lernhinweise_plebs(state: AppState, payload: dict) -> dict:
    """Speichert das Experiment „Lernhinweise für Plebs“ in der .env."""
    roh = payload.get("lernhinweise_plebs", payload.get("enabled", False))
    an = roh in (True, 1, "1", "true", "yes", "ja", "on")
    env = state.env()
    env.apply({"LERNHINWEISE_PLEBS": "1" if an else "0"})
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    return {"saved": True, "lernhinweise_plebs": an}


def _pfad_unter(kind: Path, eltern: Path) -> bool:
    try:
        kind.relative_to(eltern)
        return True
    except (ValueError, TypeError):
        return False


def _wallet_export_anlegen_und_cache(
    state: AppState,
    neu_liste: list[WalletEntry],
    parsed,
    *,
    bestaetigt: bool,
    cache_source: str,
) -> dict:
    if not neu_liste:
        raise ApiError(400, "Keine Wallets zum Anlegen.")

    from dataclasses import replace as dc_replace

    vorhanden_ids, _kenn = wallets_mod.vorhandene_abgleich(state.entries)
    entries = list(state.entries)
    angelegt = 0
    schon_da_n = 0
    origin_touch = False
    for neu in neu_liste:
        wid = neu.wallet_id()
        # zpub vs. Deskriptor: gleicher Schlüssel → nicht nochmal anlegen.
        alt = wallets_mod.finde_gleichwertigen_eintrag(entries, neu)
        if alt is None and wid in vorhanden_ids:
            alt = wallets_mod.find_entry(entries, wid)
        if alt is not None:
            schon_da_n += 1
            idx = next(
                (i for i, e in enumerate(entries) if e is alt or wallets_mod.eintrag_id(e) == wallets_mod.eintrag_id(alt)),
                None,
            )
            if idx is not None:
                alt_e = entries[idx]
                soll_origin = (
                    getattr(neu, "origin", "") or ""
                ).strip() or config_mod.WALLET_ORIGIN_WALLET_EXPORT
                if (getattr(alt_e, "origin", "") or "").strip() != soll_origin:
                    entries[idx] = dc_replace(alt_e, origin=soll_origin)
                    origin_touch = True
            continue
        entries.append(neu)
        vorhanden_ids |= wallets_mod.abgleich_ids_fuer_eintrag(neu)
        angelegt += 1

    if angelegt or origin_touch:
        try:
            write_wallets(state.env(), entries, bestaetigt=bestaetigt)
        except BestaetigungNoetig as exc:
            raise ApiError(409, " ".join(exc.warnungen)) from exc
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        except OSError as exc:
            raise ApiError(500, "Interner Serverfehler.") from exc
        state.reload()

    # Cache je angelegtem/bekanntem Wallet (SegWit+Taproot getrennt).
    utxo_n = 0
    verlauf_n = 0
    seed_keys: list[str] = []
    importierte: list[tuple[str, str, str]] = []  # name_lower, id, name
    try:
        for neu in neu_liste:
            wid_i = neu.wallet_id()
            ein = wallets_mod.find_entry(state.entries, wid_i) or neu
            schluessel = ein.analyse_schluessel
            seed_keys.append(schluessel)
            name_i = ein.display_name or neu.display_name or wid_i
            importierte.append((name_i.lower(), wid_i, name_i))
            utxos_i = _export_eintraege_fuer_wallet(parsed.utxos, ein)
            verlauf_i = _export_eintraege_fuer_wallet(parsed.verlauf, ein)
            addrs_i = _export_adressen_fuer_wallet(parsed.adressen, ein)
            # Immer UTXO-Cache anlegen (auch leer) — sonst has_cache/Pille fehlen
            # bei reinem Verlauf-Import (Wasabi ohne offene Coins).
            if utxos_i or verlauf_i or addrs_i or parsed.adressen:
                main.save_xpub_utxo_cache(
                    schluessel,
                    utxos_i or [],
                    state.cache_dir,
                    source=cache_source,
                    max_addresses=ein.max_addresses,
                )
                utxo_n += len(utxos_i or [])
            if verlauf_i:
                bisher = main.load_xpub_verlauf_cache(
                    schluessel, state.cache_dir
                ) or []
                merge = list(bisher)
                gesehen = {
                    f"{e.get('txid')}:{e.get('vout')}:{e.get('spent')}"
                    for e in merge
                    if isinstance(e, dict)
                }
                for e in verlauf_i:
                    key = f"{e.get('txid')}:{e.get('vout')}:{e.get('spent')}"
                    if key in gesehen:
                        continue
                    gesehen.add(key)
                    merge.append(e)
                # Store-/CSV-Verlauf gilt als vollständig genug; Adressen gesetzt.
                main.save_xpub_verlauf_cache(
                    schluessel,
                    merge,
                    state.cache_dir,
                    scanned_addresses=addrs_i or parsed.adressen or None,
                    incomplete=False if (utxos_i or verlauf_i) else True,
                )
                verlauf_n += len(verlauf_i)
            elif addrs_i or parsed.adressen:
                main.save_xpub_verlauf_cache(
                    schluessel,
                    main.load_xpub_verlauf_cache(schluessel, state.cache_dir)
                    or [],
                    state.cache_dir,
                    scanned_addresses=addrs_i or parsed.adressen,
                    incomplete=True,
                )
    except main.CacheDiskFullError as exc:
        raise ApiError(507, str(exc)) from exc
    except OSError as exc:
        raise ApiError(500, "Cache schreiben fehlgeschlagen.") from exc

    importierte.sort(key=lambda t: (t[0], t[1]))
    prim_id = importierte[0][1] if importierte else neu_liste[0].wallet_id()
    bekannt = wallets_mod.find_entry(state.entries, prim_id) or neu_liste[0]

    try:
        main.seed_wallet_addresses_from_utxo_cache(
            state.wallet_ctx, seed_keys or [bekannt.analyse_schluessel],
            state.cache_dir,
        )
    except Exception:
        pass

    erste = config_mod.erste_empfangsadresse(bekannt) or ""
    nachziehen = _export_adressen_nachziehen_meta(state, bekannt)
    return {
        "saved": True,
        "already_present": angelegt == 0 and schon_da_n > 0,
        "wallets_added": angelegt,
        "wallets_existing": schon_da_n,
        "wallet_id": prim_id,
        "wallet_ids": [t[1] for t in importierte],
        "wallets": [
            {"id": t[1], "name": t[2]} for t in importierte
        ],
        "name": bekannt.display_name,
        "format": parsed.format_label,
        "descriptor": bool(bekannt.descriptor),
        "is_multisig": bekannt.is_multisig,
        "erste_adresse": erste,
        "utxo_count": utxo_n,
        "verlauf_count": verlauf_n,
        "address_count": len(parsed.adressen),
        "files": parsed.dateien,
        "hinweise": parsed.hinweise,
        "wallet_count": len(state.entries),
        "address_nachziehen": nachziehen,
    }


def _export_script_familie(entry: WalletEntry) -> str:
    """Grobe Skriptfamilie für Wasabi-SegWit/Taproot-Split."""
    d = (getattr(entry, "descriptor", None) or "").lower()
    if d.startswith("tr(") or "/86h/" in d or "/86'/" in d:
        return "tr"
    if "wsh(" in d or "sh(wsh" in d:
        return "wsh"
    if "wpkh(" in d or "sh(wpkh" in d:
        return "wpkh"
    x = (getattr(entry, "xpub", None) or "").lower()
    if x.startswith(("zpub", "vpub")):
        return "wpkh"
    if x.startswith(("xpub", "tpub")):
        return "mixed"
    return "mixed"


def _export_adresse_familie(addr: str) -> str:
    a = (addr or "").strip().lower()
    if a.startswith(("bc1p", "tb1p", "bcrt1p")):
        return "tr"
    if a.startswith(("bc1q", "tb1q", "bcrt1q")):
        return "wpkh"
    if a.startswith(("3", "2")):
        return "sh"
    if a.startswith(("1", "m", "n")):
        return "pkh"
    return "other"


def _export_eintraege_fuer_wallet(
    eintraege: list | None, entry: WalletEntry,
) -> list:
    """Filtert UTXO/Verlauf-Einträge auf die Skriptfamilie des Wallets."""
    if not eintraege:
        return []
    fam = _export_script_familie(entry)
    if fam == "mixed":
        return list(eintraege)
    out = []
    for e in eintraege:
        if not isinstance(e, dict):
            continue
        addr = str(e.get("address") or "")
        if not addr:
            out.append(e)
            continue
        af = _export_adresse_familie(addr)
        if fam == "tr" and af == "tr":
            out.append(e)
        elif fam == "wpkh" and af in ("wpkh", "sh", "pkh"):
            out.append(e)
        elif fam == af:
            out.append(e)
    return out


def _export_adressen_fuer_wallet(
    adressen: list | None, entry: WalletEntry,
) -> list[str]:
    if not adressen:
        return []
    fam = _export_script_familie(entry)
    if fam == "mixed":
        return [str(a) for a in adressen if a]
    out = []
    for a in adressen:
        s = str(a or "").strip()
        if not s:
            continue
        af = _export_adresse_familie(s)
        if fam == "tr" and af == "tr":
            out.append(s)
        elif fam == "wpkh" and af in ("wpkh", "sh", "pkh"):
            out.append(s)
        elif fam == af:
            out.append(s)
    return out


def _indexer_konfiguriert(state: AppState) -> bool:
    """Eigener Electrs/Fulcrum in der .env (LAN oder Onion) — nicht öffentlicher Pool."""
    try:
        werte = state.env().values()
    except Exception:
        return False
    return bool(
        (werte.get("FULCRUM_HOST") or "").strip()
        or (werte.get("FULCRUM_TOR") or "").strip()
    )


#: Nach Import oft noch Tor-Bootstrap — Job wartet, statt still abzubrechen.
_INDEXER_WARTE_S = 120.0
_INDEXER_WARTE_SCHRITT_S = 3.0


def _warte_auf_eigenen_indexer(state: AppState, stand, job, *, timeout_s: float = _INDEXER_WARTE_S):
    """
    Electrs/Fulcrum holen; bei konfiguriertem Onion/Tor mehrfach versuchen.

    Loggt klar, wenn der Indexer noch fehlt (typisch: Tor startet länger als
    der Import dauert). Rückgabe Client oder ``None``.
    """
    import time

    client = None
    try:
        client = _eigener_fulcrum_client(state)
    except Exception:
        client = None
    if client is not None:
        return client

    if not _indexer_konfiguriert(state):
        stand.phase(
            "Adressen nachziehen braucht Indexer "
            "(kein Electrs/Fulcrum konfiguriert)."
        )
        return None

    stand.phase(
        "Adressen nachziehen braucht Indexer — noch nicht verbunden "
        "(z. B. Tor startet noch). Warte…"
    )
    deadline = time.monotonic() + max(5.0, float(timeout_s))
    n = 0
    while time.monotonic() < deadline:
        job.raise_if_cancelled()
        time.sleep(_INDEXER_WARTE_SCHRITT_S)
        n += 1
        try:
            client = _eigener_fulcrum_client(state)
        except Exception:
            client = None
        if client is not None:
            stand.phase("Indexer verbunden — Adressen nachziehen…")
            return client
        if n == 1 or n % 5 == 0:
            rest = max(0, int(deadline - time.monotonic()))
            stand.phase(
                f"Adressen nachziehen braucht Indexer — warte weiter "
                f"(noch ~{rest}s)…"
            )
    stand.phase(
        "Adressen nachziehen braucht Indexer "
        "(Timeout — Tor/Electrs nicht erreichbar). "
        "Später erneut oder „Historie“."
    )
    return None


def _export_adressen_nachziehen_meta(state: AppState, entry: WalletEntry) -> dict:
    """
    Wie viele Tx im Verlauf noch ohne Adresse sind und ob Electrs greifbar ist.

    *indexer_configured*: FULCRUM_HOST/TOR gesetzt — Job kann auf Tor warten.
    *electrs*: jetzt schon verbunden (sonst warte der Job).
    """
    from core import export_adressen as adr_mod

    verlauf = main.load_xpub_verlauf_cache(
        entry.analyse_schluessel, state.cache_dir
    ) or []
    ohne = adr_mod.verlauf_ohne_adresse(verlauf)
    txids = adr_mod.unique_txids(ohne)
    n = len(txids)
    configured = _indexer_konfiguriert(state)
    electrs = False
    try:
        electrs = _eigener_fulcrum_client(state) is not None
    except Exception:
        electrs = False
    # Konfiguriert genügt für Auto/Nachfrage — Job wartet auf Tor-Bootstrap.
    kann = bool(configured and n > 0)
    return {
        "wallet_id": wallets_mod.eintrag_id(entry),
        "name": entry.display_name,
        "pending_txids": n,
        "pending_entries": len(ohne),
        "electrs": electrs,
        "indexer_configured": configured,
        "auto_max": adr_mod.NACHZIEHEN_AUTO_MAX,
        "auto_start": bool(kann and n <= adr_mod.NACHZIEHEN_AUTO_MAX),
        "needs_confirm": bool(kann and n > adr_mod.NACHZIEHEN_AUTO_MAX),
    }


def _wallets_aus_payload(state: AppState, payload: dict) -> list[WalletEntry]:
    """
    Wandelt die Wallet-Liste aus der Oberfläche in Einträge um.

    Enthält denselben Multisig-Schutz wie beim Speichern: ungesendete Multisig
    bleiben erhalten, damit eine ältere Oberfläche sie nicht still löscht.
    """
    roh = payload.get("wallets")
    if not isinstance(roh, list):
        raise ApiError(400, "Feld 'wallets' fehlt oder ist keine Liste.")

    vorhanden = state.entries
    entries: list[WalletEntry] = []
    for index, eintrag in enumerate(roh, start=1):
        if not isinstance(eintrag, dict):
            raise ApiError(400, f"Wallet {index}: unerwartetes Format.")

        # Bestehende Wallets kommen mit ihrer Kennung zurück, nicht mit dem
        # Schlüssel: Die Oberfläche kennt nur die maskierte Fassung. Nur neu
        # eingefügte Wallets bringen einen XPUB im Klartext mit.
        # Neu angelegte Multisig: Sie kommt mit ihrem Deskriptor, nicht mit
        # einer Kennung — die entsteht erst daraus.
        neuer_deskriptor = str(eintrag.get("descriptor", "")).strip()
        if neuer_deskriptor and not str(eintrag.get("id", "")).strip():
            try:
                origin = str(eintrag.get("origin") or "").strip() or (
                    config_mod.WALLET_ORIGIN_DESCRIPTOR
                )
                entries.append(WalletEntry(
                    name=str(eintrag.get("name", "")),
                    descriptor=neuer_deskriptor,
                    max_addresses=int(
                        eintrag.get("max_addresses", main.DEFAULT_MAX_ADDRESSES)
                    ),
                    read_only=bool(eintrag.get("read_only", False)),
                    origin=origin,
                ))
            except (TypeError, ValueError) as exc:
                raise ApiError(400, f"Wallet {index}: {exc}") from exc
            continue

        kennung = str(eintrag.get("id", "")).strip()
        bekannt = None
        if kennung:
            bekannt = wallets_mod.find_entry(vorhanden, kennung)
            if bekannt is None:
                raise ApiError(400, f"Wallet {index}: unbekannte Kennung.")
            xpub = bekannt.xpub
        else:
            xpub = str(eintrag.get("xpub", ""))

        try:
            if bekannt is not None and bekannt.is_multisig:
                # Multisig kommt nur über die Kennung zurück — die Oberfläche
                # kann sie nicht bearbeiten. Cosigner, Schwellwert und
                # Skripttyp bleiben deshalb, wie sie in der .env stehen;
                # änderbar sind allein Name und Scan-Tiefe.
                entries.append(WalletEntry(
                    name=str(eintrag.get("name", "")) or bekannt.name,
                    xpubs=list(bekannt.xpubs),
                    threshold=bekannt.threshold,
                    script_type=bekannt.script_type,
                    descriptor=bekannt.descriptor,
                    max_addresses=int(
                        eintrag.get("max_addresses", bekannt.max_addresses)
                    ),
                    read_only=bool(
                        eintrag.get("read_only", bekannt.read_only)
                    ),
                    origin=bekannt.origin,
                ))
                continue

            if bekannt is not None and bekannt.descriptor and not bekannt.is_multisig:
                # Single-Sig-Policy (Wasabi WPKH …): Deskriptor behalten.
                entries.append(WalletEntry(
                    name=str(eintrag.get("name", "")) or bekannt.name,
                    descriptor=bekannt.descriptor,
                    script_type=str(
                        eintrag.get("script_type", bekannt.script_type)
                    ),
                    max_addresses=int(
                        eintrag.get("max_addresses", bekannt.max_addresses)
                    ),
                    read_only=bool(
                        eintrag.get("read_only", bekannt.read_only)
                    ),
                    origin=bekannt.origin,
                ))
                continue

            origin = str(eintrag.get("origin") or "").strip()
            if not origin and bekannt is not None:
                origin = bekannt.origin
            if not origin and not kennung:
                origin = config_mod.WALLET_ORIGIN_XPUB
            entries.append(WalletEntry(
                xpub=xpub,
                name=str(eintrag.get("name", "")),
                script_type=str(eintrag.get("script_type", "auto")),
                max_addresses=int(eintrag.get("max_addresses", main.DEFAULT_MAX_ADDRESSES)),
                read_only=bool(eintrag.get("read_only", False)),
                origin=origin,
            ))
        except (TypeError, ValueError) as exc:
            raise ApiError(400, f"Wallet {index}: {exc}") from exc

    # Netz für den Fall, dass die Oberfläche Multisig-Einträge gar nicht
    # zurückschickt — eine ältere Fassung kennt sie nicht. Sie stillschweigend
    # zu verlieren wäre nicht wiedergutzumachen: Die Cosigner stehen dann
    # nirgends mehr.
    gesendete_ids = {wallets_mod.eintrag_id(e) for e in entries}
    for vorhandener in vorhanden:
        if vorhandener.is_multisig and (
            wallets_mod.eintrag_id(vorhandener) not in gesendete_ids
        ):
            entries.append(vorhandener)
    return entries


def _entfernte_wallets(
    vorher: list[WalletEntry],
    nachher: list[WalletEntry],
) -> list[WalletEntry]:
    behalten = {wallets_mod.eintrag_id(e) for e in nachher}
    return [e for e in vorher if wallets_mod.eintrag_id(e) not in behalten]


def _payload_bool(payload: dict, *keys, default: bool | None = None) -> bool | None:
    """Erstes gesetztes Bool-Feld aus *payload*; None wenn keines der Keys da ist."""
    for key in keys:
        if key not in payload:
            continue
        roh = payload.get(key)
        if isinstance(roh, str):
            return roh.strip().lower() in ("1", "true", "ja", "yes", "on")
        return bool(roh)
    return default


def api_save_start_sync(state: AppState, payload: dict) -> dict:
    """
    Speichert „Wallets immer aktuell halten“ (+ Unteroption) in der .env.

    Bei ja: Tip-Nachzug beim Start + Electrs-Subscribe (eigener Node).
    ``nur_bekannte_utxos``: Tip-Nachzug ohne Gap — nur bekannte UTXOs.
    """
    an = _payload_bool(
        payload,
        "enabled",
        "wallets_immer_aktuell",
        "wallets_beim_start_aktualisieren",
        default=False,
    )
    assert an is not None
    nur_bekannte = _payload_bool(
        payload,
        "nur_bekannte_utxos",
        "known_only",
        "wallets_nur_bekannte_utxos",
        default=None,
    )
    if not an:
        nur_bekannte = False
    elif nur_bekannte is None:
        nur_bekannte = main.resolve_wallets_nur_bekannte_utxos(
            state.env().values()
        )

    env = state.env()
    # Beide Keys: UI-Name neu, Legacy bleibt lesbar.
    env.apply({
        "WALLETS_IMMER_AKTUELL": "1" if an else "0",
        "WALLETS_BEIM_START_AKTUALISIEREN": "1" if an else "0",
        "WALLETS_NUR_BEKANNTE_UTXOS": "1" if nur_bekannte else "0",
    })
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    # Sofort wirksam — kein Server-Neustart nötig.
    sync_job = None
    try:
        from core import wallet_watch

        if an:
            # Alten Gap-Lauf stoppen, damit die neue Option (z. B. nur bekannte)
            # nicht hinter einem noch laufenden Tip-Nachzug stecken bleibt.
            _tip_sync_abbrechen(state)
            # 1) Tip-Nachzug jetzt (wie beim Start)
            sync_job = starte_wallet_aktualisierung(state, erzwingen=True)
            # 2) Electrs-Subscribe für Live-Updates
            wallet_watch.starte_wallet_watch(
                state, on_log=lambda t: print(f"  {t}", flush=True),
            )
        else:
            _tip_sync_abbrechen(state)
            wallet_watch.stoppe_wallet_watch()
    except Exception:
        pass

    out = {
        "saved": True,
        "wallets_beim_start_aktualisieren": an,
        "wallets_immer_aktuell": an,
        "wallets_nur_bekannte_utxos": bool(nur_bekannte),
        "wallet_watch": _wallet_watch_status(),
    }
    if isinstance(sync_job, dict) and sync_job.get("id"):
        out["wallet_sync_job_id"] = sync_job["id"]
        out["job"] = sync_job
    return out


def _wallet_watch_status() -> dict:
    try:
        from core import wallet_watch

        return wallet_watch.wallet_watch_status()
    except Exception:
        return {"running": False}


def api_save_steuer(state: AppState, payload: dict) -> dict:
    """
    Speichert Haltefrist, Stichtagsregel und Anschaffungslesart.

    Die Haltefrist ist die Zahl der Jahre bis zur Steuerfreiheit (Vorgabe 1,
    Deutschland). Der Stichtag ist optional — etwa der österr. Altbestand
    (28.02.2021): Anschaffungen danach werden nicht durch Halten steuerfrei.
    Leer schaltet die Cutoff-Regel aus.

    *anschaffung*: ``juengste`` (defensiv, Default) oder ``aelteste`` (offensiv).
    """
    try:
        frist = int(payload.get("haltefrist_jahre", tax_mod.STANDARD_HALTEFRIST_JAHRE))
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "Haltefrist muss eine ganze Zahl von Jahren sein.") from exc
    frist = max(0, min(tax_mod.HALTEFRIST_MAX_JAHRE, frist))

    roh = payload.get("stichtag")
    if roh is None:
        roh = ""
    try:
        tag = tax_mod.parse_stichtag(str(roh))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc

    env = state.env()
    bisher = tax_mod.lese_steuer_einstellungen(env.values())
    if "anschaffung" in payload:
        anschaffung = tax_mod.parse_anschaffung(payload.get("anschaffung"))
    else:
        anschaffung = bisher["anschaffung"]

    env.apply({
        "STEUER_HALTEFRIST_JAHRE": str(frist),
        "STEUER_STICHTAG": tax_mod.format_stichtag(tag),
        "STEUER_ANSCHAFFUNG": anschaffung,
    })
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    return {
        "saved": True,
        "steuer": tax_mod.lese_steuer_einstellungen(env.values()),
    }


def api_save_steuer_person(state: AppState, payload: dict) -> dict:
    """
    Speichert persönliche Daten und Finanzamt-Angaben für HTML/CSV-Berichte.

    Leere Felder → Env-Key entfernen → Name/Steuernummer/Anschrift wieder
    Donald-Duck-Defaults; optionale Felder (E-Mail, Finanzamt, …) bleiben leer.
    """
    from core import selbstanzeige as sa_mod

    def _feld(*keys: str) -> str:
        for key in keys:
            if key in payload and payload.get(key) is not None:
                return str(payload.get(key) or "").strip()
        return ""

    name = _feld("name", "person_name")
    steuernummer = _feld("steuernummer", "tax_id")
    anschrift = _feld("anschrift", "address", "adresse")
    email = _feld("email", "e_mail", "mail")
    finanzamt = _feld("finanzamt", "tax_office")
    finanzamt_anschrift = _feld(
        "finanzamt_anschrift", "finanzamt_address", "tax_office_address",
    )
    sachbearbeiter = _feld("sachbearbeiter", "case_worker", "clerk")

    if len(name) > 200:
        raise ApiError(400, "Name ist zu lang (max. 200 Zeichen).")
    if len(steuernummer) > 80:
        raise ApiError(400, "Steuernummer ist zu lang (max. 80 Zeichen).")
    if len(anschrift) > 400:
        raise ApiError(400, "Anschrift ist zu lang (max. 400 Zeichen).")
    if len(email) > 200:
        raise ApiError(400, "E-Mail ist zu lang (max. 200 Zeichen).")
    if email and ("@" not in email or " " in email):
        raise ApiError(400, "E-Mail sieht ungültig aus.")
    if len(finanzamt) > 200:
        raise ApiError(400, "Finanzamt ist zu lang (max. 200 Zeichen).")
    if len(finanzamt_anschrift) > 400:
        raise ApiError(400, "Finanzamt-Anschrift ist zu lang (max. 400 Zeichen).")
    if len(sachbearbeiter) > 200:
        raise ApiError(400, "Sachbearbeiter ist zu lang (max. 200 Zeichen).")

    env = state.env()
    env.apply({
        "STEUER_PERSON_NAME": name or None,
        "STEUER_PERSON_STEUERNUMMER": steuernummer or None,
        "STEUER_PERSON_ANSCHRIFT": anschrift or None,
        "STEUER_PERSON_EMAIL": email or None,
        "STEUER_PERSON_FINANZAMT": finanzamt or None,
        "STEUER_PERSON_FINANZAMT_ANSCHRIFT": finanzamt_anschrift or None,
        "STEUER_PERSON_SACHBEARBEITER": sachbearbeiter or None,
    })
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    return {"saved": True, "person": sa_mod.lese_steuer_person(env.values())}


def api_save_hinweis_onchain(state: AppState, payload: dict) -> dict:
    """
    Merkt, dass der On-Chain-Hinweis auf dieser Installation bestätigt wurde.

    Geschrieben wird die .env — nicht localStorage — damit derselbe Rechner
    den Absatz nicht in jedem Browser wieder zeigt.
    """
    roh = payload.get("bestaetigt", payload.get("hinweis_onchain_bestaetigt"))
    if isinstance(roh, str):
        an = roh.strip().lower() in ("1", "true", "ja", "yes", "on")
    else:
        an = bool(roh)

    env = state.env()
    env.apply({
        tax_mod.ENV_HINWEIS_ONCHAIN_BESTAETIGT: "1" if an else "0",
    })
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    return {
        "saved": True,
        "hinweis_onchain_bestaetigt": an,
    }


def api_save_llm(state: AppState, payload: dict) -> dict:
    """
    Speichert die Assistenten-Anbindung (URL, Modell, Anbieter, Opt-in).

    Der API-Key wird nur geschrieben, wenn das Feld nicht leer ist — analog
    zu RPC-Passwort. ``XAI_API_KEY`` wird weder gelesen noch gesetzt; ein
    Key gehört ausschließlich nach ``LLM_API_KEY``.
    """
    if not isinstance(payload, dict):
        raise ApiError(400, "Ungültiger Körper.")

    base = str(payload.get("base_url") or payload.get("LLM_BASE_URL") or "").strip()
    modell = str(payload.get("modell") or payload.get("LLM_MODELL") or "").strip()
    anbieter = str(payload.get("anbieter") or payload.get("LLM_ANBIETER") or "").strip()
    anbieter = anbieter.lower().replace("_", "-")
    if anbieter == "apikey":
        anbieter = "api-key"
    if anbieter and anbieter not in llm_mod.ANBIETER_WERTE:
        raise ApiError(400, f"Unbekannter Anbieter „{anbieter}“.")

    roh_opt = payload.get("remote_opt_in", payload.get("LLM_REMOTE_OPT_IN"))
    if isinstance(roh_opt, str):
        opt_in = roh_opt.strip().lower() in ("1", "true", "yes", "ja", "on")
    else:
        opt_in = bool(roh_opt)

    key = str(payload.get("api_key") or payload.get("LLM_API_KEY") or "").strip()
    if payload.get("XAI_API_KEY"):
        raise ApiError(400, "XAI_API_KEY wird hier nicht entgegengenommen.")

    env = state.env()
    updates: dict[str, str | None] = {
        "LLM_BASE_URL": base or None,
        "LLM_MODELL": modell or None,
        "LLM_ANBIETER": anbieter or None,
        "LLM_REMOTE_OPT_IN": "1" if opt_in else "0",
    }
    if key:
        updates["LLM_API_KEY"] = key
    if payload.get("api_key_clear"):
        updates["LLM_API_KEY"] = None

    env.apply(updates)
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    werte = env.values()
    return {
        "saved": True,
        "llm": llm_mod.status_dict(werte, check=False),
    }


def api_save_status_mail(state: AppState, payload: dict) -> dict:
    """
    Speichert Status-Mail-Opt-in und SMTP-Zugang.

    Leeres Passwort-Feld behält den gesetzten Wert (wie LLM-API-Key).
    """
    if not isinstance(payload, dict):
        raise ApiError(400, "Ungültiger Körper.")

    to = str(payload.get("to") or payload.get("STATUS_MAIL_TO") or "").strip()
    host = str(payload.get("smtp_host") or payload.get("SMTP_HOST") or "").strip()
    from_addr = str(
        payload.get("smtp_from") or payload.get("SMTP_FROM") or ""
    ).strip()
    user = str(payload.get("smtp_user") or payload.get("SMTP_USER") or "").strip()
    port_roh = payload.get("smtp_port", payload.get("SMTP_PORT", 587))
    try:
        port = int(port_roh)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "SMTP-Port muss eine Zahl sein.") from exc
    if not (1 <= port <= 65535):
        raise ApiError(400, "SMTP-Port ungültig.")

    roh_opt = payload.get("opt_in", payload.get("STATUS_MAIL_OPT_IN"))
    if isinstance(roh_opt, str):
        opt_in = roh_opt.strip().lower() in ("1", "true", "ja", "yes", "on")
    else:
        opt_in = bool(roh_opt)

    roh_tls = payload.get("starttls", payload.get("SMTP_STARTTLS"))
    if roh_tls is None:
        starttls = True
    elif isinstance(roh_tls, str):
        starttls = roh_tls.strip().lower() in ("1", "true", "ja", "yes", "on")
    else:
        starttls = bool(roh_tls)

    password = str(
        payload.get("smtp_password") or payload.get("SMTP_PASSWORD") or ""
    ).strip()
    if host:
        try:
            outbound_policy.ensure_host_allowed(
                host, service="smtp", values=state.env().values(),
                opt_in=outbound_policy.public_opt_in(state.env().values(), "smtp"),
            )
        except outbound_policy.OutboundPolicyError as exc:
            raise ApiError(400, str(exc)) from exc

    env = state.env()
    updates: dict[str, str | None] = {
        status_mail_mod.ENV_OPT_IN: "1" if opt_in else "0",
        status_mail_mod.ENV_TO: to or None,
        status_mail_mod.ENV_HOST: host or None,
        status_mail_mod.ENV_PORT: str(port),
        status_mail_mod.ENV_USER: user or None,
        status_mail_mod.ENV_FROM: from_addr or None,
        status_mail_mod.ENV_STARTTLS: "1" if starttls else "0",
    }
    if password:
        updates[status_mail_mod.ENV_PASSWORD] = password
    if payload.get("smtp_password_clear"):
        updates[status_mail_mod.ENV_PASSWORD] = None

    env.apply(updates)
    try:
        env.save()
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    return {
        "saved": True,
        "status_mail": status_mail_mod.als_dict(env.values()),
    }


def registriere_status_mail_hook(state: AppState) -> None:
    """Job-Ende → neutrale Status-Mail (rescan/verlauf), wenn konfiguriert."""

    def fertig(job) -> None:
        kind = getattr(job, "kind", "") or ""
        if kind not in status_mail_mod.STATUS_MAIL_KINDS:
            return
        status = getattr(job, "status", "") or ""
        if status not in ("done", "failed", "cancelled"):
            return
        try:
            werte = state.env().values()
        except Exception:
            return
        if not status_mail_mod.darf_senden(werte, kind):
            return
        status_mail_mod.sende_status_mail_async(
            werte,
            kind=kind,
            status=status,
            finished_at=getattr(job, "finished_at", None),
        )

    setze_fertig_hook(fertig)


def _loesche_source_stand(state: AppState, *keys: str) -> None:
    """sources_last für geänderte Quellen leeren — sonst bleibt die Pille grün."""
    if not keys or not getattr(state, "sources_last", None):
        return
    keyset = {str(k) for k in keys}
    neu: list = []
    for eintrag in state.sources_last:
        if not isinstance(eintrag, dict):
            continue
        if str(eintrag.get("key") or "") in keyset:
            d = dict(eintrag)
            d["reachable"] = None
            d["error"] = ""
            d["peer_count"] = 0
            d["peer_hosts"] = []
            d["software"] = ""
            d["software_raw"] = ""
            neu.append(d)
        else:
            neu.append(eintrag)
    state.sources_last = neu


def _verwerfe_electrs_verbindungen(state: AppState) -> None:
    """
    Alte Electrs-Sockets/Sessions nach Host-/Port-Wechsel schließen.

    * Empfangs-QR-Client (AppState-Cache)
    * Wallet-Watch-Subscribe (sonst hängt die Session am alten Endpoint)
    """
    # Empfang-Clients: reload() hat sie schon genullt; sicherheitshalber nochmal.
    with getattr(state, "_empfang_fulcrum_lock", threading.Lock()):
        alt = getattr(state, "_empfang_fulcrum", None)
        alt_pub = getattr(state, "_empfang_public_fulcrum", None)
        state._empfang_fulcrum = None
        state._empfang_public_fulcrum = None
    for client in (alt, alt_pub):
        if client is None:
            continue
        try:
            client.close()
        except Exception:
            pass
    try:
        from core import wallet_watch

        if wallet_watch.get_watch_service().laeuft:
            wallet_watch.restart_wallet_watch(
                state,
                on_log=lambda t: LOGGER.info("%s", t),
            )
        else:
            # Watch war aus — falls Option an, frisch starten mit neuem Endpoint.
            wallet_watch.starte_wallet_watch(
                state,
                on_log=lambda t: LOGGER.info("%s", t),
            )
    except Exception as exc:
        LOGGER.warning("Electrs-Verbindungen nach Config-Wechsel: %s", exc)


def _sortierung(query: dict) -> str:
    roh = (query.get("sort") or ["betrag"])[0]
    return roh if roh in ("betrag", "datum") else "betrag"


def _verlaufs_anhang(state: AppState, entries, *, limit: int | None = None,
                     sort: str = "datum") -> dict:
    """
    Ausgegebene Outputs aus dem Verlaufs-Cache — dieselbe Datei, die
    Steuerjahr und Herkunft lesen. Kein Netzzugriff.
    """
    verlauf: list[dict] = []
    for entry in entries:
        gespeichert = main.load_xpub_verlauf_cache(
            entry.analyse_schluessel, state.cache_dir
        )
        if not gespeichert:
            continue
        # Name mitgeben: Sparrow-Tx-CSV-Einträge ohne Adresse sonst
        # „unbekanntes Wallet“, obwohl der Cache klar diesem Wallet gehört.
        name = entry.display_name
        for roh in gespeichert:
            if not isinstance(roh, dict):
                continue
            kopie = dict(roh)
            if name and not kopie.get("_wallet_fallback"):
                kopie["_wallet_fallback"] = name
            verlauf.append(kopie)
    return {
        "verlauf": utxos_mod.historische_eintraege(
            verlauf,
            wallet=state.wallet_ctx,
            immutable_cache_dir=state.immutable_cache_dir,
            own_addresses=_eigene_adressen(state),
            limit=limit,
            sort=sort,
        ),
        "hat_verlauf": bool(verlauf),
    }


def _merke_own_fulcrum_client(state: AppState, client) -> dict | None:
    """
    Eigener Electrum-Connect → sources_last + Job-tauglicher Stand.

    Tip-Sync und Empfang verbinden oft Minuten vor dem 30‑s-Peer-Takt;
    die Kopf-Pille soll dann schon grün mit libbitcoin/electrs/fulcrum sein.
    """
    stand = source_mod.own_fulcrum_stand_from_client(client)
    if not stand:
        return None
    try:
        werte = state.env().values()
        frisch = source_mod.describe_sources(werte)
        state.sources_last = source_mod.merke_own_fulcrum_in_sources(
            getattr(state, "sources_last", None),
            frisch,
            stand,
        )
    except Exception:
        LOGGER.debug("own_fulcrum Stand merken fehlgeschlagen", exc_info=True)
    return stand


def _eigener_fulcrum_client(state: AppState):
    """
    Eigener Electrs/Fulcrum oder None (kein öffentlicher Pool).

    Wiederverwendet eine Verbindung am AppState — sonst kostet jeder
    Empfangs-QR-Klick einen frischen TCP/TLS-Handshake (wirkt wie „Scan“).
    """
    werte = state.env().values()
    if not (
        (werte.get("FULCRUM_HOST") or "").strip()
        or (werte.get("FULCRUM_TOR") or "").strip()
    ):
        return None

    lock = getattr(state, "_empfang_fulcrum_lock", None)
    if lock is None:
        lock = threading.Lock()
        state._empfang_fulcrum_lock = lock

    with lock:
        alt = getattr(state, "_empfang_fulcrum", None)
        if alt is not None:
            try:
                alt.request("server.ping")
                _merke_own_fulcrum_client(state, alt)
                return alt
            except Exception:
                try:
                    alt.close()
                except Exception:
                    pass
                state._empfang_fulcrum = None
        try:
            client = main._try_own_fulcrum_client(
                state.args_namespace(), werte,
            )
        except Exception:
            return None
        state._empfang_fulcrum = client
        if client is not None:
            _merke_own_fulcrum_client(state, client)
        return client


def _oeffentlicher_fulcrum_fuer_empfang(state: AppState):
    """
    Öffentlicher Electrum-Pool für Empfangs-History — nur mit Opt-in.

    Ohne ``OEFFENTLICHE_ELECTRUM`` bleibt es bei der Cache-Schätzung
    (keine Adress-Probes an Fremdserver). Mit Opt-in: dieselbe History-Probe
    wie beim eigenen Node; die Adressen sind dem Pool ohnehin schon bekannt,
    sobald Scans darüber laufen.
    """
    werte = state.env().values()
    if not source_mod.oeffentliche_electrum_erlaubt(werte):
        return None

    lock = getattr(state, "_empfang_fulcrum_lock", None)
    if lock is None:
        lock = threading.Lock()
        state._empfang_fulcrum_lock = lock

    with lock:
        alt = getattr(state, "_empfang_public_fulcrum", None)
        if alt is not None:
            try:
                alt.request("server.ping")
                return alt
            except Exception:
                try:
                    alt.close()
                except Exception:
                    pass
                state._empfang_public_fulcrum = None
        try:
            args = state.args_namespace()
            pool = main._try_public_onion_fulcrum(
                args, werte, interactive=False,
            )
            if pool is None:
                pool = main._setup_public_clearnet_fulcrum(args, werte)
        except Exception:
            return None
        state._empfang_public_fulcrum = pool
        return pool


def _empfang_electrum_client(state: AppState):
    """
    Electrum für Empfangs-QR: eigener Node, sonst öffentlicher nach Opt-in.
    """
    eigen = _eigener_fulcrum_client(state)
    if eigen is not None:
        return eigen
    return _oeffentlicher_fulcrum_fuer_empfang(state)


def _adresse_hat_history(client, address: str) -> bool:
    """True wenn Electrs für die Adresse mindestens eine Tx kennt."""
    if not address:
        return False
    from fulcrum import address_to_scripthash

    sh = address_to_scripthash(address)
    hist = client.request("blockchain.scripthash.get_history", [sh]) or []
    return bool(hist)


def _naechste_freie_empfang_electrs(
    state: AppState,
    entry,
    client,
    *,
    max_index: int,
) -> tuple[str, int] | None:
    """
    Nächste freie Empfangsadresse per Electrs — **kein** Fullscan.

    Educated guess aus UTXO-/Verlaufs-Cache (``max bekannter Empfangs-Index + 1``,
    nach Tip-Sync typisch schon korrekt). Dann nur **vorwärts** per
    ``get_history`` prüfen, bis die erste leere Adresse kommt.

    Üblich: **1 RPC**. Wenn der Cache hinter der Chain liegt (Zahlung auf
    höherem Index), wenige weitere Probes — Obergrenze ``BIP44_GAP_LIMIT``,
    kein Walk ab #0 und kein electrs-seitiger Gap-Rescan.
    """
    gap = int(getattr(main, "BIP44_GAP_LIMIT", 20) or 20)
    skript = (
        None if entry.is_multisig or entry.descriptor else entry.script_type
    )
    xpub = entry.analyse_schluessel
    start = int(
        _next_receive_index_from_cache(state, entry, max_index=max_index)
    )
    if start < 0:
        start = 0
    # Nur vorwärts ab Schätzung — höchstens gap+1 History-Probes.
    limit = min(max_index, start + gap + 1)
    for i in range(start, limit):
        dest = main.derive_receive_address_at_index(
            xpub, i, script_type=skript,
        )
        if not dest or not dest[0]:
            break
        if _adresse_hat_history(client, dest[0]):
            continue
        return str(dest[0]), int(i)
    return None


def _schaerfe_empfang_nach_sync(
    state: AppState,
    eintraege: list,
    *,
    fulcrum=None,
    on_progress=None,
) -> int:
    """
    Einmal nach Tip-Nachzug / UTXO-Scan: Empfangs-QR schärfen.

    * Prozess-Cache leeren, dann pro Wallet **1–wenige** ``get_history`` ab
      Cache-Schätzung (kein Fullscan, siehe ``_naechste_freie_empfang_electrs``).
    * Electrum: eigener Node, oder öffentlicher Pool nach Opt-in
      (``OEFFENTLICHE_ELECTRUM``). Ohne beides: nur Cache leeren.
    """
    if not eintraege:
        return 0
    for entry in eintraege:
        try:
            state.empfang_cache.pop(wallets_mod.eintrag_id(entry), None)
        except Exception:
            pass

    client = fulcrum
    if client is not None:
        try:
            if not main.is_own_fulcrum_backend(client):
                # Öffentlicher Pool nur mit Opt-in — sonst keine Adress-Probes.
                if not source_mod.oeffentliche_electrum_erlaubt(
                    state.env().values()
                ):
                    client = None
        except Exception:
            client = None
    if client is None:
        client = _empfang_electrum_client(state)
    if client is None:
        return 0

    from core import wallet_watch

    watch = wallet_watch.wallet_watch_status()
    watch_active = bool(watch.get("running"))
    gap = int(getattr(main, "BIP44_GAP_LIMIT", 20) or 20)
    ok = 0

    def _cache_estimate_merker(entry) -> None:
        """Fallback-QR aus UTXO-Stand, falls Electrs scheitert / Belong-Check nein."""
        kennung = wallets_mod.eintrag_id(entry)
        try:
            max_index = _empfang_max_index(entry, state)
            next_index = _next_receive_index_from_cache(
                state, entry, max_index=max_index,
            )
            skript = (
                None
                if entry.is_multisig or entry.descriptor
                else entry.script_type
            )
            abgeleitet = main.derive_receive_address_at_index(
                entry.analyse_schluessel, next_index, script_type=skript,
            )
            if not abgeleitet or not abgeleitet[0]:
                return
            address, index = str(abgeleitet[0]), int(abgeleitet[1])
            # Belong-Check hier weich: sonst bleibt das Dock leer (500).
            state.empfang_cache[kennung] = _empfang_antwort(
                kennung=kennung,
                entry=entry,
                address=address,
                index=index,
                source="cache_estimate",
                subscribed=False,
                watch_active=watch_active,
                read_only=False,
            )
        except Exception:
            pass

    for entry in eintraege:
        if getattr(entry, "read_only", False) or not entry.is_valid():
            continue
        kennung = wallets_mod.eintrag_id(entry)
        try:
            if on_progress:
                on_progress(
                    f"Empfangsadresse „{entry.display_name}“ per Electrs…",
                    sofort=True,
                )
            max_index = _empfang_max_index(entry, state)
            treffer = _naechste_freie_empfang_electrs(
                state, entry, client, max_index=max_index,
            )
            if not treffer:
                _cache_estimate_merker(entry)
                continue
            address, index = treffer
            if not _empfang_gehoert_zu_wallet(state, entry, address):
                _cache_estimate_merker(entry)
                continue
            skript = (
                None
                if entry.is_multisig or entry.descriptor
                else entry.script_type
            )
            lookahead: list[str] = []
            for i in range(index, min(index + gap + 1, max_index)):
                dest = main.derive_receive_address_at_index(
                    entry.analyse_schluessel, i, script_type=skript,
                )
                if dest and dest[0] and dest[0] not in lookahead:
                    lookahead.append(dest[0])
            subscribed = False
            if watch_active and lookahead:
                subscribed = bool(
                    wallet_watch.subscribe_addresses(
                        lookahead, entry.analyse_schluessel,
                    )
                )
            state.empfang_cache[kennung] = _empfang_antwort(
                kennung=kennung,
                entry=entry,
                address=address,
                index=index,
                source="fulcrum",
                subscribed=subscribed,
                watch_active=watch_active,
                read_only=False,
            )
            ok += 1
        except Exception as exc:
            # Tip/Scan bleibt gültig — Empfang fällt auf Cache-Schätzung zurück.
            if on_progress:
                try:
                    on_progress(
                        f"Empfang „{entry.display_name}“: {exc}",
                        sofort=True,
                    )
                except Exception:
                    pass
            _cache_estimate_merker(entry)
            continue
    return ok


def _verlauf_anhang_fuer_xpub(
    state: AppState,
    xpub: str,
    *,
    limit: int | None,
    sort: str,
) -> dict:
    gespeichert = main.load_xpub_verlauf_cache(xpub, state.cache_dir) or []
    name = ""
    for e in state.entries:
        if e.analyse_schluessel == xpub or e.xpub == xpub:
            name = e.display_name
            break
    if name:
        angereichert = []
        for roh in gespeichert:
            if not isinstance(roh, dict):
                continue
            kopie = dict(roh)
            if not kopie.get("_wallet_fallback"):
                kopie["_wallet_fallback"] = name
            angereichert.append(kopie)
        gespeichert = angereichert
    return {
        "verlauf": utxos_mod.historische_eintraege(
            gespeichert,
            wallet=state.wallet_ctx,
            immutable_cache_dir=state.immutable_cache_dir,
            own_addresses=_eigene_adressen(state),
            limit=limit,
            sort=sort,
        ),
        "hat_verlauf": bool(gespeichert),
    }


def _mit_mempool_pending(
    state: AppState,
    gecacht: list[dict],
    anhang: dict,
    *,
    limit: int | None,
    sort: str,
    xpub: str | None = None,
) -> tuple[list[dict], dict]:
    """
    Eigener Electrs: Pending + bestätigte Spends gezielt.

    * **Pending** (Mempool): UTXO bleibt, „wird gerade ausgegeben“;
      unter ausgegeben als pending.
    * **Bestätigt** (ein XPUB): Cache settlen — UTXO raus, Verlauf spent,
      listunspent der Adresse (Change) — kein Fullscan.

    Mit ``xpub`` (einzelne Wallet-Ansicht) nur diese Wallet prüfen — sonst
    ``listunspent`` über alle Adressen aller Wallets und spürbare Wartezeit
    schon beim Öffnen eines 1-UTXO-Wallets. Querschnitt bleibt bei
    Herkunft ``/api/utxos`` (``xpub is None``).
    """

    client = _eigener_fulcrum_client(state)
    if client is None:
        return gecacht, anhang

    pending: list[dict] = []
    confirmed: list[dict] = []
    live: list[dict] = []
    empfaenge: list[dict] = []
    # Verlauf-Pending (nach Light-Prune ohne Mempool-Nachzug): wieder prüfen.
    kandidaten = list(gecacht)
    gesehen_k = {
        f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        for u in kandidaten
    }
    for u in (anhang.get("verlauf") or {}).get("utxos") or []:
        if not u.get("spent_pending"):
            continue
        key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        if key in gesehen_k:
            continue
        gesehen_k.add(key)
        kandidaten.append({
            "txid": u.get("txid"),
            "vout": u.get("vout"),
            "value": u.get("value_sats") or u.get("value") or 0,
            "address": u.get("address"),
            "status": {
                "confirmed": bool(u.get("confirmed")),
                "block_height": u.get("block_height"),
                "block_time": u.get("block_time"),
            },
        })
    ziel_keys = {f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}" for u in kandidaten}
    ziel_adressen = {u.get("address") for u in kandidaten if u.get("address")}
    # Herkunft: alle Wallets in den Electrs-Check. Einzel-Wallet: nicht —
    # die Ergebnisse würden ohnehin auf ziel_keys gefiltert, die Roundtrips
    # kosten aber ~100 ms je Adresse.
    if xpub is None:
        for entry_anderes in state.analyse_entries:
            try:
                cache_anderes = main.load_xpub_cache_entry(entry_anderes.analyse_schluessel, state.cache_dir)
                andere_utxos = (cache_anderes or {}).get("utxos") or []
            except Exception:
                andere_utxos = []
            for u in andere_utxos:
                key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
                if key not in gesehen_k:
                    gesehen_k.add(key)
                    kandidaten.append(u)
            try:
                verlauf_anderes = main.load_xpub_verlauf_cache(entry_anderes.analyse_schluessel, state.cache_dir) or []
            except Exception:
                verlauf_anderes = []
            for e in verlauf_anderes:
                if not e.get("spent_pending"):
                    continue
                key = f"{str(e.get('txid') or '').lower()}:{int(e.get('vout') or 0)}"
                if key in gesehen_k:
                    continue
                gesehen_k.add(key)
                kandidaten.append({"txid": e.get("txid"), "vout": e.get("vout"), "value": int(e.get("value") or 0), "address": e.get("address"), "status": e.get("status") or {}})
    try:
        from fulcrum import (
            eigene_mempool_empfaenge,
            klassifiziere_utxo_spends,
            mempool_tx_hat_eigenen_output,
        )

        alle_pending, alle_confirmed, alle_live = klassifiziere_utxo_spends(client, kandidaten)
        pending = [p for p in alle_pending if not xpub or f"{str(p.get('txid') or '').lower()}:{int(p.get('vout') or 0)}" in ziel_keys]
        confirmed = [c for c in alle_confirmed if not xpub or f"{str(c.get('txid') or '').lower()}:{int(c.get('vout') or 0)}" in ziel_keys]
        live = [u for u in alle_live if not xpub or u.get("address") in ziel_adressen]
        # Intern = Output an irgendein SatSage-Wallet (nicht nur Change desselben).
        intern_tx: set[str] = set()
        if alle_pending and state.wallet_ctx is not None:
            try:
                if xpub:
                    ziel_name = state.wallet_ctx.xpub_label(xpub)
                    def _empfang_gehort(addr: str) -> bool:
                        return state.wallet_ctx.resolve_address(addr) == ziel_name
                else:
                    _empfang_gehort = state.wallet_ctx.is_own_address
                empfaenge = eigene_mempool_empfaenge(
                    client, alle_pending, is_own_address=_empfang_gehort,
                )
            except Exception:
                empfaenge = []
            try:
                is_own = state.wallet_ctx.is_own_address
                gesehen_tx: set[str] = set()
                for p in alle_pending:
                    tid = str(p.get("spent_txid") or "").strip().lower()
                    if not tid or tid in gesehen_tx:
                        continue
                    gesehen_tx.add(tid)
                    if mempool_tx_hat_eigenen_output(client, tid, is_own):
                        intern_tx.add(tid)
            except Exception:
                intern_tx = set()
    except Exception:
        return gecacht, anhang
    else:
        # Settle bevor close — Electrs-Tip für scan_tip_height noch erreichbar.
        if confirmed and xpub:
            try:
                neu = main.settle_gezielte_spends_im_cache(
                    xpub,
                    state.cache_dir,
                    confirmed_spent=confirmed,
                    live_auf_adressen=live,
                    source="fulcrum",
                    fulcrum=client,
                )
                if neu is not None:
                    gecacht = neu
                anhang = _verlauf_anhang_fuer_xpub(
                    state, xpub, limit=limit, sort=sort,
                )
            except Exception:
                conf_keys = {
                    f"{str(c.get('txid') or '').lower()}:"
                    f"{int(c.get('vout') or 0)}"
                    for c in confirmed
                }
                gecacht = [
                    u for u in gecacht
                    if f"{str(u.get('txid') or '').lower()}:"
                    f"{int(u.get('vout') or 0)}" not in conf_keys
                ]
                anhang = utxos_mod.merge_pending_spends_in_verlauf(
                    anhang,
                    [{**c, "spent_pending": False} for c in confirmed],
                    wallet=state.wallet_ctx,
                    immutable_cache_dir=state.immutable_cache_dir,
                    own_addresses=_eigene_adressen(state),
                    limit=limit,
                    sort=sort,
                )
        elif confirmed:
            # Kein XPUB: nur aus der Anzeige streichen, kein Cache-Settle.
            conf_keys = {
                f"{str(c.get('txid') or '').lower()}:{int(c.get('vout') or 0)}"
                for c in confirmed
            }
            gecacht = [
                u for u in gecacht
                if f"{str(u.get('txid') or '').lower()}:"
                f"{int(u.get('vout') or 0)}" not in conf_keys
            ]
            anhang = utxos_mod.merge_pending_spends_in_verlauf(
                anhang,
                [{**c, "spent_pending": False} for c in confirmed],
                wallet=state.wallet_ctx,
                immutable_cache_dir=state.immutable_cache_dir,
                own_addresses=_eigene_adressen(state),
                limit=limit,
                sort=sort,
            )
    finally:
        try:
            client.close()
        except Exception:
            pass

    # Auch ohne aktuelle Pending/Confirmed: Cache-Flags bereinigen
    # (Electrs erreichbar, klassifiziere lief durch). Bestätigte Spends
    # sind oben im try/else bereits gesettled.

    # --- Pending: markieren + ausgegeben + eigene Empfänge (Change/Self) ---
    by_key = {
        f"{str(p.get('txid') or '').lower()}:{int(p.get('vout') or 0)}": p
        for p in pending
    }
    empf_keys = {
        f"{str(e.get('txid') or '').lower()}:{int(e.get('vout') or 0)}"
        for e in empfaenge
    }
    markiert: list[dict] = []
    gesehen: set[str] = set()
    for u in gecacht:
        key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        gesehen.add(key)
        p = by_key.get(key)
        if p is None:
            # Veralteter Mempool-Empfang (Tx weg / ersetzt durch frische Liste)
            if u.get("receive_pending") and key not in empf_keys:
                status = u.get("status") or {}
                if not status.get("confirmed") and not status.get("block_height"):
                    continue
            neu = dict(u)
            if neu.get("spending_pending"):
                neu.pop("spending_pending", None)
                neu.pop("spent_txid", None)
            if neu.get("receive_pending") and (
                (neu.get("status") or {}).get("confirmed")
                or (neu.get("status") or {}).get("block_height")
            ):
                neu.pop("receive_pending", None)
            markiert.append(neu)
            continue
        neu = dict(u)
        neu["spending_pending"] = True
        neu["spent_txid"] = p.get("spent_txid") or ""
        stid = str(neu.get("spent_txid") or "").strip().lower()
        if stid and stid in intern_tx:
            neu["spending_internal"] = True
        markiert.append(neu)

    # Pending-Spends, die Light-Tip schon aus dem Cache genommen hat, wieder zeigen.
    for p in pending:
        key = f"{str(p.get('txid') or '').lower()}:{int(p.get('vout') or 0)}"
        if key in gesehen:
            continue
        gesehen.add(key)
        neu = dict(p)
        neu["spending_pending"] = True
        neu.pop("spent", None)
        neu.pop("spent_pending", None)
        stid = str(neu.get("spent_txid") or "").strip().lower()
        if stid and stid in intern_tx:
            neu["spending_internal"] = True
        markiert.append(neu)

    # Selbstüberweisung/Change: unbestätigte eigenen Outputs in den Bestand.
    for e in empfaenge:
        key = f"{str(e.get('txid') or '').lower()}:{int(e.get('vout') or 0)}"
        if key in gesehen:
            continue
        gesehen.add(key)
        markiert.append(dict(e))

    if pending:
        anhang = utxos_mod.merge_pending_spends_in_verlauf(
            anhang,
            pending,
            wallet=state.wallet_ctx,
            immutable_cache_dir=state.immutable_cache_dir,
            own_addresses=_eigene_adressen(state),
            limit=limit,
            sort=sort,
        )
    return markiert, anhang


def _query_flag(query: dict, name: str, *, default: bool = True) -> bool:
    """Query-Flag: fehlt → default; 0/false/off/no → aus, sonst an."""
    roh = (query.get(name) or [None])[0]
    if roh is None or str(roh).strip() == "":
        return default
    return str(roh).strip().lower() not in ("0", "false", "no", "off")


def _empfang_max_index(entry: WalletEntry, state: AppState | None = None) -> int:
    """
    Obergrenze Empfangs-Indizes.

    Basis: Scan-Tiefe/2 (Receive-Kette). Liegt ``scan_end_index`` höher
    (Tip/Fullscan hat weiter gelaufen), die Grenze mitziehen — sonst bleibt
    die „nächste“ Adresse künstlich bei max−1 und Electrs-Schärfung scheitert.
    """
    try:
        tief = int(entry.max_addresses or 0)
    except (TypeError, ValueError):
        tief = 0
    if tief >= 2:
        basis = max(1, tief // 2)
    else:
        basis = main.MAX_TRACE_ADDRESS_SEARCH
    if state is not None:
        try:
            _, scan_end = _cache_bekannt_adressen(state, entry)
            gap = int(getattr(main, "BIP44_GAP_LIMIT", 20) or 20)
            if scan_end > 0:
                basis = max(basis, int(scan_end) + gap + 1)
        except Exception:
            pass
    return max(1, basis)


def _cache_bekannt_adressen(
    state: AppState,
    entry: WalletEntry,
) -> tuple[set[str], int]:
    """Adressen aus UTXO-/Verlaufs-Cache plus ``scan_end_index``."""
    xpub = entry.analyse_schluessel
    bekannt: set[str] = set()
    scan_end = 0
    eintrag = main.load_xpub_cache_entry(xpub, state.cache_dir)
    if eintrag:
        for u in eintrag.get("utxos") or []:
            addr = u.get("address")
            if addr:
                bekannt.add(str(addr))
        roh = eintrag.get("raw") or {}
        for addr in roh.get("scanned_addresses") or []:
            if addr:
                bekannt.add(str(addr))
        try:
            scan_end = int(eintrag.get("scan_end_index") or 0)
        except (TypeError, ValueError):
            scan_end = 0
    for e in main.load_xpub_verlauf_cache(xpub, state.cache_dir) or []:
        addr = e.get("address")
        if addr:
            bekannt.add(str(addr))
    return bekannt, scan_end


def _next_receive_index_from_cache(
    state: AppState,
    entry: WalletEntry,
    *,
    max_index: int,
) -> int:
    """
    Nächste Empfangs-Index-Schätzung: ``max(bekannter Empfangs-Index) + 1``.

    Kein BIP44-Gap ab 0 (der oft fälschlich #0 lieferte, wenn ``scan_end``
    klein war und hohe Indizes gar nicht gematcht wurden). Mit Electrs
    kann die API später nachschärfen — die Cache-Schätzung soll sofort
    und hinter dem höchsten bekannten Empfang liegen.
    """
    bekannt, scan_end = _cache_bekannt_adressen(state, entry)
    if not bekannt and scan_end <= 0:
        return 0

    xpub = entry.analyse_schluessel
    skript = None if entry.is_multisig or entry.descriptor else entry.script_type
    # Volle Scan-Tiefe matchen — nicht nur scan_end+Gap (sonst #0-Falle).
    limit = max(1, min(max_index, max(scan_end + main.BIP44_GAP_LIMIT, max_index)))
    index_fuer: dict[str, int] = {}
    for i in range(limit):
        dest = main.derive_receive_address_at_index(xpub, i, script_type=skript)
        if dest and dest[0]:
            index_fuer[str(dest[0])] = i
        # auto/xpub: zusätzlich alle Skriptformen, falls Cache-Adressen anders typisiert
        if skript in (None, "", "auto") and not entry.descriptor:
            for addr in main.derive_addresses_at_index(xpub, 0, i) or []:
                index_fuer.setdefault(str(addr), i)

    max_used = -1
    for addr in bekannt:
        idx = index_fuer.get(addr)
        if idx is not None:
            max_used = max(max_used, idx)

    if max_used < 0 and bekannt and scan_end > 0:
        # Adressen da, Index-Match fehlgeschlagen — Scan-Ende als Untergrenze.
        return min(scan_end, max_index - 1) if max_index > 0 else 0

    next_index = max_used + 1
    if next_index >= max_index:
        return max(0, max_index - 1)
    return next_index


def _empfang_gehoert_zu_wallet(
    state: AppState,
    entry: WalletEntry,
    address: str,
) -> bool:
    """Belong-Check: Adresse gehört zu diesem Wallet (kein XPUB in der Antwort)."""
    if not address:
        return False
    ctx = state.wallet_ctx
    if ctx is None:
        return True
    xpub = entry.analyse_schluessel
    bekannt = ctx.xpub_for_address(address)
    if bekannt is not None:
        return bekannt == xpub
    label = ctx.resolve_address(address)
    if label is None:
        return False
    return label == entry.display_name or ctx.xpub_for_address(address) == xpub


def _empfang_antwort(
    *,
    kennung: str,
    entry: WalletEntry,
    address: str,
    index: int,
    source: str,
    subscribed: bool,
    watch_active: bool,
    read_only: bool = False,
) -> dict:
    return {
        "wallet_id": kennung,
        "wallet_name": entry.display_name,
        "address": address,
        "index": index,
        "change": 0,
        "source": source,
        "subscribed": subscribed,
        "watch_active": watch_active,
        "read_only": bool(read_only),
    }


def _empfang_finalize(
    state: AppState,
    entry: WalletEntry,
    *,
    kennung: str,
    address: str,
    index: int,
    source: str,
    max_index: int,
) -> dict:
    """Subscribe Gap + Prozess-Cache + Antwort (ohne XPUB)."""
    xpub = entry.analyse_schluessel
    skript = None if entry.is_multisig or entry.descriptor else entry.script_type
    gap = int(getattr(main, "BIP44_GAP_LIMIT", 20) or 20)
    lookahead: list[str] = []
    for i in range(index, min(index + gap + 1, max_index)):
        dest = main.derive_receive_address_at_index(
            xpub, i, script_type=skript,
        )
        if dest and dest[0] and dest[0] not in lookahead:
            lookahead.append(dest[0])

    from core import wallet_watch

    watch = wallet_watch.wallet_watch_status()
    watch_active = bool(watch.get("running"))
    subscribed = False
    if watch_active and lookahead:
        subscribed = bool(
            wallet_watch.subscribe_addresses(lookahead, xpub)
        )

    antwort = _empfang_antwort(
        kennung=kennung,
        entry=entry,
        address=address,
        index=index,
        source=source,
        subscribed=subscribed,
        watch_active=watch_active,
        read_only=False,
    )
    state.empfang_cache[kennung] = dict(antwort)
    return antwort


def _empfang_aus_cache_schaetzung(
    state: AppState,
    entry: WalletEntry,
    *,
    kennung: str,
    max_index: int,
) -> dict:
    """Fallback ohne Electrs: max(bekannter Index)+1 — UI warnt."""
    xpub = entry.analyse_schluessel
    next_index = _next_receive_index_from_cache(
        state, entry, max_index=max_index,
    )
    skript = None if entry.is_multisig or entry.descriptor else entry.script_type
    abgeleitet = main.derive_receive_address_at_index(
        xpub, next_index, script_type=skript,
    )
    if not abgeleitet or not abgeleitet[0]:
        raise ApiError(500, "Empfangsadresse konnte nicht abgeleitet werden.")
    address, index = str(abgeleitet[0]), int(abgeleitet[1])
    # Belong weich: Ableitung kommt vom Wallet-Schlüssel; harter 500 leert das Dock.
    return _empfang_finalize(
        state,
        entry,
        kennung=kennung,
        address=address,
        index=index,
        source="cache_estimate",
        max_index=max_index,
    )


def _seed_wallet_ctx_aus_caches(state: AppState) -> None:
    """UTXO-/Verlauf-/Resolution-Adressen ins Mapping — ohne teure HD-Suche."""
    ctx = state.wallet_ctx
    if ctx is None:
        return
    schluessel = [e.analyse_schluessel for e in state.analyse_entries]
    if not schluessel:
        return
    try:
        main.seed_wallet_addresses_from_utxo_cache(
            ctx, schluessel, state.cache_dir,
        )
    except Exception:
        pass
    try:
        # Verlauf kann weit über max_addresses reichen (Gap-Scan) —
        # ohne Seed hängt /api/utxos an resolve_address × MAX_TRACE.
        main.seed_wallet_addresses_from_verlauf_cache(
            ctx, schluessel, state.cache_dir,
        )
    except Exception:
        pass
    try:
        main.seed_wallet_addresses_from_resolution_cache(ctx, schluessel)
    except Exception:
        pass


def api_sanctions(state: AppState, query: dict) -> dict:
    """Zustand der lokalen Listen — ohne Netzzugriff."""
    return sanctions_mod.status(state.sanctions_dir).as_dict()


def api_sanctions_update(state: AppState, payload: dict) -> dict:
    """Lädt die Listen neu. Läuft als Job, der Download dauert."""

    def lauf(job):
        job.progress("Lade Sanktions- und Blacklists…", log=True)
        import sanctioned

        adressen, meta = sanctioned.update_sanctioned_lists(
            cache_dir=state.sanctions_dir
        )
        job.raise_if_cancelled()
        job.message = f"{len(adressen):,} Adressen geladen.".replace(",", ".")
        return {"adressen": len(adressen)}

    job = state.jobs.start(
        "sanctions",
        "Sanktionslisten aktualisieren",
        lauf,
        meta={"art": "sanctions"},
    )
    return job.as_dict()


def api_labels(state: AppState, query: dict) -> dict:
    """Zustand des Labelbestands — ohne Netzzugriff."""
    return labels.status(state.label_dir)


def api_labels_update(state: AppState, payload: dict) -> dict:
    """Lädt den Labelbestand herunter. Die volle Fassung sind 35 MB."""
    variante = str(payload.get("variante") or "kern")
    if variante not in labels.VARIANTEN:
        raise ApiError(400, f"Unbekannte Variante: {variante}")

    def lauf(job):
        def fortschritt(dateiname: str, geladen: int, gesamt: int) -> None:
            anteil = f" von {gesamt // 1024:,} KB".replace(",", ".") if gesamt else ""
            job.progress(
                f"{dateiname}: {geladen // 1024:,} KB{anteil}".replace(",", ".")
            )

        job.progress("Lade Adress-Labels…", log=True)
        stand = labels.aktualisiere(
            state.label_dir, variante=variante, fortschritt=fortschritt
        )
        job.raise_if_cancelled()
        job.message = (
            f"{stand['adressen']:,} Adressen, davon {stand['benannt']:,} benannt."
            .replace(",", ".")
        )
        return stand

    job = state.jobs.start(
        "labels",
        "Adress-Labels laden",
        lauf,
        meta={"art": "labels", "variante": variante},
    )
    return job.as_dict()


def api_labels_verwerfen(state: AppState, query: dict) -> dict:
    return {"entfernt": labels.verwirf(state.label_dir)}


def _dateien_aus_import_payload(payload: dict) -> dict[str, bytes]:
    """
    Body: ``files`` = [{name, data_b64|text}, …] oder {name: data_b64}.

    Base64 für Binär (Labels); Klartext ``text`` für Wallet-Exporte (CSV/Descriptor),
    damit der Browser große Dateien nicht unnötig base64-kodieren muss.
    """
    import base64

    #: harte Grenze je Datei (Wallet-CSV/Descriptor) — ~25 MiB Rohbytes
    _max_bytes = 25 * 1024 * 1024

    roh = payload.get("files")
    ergebnis: dict[str, bytes] = {}
    if isinstance(roh, dict):
        eintraege = [(str(k), v, None) for k, v in roh.items()]
    elif isinstance(roh, list):
        eintraege = []
        for eintrag in roh:
            if not isinstance(eintrag, dict):
                continue
            name = str(eintrag.get("name") or "").strip()
            if not name:
                continue
            if eintrag.get("text") is not None:
                eintraege.append((name, None, str(eintrag.get("text") or "")))
            else:
                data = eintrag.get("data_b64") or eintrag.get("data") or ""
                eintraege.append((name, data, None))
    else:
        raise ApiError(400, "Feld „files“ fehlt oder ist ungültig.")

    for name, data, text in eintraege:
        name = str(name or "").strip()
        if not name:
            continue
        if text is not None:
            roh_bytes = text.encode("utf-8")
        else:
            if data is None:
                continue
            if not isinstance(data, str):
                raise ApiError(400, f"Datei {name}: data_b64 muss Text sein.")
            try:
                roh_bytes = base64.b64decode(data, validate=False)
            except Exception as exc:
                raise ApiError(400, f"Datei {name}: Base64 ungültig ({exc})") from exc
        if not roh_bytes:
            raise ApiError(400, f"Datei {name} ist leer.")
        if len(roh_bytes) > _max_bytes:
            raise ApiError(
                400,
                f"Datei {name} ist zu groß ({len(roh_bytes) // (1024 * 1024)} MiB, "
                f"max. {_max_bytes // (1024 * 1024)} MiB).",
            )
        # Gleicher Dateiname zweimal (txt+csv selten): Suffix, nicht überschreiben.
        schluessel = name
        if schluessel in ergebnis:
            n = 2
            while f"{name}#{n}" in ergebnis:
                n += 1
            schluessel = f"{name}#{n}"
        ergebnis[schluessel] = roh_bytes
    if not ergebnis:
        raise ApiError(400, "Keine Dateien im Upload.")
    return ergebnis


def api_labels_import(state: AppState, payload: dict) -> dict:
    """Manueller Label-Import (Dateien lokal beschafft)."""
    dateien = _dateien_aus_import_payload(payload)
    variante = payload.get("variante")
    try:
        stand = labels.importiere_dateien(
            dateien,
            state.label_dir,
            variante=str(variante) if variante else None,
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    return stand


def api_exchange_reports(state: AppState, query: dict) -> dict:
    """Status der importierten Börsen-CSV-Reports."""
    from core import exchange_reports as boerse

    return boerse.status(state.exchange_reports_dir)


def api_exchange_reports_import(state: AppState, payload: dict) -> dict:
    """
    Börsen-Transaktionsreport (CSV) einlesen.

    Body: ``name`` (Börse), ``csv`` (Text), optional ``filename``,
    ``ersetzen`` (true = Datei der Börse neu statt mergen).
    Nur BTC-Adressen/TxIDs — Kurse und Shitcoins werden verworfen.
    """
    from core import exchange_reports as boerse

    if not isinstance(payload, dict):
        raise ApiError(400, "JSON-Objekt erwartet.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ApiError(400, "Feld „name“ (Börse) fehlt.")
    csv_text = payload.get("csv")
    if csv_text is None:
        raise ApiError(400, "Feld „csv“ fehlt.")
    if not isinstance(csv_text, str):
        raise ApiError(400, "Feld „csv“ muss Text sein.")
    if len(csv_text) > 40 * 1024 * 1024:
        raise ApiError(400, "CSV zu groß (max. 40 MB).")
    dateiname = str(payload.get("filename") or "").strip()[:200]
    ersetzen = bool(payload.get("ersetzen"))
    try:
        ergebnis = boerse.importiere_csv(
            csv_text,
            name=name,
            filename=dateiname,
            cache_dir=state.exchange_reports_dir,
            ersetzen=ersetzen,
        )
    except boerse.ExchangeReportError as exc:
        raise ApiError(400, str(exc)) from exc
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    ergebnis["status"] = boerse.status(state.exchange_reports_dir)
    return ergebnis


def api_exchange_reports_loesche(state: AppState, query: dict) -> dict:
    """Eine Börse oder alle Reports löschen. Query: ``slug`` oder ``all=1``."""
    from core import exchange_reports as boerse

    if str(query.get("all") or "").strip() in ("1", "true", "yes"):
        n = 0
        for e in boerse.liste(state.exchange_reports_dir):
            if boerse.loesche(str(e.get("slug") or ""), state.exchange_reports_dir):
                n += 1
        return {"geloescht": n, "status": boerse.status(state.exchange_reports_dir)}
    slug = str(query.get("slug") or "").strip()
    if not slug:
        raise ApiError(400, "Query „slug“ oder „all=1“ fehlt.")
    ok = boerse.loesche(slug, state.exchange_reports_dir)
    return {
        "geloescht": 1 if ok else 0,
        "slug": slug,
        "status": boerse.status(state.exchange_reports_dir),
    }


def api_sanctions_import(state: AppState, payload: dict) -> dict:
    """Manueller Sanktionslisten-Import (JSON/TXT/XML/ZIP)."""
    import sanctioned as sanctioned_mod

    dateien = _dateien_aus_import_payload(payload)
    try:
        adressen, meta = sanctioned_mod.importiere_dateien(
            dateien, cache_dir=state.sanctions_dir
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    return {
        "adressen": len(adressen),
        "meta": meta,
        "status": sanctions_mod.status(state.sanctions_dir).as_dict(),
    }


def _sanctions_get_tx_pool(state: AppState):
    """
    (get_tx je Worker, Zahl der Verbindungen) für Sanktionsabfragen.

    Nutzt den eigenen Server, wenn er privat adressiert ist (LAN/Loopback —
    Anfragen nach gelisteten Fremdadressen bleiben im eigenen Netz); sonst
    den öffentlichen Clearnet-Pool. Liefert ``(None, 0)``, wenn nichts
    erreichbar ist.

    Jeder Worker bekommt seinen eigenen Client: Ein Fulcrum-Client ist eine
    einzelne Socket-Verbindung und verträgt keine parallelen Anfragen.
    """
    pool, _quelle, _aus_cache = main.resolve_sanctions_preferred_pool(
        state.env().values()
    )
    if pool is None:
        return None, 0

    def get_tx_je_worker(worker_id: int):
        return main.make_cached_fulcrum_get_tx(
            pool.client_at(worker_id), state.immutable_cache_dir
        )

    return get_tx_je_worker, len(pool)


def api_sanctions_check_ergebnis(state: AppState, query: dict) -> dict:
    """
    Zuletzt gespeichertes Ergebnis der Vorgeschichte-Prüfung.

    Die Oberfläche zeigt es beim Öffnen der Ansicht an, statt jedes Mal
    einen minutenlangen Lauf zu verlangen. ``vorhanden: false`` heißt
    schlicht: noch nie geprüft.
    """
    daten = sanctions_mod.check_ergebnis_laden(state.sanctions_dir)
    if not daten:
        return {"vorhanden": False}
    return {"vorhanden": True, **daten}


def api_sanctions_check_verwerfen(state: AppState) -> dict:
    """Gespeichertes Ergebnis löschen — etwa nach Wallet-Änderungen."""
    return {"geloescht": sanctions_mod.check_ergebnis_verwerfen(state.sanctions_dir)}


def api_sanctions_check(state: AppState, payload: dict) -> dict:
    """
    Prüft Wallet-UTXOs xpub-blind auf sanktionierte Adressen (CLI-Menü 6.1)
    — Drittperspektive ohne XPUB, bis *max_hops* Prevouts — als Job.

    Payload: {"wallet_id": "<kennung|leer=alle>", "max_hops": 3}
    """
    import analyze
    import sanctioned

    wallet_ctx = state.wallet_ctx
    if wallet_ctx is None:
        raise ApiError(400, "Kein gültiges Wallet konfiguriert.")

    kennung = str(payload.get("wallet_id", "")).strip()
    if kennung:
        ziel = wallets_mod.find_entry(state.entries, kennung)
        if ziel is None:
            raise ApiError(404, "Wallet nicht gefunden.")
        ziele = [ziel]
    else:
        ziele = [e for e in state.entries if e.is_valid()]
    if not ziele:
        raise ApiError(400, "Kein gültiges Wallet konfiguriert.")

    try:
        max_hops = int(payload.get("max_hops", 3))
    except (TypeError, ValueError):
        max_hops = 3
    from core.sanctions import clamp_sanktion_max_hops

    max_hops = clamp_sanktion_max_hops(max_hops, default=3)

    eigene = set(wallet_ctx.address_to_wallet)

    def lauf(job):
        adressen, _ = sanctioned.load_sanctioned_xbt_addresses(
            cache_dir=state.sanctions_dir
        )
        if not adressen:
            raise ApiError(
                412,
                "Keine Sanktionslisten vorhanden — bitte zuerst aktualisieren.",
            )

        job.progress("Verbinde mit dem Sanktions-Server…")
        print("Sanktionsprüfung: verbinde Datenquelle…", flush=True)
        get_tx_je_worker, verbindungen = _sanctions_get_tx_pool(state)
        job.raise_if_cancelled()
        if get_tx_je_worker is None:
            raise ApiError(
                503,
                "Kein Fulcrum für Sanktionsabfragen erreichbar — weder der "
                "eigene Server noch ein Clearnet-Server.",
            )
        get_tx = get_tx_je_worker(0)
        print(
            f"Sanktionsprüfung: {verbindungen} Verbindung(en), "
            f"{max_hops} Hop(s), {len(adressen):,} Listen-Adressen."
            .replace(",", "."),
            flush=True,
        )

        ergebnisse = []
        for ziel_entry in ziele:
            job.raise_if_cancelled()
            name = ziel_entry.display_name
            gecacht = utxos_mod.load_cached_utxos(
                ziel_entry.analyse_schluessel,
                state.cache_dir,
                immutable_cache_dir=state.immutable_cache_dir,
            )
            utxos = [
                u for u in (gecacht or [])
                if wallet_ctx.resolve_address(u.get("address", "")) == name
            ]
            if not utxos:
                ergebnisse.append({
                    "wallet": name, "geprueft": 0, "treffer": [],
                    "coinjoins": [],
                    "abgebrochen": False,
                })
                continue

            print(
                f"Sanktionsprüfung „{name}“: {len(utxos)} UTXO(s)…",
                flush=True,
            )

            # Parallel: Statuszeile = zuletzt meldender Worker (nicht „fertig“).
            def fortschritt(felder):
                if job.cancelled:
                    return
                job.progress(
                    f"{name}: {felder.get('status', '')} "
                    f"(UTXO {felder.get('wallet_utxo', '')}, "
                    f"Hop {felder.get('hop', 0)}/{max_hops}, "
                    f"{felder.get('addrs_checked', 0)} Adressen"
                    + (f", {verbindungen} Verbindungen" if verbindungen > 1 else "")
                    + ")"
                )

            gesehen: set[str] = set()
            try:
                treffer, geprueft, abbruch, coinjoins = (
                    analyze.check_wallet_utxos_sanctions(
                        get_tx,
                        utxos,
                        eigene,
                        adressen,
                        max_hops=max_hops,
                        wallet=wallet_ctx,
                        abort_on_hit=False,
                        progress_cb=fortschritt,
                        cancel_cb=lambda: job.cancelled,
                        gesehene_adressen=gesehen,
                        get_tx_je_worker=get_tx_je_worker,
                        worker_count=verbindungen,
                        immutable_cache_dir=state.immutable_cache_dir,
                    )
                )
            except Exception as exc:
                from core.jobs import Cancelled, ist_abbruch

                if job.cancelled or ist_abbruch(exc) or isinstance(exc, Cancelled):
                    treffer, geprueft, abbruch, coinjoins = [], 0, None, []
                else:
                    raise
            job.raise_if_cancelled()
            ergebnisse.append({
                "wallet": name,
                "geprueft": geprueft,
                "treffer": treffer,
                "coinjoins": coinjoins,
                "abgebrochen": abbruch is not None or job.cancelled,
                "adressen_geprueft": len(gesehen),
                # Sortiert und gekappt: die Datei soll auch bei tiefen Läufen
                # lesbar bleiben, und die Reihenfolge stabil, damit zwei
                # Läufe vergleichbar sind.
                "adressen": sorted(gesehen)[
                    :sanctions_mod.CHECK_ADRESSEN_LIMIT
                ],
                "adressen_gekappt": (
                    len(gesehen) > sanctions_mod.CHECK_ADRESSEN_LIMIT
                ),
                "utxos": sorted(
                    f"{u.get('txid', '')}:{u.get('vout')}" for u in utxos
                ),
            })

        gesamt_treffer = sum(len(e["treffer"]) for e in ergebnisse)
        job.message = (
            f"{gesamt_treffer} Treffer in {len(ergebnisse)} Wallet(s) "
            f"({max_hops} Hop(s))."
        )
        ergebnis = {
            "max_hops": max_hops,
            "listen_adressen": len(adressen),
            "wallets": ergebnisse,
            "erstellt_ts": int(time.time()),
            "erstellt": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "vollstaendig": not job.cancelled,
            "verbindungen": verbindungen,
        }
        # Auch ein abgebrochener Lauf wird gespeichert — er ist als
        # unvollständig markiert, und die bereits geprüften Wallets sind
        # mehr wert als eine leere Ansicht.
        ergebnis["gespeichert"] = sanctions_mod.check_ergebnis_speichern(
            state.sanctions_dir, ergebnis
        )
        return ergebnis

    namen = ", ".join(e.display_name for e in ziele)
    job = state.jobs.start(
        "sanctions-check",
        f"Sanktionsprüfung {namen} ({max_hops} Hops)",
        lauf,
        meta={"art": "sanctions-check", "hops": max_hops},
    )
    return job.as_dict()


def api_llm_status(state: AppState, query: dict) -> dict:
    """
    Assistenten-Anbindung: Banner-, Pillen- und Privacy-Felder.

    ``?check=1`` löst eine kurze Erreichbarkeitsprobe aus. Ohne Check bleibt
    die Pille grau (kein Rot-Flash vor dem ersten Versuch). Der API-Key
    kommt nicht in die Antwort.
    """
    check = query.get("check", ["0"])[0] in ("1", "true", "ja")
    return llm_mod.status_dict(state.env().values(), check=check)


def api_price(state: AppState, query: dict) -> dict:
    """
    Aktueller BTC-Spotkurs (Anzeige in der Kopfzeile).

    Keine Wallet-Daten — nur Fiat-Kurs über Mempool (optional eigene
    ``MEMPOOL_URL``) mit Coinbase-Fallback. Ergebnis wird unter
    ``immutable_cache/btc_price/`` kurz gecacht.
    """
    roh = (query.get("currency", ["EUR"])[0] or "EUR").strip()
    try:
        waehrung = price_mod.normalisiere_waehrung(roh)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    mempool = (state.env().values().get("MEMPOOL_URL") or "").strip() or None
    try:
        # Kurzes Timeout: die Kopfzeile soll den Start nicht aufhalten.
        preis = price_mod.spot_preis(
            waehrung,
            immutable_cache_dir=state.immutable_cache_dir,
            mempool_url=mempool,
            timeout=5.0,
        )
    except price_mod.PriceError as exc:
        raise ApiError(502, str(exc)) from exc
    return preis.to_dict()


def api_price_history(state: AppState, query: dict) -> dict:
    """Stand der lokalen BTC-Tageskurs-Historie (EUR/USD).

    ``?series=1`` liefert zusätzlich die Tag→Preis-Map (für EUR-Umrechnung
    ausgegebener Beträge zum Ausgabedatum).
    """
    from core import price_history_sync as hist_sync

    mit_serie = (query.get("series", ["0"])[0] or "").strip().lower() in (
        "1", "true", "ja", "yes", "on",
    )
    werte = state.env().values()
    roh = (query.get("currency", [""])[0] or "").strip()
    if roh:
        return {
            "histories": [
                price_mod.historie_status(
                    state.immutable_cache_dir, roh, mit_serie=mit_serie,
                ),
            ],
            "price_history_opt_in": True,
        }
    return {
        "histories": [
            price_mod.historie_status(
                state.immutable_cache_dir, w, mit_serie=mit_serie,
            )
            for w in sorted(price_mod.HISTORIE_WAEHRUNGEN)
        ],
        "price_history_opt_in": True,
    }


def api_price_history_sync(state: AppState, payload: dict | None = None) -> dict:
    """Manueller Historie-Nachzug (Lücken füllen — Bitstamp/CDD, sonst Mempool)."""
    from core import price_history_sync as hist_sync

    _ = payload  # früher opt_in — Nachzug braucht keine Erlaubnis mehr
    logs: list[str] = []
    # Manueller API-Lauf: Tages-Stamp ignorieren, immer versuchen.
    ergebnisse = hist_sync.historie_nachziehen_alle(
        state.immutable_cache_dir,
        values=state.env().values(),
        on_log=logs.append,
        force=True,
    )
    for zeile in logs:
        print(zeile, flush=True)
    return {
        "ok": all(e.get("ok") for e in ergebnisse),
        "results": ergebnisse,
        "log": logs,
        "price_history_opt_in": True,
        "histories": [
            price_mod.historie_status(state.immutable_cache_dir, w)
            for w in sorted(price_mod.HISTORIE_WAEHRUNGEN)
        ],
    }


def starte_historie_nachzug_taeglich(
    state: AppState,
    *,
    warte_sekunden: float = 45.0,
) -> None:
    """Lücken-Check erst *nach* GUI-Start — nicht während Splash/Verbindungsaufbau.

    Einmal pro Prozess; wartet ``warte_sekunden``, damit Browser und
    Datenquellen-Pillen stehen, bevor Bitstamp ggf. gezogen wird.
    """
    import threading

    if getattr(state, "_historie_sync_gestartet", False):
        return
    state._historie_sync_gestartet = True  # type: ignore[attr-defined]

    def _lauf() -> None:
        import time as _time

        from core import price_history_sync as hist_sync

        _time.sleep(max(0.0, float(warte_sekunden)))
        try:
            hist_sync.historie_nachziehen_alle(
                state.immutable_cache_dir,
                values=state.env().values(),
                on_log=lambda t: print(t, flush=True),
                force=False,
            )
        except Exception as exc:
            print(f"Kurs-Historie-Nachzug: {exc}", flush=True)

    threading.Thread(
        target=_lauf, name="satsage-price-history-sync", daemon=True,
    ).start()


def api_price_import(state: AppState, payload: dict) -> dict:
    """
    CSV-Tageskurse (Datum/Preis) in den Kurs-Cache schreiben.

    Body: ``currency`` (EUR|USD), ``csv`` (Text), optional ``filename``,
    ``ersetzen`` (true = Serie verwerfen statt mergen).
    """
    if not isinstance(payload, dict):
        raise ApiError(400, "JSON-Objekt erwartet.")
    roh_w = str(payload.get("currency") or "EUR")
    try:
        waehrung = price_mod.normalisiere_historie_waehrung(roh_w)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    csv_text = payload.get("csv")
    if csv_text is None:
        raise ApiError(400, "Feld „csv“ fehlt.")
    if not isinstance(csv_text, str):
        raise ApiError(400, "Feld „csv“ muss Text sein.")
    if len(csv_text) > 20 * 1024 * 1024:
        raise ApiError(400, "CSV zu groß (max. 20 MB).")
    dateiname = str(payload.get("filename") or "").strip()[:200]
    ersetzen = bool(payload.get("ersetzen"))
    try:
        ergebnis = price_mod.importiere_kurs_csv(
            state.immutable_cache_dir,
            waehrung,
            csv_text,
            dateiname=dateiname,
            ersetzen=ersetzen,
        )
    except price_mod.PriceError as exc:
        raise ApiError(400, str(exc)) from exc
    return ergebnis


def api_llm_context(state: AppState, rest: list[str], query: dict) -> dict:
    """
    Reine Cache-Reader für Slash-Befehle.

    Kein Job, kein Node, kein Chat-Completion. Unbekannte Unterpfade 404.
    """
    if not rest:
        raise ApiError(404, "Welcher Kontext? luecken, wallets, steuer, export.")
    ziel = rest[0]
    if ziel == "luecken":
        return llm_ctx.luecken(
            entries=state.analyse_entries,
            cache_dir=state.cache_dir,
            immutable_dir=state.immutable_cache_dir,
            jobs=state.jobs,
        )
    if ziel == "wallets":
        return llm_ctx.wallets(
            entries=state.analyse_entries,
            cache_dir=state.cache_dir,
            immutable_dir=state.immutable_cache_dir,
        )
    if ziel == "steuer":
        return llm_ctx.steuer_kompakt(_steuer_auswertung(state, query))
    if ziel == "export":
        art = (query.get("art") or ["legende"])[0].strip().lower()
        if art not in llm_ctx.EXPORT_ARTEN:
            raise ApiError(400, "art muss legende, markdown oder brief sein.")
        return llm_ctx.export_aus(_steuer_auswertung(state, query), art)
    raise ApiError(404, f"Unbekannter Assistenten-Kontext: {ziel}")


def _llm_werkzeug(state: AppState, name: str, args: dict) -> str:
    """Cache-Reader für den Chat — dieselben Texte wie die Slash-Befehle."""
    args = args or {}
    if name == "luecken":
        return llm_ctx.luecken(
            entries=state.analyse_entries,
            cache_dir=state.cache_dir,
            immutable_dir=state.immutable_cache_dir,
            jobs=state.jobs,
        )["text"]
    if name == "wallets":
        return llm_ctx.wallets(
            entries=state.analyse_entries,
            cache_dir=state.cache_dir,
            immutable_dir=state.immutable_cache_dir,
        )["text"]
    query: dict[str, list[str]] = {}
    jahr = args.get("jahr")
    if jahr not in (None, ""):
        query["jahr"] = [str(jahr)]
    if name == "steuer":
        return llm_ctx.steuer_kompakt(_steuer_auswertung(state, query))["text"]
    if name in ("export", "export_legende", "export_markdown", "export_brief"):
        art = str(args.get("art") or "").strip().lower()
        if not art:
            art = {
                "export_legende": "legende",
                "export_markdown": "markdown",
                "export_brief": "brief",
            }.get(name, "legende")
        return llm_ctx.export_aus(_steuer_auswertung(state, query), art)["text"]
    return f"Werkzeug „{name}“ ist nicht erlaubt."


def api_llm_chat(state: AppState, payload: dict) -> dict:
    """
    Eine Freitext-Runde. Remote nur mit Opt-in und Key aus der .env.

    Der Client schickt nur user/assistant-Nachrichten. Systemprompt und
    Werkzeuge setzt der Server. Kein Job-Start.
    """
    if not isinstance(payload, dict):
        raise ApiError(400, "Ungültiger Körper.")
    cfg = llm_mod.lese_llm_chat_einstellungen(state.env().values())
    try:
        return llm_chat.fuehre_chat(
            cfg,
            payload.get("messages"),
            tools_fn=lambda name, args: _llm_werkzeug(state, name, args),
        )
    except llm_chat.LlmFehler as exc:
        raise ApiError(exc.status, exc.message) from exc


def _persist_tls_auto(state: AppState, quellen: list, *, on_log=None) -> list:
    """
    Schreibt TLS-Auto-Ergebnis (FULCRUM_SSL / FULCRUM_TOR_SSL) in die .env.

    Nur Desktop/.env — nicht Start9/Umbrel-Bridge. Liefert Quellenliste mit
    aktualisierten Schalter-Feldern und geleertem ssl_persist.
    """
    from dataclasses import replace

    if state.managed_by in _NODE_MANAGED:
        return quellen
    erlaubt = source_mod.EDITIERBARE_FELDER.get("own_fulcrum", ())
    persist: dict[str, str | None] = {}
    for q in quellen:
        if q.key != "own_fulcrum" or not q.ssl_persist:
            continue
        for k, v in q.ssl_persist.items():
            if k in erlaubt:
                persist[k] = v
    if not persist:
        return quellen
    try:
        env = state.env()
        env.apply(persist)
        env.save()
        state.reload()
    except OSError:
        return quellen
    if on_log:
        bits = ", ".join(f"{k}={v}" for k, v in persist.items())
        on_log(f"TLS-Einstellung gespeichert: {bits}")
    werte = state.env().values()
    frisch = {q.key: q for q in source_mod.describe_sources(werte)}
    out: list = []
    for q in quellen:
        basis = frisch.get(q.key, q)
        out.append(
            replace(
                basis,
                reachable=q.reachable,
                error=q.error,
                peer_count=q.peer_count,
                peer_hosts=list(q.peer_hosts),
                software=q.software,
                software_raw=q.software_raw,
                ssl_effective=q.ssl_effective,
                ssl_persist={},
                note=q.note or basis.note,
                detail=q.detail or basis.detail,
                log=list(q.log),
            )
        )
    return out


def _live_p2p_peers() -> list[str]:
    """Gerade offene Compact-Filter-Peers (Tip-Sync / Scan)."""
    try:
        from bip158_scanner import live_filter_peer_hosts

        return live_filter_peer_hosts()
    except Exception:
        return []


def _breche_p2p_jobs_ab(state: AppState) -> list[str]:
    """
    Bricht laufende/geplante Jobs ab, die über BIP-158/P2P hängen.

    Aufruf beim Papierkorb „P2P trennen“ — Nutzer startet Electrum/Scan selbst.
    """
    abgebrochen: list[str] = []
    gesehen: set[str] = set()

    def _merk(jid: str | None) -> None:
        j = str(jid or "").strip()
        if j and j not in gesehen:
            gesehen.add(j)
            abgebrochen.append(j)

    # Header-Vorab ist immer P2P.
    hid = getattr(state, "header_job_id", None)
    if hid and (state.scan_queue.cancel(hid) or state.jobs.cancel(hid)):
        _merk(hid)
    state.header_job_id = None

    # Scan-Pipeline: aktiver Job + Warteschlange (sonst startet der nächste
    # Eintrag noch mit der alten P2P-Priorität).
    try:
        snap = state.scan_queue.snapshot()
    except Exception:
        snap = {"current": None, "queued": []}
    cur = snap.get("current") or {}
    jid = cur.get("job_id")
    if jid and state.scan_queue.cancel(jid):
        _merk(jid)
    for eintrag in snap.get("queued") or []:
        qid = eintrag.get("queue_id")
        if qid and state.scan_queue.cancel(qid):
            _merk(qid)

    # Laufende Registry-Jobs: Header/Rescan/Verlauf; wallet_sync nur mit
    # bekannter BIP-158-Quelle (sonst Electrs-Tip-Sync nicht killen).
    for job in state.jobs.list():
        if job.status != "running":
            continue
        if job.id in gesehen:
            continue
        src = (job.meta or {}).get("source")
        if job.kind == "headers" or job.kind in ("rescan", "verlauf"):
            if state.jobs.cancel(job.id) or state.scan_queue.cancel(job.id):
                _merk(job.id)
        elif job.kind == "wallet_sync" and src == "bip158":
            if state.jobs.cancel(job.id):
                _merk(job.id)

    return abgebrochen


def _alle_gecachten_utxos(state: AppState) -> list[dict]:
    """UTXOs aller Wallets aus dem Cache — ohne Netzzugriff."""
    gesammelt: list[dict] = []
    for entry in state.entries:
        gecacht = utxos_mod.load_cached_utxos(
            entry.analyse_schluessel,
            state.cache_dir,
            immutable_cache_dir=state.immutable_cache_dir,
        )
        if gecacht:
            gesammelt.extend(gecacht)
    return gesammelt


def _alle_gecachten_verlaeufe(state: AppState) -> list[dict]:
    """
    Vollständiger Verlauf aller Wallets aus dem Cache — auch ausgegebene
    Outputs. Leer, solange er nicht erhoben wurde.
    """
    gesammelt: list[dict] = []
    for entry in state.analyse_entries:
        eintraege = main.load_xpub_verlauf_cache(entry.analyse_schluessel, state.cache_dir)
        if eintraege:
            gesammelt.extend(eintraege)
    return gesammelt


def _utxo_schluessel(eintrag: dict) -> tuple[str, int] | None:
    txid = str(eintrag.get("txid") or "").strip().lower()
    if not txid:
        return None
    try:
        vout = int(eintrag.get("vout", 0))
    except (TypeError, ValueError):
        return None
    return (txid, vout)


def _steuer_verlauf_ohne_phantom_unspent(
    verlauf: list[dict],
    bestand: list[dict] | None,
) -> tuple[list[dict], int]:
    """
    Verlauf für Steuer: echte Abgänge behalten, Phantom-„unspent“ streichen.

    Phantom = im Verlauf ``spent`` falsch/fehlend (wirkt unspent), aber
    ``txid:vout`` steht nicht (mehr) im aktuellen UTXO-Cache — typisch nach
    Konsolidierung/Ausgaben, wenn der Verlauf ``spent`` nicht gesetzt hat.
    Ohne UTXO-Cache kein Abgleich möglich → Verlauf unverändert.
    """
    if not bestand:
        return list(verlauf), 0
    live = set()
    for u in bestand:
        key = _utxo_schluessel(u)
        if key:
            live.add(key)
    gefiltert: list[dict] = []
    phantome = 0
    gesehen: set[tuple[str, int]] = set()
    for eintrag in verlauf:
        key = _utxo_schluessel(eintrag)
        if eintrag.get("spent"):
            gefiltert.append(eintrag)
            if key:
                gesehen.add(key)
            continue
        if key is None:
            continue
        if key in live:
            gefiltert.append(eintrag)
            gesehen.add(key)
        else:
            phantome += 1
    # UTXOs, die der Verlauf noch nicht kennt (frischer Empfang).
    for u in bestand:
        key = _utxo_schluessel(u)
        if key is None or key in gesehen:
            continue
        neu = dict(u)
        neu.setdefault("spent", False)
        gefiltert.append(neu)
        gesehen.add(key)
    return gefiltert, phantome


def _steuer_grundlage(state: AppState) -> tuple[list[dict], list[str]]:
    """
    Woraus die Steuerauswertung rechnet — **je Wallet** entschieden.

    Der Verlauf gewinnt, wo er vorliegt (Abgänge + Empfänge). Unspent-Zeilen
    aus dem Verlauf, die nicht im aktuellen UTXO-Cache stehen, werden als
    Phantom verworfen. Wo kein Verlauf da ist, bleibt der UTXO-Bestand.

    Die Entscheidung darf nicht global fallen. Sonst verschwänden alle Wallets
    ohne Verlauf aus der Aufstellung, sobald ein einziges einen hat — in einer
    Steuerangabe ein stiller Verlust, den niemand bemerkt.

    Liefert *(eintraege, wallets_ohne_verlauf)*; die zweite Liste gehört in die
    Anzeige, damit eine gemischte Grundlage auffällt.
    """
    # Verlaufsadressen vor resolve_address (sonst HD-Suche × MAX_TRACE).
    _seed_wallet_ctx_aus_caches(state)

    eintraege: list[dict] = []
    ohne_verlauf: list[str] = []
    phantome_gesamt = 0

    for entry in state.analyse_entries:
        schluessel = entry.analyse_schluessel
        verlauf = main.load_xpub_verlauf_cache(schluessel, state.cache_dir)
        gecacht = utxos_mod.load_cached_utxos(
            schluessel,
            state.cache_dir,
            immutable_cache_dir=state.immutable_cache_dir,
        )
        if verlauf:
            bereinigt, phantome = _steuer_verlauf_ohne_phantom_unspent(
                verlauf, gecacht,
            )
            phantome_gesamt += phantome
            eintraege.extend(bereinigt)
            continue
        # Auch bei leerem Verlauf: Eine leere Liste kann ein abgebrochener
        # Lauf sein. Sie als „dieses Wallet ist leer" zu lesen wäre falsch.
        ohne_verlauf.append(entry.display_name)
        if gecacht:
            eintraege.extend(gecacht)

    if phantome_gesamt and hasattr(state, "_steuer_phantome"):
        state._steuer_phantome = phantome_gesamt
    else:
        try:
            state._steuer_phantome = phantome_gesamt  # type: ignore[attr-defined]
        except Exception:
            pass

    return eintraege, ohne_verlauf


def _steuer_auswertung(state: AppState, query: dict) -> dict:
    utxos, ohne_verlauf = _steuer_grundlage(state)
    jahre = tax_mod.verfuegbare_jahre(utxos)

    try:
        jahr = int(query.get("jahr", [""])[0])
    except (ValueError, TypeError, IndexError):
        jahr = jahre[0] if jahre else __import__("datetime").date.today().year

    einstellungen = tax_mod.lese_steuer_einstellungen(state.env().values())
    try:
        frist = int(query.get("frist", [""])[0])
    except (ValueError, TypeError, IndexError):
        frist = einstellungen["haltefrist_jahre"]

    stichtag_roh = query.get("stichtag", [None])[0]
    if stichtag_roh is None:
        stichtag = tax_mod.parse_stichtag(einstellungen["stichtag"])
    else:
        try:
            stichtag = tax_mod.parse_stichtag(stichtag_roh)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc

    anschaffung_roh = query.get("anschaffung", [None])[0]
    if anschaffung_roh is None:
        anschaffung = einstellungen["anschaffung"]
    else:
        anschaffung = tax_mod.parse_anschaffung(anschaffung_roh)

    auswertung = tax_mod.auswerten(
        utxos, jahr,
        haltefrist_jahre=max(0, frist),
        stichtag=stichtag,
        anschaffung=anschaffung,
        wallet=state.wallet_ctx,
        immutable_cache_dir=state.immutable_cache_dir,
    )
    auswertung["verfuegbare_jahre"] = jahre
    auswertung["ohne_verlauf"] = ohne_verlauf
    phantome = int(getattr(state, "_steuer_phantome", 0) or 0)
    auswertung["phantom_unspent_count"] = phantome
    if phantome:
        auswertung["hinweise"].insert(0, (
            f"{phantome} Verlaufs-Einträge wirkten unspent, fehlen aber im "
            "aktuellen UTXO-Bestand (Phantom) — für „Bestand gesamt“ ignoriert. "
            "Verlaufsscan erneut aktualisiert spent-Flags."
        ))
    if ohne_verlauf:
        # Eine gemischte Grundlage muss auffallen: Für die einen Wallets sind
        # Veräußerungen erfasst, für die anderen nur der heutige Bestand.
        auswertung["hinweise"].insert(0, (
            "Für " + ", ".join(f"„{name}“" for name in ohne_verlauf)
            + (" liegt" if len(ohne_verlauf) == 1 else " liegen")
            + " kein Verlauf vor — dort zählt nur der heutige Bestand, "
            "bereits ausgegebene Beträge fehlen. „Verlaufsscan“ in der "
            "Wallet-Ansicht oder „Verlauf aller Wallets“ schließt die Lücke."
        ))
    return auswertung


def api_tax(state: AppState, query: dict) -> dict:
    auswertung = _steuer_auswertung(state, query)
    auswertung.pop("_objekte", None)
    return auswertung


def api_selbstanzeige_kandidaten(state: AppState, query: dict) -> dict:
    from core import selbstanzeige as sa

    utxos, _ohne = _steuer_grundlage(state)
    try:
        jahr = int(query.get("jahr", [""])[0])
    except (ValueError, TypeError, IndexError):
        jahre = tax_mod.verfuegbare_jahre(utxos)
        jahr = jahre[0] if jahre else __import__("datetime").date.today().year
    txid = (query.get("txid", [""])[0] or "").strip() or None
    try:
        return sa.kandidaten(
            utxos,
            jahr,
            wallet=state.wallet_ctx,
            immutable_cache_dir=state.immutable_cache_dir,
            txid=txid,
        )
    except ValueError as exc:
        # z. B. ungültige TxID im Filterfeld
        raise ApiError(400, str(exc)) from exc


def _selbstanzeige_report(state: AppState, payload: dict) -> dict:
    from core import selbstanzeige as sa

    utxos, _ohne = _steuer_grundlage(state)
    try:
        jahr = int(payload.get("jahr") or 0)
    except (TypeError, ValueError):
        jahr = 0
    if jahr <= 0:
        jahre = tax_mod.verfuegbare_jahre(utxos)
        jahr = jahre[0] if jahre else __import__("datetime").date.today().year
    einstellungen = tax_mod.lese_steuer_einstellungen(state.env().values())
    try:
        frist = int(payload.get("haltefrist_jahre", einstellungen["haltefrist_jahre"]))
    except (TypeError, ValueError):
        frist = einstellungen["haltefrist_jahre"]
    txids = payload.get("txids") or []
    if not isinstance(txids, list):
        raise ApiError(400, "txids muss eine Liste sein.")
    utxo_keys = payload.get("utxos") or []
    if not isinstance(utxo_keys, list):
        raise ApiError(400, "utxos muss eine Liste sein.")
    # TxIDs sanft normalisieren — ungültige → 400 statt Traceback 500
    saubere_txids: list[str] = []
    for roh in txids:
        text = str(roh or "").strip()
        if not text:
            continue
        try:
            saubere_txids.append(sa._norm_txid(text, strict=True))
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
    try:
        report = sa.auswerten(
            utxos,
            jahr,
            saubere_txids,
            haltefrist_jahre=max(0, frist),
            anschaffung=einstellungen.get(
                "anschaffung", tax_mod.STANDARD_ANSCHAFFUNG
            ),
            wallet=state.wallet_ctx,
            immutable_cache_dir=state.immutable_cache_dir,
            utxo_keys=[str(u) for u in utxo_keys],
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    report["person"] = sa.lese_steuer_person(state.env().values())
    return report


def _ingress_veraltet(eintrag: dict | None) -> bool:
    """
    Sagt, ob ein UTXO (noch einmal) verfolgt werden muss.

    Einträge aus der Zeit vor dem externen Anschaffungsdatum kennen den
    Schlüssel ``external_time_ts`` gar nicht. Sie ergäben im Steuerjahr
    dauerhaft „nur Wallet-Eingang", obwohl ein neuer Lauf das genaue Datum
    liefern könnte — sie gelten deshalb als offen.

    Ein Eintrag *mit* dem Schlüssel, aber ohne Wert, ist dagegen fertig: Dort
    hat die Datenquelle keine Blockzeiten der Vorgänger hergegeben, und ein
    weiterer Lauf brächte dasselbe Ergebnis.
    """
    if not eintrag:
        return True
    return "external_time_ts" not in eintrag


def _utxos_fuer_trace(
    state: AppState,
    *,
    wallet_id: str = "",
) -> list[dict]:
    """UTXOs aus dem Cache, optional auf ein Wallet gefiltert."""
    kennung = (wallet_id or "").strip()
    if not kennung:
        return list(_alle_gecachten_utxos(state))
    entry = wallets_mod.find_entry(state.entries, kennung)
    if entry is None or not entry.is_valid():
        raise ApiError(404, "Wallet nicht gefunden.")
    gecacht = utxos_mod.load_cached_utxos(
        entry.analyse_schluessel,
        state.cache_dir,
        immutable_cache_dir=state.immutable_cache_dir,
    )
    return list(gecacht or [])


def _trace_offen_steuer(
    state: AppState,
    utxos: list[dict],
    eigene_jetzt,
) -> list[tuple[str, int]]:
    """
    UTXOs ohne steuerlich ausreichenden Herkunftsbaum.

    Reicht: Blätter extern/Coinbase **oder** Steuer-Horizont (vor Stichtag/
    Haltefrist-Anfang). Volle Graphen bis Coinbase sind nicht nötig.
    """
    offen: list[tuple[str, int]] = []
    gesehen: set[tuple[str, int]] = set()
    for utxo in utxos:
        txid = str(utxo.get("txid") or "").strip()
        if not txid:
            continue
        try:
            vout = int(utxo.get("vout", 0))
        except (TypeError, ValueError):
            continue
        key = (txid, vout)
        if key in gesehen:
            continue
        gesehen.add(key)
        kopf = trace_cache.kopf(
            txid, vout, state.immutable_cache_dir, eigene_jetzt
        )
        if kopf is None:
            # Kein Baum: alter Ingress mit Extern reicht für Steuerjahr.
            if not _ingress_veraltet(
                main.load_utxo_ingress_cache(
                    txid, vout, state.immutable_cache_dir
                )
            ):
                continue
            offen.append(key)
            continue
        if kopf.get("veraltet"):
            offen.append(key)
            continue
        if kopf.get("vollstaendig") or kopf.get("steuer_ausreichend"):
            continue
        offen.append(key)
    return offen


def _trace_offen_basis(
    state: AppState,
    utxos: list[dict],
    eigene_jetzt,
) -> list[tuple[str, int]]:
    """
    Herkunft tracen: UTXOs ohne **vollen** Baum bis extern/Coinbase.

    Steuer-Horizont allein reicht nicht — diese Lücken werden nachgezogen,
    idealerweise auf dem gespeicherten origin_tree (kein Komplett-Neulauf).
    """
    offen: list[tuple[str, int]] = []
    gesehen: set[tuple[str, int]] = set()
    for utxo in utxos:
        txid = str(utxo.get("txid") or "").strip()
        if not txid:
            continue
        try:
            vout = int(utxo.get("vout", 0))
        except (TypeError, ValueError):
            continue
        key = (txid, vout)
        if key in gesehen:
            continue
        gesehen.add(key)
        kopf = trace_cache.kopf(
            txid, vout, state.immutable_cache_dir, eigene_jetzt
        )
        if kopf is None:
            offen.append(key)
            continue
        if kopf.get("veraltet"):
            offen.append(key)
            continue
        if kopf.get("vollstaendig"):
            continue
        offen.append(key)
    return offen


def _trace_offen_tief(
    state: AppState,
    utxos: list[dict],
    eigene_jetzt,
) -> list[tuple[str, int]]:
    """
    UTXOs ohne vollständigen Baum (rot/lila-Blätter) — auch wenn schon
    einmal getraced. Veraltete Bäume und fehlender Ingress ebenso.
    """
    # Gleicher Maßstab wie Herkunft-tracen-Massenlauf (voll bis extern).
    return _trace_offen_basis(state, utxos, eigene_jetzt)


def _stop_before_ts_aus_payload(roh: dict) -> int | None:
    """Steuer-Horizont aus Job-Payload (Jahr, Haltefrist, Stichtag)."""
    try:
        jahr = int(roh.get("jahr") or 0)
    except (TypeError, ValueError):
        jahr = 0
    if jahr < 2009:
        from datetime import datetime as _dt
        jahr = _dt.now().year
    try:
        frist = int(
            roh.get("haltefrist_jahre")
            if roh.get("haltefrist_jahre") is not None
            else roh.get("frist") or tax_mod.STANDARD_HALTEFRIST_JAHRE
        )
    except (TypeError, ValueError):
        frist = tax_mod.STANDARD_HALTEFRIST_JAHRE
    stichtag_roh = roh.get("stichtag") or roh.get("stichtag_iso") or ""
    stichtag_tag = tax_mod.parse_stichtag(
        str(stichtag_roh) if stichtag_roh else None
    )
    return tax_mod.stop_before_ts_fuer_steuer(jahr, frist, stichtag_tag)


def _trace_ein_utxo_tief(
    *,
    get_tx,
    txid: str,
    vout: int,
    eigene: set,
    wallet_ctx,
    cache_dir,
    immutable_cache_dir,
    fetch_addr,
    cache_source: str,
    progress=None,
    cancel_cb=None,
    folge_bundled: bool = True,
    folge_tx: bool = True,
    resume_origin: dict | None = None,
) -> dict:
    """
    Ein UTXO wie „Herkunftslücken schließen“ (followup=full):

    1. Roh-Trace mit allen eigenen Eingängen (große Sammel-Txs),
       oder Resume aus ``resume_origin`` (nur Lücken)
    2. optional eigene Vorgänger-Txs nachverfolgen (Cache/Adressen warm)
    3. UI-Baum speichern mit resolve_bundled

    Wird vom Einzel-Trace und von „Herkunft vollständig“ genutzt — sonst
    bliebe der Superscan hinter dem Lücken-Knopf zurück.

    *progress* und *cancel_cb* müssen greifen — sonst hängt Phase 1/2 ohne
    Log und Abbruch (bare except in der Engine schluckte Cancelled früher).
    """
    import contextlib
    import io

    log = progress if callable(progress) else (lambda _m: None)
    abbruch = cancel_cb if callable(cancel_cb) else None
    # analyze.trace_utxo_origin erwartet .update(text); Jobs liefern Callables.
    fortschritt = (
        trace_mod._FortschrittsAdapter(progress) if callable(progress) else None
    )

    def _check_abbruch() -> None:
        if abbruch and abbruch():
            raise Cancelled()

    if folge_tx or folge_bundled:
        _check_abbruch()
        if folge_bundled:
            log("Lücken: eigene Eingänge großer Sammel-Txs nachziehen…")
        else:
            log("Folgeanalyse: erst Herkunft, dann Vorgänger…")
        # Fortschritt/Abbruch hier mitgeben — Phase 1 war sonst stumm und
        # unabbrechbar (CoinJoin/Remix: Minuten ohne job.progress).
        if (
            resume_origin
            and isinstance(resume_origin, dict)
            and analyze.hat_brauchbaren_teilfortschritt(resume_origin)
        ):
            log("Setze gespeicherten Teilbaum fort…")
            roh = analyze.vertiefe_herkunft_luecken(
                resume_origin,
                get_tx,
                eigene,
                wallet=wallet_ctx,
                cache_dir=cache_dir,
                fetch_address_utxos=fetch_addr,
                cache_source=cache_source,
                progress=fortschritt,
                alle_eigenen_inputs=folge_bundled,
            )
        else:
            roh = analyze.trace_utxo_origin(
                get_tx,
                txid,
                vout,
                eigene,
                wallet=wallet_ctx,
                cache_dir=cache_dir,
                fetch_address_utxos=fetch_addr,
                cache_source=cache_source,
                progress=fortschritt,
                alle_eigenen_inputs=folge_bundled,
            )
        _check_abbruch()
        if folge_tx:
            vorgaenger: set[str] = set()
            if roh:
                analyze._collect_internal_creator_txs(roh, vorgaenger)
            log(
                f"Eigene Vorgänger-Txs weiterverfolgen "
                f"({len(vorgaenger)})…"
            )
            if vorgaenger:
                buf = io.StringIO()

                def _log_zeilen() -> None:
                    text = buf.getvalue()
                    if not text:
                        return
                    buf.seek(0)
                    buf.truncate(0)
                    for zeile in text.splitlines():
                        zeile = zeile.strip()
                        if zeile:
                            log(zeile)

                def _folge_fortschritt(text: str) -> None:
                    _check_abbruch()
                    _log_zeilen()
                    log(str(text or ""))

                with contextlib.redirect_stdout(buf):
                    analyze._run_tx_oriented_followups(
                        get_tx,
                        vorgaenger,
                        txid,
                        eigene,
                        set(),
                        0,
                        wallet_ctx,
                        cache_dir,
                        fetch_addr,
                        cache_source,
                        cancel_cb=abbruch,
                        progress_cb=_folge_fortschritt,
                    )
                _log_zeilen()
        _check_abbruch()
        log("Aktualisiere Herkunftsbaum…")

    ergebnis = trace_mod.trace_utxo(
        get_tx,
        txid,
        vout,
        eigene,
        wallet=wallet_ctx,
        cache_dir=cache_dir,
        immutable_cache_dir=immutable_cache_dir,
        fetch_address_utxos=fetch_addr,
        cache_source=cache_source,
        progress=progress if callable(progress) else None,
        resolve_bundled=folge_bundled,
        merke_tx_oriented_done=folge_tx,
        resume_origin=resume_origin,
    )
    return ergebnis


def _wallet_name_fuer_utxo(
    state: AppState,
    txid: str,
    vout: int,
    *,
    hinweis: str = "",
) -> str:
    """
    Anzeigename des Wallets zu txid:vout — für Job-Meta und UI nach Reload.

    Reihenfolge: Client-Hinweis → gespeicherter Trace-Root → UTXO-Cache-Adresse
    → Adressauflösung im Wallet-Kontext.
    """
    name = str(hinweis or "").strip()
    if name:
        return name
    try:
        treffer = trace_cache.laden(
            txid, vout, state.immutable_cache_dir, None,
        )
        if treffer:
            root = (treffer.get("baum") or {}).get("root") or {}
            w = str(root.get("wallet") or "").strip()
            if w:
                return w
            addr = str(root.get("address") or "").strip()
            ctx = state.wallet_ctx
            if addr and ctx is not None:
                w = str(ctx.resolve_address(addr) or "").strip()
                if w:
                    return w
    except Exception:
        pass
    try:
        ctx = state.wallet_ctx
        if ctx is None:
            return ""
        for entry in state.entries or []:
            schluessel = getattr(entry, "analyse_schluessel", None) or getattr(
                entry, "xpub", None,
            )
            if not schluessel:
                continue
            cached = main.load_xpub_utxo_cache(schluessel, state.cache_dir) or []
            for u in cached:
                if (
                    str(u.get("txid") or "").lower() == str(txid).lower()
                    and int(u.get("vout") or -1) == int(vout)
                ):
                    addr = str(u.get("address") or "").strip()
                    if addr:
                        w = str(ctx.resolve_address(addr) or "").strip()
                        if w:
                            return w
                    return str(entry.display_name or "").strip()
    except Exception:
        pass
    return ""


# Job-API: Domänenmodul (Modularisierung Slice 1). Öffentliche Namen bleiben.
from httpserver.api.jobs import (  # noqa: E402
    api_cancel_job,
    api_job,
    api_jobs,
)




from httpserver.api.source import (  # noqa: E402
    api_clear_source,
    api_header_vorab,
    api_lade_electrum_server,
    api_local_core_accept,
    api_oeffentliche_electrum,
    api_rescan,
    api_save_mempool,
    api_save_source,
    api_source_status,
)



from httpserver.api.wallets import (  # noqa: E402
    api_alle_utxos,
    api_cache_wallet_leeren,
    api_cache_wallet_zeilen,
    api_deskriptor_pruefen,
    api_lab_faucet_senden,
    api_probe,
    api_save_wallets,
    api_sparrow_import,
    api_wallet_empfang,
    api_wallet_export_adressen_nachziehen,
    api_wallet_export_import,
    api_wallet_export_import_pfade,
    api_wallet_export_suchen,
    api_wallet_tip_sync,
    api_wallet_utxos,
    api_wallets_cache_vorschau,
)



from httpserver.api.trace import (  # noqa: E402
    api_trace,
    api_trace_alle,
    api_trace_gespeichert,
    api_verlauf,
)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _client_weg(exc: BaseException | None) -> bool:
    """Browser/Tab zu — Verbindung weg; kein Fehler fürs Terminal."""
    if exc is None:
        return False
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    if isinstance(exc, ConnectionError):
        return True
    if isinstance(exc, OSError):
        win = getattr(exc, "winerror", None)
        if win in (10053, 10054):  # WSAECONNABORTED / WSAECONNRESET
            return True
        if exc.errno in (
            errno.EPIPE,
            errno.ECONNRESET,
            getattr(errno, "ECONNABORTED", -1),
        ):
            return True
    return False


def _shutdown_rauschen(exc: BaseException | None) -> bool:
    """Fehler beim Server-Ende / Client-Weg — nicht ins Terminal speien."""
    if _client_weg(exc):
        return True
    if isinstance(exc, RuntimeError):
        msg = str(exc).lower()
        if "interpreter shutdown" in msg or "cannot schedule new futures" in msg:
            return True
    return False


def _server_faehrt_runter(state) -> bool:
    return bool(getattr(state, "_shutting_down", False))


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Unterdrückt Tracebacks bei Client-Abbruch und Server-Shutdown."""

    def handle_error(self, request, client_address) -> None:
        err = sys.exc_info()[1]
        if _shutdown_rauschen(err):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    server_version = "SatSage"
    sys_version = ""

    state: AppState = None  # wird beim Start gesetzt

    # -- Hilfen -------------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if getattr(self, "_pending_cookie", None):
                self.send_header("Set-Cookie", self._pending_cookie)
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:",
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except Exception as exc:
            if _client_weg(exc):
                return
            raise

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _will_ndjson(self) -> bool:
        accept = (self.headers.get("Accept") or "").lower()
        return "application/x-ndjson" in accept

    def _ndjson_zeile(self, obj: dict) -> None:
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

    def _fehler(self, status: int, message: str) -> None:
        try:
            self._json(status, {"error": message})
        except Exception as exc:
            if _shutdown_rauschen(exc):
                return
            raise

    def _request_host(self) -> str:
        trust_proxy = _env_setting(self.state, "SATSAGE_TRUST_PROXY") == "1"
        forwarded = self.headers.get("X-Forwarded-Host") if trust_proxy else None
        return _normalisiere_host(forwarded or self.headers.get("Host"))

    def _host_value_ok(self, host: str) -> bool:
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
        return self._host_value_ok(self._request_host())

    def _loopback_request(self) -> bool:
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
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def _secure_cookie(self) -> bool:
        if _env_setting(self.state, "SATSAGE_TRUST_PROXY") == "1":
            return (self.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower() == "https"
        return (urlparse(self.path).scheme or "").lower() == "https"

    def _set_session_cookie(self, value: str, *, delete: bool = False) -> None:
        parts = [f"{SESSION_COOKIE}={value}", "Path=/", "HttpOnly", "SameSite=Lax"]
        if self._secure_cookie():
            parts.append("Secure")
        if delete:
            parts.extend(("Max-Age=0", "Expires=Thu, 01 Jan 1970 00:00:00 GMT"))
        self._pending_cookie = "; ".join(parts)

    def _new_session(self) -> None:
        sid = secrets.token_urlsafe(32)
        with self.state._auth_lock:
            self.state.sessions[sid] = time.time() + SESSION_TTL
        self._set_session_cookie(sid)

    def _session_id(self) -> str:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else ""
        except (CookieError, ValueError):
            return ""

    def _session_ok(self) -> bool:
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
        value = self.headers.get("X-Satsage-Token", "")
        return bool(value) and secrets.compare_digest(value, self.state.token)

    def _token_ok(self, query: dict) -> bool:
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
        if methode not in ("POST", "PUT", "DELETE"):
            return True
        if self._has_valid_token_header():
            return True
        if not _password_is_set(self.state) and _env_setting(self.state, "SATSAGE_TRUST_PROXY") != "1":
            return True
        return self._origin_ok()

    def _rate_limited(self) -> bool:
        now = time.time()
        ip = _client_ip(self)
        with self.state._auth_lock:
            values = [stamp for stamp in self.state._login_failures.get(ip, []) if now - stamp < LOGIN_WINDOW]
            self.state._login_failures[ip] = values
            return len(values) >= LOGIN_MAX_FAILURES

    def _record_login_failure(self) -> None:
        now = time.time()
        ip = _client_ip(self)
        with self.state._auth_lock:
            values = [stamp for stamp in self.state._login_failures.get(ip, []) if now - stamp < LOGIN_WINDOW]
            values.append(now)
            self.state._login_failures[ip] = values

    def _login_succeeded(self) -> None:
        with self.state._auth_lock:
            self.state._login_failures.pop(_client_ip(self), None)
        self._new_session()

    def _body(self, *, max_bytes: int = 1_000_000) -> dict:
        laenge = int(self.headers.get("Content-Length") or 0)
        if laenge <= 0:
            return {}
        if laenge > max_bytes:
            raise ApiError(413, "Anfrage zu groß.")
        try:
            raw = self.rfile.read(laenge).decode("utf-8")
            if (self.headers.get("Content-Type") or "").split(";", 1)[0].lower() == "application/x-www-form-urlencoded":
                return {key: values[-1] for key, values in parse_qs(raw, keep_blank_values=True).items()}
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("JSON-Objekt erwartet")
            return value
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise ApiError(400, f"Ungültiges JSON: {exc}") from exc

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        if getattr(self, "_pending_cookie", None):
            self.send_header("Set-Cookie", self._pending_cookie)
        self.end_headers()

    def _login_page(self) -> None:
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
        # The status endpoint must establish the same session as initial HTML.
        authenticated = self._auth_ok({})
        return {
            "password_set": _password_is_set(self.state),
            "authenticated": authenticated,
            "setup_required": not _password_is_set(self.state),
        }

    def _auth_api(self, methode: str, pfad: str) -> bool:
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

    # -- Verteiler ----------------------------------------------------------

    def do_GET(self):
        self._verarbeite("GET")

    def do_POST(self):
        self._verarbeite("POST")

    def do_PUT(self):
        self._verarbeite("PUT")

    def do_DELETE(self):
        self._verarbeite("DELETE")

    def _verarbeite(self, methode: str):
        self._pending_cookie = None
        if _server_faehrt_runter(self.state):
            return
        if not self._host_ok():
            self._fehler(403, "Ungültiger Host-Header.")
            return
        zerlegt = urlparse(self.path)
        pfad = unquote(zerlegt.path)
        query = parse_qs(zerlegt.query, keep_blank_values=True)
        if methode == "GET" and pfad in ("/login", "/login.html"):
            self._login_page()
            return
        if pfad == "/api/health" and methode == "GET":
            self._json(200, api_health(self.state))
            return
        # Logo/Favicon für die Login-Seite — ohne die übrige UI-Shell freizugeben.
        if methode == "GET" and pfad in LOGIN_PUBLIC_ASSETS:
            self._statisch(pfad)
            return
        if self._auth_api(methode, pfad):
            return
        auth_ok = self._auth_ok(query)
        if auth_ok:
            _splash_bei_browser()
        if not self._csrf_ok(methode):
            self._fehler(403, "Origin/Referer fehlt oder ist nicht erlaubt.")
            return
        try:
            if pfad.startswith("/api/"):
                if not auth_ok:
                    self._fehler(403, "Anmeldung oder gültiger Token erforderlich.")
                    return
                if pfad in ("/api/tax/export.csv", "/api/tax/bericht.html"):
                    self._download(pfad, query)
                    return
                if pfad in ("/api/tax/selbstanzeige/bericht.html", "/api/tax/selbstanzeige/export.csv"):
                    if methode not in ("GET", "HEAD"):
                        self._fehler(405, "Methode nicht erlaubt.")
                        return
                    self._download_selbstanzeige(pfad, query)
                    return
                if (pfad == "/api/source/status" and methode == "GET" and self._will_ndjson() and query.get("check", ["0"])[0] in ("1", "true", "ja")):
                    self._stream_source_status(query)
                    return
                # Wallet-Suche: bewusst normales JSON (logs[] in der Antwort).
                # NDJSON-Stream endete unter WebKit mit „Load failed“.
                self._json(*self._api(methode, pfad, query))
                return
            if methode == "GET" and pfad in ("/handbuch.html", "/handbuch"):
                if _password_is_set(self.state) and not auth_ok:
                    self._redirect("/login?next=/handbuch.html")
                else:
                    self._sende_handbuch()
                return
            if methode == "GET":
                if _password_is_set(self.state) and not auth_ok:
                    # Auch Loopback: gesetztes Passwort → Login, nicht nur ?t=.
                    next_pfad = pfad or "/"
                    if next_pfad == "/":
                        self._redirect("/login?next=/")
                    else:
                        self._redirect("/login?next=" + next_pfad)
                else:
                    # Ohne Passwort: Token (?t=) in der URL belassen — die Web-GUI
                    # liest es clientseitig und entfernt es per history.replaceState.
                    self._statisch(pfad)
                return
            self._fehler(405, "Methode nicht erlaubt.")
        except JobQuotaExceeded as exc:
            self._fehler(429, str(exc))
        except ApiError as exc:
            if exc.status >= 500:
                LOGGER.exception("API-Fehler: %s", _redact_url(self.path))
            self._fehler(exc.status, exc.message)
        except Exception as exc:
            if _shutdown_rauschen(exc) or _server_faehrt_runter(self.state):
                return
            LOGGER.exception("API-Fehler: %s", _redact_url(self.path))
            try:
                self._fehler(500, "Interner Serverfehler.")
            except Exception as exc2:
                if _shutdown_rauschen(exc2):
                    return
                raise

    def _api(self, methode: str, pfad: str, query: dict) -> tuple[int, dict]:
        state = self.state
        teile = [t for t in pfad.split("/") if t][1:]  # ohne 'api'

        if teile == ["config"] and methode == "GET":
            return 200, api_config(
                state, query, self.headers.get("Accept-Language")
            )
        if teile == ["config", "wallets"] and methode == "PUT":
            return 200, api_save_wallets(state, self._body())
        if teile == ["config", "wallets", "cache-vorschau"] and methode == "POST":
            return 200, api_wallets_cache_vorschau(state, self._body())
        if teile == ["config", "source"] and methode == "PUT":
            return 200, api_save_source(state, self._body())
        if (
            len(teile) == 3
            and teile[0] == "config"
            and teile[1] == "source"
            and methode == "DELETE"
        ):
            return 200, api_clear_source(state, teile[2])
        if teile == ["config", "electrum-servers"] and methode == "POST":
            return 200, api_lade_electrum_server(state, self._body())
        if teile == ["config", "mempool"] and methode == "PUT":
            return 200, api_save_mempool(state, self._body())
        if teile == ["config", "start-sync"] and methode == "PUT":
            return 200, api_save_start_sync(state, self._body())
        if teile == ["config", "app-password"] and methode == "PUT":
            return 200, api_save_app_password(state, self._body())
        if teile == ["config", "app-password"] and methode == "POST":
            # Löschen per POST (Body); DELETE+Body bricht in manchen Browsern ab.
            body = self._body()
            aktion = str(body.get("action") or body.get("op") or "").strip().lower()
            if aktion in ("delete", "remove", "clear", "loeschen", "löschen"):
                return 200, api_delete_app_password(state, body)
            raise ApiError(400, "Unbekannte app-password-Aktion.")
        if teile == ["config", "app-password"] and methode == "DELETE":
            return 200, api_delete_app_password(state, self._body())
        if teile == ["config", "unlock-env"] and methode == "POST":
            return 200, api_unlock_env(state, self._body())
        if teile == ["config", "ui-lang"] and methode == "PUT":
            return 200, api_save_ui_lang(state, self._body())
        if teile == ["config", "ui-theme"] and methode == "PUT":
            return 200, api_save_ui_theme(state, self._body())
        if teile == ["config", "lernhinweise-plebs"] and methode == "PUT":
            return 200, api_save_lernhinweise_plebs(state, self._body())
        if teile == ["config", "steuer"] and methode == "PUT":
            return 200, api_save_steuer(state, self._body())
        if teile == ["config", "person"] and methode == "PUT":
            return 200, api_save_steuer_person(state, self._body())
        if teile == ["config", "hinweis-onchain"] and methode == "PUT":
            return 200, api_save_hinweis_onchain(state, self._body())
        if teile == ["config", "llm"] and methode == "PUT":
            return 200, api_save_llm(state, self._body())
        if teile == ["config", "status-mail"] and methode == "PUT":
            return 200, api_save_status_mail(state, self._body())
        if teile == ["wallets", "probe"] and methode == "POST":
            return 200, api_probe(state, self._body())
        if len(teile) == 3 and teile[0] == "wallets" and teile[2] == "utxos" and methode == "GET":
            return 200, api_wallet_utxos(state, teile[1], query)
        if len(teile) == 3 and teile[0] == "wallets" and teile[2] == "empfang" and methode == "GET":
            return 200, api_wallet_empfang(state, teile[1])
        if teile == ["lab", "faucet-senden"] and methode == "POST":
            return 200, api_lab_faucet_senden(state, self._body())
        if teile == ["utxos"] and methode == "GET":
            return 200, api_alle_utxos(state, query)
        if teile == ["sanctions"] and methode == "GET":
            return 200, api_sanctions(state, query)
        if teile == ["sanctions", "update"] and methode == "POST":
            return 202, api_sanctions_update(state, self._body())
        if teile == ["sanctions", "import"] and methode == "POST":
            # Bis ~55 MB Base64 (Voll-ZIP Labels-ähnlich; Sanktionen meist kleiner).
            return 200, api_sanctions_import(
                state, self._body(max_bytes=60 * 1024 * 1024)
            )
        if teile == ["sanctions", "check"] and methode == "POST":
            return 202, api_sanctions_check(state, self._body())
        if teile == ["sanctions", "check"] and methode == "GET":
            return 200, api_sanctions_check_ergebnis(state, query)
        if teile == ["sanctions", "check"] and methode == "DELETE":
            return 200, api_sanctions_check_verwerfen(state)
        if teile == ["labels"] and methode == "GET":
            return 200, api_labels(state, query)
        if teile == ["labels"] and methode == "POST":
            return 200, api_labels_update(state, self._body())
        if teile == ["labels", "import"] and methode == "POST":
            # Vollbestand ~37 MB → Base64 ~50 MB.
            return 200, api_labels_import(
                state, self._body(max_bytes=80 * 1024 * 1024)
            )
        if teile == ["labels"] and methode == "DELETE":
            return 200, api_labels_verwerfen(state, query)
        if teile == ["exchange-reports"] and methode == "GET":
            return 200, api_exchange_reports(state, query)
        if teile == ["exchange-reports", "import"] and methode == "POST":
            return 200, api_exchange_reports_import(
                state, self._body(max_bytes=45 * 1024 * 1024)
            )
        if teile == ["exchange-reports"] and methode == "DELETE":
            return 200, api_exchange_reports_loesche(state, query)
        if teile == ["source", "status"] and methode == "GET":
            return 200, api_source_status(state, query)
        if teile == ["source", "oeffentlich"] and methode == "POST":
            return 200, api_oeffentliche_electrum(state, self._body())
        if teile == ["source", "local-core"] and methode == "POST":
            return 200, api_local_core_accept(state, self._body())
        if teile == ["llm", "status"] and methode == "GET":
            return 200, api_llm_status(state, query)
        if teile == ["price"] and methode == "GET":
            return 200, api_price(state, query)
        if teile == ["price", "history"] and methode == "GET":
            return 200, api_price_history(state, query)
        if teile == ["price", "history", "sync"] and methode == "POST":
            return 200, api_price_history_sync(state, self._body())
        if teile == ["price", "import"] and methode == "POST":
            return 200, api_price_import(state, self._body())
        if teile[:2] == ["llm", "context"]:
            if methode != "GET":
                raise ApiError(405, "Nur Lesen — der Assistent startet keine Jobs.")
            return 200, api_llm_context(state, teile[2:], query)
        if teile == ["llm", "chat"] and methode == "POST":
            return 200, api_llm_chat(state, self._body())
        if teile == ["tax"] and methode == "GET":
            return 200, api_tax(state, query)
        if teile == ["tax", "selbstanzeige", "kandidaten"] and methode == "GET":
            return 200, api_selbstanzeige_kandidaten(state, query)
        if teile == ["trace", "alle"] and methode == "POST":
            return 202, api_trace_alle(state, self._body())
        if teile == ["trace"] and methode == "POST":
            body = api_trace(state, self._body())
            # Cache-Hit: 200 sofort. Live-Job: 202 Accepted.
            return (200 if body.get("from_cache") else 202), body
        if teile == ["trace"] and methode == "GET":
            return 200, api_trace_gespeichert(state, query)
        if teile == ["config", "deskriptor"] and methode == "POST":
            return 200, api_deskriptor_pruefen(state, self._body())
        if teile == ["config", "sparrow-import"] and methode == "POST":
            return 200, api_sparrow_import(state, self._body())
        if teile == ["config", "wallet-export-import"] and methode == "POST":
            return 200, api_wallet_export_import(state, self._body())
        if teile == ["config", "wallet-export-suchen"] and methode == "POST":
            # NDJSON-Stream läuft in _verarbeite (nicht hier), sonst doppelte Antwort.
            return 200, api_wallet_export_suchen(state)
        if teile == ["config", "wallet-export-import-pfade"] and methode == "POST":
            return 200, api_wallet_export_import_pfade(state, self._body())
        if teile == ["config", "wallet-export-adressen-nachziehen"] and methode == "POST":
            return 200, api_wallet_export_adressen_nachziehen(state, self._body())
        if teile == ["verlauf"] and methode == "POST":
            return 202, api_verlauf(state, self._body())
        if teile == ["cache", "unreferenziert"] and methode == "GET":
            return 200, api_cache_unreferenziert(state)
        if teile == ["cache", "unreferenziert"] and methode == "DELETE":
            return 200, api_cache_unreferenziert_loeschen(state)
        if teile == ["cache", "stats"] and methode == "GET":
            return 200, api_cache_stats(state)
        if teile == ["cache", "wallets"] and methode == "GET":
            return 200, api_cache_wallet_zeilen(state)
        if teile == ["cache"] and methode == "DELETE":
            return 200, api_cache_leeren(state)
        if len(teile) == 2 and teile[0] == "cache" and methode == "DELETE":
            return 200, api_cache_wallet_leeren(state, teile[1])
        if teile == ["headers"] and methode == "POST":
            return 202, api_header_vorab(state)
        if teile == ["jobs", "rescan"] and methode == "POST":
            return 202, api_rescan(state, self._body())
        if teile == ["jobs", "wallet-sync"] and methode == "POST":
            return 202, api_wallet_tip_sync(state, self._body())
        if teile == ["jobs"] and methode == "GET":
            return 200, api_jobs(state, query)
        if len(teile) == 2 and teile[0] == "jobs" and methode == "GET":
            return 200, api_job(state, teile[1])
        if len(teile) == 2 and teile[0] == "jobs" and methode == "DELETE":
            return 200, api_cancel_job(state, teile[1])

        raise ApiError(404, f"Unbekannter Endpunkt: {methode} {pfad}")

    def _download(self, pfad: str, query: dict) -> None:
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
            name = f"satsage-sat-geschichte-{jahr}.csv"
            # CSV immer als Download — im Tab wäre es nur Rohtext.
            disposition = f'attachment; filename="{name}"'
        else:
            inhalt = sa.als_html(
                report,
                immutable_cache_dir=self.state.immutable_cache_dir,
                theme=theme,
            )
            typ = "text/html; charset=utf-8"
            name = f"satsage-sat-geschichte-{jahr}.html"
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

    def _sende_handbuch(self) -> None:
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

    def log_message(self, format, *args):  # noqa: A002
        """Keine Zugriffsprotokolle — die Pfade enthalten Wallet-Kennungen."""


def build_state(args) -> AppState:
    # Damit main._load_dotenv() dieselbe Datei sieht wie --env / AppState.
    if args.env:
        main.ENV_FILE = Path(args.env)
    if args.cache_dir:
        main.UTXO_CACHE_DIR = Path(args.cache_dir)
    if args.immutable_cache_dir:
        # fulcrum._block_time_for_height liest global IMMUTABLE_CACHE_DIR —
        # sonst Mainnet-Header-Zeiten auf Regtest-Höhen (Alter nur 1T/377T).
        main.IMMUTABLE_CACHE_DIR = Path(args.immutable_cache_dir)
    state = AppState(
        env_path=Path(args.env or main.ENV_FILE),
        cache_dir=Path(args.cache_dir or main.UTXO_CACHE_DIR),
        immutable_cache_dir=Path(args.immutable_cache_dir or main.IMMUTABLE_CACHE_DIR),
        # Ohne eigene Angabe das Verzeichnis der Listen. Vorher stand hier
        # None — dann lieferte check_ergebnis_pfad() ebenfalls None, und das
        # Ergebnis des minutenlangen Prüflaufs wurde weder geschrieben noch
        # gelesen. Still, und deshalb lange unbemerkt.
        sanctions_dir=(
            Path(args.sanctions_dir) if args.sanctions_dir
            else sanctioned.SANCTIONED_CACHE_DIR
        ),
        label_dir=Path(args.label_dir) if args.label_dir else None,
    )
    _seed_managed_password(state)
    registriere_status_mail_hook(state)
    return state


class EingebetteterServer:
    """
    Hintergrund-HTTP für Einbettung (Specter-iframe o. ä.).

    Läuft im selben Prozess als Daemon-Thread — kein Multiprocessing.
    """

    def __init__(
        self,
        *,
        state: AppState,
        httpd: ThreadingHTTPServer,
        thread: threading.Thread,
        bind: str,
        port: int,
    ):
        self.state = state
        self.httpd = httpd
        self.thread = thread
        self.bind = bind
        self.port = port

    @property
    def token(self) -> str:
        return self.state.token

    @property
    def url(self) -> str:
        return f"http://{self.bind}:{self.port}/?t={self.token}"

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
        finally:
            self.httpd.server_close()


def _port_erreichbar(bind: str, port: int, *, timeout: float = 0.2) -> bool:
    """True, wenn unter *bind*:*port* schon etwas annimmt (Windows: SO_REUSEADDR)."""
    if int(port) <= 0:
        return False
    try:
        with socket.create_connection((bind, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def starte_im_hintergrund(
    state: AppState | None = None,
    *,
    port: int = DEFAULT_PORT,
    bind: str | None = None,
    args=None,
    header_vorab: bool = False,
) -> EingebetteterServer:
    """
    Startet die Web-GUI in einem Daemon-Thread.

    Bevorzugt *port*; ist er belegt, nimmt der Server einen freien Port
    (``0``). Kein Browser-Autostart — der Aufrufer liefert die URL weiter
    (iframe / neuer Tab).
    """
    if state is None:
        if args is None:
            args = build_argumente().parse_args([])
        state = build_state(args)

    bind = _bind_host(bind, state=state, args=args)
    Handler.state = state

    ziel = int(port)
    # HTTPServer.allow_reuse_address ist unter Windows oft wirkungslos gegen
    # „Port belegt“ — erst verbinden, dann ggf. auf Port 0 ausweichen.
    if ziel > 0 and _port_erreichbar(bind, ziel):
        ziel = 0
    try:
        httpd = QuietThreadingHTTPServer((bind, ziel), Handler)
    except OSError:
        httpd = QuietThreadingHTTPServer((bind, 0), Handler)

    tatsaechlich = int(httpd.server_address[1])
    thread = threading.Thread(
        target=httpd.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
        name="satsage-webgui",
    )
    thread.start()

    try:
        _log_local_core_hint_once(state)
    except Exception:
        pass

    if header_vorab:
        starte_header_vorab(state)

    return EingebetteterServer(
        state=state,
        httpd=httpd,
        thread=thread,
        bind=bind,
        port=tatsaechlich,
    )


def tip_sync_laeuft(state: AppState) -> bool:
    """Ob gerade ein Tip-Nachzug-Job läuft (Watcher darf dann nachziehen)."""
    jid = state.wallet_sync_job_id
    if not jid:
        return False
    job = state.jobs.get(jid)
    if job is None or job.status != "running":
        # Fertig/weg: stale ID freigeben — sonst meldet /api/config ewig den alten Job.
        if job is None or job.status in ("done", "failed", "cancelled"):
            state.wallet_sync_job_id = None
        return False
    # Abbruch angefordert: neuer Start darf den Slot übernehmen.
    if getattr(job, "cancelled", False):
        return False
    return True


def _tip_sync_abbrechen(state: AppState, *, warte_s: float = 3.0) -> None:
    """Bricht laufenden Tip-Nachzug ab und gibt den Slot frei."""
    jid = state.wallet_sync_job_id
    if not jid:
        return
    job = state.jobs.get(jid)
    if job is not None and job.status == "running":
        try:
            state.jobs.cancel(jid)
        except Exception:
            pass
        deadline = time.monotonic() + max(0.0, warte_s)
        while time.monotonic() < deadline:
            job = state.jobs.get(jid)
            if job is None or job.status != "running":
                break
            time.sleep(0.05)
    state.wallet_sync_job_id = None


def starte_wallet_aktualisierung(
    state: AppState,
    *,
    erzwingen: bool = False,
    wallet_ids: list[str] | None = None,
    still: bool = False,
) -> dict | None:
    """
    Hintergrund: Wallets mit Cache bis Chain-Tip nachziehen.

    Kein Fullscan — BIP-158 ab ``scan_tip_height`` oder Electrs light.
    *erzwingen*: auch ohne ``WALLETS_BEIM_START_AKTUALISIEREN`` (UI-Knopf).
    *wallet_ids*: nur diese Wallets; sonst alle mit Cache.
    *still*: Hintergrund (Wallet-Watch-Fallback) — GUI ohne Nav-„aktualisiere…“.
    Rückgabe: Job-Dict bei Start, None wenn nichts zu tun / schon läuft.
    """
    werte = state.env().values()
    if not erzwingen and not main.resolve_wallets_beim_start_aktualisieren(
        werte
    ):
        return None
    if tip_sync_laeuft(state):
        return None

    # Auch leerer Cache (0 UTXOs) zählt — Scan-Stand zum Fortsetzen.
    eintraege = [
        e for e in state.analyse_entries
        if main.load_xpub_cache_entry(e.analyse_schluessel, state.cache_dir)
    ]
    if wallet_ids:
        erlaubt = {str(x) for x in wallet_ids}
        eintraege = [
            e for e in eintraege
            if wallets_mod.eintrag_id(e) in erlaubt
        ]
    if not eintraege:
        return None

    def lauf(job):
        from core.jobs import Fortschritt, herzschlag

        stand = Fortschritt(job)
        halt = threading.Event()
        threading.Thread(
            target=herzschlag, args=(stand, halt), daemon=True,
        ).start()
        try:
            nur_bekannte = main.resolve_wallets_nur_bekannte_utxos(
                state.env().values()
            )
            extras = []
            if still:
                extras.append("still")
            if nur_bekannte:
                extras.append("nur bekannte UTXOs, kein Gap")
            suffix = f" ({', '.join(extras)})…" if extras else "…"
            stand.phase(
                f"Aktualisiere {len(eintraege)} Wallet(s) bis Chain-Tip{suffix}"
            )
            args = state.args_namespace()
            args.xpubs = [e.analyse_schluessel for e in eintraege]
            quelle, backend = main._setup_blockchain_client(args, state.env().values())
            job.raise_if_cancelled()
            fetchers = main._build_blockchain_fetchers(
                quelle, backend, args, state.wallet_ctx,
                immutable_cache_dir=state.immutable_cache_dir,
            )
            stand.phase(f"Datenquelle: {quelle}")

            # Tip-Nachzug:
            # * Eigener Electrs → nur Electrs light, kein BIP-158 (schneller;
            #   Subscribe hält danach aktuell).
            # * Nur BIP-158 / kein Electrs → Filter inkrementell.
            # * Öffentliches Electrum → BIP-158 wenn Tip da (Privatsphäre).
            # * nur_bekannte → kein Gap / kein BIP-158-Walk.
            bip158_fetch = None
            fulcrum = fetchers.get("fulcrum")
            electrs_eigen = (
                quelle == "fulcrum"
                and fulcrum is not None
                and main.is_own_fulcrum_backend(fulcrum)
            )
            # Kopf-Pille sofort: Indexer schon in Nutzung, nicht erst Peer-Takt.
            if electrs_eigen:
                own_stand = _merke_own_fulcrum_client(state, fulcrum)
                if own_stand and isinstance(job.meta, dict):
                    job.meta["own_fulcrum"] = own_stand
                    soft = str(own_stand.get("software") or "").strip()
                    if soft:
                        stand.phase(f"Indexer: {soft}")
            schluessel = [e.analyse_schluessel for e in eintraege]
            hat_tip = any(
                (main.load_xpub_cache_entry(x, state.cache_dir) or {})
                .get("raw", {})
                .get("scan_tip_height")
                is not None
                for x in schluessel
            )
            if nur_bekannte:
                stand.phase(
                    "Tip-Nachzug: nur bekannte UTXOs "
                    "(kein Gap — neue Adressen per UTXO-Scan)"
                )
            elif electrs_eigen:
                stand.phase(
                    "Tip-Nachzug: eigener Electrs (listunspent/Gap) — "
                    "ohne BIP-158; Subscribe übernimmt Live-Updates"
                )
            elif quelle == "bip158":
                bip158_fetch = fetchers.get("fetch_wallet_utxos")
                stand.phase("Tip-Nachzug: BIP-158 inkrementell")
            elif hat_tip:
                stand.phase("Prüfe BIP-158 für Tip-Nachzug…")
                job.raise_if_cancelled()
                bip158_fetch = main.try_bip158_fetch_for_tip_sync(
                    args,
                    state.env().values(),
                    state.wallet_ctx,
                    immutable_cache_dir=state.immutable_cache_dir,
                )
                if bip158_fetch is not None:
                    stand.phase(
                        "Tip-Nachzug: BIP-158 inkrementell "
                        "(kein eigener Electrs)"
                    )
                else:
                    stand.phase(
                        "Tip-Nachzug: Electrs/Adresse light "
                        "(kein BIP-158-Peer)"
                    )
            else:
                stand.phase(
                    "Tip-Nachzug: Electrs light "
                    "(kein scan_tip_height — kein Filter-Nachzug)"
                )

            def on_progress(text, *, sofort=False):
                job.raise_if_cancelled()
                if sofort:
                    stand.phase(text)
                else:
                    stand.tick(text)

            zaehler = {"ok": 0, "utxos": 0}
            # xpub → Nav-ID, damit die GUI je fertigem Wallet „gerade eben“ zeigt
            # (nicht erst wenn alle Wallets durch sind).
            id_nach_schluessel = {
                e.analyse_schluessel: wallets_mod.eintrag_id(e)
                for e in eintraege
            }
            if isinstance(job.meta, dict):
                job.meta["done_wallet_ids"] = []
                job.meta["total_wallets"] = len(eintraege)

            def on_done(xpub, utxos):
                if utxos is not None:
                    zaehler["ok"] += 1
                    zaehler["utxos"] += len(utxos)
                wid = id_nach_schluessel.get(xpub)
                if not wid or not isinstance(job.meta, dict):
                    return
                fertig = list(job.meta.get("done_wallet_ids") or [])
                if wid in fertig:
                    return
                fertig.append(wid)
                job.meta["done_wallet_ids"] = fertig
                job.meta["done_wallets"] = len(fertig)
                # Leichte Message für Poller — ohne Log-Flut.
                name = next(
                    (
                        e.display_name for e in eintraege
                        if wallets_mod.eintrag_id(e) == wid
                    ),
                    wid,
                )
                job.message = (
                    f"Wallet-Tip {len(fertig)}/{len(eintraege)}: "
                    f"„{name}“ aktuell"
                )

            main.sync_wallets_zum_tip(
                [e.analyse_schluessel for e in eintraege],
                fetchers["fetch_wallet_utxos"],
                fetchers["fetch_address_utxos"],
                fetchers.get("fetch_addresses_utxos"),
                state.cache_dir,
                quelle,
                max_addresses=main.DEFAULT_MAX_ADDRESSES,
                wallet=state.wallet_ctx,
                fulcrum=fetchers.get("fulcrum"),
                verify_utxo_spent=fetchers.get("verify_utxo_spent"),
                bip158_fetch_wallet_utxos=bip158_fetch,
                on_progress=on_progress,
                on_wallet_done=on_done,
                nur_bekannte=nur_bekannte,
            )
            job.raise_if_cancelled()
            # UTXO-Tip ist fertig → Nav darf „gerade eben“ zeigen. Empfangs-QR
            # wird danach noch geschärft; der Nutzer sieht das am QR, nicht am
            # Wallet-Marker.
            if isinstance(job.meta, dict):
                job.meta["phase"] = "empfang"
            job.result = {
                "wallets": zaehler["ok"],
                "utxo_count": zaehler["utxos"],
                "empfang_phase": True,
            }
            if state.wallet_sync_job_id == job.id:
                state.wallet_sync_job_id = None
            stand.phase(
                f"{zaehler['ok']} Wallet(s) aktualisiert, "
                f"{zaehler['utxos']} UTXO(s) — Empfangsadressen folgen…"
            )
            n_empfang = _schaerfe_empfang_nach_sync(
                state,
                eintraege,
                fulcrum=fetchers.get("fulcrum"),
                on_progress=lambda text, *, sofort=False: (
                    stand.phase(text) if sofort else stand.tick(text)
                ),
            )
            job.raise_if_cancelled()
            if n_empfang:
                stand.phase(f"Empfang per Electrs: {n_empfang} Wallet(s).")
            return {
                "wallets": zaehler["ok"],
                "utxo_count": zaehler["utxos"],
                "empfang_scharf": n_empfang,
            }
        finally:
            halt.set()
            stand.close()
            # Slot freigeben sobald der Job-Thread endet (done/fail/cancel).
            if state.wallet_sync_job_id == job.id:
                state.wallet_sync_job_id = None
            try:
                from core import wallet_watch

                wallet_watch.get_watch_service().tip_nachzug_job_beendet()
            except Exception:
                pass

    namen = ", ".join(e.display_name for e in eintraege[:3])
    if len(eintraege) > 3:
        namen += f" +{len(eintraege) - 3}"
    if still:
        label = f"Tip-Nachzug still ({namen})"
    elif erzwingen:
        label = f"Tip-Nachzug ({namen})"
    else:
        label = f"Start-Aktualisierung ({namen})"
    job = state.jobs.start(
        "wallet_sync",
        label,
        lauf,
        meta={
            "art": "wallet_sync",
            "wallet_ids": [wallets_mod.eintrag_id(e) for e in eintraege],
            "still": bool(still),
        },
    )
    state.wallet_sync_job_id = job.id
    return job.as_dict()


#: Mindestabstand zwischen Header-Tip-Checks (Peer schon am Tip → idle).
HEADER_VORAB_COOLDOWN_S = 15 * 60


def starte_header_vorab(state: AppState, *, nur_wenn_leer: bool = False) -> None:
    """
    Block-Header ab SegWit im Hintergrund.

    Unabhängig von eingetragenen Wallets. ``nur_wenn_leer``: nur wenn die
    Datei fehlt oder nur der SegWit-Anker da ist.

    Ohne ``nur_wenn_leer``: Tip-Nachzug höchstens alle
    ``HEADER_VORAB_COOLDOWN_S`` (kein Spam durch Peer-Takt / Job-Poll).
    """
    from bip158_scanner import vorab_block_header
    from core.jobs import Fortschritt, herzschlag
    from core.p2p import SEGWIT_HEIGHT, header_cache_leer, header_datei_tip

    env = state.env().values()
    if env.get("BIP158_P2P", "1").strip().lower() in ("0", "false", "nein", "off"):
        return
    if state.header_job_id:
        laufend = state.jobs.get(state.header_job_id)
        if laufend is not None and laufend.status == "running":
            return

    tip_vor = header_datei_tip(_header_pfad(state))
    cache_ok = tip_vor is not None and tip_vor > SEGWIT_HEIGHT
    if nur_wenn_leer and not header_cache_leer(
        _header_pfad(state), start_height=SEGWIT_HEIGHT,
    ):
        return
    # Gefüllter Cache: Cooldown — sonst Peer-Takt alle paar Sekunden.
    if cache_ok and time.monotonic() < float(
        getattr(state, "header_vorab_naechstes", 0.0) or 0.0
    ):
        return
    if cache_ok and nur_wenn_leer:
        return

    label = (
        "Block-Header Tip-Nachzug"
        if cache_ok
        else "Block-Header ab SegWit"
    )

    def lauf(job):
        stand = Fortschritt(job)
        halt = threading.Event()
        threading.Thread(
            target=herzschlag, args=(stand, halt), daemon=True,
        ).start()
        try:
            def log(text: str) -> None:
                job.raise_if_cancelled()
                stand.phase(text)
                print(text, flush=True)

            tip = vorab_block_header(
                env,
                cache_dir=state.cache_dir,
                immutable_dir=state.immutable_cache_dir,
                on_log=log,
            )
            # Auch bei unverändertem Tip: lange Pause bis zum nächsten Check.
            state.header_vorab_naechstes = (
                time.monotonic() + HEADER_VORAB_COOLDOWN_S
            )
            job.message = (
                f"Header bis Block {tip:,}.".replace(",", ".")
                if tip else "Header-Vorab ohne Tip."
            )
            return {"tip": tip}
        finally:
            halt.set()
            stand.close()

    # Cooldown schon vor Start setzen — parallele API-Calls starten sonst
    # dutzende Jobs, bevor der erste finished_at hat.
    if cache_ok:
        state.header_vorab_naechstes = time.monotonic() + HEADER_VORAB_COOLDOWN_S
    job = state.jobs.start("headers", label, lauf)
    state.header_job_id = job.id


def _konsole_auf_utf8() -> None:
    """
    Stellt die Ausgabe auf UTF-8 um.

    Unter Windows verwendet Python die Codepage der Umgebung, sobald die
    Ausgabe in eine Datei umgeleitet wird — Gedankenstriche und Umlaute
    lösen dann einen UnicodeEncodeError aus und der Server startet nicht.
    """
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def build_argumente() -> argparse.ArgumentParser:
    """Die Startoptionen — als Funktion, damit die Vorgaben prüfbar sind."""
    parser = argparse.ArgumentParser(
        description="Lokale Web-Oberfläche für SatSage"
    )
    parser.add_argument("--bind", default=None, help="Listener-Adresse (Default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--env", default=None, help="Pfad zur .env")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--immutable-cache-dir", default=None)
    parser.add_argument("--sanctions-dir", default=None,
                        help="Verzeichnis der Sanktionslisten")
    parser.add_argument("--label-dir", default=None,
                        help="Verzeichnis der Adress-Labels")
    parser.add_argument("--no-browser", action="store_true",
                        help="Browser nicht automatisch öffnen")
    parser.add_argument(
        "--plain-console",
        action="store_true",
        help="Ohne Terminal-Menü: nur URL ausgeben und auf Strg+C warten "
             "(Tests/Automation, non-TTY)",
    )
    return parser


# pyi_splash nur mit Bootloader (_PYI_SPLASH_IPC). Sonst Tk-Fallback (macOS).
_splash_mod = None  # False = kein pyi; Modul = aktiv
_splash_tk = False
_splash_browser_gesehen = threading.Event()
_splash_zu = threading.Event()


def _splash_laden():
    """Lädt pyi_splash einmalig, oder None wenn nicht verfügbar."""
    global _splash_mod
    if _splash_mod is False:
        return None
    if _splash_mod is not None:
        return _splash_mod
    if "_PYI_SPLASH_IPC" not in os.environ:
        _splash_mod = False
        return None
    try:
        import pyi_splash  # type: ignore

        _splash_mod = pyi_splash
        return pyi_splash
    except Exception:
        _splash_mod = False
        return None


def _splash_start() -> None:
    """Früh: PyInstaller-Splash nutzen oder Tk-Kind starten (macOS/Fallback)."""
    global _splash_tk
    if _splash_laden() is not None:
        return
    # Windows-CLI: kein Tk-Kindprozess — der Prozessbaum wird sonst leicht
    # mit taskkill /T mitgerissen, und die Konsole gerät durcheinander.
    if sys.platform == "win32" and os.environ.get("SATSAGE_SPLASH", "").strip().lower() not in (
        "1", "true", "yes", "ja",
    ):
        return
    if splash_ui_mod.start_tk_splash():
        _splash_tk = True


def _splash_text(meldung: str) -> None:
    """Statuszeile am Splash (pyi oder Tk)."""
    try:
        splash = _splash_laden()
        if splash is not None and splash.is_alive():
            splash.update_text(meldung)
            return
    except Exception:
        pass
    if _splash_tk:
        splash_ui_mod.update_tk_splash(meldung)


def _splash_schliessen() -> None:
    """Splash ausblenden (idempotent)."""
    if _splash_zu.is_set():
        return
    _splash_zu.set()
    try:
        splash = _splash_laden()
        if splash is not None and splash.is_alive():
            splash.close()
    except Exception:
        pass
    if _splash_tk:
        splash_ui_mod.close_tk_splash()


def _splash_bei_browser() -> None:
    """Erster authentifizierter GUI-Request → Oberfläche steht, Splash weg."""
    if _splash_browser_gesehen.is_set():
        return
    _splash_browser_gesehen.set()
    _splash_schliessen()


def _port_belegt_errno(exc: BaseException) -> bool:
    return getattr(exc, "errno", None) in (
        errno.EADDRINUSE,
        getattr(errno, "WSAEADDRINUSE", -1),
    )


def _httpd_binden(port: int, bind: str | None = None) -> QuietThreadingHTTPServer:
    """
    Bindet an host:port. Bei Belegung durch eine SatSage-Instanz:
    alten Prozess beenden und erneut binden.
    """
    host = _bind_host(bind)
    try:
        return QuietThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        if not _port_belegt_errno(exc):
            raise
        beendet = single_mod.port_freigeben_satsage(port, host=host)
        if not beendet:
            raise
        print(
            f"Port {port} war belegt — vorherige SatSage-Instanz beendet "
            f"(PID {', '.join(str(p) for p in beendet)}), starte weiter…",
            flush=True,
        )
        time.sleep(0.25)
        try:
            return QuietThreadingHTTPServer((host, port), Handler)
        except OSError as exc2:
            if _port_belegt_errno(exc2):
                # Zweiter Versuch nach kurzer Pause (TIME_WAIT)
                time.sleep(0.75)
                return QuietThreadingHTTPServer((host, port), Handler)
            raise


def _splash_timeout_wache(sekunden: float = 25.0) -> None:
    """Fallback: Splash spätestens nach sekunden schließen (Browser ohne Request)."""

    def _lauf() -> None:
        ende = time.time() + sekunden
        while time.time() < ende:
            if _splash_zu.is_set() or _splash_browser_gesehen.is_set():
                return
            time.sleep(0.4)
        _splash_schliessen()

    threading.Thread(target=_lauf, name="satsage-splash-timeout", daemon=True).start()


def _oeffne_browser_sicher(adresse: str) -> None:
    """
    Öffnet die GUI-URL ohne die Server-Konsole zu gefährden.

    Unter Windows können ``webbrowser.open`` / ``cmd start`` CTRL-Events an die
    Konsolen-Prozessgruppe senden — dann endet der Server sofort. Deshalb:
    verzögert im Daemon-Thread und auf Windows ``os.startfile`` (ShellExecute).
    """

    def _lauf() -> None:
        time.sleep(1.2)
        try:
            if sys.platform == "win32":
                os.startfile(adresse)  # noqa: S606 — lokale http://-URL
                return
            webbrowser.open(adresse)
        except Exception:
            try:
                webbrowser.open(adresse)
            except Exception:
                pass

    threading.Thread(target=_lauf, name="satsage-open-browser", daemon=True).start()


def _http_debug_log(text: str) -> None:
    """Datei-Log für Windows-Diagnose (Konsole kann Events verschlucken)."""
    try:
        pfad = Path("tmp") / "satsage-http-thread.log"
        pfad.parent.mkdir(parents=True, exist_ok=True)
        with pfad.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {text}\n")
    except Exception:
        pass


def _http_loop_bis_strg_c(httpd: QuietThreadingHTTPServer) -> None:
    """
    HTTP in Daemon-Thread; Hauptthread blockiert bis Strg+C.

    Die Prozess-Lebensdauer hängt nicht an ``serve_forever``. Unter Windows
    kann die HTTP-Schleife sterben (Konsolen-CTRL / SystemExit im Thread) —
    der Hauptthread hält den Prozess und startet HTTP neu.
    """
    stop = threading.Event()
    http_thread: threading.Thread | None = None

    def _serve_once() -> None:
        _http_debug_log("serve_forever enter")
        try:
            httpd.serve_forever(poll_interval=0.5)
            _http_debug_log("serve_forever returned normally")
        except BaseException as exc:
            _http_debug_log(f"serve_forever BaseException: {exc!r}")
            if not stop.is_set() and not isinstance(exc, (SystemExit, KeyboardInterrupt)):
                LOGGER.exception("HTTP-Server-Fehler")

    def _ensure_http() -> None:
        nonlocal http_thread
        if http_thread is not None and http_thread.is_alive():
            return
        if stop.is_set():
            return
        if http_thread is not None:
            print(
                "\n  ⚠️  HTTP-Thread weg — starte neu (Strg+C beendet).",
                flush=True,
            )
            _http_debug_log("restarting http thread")
        http_thread = threading.Thread(
            target=_serve_once, name="satsage-http", daemon=True,
        )
        http_thread.start()

    _ensure_http()
    try:
        while True:
            _ensure_http()
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nBeendet.", flush=True)
        _http_debug_log("KeyboardInterrupt in main keep-alive")
        stop.set()
        try:
            httpd.shutdown()
        except Exception:
            pass
        if http_thread is not None:
            http_thread.join(timeout=5.0)


def main_cli(argv=None) -> int:
    from core.terminal_steuerung import lauf_steuerung, steuerung_sinnvoll

    _splash_start()
    _splash_text("SatSage …")
    _konsole_auf_utf8()
    args = build_argumente().parse_args(argv)

    _splash_text("Konfiguration …")
    state = build_state(args)
    bind = _bind_host(args.bind, state=state, args=args)
    try:
        from core.i18n import init_from_env
        from core.log_i18n import install_stdout_translation

        env_datei = state.env()
        werte = env_datei.values() if hasattr(env_datei, "values") else {}
        init_from_env(werte if isinstance(werte, dict) else None)
        install_stdout_translation()
    except Exception:
        pass
    Handler.state = state
    _splash_text("Hintergrunddienste …")
    starte_header_vorab(state)
    starte_wallet_aktualisierung(state)
    try:
        from core import wallet_watch

        wallet_watch.starte_wallet_watch(
            state, on_log=lambda t: print(f"  {t}", flush=True),
        )
    except Exception as exc:
        print(f"  Wallet-Watch nicht gestartet: {exc}", flush=True)

    _splash_text("Server …")
    try:
        httpd = _httpd_binden(args.port, bind=bind)
    except OSError as exc:
        _splash_schliessen()
        if _port_belegt_errno(exc):
            name = single_mod.binary_name()
            print(
                f"Port {args.port} ist belegt ({bind}) — keine SatSage-Instanz "
                f"zum Übernehmen gefunden.\n"
                f"  Anderen Prozess beenden oder starten mit:\n"
                f"    {name} --port {args.port + 1}\n"
                f"  Belegten Port prüfen:  lsof -nP -iTCP:{args.port} -sTCP:LISTEN",
                file=sys.stderr,
                flush=True,
            )
            return 1
        raise
    adresse = f"http://{bind}:{httpd.server_address[1]}/?t={state.token}"
    # Maschinenlesbar für GUI-Tests/Assistenten (kein Log-Grep auf Token).
    session_pfad = None
    try:
        session_pfad = gui_session_mod.schreibe_session(
            gui_session_mod.bau_payload(
                url=adresse,
                token=state.token,
                port=args.port,
                bind=bind,
                env_path=str(state.env_path),
            )
        )
    except Exception:
        session_pfad = None

    # Splash bleibt bis Browser die GUI lädt (nicht schon beim Bind).
    _splash_text("Browser …")

    mit_steuerung = steuerung_sinnvoll(plain_console=bool(args.plain_console))
    if mit_steuerung:
        # HTTP robust im Hintergrund; Hauptthread = Menü (1/2/3).
        stop_http = threading.Event()
        state._http_stop_event = stop_http  # type: ignore[attr-defined]

        def _http_im_hintergrund() -> None:
            while not stop_http.is_set():
                try:
                    httpd.serve_forever(poll_interval=0.5)
                except BaseException as exc:
                    _http_debug_log(f"menu-path http: {exc!r}")
                if stop_http.is_set():
                    break
                # shutdown() kann vor stop.set() zurückkehren — kurz nachprüfen
                time.sleep(0.05)
                if stop_http.is_set():
                    break
                print(
                    "\n  ⚠️  HTTP-Thread weg — starte neu.",
                    flush=True,
                )
                time.sleep(0.5)

        threading.Thread(
            target=_http_im_hintergrund, name="satsage-webgui", daemon=True,
        ).start()
        if state.header_job_id:
            from core.i18n import t

            print(t("cli.term.blockHeaders"), flush=True)
        if not args.no_browser:
            _splash_timeout_wache(25.0)
        else:
            _splash_schliessen()
        # GUI/HTTP stehen — Historie-Nachzug erst danach (nicht im Splash).
        starte_historie_nachzug_taeglich(state)
        try:
            return lauf_steuerung(
                state,
                httpd,
                adresse,
                # Windows: Auto-Browser aus dem Menü-Modul gesteuert
                oeffne_browser_anfangs=not args.no_browser,
            )
        finally:
            stop_http.set()
            try:
                httpd.shutdown()
            except Exception:
                pass
            _splash_schliessen()
            try:
                gui_session_mod.loesche_session(session_pfad)
            except Exception:
                pass

    from core.i18n import t

    print("SatSage – know your sats")
    print(t("cli.term.webUi"))
    print(t("cli.term.configLabel", path=state.env_path))
    print(t("cli.term.utxoCache", path=state.cache_dir))
    print(t("cli.term.sanctions", path=state.sanctions_dir))
    print(t("cli.term.wallets", n=len(state.entries)))
    print()
    print("  Im Browser öffnen (Token ist enthalten):")
    print(f"    {adresse}")
    if session_pfad is not None:
        print(f"  Session-Datei : {session_pfad}")
    print()
    print(f"  Listener {bind}. Beenden mit Strg+C.")
    print("  Browser darf geschlossen werden — Server läuft hier weiter.")
    if state.header_job_id:
        print("  Block-Header ab SegWit werden im Hintergrund geladen.")
    if not args.no_browser:
        _splash_timeout_wache(25.0)
        # Auch Windows: erst nach Banner/HTTP, verzögert via os.startfile.
        _oeffne_browser_sicher(adresse)
    else:
        _splash_schliessen()
    print("  Server bereit — Anfragen werden angenommen (Strg+C beendet).", flush=True)
    # GUI erreichbar — Lücken-Nachzug nachgelagert (nicht Startpfad).
    starte_historie_nachzug_taeglich(state)
    try:
        _http_loop_bis_strg_c(httpd)
    finally:
        _splash_schliessen()
        try:
            gui_session_mod.loesche_session(session_pfad)
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
