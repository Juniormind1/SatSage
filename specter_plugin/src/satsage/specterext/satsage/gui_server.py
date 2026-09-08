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
from .specter_session import (
    _SATSAGE_ROOT,
    collect_specter_utxos,
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


def _wallet_entries_aus_kontext(ctx: SatSageContext):
    ensure_satsage_on_path()
    from core.config import WalletEntry

    eintraege = []
    gesehen: set[str] = set()
    for w in ctx.wallets:
        if w.recv_descriptor:
            eintraege.append(
                WalletEntry(
                    name=w.name or w.alias or "Specter-Wallet",
                    descriptor=w.recv_descriptor,
                    max_addresses=200,
                )
            )
            continue
        for xpub in w.xpubs:
            if not xpub or xpub in gesehen:
                continue
            gesehen.add(xpub)
            eintraege.append(
                WalletEntry(
                    xpub=xpub,
                    name=w.name or xpub[:16],
                    script_type="auto",
                    max_addresses=200,
                )
            )
    return eintraege


def _schreibe_specter_env(ctx: SatSageContext) -> Path:
    """Spiegelt Specter-Kontext in die Plugin-.env, nicht in die Desktop-.env."""
    ensure_satsage_on_path()
    import main as xq_main
    from core.config import EnvFile, write_wallets

    pfad = _gui_env_path()
    if not pfad.is_file():
        pfad.write_text(
            "# SatSage — Specter-Plugin (automatisch gespiegelt)\n"
            "# NETWORK kommt aus Specter; Core nutzt BIP-158/P2P, Electrum/Spectrum FULCRUM_*.\n",
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
    env.apply(updates)
    env.save()

    write_wallets(EnvFile.load(pfad), _wallet_entries_aus_kontext(ctx), bestaetigt=True)
    return pfad


def _seed_utxo_cache(specter: Any, ctx: SatSageContext, cache_dir: Path) -> int:
    """Leichter Seed aus Specter-UTXOs — ohne Blockchain-Connect."""
    ensure_satsage_on_path()
    import main as xq_main

    utxos = collect_specter_utxos(specter)
    if not utxos:
        return 0

    by_xpub: dict[str, list[dict]] = {x: [] for x in ctx.all_xpubs()}
    for u in utxos:
        xp = u.get("xpub")
        if xp and xp in by_xpub:
            by_xpub[xp].append(u)
        elif by_xpub:
            # Fallback: erstes XPUB des Kontexts
            by_xpub[next(iter(by_xpub))].append(u)

    geschrieben = 0
    for xpub, liste in by_xpub.items():
        if not liste:
            continue
        try:
            xq_main.save_xpub_utxo_cache(
                xpub,
                liste,
                cache_dir,
                source="specter",
                max_addresses=200,
            )
            geschrieben += 1
        except Exception as exc:
            logger.warning("UTXO-Seed für Specter-GUI: %s", exc)
    return geschrieben


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
        env_pfad = _schreibe_specter_env(ctx)
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
            logger.info("SatSage-GUI: Wallets aus Specter neu geladen")

        _fingerprint = fp
        try:
            _seed_utxo_cache(specter, ctx, cache_dir)
        except Exception as exc:
            logger.warning("UTXO-Seed übersprungen: %s", exc)

        return {
            "url": _server.url,
            "token": _server.token,
            "port": _server.port,
            "wallet_count": len(ctx.wallets),
            "xpub_count": len(ctx.all_xpubs()),
            "neu_gestartet": neu,
            "env_path": str(env_pfad),
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
