"""
Brücke zwischen Specter-Desktop-Kontext und SatSage-Config.

Ziel (Phase 1): aus app.specter lesen
  - Wallets inkl. XPUBs / Deskriptoren
  - aktiver Node (Bitcoin Core RPC oder Electrum/Spectrum, soweit vorhanden)
  - UTXOs und Transaktionen über Specter-Wallet-Objekte

Die eigentliche Analyse-Logik aus main.py wird später angebunden.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


# SLIP-132 / BIP32 public key prefixes
_XPUB_RE = re.compile(
    r"\b([xyztuv]pub[1-9A-HJ-NP-Za-km-z]{50,})\b"
)


@dataclass
class SpecterKeyInfo:
    original: str | None = None
    xpub: str | None = None
    fingerprint: str | None = None
    derivation: str | None = None
    purpose: str | None = None


@dataclass
class SpecterWalletInfo:
    name: str
    alias: str
    address_type: str | None = None
    description: str | None = None
    keys: list[SpecterKeyInfo] = field(default_factory=list)
    xpubs: list[str] = field(default_factory=list)
    recv_descriptor: str | None = None
    change_descriptor: str | None = None
    balance_btc: float | None = None
    utxo_count: int = 0
    tx_count: int = 0


@dataclass
class SpecterNodeInfo:
    alias: str | None = None
    name: str | None = None
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None
    protocol: str | None = None  # http / https
    ssl: bool | None = None
    chain: str | None = None
    external_node: bool | None = None
    node_type: str | None = None  # bitcoind / spectrum / electrum / unknown
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SatSageContext:
    """Was SatSage später als Config/Backend nutzen kann."""

    wallets: list[SpecterWalletInfo] = field(default_factory=list)
    node: SpecterNodeInfo | None = None
    # Abgeleitete .env-ähnliche Werte (ohne Secrets in Logs ausgeben)
    env_like: dict[str, str] = field(default_factory=dict)
    source: str = "specter-inprocess"

    def all_xpubs(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for w in self.wallets:
            for x in w.xpubs:
                if x and x not in seen:
                    seen.add(x)
                    out.append(x)
        return out

    def wallet_names(self) -> list[str]:
        return [w.name for w in self.wallets]

    def to_dict(self, *, include_secrets: bool = False) -> dict[str, Any]:
        data = {
            "source": self.source,
            "wallets": [asdict(w) for w in self.wallets],
            "node": asdict(self.node) if self.node else None,
            "env_like": dict(self.env_like),
            "xpubs": self.all_xpubs(),
            "wallet_names": self.wallet_names(),
        }
        if not include_secrets and data["node"]:
            data["node"]["password"] = "***" if data["node"].get("password") else None
            if "RPCPASSWORD" in data["env_like"]:
                data["env_like"]["RPCPASSWORD"] = "***"
        return data


def _safe_get(obj: Any, *names: str, default=None):
    for name in names:
        if obj is None:
            break
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        else:
            if hasattr(obj, name):
                return getattr(obj, name)
    return default


def extract_xpubs_from_text(text: str | None) -> list[str]:
    if not text:
        return []
    return list(dict.fromkeys(_XPUB_RE.findall(text)))


def key_to_info(key: Any) -> SpecterKeyInfo:
    original = _safe_get(key, "original")
    xpub = _safe_get(key, "xpub")
    if not xpub and original:
        found = extract_xpubs_from_text(str(original))
        xpub = found[0] if found else str(original)
    return SpecterKeyInfo(
        original=str(original) if original is not None else None,
        xpub=str(xpub) if xpub is not None else None,
        fingerprint=str(_safe_get(key, "fingerprint")) if _safe_get(key, "fingerprint") is not None else None,
        derivation=str(_safe_get(key, "derivation")) if _safe_get(key, "derivation") is not None else None,
        purpose=str(_safe_get(key, "purpose")) if _safe_get(key, "purpose") is not None else None,
    )


def wallet_to_info(wallet: Any) -> SpecterWalletInfo:
    keys_raw = _safe_get(wallet, "keys") or []
    keys = [key_to_info(k) for k in keys_raw]
    xpubs: list[str] = []
    for k in keys:
        if k.xpub:
            xpubs.extend(extract_xpubs_from_text(k.xpub) or [k.xpub])
        if k.original:
            xpubs.extend(extract_xpubs_from_text(k.original))

    recv = _safe_get(wallet, "recv_descriptor")
    change = _safe_get(wallet, "change_descriptor")
    xpubs.extend(extract_xpubs_from_text(str(recv) if recv else None))
    xpubs.extend(extract_xpubs_from_text(str(change) if change else None))
    # stabil & unique
    xpubs = list(dict.fromkeys([x for x in xpubs if x]))

    balance = None
    bal_obj = _safe_get(wallet, "balance")
    if isinstance(bal_obj, dict):
        balance = bal_obj.get("trusted")
        if balance is None:
            balance = bal_obj.get("available", {}).get("trusted") if isinstance(bal_obj.get("available"), dict) else None
    elif isinstance(bal_obj, (int, float)):
        balance = float(bal_obj)

    utxos = _safe_get(wallet, "full_utxo") or _safe_get(wallet, "utxo") or []
    try:
        utxo_count = len(utxos)
    except TypeError:
        utxo_count = 0

    txs = _safe_get(wallet, "txlist")
    if callable(txs):
        try:
            txs = txs(validate_merkle_proofs=False)
        except TypeError:
            try:
                txs = txs()
            except Exception:
                txs = []
    if txs is None:
        txs = _safe_get(wallet, "_transactions") or {}
        tx_count = len(txs) if hasattr(txs, "__len__") else 0
    else:
        try:
            tx_count = len(txs)
        except TypeError:
            tx_count = 0

    return SpecterWalletInfo(
        name=str(_safe_get(wallet, "name") or _safe_get(wallet, "alias") or "unknown"),
        alias=str(_safe_get(wallet, "alias") or ""),
        address_type=str(_safe_get(wallet, "address_type")) if _safe_get(wallet, "address_type") is not None else None,
        description=str(_safe_get(wallet, "description")) if _safe_get(wallet, "description") is not None else None,
        keys=keys,
        xpubs=xpubs,
        recv_descriptor=str(recv) if recv else None,
        change_descriptor=str(change) if change else None,
        balance_btc=float(balance) if balance is not None else None,
        utxo_count=utxo_count,
        tx_count=tx_count,
    )


def node_to_info(specter: Any) -> SpecterNodeInfo:
    node = _safe_get(specter, "node")
    info = SpecterNodeInfo()
    if node is None:
        return info

    info.alias = str(_safe_get(node, "alias") or "") or None
    info.name = str(_safe_get(node, "name") or info.alias or "") or None
    info.host = _safe_get(node, "host")
    if info.host is not None:
        info.host = str(info.host)
    port = _safe_get(node, "port")
    if port is not None:
        try:
            info.port = int(port)
        except (TypeError, ValueError):
            info.port = None
    info.user = str(_safe_get(node, "user")) if _safe_get(node, "user") is not None else None
    info.password = str(_safe_get(node, "password")) if _safe_get(node, "password") is not None else None
    info.protocol = str(_safe_get(node, "protocol") or "http")
    ssl_raw = _safe_get(node, "ssl", "use_ssl", "tls")
    if ssl_raw is not None:
        info.ssl = bool(ssl_raw) if not isinstance(ssl_raw, str) else ssl_raw.strip().lower() not in ("0", "false", "no", "off")
    else:
        info.ssl = info.protocol.lower() in ("https", "ssl", "tls")
    info.external_node = _safe_get(node, "external_node")
    info.chain = _safe_get(specter, "chain")
    if info.chain is not None:
        info.chain = str(info.chain)

    # Node-Typ grob erkennen
    cls_name = type(node).__name__.lower()
    if "spectrum" in cls_name:
        info.node_type = "spectrum"
    elif "electrum" in cls_name:
        info.node_type = "electrum"
    elif ("bitcoin" in cls_name or "rpc" in cls_name or "node" in cls_name
          or _safe_get(node, "rpc") is not None
          or _safe_get(node, "user") is not None
          or _safe_get(node, "rpc_port") is not None):
        info.node_type = "bitcoind"
    else:
        info.node_type = cls_name or "unknown"

    # rpc object may carry host/port too
    rpc = _safe_get(node, "rpc") or _safe_get(specter, "rpc")
    if rpc is not None:
        if not info.host:
            info.host = str(_safe_get(rpc, "host") or "") or None
        if info.port is None:
            p = _safe_get(rpc, "port")
            if p is not None:
                try:
                    info.port = int(p)
                except (TypeError, ValueError):
                    pass
        if not info.user:
            info.user = str(_safe_get(rpc, "user") or "") or None
        if not info.password:
            info.password = str(_safe_get(rpc, "password") or "") or None

    info.raw = {
        "class": type(node).__name__,
        "alias": info.alias,
        "host": info.host,
        "port": info.port,
        "chain": info.chain,
        "node_type": info.node_type,
    }
    return info


def _network_name(chain: str | None) -> str | None:
    """Normalisiert Specter-Chainnamen für embit/SatSage."""
    value = (chain or "").strip().lower()
    return {
        "mainnet": "main", "bitcoin": "main", "main": "main",
        "regtest": "regtest", "testnet": "test", "test": "test",
        "signet": "signet",
    }.get(value)


def build_env_like(node: SpecterNodeInfo | None, wallets: list[SpecterWalletInfo]) -> dict[str, str]:
    """Mappt Specter-Wallets und -Node in SatSage-Env-Schlüssel.

    Bitcoin Core wird absichtlich nicht als Fulcrum ausgegeben: SatSage nutzt
    dafür BIP-158/P2P und optional Core-RPC für Transaktions-Lookups. Nur
    Electrum/Spectrum erhält FULCRUM_HOST/PORT/SSL.
    """
    env: dict[str, str] = {}
    xpubs = []
    names = []
    for w in wallets:
        for x in w.xpubs:
            if x not in xpubs:
                xpubs.append(x)
                names.append(w.name)
    if xpubs:
        env["XPUBS"] = " ".join(xpubs)
        env["WALLET_NAMES"] = "|".join(names)

    if node:
        network = _network_name(node.chain)
        if network:
            env["NETWORK"] = network
        kind = (node.node_type or "").lower()
        if kind in ("electrum", "spectrum"):
            if node.host:
                env["FULCRUM_HOST"] = str(node.host)
            if node.port is not None:
                env["FULCRUM_PORT"] = str(node.port)
            if node.ssl is not None:
                env["FULCRUM_SSL"] = "true" if node.ssl else "false"
        elif kind == "bitcoind":
            env["BIP158_P2P"] = "1"
            if node.host:
                env["NODE_IP"] = str(node.host)
            if node.port is not None:
                env["RPCPORT"] = str(node.port)
            if node.user:
                env["RPCUSER"] = str(node.user)
            if node.password:
                env["RPCPASSWORD"] = str(node.password)
    return env


def collect_wallets(specter: Any) -> list[Any]:
    """Wallets aus wallet_manager (ggf. user-spezifisch)."""
    wm = _safe_get(specter, "wallet_manager")
    if wm is None:
        return []
    wallets = _safe_get(wm, "wallets")
    if isinstance(wallets, dict):
        return list(wallets.values())
    if wallets is None:
        return []
    try:
        return list(wallets)
    except TypeError:
        return []


def build_context(specter: Any) -> SatSageContext:
    wallets_raw = collect_wallets(specter)
    wallets = [wallet_to_info(w) for w in wallets_raw]
    node = node_to_info(specter)
    env_like = build_env_like(node, wallets)
    return SatSageContext(
        wallets=wallets,
        node=node,
        env_like=env_like,
        source="specter-inprocess",
    )


def wallet_utxos(wallet: Any, limit: int = 25) -> list[dict[str, Any]]:
    utxos = _safe_get(wallet, "full_utxo") or _safe_get(wallet, "utxo") or []
    out: list[dict[str, Any]] = []
    try:
        items = list(utxos)
    except TypeError:
        return out
    for u in items[:limit]:
        if isinstance(u, dict):
            out.append(
                {
                    "txid": u.get("txid"),
                    "vout": u.get("vout"),
                    "address": u.get("address"),
                    "amount": u.get("amount"),
                    "confirmations": u.get("confirmations"),
                    "label": u.get("label"),
                }
            )
        else:
            out.append({"raw": str(u)})
    return out


def wallet_transactions(wallet: Any, limit: int = 25) -> list[dict[str, Any]]:
    txs = _safe_get(wallet, "txlist")
    if callable(txs):
        try:
            txs = txs(validate_merkle_proofs=False)
        except TypeError:
            try:
                txs = txs()
            except Exception:
                txs = []
    if txs is None:
        raw = _safe_get(wallet, "_transactions") or {}
        if isinstance(raw, dict):
            txs = list(raw.values())
        else:
            txs = []
    try:
        items = list(txs)
    except TypeError:
        return []
    out: list[dict[str, Any]] = []
    for t in items[:limit]:
        if isinstance(t, dict):
            out.append(
                {
                    "txid": t.get("txid"),
                    "category": t.get("category"),
                    "amount": t.get("amount"),
                    "confirmations": t.get("confirmations"),
                    "time": t.get("time"),
                    "address": t.get("address"),
                    "blockheight": t.get("blockheight"),
                }
            )
        else:
            out.append({"raw": str(t)})
    return out


def find_wallet_by_alias(specter: Any, alias: str) -> Any | None:
    for w in collect_wallets(specter):
        if str(_safe_get(w, "alias") or "") == alias:
            return w
    return None
