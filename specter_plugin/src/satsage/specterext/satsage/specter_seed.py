"""Specter → SatSage-Caches: UTXOs, Verlauf, Labels, Scan-Indizes.

Ziel: Der Nutzer pflegt Node/Wallets in Specter; SatSage übernimmt Bestand und
Historie als Light-Seed, ohne doppelte Konfiguration und ohne Full-Rescan.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .bridge import (
    SatSageContext,
    _safe_get,
    collect_wallets,
    wallet_to_info,
)
from .specter_session import (
    collect_specter_utxos,
    convert_specter_utxo,
    ensure_satsage_on_path,
)

logger = logging.getLogger(__name__)

_LABELS_NAME = "specter_address_labels.json"
_DEFAULT_GAP = 20
_MIN_MAX_ADDRESSES = 200


def _wallet_indices(wallet: Any) -> tuple[int, int]:
    """Receive-/Change-Index aus Specter (0-basiert, höchster bekannter)."""
    recv = _safe_get(wallet, "address_index", "recv_index", "index")
    change = _safe_get(wallet, "change_index")
    try:
        recv_i = max(0, int(recv)) if recv is not None else 0
    except (TypeError, ValueError):
        recv_i = 0
    try:
        change_i = max(0, int(change)) if change is not None else 0
    except (TypeError, ValueError):
        change_i = 0
    # Adressliste kann höhere Indizes tragen als die Counter
    raw_addrs = _safe_get(wallet, "_addresses") or {}
    if isinstance(raw_addrs, dict):
        for obj in raw_addrs.values():
            if not isinstance(obj, dict):
                continue
            try:
                idx = int(obj.get("index"))
            except (TypeError, ValueError, AttributeError):
                continue
            if obj.get("change") or obj.get("is_change"):
                change_i = max(change_i, idx)
            else:
                recv_i = max(recv_i, idx)
    return recv_i, change_i


def suggested_max_addresses(wallet: Any, *, minimum: int = _MIN_MAX_ADDRESSES) -> int:
    """Scan-Fenster: 2×(max Index + Gap), mindestens ``minimum`` (Empfang+Change)."""
    recv_i, change_i = _wallet_indices(wallet)
    tip = max(recv_i, change_i) + _DEFAULT_GAP + 1
    return max(minimum, tip * 2)


def scan_end_index_for_wallet(wallet: Any) -> int:
    """Höchster bekannter Empfangs-/Change-Index + 1 (eine Kette)."""
    recv_i, change_i = _wallet_indices(wallet)
    return max(recv_i, change_i) + 1


def _collect_labels(wallet: Any) -> dict[str, str]:
    """Adresse → Label aus Specter (UTXOs, Adressbuch, getlabel)."""
    out: dict[str, str] = {}
    getlabel = getattr(wallet, "getlabel", None)

    def _put(addr: Any, label: Any) -> None:
        a = str(addr or "").strip()
        lab = str(label or "").strip()
        if a and lab:
            out[a] = lab

    raw_addrs = _safe_get(wallet, "_addresses") or {}
    if isinstance(raw_addrs, dict):
        for key, obj in raw_addrs.items():
            if isinstance(obj, dict):
                _put(obj.get("address") or key, obj.get("label"))
            elif isinstance(key, str) and callable(getlabel):
                try:
                    _put(key, getlabel(key))
                except Exception:
                    pass

    for u in _safe_get(wallet, "full_utxo") or _safe_get(wallet, "utxo") or []:
        if isinstance(u, dict):
            _put(u.get("address"), u.get("label"))

    if callable(getlabel):
        for addr in list(out):
            try:
                lab = getlabel(addr)
            except Exception:
                continue
            _put(addr, lab)

    return out


def _labels_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / _LABELS_NAME


def merge_specter_labels(cache_dir: Path, labels: dict[str, str]) -> int:
    """Schreibt/merged Nutzer-Labels aus Specter (nicht am-i.exposed)."""
    if not labels:
        return 0
    path = _labels_path(cache_dir)
    bisher: dict[str, str] = {}
    if path.is_file():
        try:
            roh = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(roh, dict):
                bisher = {str(k): str(v) for k, v in roh.items() if k and v}
        except (OSError, json.JSONDecodeError, TypeError):
            bisher = {}
    bisher.update(labels)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bisher, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return len(labels)


def load_specter_labels(cache_dir: Path) -> dict[str, str]:
    path = _labels_path(cache_dir)
    if not path.is_file():
        return {}
    try:
        roh = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(roh, dict):
        return {}
    return {str(k): str(v) for k, v in roh.items() if k and v}


def _amount_sats(amount: Any) -> int:
    if amount is None:
        return 0
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return 0
    return int(round(val * 1e8))


def _specter_tx_list(wallet: Any) -> list[dict[str, Any]]:
    txs = _safe_get(wallet, "txlist")
    if callable(txs):
        try:
            txs = txs(fetch_transactions=False, validate_merkle_proofs=False)
        except TypeError:
            try:
                txs = txs(validate_merkle_proofs=False)
            except TypeError:
                try:
                    txs = txs()
                except Exception:
                    txs = []
            except Exception:
                txs = []
        except Exception:
            txs = []
    if txs is None:
        raw = _safe_get(wallet, "_transactions") or {}
        if hasattr(raw, "get_transactions"):
            try:
                txs = raw.get_transactions()
            except Exception:
                txs = []
        elif isinstance(raw, dict):
            txs = list(raw.values())
        else:
            txs = []
    try:
        return [t for t in list(txs) if isinstance(t, dict)]
    except TypeError:
        return []


def _verlauf_from_utxo(u: dict[str, Any]) -> dict[str, Any] | None:
    txid = str(u.get("txid") or "").strip()
    if not txid:
        return None
    try:
        vout = int(u.get("vout") or 0)
    except (TypeError, ValueError):
        vout = 0
    conf = int(u.get("confirmations") or 0)
    status = u.get("status") if isinstance(u.get("status"), dict) else {}
    block_time = status.get("block_time") or u.get("blocktime") or u.get("time")
    try:
        block_time_i = int(block_time) if block_time is not None else None
    except (TypeError, ValueError):
        block_time_i = None
    height = status.get("block_height")
    try:
        height_i = int(height) if height is not None else (1 if conf > 0 else 0)
    except (TypeError, ValueError):
        height_i = 1 if conf > 0 else 0
    value = u.get("value")
    if value is None:
        value = _amount_sats(u.get("amount"))
    return {
        "txid": txid,
        "vout": vout,
        "value": int(value or 0),
        "address": str(u.get("address") or ""),
        "status": {
            "confirmed": conf > 0 or bool(status.get("confirmed")),
            "block_height": height_i,
            "block_time": block_time_i,
        },
        "spent": False,
        "spent_txid": None,
        "label": str(u.get("label") or "").strip() or None,
        "source": "specter",
    }


def _verlauf_from_receive_tx(tx: dict[str, Any]) -> dict[str, Any] | None:
    """Receive-Tx → Verlaufseintrag, nur wenn vout bekannt."""
    category = str(tx.get("category") or "").lower()
    if category not in ("receive", "generate", "immature"):
        return None
    txid = str(tx.get("txid") or "").strip()
    if not txid:
        return None
    if tx.get("vout") is None and tx.get("n") is None:
        # Ohne vout kein stabiler UTXO-Key — überspringen (UTXO-Seed deckt Unspent).
        return None
    try:
        vout = int(tx.get("vout") if tx.get("vout") is not None else tx.get("n") or 0)
    except (TypeError, ValueError):
        return None
    conf = int(tx.get("confirmations") or 0)
    try:
        height = int(tx["blockheight"]) if tx.get("blockheight") is not None else (1 if conf > 0 else 0)
    except (TypeError, ValueError):
        height = 1 if conf > 0 else 0
    try:
        block_time = int(tx["time"]) if tx.get("time") is not None else None
    except (TypeError, ValueError):
        block_time = None
    addr = tx.get("address")
    if isinstance(addr, list):
        addr = addr[0] if addr else ""
    return {
        "txid": txid,
        "vout": vout,
        "value": _amount_sats(tx.get("amount")),
        "address": str(addr or ""),
        "status": {
            "confirmed": conf > 0,
            "block_height": height,
            "block_time": block_time,
        },
        "spent": False,
        "spent_txid": None,
        "label": str(tx.get("label") or "").strip() or None,
        "source": "specter",
    }


def seed_caches_from_specter(
    specter: Any,
    ctx: SatSageContext,
    cache_dir: Path,
    *,
    source_tag: str = "specter",
) -> dict[str, int]:
    """
    Schreibt UTXO-Cache, Verlaufs-Merge und Labels aus Specter.

    Rückgabe: Zähler für Log/UI.
    """
    ensure_satsage_on_path()
    import main as xq_main

    cache_dir = Path(cache_dir)
    stats = {
        "wallets": 0,
        "utxo_files": 0,
        "utxos": 0,
        "verlauf_merged": 0,
        "labels": 0,
    }

    wallets = collect_wallets(specter)
    # Pro XPUB: UTXOs + Meta aus zugehörigem Specter-Wallet
    xpub_meta: dict[str, dict[str, Any]] = {}
    for w in wallets:
        info = wallet_to_info(w)
        max_addr = suggested_max_addresses(w)
        end_idx = scan_end_index_for_wallet(w)
        for xpub in info.xpubs:
            xpub_meta[xpub] = {
                "wallet": w,
                "info": info,
                "max_addresses": max_addr,
                "scan_end_index": end_idx,
            }
        stats["wallets"] += 1

    all_labels: dict[str, str] = {}
    for w in wallets:
        all_labels.update(_collect_labels(w))
    stats["labels"] = merge_specter_labels(cache_dir, all_labels)

    utxos = collect_specter_utxos(specter)
    by_xpub: dict[str, list[dict]] = {x: [] for x in ctx.all_xpubs()}
    for u in utxos:
        xp = u.get("xpub")
        if xp and xp in by_xpub:
            by_xpub[xp].append(u)
        elif by_xpub:
            by_xpub[next(iter(by_xpub))].append(u)

    for xpub, liste in by_xpub.items():
        meta = xpub_meta.get(xpub) or {}
        max_addr = int(meta.get("max_addresses") or _MIN_MAX_ADDRESSES)
        end_idx = int(meta.get("scan_end_index") or max_addr // 2)
        # Labels auf UTXOs nachziehen
        for u in liste:
            addr = str(u.get("address") or "")
            if addr and not u.get("label") and addr in all_labels:
                u["label"] = all_labels[addr]
        try:
            if liste:
                xq_main.save_xpub_utxo_cache(
                    xpub,
                    liste,
                    cache_dir,
                    source=source_tag,
                    scan_end_index=max(end_idx, 1),
                    max_addresses=max_addr,
                )
                stats["utxo_files"] += 1
                stats["utxos"] += len(liste)
            elif xpub in xpub_meta:
                # Indizes trotzdem merken (leerer Bestand, aber Scan-Fenster)
                bisher = xq_main.load_xpub_utxo_cache(xpub, cache_dir) or []
                xq_main.save_xpub_utxo_cache(
                    xpub,
                    bisher,
                    cache_dir,
                    source=source_tag,
                    scan_end_index=max(end_idx, 1),
                    max_addresses=max_addr,
                )
        except Exception as exc:
            logger.warning("UTXO-Seed %s…: %s", xpub[:16], exc)

        verlauf_neu: list[dict[str, Any]] = []
        for u in liste:
            ein = _verlauf_from_utxo(u)
            if ein:
                verlauf_neu.append(ein)

        wallet_obj = meta.get("wallet")
        if wallet_obj is not None:
            for tx in _specter_tx_list(wallet_obj):
                ein = _verlauf_from_receive_tx(tx)
                if ein:
                    if not ein.get("label"):
                        addr = ein.get("address") or ""
                        if addr in all_labels:
                            ein["label"] = all_labels[addr]
                    verlauf_neu.append(ein)

        if verlauf_neu:
            try:
                path = xq_main.merke_bip158_verlauf(xpub, verlauf_neu, cache_dir)
                stats["verlauf_merged"] += len(verlauf_neu)
                logger.info(
                    "Specter-Verlauf → %s (%s Einträge)",
                    path.name,
                    len(verlauf_neu),
                )
            except Exception as exc:
                logger.warning("Verlauf-Seed %s…: %s", xpub[:16], exc)

    return stats


def wallet_entries_with_specter_limits(ctx: SatSageContext, specter: Any):
    """WalletEntry-Liste inkl. max_addresses aus Specter-Indizes."""
    ensure_satsage_on_path()
    from core.config import WalletEntry

    by_alias = {
        str(_safe_get(w, "alias") or ""): w for w in collect_wallets(specter)
    }
    eintraege = []
    gesehen: set[str] = set()
    for info in ctx.wallets:
        w = by_alias.get(info.alias)
        max_addr = suggested_max_addresses(w) if w is not None else _MIN_MAX_ADDRESSES
        if info.recv_descriptor:
            eintraege.append(
                WalletEntry(
                    name=info.name or info.alias or "Specter-Wallet",
                    descriptor=info.recv_descriptor,
                    max_addresses=max_addr,
                )
            )
            continue
        for xpub in info.xpubs:
            if not xpub or xpub in gesehen:
                continue
            gesehen.add(xpub)
            eintraege.append(
                WalletEntry(
                    xpub=xpub,
                    name=info.name or xpub[:16],
                    script_type="auto",
                    max_addresses=max_addr,
                )
            )
    return eintraege
