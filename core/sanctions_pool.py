"""
Sanktions-Fulcrum-Pools: eigener privater Node und öffentlicher Clearnet-Pool.

Aus main.py ausgelagert (Slice 3 step 6 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.

``core.chain_sources._setup_public_clearnet_fulcrum`` importiert den
Clearnet-Pool lazy aus diesem Modul (kein Top-Level-Zyklus).
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from core.chain_sources import (
    ELECTRUM_SERVERS_FILE,
    MAX_PUBLIC_ONION_SERVERS,
    _build_clearnet_fulcrum_targets,
    _dedupe_clearnet_fulcrum_hits,
    _env_port,
    _is_private_fulcrum_host,
    _normalize_fulcrum_host,
    _parse_env_bool,
    _probe_clearnet_fulcrum,
    wrap_get_tx_with_immutable_cache,
)
from core.xpub_cache import (
    IMMUTABLE_CACHE_DIR,
    _fetch_utxos_for_addresses,
    resolve_immutable_cache_dir,
)

SANCTIONS_CLEARNET_PROBE_TIMEOUT = 4
SANCTIONS_CLEARNET_PROBE_WORKERS = 12
SANCTIONS_CLEARNET_MAX_SERVERS = 10
SANCTIONS_CLEARNET_MIN_SERVERS = 2
#: Verbindungen zum eigenen Node für den parallelen Sanktions-Scan. Ein
#: Fulcrum im LAN verträgt das mühelos; darüber hinaus bremst nicht mehr die
#: Verbindung, sondern die Auswertung.
SANCTIONS_OWN_NODE_WORKERS = 4


def make_cached_fulcrum_get_tx(
    client,
    cache_root: Path | None = None,
    *,
    enrich_block_info: bool = False,
):
    """Gecachter get_tx für einen Fulcrum-Client (parallel pro Worker nutzbar)."""
    from core.fulcrum_history import fetch_tx_fulcrum

    root = cache_root or IMMUTABLE_CACHE_DIR
    return wrap_get_tx_with_immutable_cache(
        lambda txid: fetch_tx_fulcrum(
            client,
            txid,
            enrich_block_info=enrich_block_info,
        ),
        root,
        "fulcrum",
    )


_sanctions_clearnet_pool = None
_sanctions_clearnet_cache_key: tuple[str, str, str] | None = None

#: Offener Pool zum eigenen, privat adressierten Node (siehe
#: resolve_sanctions_preferred_pool) samt (host, port, ssl) als Schlüssel.
_sanctions_own_pool = None
_sanctions_own_cache_key: tuple[str, int, bool] | None = None


def _sanctions_fulcrum_exclude_hosts(env: dict[str, str]) -> set[str]:
    hosts: set[str] = set()
    for key in (
        "FULCRUM_HOST",
        "NODE_IP",
        "RPCHOST",
        "FULCRUM_TOR",
        "FULCRUM_SANCTIONS_HOST",
    ):
        raw = env.get(key, "").strip()
        if raw:
            hosts.add(_normalize_fulcrum_host(raw))
    for index in range(MAX_PUBLIC_ONION_SERVERS):
        raw = env.get(f"FULCRUM_TOR_{index}", "").strip()
        if raw:
            hosts.add(_normalize_fulcrum_host(raw))
    hosts.discard("")
    return hosts


def _print_sanctions_clearnet_pool(pool) -> None:
    from core.fulcrum_client import SanctionsClearnetPool

    if not isinstance(pool, SanctionsClearnetPool):
        return
    print(
        f"  → {len(pool)} Clearnet-Server für Sanktionslisten:",
        flush=True,
    )
    for index, client in enumerate(pool._clients, start=1):
        route = "SSL" if client.use_ssl else "TCP"
        print(
            f"     [{index}] {client.host}:{client.port} ({route})",
            flush=True,
        )


def resolve_sanctions_clearnet_pool(
    env: dict[str, str],
) -> tuple[object | None, bool]:
    """
    Mehrere schnelle Clearnet-Fulcrum-Server für OFAC-Listenabfragen.
    Rückgabe: (SanctionsClearnetPool oder None, aus Session-Cache).
    """
    global _sanctions_clearnet_pool, _sanctions_clearnet_cache_key

    from core.fulcrum_client import SanctionsClearnetPool

    cache_key = (
        env.get("FULCRUM_SANCTIONS_HOST", "").strip(),
        env.get("FULCRUM_SANCTIONS_PORT", "").strip(),
        env.get("FULCRUM_SANCTIONS_SSL", "").strip(),
    )
    if (
        _sanctions_clearnet_pool is not None
        and _sanctions_clearnet_cache_key == cache_key
    ):
        return _sanctions_clearnet_pool, True

    if _sanctions_clearnet_pool is not None:
        _sanctions_clearnet_pool.close()
        _sanctions_clearnet_pool = None

    configured = env.get("FULCRUM_SANCTIONS_HOST", "").strip()
    if configured:
        host = _normalize_fulcrum_host(configured)
        port = _env_port(env, "FULCRUM_SANCTIONS_PORT")
        use_ssl = _parse_env_bool(env.get("FULCRUM_SANCTIONS_SSL"), default=True)
        route = "SSL" if use_ssl else "TCP"
        print(
            f"Sanktions-Fulcrum (Clearnet, .env): {host}:{port} ({route})…",
            flush=True,
        )
        hit = _probe_clearnet_fulcrum(
            host,
            port,
            use_ssl,
            SANCTIONS_CLEARNET_PROBE_TIMEOUT,
        )
        if hit:
            client, latency = hit
            pool = SanctionsClearnetPool([client])
            print(
                f"  → {host}:{port} ({route}, {latency * 1000:.0f} ms)",
                flush=True,
            )
            _sanctions_clearnet_pool = pool
            _sanctions_clearnet_cache_key = cache_key
            return pool, False
        print(
            "  → nicht erreichbar, ohne listunspent oder ohne Block-Historie",
            flush=True,
        )

    from check_fulcrum_tor import load_electrum_servers

    try:
        servers = load_electrum_servers(ELECTRUM_SERVERS_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"  ⚠️  electrum_servers.json nicht nutzbar: {exc}", flush=True)
        return None, False

    exclude = _sanctions_fulcrum_exclude_hosts(env)
    targets = _build_clearnet_fulcrum_targets(servers, exclude)
    if not targets:
        print("  ⚠️  Keine Clearnet-Kandidaten in electrum_servers.json", flush=True)
        return None, False

    print(
        f"Suche geeignete Clearnet-Fulcrum-Server für Sanktionslisten "
        f"({len(targets)} Kandidaten, max. "
        f"{SANCTIONS_CLEARNET_PROBE_WORKERS} parallel, "
        f"bis zu {SANCTIONS_CLEARNET_MAX_SERVERS})…",
        flush=True,
    )

    hits: list[tuple[object, float]] = []
    executor = ThreadPoolExecutor(max_workers=SANCTIONS_CLEARNET_PROBE_WORKERS)
    futures = [
        executor.submit(
            _probe_clearnet_fulcrum,
            host,
            port,
            use_ssl,
            SANCTIONS_CLEARNET_PROBE_TIMEOUT,
        )
        for host, port, use_ssl in targets
    ]
    try:
        for future in as_completed(futures):
            try:
                probe = future.result()
            except Exception:
                probe = None
            if probe is None:
                continue
            client, latency = probe
            hits.append((client, latency))
            if len(_dedupe_clearnet_fulcrum_hits(hits)) >= SANCTIONS_CLEARNET_MAX_SERVERS:
                break
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    unique_hits = _dedupe_clearnet_fulcrum_hits(hits)[:SANCTIONS_CLEARNET_MAX_SERVERS]
    if not unique_hits:
        print(
            "  → kein Clearnet-Fulcrum mit listunspent gefunden",
            flush=True,
        )
        return None, False

    selected_hosts = {getattr(client, "host", "") for client, _lat in unique_hits}
    for client, _latency in hits:
        if getattr(client, "host", "") not in selected_hosts:
            client.close()

    pool = SanctionsClearnetPool([client for client, _lat in unique_hits])
    _print_sanctions_clearnet_pool(pool)
    _sanctions_clearnet_pool = pool
    _sanctions_clearnet_cache_key = cache_key
    return pool, False


def _open_own_sanctions_pool(
    host: str,
    port: int,
    use_ssl: bool,
    workers: int,
) -> tuple[object | None, float]:
    """
    Mehrere Verbindungen zum eigenen Node als Pool.

    Der Parallel-Scan über die Listenadressen (Menü 6.2) braucht eine
    Verbindung pro Worker-Thread. Beim Clearnet-Pool kommt die aus je einem
    anderen Server; ein eigener Fulcrum im LAN verträgt die Last dagegen
    problemlos selbst, also werden mehrere Verbindungen dorthin geöffnet.

    Die erste Verbindung muss listunspent können. Die Mainnet-Historie-Sonde
    (Höhe 500k) entfällt hier — Regtest/Testnet und frische LAN-Nodes hätten
    sonst fälschlich Clearnet als Fallback.
    """
    from core.fulcrum_client import SanctionsClearnetPool, connect_fulcrum

    started = time.monotonic()
    erster, _fehler = connect_fulcrum(
        host,
        port,
        use_ssl=use_ssl,
        timeout=SANCTIONS_CLEARNET_PROBE_TIMEOUT,
        require_listunspent=True,
    )
    if not erster:
        return None, 0.0
    latency = time.monotonic() - started

    clients = [erster]
    for _ in range(max(0, workers - 1)):
        weiterer, _fehler = connect_fulcrum(
            host,
            port,
            use_ssl=use_ssl,
            timeout=SANCTIONS_CLEARNET_PROBE_TIMEOUT,
            require_listunspent=True,
        )
        if not weiterer:
            break
        clients.append(weiterer)
    return SanctionsClearnetPool(clients), latency


def resolve_sanctions_preferred_pool(env: dict[str, str]):
    """
    Fulcrum-Pool für Sanktionsabfragen.

    Reihenfolge:
    1. Eigener Server, wenn er **privat** adressiert ist (LAN, Loopback,
       Link-Local) — egal ob über FULCRUM_SANCTIONS_HOST oder FULCRUM_HOST
       konfiguriert. Gehört dem Benutzer: schnell im LAN, und die Anfragen
       nach gelisteten Fremdadressen verlassen das eigene Netz nicht.
       Der Pool bündelt mehrere Verbindungen dorthin, damit der
       Parallel-Scan auch mit eigenem Node parallel bleibt.
    2. Sonst der öffentliche Clearnet-Pool (resolve_sanctions_clearnet_pool):
       Sanktionsabfragen laufen bewusst nicht über einen öffentlich
       konfigurierten eigenen Server oder Tor, damit sie nicht mit der
       Identität des Benutzers verknüpft werden.

    Rückgabe: (pool, quelle, aus_cache). *quelle* ist "own_private",
    "clearnet_pool" oder "none"; *aus_cache* meldet einen bereits offenen
    Pool, damit Aufrufer die Statusmeldung nicht bei jedem Menüpunkt
    wiederholen.
    """
    global _sanctions_own_pool, _sanctions_own_cache_key

    kandidaten: list[tuple[str, int, bool]] = []
    configured = env.get("FULCRUM_SANCTIONS_HOST", "").strip()
    if configured:
        host = _normalize_fulcrum_host(configured)
        if _is_private_fulcrum_host(host):
            kandidaten.append((
                host,
                _env_port(env, "FULCRUM_SANCTIONS_PORT"),
                _parse_env_bool(env.get("FULCRUM_SANCTIONS_SSL"), default=True),
            ))

    own = env.get("FULCRUM_HOST", "").strip()
    if own:
        host = _normalize_fulcrum_host(own)
        if _is_private_fulcrum_host(host):
            kandidaten.append((
                host,
                _env_port(env, "FULCRUM_PORT"),
                _parse_env_bool(env.get("FULCRUM_SSL"), default=True),
            ))

    for host, port, use_ssl in kandidaten:
        # Ein einmal geöffneter Pool bleibt offen: vier Verbindungen bei
        # jedem Menüpunkt neu aufzubauen kostet mehr als es bringt.
        if _sanctions_own_pool is not None and _sanctions_own_cache_key == (
            host, port, use_ssl
        ):
            return _sanctions_own_pool, "own_private", True

        route = "SSL" if use_ssl else "TCP"
        print(
            f"Sanktions-Fulcrum (eigener Server): {host}:{port} ({route})…",
            flush=True,
        )
        pool, latency = _open_own_sanctions_pool(
            host, port, use_ssl, SANCTIONS_OWN_NODE_WORKERS
        )
        if pool is not None:
            print(
                f"  → {host}:{port} ({route}, {latency * 1000:.0f} ms, "
                f"{len(pool)} Verbindung(en))",
                flush=True,
            )
            if _sanctions_own_pool is not None:
                _sanctions_own_pool.close()
            _sanctions_own_pool = pool
            _sanctions_own_cache_key = (host, port, use_ssl)
            return pool, "own_private", False
        print("  → nicht erreichbar, falle auf Clearnet zurück", flush=True)

    pool, aus_cache = resolve_sanctions_clearnet_pool(env)
    if pool is None:
        return None, "none", False
    return pool, "clearnet_pool", aus_cache


def resolve_sanctions_preferred_client(env: dict[str, str]):
    """
    Einzelner Client aus dem bevorzugten Sanktions-Pool — für Abfragen
    ohne Parallelität (Einzel-UTXO-Prüfung, get_tx).

    Rückgabe: (client, quelle) oder (None, grund).
    """
    pool, quelle, _aus_cache = resolve_sanctions_preferred_pool(env)
    if pool is None:
        return None, quelle
    return pool.primary, quelle


def resolve_sanctions_clearnet_fulcrum(
    env: dict[str, str],
) -> tuple[object | None, bool]:
    """Kompatibilität: erster Server aus dem Sanktions-Clearnet-Pool."""
    pool, from_cache = resolve_sanctions_clearnet_pool(env)
    if pool is None:
        return None, from_cache
    return pool.primary, from_cache


def build_sanctions_fulcrum_fetchers(session) -> dict:
    """
    Fetcher für Sanktionslisten (nur OFAC-Adressen).

    Eigener privat adressierter Server (LAN/Loopback) zuerst — schnell und
    die Anfragen bleiben im eigenen Netz; sonst Clearnet-Fulcrum-Pool
    (Priorität 4), unabhängig von der Wallet-Datenquelle. In beiden Fällen
    trägt der Pool den Parallel-Scan aus Menü 6.2.
    """
    from core.fulcrum_wallet import fetch_address_utxos_fulcrum

    pool, quelle, aus_cache = resolve_sanctions_preferred_pool(session.env)
    if pool is None:
        print(
            "  ⚠️  Sanktionsabfragen: kein Fulcrum erreichbar",
            flush=True,
        )
        return {}

    client = pool.primary
    cache_root = resolve_immutable_cache_dir(session.args)
    fetch_address_utxos = lambda addr: fetch_address_utxos_fulcrum(client, addr)
    get_tx = make_cached_fulcrum_get_tx(client, cache_root)
    fetch_addresses_utxos_utxoset = lambda addrs, **kw: _fetch_utxos_for_addresses(
        addrs,
        fetch_address_utxos,
        **kw,
    )

    if not aus_cache:
        if quelle == "own_private":
            print(
                f"  Sanktionsabfragen über den eigenen Server (privates Netz, "
                f"{len(pool)} Verbindung(en) parallel)",
                flush=True,
            )
        elif len(pool) > 1:
            print(
                f"  Sanktionsabfragen parallel über {len(pool)} Clearnet-Server",
                flush=True,
            )
        else:
            print(
                "  Sanktionsabfragen über öffentlichen Clearnet-Server (ohne Tor)",
                flush=True,
            )

    return {
        "fulcrum": client,
        "fulcrum_pool": pool,
        "get_tx": get_tx,
        "fetch_addresses_utxos_utxoset": fetch_addresses_utxos_utxoset,
    }
