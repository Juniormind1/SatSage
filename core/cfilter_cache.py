"""
BIP-158 basic-filter Disk-Cache unter immutable_cache/cfilter/.

Key: Höhe + Blockhash (Reorg-sicher). Blob = raw cfilter payload (N + GCS).
"""
from __future__ import annotations

from pathlib import Path

_CFILTER_DIR = "cfilter"


def cfilter_cache_dir(immutable_dir: Path | str | None) -> Path | None:
    if immutable_dir is None:
        return None
    return Path(immutable_dir) / _CFILTER_DIR


def cfilter_cache_pfad(
    immutable_dir: Path | str | None,
    height: int,
    block_hash: bytes | str,
) -> Path | None:
    basis = cfilter_cache_dir(immutable_dir)
    if basis is None:
        return None
    if isinstance(block_hash, (bytes, bytearray)):
        hx = bytes(block_hash).hex()
    else:
        hx = str(block_hash).strip().lower()
        if hx.startswith("0x"):
            hx = hx[2:]
    if len(hx) != 64:
        return None
    return basis / f"{int(height)}_{hx}.bin"


def lade_cfilter_blob(
    immutable_dir: Path | str | None,
    height: int,
    block_hash: bytes | str,
) -> bytes | None:
    pfad = cfilter_cache_pfad(immutable_dir, height, block_hash)
    if pfad is None or not pfad.is_file():
        return None
    try:
        data = pfad.read_bytes()
    except OSError:
        return None
    return data if data else None


def speichere_cfilter_blob(
    immutable_dir: Path | str | None,
    height: int,
    block_hash: bytes | str,
    blob: bytes,
) -> bool:
    if not blob:
        return False
    pfad = cfilter_cache_pfad(immutable_dir, height, block_hash)
    if pfad is None:
        return False
    try:
        from main import cache_disk_write_allowed
    except Exception:
        cache_disk_write_allowed = None  # type: ignore
    if cache_disk_write_allowed is not None:
        try:
            if not cache_disk_write_allowed(pfad.parent):
                return False
        except Exception:
            return False
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        tmp = pfad.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(pfad)
    except OSError:
        return False
    return True
