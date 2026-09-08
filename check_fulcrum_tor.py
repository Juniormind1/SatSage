#!/usr/bin/env python3
"""Verbindungstest und .env-Vorschlaeger fuer Fulcrum.

Testet LAN/Tor aus .env, scannt bei Bedarf electrum_servers.json (nur .onion)
und gibt bis zu 10 erreichbare Onion-Server als nummerierte .env-Eintraege aus. main.py nutzt nur manuell gesetzte .env-Werte."""

from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from datetime import datetime, timezone
import json
import socket
import ssl
import struct
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"
ELECTRUM_SERVERS_FILE = Path(__file__).resolve().parent / "electrum_servers.json"
ELECTRUM_SERVERS_URL = (
    "https://raw.githubusercontent.com/spesmilo/electrum/master/"
    "electrum/chains/mainnet/servers.json"
)
ELECTRUM_SERVERS_GITHUB_COMMITS_URL = (
    "https://api.github.com/repos/spesmilo/electrum/commits"
    "?path=electrum/chains/mainnet/servers.json&sha=master&per_page=1"
)
ELECTRUM_SERVERS_DOWNLOAD_TIMEOUT = 30
DEFAULT_FULCRUM_PORT = 50002
LAN_TIMEOUT = 8
TOR_TIMEOUT = 30
PUBLIC_SCAN_TIMEOUT = 8
PUBLIC_SCAN_WORKERS = 6
MAX_PUBLIC_ONION_SERVERS = 10
TOR_PROXY_CHECK_TIMEOUT = 2
TOR_BROWSER_SOCKS_HOST = "127.0.0.1"
TOR_BROWSER_SOCKS_PORT = 9150
TOR_EXPERT_SOCKS_PORT = 9050
TOR_BROWSER_DOWNLOAD = "https://www.torproject.org/download/"
CLIENT_NAME = "SatSage-check"
PROTOCOL_VERSION = "1.4"

TOR_ONION_SOCKS_ERRORS = {
    0xF0: (
        "Onion-Dienst im Tor-Netz nicht gefunden — "
        "Adresse falsch, Tor/Fulcrum auf Start9 offline, oder Hidden Service nicht angelegt"
    ),
    0xF1: "Onion-Descriptor ungueltig",
    0xF2: (
        "Onion-Introduction fehlgeschlagen — "
        "Fulcrum laeuft nicht oder Hidden Service noch nicht veroeffentlicht"
    ),
    0xF3: "Onion-Rendezvous fehlgeschlagen",
    0xF4: "Onion-Dienst erfordert Client-Autorisierung (fehlt)",
    0xF5: "Onion-Client-Autorisierung abgelehnt",
}

SOCKS5_ERRORS = {
    0x01: "allgemeiner SOCKS-Fehler",
    0x02: "Verbindung durch Ziel nicht erlaubt",
    0x03: "Netzwerk nicht erreichbar",
    0x04: "Host nicht erreichbar",
    0x05: "Verbindung abgelehnt",
    0x06: "TTL abgelaufen",
    0x07: "Befehl nicht unterstützt",
    0x08: "Adresstyp nicht unterstützt",
}


def load_dotenv(env_path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def parse_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no")


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


def parse_host_port(
    value: str | None,
    default_host: str,
    default_port: int,
) -> tuple[str, int]:
    if not value:
        return default_host, default_port

    raw = value.strip()
    if raw.startswith("[") and "]" in raw:
        host, _, port_part = raw[1:].partition("]")
        port = int(port_part.lstrip(":")) if port_part.startswith(":") else default_port
        return host, port

    if ":" in raw:
        host, port_str = raw.rsplit(":", 1)
        if port_str.isdigit():
            return host, int(port_str)

    return raw, default_port


def _prompt_yes_no(default_yes: bool = False) -> bool:
    try:
        answer = input().strip().lower()
    except EOFError:
        return False
    if not answer:
        return default_yes
    return answer in ("j", "ja", "y", "yes")




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


def maybe_refresh_electrum_servers_json(args) -> None:
    """Fragt nach Update der JSON-Liste; bei fehlender Datei automatisch laden."""
    if getattr(args, "no_public_fallback", False) and not args.onion_list_only:
        return

    if not ELECTRUM_SERVERS_FILE.is_file():
        print(f"{ELECTRUM_SERVERS_FILE.name} fehlt — lade Serverliste...", flush=True)
        fetch_electrum_servers_json()
        return

    if getattr(args, "no_pause", False):
        return

    print("Pruefe Alter der Serverliste (lokal vs. GitHub)...", flush=True)
    local_age = _format_age_days(_local_json_age_days())
    remote_age = _format_age_days(_remote_json_age_days())
    print(
        f"Lokal: {local_age} alt | GitHub: {remote_age} alt",
        flush=True,
    )
    print(
        "JSON-Serverliste aktualisieren? [j/N] (Enter = nein): ",
        end="",
        flush=True,
    )
    if _prompt_yes_no(default_yes=False):
        try:
            fetch_electrum_servers_json()
        except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            print(f"  ⚠️  Update fehlgeschlagen: {exc}", file=sys.stderr)
            print(f"  Nutze vorhandene {ELECTRUM_SERVERS_FILE.name}.", flush=True)


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


def configured_hosts(env: dict[str, str], args) -> set[str]:
    hosts: set[str] = set()
    # Nur explizite Fulcrum-Hosts — NODE_IP/RPCHOST sind Bitcoin Core RPC.
    for key in (args.host, env.get("FULCRUM_HOST")):
        if key:
            hosts.add(normalize_host(key))
    for key in (args.tor_host, env.get("FULCRUM_TOR")):
        if key:
            hosts.add(normalize_host(key))
    for index in range(MAX_PUBLIC_ONION_SERVERS):
        key = env.get(f"FULCRUM_TOR_{index}")
        if key:
            hosts.add(normalize_host(key))
    hosts.discard("")
    return hosts




def build_public_targets(
    servers: dict[str, dict],
    proxy_host: str,
    proxy_port: int,
    exclude_hosts: set[str],
    timeout: int,
) -> list[dict[str, object]]:
    """Nur .onion aus electrum_servers.json (via Tor). Pro Host: SSL vor TCP."""
    ordered_hosts = sorted(h for h in servers if h.endswith(".onion"))
    targets: list[dict[str, object]] = []
    for host in ordered_hosts:
        host_norm = normalize_host(host)
        if host_norm in exclude_hosts:
            continue
        meta = servers[host]
        use_tor = True
        variants: list[tuple[str, bool]] = []
        if "s" in meta:
            variants.append(("s", True))
        if "t" in meta:
            variants.append(("t", False))
        for key, use_ssl in variants:
            targets.append({
                "label": "Onion-List",
                "host": host_norm,
                "port": int(meta[key]),
                "use_ssl": use_ssl,
                "use_tor": use_tor,
                "timeout": timeout,
                "proxy_host": proxy_host,
                "proxy_port": proxy_port,
            })
    return targets


def resolve_targets(args, env: dict[str, str]) -> list[dict[str, object]]:
    port = args.port or int(env.get("FULCRUM_PORT", DEFAULT_FULCRUM_PORT))
    if args.no_ssl:
        use_ssl = False
    else:
        use_ssl = parse_bool(env.get("FULCRUM_SSL"), default=True)

    tor_proxy = args.tor_proxy or env.get("FULCRUM_TOR_PROXY") or env.get("TOR_PROXY")
    proxy_host, proxy_port = parse_host_port(tor_proxy, "127.0.0.1", 9050)

    # LAN-Fulcrum nur bei FULCRUM_HOST / --host — nicht NODE_IP (Bitcoin Core).
    lan_host = args.host or env.get("FULCRUM_HOST")
    tor_host = args.tor_host or env.get("FULCRUM_TOR")

    if lan_host:
        lan_host = normalize_host(lan_host)
    if tor_host:
        tor_host = normalize_host(tor_host)

    targets: list[dict[str, object]] = []

    if lan_host and not args.tor_only:
        targets.append({
            "label": "LAN",
            "host": lan_host,
            "port": port,
            "use_ssl": use_ssl,
            "use_tor": False,
            "timeout": args.lan_timeout,
        })

    if tor_host and not args.lan_only:
        tor_port_raw = env.get("FULCRUM_TOR_PORT", "").strip()
        tor_port = int(tor_port_raw) if tor_port_raw else port
        tor_ssl_raw = env.get("FULCRUM_TOR_SSL", "").strip()
        if tor_ssl_raw:
            tor_ssl = parse_bool(tor_ssl_raw, default=True)
        else:
            tor_ssl = use_ssl
        targets.append({
            "label": "Tor",
            "host": tor_host,
            "port": tor_port,
            "use_ssl": tor_ssl,
            "use_tor": True,
            "timeout": args.timeout,
        })

    if not targets:
        raise SystemExit(
            "Kein Fulcrum-Ziel konfiguriert. "
            "Trage FULCRUM_HOST (LAN) und/oder FULCRUM_TOR (.onion) in .env ein."
        )

    for target in targets:
        target["proxy_host"] = proxy_host
        target["proxy_port"] = proxy_port
        target["env_path"] = args.env

    return targets


def socks5_connect(
    proxy_host: str,
    proxy_port: int,
    dest_host: str,
    dest_port: int,
    timeout: int,
) -> socket.socket:
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        sock.sendall(b"\x05\x01\x00")
        greeting = sock.recv(2)
        if len(greeting) != 2 or greeting[0] != 0x05:
            raise ConnectionError("Ungültige SOCKS5-Antwort vom Tor-Proxy")

        if greeting[1] != 0x00:
            raise ConnectionError(
                f"SOCKS5-Authentifizierung fehlgeschlagen (Methode {greeting[1]})"
            )

        host_bytes = dest_host.encode("idna")
        request = (
            b"\x05\x01\x00\x03"
            + bytes([len(host_bytes)])
            + host_bytes
            + struct.pack(">H", dest_port)
        )
        sock.sendall(request)

        header = _recv_exact(sock, 4)
        if header[0] != 0x05:
            raise ConnectionError("Ungültige SOCKS5-Connect-Antwort")

        status = header[1]
        if status != 0x00:
            reason = TOR_ONION_SOCKS_ERRORS.get(status) or SOCKS5_ERRORS.get(
                status,
                f"unbekannter Status {status} (0x{status:02X})",
            )
            raise ConnectionError(f"SOCKS5-Connect fehlgeschlagen: {reason}")

        atyp = header[3]
        if atyp == 0x01:
            _recv_exact(sock, 4 + 2)
        elif atyp == 0x03:
            length = _recv_exact(sock, 1)[0]
            _recv_exact(sock, length + 2)
        elif atyp == 0x04:
            _recv_exact(sock, 16 + 2)
        else:
            raise ConnectionError(f"Unbekannter SOCKS5-Adresstyp: {atyp}")

        return sock
    except Exception:
        sock.close()
        raise


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("SOCKS5-Verbindung unerwartet geschlossen")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def open_fulcrum_socket(target: dict[str, object]) -> socket.socket | ssl.SSLSocket:
    host = str(target["host"])
    port = int(target["port"])
    use_ssl = bool(target["use_ssl"])
    use_tor = bool(target["use_tor"])
    proxy_host = str(target["proxy_host"])
    proxy_port = int(target["proxy_port"])
    timeout = int(target["timeout"])

    if use_tor:
        raw = socks5_connect(proxy_host, proxy_port, host, port, timeout)
    else:
        raw = socket.create_connection((host, port), timeout=timeout)

    if not use_ssl:
        return raw

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx.wrap_socket(raw, server_hostname=host)


def electrum_request(
    sock: socket.socket | ssl.SSLSocket,
    method: str,
    params: list | None = None,
) -> object:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or [],
    }
    sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

    buf = b""
    while not buf.endswith(b"\n"):
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("Fulcrum hat die Verbindung geschlossen")
        buf += chunk

    response = json.loads(buf.decode("utf-8"))
    if response.get("error"):
        err = response["error"]
        if isinstance(err, dict):
            raise RuntimeError(err.get("message", err))
        raise RuntimeError(str(err))
    return response.get("result")


def socks_proxy_reachable(
    proxy_host: str,
    proxy_port: int,
    timeout: int = TOR_PROXY_CHECK_TIMEOUT,
) -> bool:
    try:
        sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def proxy_label(host: str, port: int) -> str:
    if port == TOR_BROWSER_SOCKS_PORT and host in ("127.0.0.1", "localhost"):
        return "Tor Browser (portable)"
    if port == TOR_EXPERT_SOCKS_PORT and host in ("127.0.0.1", "localhost"):
        return "Tor Expert Bundle"
    return "Tor-Proxy (.env)"


def find_tor_proxy(
    configured_host: str,
    configured_port: int,
) -> tuple[str, int, str] | None:
    """Sucht einen laufenden Tor-SOCKS-Proxy: .env zuerst, dann Browser/Dienst."""
    from core.tor import erkenne_tor_socks

    found = erkenne_tor_socks((configured_host, configured_port))
    if found is None:
        return None
    proxy_host, proxy_port = found
    return proxy_host, proxy_port, proxy_label(proxy_host, proxy_port)


def print_tor_browser_hint(configured_host: str, configured_port: int) -> None:
    print("  ❌ Kein Tor-SOCKS-Proxy erreichbar")
    print("  💡 SatSage startet Tor selbst, wenn ein Binary da ist")
    print("     (tor im Tor-Browser-Ordner bzw. Tor Browser.app, ohne Fenster).")
    print(f"     Sonst einmalig installieren: {TOR_BROWSER_DOWNLOAD}")
    print(
        f"     Oder TOR_BINARY setzen. Fallback-Proxy: "
        f"{TOR_BROWSER_SOCKS_HOST}:{TOR_EXPERT_SOCKS_PORT}"
    )
    if configured_port not in (TOR_BROWSER_SOCKS_PORT, TOR_EXPERT_SOCKS_PORT):
        print(
            f"     In .env steht {configured_host}:{configured_port}"
        )


def ensure_tor_proxy(target: dict[str, object]) -> dict[str, object] | None:
    from core.tor import TorFehler, stelle_tor_socks_bereit

    configured_host = str(target["proxy_host"])
    configured_port = int(target["proxy_port"])
    try:
        proxy_host, proxy_port = stelle_tor_socks_bereit(
            (configured_host, configured_port),
            log=lambda m: print(f"  {m}"),
        )
    except TorFehler as exc:
        print_tor_browser_hint(configured_host, configured_port)
        print(f"  {exc}")
        return None

    label = proxy_label(proxy_host, proxy_port)
    if (proxy_host, proxy_port) == (configured_host, configured_port):
        print(f"  ✅ {label} läuft ({proxy_host}:{proxy_port})")
    else:
        print(
            f"  ℹ️  {label} auf {proxy_host}:{proxy_port} "
            f"(.env: {configured_host}:{configured_port})"
        )

    updated = dict(target)
    updated["proxy_host"] = proxy_host
    updated["proxy_port"] = proxy_port
    return updated


def check_fulcrum(target: dict[str, object]) -> dict[str, object]:
    sock = open_fulcrum_socket(target)
    try:
        version = electrum_request(
            sock,
            "server.version",
            [CLIENT_NAME, PROTOCOL_VERSION],
        )
        banner = electrum_request(sock, "server.banner", [])
        try:
            electrum_request(
                sock,
                "blockchain.scripthash.listunspent",
                ["0" * 64],
            )
        except RuntimeError as exc:
            if "unknown method" in str(exc).lower():
                raise RuntimeError(
                    "listunspent nicht unterstützt (für UTXO-Scan ungeeignet)"
                ) from exc
            raise
        return {"version": version, "banner": banner}
    finally:
        sock.close()


def format_target_line(target: dict[str, object]) -> str:
    host = target["host"]
    port = target["port"]
    ssl_label = "SSL" if target["use_ssl"] else "TCP"
    if target["use_tor"]:
        return (
            f"{target['label']}: {host}:{port} ({ssl_label}) "
            f"via {target['proxy_host']}:{target['proxy_port']}"
        )
    return f"{target['label']}: {host}:{port} ({ssl_label})"


def print_plan(targets: list[dict[str, object]], public_fallback: bool) -> None:
    env_path = targets[0]["env_path"]
    print(f".env: {env_path}")
    if len(targets) == 2:
        print("Strategie: LAN zuerst, Tor als Fallback", end="")
    elif targets[0]["label"] == "LAN":
        print("Strategie: nur LAN", end="")
    else:
        print("Strategie: nur Tor", end="")
    if public_fallback:
        print(", dann Onion-Server aus electrum_servers.json")
    else:
        print()
    print()


def print_success(result: dict[str, object], target: dict[str, object]) -> None:
    print("  ✅ Fulcrum erreichbar")
    print(f"     server.version: {result['version']}")
    if result.get("banner"):
        print(f"     server.banner: {result['banner']}")


def print_env_suggestion(target: dict[str, object], own_node: bool) -> None:
    print()
    print("=" * 72)
    if own_node:
        print("Eigener Node erreichbar — .env ist korrekt konfiguriert.")
    print("=" * 72)


def dedupe_onion_hits(
    hits: list[tuple[dict[str, object], dict[str, object]]],
) -> list[tuple[dict[str, object], dict[str, object]]]:
    """Pro Host ein Eintrag; bei SSL+TCP wird SSL bevorzugt."""
    by_host: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
    for target, result in hits:
        host = str(target["host"])
        existing = by_host.get(host)
        if existing is None:
            by_host[host] = (target, result)
            continue
        if bool(target["use_ssl"]) and not bool(existing[0]["use_ssl"]):
            by_host[host] = (target, result)
    return [by_host[host] for host in sorted(by_host)]


def print_reachable_onion_servers(
    servers: list[tuple[dict[str, object], dict[str, object]]],
) -> None:
    print()
    print("=" * 72)
    print(
        f"Erreichbare Onion-Server ({len(servers)} von max. "
        f"{MAX_PUBLIC_ONION_SERVERS}):"
    )
    print("-" * 72)
    for index, (target, result) in enumerate(servers):
        ssl_label = "SSL" if target["use_ssl"] else "TCP"
        version = result.get("version", "?")
        print(
            f"  [{index}] {target['host']}:{target['port']} ({ssl_label}) "
            f"— {version}"
        )
    print("=" * 72)


def print_public_onion_env(
    servers: list[tuple[dict[str, object], dict[str, object]]],
) -> None:
    if not servers:
        return

    proxy_host = str(servers[0][0]["proxy_host"])
    proxy_port = int(servers[0][0]["proxy_port"])

    print()
    print("=" * 72)
    print(
        "Vorschlag fuer .env — oeffentliche Onion-Server fuer Rotation "
        f"(FULCRUM_TOR_0 … FULCRUM_TOR_{len(servers) - 1}):"
    )
    print("-" * 72)
    print(f"FULCRUM_TOR_PROXY={proxy_host}:{proxy_port}")
    for index, (target, _) in enumerate(servers):
        use_ssl = bool(target["use_ssl"])
        print(f"FULCRUM_TOR_{index}={target['host']}")
        print(f"FULCRUM_PORT_{index}={target['port']}")
        print(f"FULCRUM_SSL_{index}={'true' if use_ssl else 'false'}")
    print("-" * 72)
    print(
        "Hinweis: Oeffentliche Server — XPUBs/Adressen sind fuer den Betreiber "
        "sichtbar. Eigener Start9-Node ist privatsphaerer; Rotation verteilt "
        "Abfragen auf mehrere Betreiber."
    )
    print("=" * 72)



def _try_fulcrum_target(
    target: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]] | None:
    try:
        return target, check_fulcrum(target)
    except Exception:
        return None

def scan_public_servers(
    args,
    env: dict[str, str],
    proxy_host: str,
    proxy_port: int,
) -> list[tuple[dict[str, object], dict[str, object]]]:
    maybe_refresh_electrum_servers_json(args)

    try:
        servers = load_electrum_servers()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"\n⚠️  Electrum-Serverliste nicht nutzbar: {exc}", file=sys.stderr)
        return []

    tor_proxy = find_tor_proxy(proxy_host, proxy_port)
    if tor_proxy is None:
        print("\n[Fallback] Onion-Liste — Tor Browser noetig:")
        print_tor_browser_hint(proxy_host, proxy_port)
        return []

    proxy_host, proxy_port, label = tor_proxy
    print(f"\n[Fallback] Tor aktiv ({label}, {proxy_host}:{proxy_port})")

    onion_hosts = sorted(h for h in servers if h.endswith(".onion"))
    candidates = build_public_targets(
        servers,
        proxy_host,
        proxy_port,
        set(),
        args.public_timeout,
    )

    total = len(candidates)
    if total == 0:
        print("  Keine .onion-Server in electrum_servers.json.")
        return []

    workers = args.public_workers
    print(
        f"  Scanne {total} Kandidaten aus {len(onion_hosts)} .onion-Hosts in "
        f"{ELECTRUM_SERVERS_FILE.name} (max {workers} parallel, bis zu "
        f"{MAX_PUBLIC_ONION_SERVERS} erreichbare Hosts)..."
    )

    hits: list[tuple[dict[str, object], dict[str, object]]] = []
    hits_lock = threading.Lock()
    index_by_target = {id(t): i for i, t in enumerate(candidates, start=1)}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_try_fulcrum_target, target): target
            for target in candidates
        }
        for future in as_completed(futures):
            target = futures[future]
            index = index_by_target[id(target)]

            try:
                hit = future.result()
            except Exception:
                hit = None

            if hit is None:
                print(f"  [{index}/{total}] {format_target_line(target)} — nein")
                continue

            print(f"  [{index}/{total}] {format_target_line(target)} — OK")
            with hits_lock:
                hits.append(hit)

    reachable = dedupe_onion_hits(hits)[:MAX_PUBLIC_ONION_SERVERS]

    if not reachable:
        print("  Kein Onion-Server aus der Liste erreichbar.")
        return []

    print_reachable_onion_servers(reachable)
    print_public_onion_env(reachable)
    return reachable


def pause_before_exit() -> None:
    print("\nBeliebige Taste zum Beenden...", end="", flush=True)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.getch()
        else:
            input()
    except (EOFError, KeyboardInterrupt):
        pass


def describe_failure(target: dict[str, object], exc: Exception) -> str:
    if isinstance(exc, socket.timeout):
        return "Timeout — nicht erreichbar"
    if isinstance(exc, ConnectionError):
        return f"Verbindungsfehler: {exc}"
    if isinstance(exc, OSError):
        return f"Netzwerkfehler: {exc}"
    return f"Fehler: {exc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prüft Fulcrum aus .env — LAN, Tor, Onion-Liste."
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=ENV_FILE,
        help=f"Pfad zur .env-Datei (Default: {ENV_FILE})",
    )
    parser.add_argument(
        "--host",
        help="LAN-Host (überschreibt FULCRUM_HOST)",
    )
    parser.add_argument(
        "--tor-host",
        help="Onion-Host (überschreibt FULCRUM_TOR)",
    )
    parser.add_argument("--port", type=int, help="Fulcrum-Port (Default: 50002)")
    parser.add_argument(
        "--tor-proxy",
        help="SOCKS5-Proxy host:port (Default: 127.0.0.1:9050; Tor Browser: 9150)",
    )
    parser.add_argument(
        "--lan-only",
        action="store_true",
        help="Nur LAN testen, kein Tor-Fallback",
    )
    parser.add_argument(
        "--tor-only",
        action="store_true",
        help="Nur Tor testen, LAN überspringen",
    )
    parser.add_argument(
        "--no-ssl",
        action="store_true",
        help="Fulcrum ohne SSL (z. B. Port 50001)",
    )
    parser.add_argument(
        "--no-public-fallback",
        action="store_true",
        help="Keine Onion-Server aus electrum_servers.json durchsuchen",
    )
    parser.add_argument(
        "--onion-list-only",
        action="store_true",
        help="Nur Onion-Server aus electrum_servers.json testen (eigenen Node ueberspringen)",
    )
    parser.add_argument(
        "--lan-timeout",
        type=int,
        default=LAN_TIMEOUT,
        help=f"Timeout für LAN in Sekunden (Default: {LAN_TIMEOUT})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=TOR_TIMEOUT,
        help=f"Timeout für Tor in Sekunden (Default: {TOR_TIMEOUT})",
    )
    parser.add_argument(
        "--public-timeout",
        type=int,
        default=PUBLIC_SCAN_TIMEOUT,
        help=f"Timeout pro Onion-Server (Default: {PUBLIC_SCAN_TIMEOUT})",
    )
    parser.add_argument(
        "--public-workers",
        type=int,
        default=PUBLIC_SCAN_WORKERS,
        help=(
            f"Parallele Onion-Tests im Fallback (Default: {PUBLIC_SCAN_WORKERS}, "
            f"max. {MAX_PUBLIC_ONION_SERVERS} erreichbare Hosts)"
        ),
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Kein Warten am Ende (fuer Skripte/Terminal)",
    )
    args = parser.parse_args(argv)

    if args.lan_only and args.tor_only:
        parser.error("--lan-only und --tor-only schließen sich aus.")

    if args.onion_list_only and args.no_public_fallback:
        parser.error("--onion-list-only und --no-public-fallback schliessen sich aus.")

    env = load_dotenv(args.env)
    public_fallback = not args.no_public_fallback

    if args.onion_list_only:
        tor_proxy = (
            args.tor_proxy
            or env.get("FULCRUM_TOR_PROXY")
            or env.get("TOR_PROXY")
        )
        proxy_host, proxy_port = parse_host_port(tor_proxy, "127.0.0.1", 9050)
        print(f".env: {args.env}")
        print(f"Strategie: nur Onion-Server aus {ELECTRUM_SERVERS_FILE.name}\n")
        found = scan_public_servers(args, env, proxy_host, proxy_port)
        if not args.no_pause:
            pause_before_exit()
        return 0 if found else 1

    try:
        targets = resolve_targets(args, env)
    except SystemExit as exc:
        print(f"❌ {exc}", file=sys.stderr)
        exit_code = 2
    else:
        print_plan(targets, public_fallback)

        failures: list[str] = []
        exit_code = 1
        proxy_host = str(targets[0]["proxy_host"])
        proxy_port = int(targets[0]["proxy_port"])

        for index, target in enumerate(targets, start=1):
            prefix = f"[{index}/{len(targets)}] "
            print(f"{prefix}{format_target_line(target)}")

            if target["use_tor"]:
                ready_target = ensure_tor_proxy(target)
                if ready_target is None:
                    failures.append(
                        "Tor: Kein SOCKS-Proxy — Tor Browser (portable) starten"
                    )
                    if index < len(targets):
                        print()
                    continue
                target = ready_target

            try:
                result = check_fulcrum(target)
            except Exception as exc:
                message = describe_failure(target, exc)
                failures.append(f"{target['label']}: {message}")
                print(f"  ❌ {message}")
                if index < len(targets):
                    print("  → versuche Fallback...\n")
                continue

            print_success(result, target)
            print_env_suggestion(target, own_node=True)
            exit_code = 0
            break
        else:
            print("\nEigener Node nicht erreichbar — Onion-Serverliste als Fallback:\n")
            for failure in failures:
                print(f"   {failure}")

            if public_fallback:
                found = scan_public_servers(args, env, proxy_host, proxy_port)
                if found:
                    exit_code = 0
                else:
                    print(
                        "\n❌ Fulcrum weder eigen noch per Onion-Liste erreichbar.",
                        file=sys.stderr,
                    )
                    if any(t["use_tor"] for t in targets):
                        if not any("SOCKS-Proxy" in failure for failure in failures):
                            proxy = next(t for t in reversed(targets) if t["use_tor"])
                            print(
                                f"   Tor-Hinweis: Proxy {proxy['proxy_host']}:"
                                f"{proxy['proxy_port']} laeuft, Onion aber nicht erreichbar.",
                                file=sys.stderr,
                            )
            else:
                print(
                    "\n❌ Eigener Fulcrum nicht erreichbar.",
                    file=sys.stderr,
                )

    if not args.no_pause:
        pause_before_exit()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())