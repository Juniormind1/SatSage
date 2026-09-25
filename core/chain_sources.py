"""
Chain-Quellen: Fulcrum/Electrum/Onion-Rotation, BIP-158-Setup, Fetcher-Bindung.

Aus main.py ausgelagert (Slice 3 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.

Sanktions-Pools leben in ``core.sanctions_pool``; ``_setup_public_clearnet_fulcrum``
importiert den Clearnet-Pool lazy von dort (kein Top-Level-Zyklus).
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

from core.derivation import DEFAULT_MAX_ADDRESSES
from core.env_bootstrap import _load_dotenv
from core.paths import app_dir
from core.xpub_cache import (
    IMMUTABLE_CACHE_DIR,
    UTXO_CACHE_DIR,
    _fetch_utxos_for_addresses,
    _normalize_txid,
    load_cached_tx,
    load_xpub_verlauf_cache,
    resolve_immutable_cache_dir,
    save_cached_tx,
)

if TYPE_CHECKING:
    from core.wallet_context import WalletContext


DEFAULT_BIP158_START_HEIGHT = 481_824  # SegWit-Aktivierung; P2P-Filter ab hier

FULCRUM_CONNECT_TIMEOUT = 8

ELECTRUM_SERVERS_FILE = app_dir() / "electrum_servers.json"
MAX_PUBLIC_ONION_SERVERS = 10
MIN_PUBLIC_ONION_POOL = 3
PUBLIC_ONION_PROBE_WORKERS = 6
#: Setup-Latenz-Gate für öffentliches Onion-Electrs (Auto-Priorität).
#: Probe = eine ``get_history`` auf Dummy-Scripthash; darüber → BIP-158
#: bevorzugen bzw. Warnung/Abbruch. ``PUBLIC_ONION_LATENCY_SECONDS=0`` aus.
PUBLIC_ONION_LATENCY_GATE_SECONDS = 8.0


def wrap_get_tx_with_immutable_cache(
    fetch_tx,
    cache_root: Path,
    source: str,
    *,
    pool=None,
):
    """
    Umschließt get_tx: Flatfile-Cache → Live-Abfrage → persistieren.

    Mit *pool* trägt die zurückgegebene Funktion zusätzlich ein Attribut
    ``prefetch(txids)``: Es lädt mehrere Transaktionen parallel in den Cache.
    Die Herkunftsanalyse holt ihre Vorgänger anschließend wie gehabt einzeln —
    nur eben aus dem warmen Cache statt über das Netz. Reihenfolge und
    Ergebnis bleiben damit unverändert; allein die Wartezeit fällt weg.

    Als Attribut und nicht als weiterer Parameter, weil das Vorladen zur
    Datenquelle gehört und nicht zur Baumlogik — sonst müsste es durch jede
    Zwischenschicht gereicht werden.
    """

    def get_tx(txid: str) -> dict:
        cached = load_cached_tx(txid, cache_root)
        if cached is not None:
            return cached
        tx = fetch_tx(txid)
        save_cached_tx(txid, tx, cache_root, source)
        return tx

    if pool is not None and len(pool) > 1:
        get_tx.prefetch = _mache_prefetch(pool, cache_root, source)
    return get_tx


def _mache_prefetch(pool, cache_root: Path, source: str):
    """
    Baut einen parallelen Vorlader für Transaktionen.

    Lädt nur, was nicht schon im Cache liegt. Fehler werden geschluckt: Das
    Vorladen ist eine Beschleunigung, kein Abruf — was hier ausfällt, holt
    der reguläre Weg gleich danach einzeln nach und meldet dort seinen Fehler.
    """
    from core.fulcrum_history import fetch_tx_fulcrum
    from core.fulcrum_client import parallel_ueber_pool

    def prefetch(txids) -> None:
        fehlend = []
        gesehen = set()
        for txid in txids:
            key = _normalize_txid(txid)
            if key in gesehen:
                continue
            gesehen.add(key)
            if load_cached_tx(key, cache_root) is None:
                fehlend.append(key)
        if len(fehlend) < 2:
            return

        def hole(client, txid: str) -> None:
            tx = fetch_tx_fulcrum(client, txid)
            save_cached_tx(txid, tx, cache_root, source)

        parallel_ueber_pool(pool, fehlend, hole)

    return prefetch


def _normalize_fulcrum_host(value: str) -> str:
    """Host aus .env/CLI: ohne Schema, ohne Port (ausser .onion)."""
    raw = value.strip()
    for prefix in ("https://", "http://"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    # user:pass@host oder user@host (Start9/Copy-Paste)
    if "@" in raw:
        raw = raw.rsplit("@", 1)[-1]
    if ":" in raw and not raw.endswith(".onion"):
        host, port_str = raw.rsplit(":", 1)
        if port_str.isdigit():
            return host
    return raw


def _parse_tor_proxy(env: dict[str, str]) -> tuple[str, int]:
    raw = env.get("FULCRUM_TOR_PROXY") or env.get("TOR_PROXY") or "127.0.0.1:9050"
    value = raw.strip()
    if ":" in value:
        host, port_str = value.rsplit(":", 1)
        if port_str.isdigit():
            return host, int(port_str)
    return value, 9050


def _require_tor_proxy(env: dict[str, str]) -> tuple[str, int]:
    from core.jobs import aktueller_zwischenstand
    from core.tor import TOR_BROWSER_DOWNLOAD, TorFehler, stelle_tor_socks_bereit

    configured = _parse_tor_proxy(env)

    def _tor_log(meldung: str) -> None:
        print(f"  {meldung}", flush=True)
        stand = aktueller_zwischenstand()
        if stand is not None:
            stand.phase(meldung)

    try:
        return stelle_tor_socks_bereit(
            configured,
            env=env,
            log=_tor_log,
        )
    except TorFehler as exc:
        print(f"  {exc}", flush=True)
        print(f"     {TOR_BROWSER_DOWNLOAD}", flush=True)
        raise SystemExit(
            "Tor-Proxy nicht erreichbar — Binary fehlt oder Autostart aus"
        ) from exc


def _parse_env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no")


def resolve_verbose_from_env(env: dict[str, str], default: bool = False) -> bool:
    return _parse_env_bool(env.get("VERBOSE"), default=default)

def _env_port(env: dict[str, str], key: str, default: int = 50002) -> int:
    """
    Portnummer aus der .env — leere oder unlesbare Werte ergeben *default*.

    Eine leergeräumte Zeile (`FULCRUM_PORT=`) ist ein völlig normaler
    Zwischenzustand beim Bearbeiten der .env und darf keine Abfrage mit
    einem ValueError abbrechen.
    """
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _default_fulcrum_port(args, env: dict[str, str]) -> int:
    if getattr(args, "fulcrum_port", None):
        return int(args.fulcrum_port)
    if env.get("FULCRUM_PORT"):
        return int(env["FULCRUM_PORT"])
    return 50002


def _default_fulcrum_ssl(args, env: dict[str, str]) -> bool:
    if getattr(args, "fulcrum_no_ssl", False):
        return False
    return _parse_env_bool(env.get("FULCRUM_SSL"), default=True)


def _resolve_own_lan_endpoint(
    args,
    env: dict[str, str],
) -> tuple[str, int, bool] | None:
    """LAN-Fulcrum nur bei explizitem FULCRUM_HOST / --fulcrum-host / --rpchost.

    NODE_IP / RPCHOST sind Bitcoin-Core-RPC und werden hier bewusst nicht
    als Fulcrum-Fallback verwendet (eigener Fulcrum oft nur über Tor).
    """
    host_raw = (
        getattr(args, "fulcrum_host", None)
        or args.rpchost
        or env.get("FULCRUM_HOST")
    )
    if not host_raw:
        return None
    host = _normalize_fulcrum_host(host_raw)
    if host.endswith(".onion"):
        return None
    return host, _default_fulcrum_port(args, env), _default_fulcrum_ssl(args, env)


def _resolve_own_tor_endpoint(
    args,
    env: dict[str, str],
) -> tuple[str, int, bool] | None:
    host_raw = env.get("FULCRUM_TOR")
    if not host_raw:
        return None
    host = _normalize_fulcrum_host(host_raw)
    if not host.endswith(".onion"):
        return None
    port_raw = env.get("FULCRUM_TOR_PORT", "").strip()
    port = int(port_raw) if port_raw else _default_fulcrum_port(args, env)
    ssl_raw = env.get("FULCRUM_TOR_SSL", "").strip()
    if ssl_raw:
        use_ssl = _parse_env_bool(ssl_raw, default=True)
    else:
        use_ssl = _default_fulcrum_ssl(args, env)
    return host, port, use_ssl


def _load_public_onion_endpoints(
    args,
    env: dict[str, str],
) -> list[tuple[int, str, int, bool]]:
    """FULCRUM_TOR_0…9 aus .env; Rückgabe: (index, host, port, use_ssl)."""
    default_port = _default_fulcrum_port(args, env)
    default_ssl = _default_fulcrum_ssl(args, env)
    endpoints: list[tuple[int, str, int, bool]] = []
    for index in range(MAX_PUBLIC_ONION_SERVERS):
        host_raw = env.get(f"FULCRUM_TOR_{index}")
        if not host_raw:
            continue
        host = _normalize_fulcrum_host(host_raw)
        port_raw = env.get(f"FULCRUM_PORT_{index}")
        port = int(port_raw) if port_raw else default_port
        ssl_raw = env.get(f"FULCRUM_SSL_{index}")
        use_ssl = _parse_env_bool(ssl_raw, default_ssl) if ssl_raw else default_ssl
        endpoints.append((index, host, port, use_ssl))
    return endpoints


def _format_fulcrum_route(use_ssl: bool, tor_proxy: tuple[str, int] | None) -> str:
    route = "SSL" if use_ssl else "TCP"
    if tor_proxy:
        route += f", via Tor {tor_proxy[0]}:{tor_proxy[1]}"
    return route


def _probe_public_onion_endpoint(
    index: int,
    host: str,
    port: int,
    use_ssl: bool,
    tor_proxy: tuple[str, int],
) -> tuple[int, object | None, str | None]:
    from core.fulcrum_client import FULCRUM_ONION_TIMEOUT, connect_fulcrum

    client, error = connect_fulcrum(
        host,
        port,
        use_ssl=use_ssl,
        timeout=FULCRUM_ONION_TIMEOUT,
        tor_proxy=tor_proxy,
        require_listunspent=True,
    )
    return index, client, error


def tls_should_try_opposite(error: str | None) -> bool:
    """
    Ob nach Fehlversuch die andere TLS-Einstellung sinnvoll ist.

    Reine Netzfehler (Timeout, refused) nicht — da hilft SSL-Umschalten nicht.
    Protokoll-Mismatch (wrong version, EOF, SSL) und unklare Handshake-Fehler ja.
    """
    if not error:
        return False
    text = str(error).lower()
    if "listunspent" in text:
        return False
    if any(
        x in text
        for x in (
            "timed out",
            "timeout",
            "connection refused",
            "network is unreachable",
            "no route to host",
            "name or service not known",
            "nodename nor servname",
            "getaddrinfo failed",
            "temporary failure in name resolution",
        )
    ):
        return False
    return True


def connection_error_hint(error: str | None, use_ssl: bool) -> str | None:
    """
    Übersetzt typische Verbindungsfehler in einen umsetzbaren Hinweis.

    Ein Protokoll-Mismatch sieht sonst aus wie ein reines Erreichbarkeits-
    problem: Wer FULCRUM_SSL=true gegen einen Node ohne TLS stellt, sieht nur
    „nicht erreichbar" und sucht an der falschen Stelle.
    """
    if not error:
        return None
    text = str(error).lower()

    if use_ssl and "wrong version number" in text:
        return (
            "TLS-Handshake fehlgeschlagen — der Port spricht vermutlich kein SSL. "
            "SatSage probiert beim nächsten Check ohne TLS und schreibt es fest."
        )
    if use_ssl and "certificate verify failed" in text:
        return (
            "Zertifikat nicht überprüfbar — bei öffentlichen Hosts prüft SatSage "
            "streng. Heimnetz/LAN bleibt ohne CA-Prüfung; für öffentliche "
            "Self-Signed-Ziele: SATSAGE_TLS_INSECURE=1."
        )
    if not use_ssl and ("unexpected eof" in text or "not enough data" in text):
        return (
            "Verbindung ohne TLS abgebrochen — der Port erwartet vermutlich SSL. "
            "SatSage probiert beim nächsten Check mit TLS und schreibt es fest."
        )
    if "connection refused" in text:
        return "Port geschlossen — läuft Fulcrum, und stimmt FULCRUM_PORT?"
    return None


def _print_connection_error(prefix: str, error: str | None, use_ssl: bool) -> None:
    """Meldet einen Verbindungsfehler samt Hinweis, falls einer ableitbar ist."""
    print(f"{prefix}nicht erreichbar: {error}", flush=True)
    hint = connection_error_hint(error, use_ssl)
    if hint:
        print(f"     ↳ {hint}", flush=True)


def _print_public_onion_probe_result(
    index: int,
    host: str,
    port: int,
    use_ssl: bool,
    tor_proxy: tuple[str, int],
    client: object | None,
    error: str | None,
) -> None:
    route = _format_fulcrum_route(use_ssl, tor_proxy)
    label = f"[{index}] öffentlicher Server"
    target = f"{label}: {host}:{port} ({route})"
    if client:
        print(f"  → {target} — erreichbar", flush=True)
        return
    if error and "listunspent" in error:
        print(f"  → {target} — ungeeignet: {error}", flush=True)
    else:
        _print_connection_error(f"  → {target} — ", error, use_ssl)


def _try_fulcrum_endpoint(
    label: str,
    host: str,
    port: int,
    use_ssl: bool,
    tor_proxy: tuple[str, int] | None,
):
    route = _format_fulcrum_route(use_ssl, tor_proxy)
    print(f"Prüfe {label}: {host}:{port} ({route})...", flush=True)
    if tor_proxy:
        _index, client, error = _probe_public_onion_endpoint(
            0,
            host,
            port,
            use_ssl,
            tor_proxy,
        )
    else:
        from core.fulcrum_client import connect_fulcrum

        client, error = connect_fulcrum(
            host,
            port,
            use_ssl=use_ssl,
            timeout=FULCRUM_CONNECT_TIMEOUT,
            tor_proxy=None,
            require_listunspent=True,
        )
    # TLS ja/nein: bei Protokoll-Mismatch die andere Einstellung (LAN + Onion).
    if not client and error and tls_should_try_opposite(error):
        alt = not use_ssl
        print(
            f"  → {'TLS' if use_ssl else 'ohne TLS'} fehlgeschlagen "
            f"({error}) — versuche {'ohne TLS' if use_ssl else 'mit TLS'}…",
            flush=True,
        )
        if tor_proxy:
            _index, client, error = _probe_public_onion_endpoint(
                0, host, port, alt, tor_proxy,
            )
        else:
            from core.fulcrum_client import connect_fulcrum

            client, error = connect_fulcrum(
                host,
                port,
                use_ssl=alt,
                timeout=FULCRUM_CONNECT_TIMEOUT,
                tor_proxy=None,
                require_listunspent=True,
            )
        use_ssl = alt
    if client:
        print(
            f"  → {label} erreichbar"
            + (f" ({'TLS' if use_ssl else 'ohne TLS'})"),
            flush=True,
        )
        return client
    if error and "listunspent" in error:
        print(f"  → ungeeignet: {error}", flush=True)
    else:
        _print_connection_error("  → ", error, use_ssl)
    return None


def _is_private_fulcrum_host(host: str) -> bool:
    import ipaddress

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def _build_clearnet_fulcrum_targets(
    servers: dict[str, dict],
    exclude_hosts: set[str],
) -> list[tuple[str, int, bool]]:
    targets: list[tuple[str, int, bool]] = []
    for host in sorted(servers):
        if host.endswith(".onion"):
            continue
        host_norm = _normalize_fulcrum_host(host)
        if host_norm in exclude_hosts or _is_private_fulcrum_host(host_norm):
            continue
        meta = servers[host]
        if "s" in meta:
            targets.append((host_norm, int(meta["s"]), True))
        elif "t" in meta:
            targets.append((host_norm, int(meta["t"]), False))
    return targets


def _probe_clearnet_fulcrum(
    host: str,
    port: int,
    use_ssl: bool,
    timeout: int,
) -> tuple[object, float] | None:
    from core.fulcrum_client import connect_fulcrum
    from core.fulcrum_history import (
        SANCTIONS_HISTORY_PROBE_HEIGHT,
        supports_historical_headers,
    )

    started = time.monotonic()
    client, _error = connect_fulcrum(
        host,
        port,
        use_ssl=use_ssl,
        timeout=timeout,
        require_listunspent=True,
    )
    if not client:
        return None
    if not supports_historical_headers(client, SANCTIONS_HISTORY_PROBE_HEIGHT):
        client.close()
        return None
    latency = time.monotonic() - started
    return client, latency


def _dedupe_clearnet_fulcrum_hits(
    hits: list[tuple[object, float]],
) -> list[tuple[object, float]]:
    """Pro Host der schnellste Treffer; sortiert nach Latenz."""
    by_host: dict[str, tuple[object, float]] = {}
    for client, latency in hits:
        host = str(getattr(client, "host", ""))
        if not host:
            continue
        existing = by_host.get(host)
        if existing is None or latency < existing[1]:
            by_host[host] = (client, latency)
    return sorted(by_host.values(), key=lambda item: item[1])


#: Zusätzliche Verbindungen zum eigenen Node für den parallelen Wallet-Scan.
#:
#: Vier ist bewusst zurückhaltend: Ein Fulcrum im LAN verträgt deutlich mehr,
#: aber der Nutzen flacht schnell ab, und der Node gehört jemandem, der ihn
#: vielleicht noch für anderes braucht.
SCAN_POOL_WORKERS = 4


def _open_scan_pool(client, workers: int = SCAN_POOL_WORKERS):
    """
    Öffnet weitere Verbindungen zum selben Server für parallele Scans.

    Ein FulcrumClient hält einen Socket und verträgt keine gleichzeitigen
    Anfragen; ohne zusätzliche Verbindungen bliebe jeder Scan sequenziell.

    **Nur eigener Einzel-Client.** `RotatingFulcrumPool` (öffentliche
    Onions/Clearnet) hat keinen einzelnen Host/Port — `.host` ist nur ein
    Label. Extra-Verbindungen dorthin wären falsch; der Scan bleibt dann
    bei der einen Rotation.

    **Nicht über Tor.** Jede weitere Verbindung wäre ein eigener Circuit —
    langsam im Aufbau und unnötige Last für das Netz. Dort bleibt es beim
    einen Socket.

    Schlägt das Öffnen fehl, gibt es keinen Pool und der Scan läuft wie
    bisher. Ein langsamer Scan ist besser als gar keiner.
    """
    from core.fulcrum_client import FulcrumClient, SanctionsClearnetPool, connect_fulcrum

    if not isinstance(client, FulcrumClient) or client.tor_proxy:
        return None
    if workers < 2:
        return None

    clients = [client]
    for _ in range(workers - 1):
        weiterer, _fehler = connect_fulcrum(
            client.host,
            client.port,
            use_ssl=client.use_ssl,
            timeout=client.timeout,
        )
        if not weiterer:
            break
        clients.append(weiterer)

    if len(clients) < 2:
        return None
    return SanctionsClearnetPool(clients)


def _setup_public_onion_rotation(
    args,
    env: dict[str, str],
    *,
    interactive: bool = True,
):
    from core.fulcrum_client import RotatingFulcrumPool

    endpoints = _load_public_onion_endpoints(args, env)
    if not endpoints:
        raise SystemExit(
            "Eigener Fulcrum nicht erreichbar und keine FULCRUM_TOR_0… "
            "in .env konfiguriert. "
            "Nutze check_fulcrum_tor.py --onion-list-only für Vorschläge."
        )

    tor_proxy = _require_tor_proxy(env)
    workers = min(PUBLIC_ONION_PROBE_WORKERS, len(endpoints))
    print(
        f"\nEigener Node nicht erreichbar — prüfe "
        f"{len(endpoints)} öffentliche Server (FULCRUM_TOR_0…, "
        f"max. {workers} parallel):",
        flush=True,
    )

    endpoint_by_index = {
        index: (host, port, use_ssl)
        for index, host, port, use_ssl in endpoints
    }
    reachable_by_index: dict[int, object] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _probe_public_onion_endpoint,
                index,
                host,
                port,
                use_ssl,
                tor_proxy,
            ): index
            for index, host, port, use_ssl in endpoints
        }
        for future in as_completed(futures):
            index = futures[future]
            host, port, use_ssl = endpoint_by_index[index]
            try:
                _index, client, error = future.result()
            except Exception as exc:
                client, error = None, str(exc)
            _print_public_onion_probe_result(
                index,
                host,
                port,
                use_ssl,
                tor_proxy,
                client,
                error,
            )
            if client:
                reachable_by_index[index] = client

    reachable_clients = [
        reachable_by_index[index]
        for index in sorted(reachable_by_index)
    ]

    if not reachable_clients:
        raise SystemExit(
            "Kein öffentlicher Fulcrum-Server erreichbar. "
            "Tor Browser/Proxy prüfen oder check_fulcrum_tor.py ausführen."
        )

    configured = len(endpoints)
    reachable_count = len(reachable_clients)
    if reachable_count < MIN_PUBLIC_ONION_POOL:
        print(
            f"\n⚠️  Nur {reachable_count} von {configured} Server(n) erreichbar "
            f"(empfohlen: mindestens {MIN_PUBLIC_ONION_POOL}).",
            flush=True,
        )
        print(
            "Mit wenigen Servern ist die Privatsphäre-Rotation eingeschränkt.",
            flush=True,
        )
        if interactive:
            print("Trotzdem fortfahren? [j/N]: ", end="", flush=True)
            from interact import prompt_yes_no

            if not prompt_yes_no(default_yes=False):
                for client in reachable_clients:
                    client.close()
                raise SystemExit("Abgebrochen.")

    _log_quelle(
        f"Datenquelle: öffentliche Electrum-Server "
        f"(Onion-Rotation, {reachable_count} von {configured} erreichbar)"
    )
    return RotatingFulcrumPool(reachable_clients)


#: Letzte _log_quelle-Zeile (Dedup bei Watch/Reconnect/Setup-Wiederholung).
_quelle_log_zuletzt: str = ""
_quelle_log_lock = threading.Lock()


def _log_quelle(text: str) -> None:
    """
    Eine Zeile nach stdout und in den Web-Log.

    „Datenquelle: …“ nur für die wirklich gewählte Quelle — nicht für
    fehlgeschlagene Probes der Prioritätskette.

    Identische Zeilen und erneute „Priorität…“ nach bereits gewählter Quelle
    werden unterdrückt (sonst spammt Herkunft/Wallet-Watch das Log alle paar
    Sekunden mit derselben Datenquellen-Zeile).
    """
    global _quelle_log_zuletzt
    zeile = (text or "").strip()
    if not zeile:
        return
    with _quelle_log_lock:
        if zeile == _quelle_log_zuletzt:
            return
        # Schon eine Quelle gemeldet → erneute Prioritäts-Ansage weglassen,
        # bis etwas anderes (Fehler/andere Quelle) den Stand ändert.
        if (
            zeile == "Automatische Datenquellen-Priorität…"
            and _quelle_log_zuletzt.startswith("Datenquelle:")
        ):
            return
        _quelle_log_zuletzt = zeile
    print(zeile, flush=True)
    from display import melde_zwischenstand

    melde_zwischenstand(zeile)


def _reset_quelle_log() -> None:
    """Für Tests: Dedup-Zustand leeren."""
    global _quelle_log_zuletzt
    with _quelle_log_lock:
        _quelle_log_zuletzt = ""


def _try_own_fulcrum_client(args, env: dict[str, str]):
    """Priorität 1: eigener Fulcrum (LAN, dann Tor)."""
    lan = _resolve_own_lan_endpoint(args, env)
    if lan:
        host, port, use_ssl = lan
        client = _try_fulcrum_endpoint(
            "eigener Fulcrum-Node (LAN)",
            host,
            port,
            use_ssl,
            None,
        )
        if client:
            _log_quelle(
                f"Datenquelle: eigener Electrum-Server (LAN) {host}:{port}"
            )
            return client

    tor = _resolve_own_tor_endpoint(args, env)
    if tor:
        host, port, use_ssl = tor
        tor_proxy = _require_tor_proxy(env)
        client = _try_fulcrum_endpoint(
            "eigener Fulcrum-Node (Tor)",
            host,
            port,
            use_ssl,
            tor_proxy,
        )
        if client:
            _log_quelle(
                f"Datenquelle: eigener Electrum-Server (Tor) {host}:{port}"
            )
            return client
    return None


def _try_bip158_backend(args, env: dict[str, str]):
    """Priorität 2: Compact Filter über Bitcoin-P2P (kein eigener Core)."""
    if env.get("BIP158_P2P", "1").strip() in ("0", "false", "nein", "off"):
        return None
    try:
        return _setup_bip158_client(args, env, raise_on_error=False)
    except (SystemExit, RuntimeError) as exc:
        _log_quelle(f"→ P2P-BIP-158 nicht erreichbar: {exc}")
        return None


def try_bip158_fetch_for_tip_sync(
    args,
    env: dict[str, str] | None = None,
    wallet_ctx: "WalletContext | None" = None,
    *,
    immutable_cache_dir: Path | None = None,
):
    """
    Optionaler BIP-158-``fetch_wallet_utxos`` für Tip-Nachzug.

    Unabhängig von der aktiven allgemeinen Datenquelle (Electrs/Core).
    ``None``, wenn Compact-Filter-Peers fehlen oder ``BIP158_P2P=0``.
    """
    env = env or _load_dotenv()
    backend = _try_bip158_backend(args, env)
    if backend is None:
        return None
    fetchers = _build_blockchain_fetchers(
        "bip158",
        backend,
        args,
        wallet_ctx,
        immutable_cache_dir=immutable_cache_dir,
    )
    return fetchers.get("fetch_wallet_utxos")


def _try_public_onion_fulcrum(
    args,
    env: dict[str, str],
    *,
    interactive: bool = False,
):
    """Öffentliche Fulcrum-Onions — nur wenn Clearnet öffentlich fehlt."""
    if not _load_public_onion_endpoints(args, env):
        return None
    try:
        return _setup_public_onion_rotation(args, env, interactive=interactive)
    except SystemExit as exc:
        _log_quelle(f"→ öffentliche Onion-Server nicht nutzbar: {exc}")
        return None


def _public_onion_latency_limit(env: dict[str, str]) -> float | None:
    """
    Schwelle in Sekunden für das Onion-Latenz-Gate.

    ``None`` = Gate aus (``PUBLIC_ONION_LATENCY_SECONDS=0`` / negativ).
    """
    raw = (env.get("PUBLIC_ONION_LATENCY_SECONDS") or "").strip()
    if raw:
        try:
            val = float(raw.replace(",", "."))
        except ValueError:
            val = PUBLIC_ONION_LATENCY_GATE_SECONDS
        if val <= 0:
            return None
        return val
    return PUBLIC_ONION_LATENCY_GATE_SECONDS


def _measure_onion_get_history_latency(backend) -> float | None:
    """
    Eine Probe-``get_history`` (Dummy-Scripthash) und Wandzeit in Sekunden.

    Ohne Retries — das Gate soll schnell entscheiden, nicht 3×30 s hängen.
    ``None`` bei Fehler (dann gilt der Pool nicht als „zu langsam“).
    """
    from core.fulcrum_client import _PROBE_SCRIPT_HASH

    clients = getattr(backend, "_clients", None)
    client = clients[0] if clients else backend
    t0 = time.monotonic()
    try:
        once = getattr(client, "_request_once", None)
        if callable(once):
            lock = getattr(client, "_lock", None)
            if lock is not None:
                with lock:
                    once(
                        "blockchain.scripthash.get_history",
                        [_PROBE_SCRIPT_HASH],
                    )
            else:
                once(
                    "blockchain.scripthash.get_history",
                    [_PROBE_SCRIPT_HASH],
                )
        else:
            backend.request(
                "blockchain.scripthash.get_history",
                [_PROBE_SCRIPT_HASH],
            )
    except Exception:
        return None
    return time.monotonic() - t0


def _nach_oeffentlichem_onion_latenz(
    pool,
    args,
    env: dict[str, str],
    *,
    allow_bip158_fallback: bool,
    interactive: bool,
) -> tuple[str, object] | None:
    """
    Latenz-Gate nur für Auto-Priorität (öffentliches Onion nach BIP-158-Fail).

    Zu langsam + BIP-158 erreichbar → BIP-158 binden (kein Mid-Scan-Hop).
    Zu langsam ohne BIP-158 → klare Warnung; interaktiv Abbruch möglich.
    Explizites ``--rpc-only`` (``allow_bip158_fallback=False``) überspringt
    das Gate.
    """
    if not allow_bip158_fallback:
        return "fulcrum", pool

    limit = _public_onion_latency_limit(env)
    if limit is None:
        return "fulcrum", pool

    _log_quelle("Prüfe Latenz öffentliches Onion-Electrs…")
    sekunden = _measure_onion_get_history_latency(pool)
    if sekunden is None:
        return "fulcrum", pool
    if sekunden <= limit:
        return "fulcrum", pool

    _log_quelle(
        f"Öffentliches Onion-Electrs langsam "
        f"(Probe {sekunden:.1f}s > {limit:.0f}s)."
    )

    bip = _try_bip158_backend(args, env)
    if bip:
        try:
            pool.close()
        except Exception:
            pass
        _log_quelle(
            "→ wechsle zu BIP-158 Compact Filter "
            "(Onion für diese Session zu langsam)."
        )
        return "bip158", bip

    _log_quelle(
        "Onion ist die einzige Option und wird langsam — "
        "Scan kann sehr lange dauern."
    )
    if interactive:
        print("Trotzdem fortfahren? [j/N]: ", end="", flush=True)
        from interact import prompt_yes_no

        if not prompt_yes_no(default_yes=False):
            try:
                pool.close()
            except Exception:
                pass
            _log_quelle("Abgebrochen (Onion zu langsam).")
            return None
    return "fulcrum", pool


def _setup_public_clearnet_fulcrum(args, env: dict[str, str]):
    """Öffentliche Fulcrum-Server über Clearnet (vor öffentlichem Onion)."""
    from core.fulcrum_client import RotatingFulcrumPool

    # Vor der Suche ansagen — sonst wiederholt der 10s-Herzschlag die
    # letzte Probe, während Clearnet nur nach stdout schreibt.
    _log_quelle("Suche öffentliche Electrum-Server (Clearnet)…")
    # Sanctions-Pool in core.sanctions_pool; lazy, kein Top-Level-Zyklus.
    from core.sanctions_pool import resolve_sanctions_clearnet_pool

    pool, _from_cache = resolve_sanctions_clearnet_pool(env)
    if pool is None:
        _log_quelle("→ kein Clearnet-Electrum für Wallet-Zugriff gefunden")
        return None
    clients = [pool.client_at(worker_id) for worker_id in range(len(pool))]
    _log_quelle(
        f"Datenquelle: öffentliche Electrum-Server "
        f"(Clearnet, {len(clients)} Server)"
    )
    # Tor-Autostart für öffentliche Onions nicht als Flaschenhals stehen lassen.
    try:
        from core.source import _loese_oeffentliches_onion_tor

        _loese_oeffentliches_onion_tor(on_log=_log_quelle)
    except Exception:
        pass
    return RotatingFulcrumPool(clients)


def _try_data_source_priority_chain(
    args,
    env: dict[str, str],
    *,
    include_bip158: bool = True,
    interactive_onion: bool = False,
):
    """
    Automatische Datenquelle in Prioritätsreihenfolge.
    1. eigener Electrum-Server (Fulcrum/electrs), 2. P2P-BIP-158.
    Öffentliche Electrum nur nach Bestätigung: Clearnet vor Onion.
    """
    _log_quelle("Automatische Datenquellen-Priorität…")

    client = _try_own_fulcrum_client(args, env)
    if client:
        return "fulcrum", client, None

    if include_bip158:
        backend = _try_bip158_backend(args, env)
        if backend:
            return "bip158", backend, None

    erlaubt = _oeffentliche_electrum_erlaubt(env, args)
    if not erlaubt and interactive_onion:
        print(
            "\nCompact Filter (BIP-158) haben keine Peers geliefert. "
            "Öffentliche Electrum-Server (Onion oder Clearnet) sehen die "
            "abgeleiteten Wallet-Adressen.",
            flush=True,
        )
        print("Trotzdem verbinden? [j/N]: ", end="", flush=True)
        from interact import prompt_yes_no

        if prompt_yes_no(default_yes=False):
            erlaubt = True
            if args is not None:
                args.oeffentliche_electrum = True
    if not erlaubt:
        _log_quelle(
            "Öffentliche Electrum-Server nicht genutzt (Bestätigung fehlt)."
        )
        return None

    # Clearnet vor öffentlichem Onion: nach Opt-in kein Tor-Flaschenhals,
    # solange Clearnet-Electrs erreichbar sind.
    pool = _setup_public_clearnet_fulcrum(args, env)
    if pool:
        return "fulcrum", pool, None

    pool = _try_public_onion_fulcrum(args, env, interactive=interactive_onion)
    if pool:
        gewählt = _nach_oeffentlichem_onion_latenz(
            pool,
            args,
            env,
            allow_bip158_fallback=include_bip158,
            interactive=interactive_onion,
        )
        if gewählt:
            return gewählt[0], gewählt[1], None
        return None

    return None


def _try_public_electrum_fuer_verlauf(
    args,
    env: dict[str, str],
    *,
    interactive_onion: bool = False,
    allow_bip158_fallback: bool = True,
):
    """Öffentliche Electrum-Server für Verlauf — nur nach Bestätigung."""
    erlaubt = _oeffentliche_electrum_erlaubt(env, args)
    if not erlaubt and interactive_onion:
        print(
            "\nFür den Verlaufsscan fehlt ein eigener Electrum-Server "
            "(und BIP-158 ist nicht nutzbar). Öffentliche Electrum-Server "
            "sehen die abgeleiteten Wallet-Adressen.",
            flush=True,
        )
        print("Trotzdem verbinden? [j/N]: ", end="", flush=True)
        from interact import prompt_yes_no

        if prompt_yes_no(default_yes=False):
            erlaubt = True
            if args is not None:
                args.oeffentliche_electrum = True
    if not erlaubt:
        _log_quelle(
            "Verlauf: öffentliche Electrum-Server nicht genutzt "
            "(Bestätigung fehlt)."
        )
        return None

    pool = _setup_public_clearnet_fulcrum(args, env)
    if pool:
        _log_quelle(
            "Verlauf: öffentliche Electrum-Server (Clearnet) — get_history "
            "(Privatsphäre mäßig)."
        )
        return "fulcrum", pool

    pool = _try_public_onion_fulcrum(args, env, interactive=interactive_onion)
    if pool:
        gewählt = _nach_oeffentlichem_onion_latenz(
            pool,
            args,
            env,
            allow_bip158_fallback=allow_bip158_fallback,
            interactive=interactive_onion,
        )
        if not gewählt:
            return None
        quelle, backend = gewählt
        if quelle == "bip158":
            _log_quelle(
                "Verlauf: BIP-158 Compact Filter — Historie per "
                "Blockwalk/Cache (Onion zu langsam)."
            )
            return quelle, backend
        _log_quelle(
            "Verlauf: öffentliche Electrum-Server (Onion) — get_history "
            "(Privatsphäre mäßig; Clearnet nicht erreichbar)."
        )
        return "fulcrum", backend
    return None


def _try_verlauf_priority_chain(
    args,
    env: dict[str, str],
    *,
    include_bip158: bool = True,
    interactive_onion: bool = False,
):
    """
    Datenquelle nur für den Verlaufsscan (Historie inkl. ausgegebener Outputs).

    Reihenfolge (anders als UTXO-Bestand — Core scantxoutset liefert keinen
    Verlauf):

    1. Electrs/Fulcrum im LAN (``get_history``)
    2. Electrs/Fulcrum über Onion
    3. BIP-158 Compact Filter (Blockwalk/Cache, kein get_history)
    4. öffentliche Electrum (Clearnet, sonst Onion) nach Bestätigung
    """
    _log_quelle("Verlaufsscan — eigene Datenquellen-Priorität…")

    lan = _resolve_own_lan_endpoint(args, env)
    if lan:
        host, port, use_ssl = lan
        client = _try_fulcrum_endpoint(
            "eigener Fulcrum-Node (LAN)",
            host,
            port,
            use_ssl,
            None,
        )
        if client:
            _log_quelle(
                f"Verlauf: eigener Electrum-Server (LAN) {host}:{port} "
                f"— get_history."
            )
            return "fulcrum", client

    tor = _resolve_own_tor_endpoint(args, env)
    if tor:
        host, port, use_ssl = tor
        tor_proxy = _require_tor_proxy(env)
        client = _try_fulcrum_endpoint(
            "eigener Fulcrum-Node (Tor)",
            host,
            port,
            use_ssl,
            tor_proxy,
        )
        if client:
            _log_quelle(
                f"Verlauf: eigener Electrum-Server (Tor) {host}:{port} "
                f"— get_history."
            )
            return "fulcrum", client

    if include_bip158:
        backend = _try_bip158_backend(args, env)
        if backend:
            _log_quelle(
                "Verlauf: BIP-158 Compact Filter — Electrs nicht erreichbar; "
                "Historie per Blockwalk/Cache."
            )
            return "bip158", backend

    return _try_public_electrum_fuer_verlauf(
        args,
        env,
        interactive_onion=interactive_onion,
        allow_bip158_fallback=include_bip158,
    )


def _setup_verlauf_client(
    args,
    env: dict[str, str] | None = None,
    *,
    interactive_onion: bool = False,
):
    """
    Wählt die Datenquelle für den Verlaufsscan.

    Siehe ``_try_verlauf_priority_chain``. Nicht ``_setup_blockchain_client``:
    dessen Auto-Kette kann BIP-158 wählen und dann am fehlenden
    ``fetch_wallet_history`` scheitern.
    """
    env = env or _load_dotenv()

    if _data_source_is_explicit(args, env):
        if _wants_bip158(args, env):
            backend = _setup_bip158_client(args, env, raise_on_error=True)
            _log_quelle(
                "Verlauf: BIP-158 Compact Filter (explizit) — "
                "Historie per Blockwalk/Cache."
            )
            return "bip158", backend

        if _wants_fulcrum(args, env):
            result = _try_verlauf_priority_chain(
                args,
                env,
                include_bip158=False,
                interactive_onion=interactive_onion,
            )
            if result:
                return result[0], result[1]
            raise SystemExit(
                "Verlauf: Fulcrum/Electrs nicht erreichbar (eigener Node). "
                "Öffentliche Server nur nach Bestätigung "
                "(OEFFENTLICHE_ELECTRUM=1)."
            )
        raise SystemExit(
            "Verlauf: keine Datenquelle gewählt (--bip158 oder --rpc-only)."
        )

    result = _try_verlauf_priority_chain(
        args,
        env,
        include_bip158=True,
        interactive_onion=interactive_onion,
    )
    if result:
        return result[0], result[1]

    grund = (
        "Verlauf: keine Quelle mit Historie erreichbar "
        "(Electrs, BIP-158, öffentliche Electrum nur nach Bestätigung)."
    )
    _log_quelle(grund)
    raise SystemExit(grund)


def _oeffentliche_electrum_erlaubt(env: dict[str, str], args=None) -> bool:
    if args is not None and getattr(args, "oeffentliche_electrum", False):
        return True
    from core.source import oeffentliche_electrum_erlaubt

    return oeffentliche_electrum_erlaubt(env)


def _data_source_is_explicit(args, env: dict[str, str]) -> bool:
    """True wenn CLI oder manuelle Menüwahl die Datenquelle festlegen."""
    return bool(
        getattr(args, "bip158", False) or args.rpc_only
    )


def apply_data_source_choice(
    args,
    env: dict[str, str],
    choice: str,
    *,
    bip158_start: int | None = None,
) -> None:
    """Übernimmt die interaktive Datenquellen-Wahl in args."""
    args.bip158 = False
    args.rpc_only = False
    if choice == "bip158":
        args.bip158 = True
        if bip158_start is not None:
            args.bip158_start = bip158_start
    elif choice == "fulcrum":
        args.rpc_only = True
    else:
        raise ValueError(f"unbekannte Datenquelle: {choice}")


def _resolve_data_source(args, env: dict[str, str]) -> None:
    """Setzt args bei mehrdeutiger Quelle per interaktiver Abfrage."""
    if _data_source_is_explicit(args, env):
        return
    from interact import prompt_data_source

    choice = prompt_data_source()
    if choice is None:
        raise SystemExit("Keine Datenquelle gewählt.")
    apply_data_source_choice(args, env, choice)


def _wants_bip158(args, env: dict[str, str]) -> bool:
    """P2P-BIP-158 wenn --bip158 oder BIP158_P2P=1 (ohne 0)."""
    if getattr(args, "bip158", False):
        return True
    return _parse_env_bool(env.get("BIP158_P2P"), default=False)


def _wants_fulcrum(args, env: dict[str, str]) -> bool:
    """Fulcrum wenn --rpc-only (oder nach interaktiver Auswahl)."""
    if _wants_bip158(args, env):
        return False
    if args.rpc_only:
        return True
    return True


def _setup_bip158_client(args, env: dict[str, str], *, raise_on_error: bool = True):
    from core.bip158_scan import verify_p2p_filters
    from core.bip158_wallet import (
        create_bip158_client_from_env,
        fetch_address_utxos_bip158,
        fetch_addresses_utxos_bip158,
        fetch_tx_p2p_mit_fallback,
        fetch_wallet_utxos_bip158,
    )
    from core.bitcoind_rpc import stelle_tx_lookup_rollen

    if args.bip158_start is not None:
        start_height = args.bip158_start
    else:
        start_height = int(
            env.get("BIP158_START_HEIGHT", str(DEFAULT_BIP158_START_HEIGHT))
        )
    if raise_on_error:
        _log_quelle("Datenquelle: Bitcoin-P2P (BIP-158 Compact Filter)")
    else:
        _log_quelle("Prüfe P2P-BIP-158 (Compact Filter)…")
    cache = Path(getattr(args, "cache_dir", None) or UTXO_CACHE_DIR)
    client = create_bip158_client_from_env(
        env,
        start_height=start_height,
        verbose=resolve_verbose_from_env(env),
        cache_dir=cache,
    )
    try:
        tip = verify_p2p_filters(client)
        # Nach dem 1-Peer-Handshake Pool auf Scan-Ziel füllen (bis 4 / Tor 2).
        pool = client.scanner._ensure_peers()
    except RuntimeError as exc:
        if raise_on_error:
            raise SystemExit(f"P2P-BIP-158 nicht erreichbar: {exc}") from exc
        raise
    if not raise_on_error:
        _log_quelle("Datenquelle: Bitcoin-P2P (BIP-158 Compact Filter)")
    weg = "Tor" if client.scanner._tor_proxy else "Clearnet"
    n_peers = len(pool) if pool else 1
    wort = "Peer" if n_peers == 1 else "Peers"
    _log_quelle(f"→ {n_peers} Compact-Filter-{wort} über {weg}")
    tip_zeile = f"Chain-Tip: {tip:,}, BIP-158 ab Höhe {start_height:,}"
    _log_quelle(tip_zeile)

    def _bip158_fetch_wallet_utxos(
        addrs,
        xpubs=None,
        wallet=None,
        max_addr=DEFAULT_MAX_ADDRESSES,
        max_by=None,
        *,
        filter_scan=False,
        on_utxos_update=None,
    ):
        if filter_scan:
            return fetch_wallet_utxos_bip158(
                client,
                xpubs or args.xpubs,
                max_addresses=max_addr,
                max_addresses_by_xpub=max_by,
                on_utxos_update=on_utxos_update,
            )
        if addrs:
            return fetch_addresses_utxos_bip158(client, addrs)
        return fetch_wallet_utxos_bip158(
            client,
            xpubs or args.xpubs,
            max_addresses=max_addr,
            max_addresses_by_xpub=max_by,
            on_utxos_update=on_utxos_update,
        )

    # Core optional: lokal (UTXO-Slot) bis pruneheight, sonst Lookup (Start9).
    lokal_core = None
    archival_core = None
    lokal_prune = None
    try:
        lokal_core, archival_core, lokal_prune = stelle_tx_lookup_rollen(
            env, timeout=30.0,
        )
        if lokal_core is not None:
            ph = (
                f"pruneheight {lokal_prune}"
                if lokal_prune and lokal_prune > 0
                else "nicht gepruned"
            )
            _log_quelle(
                f"→ Core lokal für Tx/Block ({lokal_core.cfg.ziel}, {ph})"
            )
        if archival_core is not None:
            _log_quelle(
                f"→ Core-Lookup für Tx/Block ({archival_core.cfg.ziel})"
            )
        if lokal_core is None and archival_core is None:
            _log_quelle("→ kein Core-RPC für Tx-Lookup konfiguriert")
    except Exception as exc:
        _log_quelle(f"→ Core-RPC für Tx-Lookup nicht nutzbar: {exc}")

    def _get_tx_bip158(txid: str) -> dict:
        return fetch_tx_p2p_mit_fallback(
            client,
            txid,
            local_core=lokal_core,
            archival_core=archival_core,
            local_pruneheight=lokal_prune,
            on_log=_log_quelle,
        )

    return {
        "get_tx": _get_tx_bip158,
        "fetch_address_utxos": lambda addr: fetch_address_utxos_bip158(client, addr),
        "fetch_addresses_utxos": lambda addrs, **kw: fetch_addresses_utxos_bip158(
            client, addrs, **kw
        ),
        "fetch_addresses_utxos_utxoset": lambda addrs, **kw: fetch_addresses_utxos_bip158(
            client, addrs, **kw
        ),
        "verify_utxo_spent": None,
        "fetch_wallet_utxos": _bip158_fetch_wallet_utxos,
        "fulcrum": None,
        "client": client,
        "core_rpc": archival_core or lokal_core,
        "core_local": lokal_core,
        "core_archival": archival_core,
        "core_local_pruneheight": lokal_prune,
    }


def _setup_blockchain_client(
    args,
    env: dict[str, str] | None = None,
    *,
    interactive_onion: bool = False,
):
    """
    Wählt die Datenquelle:
    - explizit (--bip158, --rpc-only oder manuelle Menüwahl)
    - sonst automatische Priorität:
      1. eigener Electrum-Server, 2. P2P-BIP-158;
      öffentliche Onions/Clearnet nur nach Bestätigung
    """
    env = env or _load_dotenv()

    if _data_source_is_explicit(args, env):
        if _wants_bip158(args, env):
            return (
                "bip158",
                _setup_bip158_client(args, env, raise_on_error=True),
            )

        if _wants_fulcrum(args, env):
            result = _try_data_source_priority_chain(
                args,
                env,
                include_bip158=False,
                interactive_onion=interactive_onion,
            )
            if result:
                return result[0], result[1]
            raise SystemExit(
                "Fulcrum nicht erreichbar (eigener Node). "
                "Öffentliche Server nur nach Bestätigung "
                "(OEFFENTLICHE_ELECTRUM=1)."
            )
        raise SystemExit("Keine Datenquelle gewählt (--bip158 oder --rpc-only).")

    result = _try_data_source_priority_chain(
        args,
        env,
        include_bip158=True,
        interactive_onion=interactive_onion,
    )
    if result:
        return result[0], result[1]

    if _oeffentliche_electrum_erlaubt(env, args):
        grund = (
            "Keine Datenquelle erreichbar: eigener Electrum-Server und "
            "BIP-158 fehlen, öffentliche Electrum-Server (Onion/Clearnet) "
            "waren trotz Freigabe nicht nutzbar (Tor/Netz/Liste prüfen)."
        )
    else:
        grund = (
            "Keine Datenquelle erreichbar (eigener Electrum-Server, BIP-158). "
            "Öffentliche Electrum-Server nur nach Bestätigung."
        )
    _log_quelle(grund)
    raise SystemExit(grund)

def is_own_fulcrum_backend(fulcrum) -> bool:
    """True bei direktem FulcrumClient (eigener Node), nicht bei öffentlicher Rotation."""
    from core.fulcrum_client import FulcrumClient, RotatingFulcrumPool

    if isinstance(fulcrum, FulcrumClient):
        return True
    if isinstance(fulcrum, RotatingFulcrumPool):
        return False
    return False


def privacy_notice_for_source(
    source: str | None,
    *,
    fulcrum=None,
) -> str:
    """Privatsphäre-Hinweis zur Datenquelle (Menü-Statuszeile)."""
    if source == "bip158":
        return "Privatsphäre: hoch (P2P-Filter, keine Adressen an Peers)"
    if source in ("bitcoind", "scantxoutset"):
        return "Privatsphäre: hoch (eigener Bitcoin Core)"
    if source == "fulcrum":
        if is_own_fulcrum_backend(fulcrum):
            return "Privatsphäre: hoch"
        return "⚠ Privatsphäre: mäßig"
    return ""


def _build_blockchain_fetchers(
    source: str,
    backend,
    args,
    wallet_ctx: "WalletContext | None",
    *,
    immutable_cache_dir: Path | None = None,
):
    """Bindet get_tx / fetch_*-Funktionen an die gewählte Datenquelle."""
    cache_root = immutable_cache_dir or resolve_immutable_cache_dir(args)

    if source == "bip158":
        raw_get_tx = backend["get_tx"]
        fetch_address_utxos = backend["fetch_address_utxos"]
        max_by = {
            xpub: wallet_ctx.max_addresses_for(xpub, args.max_addresses)
            for xpub in args.xpubs
        }
        def fetch_wallet_utxos(
            addrs,
            *,
            filter_scan=False,
            max_addr=None,
            on_progress=None,
            on_utxos_update=None,
            xpubs=None,
        ):
            # Explizites max_addr (Gap-/Filter-Scan) darf die konfigurierte
            # Anzeige-Tiefe nicht wieder auf 50/2 = Index 25 stauchen.
            # *xpubs* eingrenzen: sonst scannte BIP-158 bei jedem Wallet
            # den gesamten args.xpubs-Satz und mischte die UTXOs.
            try:
                return backend["fetch_wallet_utxos"](
                    addrs,
                    xpubs=xpubs if xpubs is not None else args.xpubs,
                    wallet=wallet_ctx,
                    max_addr=max_addr if max_addr is not None else args.max_addresses,
                    max_by=None if max_addr is not None else max_by,
                    filter_scan=filter_scan,
                    on_utxos_update=on_utxos_update,
                )
            except TypeError:
                return backend["fetch_wallet_utxos"](
                    addrs,
                    xpubs=xpubs if xpubs is not None else args.xpubs,
                    wallet=wallet_ctx,
                    max_addr=max_addr if max_addr is not None else args.max_addresses,
                    max_by=None if max_addr is not None else max_by,
                    filter_scan=filter_scan,
                )
        fetch_addresses_utxos = backend.get(
            "fetch_addresses_utxos",
            lambda addrs: _fetch_utxos_for_addresses(addrs, fetch_address_utxos),
        )
        fetch_addresses_utxos_utxoset = backend.get(
            "fetch_addresses_utxos_utxoset",
            fetch_addresses_utxos,
        )
        verify_utxo_spent = backend.get("verify_utxo_spent")
        get_tx = wrap_get_tx_with_immutable_cache(raw_get_tx, cache_root, source)
        cache_dir = getattr(backend.get("client"), "cache_dir", None)

        def fetch_wallet_history(
            addrs,
            *,
            skip_addresses=None,
            on_address_done=None,
            on_progress=None,
            seed_eintraege=None,
            **_kw,
        ):
            """
            Historie über BIP-158-Blockwalk (kein Electrum get_history).

            Löst denselben Compact-Filter-Scan aus wie der UTXO-Pfad; der
            schreibt ``merke_bip158_verlauf``. Anschließend Cache lesen.
            """
            skip = {str(a) for a in (skip_addresses or [])}
            offen = [a for a in addrs if a not in skip]
            if not offen:
                seed = list(seed_eintraege or [])
                return [
                    e for e in seed
                    if e.get("address") in set(addrs)
                ]

            xpubs: list[str] = []
            gesehen: set[str] = set()
            if wallet_ctx is not None:
                for adresse in offen:
                    xpub = wallet_ctx.address_to_xpub.get(adresse)
                    if xpub and xpub not in gesehen:
                        gesehen.add(xpub)
                        xpubs.append(xpub)
            if not xpubs:
                xpubs = list(args.xpubs)

            if on_progress:
                on_progress(
                    "BIP-158 Blockwalk für Verlauf "
                    f"({len(xpubs)} Wallet(s), {len(offen)} Adressen)…",
                    sofort=True,
                )
            fetch_wallet_utxos(
                offen,
                filter_scan=True,
                xpubs=xpubs,
            )

            cache_je_xpub: dict[str, list[dict]] = {}
            if cache_dir is not None:
                for xpub in xpubs:
                    cache_je_xpub[xpub] = (
                        load_xpub_verlauf_cache(xpub, cache_dir) or []
                    )

            gesammelt: list[dict] = []
            for adresse in offen:
                xpub = None
                if wallet_ctx is not None:
                    xpub = wallet_ctx.address_to_xpub.get(adresse)
                kandidaten = (
                    cache_je_xpub.get(xpub, [])
                    if xpub
                    else [
                        e
                        for roh in cache_je_xpub.values()
                        for e in roh
                    ]
                )
                neu = [
                    e for e in kandidaten
                    if e.get("address") == adresse
                ]
                if on_address_done:
                    on_address_done(adresse, neu)
                gesammelt.extend(neu)
            return gesammelt

        return {
            "get_tx": get_tx,
            "fetch_address_utxos": fetch_address_utxos,
            "fetch_addresses_utxos": fetch_addresses_utxos,
            "fetch_addresses_utxos_utxoset": fetch_addresses_utxos_utxoset,
            "verify_utxo_spent": verify_utxo_spent,
            "fetch_wallet_utxos": fetch_wallet_utxos,
            "fetch_wallet_history": fetch_wallet_history,
            "fetch_utxos": fetch_address_utxos,
            "fulcrum": None,
            "immutable_cache_dir": cache_root,
        }

    if source == "fulcrum":
        from core.fulcrum_wallet import (
            fetch_address_utxos_fulcrum,
            fetch_wallet_utxos_fulcrum,
        )
        from core.fulcrum_history import (
            fetch_tx_fulcrum,
            fetch_wallet_history_fulcrum,
        )
        from core.bitcoind_rpc import (
            fetch_tx_core_mit_rollen,
            stelle_tx_lookup_rollen,
        )

        fulcrum = backend
        # Weitere Verbindungen für den parallelen Scan. Einmal geöffnet und
        # über die Fetcher weitergereicht — nicht je Aufruf neu, das kostete
        # mehr als es einbrächte.
        scan_pool = _open_scan_pool(fulcrum)
        if scan_pool is not None and not getattr(args, "no_verbose", False):
            print(
                f"  Scan über {len(scan_pool)} parallele Verbindungen",
                flush=True,
            )
        fetch_address_utxos = lambda addr: fetch_address_utxos_fulcrum(fulcrum, addr)
        # Core nur Ausnahme, wenn Electrs die Tx nicht liefert.
        _core_lokal = _core_arch = None
        _core_ph = None
        try:
            _env_tx = _load_dotenv()
            _core_lokal, _core_arch, _core_ph = stelle_tx_lookup_rollen(
                _env_tx, timeout=20.0,
            )
        except Exception:
            pass

        def raw_get_tx(txid: str) -> dict:
            try:
                return fetch_tx_fulcrum(fulcrum, txid)
            except Exception as electrs_exc:
                if _core_lokal is None and _core_arch is None:
                    raise
                try:
                    return fetch_tx_core_mit_rollen(
                        txid,
                        local=_core_lokal,
                        archival=_core_arch,
                        local_pruneheight=_core_ph,
                        on_log=_log_quelle,
                    )
                except Exception:
                    raise electrs_exc from None

        get_tx = wrap_get_tx_with_immutable_cache(
            raw_get_tx, cache_root, source, pool=scan_pool
        )
        fetch_addresses_utxos = lambda addrs, **kw: _fetch_utxos_for_addresses(
            addrs, fetch_address_utxos, **kw
        )
        return {
            "get_tx": get_tx,
            "fetch_address_utxos": fetch_address_utxos,
            "fetch_addresses_utxos": fetch_addresses_utxos,
            "fetch_addresses_utxos_utxoset": fetch_addresses_utxos,
            "verify_utxo_spent": None,
            "fetch_wallet_utxos": lambda addrs, *, filter_scan=False, on_progress=None, on_utxos_update=None, xpubs=None: (
                fetch_wallet_utxos_fulcrum(
                    fulcrum,
                    addrs,
                    pool=scan_pool,
                    on_progress=on_progress,
                    on_utxos_update=on_utxos_update,
                )
            ),
            "fulcrum_scan_pool": scan_pool,
            # Vollständiger Verlauf inkl. ausgegebener Outputs — nur über
            # einen Electrum-Server. Bei BIP-158 schreibt der UTXO-Scan
            # den Verlauf mit; hier bleibt der Schlüssel None.
            "fetch_wallet_history": lambda addrs, on_progress=None, **kw: (
                fetch_wallet_history_fulcrum(
                    fulcrum, addrs, on_progress=on_progress, **kw,
                )
            ),
            "fetch_utxos": fetch_address_utxos,
            "fulcrum": fulcrum,
            "immutable_cache_dir": cache_root,
        }


def _fulcrum_transport_ist_lan(fulcrum) -> bool:
    """
    True = eigener Electrum-Server ohne Tor (typisch IPv4 im LAN).

    Öffentliche Pools und Onion-Verbindungen zählen nicht — die sind
    für den UTXO-Bestand langsamer bzw. privatsphäreärmer.
    """
    if fulcrum is None:
        return False
    from core.fulcrum_client import FulcrumClient, RotatingFulcrumPool

    if isinstance(fulcrum, RotatingFulcrumPool):
        return False
    if not isinstance(fulcrum, FulcrumClient):
        return False
    host = (getattr(fulcrum, "host", None) or "").strip().lower()
    if not host or host.endswith(".onion"):
        return False
    if getattr(fulcrum, "tor_proxy", None):
        return False
    return True
