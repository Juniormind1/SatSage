"""Lokalen Bitcoin Core auf derselben Maschine finden (Desktop-MVP).

Nur Loopback + Standard-Datadirs / Cookie. Kein Start9/Specter-Managed.
Sonderfälle (custom datadir, mehrere Nodes, …): ISSUES.md.
"""
from __future__ import annotations

import os
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# (NETWORK-Wert für SatSage, Unterordner unter Datadir, RPC-Port, P2P-Port)
_NETWORKS: tuple[tuple[str, str, int, int], ...] = (
    ("main", "", 8332, 8333),
    ("test", "testnet3", 18332, 18333),
    ("signet", "signet", 38332, 38333),
    ("regtest", "regtest", 18443, 18444),
)


@dataclass(frozen=True)
class LocalCoreHit:
    host: str
    port: int
    cookie_path: str
    network: str
    chain: str
    blocks: int
    pruned: bool
    user: str
    # Passwort nur transient für Opt-in-Schreiben — nicht loggen.
    password: str
    p2p_port: int = 8333
    p2p_tcp_open: bool | None = None

    def as_public_dict(self) -> dict[str, Any]:
        """Für API/Log — ohne Passwort."""
        d = asdict(self)
        d.pop("password", None)
        tip = (
            "Pruned: gut für scantxoutset (UTXO-Bestand). "
            if self.pruned
            else "Vollständiger Node: starke Quelle für Core-RPC/Lookups. "
        )
        tip += (
            f"P2P :{self.p2p_port} für BIP-158 "
            + (
                "erreichbar (peerblockfilters=1 empfohlen)."
                if self.p2p_tcp_open
                else "wird mitgesetzt — Compact Filters brauchen peerblockfilters=1."
                if self.p2p_tcp_open is False
                else "wird mit Opt-in als Prefer-Peer gesetzt."
            )
        )
        d["hint"] = tip + " Opt-in nötig — nicht still verbunden."
        return d


def default_bitcoin_datadirs() -> list[Path]:
    """Übliche Bitcoin-Core-Datadirs (erste existierende zuerst)."""
    gefunden: list[Path] = []
    for key in ("BITCOIN_DATADIR", "BITCOIN_DATA_DIR"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            gefunden.append(Path(raw).expanduser())
    if sys.platform.startswith("win"):
        appdata = (os.environ.get("APPDATA") or "").strip()
        if appdata:
            gefunden.append(Path(appdata) / "Bitcoin")
        lokal = (os.environ.get("LOCALAPPDATA") or "").strip()
        if lokal:
            gefunden.append(Path(lokal) / "Bitcoin")
    elif sys.platform == "darwin":
        gefunden.append(
            Path.home() / "Library" / "Application Support" / "Bitcoin"
        )
    else:
        gefunden.append(Path.home() / ".bitcoin")
        # Flatpak o. ä. oft unter .var — Sonderfall, hier nur erwähnen in ISSUES
    out: list[Path] = []
    gesehen: set[str] = set()
    for p in gefunden:
        try:
            key = str(p.resolve()) if p.exists() else str(p)
        except OSError:
            key = str(p)
        if key in gesehen:
            continue
        gesehen.add(key)
        out.append(p)
    return out


def _cookie_file(datadir: Path, subdir: str) -> Path:
    return (datadir / subdir / ".cookie") if subdir else (datadir / ".cookie")


def _read_cookie(path: Path) -> tuple[str, str] | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    if ":" not in text:
        return None
    user, password = text.split(":", 1)
    user, password = user.strip(), password.strip()
    if not user or not password:
        return None
    return user, password


def _tcp_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_rpc(
    host: str,
    port: int,
    user: str,
    password: str,
    *,
    timeout: float = 2.0,
) -> dict[str, Any] | None:
    from core.bitcoind_rpc import BitcoinRpcClient, CoreRpcConfig

    cfg = CoreRpcConfig(
        host=host,
        port=port,
        user=user,
        password=password,
        use_ssl=False,
    )
    try:
        return BitcoinRpcClient(cfg, timeout=timeout).call("getblockchaininfo")
    except Exception:
        return None


def discover_local_bitcoind(
    *,
    preferred_network: str | None = None,
    host: str = "127.0.0.1",
) -> LocalCoreHit | None:
    """
    Sucht Cookie + offenen RPC auf Loopback.

    *preferred_network*: ``main``/``test``/… — wird zuerst geprüft, sonst
    Reihenfolge main→test→signet→regtest.
    """
    pref = (preferred_network or "").strip().lower()
    if pref in ("mainnet", "bitcoin"):
        pref = "main"
    if pref in ("testnet",):
        pref = "test"

    nets = list(_NETWORKS)
    if pref:
        nets.sort(key=lambda n: 0 if n[0] == pref else 1)

    for datadir in default_bitcoin_datadirs():
        if not datadir.is_dir():
            continue
        for network, sub, port, p2p_port in nets:
            cookie_path = _cookie_file(datadir, sub)
            if not cookie_path.is_file():
                continue
            creds = _read_cookie(cookie_path)
            if not creds:
                continue
            if not _tcp_open(host, port):
                continue
            user, password = creds
            info = _probe_rpc(host, port, user, password)
            if not isinstance(info, dict):
                continue
            chain = str(info.get("chain") or network)
            try:
                blocks = int(info.get("blocks") or 0)
            except (TypeError, ValueError):
                blocks = 0
            pruned = bool(info.get("pruned"))
            p2p_open = _tcp_open(host, p2p_port)
            return LocalCoreHit(
                host=host,
                port=port,
                cookie_path=str(cookie_path.resolve()),
                network=network,
                chain=chain,
                blocks=blocks,
                pruned=pruned,
                user=user,
                password=password,
                p2p_port=p2p_port,
                p2p_tcp_open=p2p_open,
            )
    return None


def core_already_configured(env: dict[str, str]) -> bool:
    """True, wenn der Nutzer (oder Managed-Modus) Core schon gesetzt hat."""
    host = (
        env.get("NODE_IP")
        or env.get("RPCHOST")
        or env.get("BITCOIN_RPC_HOST")
        or env.get("BITCOIND_HOST")
        or ""
    ).strip()
    if not host:
        return False
    user = (env.get("RPCUSER") or "").strip()
    password = (env.get("RPCPASSWORD") or "").strip()
    cookie = (env.get("RPC_COOKIE_FILE") or "").strip()
    return bool(user and password) or bool(cookie)


def local_core_opt_in_enabled(env: dict[str, str]) -> bool:
    raw = (env.get("LOCAL_CORE_OPT_IN") or "").strip().lower()
    return raw in ("1", "true", "yes", "ja", "on")


def env_updates_from_hit(hit: LocalCoreHit) -> dict[str, str]:
    """Werte für ``.env`` / Runtime nach Opt-in.

    RPC für scantxoutset/Lookups **und** ``BIP158_HOST`` als Prefer-Peer
    für Compact Filter (P2P-Port, nicht RPC-Port).
    """
    return {
        "NODE_IP": hit.host,
        "RPCPORT": str(hit.port),
        "RPCUSER": hit.user,
        "RPCPASSWORD": hit.password,
        "RPC_COOKIE_FILE": hit.cookie_path,
        "RPC_SSL": "false",
        "LOCAL_CORE_OPT_IN": "1",
        "NETWORK": hit.network,
        # P2P Compact Filter — LAN/Loopback zuerst (core/p2p.p2p_peers_from_env).
        "BIP158_HOST": f"{hit.host}:{int(hit.p2p_port)}",
        "BIP158_P2P": "1",
    }
