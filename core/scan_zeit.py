"""Datum ↔ Blockhöhe für den P2P-Scan-Start.

Reihenfolge: lokale Header-Datei, verbundener Block-Explorer, 10-Minuten-Schätzung.
Die gespeicherte Scan-Grenze bleibt immer die Höhe (BIP158_START_HEIGHT).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.xpub_cache import (
    BITCOIN_BLOCK_INTERVAL_SECONDS,
    BITCOIN_GENESIS_TIMESTAMP,
    IMMUTABLE_CACHE_DIR,
    block_time_for_height,
    hoehe_zur_blockzeit,
)

UTC = timezone.utc

def parse_utc_datum(date_str: str) -> int:
    """UTC-Tagesbeginn eines Datums. ValueError bei unlesbarem Text."""
    from core.fulcrum_history import _parse_utc_date_timestamp

    return _parse_utc_date_timestamp(date_str)


def iso_datum(ts: int) -> str:
    """YYYY-MM-DD in UTC."""
    return datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%d")


def normalisiere_iso_datum(date_str: str) -> str:
    """Eingabe (DE/ISO) als YYYY-MM-DD."""
    return iso_datum(parse_utc_datum(date_str))


def schaetze_hoehe_aus_datum(date_str: str) -> int:
    """10-Minuten-Blöcke ab Genesis, ohne Netz."""
    from core.utxo_report import estimate_block_height_for_date

    return int(estimate_block_height_for_date(date_str))


def schaetze_datum_aus_hoehe(hoehe: int) -> str:
    """Umkehr der 10-Minuten-Schätzung."""
    h = max(0, int(hoehe))
    ts = BITCOIN_GENESIS_TIMESTAMP + h * BITCOIN_BLOCK_INTERVAL_SECONDS
    return iso_datum(ts)


def datum_aus_lokaler_hoehe(
    hoehe: int,
    cache_root: Path | None = None,
) -> str | None:
    """Datum aus ``p2p_headers.bin`` / Header-JSON. None wenn die Höhe fehlt."""
    h = int(hoehe)
    if h <= 0:
        return iso_datum(BITCOIN_GENESIS_TIMESTAMP)
    ts = block_time_for_height(h, cache_root)
    if ts is None:
        return None
    return iso_datum(ts)


def hoehe_aus_lokalem_datum(
    date_str: str,
    cache_root: Path | None = None,
) -> int | None:
    """Erste lokale Höhe am oder nach dem Datum. None außerhalb der Header-Datei."""
    ts = parse_utc_datum(date_str)
    if ts <= BITCOIN_GENESIS_TIMESTAMP:
        return 0
    return hoehe_zur_blockzeit(ts, cache_root)


def _explorer_get(
    explorer_url: str,
    pfade: list[str],
    *,
    values: dict[str, str] | None = None,
) -> bytes | None:
    from core.config import mempool_api_get

    return mempool_api_get(explorer_url, pfade, values=values)


def _json_obj(roh: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(roh.decode("utf-8", errors="replace"))
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _int_feld(obj: dict[str, Any], *namen: str) -> int | None:
    for name in namen:
        wert = obj.get(name)
        if wert is None or wert == "":
            continue
        try:
            return int(wert)
        except (TypeError, ValueError):
            continue
    return None


def explorer_hoehe_aus_datum(
    explorer_url: str,
    date_str: str,
    *,
    values: dict[str, str] | None = None,
) -> int | None:
    """Erste Höhe am oder nach dem Datum über die mempool-API."""
    ts = parse_utc_datum(date_str)
    roh = _explorer_get(
        explorer_url,
        [
            f"mining/blocks/timestamp/{ts}",
            f"v1/mining/blocks/timestamp/{ts}",
        ],
        values=values,
    )
    if not roh:
        return None
    obj = _json_obj(roh)
    if not obj:
        return None
    hoehe = _int_feld(obj, "height")
    if hoehe is None:
        return None
    block_ts = _zeit_aus_explorer_objekt(obj)
    if block_ts is not None and block_ts < ts:
        hoehe += 1
    return max(0, hoehe)


def explorer_datum_aus_hoehe(
    explorer_url: str,
    hoehe: int,
    *,
    values: dict[str, str] | None = None,
) -> str | None:
    """Kalendertag des Blocks über Esplora ``block-height`` + ``block``."""
    h = int(hoehe)
    if h <= 0:
        return iso_datum(BITCOIN_GENESIS_TIMESTAMP)
    roh_hash = _explorer_get(
        explorer_url,
        [f"block-height/{h}"],
        values=values,
    )
    if not roh_hash:
        return None
    blockhash = roh_hash.decode("utf-8", errors="replace").strip().strip('"')
    if len(blockhash) != 64:
        obj = _json_obj(roh_hash)
        if obj:
            blockhash = str(obj.get("hash") or obj.get("id") or "").strip()
    if len(blockhash) != 64:
        return None
    roh_block = _explorer_get(
        explorer_url,
        [f"block/{blockhash}", f"v1/block/{blockhash}"],
        values=values,
    )
    if not roh_block:
        return None
    obj = _json_obj(roh_block)
    if not obj:
        return None
    ts = _zeit_aus_explorer_objekt(obj)
    if ts is None:
        return None
    return iso_datum(ts)


def _zeit_aus_explorer_objekt(obj: dict[str, Any]) -> int | None:
    wert = obj.get("timestamp")
    if wert is None:
        wert = obj.get("time")
    if wert is None:
        return None
    if isinstance(wert, (int, float)):
        ts = int(wert)
        return ts if ts > 0 else None
    text = str(wert).strip()
    if not text:
        return None
    if text.isdigit():
        ts = int(text)
        return ts if ts > 0 else None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp())
    except ValueError:
        return None


def rechne_scan_zeit(
    *,
    hoehe: int | None = None,
    datum: str | None = None,
    cache_root: Path | None = None,
    explorer_url: str | None = None,
    values: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Eine Richtung: Höhe oder Datum.

    Rückgabe: ``height``, ``date`` (YYYY-MM-DD), ``source``
    (``headers`` / ``explorer`` / ``estimate``).
    """
    root = Path(cache_root) if cache_root else IMMUTABLE_CACHE_DIR
    explorer = str(explorer_url or "").strip() or None

    if datum is not None and str(datum).strip():
        iso = normalisiere_iso_datum(str(datum))
        lokal = hoehe_aus_lokalem_datum(iso, root)
        if lokal is not None:
            return {"height": int(lokal), "date": iso, "source": "headers"}
        if explorer:
            expl = explorer_hoehe_aus_datum(explorer, iso, values=values)
            if expl is not None:
                return {"height": int(expl), "date": iso, "source": "explorer"}
        return {
            "height": schaetze_hoehe_aus_datum(iso),
            "date": iso,
            "source": "estimate",
        }

    if hoehe is None:
        raise ValueError("Höhe oder Datum angeben.")
    h = int(hoehe)
    if h < 0:
        raise ValueError("Höhe muss ≥ 0 sein.")
    lokal = datum_aus_lokaler_hoehe(h, root)
    if lokal is not None:
        return {"height": h, "date": lokal, "source": "headers"}
    if explorer:
        expl = explorer_datum_aus_hoehe(explorer, h, values=values)
        if expl is not None:
            return {"height": h, "date": expl, "source": "explorer"}
    return {
        "height": h,
        "date": schaetze_datum_aus_hoehe(h),
        "source": "estimate",
    }
