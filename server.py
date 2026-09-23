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


# Auth-Helfer + Passwort-APIs: Domänenmodul (Modularisierung Slice 1).
# Früh re-exportiert — Bootstrap/Login nutzen die Namen vor dem späten API-Fassaden-Block.
from httpserver.api.auth_session import (  # noqa: E402
    _auth_file,
    _clear_password_hash,
    _hash_password,
    _password_hash,
    _password_is_set,
    _verify_password,
    _write_password_hash,
)


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


# Local-Core / Managed-Config → httpserver.local_core (Re-Export unten).

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


def _pfad_unter(kind: Path, eltern: Path) -> bool:
    try:
        kind.relative_to(eltern)
        return True
    except (ValueError, TypeError):
        return False


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


def _wallet_watch_status() -> dict:
    try:
        from core import wallet_watch

        return wallet_watch.wallet_watch_status()
    except Exception:
        return {"running": False}


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


# Empfang-/Mempool-Helfer → httpserver.empfang (Re-Export unten).
# Import-Payload → httpserver.import_payload (Re-Export unten).
# Historie-Nachzug → httpserver.historie_nachzug (Re-Export unten).
# TLS-Auto / P2P → httpserver.tls_p2p (Re-Export unten).
# Local-Core / Managed-Config → httpserver.local_core (Re-Export unten).


from httpserver.steuer import (  # noqa: E402
    _alle_gecachten_utxos,
    _alle_gecachten_verlaeufe,
    _selbstanzeige_report,
    _steuer_auswertung,
    _steuer_grundlage,
    _steuer_verlauf_ohne_phantom_unspent,
    _utxo_schluessel,
)


from httpserver.trace_helpers import (  # noqa: E402
    _ingress_veraltet,
    _stop_before_ts_aus_payload,
    _trace_ein_utxo_tief,
    _trace_offen_basis,
    _trace_offen_steuer,
    _trace_offen_tief,
    _utxos_fuer_trace,
    _wallet_name_fuer_utxo,
)


# Job-API: Domänenmodul (Modularisierung Slice 1). Öffentliche Namen bleiben.
from httpserver.api.auth_session import (  # noqa: E402
    api_delete_app_password,
    api_save_app_password,
    api_unlock_env,
)


from httpserver.api.config_ui import (  # noqa: E402
    api_config,
    api_save_hinweis_onchain,
    api_save_lernhinweise_plebs,
    api_save_llm,
    api_save_start_sync,
    api_save_status_mail,
    api_save_ui_lang,
    api_save_ui_theme,
    registriere_status_mail_hook,
    _ui_theme_aus_env,
)


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


from httpserver.api.tax import (  # noqa: E402
    api_save_steuer,
    api_save_steuer_person,
    api_selbstanzeige_kandidaten,
    api_tax,
)


from httpserver.api.labels_sanctions_exchange import (  # noqa: E402
    api_exchange_reports,
    api_exchange_reports_import,
    api_exchange_reports_loesche,
    api_labels,
    api_labels_import,
    api_labels_update,
    api_labels_verwerfen,
    api_sanctions,
    api_sanctions_check,
    api_sanctions_check_ergebnis,
    api_sanctions_check_verwerfen,
    api_sanctions_import,
    api_sanctions_update,
    _sanctions_get_tx_pool,
)


from httpserver.api.price_llm_lab import (  # noqa: E402
    api_llm_chat,
    api_llm_context,
    api_llm_status,
    api_price,
    api_price_history,
    api_price_history_sync,
    api_price_import,
    _llm_werkzeug,
)


from httpserver.api.utxos_cache import (  # noqa: E402
    api_cache_leeren,
    api_cache_stats,
    api_cache_unreferenziert,
    api_cache_unreferenziert_loeschen,
    _aktive_cache_kennungen,
    _aktive_utxo_refs,
    _cache_baum_stats,
    _cache_datei_kennung,
    _cache_datei_stats,
    _cache_kennung_hat_dateien,
    _cache_utxo_schluessel,
    _platte_cache_stats,
    _unreferenzierte_cache_pfade,
    _unreferenzierter_cache_bericht,
    _utxo_refs_aus_datei,
    _wallet_cache_belegung,
    _wallet_cache_loeschen,
    _wallet_cache_loeschen_kennung,
    _wallet_cache_pfade,
    _wallet_cache_pfade_kennung,
    _wallet_cache_umfang,
)


from httpserver.wallet_export import (  # noqa: E402
    _INDEXER_WARTE_S,
    _INDEXER_WARTE_SCHRITT_S,
    _electrum_indexer,
    _entfernte_wallets,
    _export_adresse_familie,
    _export_adressen_fuer_wallet,
    _export_adressen_nachziehen_meta,
    _export_eintraege_fuer_wallet,
    _export_script_familie,
    _indexer_konfiguriert,
    _wallet_export_anlegen_und_cache,
    _wallets_aus_payload,
    _wallets_config_gesperrt,
    _warte_auf_eigenen_indexer,
)




from httpserver.empfang import (  # noqa: E402
    _adresse_hat_history,
    _cache_bekannt_adressen,
    _eigener_fulcrum_client,
    _empfang_antwort,
    _empfang_aus_cache_schaetzung,
    _empfang_electrum_client,
    _empfang_finalize,
    _empfang_gehoert_zu_wallet,
    _empfang_max_index,
    _merke_own_fulcrum_client,
    _mit_mempool_pending,
    _naechste_freie_empfang_electrs,
    _next_receive_index_from_cache,
    _oeffentlicher_fulcrum_fuer_empfang,
    _query_flag,
    _schaerfe_empfang_nach_sync,
    _seed_wallet_ctx_aus_caches,
    _sortierung,
    _verlauf_anhang_fuer_xpub,
    _verlaufs_anhang,
)



from httpserver.import_payload import (  # noqa: E402
    _dateien_aus_import_payload,
)


from httpserver.historie_nachzug import (  # noqa: E402
    starte_historie_nachzug_taeglich,
)


from httpserver.tls_p2p import (  # noqa: E402
    _breche_p2p_jobs_ab,
    _live_p2p_peers,
    _persist_tls_auto,
)


from httpserver.local_core import (  # noqa: E402
    _BRIDGE_QUELLEN,
    _BRIDGE_SCHLUESSEL,
    _apply_local_core_runtime,
    _datenquellen_config_gesperrt,
    _discover_local_core_cached,
    _local_core_hint_logged,
    _local_core_probe_cache,
    _local_core_runtime_logged,
    _local_core_status_for_api,
    _log_local_core_hint_once,
    _managed_hint,
    _specter_labels_for_api,
)


from httpserver.api.health import (  # noqa: E402
    api_health,
)

from httpserver.handler_auth import HandlerAuthMixin  # noqa: E402
from httpserver.handler_static import HandlerStaticMixin  # noqa: E402
from httpserver.handler_download import HandlerDownloadMixin  # noqa: E402
from httpserver.handler_sse import HandlerSseMixin  # noqa: E402



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


class Handler(
    HandlerAuthMixin,
    HandlerStaticMixin,
    HandlerDownloadMixin,
    HandlerSseMixin,
    BaseHTTPRequestHandler,
):
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

    def _fehler(self, status: int, message: str) -> None:
        try:
            self._json(status, {"error": message})
        except Exception as exc:
            if _shutdown_rauschen(exc):
                return
            raise

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
