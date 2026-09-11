"""
Startet die SatSage-Web-GUI im Hintergrund und speist Specter-Wallets ein.

Die Oberfläche bleibt `server.py` + `web/` — Specter zeigt sie per iframe
(oder neuem Tab). Keine zweite UI.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from .bridge import SatSageContext, build_context
from .specter_seed import (
    seed_caches_from_specter,
    wallet_entries_with_specter_limits,
)
from .specter_session import (
    _SATSAGE_ROOT,
    context_fingerprint,
    ensure_satsage_on_path,
)

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_server = None  # server.EingebetteterServer | None
_fingerprint: str = ""
_env_path: Path | None = None

#: Specter-eigene Env — nicht die Repo-`.env` des Nutzers überschreiben.
_SPECTER_ENV_NAME = "satsage.env"


def _specter_dev_dir() -> Path:
    # …/specter_plugin/.specter_dev/
    return _SATSAGE_ROOT / "specter_plugin" / ".specter_dev"


def _gui_env_path() -> Path:
    ziel = _specter_dev_dir()
    ziel.mkdir(parents=True, exist_ok=True)
    return ziel / _SPECTER_ENV_NAME


def _schreibe_specter_env(ctx: SatSageContext, specter: Any | None = None) -> Path:
    """Spiegelt Specter-Kontext in die Plugin-.env, nicht in die Desktop-.env."""
    ensure_satsage_on_path()
    import main as xq_main
    from core.config import EnvFile, write_wallets

    pfad = _gui_env_path()
    if not pfad.is_file():
        pfad.write_text(
            "# SatSage — Specter-Plugin (automatisch gespiegelt)\n"
            "# Wallets + Node/Electrum kommen aus Specter — hier nicht doppelt pflegen.\n"
            "# NETWORK aus Specter; Core → BIP-158/P2P + RPC, Electrum/Spectrum → FULCRUM_*.\n",
            encoding="utf-8",
        )

    basis = dict(xq_main._load_dotenv(xq_main.ENV_FILE))
    wallet_keys = {
        "XPUBS", "WALLET_NAMES", "SCRIPT_TYPES", "MAX_ADDRESSES_PER_XPUB",
        *{f"XPUB_{i}" for i in range(10)},
    }
    mapped_node_keys = {
        "NETWORK", "BIP158_P2P", "NODE_IP", "RPCPORT", "RPCUSER",
        "RPCPASSWORD", "FULCRUM_HOST", "FULCRUM_PORT", "FULCRUM_SSL",
    }
    # Wallets und Verbindung stammen vollständig aus Specter. Alte Node-Werte
    # müssen verschwinden, wenn der Benutzer in Specter den Node-Typ wechselt.
    basis = {
        key: value for key, value in basis.items()
        if not key.startswith("WALLET_") and key not in wallet_keys
        and key not in mapped_node_keys
    }
    env = EnvFile.load(pfad)
    vorhanden = env.values()
    updates = {key: None for key in mapped_node_keys if key in vorhanden}
    updates.update({key: value for key, value in basis.items() if value})
    updates.update({key: value for key, value in ctx.env_like.items() if value})
    updates["SATSAGE_MANAGED_BY"] = "specter"
    env.apply(updates)
    env.save()

    eintraege = wallet_entries_with_specter_limits(ctx, specter)
    write_wallets(EnvFile.load(pfad), eintraege, bestaetigt=True)
    return pfad


def _seed_caches(specter: Any, ctx: SatSageContext, cache_dir: Path) -> dict[str, int]:
    """UTXOs + Verlauf + Labels + Scan-Indizes aus Specter."""
    try:
        stats = seed_caches_from_specter(specter, ctx, cache_dir, source_tag="specter")
        logger.info(
            "Specter-Seed: %s UTXO-Dateien, %s UTXOs, %s Verlauf, %s Labels",
            stats.get("utxo_files"),
            stats.get("utxos"),
            stats.get("verlauf_merged"),
            stats.get("labels"),
        )
        return stats
    except Exception as exc:
        logger.warning("Specter-Cache-Seed fehlgeschlagen: %s", exc)
        return {}


def ensure_gui_server(specter: Any) -> dict[str, Any]:
    """
    Stellt sicher, dass die Web-GUI läuft und Specter-Wallets kennt.

    Rückgabe: ``url``, ``token``, ``port``, ``wallet_count``, ``neu_gestartet``.
    """
    global _server, _fingerprint, _env_path

    ensure_satsage_on_path()
    import server as xq_server

    ctx = build_context(specter)
    fp = context_fingerprint(ctx)

    with _lock:
        env_pfad = _schreibe_specter_env(ctx, specter)
        _env_path = env_pfad
        cache_dir = _SATSAGE_ROOT / "utxo_cache"
        immutable = _SATSAGE_ROOT / "immutable_cache"
        neu = False

        if _server is not None:
            _server.state.set_managed_by("specter")

        if _server is None:
            state = xq_server.AppState(
                env_path=env_pfad,
                cache_dir=cache_dir,
                immutable_cache_dir=immutable,
                managed_by="specter",
            )
            _server = xq_server.starte_im_hintergrund(state, port=xq_server.DEFAULT_PORT)
            neu = True
            logger.info(
                "SatSage-GUI gestartet auf Port %s (%s Wallets)",
                _server.port,
                len(ctx.wallets),
            )
        elif fp != _fingerprint:
            _server.state.set_managed_by("specter")
            _server.state.reload()
            logger.info("SatSage-GUI: Wallets/Node aus Specter neu geladen")

        _fingerprint = fp
        seed_stats = _seed_caches(specter, ctx, cache_dir)

        return {
            "url": _server.url,
            "token": _server.token,
            "port": _server.port,
            "wallet_count": len(ctx.wallets),
            "xpub_count": len(ctx.all_xpubs()),
            "neu_gestartet": neu,
            "env_path": str(env_pfad),
            "seed": seed_stats,
        }


def gui_status() -> dict[str, Any] | None:
    with _lock:
        if _server is None:
            return None
        return {
            "url": _server.url,
            "port": _server.port,
            "env_path": str(_env_path) if _env_path else None,
        }
