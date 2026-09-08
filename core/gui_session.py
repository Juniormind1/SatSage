"""
Maschinenlesbare GUI-Sitzung (Token/URL/Port) für Tests und Assistenten.

Problem: Das Sitzungs-Token steht nur in der Konsole — Log-Grep ist
unzuverlässig (Puffer, Header-Jobs, doppelte Starts).

Lösung: Beim Bind schreibt der Server eine kleine JSON-Datei (tmp/, mode 0600)
und eine Zeile ``SATSAGE_SESSION {…}`` auf stdout. Tests lesen die Datei
oder die Zeile — nie den Fließtext.

Pfade (erste Treffer-Reihenfolge beim Lesen):
  1. ``$SATSAGE_SESSION_FILE``
  2. ``{app_dir}/tmp/satsage-gui-session.json``
  3. ``{app_dir}/satsage-gui-session.json`` (Fallback neben Binary)
"""
from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any

from core.paths import app_dir

SESSION_NAME = "satsage-gui-session.json"
STDOUT_PREFIX = "SATSAGE_SESSION "


def session_pfade() -> list[Path]:
    """Kandidaten zum Lesen (Priorität absteigend)."""
    out: list[Path] = []
    env = (os.environ.get("SATSAGE_SESSION_FILE") or "").strip()
    if env:
        out.append(Path(env).expanduser())
    basis = app_dir()
    out.append(basis / "tmp" / SESSION_NAME)
    out.append(basis / SESSION_NAME)
    # unique, Reihenfolge halten
    gesehen: set[str] = set()
    einzig: list[Path] = []
    for p in out:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in gesehen:
            continue
        gesehen.add(key)
        einzig.append(p)
    return einzig


def default_schreib_pfad() -> Path:
    """Wohin der Server schreibt (tmp unter app_dir, sonst app_dir)."""
    env = (os.environ.get("SATSAGE_SESSION_FILE") or "").strip()
    if env:
        return Path(env).expanduser()
    tmp = app_dir() / "tmp"
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp / SESSION_NAME
    except OSError:
        return app_dir() / SESSION_NAME


def bau_payload(
    *,
    url: str,
    token: str,
    port: int,
    bind: str = "127.0.0.1",
    pid: int | None = None,
    env_path: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": 1,
        "url": url,
        "token": token,
        "port": int(port),
        "bind": bind,
        "pid": int(pid if pid is not None else os.getpid()),
        "env_path": env_path or "",
        "ts": time.time(),
    }


def schreibe_session(
    payload: dict[str, Any],
    pfad: Path | None = None,
    *,
    stdout_zeile: bool = True,
) -> Path:
    """
    Schreibt JSON atomar (tmp + replace), Mode 0600.
    Optional eine Parse-Zeile auf stdout (flush) — bei Skripten mit
    ``--json`` abschalten, damit stdout nur die Nutzlast ist.
    """
    ziel = pfad or default_schreib_pfad()
    ziel.parent.mkdir(parents=True, exist_ok=True)
    roh = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    tmp = ziel.with_suffix(ziel.suffix + ".tmp")
    tmp.write_text(roh + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    tmp.replace(ziel)
    try:
        os.chmod(ziel, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if stdout_zeile:
        # Eine Zeile, greppbar und für `tail -F` / JSONL-Tools
        print(f"{STDOUT_PREFIX}{roh}", flush=True)
    return ziel

def lese_session(pfad: Path | None = None) -> dict[str, Any] | None:
    """Liest die neueste gültige Session-Datei oder None."""
    kandidaten = [pfad] if pfad is not None else session_pfade()
    for p in kandidaten:
        if p is None or not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if not data.get("token") or not data.get("url"):
            continue
        data["_path"] = str(p)
        return data
    return None


def loesche_session(pfad: Path | None = None) -> None:
    """Entfernt Session-Datei(en) — beim Server-Ende."""
    if pfad is not None:
        try:
            pfad.unlink(missing_ok=True)
        except TypeError:
            try:
                if pfad.exists():
                    pfad.unlink()
            except OSError:
                pass
        except OSError:
            pass
        return
    for p in session_pfade():
        try:
            p.unlink(missing_ok=True)
        except TypeError:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        except OSError:
            pass


def session_lebt(payload: dict[str, Any], *, timeout: float = 2.0) -> bool:
    """True, wenn /api/config mit dem Token antwortet."""
    import urllib.error
    import urllib.request

    port = int(payload.get("port") or 0)
    token = str(payload.get("token") or "")
    bind = str(payload.get("bind") or "127.0.0.1")
    if not port or not token:
        return False
    url = f"http://{bind}:{port}/api/config"
    req = urllib.request.Request(
        url,
        headers={"X-Satsage-Token": token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as ant:
            if ant.status != 200:
                return False
            json.loads(ant.read().decode("utf-8"))
            return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def warte_session(
    *,
    sekunden: float = 30.0,
    pfad: Path | None = None,
    muss_leben: bool = True,
) -> dict[str, Any]:
    """Pollt bis Session-Datei da ist (und optional API antwortet)."""
    deadline = time.time() + sekunden
    letzte: dict[str, Any] | None = None
    while time.time() < deadline:
        letzte = lese_session(pfad)
        if letzte:
            if not muss_leben or session_lebt(letzte):
                return letzte
        time.sleep(0.25)
    raise TimeoutError(
        f"Keine gültige GUI-Session innerhalb {sekunden:.0f}s "
        f"(gesucht: {pfad or session_pfade()})"
    )
