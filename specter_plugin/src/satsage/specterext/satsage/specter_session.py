"""
SatSage-Runtime aus Specter-Kontext.

Baut WalletContext + Blockchain-Fetchers (bevorzugt BIP-158/Core aus Specter-Node)
und stellt nicht-interaktive Analyse-Aufrufe bereit (stdout → Text für die UI).
"""

from __future__ import annotations

import io
import logging
import sys
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from .bridge import (
    SatSageContext,
    build_context,
    collect_wallets,
    find_wallet_by_alias,
    wallet_to_info,
    wallet_utxos as bridge_wallet_utxos,
    _safe_get,
)

logger = logging.getLogger(__name__)

# …/SatSage/specter_plugin/src/satsage/specterext/satsage/specter_session.py
# Datei-parents: pkg → specterext → ns → src → specter_plugin → repo(SatSage)
_SATSAGE_ROOT = Path(__file__).resolve().parents[5]

_session_lock = threading.RLock()
_cached: "SatSageSession | None" = None
_cached_fingerprint: str = ""


def ensure_satsage_on_path() -> Path:
    root = str(_SATSAGE_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return _SATSAGE_ROOT


def _amount_to_sats(amount: Any) -> int:
    """Specter speichert UTXO-Beträge typischerweise in BTC (float)."""
    if amount is None:
        return 0
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return 0
    # Heuristik: >= 21e6 könnte schon sats sein (aber 21 BTC wäre möglich)
    # Specter API-Doku zeigt amount in BTC → immer * 1e8
    return int(round(val * 1e8))


def convert_specter_utxo(
    raw: dict[str, Any],
    *,
    wallet_name: str | None = None,
    xpub: str | None = None,
) -> dict[str, Any]:
    conf = raw.get("confirmations")
    try:
        conf_i = int(conf) if conf is not None else 0
    except (TypeError, ValueError):
        conf_i = 0
    block_time = raw.get("time") or raw.get("blocktime")
    try:
        block_time_i = int(block_time) if block_time is not None else None
    except (TypeError, ValueError):
        block_time_i = None

    status: dict[str, Any] = {
        "confirmed": conf_i > 0,
    }
    if block_time_i is not None:
        status["block_time"] = block_time_i

    out: dict[str, Any] = {
        "txid": str(raw.get("txid") or ""),
        "vout": int(raw.get("vout") or 0),
        "value": _amount_to_sats(raw.get("amount")),
        "address": str(raw.get("address") or ""),
        "confirmations": conf_i,
        "status": status,
    }
    if wallet_name:
        out["wallet"] = wallet_name
    if xpub:
        out["xpub"] = xpub
    if block_time_i is not None:
        out["blocktime"] = block_time_i
    label = raw.get("label")
    if label:
        out["label"] = str(label).strip()
    return out


def collect_specter_utxos(
    specter: Any,
    *,
    wallet_alias: str | None = None,
) -> list[dict[str, Any]]:
    """Alle (oder ein Wallet) Specter-UTXOs im SatSage-Format."""
    wallets = collect_wallets(specter)
    out: list[dict[str, Any]] = []
    for w in wallets:
        alias = str(_safe_get(w, "alias") or "")
        if wallet_alias and alias != wallet_alias:
            continue
        info = wallet_to_info(w)
        raw_utxos = _safe_get(w, "full_utxo") or _safe_get(w, "utxo") or []
        try:
            items = list(raw_utxos)
        except TypeError:
            items = []
        primary_xpub = info.xpubs[0] if info.xpubs else None
        for u in items:
            if not isinstance(u, dict):
                continue
            out.append(
                convert_specter_utxo(
                    u, wallet_name=info.name, xpub=primary_xpub
                )
            )
    out.sort(key=lambda u: u.get("value", 0), reverse=True)
    return out


def seed_wallet_from_specter(wallet_ctx, specter: Any) -> int:
    """Trägt Specter-Adressen und UTXO-Adressen in den WalletContext ein."""
    seeded = 0
    for w in collect_wallets(specter):
        info = wallet_to_info(w)
        name = info.name
        xpubs = info.xpubs
        primary = xpubs[0] if xpubs else None
        # bekannte Adressen aus Specter
        raw_addrs = _safe_get(w, "_addresses") or {}
        if isinstance(raw_addrs, dict):
            for key, obj in raw_addrs.items():
                addr = key if isinstance(key, str) else _safe_get(obj, "address")
                if not addr:
                    continue
                addr = str(addr)
                if addr not in wallet_ctx.address_to_wallet:
                    wallet_ctx.address_to_wallet[addr] = name
                    if primary:
                        wallet_ctx.address_to_xpub[addr] = primary
                    seeded += 1
        # UTXO-Adressen
        raw_utxos = _safe_get(w, "full_utxo") or _safe_get(w, "utxo") or []
        try:
            items = list(raw_utxos)
        except TypeError:
            items = []
        for u in items:
            if not isinstance(u, dict):
                continue
            addr = u.get("address")
            if not addr:
                continue
            addr = str(addr)
            if addr not in wallet_ctx.address_to_wallet:
                wallet_ctx.address_to_wallet[addr] = name
                if primary:
                    wallet_ctx.address_to_xpub[addr] = primary
                seeded += 1
    return seeded


def context_fingerprint(ctx: SatSageContext) -> str:
    node = ctx.node
    node_key = ""
    if node:
        node_key = f"{node.host}:{node.port}:{node.user}:{node.chain}:{node.node_type}:{node.protocol}:{node.ssl}"
    wallets = "|".join(
        f"{w.alias}:{w.name}:{w.recv_descriptor or ''}:{w.change_descriptor or ''}:{','.join(w.xpubs)}"
        for w in ctx.wallets
    )
    return f"{node_key}::{wallets}"


def _merged_env(ctx: SatSageContext) -> dict[str, str]:
    """SatSage-.env als Basis, Specter-Node/XPUBs überschreiben."""
    ensure_satsage_on_path()
    import main as xq_main

    env = dict(xq_main._load_dotenv(xq_main.ENV_FILE))
    # Specter-Kontext gewinnt
    env.update({k: v for k, v in ctx.env_like.items() if v})
    mapped_node_keys = {"NETWORK", "BIP158_P2P", "NODE_IP", "RPCPORT", "RPCUSER", "RPCPASSWORD", "FULCRUM_HOST", "FULCRUM_PORT", "FULCRUM_SSL"}
    for key in mapped_node_keys - set(ctx.env_like):
        env.pop(key, None)
    return env


def _build_args(ctx: SatSageContext, env: dict[str, str], *, max_addresses: int):
    xpubs = ctx.all_xpubs()
    # Namen 1:1 zu XPUBs (Bridge erzeugt pro XPUB den Wallet-Namen)
    names: list[str] = []
    for w in ctx.wallets:
        for _x in w.xpubs:
            names.append(w.name)
    # falls Dedup in all_xpubs Namen-Länge bricht: neu mappen
    if len(names) != len(xpubs):
        names = []
        for x in xpubs:
            label = next((w.name for w in ctx.wallets if x in w.xpubs), None)
            names.append(label or x[:16])

    bip158_start = None
    raw = env.get("BIP158_START_HEIGHT")
    if raw:
        try:
            bip158_start = int(raw)
        except ValueError:
            pass

    return SimpleNamespace(
        xpubs=xpubs,
        wallet_names=names,
        max_addresses=max_addresses,
        max_addresses_per_xpub=None,
        bip158=False,
        bip158_start=bip158_start,
        rpc_only=False,
        esplora=None,
        rescan=False,
        cache_dir=str(_SATSAGE_ROOT / "utxo_cache"),
        immutable_cache_dir=str(_SATSAGE_ROOT / "immutable_cache"),
        rpchost=None,
        rpcport=None,
        fulcrum_host=None,
        fulcrum_port=None,
        fulcrum_no_ssl=False,
        no_verbose=True,
        top_utxos=25,
    )


@dataclass
class SatSageSession:
    """Laufzeit-Session für das Plugin (thread-sicher über Modul-Lock)."""

    ctx: SatSageContext
    env: dict[str, str]
    args: Any
    wallet_ctx: Any
    source: str
    fetchers: dict[str, Any]
    specter_utxos: list[dict[str, Any]] = field(default_factory=list)
    setup_log: str = ""
    root: Path = field(default_factory=lambda: _SATSAGE_ROOT)

    @property
    def own_addresses(self) -> set[str]:
        return set(self.wallet_ctx.address_to_wallet.keys())

    @property
    def cache_dir(self) -> Path:
        return Path(self.args.cache_dir)

    @property
    def immutable_cache_dir(self) -> Path:
        return Path(
            self.fetchers.get("immutable_cache_dir")
            or self.args.immutable_cache_dir
            or (_SATSAGE_ROOT / "immutable_cache")
        )


def _setup_session(specter: Any, *, max_addresses: int = 200) -> SatSageSession:
    ensure_satsage_on_path()
    import main as xq_main
    from display import set_verbose

    set_verbose(False)

    ctx = build_context(specter)
    if not ctx.all_xpubs():
        raise RuntimeError("Keine XPUBs in Specter-Wallets gefunden.")

    env = _merged_env(ctx)
    args = _build_args(ctx, env, max_addresses=max_addresses)

    log_buf = io.StringIO()
    with redirect_stdout(log_buf), redirect_stderr(log_buf):
        wallet_ctx = xq_main.build_wallet_context(
            args.xpubs,
            wallet_names=args.wallet_names,
            max_addresses=args.max_addresses,
        )
        seeded = seed_wallet_from_specter(wallet_ctx, specter)
        xq_main.seed_wallet_addresses_from_utxo_cache(
            wallet_ctx, args.xpubs, Path(args.cache_dir)
        )
        xq_main.init_external_address_cache(
            Path(args.cache_dir), args.xpubs, xq_main.MAX_TRACE_ADDRESS_SEARCH
        )
        xq_main.seed_wallet_addresses_from_resolution_cache(wallet_ctx, args.xpubs)

        print(
            f"WalletContext: {len(args.xpubs)} XPUB(s), "
            f"{len(wallet_ctx.address_to_wallet)} Adressen "
            f"(+{seeded} aus Specter geseedet)",
            flush=True,
        )

        source, backend = xq_main._setup_blockchain_client(
            args, env, interactive_onion=False
        )
        fetchers = xq_main._build_blockchain_fetchers(
            source,
            backend,
            args,
            wallet_ctx,
            immutable_cache_dir=Path(args.immutable_cache_dir),
        )

    specter_utxos = collect_specter_utxos(specter)
    try:
        from .specter_seed import seed_caches_from_specter

        seed_caches_from_specter(
            specter,
            ctx,
            Path(args.cache_dir),
            source_tag=f"specter+{source}",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Specter-Cache-Seed fehlgeschlagen: %s", exc)

    return SatSageSession(
        ctx=ctx,
        env=env,
        args=args,
        wallet_ctx=wallet_ctx,
        source=source,
        fetchers=fetchers,
        specter_utxos=specter_utxos,
        setup_log=log_buf.getvalue(),
        root=_SATSAGE_ROOT,
    )


def get_session(specter: Any, *, force_reload: bool = False) -> SatSageSession:
    global _cached, _cached_fingerprint
    ctx = build_context(specter)
    fp = context_fingerprint(ctx)
    with _session_lock:
        if (
            not force_reload
            and _cached is not None
            and _cached_fingerprint == fp
        ):
            # UTXOs frisch aus Specter (können sich ändern ohne XPUB-Wechsel)
            _cached.specter_utxos = collect_specter_utxos(specter)
            return _cached
        _cached = _setup_session(specter)
        _cached_fingerprint = fp
        return _cached


def capture_output(fn: Callable[[], Any]) -> tuple[Any, str, str | None]:
    """Führt fn aus, fängt stdout/stderr. Rückgabe: (result, text, error)."""
    buf = io.StringIO()
    err: str | None = None
    result = None
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            result = fn()
    except SystemExit as exc:
        err = f"Abbruch: {exc}"
        print(err, file=buf)
    except Exception:
        err = traceback.format_exc()
        print(err, file=buf)
    return result, buf.getvalue(), err


def run_analyze_tx(session: SatSageSession, txid: str) -> tuple[str, str | None]:
    ensure_satsage_on_path()
    from analyze import analyze_tx

    txid = (txid or "").strip().lower()
    if not txid or len(txid) != 64:
        return "", "Ungültige TxID (64 Hex-Zeichen erwartet)."

    def _run():
        return analyze_tx(
            session.fetchers["get_tx"],
            txid,
            session.own_addresses,
            wallet=session.wallet_ctx,
            cache_dir=session.cache_dir,
            fetch_address_utxos=session.fetchers.get("fetch_address_utxos"),
            cache_source=session.source,
            allow_tx_followup=False,
        )

    _res, text, err = capture_output(_run)
    return text, err


def run_analyze_utxo(
    session: SatSageSession,
    utxo_ref: str,
    *,
    address: str | None = None,
) -> tuple[str, str | None]:
    ensure_satsage_on_path()
    from analyze import analyze_address_utxos, _parse_utxo_ref

    ref = (utxo_ref or "").strip()
    parsed = _parse_utxo_ref(ref)
    if not parsed:
        return "", "Ungültiges UTXO (Format: txid:vout)."

    txid, vout = parsed
    addr = (address or "").strip()
    if not addr:
        for u in session.specter_utxos:
            if u.get("txid") == txid and int(u.get("vout", -1)) == vout:
                addr = u.get("address") or ""
                break
    if not addr:
        return "", "Adresse zum UTXO unbekannt — bitte Adresse angeben."

    # Einzelnes UTXO: fetch_utxos liefert nur dieses (ohne Chain-Scan der Adresse)
    utxo_obj = None
    for u in session.specter_utxos:
        if u.get("txid") == txid and int(u.get("vout", -1)) == vout:
            utxo_obj = u
            break

    def _fetch_utxos(_address: str):
        if utxo_obj:
            return [utxo_obj]
        return session.fetchers["fetch_utxos"](_address)

    def _run():
        return analyze_address_utxos(
            session.fetchers["get_tx"],
            _fetch_utxos,
            addr,
            session.own_addresses,
            utxo_ref=f"{txid}:{vout}",
            wallet=session.wallet_ctx,
            cache_dir=session.cache_dir,
            fetch_address_utxos=session.fetchers.get("fetch_address_utxos"),
            cache_source=session.source,
        )

    _res, text, err = capture_output(_run)
    return text, err


def run_utxo_rank(
    session: SatSageSession,
    *,
    wallet_alias: str | None = None,
    limit: int = 25,
) -> tuple[list[dict[str, Any]], str, str | None]:
    ensure_satsage_on_path()
    import main as xq_main

    utxos = list(session.specter_utxos)
    if wallet_alias:
        name = next(
            (w.name for w in session.ctx.wallets if w.alias == wallet_alias),
            None,
        )
        if name:
            utxos = [u for u in utxos if u.get("wallet") == name]
        else:
            utxos = []

    def _run():
        return xq_main.list_top_wallet_utxos(
            utxos,
            limit,
            wallet=session.wallet_ctx,
            immutable_cache_dir=session.immutable_cache_dir,
        )

    ranked, text, err = capture_output(_run)
    return ranked or [], text, err


def run_trace_utxos(
    session: SatSageSession,
    utxos: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> tuple[str, str | None]:
    ensure_satsage_on_path()
    from analyze import trace_known_utxos

    subset = sorted(utxos, key=lambda u: u.get("value", 0), reverse=True)[:limit]

    def _run():
        return trace_known_utxos(
            session.fetchers["get_tx"],
            subset,
            session.own_addresses,
            wallet=session.wallet_ctx,
            cache_dir=session.cache_dir,
            fetch_address_utxos=session.fetchers.get("fetch_address_utxos"),
            cache_source=session.source,
            tx_oriented_followup=False,
        )

    _res, text, err = capture_output(_run)
    return text, err
