"""Electrum-Serverliste: URL, Laden, Split in Onion/Clearnet.

Slice 5 Schritt 10. ``check_fulcrum_tor`` bleibt Diagnose-CLI und
re-exportiert diese Symbole.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from core.paths import app_dir

ELECTRUM_SERVERS_FILE = app_dir() / "electrum_servers.json"
ELECTRUM_SERVERS_URL = (
    "https://raw.githubusercontent.com/spesmilo/electrum/master/"
    "electrum/chains/mainnet/servers.json"
)
ELECTRUM_SERVERS_GITHUB_COMMITS_URL = (
    "https://api.github.com/repos/spesmilo/electrum/commits"
    "?path=electrum/chains/mainnet/servers.json&sha=master&per_page=1"
)
ELECTRUM_SERVERS_DOWNLOAD_TIMEOUT = 30
CLIENT_NAME = "SatSage-check"
PROTOCOL_VERSION = "1.4"


def normalize_host(value: str) -> str:
    """Entfernt http(s):// und Pfade — nur Hostname für Fulcrum."""
    raw = value.strip()
    for prefix in ("https://", "http://"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if ":" in raw and not raw.endswith(".onion"):
        host, port_str = raw.rsplit(":", 1)
        if port_str.isdigit():
            return host
    return raw


def _format_age_days(age_days: float | None) -> str:
    if age_days is None:
        return "unbekannt"
    if age_days < 0.5:
        return "heute"
    whole = int(age_days)
    if whole == 0:
        return "weniger als 1 Tag"
    if whole == 1:
        return "1 Tag"
    return f"{whole} Tage"


def _local_json_age_days(path: Path = ELECTRUM_SERVERS_FILE) -> float:
    mtime = path.stat().st_mtime
    now = datetime.now(timezone.utc).timestamp()
    return max(0.0, (now - mtime) / 86400.0)


def _remote_json_age_days(
    api_url: str = ELECTRUM_SERVERS_GITHUB_COMMITS_URL,
) -> float | None:
    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": f"{CLIENT_NAME}/{PROTOCOL_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(
            req,
            timeout=ELECTRUM_SERVERS_DOWNLOAD_TIMEOUT,
        ) as resp:
            commits = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(commits, list) or not commits:
        return None
    try:
        date_str = commits[0]["commit"]["committer"]["date"]
        modified_at = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return max(0.0, (now - modified_at).total_seconds() / 86400.0)
    except (KeyError, TypeError, ValueError):
        return None


def fetch_electrum_servers_json(
    dest: Path = ELECTRUM_SERVERS_FILE,
    url: str = ELECTRUM_SERVERS_URL,
) -> dict[str, dict]:
    """Lädt servers.json vom Electrum-Repo und speichert sie lokal."""
    print(f"Lade {url} ...", flush=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"{CLIENT_NAME}/{PROTOCOL_VERSION}"},
    )
    try:
        with urllib.request.urlopen(
            req,
            timeout=ELECTRUM_SERVERS_DOWNLOAD_TIMEOUT,
        ) as resp:
            raw = resp.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Download fehlgeschlagen: {exc}") from exc

    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Ungueltiges Format in {url}")

    dest.write_bytes(raw)
    onion_count = sum(1 for host in data if str(host).endswith(".onion"))
    print(
        f"  → {len(data)} Server ({onion_count} .onion) "
        f"gespeichert in {dest.name}",
        flush=True,
    )
    return data


def electrum_endpunkt(meta: object) -> tuple[int, bool] | None:
    """Bevorzugt SSL (s), sonst TCP (t) — wie beim Onion-Scan."""
    if not isinstance(meta, dict):
        return None
    if "s" in meta:
        try:
            return int(meta["s"]), True
        except (TypeError, ValueError):
            return None
    if "t" in meta:
        try:
            return int(meta["t"]), False
        except (TypeError, ValueError):
            return None
    return None


def splitte_electrum_server(
    servers: dict,
) -> tuple[list[tuple[str, int, bool]], list[tuple[str, int, bool]]]:
    """Teilt die Electrum-Liste in Onion- und Clearnet-Endpunkte."""
    onions: list[tuple[str, int, bool]] = []
    clearnet: list[tuple[str, int, bool]] = []
    for roh, meta in servers.items():
        host = normalize_host(str(roh))
        if not host:
            continue
        ende = electrum_endpunkt(meta)
        if ende is None:
            continue
        port, use_ssl = ende
        ziel = onions if host.endswith(".onion") else clearnet
        ziel.append((host, port, use_ssl))
    onions.sort(key=lambda e: e[0])
    clearnet.sort(key=lambda e: e[0])
    return onions, clearnet


def load_electrum_servers(path: Path = ELECTRUM_SERVERS_FILE) -> dict[str, dict]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Electrum-Serverliste fehlt: {path}\n"
            "Lade electrum_servers.json aus dem Electrum-Repo nach."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Ungueltiges Format in {path}")
    return data


