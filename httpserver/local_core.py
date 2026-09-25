"""Local-Core- und Managed-Config-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports.
"""

from __future__ import annotations

import json
from pathlib import Path


_BRIDGE_QUELLEN = frozenset(("own_fulcrum", "own_core"))
_BRIDGE_SCHLUESSEL = frozenset((
    "FULCRUM_HOST", "FULCRUM_TOR", "FULCRUM_PORT", "FULCRUM_SSL",
    "FULCRUM_TOR_PORT", "FULCRUM_TOR_SSL",
    "NODE_IP", "RPCHOST", "BITCOIN_RPC_HOST", "RPCPORT", "RPCUSER",
    "RPCPASSWORD", "RPC_SSL", "RPC_COOKIE_FILE", "BITCOIN_RPC_COOKIE",
))


_local_core_probe_cache: tuple[float, object | None] | None = None
_local_core_hint_logged = False
_local_core_runtime_logged = False


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
    from httpserver.app_state import _MANAGED_MODI
    from core import local_bitcoind as local_core

    if state.managed_by in _MANAGED_MODI:
        return None

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
    from server import _electrum_indexer

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
    from server import ApiError
    from httpserver.app_state import _NODE_MANAGED

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
