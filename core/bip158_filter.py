"""BIP-158 basic-filter primitives (SipHash/Golomb) and scan dataclasses."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

try:
    from chiabip158 import PyBIP158
except ImportError:  # pragma: no cover - optional at import time
    PyBIP158 = None  # type: ignore[misc, assignment]


BASIC_FILTER_M = 784_931
BASIC_FILTER_P = 19

ProgressCallback = Callable[["ScanProgress"], None]


# ---------------------------------------------------------------------------
# BIP-158 primitives (Bitcoin Core compatible)
# ---------------------------------------------------------------------------


def _rotl64(value: int, bits: int) -> int:
    mask = (1 << 64) - 1
    return ((value >> (64 - bits)) | ((value & ((1 << (64 - bits)) - 1)) << bits)) & mask


def _siphash_round(v0: int, v1: int, v2: int, v3: int) -> tuple[int, int, int, int]:
    mask = (1 << 64) - 1
    v0 = (v0 + v1) & mask
    v1 = _rotl64(v1, 13)
    v1 ^= v0
    v0 = _rotl64(v0, 32)
    v2 = (v2 + v3) & mask
    v3 = _rotl64(v3, 16)
    v3 ^= v2
    v0 = (v0 + v3) & mask
    v3 = _rotl64(v3, 21)
    v3 ^= v0
    v2 = (v2 + v1) & mask
    v1 = _rotl64(v1, 17)
    v1 ^= v2
    v2 = _rotl64(v2, 32)
    return v0, v1, v2, v3


def siphash(k0: int, k1: int, data: bytes) -> int:
    """SipHash-2-4 (Bitcoin Core compatible)."""
    mask = (1 << 64) - 1
    v0 = 0x736F6D6570736575 ^ k0
    v1 = 0x646F72616E646F6D ^ k1
    v2 = 0x6C7967656E657261 ^ k0
    v3 = 0x7465646279746573 ^ k1
    count = 0
    tail = 0
    for byte in data:
        tail |= byte << (8 * (count % 8))
        count = (count + 1) & 0xFF
        if (count & 7) == 0:
            v3 ^= tail
            v0, v1, v2, v3 = _siphash_round(v0, v1, v2, v3)
            v0, v1, v2, v3 = _siphash_round(v0, v1, v2, v3)
            v0 ^= tail
            tail = 0
    tail |= count << 56
    v3 ^= tail
    v0, v1, v2, v3 = _siphash_round(v0, v1, v2, v3)
    v0, v1, v2, v3 = _siphash_round(v0, v1, v2, v3)
    v0 ^= tail
    v2 ^= 0xFF
    for _ in range(4):
        v0, v1, v2, v3 = _siphash_round(v0, v1, v2, v3)
    return (v0 ^ v1 ^ v2 ^ v3) & mask


def _sip_keys_from_block_hash(block_hash_hex: str) -> tuple[int, int]:
    block_hash_bytes = bytes.fromhex(block_hash_hex)[::-1]
    k0 = int.from_bytes(block_hash_bytes[0:8], "little")
    k1 = int.from_bytes(block_hash_bytes[8:16], "little")
    return k0, k1


def _read_compact_size(data: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(data):
        raise ValueError("compact size read past end")
    first = data[offset]
    offset += 1
    if first < 253:
        return first, offset
    if first == 253:
        return struct.unpack_from("<H", data, offset)[0], offset + 2
    if first == 254:
        return struct.unpack_from("<I", data, offset)[0], offset + 4
    return struct.unpack_from("<Q", data, offset)[0], offset + 8


class _BitStreamReader:
    """Minimal big-endian bit reader for Golomb-Rice decoding."""

    def __init__(self, data: bytes):
        self._data = data
        self._byte = 0
        self._bit = 0

    def read_bit(self) -> int:
        if self._bit == 0:
            if self._byte >= len(self._data):
                raise ValueError("bitstream exhausted")
            self._current = self._data[self._byte]
            self._byte += 1
            self._bit = 8
        self._bit -= 1
        return (self._current >> self._bit) & 1

    def read_bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            value = (value << 1) | self.read_bit()
        return value


def _golomb_rice_decode(reader: _BitStreamReader, p: int) -> int:
    quotient = 0
    while reader.read_bit() == 1:
        quotient += 1
    remainder = reader.read_bits(p)
    return (quotient << p) + remainder


class _BitStreamWriter:
    """Append-only bit writer for Golomb-Rice encoding."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._current = 0
        self._bit_count = 0

    def write_bit(self, value: int) -> None:
        self._current = (self._current << 1) | (value & 1)
        self._bit_count += 1
        if self._bit_count == 8:
            self._buffer.append(self._current)
            self._current = 0
            self._bit_count = 0

    def write_bits(self, value: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            self.write_bit((value >> shift) & 1)

    def flush(self) -> bytes:
        if self._bit_count:
            self._current <<= 8 - self._bit_count
            self._buffer.append(self._current)
            self._current = 0
            self._bit_count = 0
        return bytes(self._buffer)


def _write_compact_size(value: int) -> bytes:
    if value < 253:
        return bytes([value])
    if value <= 0xFFFF:
        return bytes([253]) + struct.pack("<H", value)
    if value <= 0xFFFFFFFF:
        return bytes([254]) + struct.pack("<I", value)
    return bytes([255]) + struct.pack("<Q", value)


def _golomb_rice_encode(writer: _BitStreamWriter, p: int, delta: int) -> None:
    quotient = delta >> p
    remainder = delta & ((1 << p) - 1)
    for _ in range(quotient):
        writer.write_bit(1)
    writer.write_bit(0)
    writer.write_bits(remainder, p)


def _encode_core_basic_filter(elements: Sequence[bytes], block_hash_hex: str) -> bytes:
    """Build a Bitcoin Core ``basic`` filter blob (for tests and tooling)."""
    k0, k1 = _sip_keys_from_block_hash(block_hash_hex)
    n = len(elements)
    f_range = n * BASIC_FILTER_M
    hashed = sorted(_hash_to_range(element, k0, k1, f_range) for element in elements)
    payload = bytearray(_write_compact_size(n))
    if not hashed:
        return bytes(payload)
    writer = _BitStreamWriter()
    last = 0
    for value in hashed:
        _golomb_rice_encode(writer, BASIC_FILTER_P, value - last)
        last = value
    writer.flush()
    payload.extend(writer._buffer)
    return bytes(payload)


def _hash_to_range(element: bytes, k0: int, k1: int, f_range: int) -> int:
    digest = siphash(k0, k1, element)
    return (digest * f_range) >> 64


class _CoreBasicFilterMatcher:
    """
    Matches scriptPubKeys against a Bitcoin Core ``basic`` block filter.

    Implements the same ranged-hash + Golomb-Rice set lookup as Bitcoin Core.
    """

    def __init__(self, encoded_filter: bytes, block_hash_hex: str):
        self._encoded = encoded_filter
        self._block_hash = block_hash_hex
        self._k0, self._k1 = _sip_keys_from_block_hash(block_hash_hex)
        self._n, self._f_range = self._decode_params()

    def _decode_params(self) -> tuple[int, int]:
        n, offset = _read_compact_size(self._encoded, 0)
        if n > 0xFFFFFFFF:
            raise ValueError("filter element count exceeds uint32")
        return int(n), int(n) * BASIC_FILTER_M

    @property
    def element_count(self) -> int:
        return self._n

    def match_any(self, elements: Iterable[bytes]) -> bool:
        """Return True if any *elements* (raw scriptPubKey bytes) may be in the filter."""
        queries = sorted(
            {_hash_to_range(element, self._k0, self._k1, self._f_range) for element in elements}
        )
        if not queries:
            return False
        return self._match_internal(queries)

    def _match_internal(self, queries: list[int]) -> bool:
        n, offset = _read_compact_size(self._encoded, 0)
        if n != self._n:
            raise ValueError("filter N mismatch")
        reader = _BitStreamReader(self._encoded[offset:])
        value = 0
        query_index = 0
        for _ in range(n):
            delta = _golomb_rice_decode(reader, BASIC_FILTER_P)
            value += delta
            while query_index < len(queries):
                if queries[query_index] == value:
                    return True
                if queries[query_index] > value:
                    break
                query_index += 1
        return False


def _match_with_chiabip158(encoded_filter: bytes, elements: list[bytes]) -> bool:
    """
    Match using chiabip158.PyBIP158 — only valid for filters encoded with the
    binding's default SipHash keys (k0=k1=0).  Not used for Bitcoin Core filters.
    """
    if PyBIP158 is None:
        raise RuntimeError("chiabip158 is not installed")
    # chiabip158: PyBIP158(encoded_bytes).MatchAny(scriptPubKey_bytes)
    matcher = PyBIP158(list(encoded_filter))
    payload = [bytearray(element) for element in elements]
    return bool(matcher.MatchAny(payload))


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScanProgress:
    """Progress event emitted during a height scan."""

    height: int
    tip_height: int
    blocks_checked: int
    matches_found: int
    phase: str
    utxo_id: str | None = None
    total_blocks: int = 0


@dataclass(frozen=True)
class MatchedOutput:
    """A vout that pays one of the watched scriptPubKeys."""

    txid: str
    vout: int
    value_sats: int
    address: str | None
    script_pubkey_hex: str
    block_height: int
    block_hash: str


@dataclass(frozen=True)
class MatchedTransaction:
    """Full transaction data for a positive filter match."""

    txid: str
    block_height: int
    block_hash: str
    raw_tx: dict[str, Any]
    matched_outputs: tuple[MatchedOutput, ...] = ()
    matched_inputs: tuple[dict[str, Any], ...] = ()


@dataclass
class ScanResult:
    """Aggregated output of a BIP-158 scan."""

    start_height: int
    stop_height: int
    matched_blocks: list[str] = field(default_factory=list)
    transactions: list[MatchedTransaction] = field(default_factory=list)
    outputs: list[MatchedOutput] = field(default_factory=list)
    false_positive_blocks: list[str] = field(default_factory=list)
    verlauf: list[dict[str, Any]] = field(default_factory=list)

    @property
    def utxos(self) -> list[MatchedOutput]:
        """Alias: matched outputs (unspent status requires a follow-up ``gettxout``)."""
        return self.outputs
