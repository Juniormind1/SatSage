"""
CLI-UTXO-/Ingress-Berichte und Tx-Output-Helfer.

Aus main.py ausgelagert (Slice 3 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from display import abbrev_display, format_sats, format_utxo_display

from core.wallet_context import WalletContext
from core.xpub_cache import (
    BITCOIN_BLOCK_INTERVAL_SECONDS,
    BITCOIN_GENESIS_TIMESTAMP,
    UTXO_INGRESS_CACHE_SUBDIR,
    iter_utxo_ingress_cache_entries,
    load_cached_tx,
    load_unspent_outpoint_values,
    load_utxo_ingress_cache,
)


_ESTIMATED_HEIGHT_CACHE: dict[str, int] = {}


def estimate_block_height_for_date(date_str: str) -> int:
    """
    Schätzt die Blockhöhe zum UTC-Tagesbeginn eines Datums.
    Annahme: konstante 10-Minuten-Blöcke ab Genesis (ohne Netzwerkabfrage).
    """
    from fulcrum import _parse_utc_date_timestamp

    key = date_str.strip()
    cached = _ESTIMATED_HEIGHT_CACHE.get(key)
    if cached is not None:
        return cached

    target_ts = _parse_utc_date_timestamp(key)
    if target_ts <= BITCOIN_GENESIS_TIMESTAMP:
        height = 0
    else:
        height = (target_ts - BITCOIN_GENESIS_TIMESTAMP) // BITCOIN_BLOCK_INTERVAL_SECONDS

    _ESTIMATED_HEIGHT_CACHE[key] = height
    return height


def _resolve_utxo_ingress_address(
    entry: dict,
    cache_root: Path | None = None,
) -> str | None:
    """Adresse eines gecachten UTXO-Eintrags (Cache-Feld oder Tx-Flatfile)."""
    address = entry.get("address")
    if address:
        return str(address)

    txid = str(entry.get("txid", "")).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", txid):
        return None
    try:
        vout = int(entry.get("vout", -1))
    except (TypeError, ValueError):
        return None
    if vout < 0:
        return None

    tx = load_cached_tx(txid, cache_root)
    if not tx:
        return None
    vouts = tx.get("vout", [])
    if vout >= len(vouts):
        return None
    addrs = _extract_addresses(vouts[vout])
    if not addrs:
        return None
    return addrs[0] if len(addrs) == 1 else ", ".join(addrs)


def print_analyzed_utxo_ingress_report(
    cache_root: Path | None = None,
    utxo_cache_dir: Path | None = None,
    unspent_values: dict[str, int] | None = None,
) -> int:
    """Listet gespeicherte Herkunfts-Analysen zu Outputs (auch bereits ausgegebene).

    Noch unspent Outputs (laut Wallet-UTXO-Cache) werden mit ``UTXO: <Saldo>`` markiert.
    """
    entries = iter_utxo_ingress_cache_entries(cache_root)
    if not entries:
        print(
            "\nKeine gespeicherten Herkunfts-Analysen gefunden "
            f"({UTXO_INGRESS_CACHE_SUBDIR}/ im Immutable-Cache leer)."
        )
        return 0

    if unspent_values is None:
        unspent_values = load_unspent_outpoint_values(utxo_cache_dir)

    entries.sort(
        key=lambda e: (
            -(e.get("youngest_time_ts") or 0),
            str(e.get("txid", "")),
            int(e.get("vout", 0)),
        )
    )
    unique_txids = {str(e.get("txid", "")).lower() for e in entries}

    unspent_count = 0
    for entry in entries:
        try:
            key = f"{str(entry.get('txid', '')).lower()}:{int(entry.get('vout', -1))}"
        except (TypeError, ValueError):
            continue
        if key in unspent_values:
            unspent_count += 1

    print(f"\n{'=' * 85}")
    print(
        f"Herkunfts-Analysen: {len(entries)}  |  "
        f"davon unspent UTXOs: {unspent_count}  |  "
        f"verschiedene TxIDs: {len(unique_txids)}"
    )
    print(
        "  (Tx-Outputs mit gespeicherter Jüngste-Sats-Analyse — "
        "inkl. bereits ausgegebener; unspent = laut Wallet-UTXO-Cache)"
    )
    print(f"{'=' * 85}\n")

    for index, entry in enumerate(entries, start=1):
        txid = str(entry.get("txid", ""))
        vout_raw = entry.get("vout")
        youngest_time = entry.get("youngest_time") or "unbekannt"
        youngest_wallet = entry.get("youngest_wallet") or "?"
        youngest_sats = entry.get("youngest_sats")

        has_vout = False
        vout = -1
        try:
            vout = int(vout_raw)
            has_vout = vout >= 0
        except (TypeError, ValueError):
            has_vout = False

        unspent_sats: int | None = None
        if has_vout:
            unspent_sats = unspent_values.get(f"{txid.lower()}:{vout}")
            address = _resolve_utxo_ingress_address(entry, cache_root)
            out_ref = format_utxo_display(txid, vout, address=None)
            if address:
                ref_label = f"Output {out_ref}  →  {abbrev_display(address)}"
            else:
                ref_label = f"Output {out_ref}"
        else:
            ref_label = f"TxID: {abbrev_display(txid)}"

        print(f"{index:3}. {ref_label}")
        if unspent_sats is not None:
            print(f"     UTXO: {format_sats(unspent_sats)}")
        print(f"     Jüngste Sats zugegangen: {youngest_time}")
        if youngest_sats is not None:
            try:
                sats = int(youngest_sats)
                print(f"     Wallet: {youngest_wallet}    Jüngste Sats: {sats:,}")
            except (TypeError, ValueError):
                print(f"     Wallet: {youngest_wallet}")
        else:
            print(f"     Wallet: {youngest_wallet}")
        print()

    return len(entries)
def _extract_addresses(vout: dict) -> list[str]:
    """Adressen aus RPC-/Electrum-Output extrahieren."""
    if "scriptpubkey_address" in vout:
        addr = vout.get("scriptpubkey_address")
        return [addr] if addr else []

    spk = vout.get("scriptPubKey", {})
    if spk.get("address"):
        return [spk["address"]]
    return spk.get("addresses", [])


def _extract_value_sats(vout: dict) -> int:
    """Wert in Satoshis aus RPC- (float BTC) oder Esplora-Format (Satoshis)."""
    if "scriptpubkey_address" in vout or "scriptpubkey" in vout:
        return int(vout.get("value", 0))
    return int(round(float(vout.get("value", 0)) * 1e8))


def _extract_value_btc(vout: dict) -> float:
    """Wert in BTC aus RPC- (float) oder Esplora-Format (Satoshis)."""
    return _extract_value_sats(vout) / 1e8


def _tx_block_height(tx: dict) -> int | None:
    """Blockhöhe der Tx (Fulcrum verbose oder Hex-Anreicherung)."""
    status = tx.get("status", {})
    if status.get("block_height") is not None:
        return int(status["block_height"])
    if tx.get("blockheight") is not None:
        return int(tx["blockheight"])
    if tx.get("blockHeight") is not None:
        return int(tx["blockHeight"])
    return None


def _tx_block_time(tx: dict) -> int | None:
    """Unix-Zeitstempel der Tx (Electrum oder RPC)."""
    status = tx.get("status", {})
    if status.get("block_time"):
        return status["block_time"]
    if tx.get("blocktime"):
        return tx["blocktime"]
    if tx.get("time"):
        return tx["time"]
    return None


def _format_tx_time(tx: dict) -> str:
    """Datum/Uhrzeit der Tx; bei Blockhöhe auch Blocknummer anzeigen."""
    ts = _tx_block_time(tx)
    height = _tx_block_height(tx)

    if ts is None and height is None:
        return "unbekannt"
    if height is not None and height > 0 and ts is not None:
        dt = datetime.fromtimestamp(ts)
        label = dt.strftime("%d.%m.%Y %H:%M:%S")
        confirmed = tx.get("status", {}).get(
            "confirmed",
            tx.get("confirmations", 0) > 0,
        )
        block_label = f"Block {height:,}"
        if not confirmed:
            return f"{block_label} · {label} (noch unbestätigt)"
        return f"{block_label} · {label}"
    if height is not None and height > 0:
        return f"Block {height:,}"

    dt = datetime.fromtimestamp(ts)
    label = dt.strftime("%d.%m.%Y %H:%M:%S")
    confirmed = tx.get("status", {}).get("confirmed", tx.get("confirmations", 0) > 0)
    if not confirmed:
        return f"{label} (noch unbestätigt)"
    return label
def _format_utxo_status(utxo: dict) -> str:
    """Datum/Uhrzeit, wann das UTXO erstellt (bestätigt) wurde."""
    status = utxo.get("status", {})
    return _format_tx_time({
        "status": status,
        "blocktime": status.get("block_time"),
        "blockheight": status.get("block_height"),
        "confirmations": 1 if status.get("confirmed") else 0,
    })

















def _print_utxo_rank_row(
    rank: int,
    utxo: dict,
    wallet: WalletContext | None,
    immutable_cache_dir: Path | None = None,
) -> None:
    addr = utxo.get("address", "?")
    wallet_label = wallet.resolve_address(addr) if wallet else None
    if not wallet_label:
        if addr and addr != "?":
            wallet_label = hashlib.sha256(addr.encode()).hexdigest()
        else:
            wallet_label = "?"

    timestamp = _format_utxo_status(utxo)
    print(
        f"{rank:2}. {format_sats(utxo['value']):>14}  {timestamp}"
    )
    print(f"    Wallet: {wallet_label}    Adresse: {abbrev_display(addr)}")
    print(f"    UTXO: {format_utxo_display(utxo['txid'], utxo['vout'], address=addr)}")
    if immutable_cache_dir:
        ingress = load_utxo_ingress_cache(
            utxo["txid"], utxo["vout"], immutable_cache_dir
        )
        if ingress and ingress.get("youngest_time"):
            print(f"    Jüngste Sats im UTXO: {ingress['youngest_time']}")
    print()


def print_utxo_rank_entries(
    sorted_utxos: list[dict],
    start: int,
    end: int,
    wallet: WalletContext | None = None,
    immutable_cache_dir: Path | None = None,
) -> None:
    """Druckt Ranglisten-Einträge [start, end) (0-basiert)."""
    for index in range(start, min(end, len(sorted_utxos))):
        _print_utxo_rank_row(index + 1, sorted_utxos[index], wallet, immutable_cache_dir)


def list_top_wallet_utxos(
    all_utxos: list,
    limit: int,
    wallet: WalletContext | None = None,
    immutable_cache_dir: Path | None = None,
) -> list[dict]:
    """Listet die größten unspent UTXOs; gibt die vollständige sortierte Liste zurück."""
    if not all_utxos:
        print("Keine unspent UTXOs im Wallet gefunden.")
        return []

    sorted_utxos = sorted(all_utxos, key=lambda u: u["value"], reverse=True)
    total_count = len(sorted_utxos)
    total_sats = sum(u["value"] for u in sorted_utxos)
    shown_end = min(limit, total_count)
    shown = sorted_utxos[:shown_end]
    shown_sats = sum(u["value"] for u in shown)

    print(f"\n{'='*85}")
    print(
        f"Wallet-UTXOs: {total_count} unspent gesamt, "
        f"{format_sats(total_sats)}"
    )
    print(
        f"Top {shown_end} (Limit: {limit}): "
        f"{format_sats(shown_sats)}"
    )
    print(f"{'='*85}\n")

    print_utxo_rank_entries(sorted_utxos, 0, shown_end, wallet, immutable_cache_dir)

    if total_count > shown_end:
        print(f"... und {total_count - shown_end} weitere UTXO(s) in der Rangliste")
    print(f"{'='*85}")
    return sorted_utxos
