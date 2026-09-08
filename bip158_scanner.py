#!/usr/bin/env python3
"""
BIP-158-Scanner über Bitcoin-P2P (BIP 157 Compact Filter).

Filter und Blöcke kommen von Peers mit NODE_COMPACT_FILTERS, nicht von
Bitcoin-Core-RPC. Abgleich lokal. Ungenutzte Keys nur gegen das Turbo-Fenster
(Wasabi-TurboSync), damit False-Positive-Downloads in der Historie entfallen.

chiabip158 nur für Self-Tests. Produktions-Filter: _CoreBasicFilterMatcher.
"""

from __future__ import annotations

import argparse
import io
import logging
import queue
import struct
import sys
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# Callable used in _encoders_for_xpub return type below

from embit import script
from embit.bip32 import HDKey
from embit.script import address_to_scriptpubkey

try:
    from chiabip158 import PyBIP158
except ImportError:  # pragma: no cover - optional at import time
    PyBIP158 = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

BASIC_FILTER_M = 784_931
BASIC_FILTER_P = 19
DEFAULT_GAP_LIMIT = 20
DEFAULT_MAX_INDEX = 500
DEFAULT_MAX_ADDRESSES = 50
#: ~14 Tage. Ungenutzte Keys nur in diesem Fenster — Historie wäre nur FP.
TURBO_WINDOW = 2_016
ENV_FILE = Path(__file__).resolve().parent / ".env"

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


# ---------------------------------------------------------------------------
# XPUB derivation (self-contained, embit only)
# ---------------------------------------------------------------------------


def _encoders_for_xpub(xpub: str, script_type: str | None = None) -> list[Callable]:
    """
    Delegiert an main._encoders_for_xpub, damit der konfigurierte Skripttyp
    auch beim BIP-158-Scan gilt. Der Import erfolgt verzögert; main lädt dieses
    Modul seinerseits erst zur Laufzeit, ein Zirkelbezug entsteht nicht.

    Der Fallback hält das Modul eigenständig lauffähig — dann allerdings ohne
    Skripttyp-Konfiguration, weshalb 'xpub' dort alle Typen probiert.
    """
    try:
        import main

        return main._encoders_for_xpub(xpub, script_type)
    except Exception:
        pass

    pubkey = lambda pk: script.p2pkh(pk)
    nested = lambda pk: script.p2sh(script.p2wpkh(pk))
    segwit = lambda pk: script.p2wpkh(pk)
    taproot = lambda pk: script.p2tr(pk)
    mapping = {
        "ypub": [nested],
        "zpub": [segwit],
        "upub": [nested],
        "vpub": [segwit],
    }
    return mapping.get(xpub[:4].lower(), [pubkey, nested, segwit, taproot])


def derive_script_pubkeys_from_xpub(
    xpub: str,
    *,
    max_index: int = DEFAULT_MAX_INDEX,
    include_change: bool = True,
) -> dict[bytes, str | None]:
    """
    Derive receive (+ optional change) scriptPubKeys from an XPUB
    **or Output-Deskriptor** (Multisig ``wsh(sortedmulti…)`` u. a.).

    Returns ``script_pubkey_bytes -> address`` (address may be None if encoding fails).
    """
    # Multisig/Deskriptor: embit HDKey versteht den String nicht — main.derive_*.
    try:
        import main as main_mod

        if main_mod.ist_deskriptor(xpub):
            # max_index ≈ pro Chain; Deskriptor-Pfad teilt max_addresses auf Zweige.
            zweige = 2 if include_change else 1
            max_addr = max(2, int(max_index) * zweige)
            addrs = main_mod.derive_addresses(
                xpub, max_addresses=max_addr, start_index=0,
            )
            result: dict[bytes, str | None] = {}
            for addr in addrs or []:
                if not addr:
                    continue
                try:
                    spk = bytes(address_to_scriptpubkey(addr).data)
                except Exception:
                    continue
                result[spk] = addr
            if not result:
                raise ValueError(
                    f"Deskriptor liefert keine Adressen: {xpub[:40]}…"
                )
            return result
    except ValueError:
        raise
    except Exception:
        pass

    try:
        hd = HDKey.from_string(xpub)
    except Exception as exc:
        raise ValueError(f"invalid xpub: {exc}") from exc

    result = {}
    chains = (0, 1) if include_change else (0,)
    for encoder in _encoders_for_xpub(xpub):
        for change in chains:
            for index in range(max_index):
                try:
                    child = hd.derive([change, index])
                    sc = encoder(child.key)
                    spk = bytes(sc.data)
                    try:
                        addr = sc.address()
                    except Exception:
                        addr = None
                    result[spk] = addr
                except Exception:
                    break
    return result


def addresses_to_script_pubkeys(addresses: Sequence[str]) -> dict[bytes, str]:
    """Convert base58/bech32 addresses to scriptPubKey bytes."""
    mapping: dict[bytes, str] = {}
    for address in addresses:
        spk = bytes(address_to_scriptpubkey(address).data)
        mapping[spk] = address
    return mapping


# ---------------------------------------------------------------------------
# TurboSync (Wasabi): ungenutzte Keys nicht durch die Historie jagen
# ---------------------------------------------------------------------------


def plane_filter_passes(
    start_height: int,
    tip: int,
    all_scripts: set[bytes],
    used_scripts: set[bytes],
    *,
    turbo_window: int = TURBO_WINDOW,
) -> list[tuple[str, int, int, frozenset[bytes]]]:
    """
    Chronologische Filter-Pässe (niedrig → hoch), damit das UTXO-Set stimmt.

    Erstscan (keine used): ein Pass, alle Keys, start…tip.
    Danach: Historie nur used Keys; Turbo-Fenster alle Keys (neue Empfänge
    auf frischen Adressen). Ungenutzte Lookahead-Keys erzeugen in alten
    Filtern nur False Positives.
    """
    if tip < start_height:
        return []
    scripts_all = frozenset(all_scripts)
    if not used_scripts:
        return [("historie", start_height, tip, scripts_all)]
    turbo_from = max(start_height, tip - turbo_window + 1)
    passe: list[tuple[str, int, int, frozenset[bytes]]] = []
    if start_height < turbo_from:
        passe.append(
            ("historie", start_height, turbo_from - 1, frozenset(used_scripts))
        )
    passe.append(("turbo", turbo_from, tip, scripts_all))
    return passe


def _cfilter_chunks(
    von: int, bis: int, hash_at,
    *,
    schritt: int,
) -> list[tuple[int, int, bytes]]:
    chunks: list[tuple[int, int, bytes]] = []
    hoehe = von
    while hoehe <= bis:
        ende = min(hoehe + schritt - 1, bis)
        chunks.append((hoehe, ende, hash_at(ende)))
        hoehe = ende + 1
    return chunks


def _filter_umfang(passe) -> int:
    """Wie viele Filter-Höhen die Pässe zusammen ablaufen."""
    return sum(max(0, bis - von + 1) for _name, von, bis, _s in passe)


def _filter_prozent_text(geprueft: int, gesamt: int) -> str:
    """„12.000/481.375 (2,5 %)“ — leer, solange die Gesamtzahl fehlt."""
    if gesamt <= 0:
        return ""
    geprueft = max(0, int(geprueft))
    zahlen = f"{geprueft:,}/{gesamt:,}".replace(",", ".")
    if geprueft >= gesamt:
        return f"{zahlen} (100 %)"
    pct = 100.0 * geprueft / gesamt
    if pct < 10:
        pct_s = f"{pct:.1f} %".replace(".", ",")
    else:
        pct_s = f"{int(pct)} %"
    return f"{zahlen} ({pct_s})"


def _tick_filter_stand(
    von: int, bis: int, gezaehlt: list[int], gesamt: int,
    *,
    sperre: threading.Lock | None = None,
) -> None:
    n = max(0, bis - von + 1)
    if sperre:
        with sperre:
            gezaehlt[0] += n
            bisher = gezaehlt[0]
    else:
        gezaehlt[0] += n
        bisher = gezaehlt[0]
    from display import melde_zwischenstand

    text = f"Filter Block {von:,}–{bis:,}".replace(",", ".")
    pct = _filter_prozent_text(bisher, gesamt)
    if pct:
        text = f"{text} · {pct}"
    melde_zwischenstand(text, log=False)


def _kuerze_adresse(addr: str | None) -> str:
    text = addr or "?"
    if len(text) <= 16:
        return text
    return f"{text[:8]}…{text[-4:]}"


def _filter_treffer_praefix(hoehe: int) -> str:
    """Anfang der Log-Zeile — gleich für „hole Block“ und das Ergebnis."""
    return f"Filter-Treffer Block {hoehe:,}".replace(",", ".")


def _beschreibe_block_treffer(
    hoehe: int,
    neu: dict,
    spent_ours: set[str],
) -> str:
    """
    Eine Zeile: was der geholte Block für uns enthielt.

    Dieselbe Zeile wie „Filter-Treffer … — hole Block…“, nur der Teil
    nach dem Gedankenstrich wechselt (False Positive oder Fund).
    """
    from display import format_sats

    label = _filter_treffer_praefix(hoehe)
    teile: list[str] = []
    if neu:
        sats = sum(int(o.value_sats) for o in neu.values())
        gesehen: list[str] = []
        for o in neu.values():
            a = _kuerze_adresse(o.address)
            if a not in gesehen:
                gesehen.append(a)
        wo = ", ".join(gesehen[:3])
        if len(gesehen) > 3:
            wo += f" (+{len(gesehen) - 3})"
        wort = "UTXO" if len(neu) == 1 else "UTXOs"
        teile.append(f"+{len(neu)} {wort}, {format_sats(sats)} auf {wo}")
    if spent_ours:
        wort = "Output" if len(spent_ours) == 1 else "Outputs"
        teile.append(f"{len(spent_ours)} {wort} ausgegeben")
    if not teile:
        return f"{label} — False Positive"
    return f"{label} — {'; '.join(teile)}"


def _lade_cfilter_chunk(
    peer, von: int, bis: int, stop_hash: bytes, scripts, on_log=None,
) -> list:
    from core.p2p import hash_to_hex
    from display import melde_zwischenstand

    expect = bis - von + 1
    melde_zwischenstand(
        f"Filter Block {von:,}–{bis:,}…".replace(",", "."),
        log=False,
    )
    filter_liste = peer.fetch_cfilters(von, stop_hash, expect=expect)
    if len(filter_liste) != expect:
        raise ConnectionError(
            f"cfilter: {len(filter_liste)} statt {expect} ab Höhe {von}"
        )
    zeilen = []
    for offset, (block_hash, blob) in enumerate(filter_liste):
        h = von + offset
        display = hash_to_hex(block_hash)
        matcher = _CoreBasicFilterMatcher(blob, display)
        roh = None
        if matcher.match_any(scripts):
            if on_log:
                on_log(f"{_filter_treffer_praefix(h)} — hole Block…")
            roh = peer.fetch_block(block_hash)
        zeilen.append((h, block_hash, blob, roh))
    return zeilen


def verteile_cfilter_chunks(
    peers,
    chunks: list[tuple[int, int, bytes]],
    scripts,
    *,
    on_log=None,
    gesamt: int = 0,
    gezaehlt: list[int] | None = None,
    tor_proxy: tuple[str, int] | None = None,
):
    """
    Holt Filter-Chunks parallel (ein Auftrag je Peer).

    Liefert Chunks als Iterator in Höhenreihenfolge — der Aufrufer kann
    UTXOs auswerten, während weitere Filter noch laden.
    *gesamt* / *gezaehlt* zählen Filter-Höhen für die Prozentanzeige.
    """
    if not peers:
        raise RuntimeError("keine Compact-Filter-Peers")
    if not chunks:
        return
        yield  # macht die Funktion zum Generator
    stand = gezaehlt if gezaehlt is not None else [0]
    if len(peers) == 1:
        for von, bis, stop in chunks:
            zeilen = _lade_cfilter_chunk(
                peers[0], von, bis, stop, scripts, on_log=on_log,
            )
            _tick_filter_stand(von, bis, stand, gesamt)
            yield zeilen
        return

    auftraege: queue.Queue = queue.Queue()
    for index, chunk in enumerate(chunks):
        auftraege.put((index, chunk, 0))
    fertig: dict[int, object] = {}
    sperre = threading.Lock()
    wach = threading.Condition(sperre)
    lebendig = len(peers)
    max_versuche = 5
    stand_lock = threading.Lock()
    erledigt = [0]

    def arbeit(peer) -> None:
        nonlocal lebendig
        try:
            while True:
                try:
                    index, chunk, versuche = auftraege.get(timeout=0.4)
                except queue.Empty:
                    with sperre:
                        if erledigt[0] >= len(chunks):
                            return
                    continue
                von, bis, stop = chunk
                try:
                    zeilen = _lade_cfilter_chunk(
                        peer, von, bis, stop, scripts, on_log=on_log,
                    )
                except Exception as exc:
                    try:
                        peer.close()
                    except Exception:
                        pass
                    if versuche + 1 < max_versuche:
                        if on_log:
                            on_log(
                                f"Chunk {von:,}–{bis:,} fehlgeschlagen "
                                f"({type(exc).__name__}) — "
                                f"Versuch {versuche + 2}/{max_versuche}"
                                .replace(",", ".")
                            )
                        auftraege.put((index, chunk, versuche + 1))
                        # Defekten Peer ersetzen; sonst Worker beenden,
                        # damit kein toter Socket die Queue leersaugt.
                        try:
                            from core.p2p import verbinde_compact_filter_peers

                            frisch = verbinde_compact_filter_peers(
                                limit=1,
                                tor_proxy=tor_proxy,
                                ruhig=True,
                                versuche=12,
                                dns_fallback=True,
                            )
                            if frisch:
                                peer = frisch[0]
                                continue
                        except Exception:
                            pass
                        return
                    with wach:
                        fertig[index] = exc
                        erledigt[0] += 1
                        wach.notify_all()
                    return
                with wach:
                    fertig[index] = zeilen
                    erledigt[0] += 1
                    wach.notify_all()
                _tick_filter_stand(
                    von, bis, stand, gesamt, sperre=stand_lock,
                )
        finally:
            with wach:
                lebendig -= 1
                wach.notify_all()

    if on_log:
        on_log(f"Filter über {len(peers)} Peers parallel…")
    threads = [
        threading.Thread(target=arbeit, args=(peer,), daemon=True)
        for peer in peers
    ]
    for t in threads:
        t.start()

    def _neuer_worker() -> bool:
        nonlocal lebendig
        try:
            from core.p2p import verbinde_compact_filter_peers

            frisch = verbinde_compact_filter_peers(
                limit=1,
                tor_proxy=tor_proxy,
                ruhig=True,
                versuche=12,
                dns_fallback=True,
            )
        except Exception:
            return False
        if not frisch:
            return False
        with wach:
            lebendig += 1
        t = threading.Thread(target=arbeit, args=(frisch[0],), daemon=True)
        threads.append(t)
        t.start()
        return True

    try:
        # Chunkweise in Höhenreihenfolge ausliefern — UTXO-Auswertung
        # läuft parallel zum weiteren Filter-Download.
        for index in range(len(chunks)):
            with wach:
                while index not in fertig:
                    if lebendig <= 0 and index not in fertig:
                        break
                    wach.wait(timeout=1.0)
                if index not in fertig:
                    # Alle Worker tot — einen neuen Peer holen und warten
                    if not _neuer_worker():
                        raise RuntimeError("alle Compact-Filter-Peers ausgefallen")
                    while index not in fertig:
                        if lebendig <= 0 and index not in fertig:
                            raise RuntimeError(
                                "alle Compact-Filter-Peers ausgefallen"
                            )
                        wach.wait(timeout=1.0)
                    if index not in fertig:
                        raise RuntimeError("alle Compact-Filter-Peers ausgefallen")
                wert = fertig.pop(index)
            if isinstance(wert, BaseException):
                raise wert
            yield wert
    finally:
        with sperre:
            erledigt[0] = max(erledigt[0], len(chunks))
        for t in threads:
            t.join(timeout=2.0)


def parse_raw_block(raw: bytes):
    """Header + Transaktionen aus einem P2P-``block``-Payload."""
    from embit import compact as embit_compact
    from embit.transaction import Transaction

    if len(raw) < 80:
        raise ValueError("Block zu kurz")
    header = raw[:80]
    stream = io.BytesIO(raw[80:])
    anzahl = embit_compact.read_from(stream)
    txs = [Transaction.read_from(stream) for _ in range(anzahl)]
    return header, txs


def _header_unixzeit(header: bytes) -> int:
    """nTime des Block-Headers (Unix, Offset 68)."""
    if len(header) < 72:
        return 0
    return int.from_bytes(header[68:72], "little")


def _verlauf_eintrag(output: MatchedOutput, block_time: int) -> dict[str, Any]:
    """Ein Verlaufs-Datensatz wie Fulcrum: Empfang, optional später spent."""
    return {
        "txid": output.txid,
        "vout": int(output.vout),
        "value": int(output.value_sats),
        "address": output.address,
        "status": {
            "confirmed": output.block_height > 0,
            "block_height": output.block_height,
            "block_time": int(block_time) if block_time else None,
        },
        "spent": False,
        "spent_txid": None,
    }


def _uebernehme_block_verlauf(
    verlauf: dict[str, dict[str, Any]],
    neu: dict[str, MatchedOutput],
    spent_ours: dict[str, str],
    *,
    hoehe: int,
    block_time: int,
) -> None:
    """Schreibt Empfänge und Abgänge dieses Blocks in den Verlauf."""
    for key, output in neu.items():
        verlauf.setdefault(key, _verlauf_eintrag(output, block_time))
    for key, spend_txid in spent_ours.items():
        eintrag = verlauf.get(key)
        if eintrag is None:
            continue
        eintrag["spent"] = True
        eintrag["spent_txid"] = spend_txid
        eintrag["spent_height"] = hoehe
        if block_time:
            eintrag["spent_time_ts"] = block_time


def extract_from_parsed_block(
    header: bytes,
    txs,
    watched: dict[bytes, str | None],
    height: int,
) -> tuple[list[MatchedTransaction], dict[str, MatchedOutput], dict[str, str]]:
    """
    Liefert Treffer, neue Outputs (outpoint → MatchedOutput) und verbrauchte
    Outpoints (txid:vout → ausgebende TxID).
    """
    from core.p2p import hash_to_hex, header_hash

    block_hash = hash_to_hex(header_hash(header))
    matches: list[MatchedTransaction] = []
    neu: dict[str, MatchedOutput] = {}
    spent_by: dict[str, str] = {}
    null_txid = b"\x00" * 32

    for tx in txs:
        txid = tx.txid().hex()
        matched_outputs: list[MatchedOutput] = []
        matched_inputs: list[dict[str, Any]] = []

        for vin in tx.vin:
            prev_txid = bytes(vin.txid)
            if prev_txid == null_txid:
                continue
            prev = f"{prev_txid.hex()}:{int(vin.vout)}"
            spent_by[prev] = txid
            matched_inputs.append({"txid": prev_txid.hex(), "vout": int(vin.vout)})

        for n, vout in enumerate(tx.vout):
            spk = bytes(vout.script_pubkey.data)
            if spk not in watched:
                continue
            output = MatchedOutput(
                txid=txid,
                vout=int(n),
                value_sats=int(vout.value),
                address=watched.get(spk),
                script_pubkey_hex=spk.hex(),
                block_height=height,
                block_hash=block_hash,
            )
            matched_outputs.append(output)
            neu[f"{txid}:{n}"] = output

        if matched_outputs:
            matches.append(
                MatchedTransaction(
                    txid=txid,
                    block_height=height,
                    block_hash=block_hash,
                    raw_tx={"txid": txid},
                    matched_outputs=tuple(matched_outputs),
                    matched_inputs=tuple(matched_inputs),
                )
            )
    return matches, neu, spent_by


# ---------------------------------------------------------------------------
# Scanner (P2P)
# ---------------------------------------------------------------------------

#: Live-Peers offener BIP-158-Scanner (Tip-Sync / Filter-Walk) für die UI-Pille.
_LIVE_FILTER_LOCK = threading.Lock()
_LIVE_FILTER_PEERS: dict[int, tuple[str, ...]] = {}


def _peer_host_label(peer) -> str:
    if peer is None:
        return ""
    if isinstance(peer, str):
        return peer.strip()
    if isinstance(peer, (tuple, list)) and len(peer) >= 2:
        return f"{peer[0]}:{peer[1]}"
    host = getattr(peer, "host", None)
    if not host:
        return ""
    port = getattr(peer, "port", 8333)
    return f"{host}:{port}"


def melde_live_filter_peers(owner: object, peers) -> None:
    """Registriert offene Compact-Filter-Verbindungen (für Kopf-Pille)."""
    hosts: list[str] = []
    for peer in peers or []:
        label = _peer_host_label(peer)
        if label and label not in hosts:
            hosts.append(label)
    with _LIVE_FILTER_LOCK:
        if hosts:
            _LIVE_FILTER_PEERS[id(owner)] = tuple(hosts)
        else:
            _LIVE_FILTER_PEERS.pop(id(owner), None)


def clear_live_filter_peers(owner: object) -> None:
    with _LIVE_FILTER_LOCK:
        _LIVE_FILTER_PEERS.pop(id(owner), None)


def live_filter_peer_hosts() -> list[str]:
    """Alle gerade verbundenen Compact-Filter-Peers (dedupliziert)."""
    with _LIVE_FILTER_LOCK:
        gesehen: list[str] = []
        for hosts in _LIVE_FILTER_PEERS.values():
            for h in hosts:
                if h not in gesehen:
                    gesehen.append(h)
        return gesehen


class BIP158Scanner:
    """Filter-Scan über Compact-Filter-Peers, mit TurboSync."""

    def __init__(
        self,
        *,
        tor_proxy: tuple[str, int] | None = None,
        peers: list[tuple[str, int]] | None = None,
        header_path: Path | None = None,
        progress_callback: ProgressCallback | None = None,
        timeout: float = 12.0,
        env: dict[str, str] | None = None,
    ) -> None:
        self._tor_proxy = tor_proxy
        self._peers = list(peers or [])
        self._header_path = header_path
        self._progress_callback = progress_callback
        self._timeout = timeout
        self._env = dict(env or {})
        self._filter_gesamt = 0
        self._peer = None
        self._pool: list = []

    def _log(self, text: str, *, ersetze_praefix: str | None = None) -> None:
        print(text, flush=True)
        try:
            from display import melde_zwischenstand

            melde_zwischenstand(text, ersetze_praefix=ersetze_praefix)
        except Exception:
            pass

    def _log_block_treffer(
        self,
        hoehe: int,
        neu: dict,
        spent_ours: set[str],
    ) -> None:
        """Ergebnis auf die „hole Block…“-Zeile schreiben, nicht dranhängen."""
        text = _beschreibe_block_treffer(hoehe, neu, spent_ours)
        self._log(text, ersetze_praefix=_filter_treffer_praefix(hoehe))

    def _emit(self, height: int, tip: int, checked: int, matches: int, phase: str,
              utxo_id: str | None = None) -> None:
        if not self._progress_callback:
            return
        self._progress_callback(
            ScanProgress(
                height=height,
                tip_height=tip,
                blocks_checked=checked,
                matches_found=matches,
                phase=phase,
                utxo_id=utxo_id,
                total_blocks=self._filter_gesamt,
            )
        )

    def _ensure_peer(self):
        return self._ensure_peers(limit=1)[0]

    def _ensure_peers(self, limit: int | None = None):
        from core.p2p import FILTER_PEERS_MAX, verbinde_compact_filter_peers

        # Über Tor weniger Parallelität — sonst reißen Peers und stecken
        # die Queue mit toten Sockets zu.
        vorgabe = 2 if self._tor_proxy else FILTER_PEERS_MAX
        ziel = vorgabe if limit is None else max(1, min(limit, vorgabe if self._tor_proxy else limit))
        if self._peer is not None and self._peer not in self._pool:
            self._pool.insert(0, self._peer)
        if len(self._pool) >= ziel:
            return self._pool[:ziel]
        exclude = {(p.host, p.port) for p in self._pool}
        frisch = verbinde_compact_filter_peers(
            timeout=self._timeout,
            tor_proxy=self._tor_proxy,
            peers=self._peers or None,
            limit=ziel - len(self._pool),
            exclude=exclude,
            on_log=self._log,
            ruhig=True,
        )
        self._pool.extend(frisch)
        if not self._pool and self._tor_proxy is None:
            from core.p2p import stelle_p2p_tor_bereit

            self._log(
                "Clearnet-P2P ohne Compact-Filter-Peer — versuche über Tor…"
            )
            proxy = stelle_p2p_tor_bereit(self._env, on_log=self._log)
            if proxy:
                self._tor_proxy = proxy
                frisch = verbinde_compact_filter_peers(
                    timeout=self._timeout,
                    tor_proxy=proxy,
                    peers=self._peers or None,
                    limit=ziel,
                    on_log=self._log,
                    ruhig=True,
                )
                self._pool.extend(frisch)
        if not self._pool:
            clear_live_filter_peers(self)
            raise RuntimeError(
                "Kein P2P-Peer mit Compact Filter gefunden "
                "(NODE_COMPACT_FILTERS, peerblockfilters=1)."
            )
        self._peer = self._pool[0]
        melde_live_filter_peers(self, self._pool)
        return self._pool

    def close(self) -> None:
        clear_live_filter_peers(self)
        gesehen = []
        for peer in list(self._pool):
            if peer not in gesehen:
                gesehen.append(peer)
                peer.close()
        if self._peer is not None and self._peer not in gesehen:
            self._peer.close()
        self._pool = []
        self._peer = None

    def get_block_count(self) -> int:
        peer = self._ensure_peer()
        return int(peer.start_height)

    def scan_addresses(
        self,
        addresses: Sequence[str],
        *,
        start_height: int = 0,
        stop_height: int | None = None,
        used_addresses: Sequence[str] = (),
    ) -> ScanResult:
        watched = addresses_to_script_pubkeys(addresses)
        used = set(addresses_to_script_pubkeys(used_addresses).keys())
        return self._scan_script_map(
            watched, start_height, stop_height, used_scripts=used,
        )

    def scan_addresses_sync(self, addresses: Sequence[str], **kwargs) -> ScanResult:
        return self.scan_addresses(addresses, **kwargs)

    def scan_from_xpub(
        self,
        xpub: str,
        *,
        gap_limit: int = DEFAULT_GAP_LIMIT,
        max_index: int = DEFAULT_MAX_INDEX,
        start_height: int = 0,
        stop_height: int | None = None,
        include_change: bool = True,
        used_scripts: set[bytes] | None = None,
        seed_outputs: dict[str, MatchedOutput] | None = None,
        seed_verlauf: dict[str, dict[str, Any]] | None = None,
        on_utxos_update=None,
    ) -> ScanResult:
        index_limit = max(gap_limit, max_index)
        watched = derive_script_pubkeys_from_xpub(
            xpub, max_index=index_limit, include_change=include_change,
        )
        logger.info(
            "P2P-BIP-158: %d Skripte, Höhe %d..%s",
            len(watched),
            start_height,
            stop_height if stop_height is not None else "tip",
        )
        return self._scan_script_map(
            watched, start_height, stop_height,
            used_scripts=used_scripts or set(),
            seed_outputs=seed_outputs,
            seed_verlauf=seed_verlauf,
            on_utxos_update=on_utxos_update,
        )

    def scan_from_xpub_sync(self, xpub: str, **kwargs) -> ScanResult:
        return self.scan_from_xpub(xpub, **kwargs)

    def _scan_script_map(
        self,
        watched: dict[bytes, str | None],
        start_height: int,
        stop_height: int | None,
        *,
        used_scripts: set[bytes],
        seed_outputs: dict[str, MatchedOutput] | None = None,
        seed_verlauf: dict[str, dict[str, Any]] | None = None,
        on_utxos_update=None,
    ) -> ScanResult:
        from core.p2p import GETCFILTERS_MAX, hash_to_hex, hole_header

        if not watched:
            raise ValueError("keine Skripte zum Beobachten")
        chain = None
        tip = 0
        self._log("Synchronisiere Block-Header…")
        letzter_fehler: BaseException | None = None
        for versuch in range(1, 6):
            try:
                pool = self._ensure_peers()
                peer = pool[0]
                chain = hole_header(
                    self._header_path, start_height, peer, on_log=self._log,
                )
                tip = chain.tip_height()
                if peer.start_height and tip < peer.start_height:
                    chain = hole_header(
                        self._header_path, start_height, peer, on_log=self._log,
                    )
                    tip = chain.tip_height()
                letzter_fehler = None
                break
            except (ConnectionError, OSError, TimeoutError) as exc:
                letzter_fehler = exc
                self._log(
                    f"Header-Sync abgebrochen ({exc}) — "
                    f"neuer Peer (Versuch {versuch}/5)…"
                )
                self.close()
        if chain is None or letzter_fehler is not None and tip <= 0:
            raise RuntimeError(
                f"Header-Sync gescheitert: {letzter_fehler}"
            ) from letzter_fehler
        end = tip if stop_height is None else min(stop_height, tip)
        start = max(0, start_height)
        result = ScanResult(start_height=start, stop_height=end)
        if end < start:
            return result

        bestaende: dict[str, MatchedOutput] = dict(seed_outputs or {})
        verlauf: dict[str, dict[str, Any]] = dict(seed_verlauf or {})
        if bestaende:
            self._log(
                f"Inkrementell ab Block {start:,}: "
                f"{len(bestaende)} UTXOs aus dem Cache".replace(",", ".")
            )
        passe = plane_filter_passes(start, end, set(watched), used_scripts)
        gesamt = _filter_umfang(passe)
        self._filter_gesamt = gesamt
        gezaehlt = [0]
        geprueft = 0
        if gesamt:
            self._log(
                f"Filter {gesamt:,} Blöcke zu prüfen "
                f"({start:,}–{end:,}).".replace(",", ".")
            )
        for name, von, bis, scripts in passe:
            from display import melde_zwischenstand

            melde_zwischenstand(
                f"BIP-158 {name}: Block {von:,}–{bis:,} "
                f"({len(scripts)} Keys)".replace(",", ".")
            )
            chunks = _cfilter_chunks(
                von, bis, chain.hash_at, schritt=GETCFILTERS_MAX,
            )
            geladen = verteile_cfilter_chunks(
                pool, chunks, scripts, on_log=self._log,
                gesamt=gesamt, gezaehlt=gezaehlt,
                tor_proxy=self._tor_proxy,
            )
            for zeilen in geladen:
                for h, block_hash, _blob, roh in zeilen:
                    display = hash_to_hex(block_hash)
                    geprueft += 1
                    if roh is None:
                        self._emit(h, end, geprueft, len(result.matched_blocks), name)
                        continue
                    header, txs = parse_raw_block(roh)
                    treffer, neu, spent_by = extract_from_parsed_block(
                        header, txs, watched, h,
                    )
                    gesehen = set(bestaende) | set(neu)
                    spent_ours = {
                        key: spent_by[key] for key in spent_by if key in gesehen
                    }
                    self._log_block_treffer(h, neu, set(spent_ours))
                    if not treffer and not spent_ours:
                        result.false_positive_blocks.append(display)
                        self._emit(h, end, geprueft, len(result.matched_blocks), name)
                        continue
                    result.matched_blocks.append(display)
                    result.transactions.extend(treffer)
                    _uebernehme_block_verlauf(
                        verlauf, neu, spent_ours,
                        hoehe=h, block_time=_header_unixzeit(header),
                    )
                    for key in spent_ours:
                        bestaende.pop(key, None)
                    bestaende.update(neu)
                    if on_utxos_update and (neu or spent_ours):
                        on_utxos_update([
                            _matched_output_to_utxo(ausgabe)
                            for ausgabe in bestaende.values()
                        ])
                    latest = next(iter(neu), None)
                    self._emit(
                        h, end, geprueft, len(result.matched_blocks), "match",
                        utxo_id=latest,
                    )
        result.outputs = list(bestaende.values())
        result.verlauf = list(verlauf.values())
        return result


@dataclass
class Bip158Client:
    scanner: BIP158Scanner
    start_height: int = 0
    verbose: bool = True
    cache_dir: Path | None = None


def create_bip158_client_from_env(
    env: dict[str, str],
    *,
    start_height: int = 0,
    progress_callback: ProgressCallback | None = None,
    verbose: bool = True,
    cache_dir: Path | None = None,
) -> Bip158Client:
    """P2P-Client: Clearnet zuerst, bei Fehlschlag Tor wie beim eigenen Node."""
    from core.p2p import SEGWIT_HEIGHT, p2p_peers_from_env
    from core.paths import app_dir

    peers = p2p_peers_from_env(env)
    header_path = app_dir() / "immutable_cache" / "p2p_headers.bin"
    if cache_dir is not None:
        header_path = Path(cache_dir).parent / "immutable_cache" / "p2p_headers.bin"
    scanner = BIP158Scanner(
        peers=peers,
        header_path=header_path,
        progress_callback=progress_callback,
        env=env,
    )
    hoehe = start_height if start_height else SEGWIT_HEIGHT
    return Bip158Client(
        scanner=scanner, start_height=hoehe, verbose=verbose, cache_dir=cache_dir,
    )


def vorab_block_header(
    env: dict[str, str],
    *,
    cache_dir: Path | None = None,
    on_log=None,
) -> int:
    """
    Holt die Header-Kette ab SegWit in denselben Cache wie der Scan.

    Ohne XPUB, im Hintergrund — der erste Compact-Filter-Scan spart sich
    den Erstsync. Ein eigener Electrum-Server braucht das nicht.

    Ist der Cache schon weit, nur Tip-Nachzug (keine „ab SegWit“-Meldung).
    """
    from core.p2p import SEGWIT_HEIGHT, header_datei_tip, hole_header

    def _log(text: str) -> None:
        if on_log:
            on_log(text)

    if env.get("BIP158_P2P", "1").strip().lower() in ("0", "false", "nein", "off"):
        _log("P2P-Header-Vorab aus (BIP158_P2P=0).")
        return 0

    client = create_bip158_client_from_env(
        env, start_height=SEGWIT_HEIGHT, cache_dir=cache_dir,
    )
    path = client.scanner._header_path
    tip_bisher = header_datei_tip(path)
    if tip_bisher is not None and tip_bisher > SEGWIT_HEIGHT:
        _log(
            f"Header-Cache bei Block {tip_bisher:,} — prüfe Chain-Tip…"
            .replace(",", ".")
        )
    else:
        _log(
            "Lade Block-Header ab SegWit (Block 481.824, August 2017) — "
            "einmalig, für alle späteren Wallets."
        )
    peer = client.scanner._ensure_peer()
    try:
        chain = hole_header(path, SEGWIT_HEIGHT, peer, on_log=_log)
        tip = chain.tip_height()
        if tip_bisher is not None and tip <= tip_bisher:
            _log(
                f"Header-Cache unverändert bis Block {tip:,}.".replace(",", ".")
            )
        else:
            _log(
                f"Header-Cache fertig bis Block {tip:,}.".replace(",", ".")
            )
        return tip
    finally:
        client.scanner.close()


def verify_p2p_filters(client: Bip158Client) -> int:
    """Handshake mit einem Compact-Filter-Peer; Rückgabe: dessen Höhe."""
    live = client.scanner._ensure_peer()
    return int(live.start_height)


def _used_scripts_aus_cache(xpub: str, cache_dir: Path | None) -> set[bytes]:
    if cache_dir is None:
        return set()
    try:
        import main as main_mod

        eintrag = main_mod.load_xpub_cache_entry(xpub, cache_dir)
    except Exception:
        return set()
    roh = (eintrag or {}).get("raw") or {}
    adressen: list[str] = []
    for utxo in roh.get("utxos") or []:
        addr = utxo.get("address")
        if addr:
            adressen.append(addr)
    adressen.extend(roh.get("scanned_addresses") or [])
    try:
        verlauf = main_mod.load_xpub_verlauf_cache(xpub, cache_dir)
    except Exception:
        verlauf = None
    for eintrag in verlauf or []:
        addr = eintrag.get("address")
        if addr:
            adressen.append(addr)
    if not adressen:
        return set()
    return set(addresses_to_script_pubkeys(adressen).keys())


#: TxID → Blockhöhe für P2P-Block-Fallback (z. B. aus UTXO-Scan).
_TX_HEIGHT_HINTS: ContextVar[dict[str, int] | None] = ContextVar(
    "xpq_tx_height_hints", default=None,
)


def note_tx_height(txid: str, height: int | None) -> None:
    """Merkt eine bekannte Bestätigungshöhe für den nächsten ``get_tx``."""
    if height is None:
        return
    try:
        h = int(height)
    except (TypeError, ValueError):
        return
    if h <= 0:
        return
    key = (txid or "").strip().lower()
    if len(key) != 64:
        return
    cur = _TX_HEIGHT_HINTS.get()
    if cur is None:
        cur = {}
        _TX_HEIGHT_HINTS.set(cur)
    cur[key] = h


def tx_height_hint(txid: str) -> int | None:
    cur = _TX_HEIGHT_HINTS.get()
    if not cur:
        return None
    return cur.get((txid or "").strip().lower())


def clear_tx_height_hints() -> None:
    """Leert den Höhen-Hinweis (Tests / neuer Lauf)."""
    _TX_HEIGHT_HINTS.set({})


def _embit_tx_to_dict(
    tx,
    *,
    height: int | None = None,
    block_time: int | None = None,
) -> dict[str, Any]:
    null = b"\x00" * 32
    vins: list[dict[str, Any]] = []
    for vin in tx.vin:
        if bytes(vin.txid) == null:
            vins.append({"is_coinbase": True})
        else:
            vins.append({"txid": bytes(vin.txid).hex(), "vout": int(vin.vout)})
    vouts: list[dict[str, Any]] = []
    for n, vout in enumerate(tx.vout):
        try:
            addr = vout.script_pubkey.address()
        except Exception:
            addr = None
        vouts.append({
            "n": n,
            "value": vout.value / 1e8,
            "scriptPubKey": {
                "hex": bytes(vout.script_pubkey.data).hex(),
                "address": addr,
            },
        })
    out: dict[str, Any] = {
        "txid": tx.txid().hex(),
        "vin": vins,
        "vout": vouts,
    }
    if height and height > 0:
        status: dict[str, Any] = {
            "confirmed": True,
            "block_height": int(height),
        }
        if block_time:
            status["block_time"] = int(block_time)
        out["status"] = status
    return out


def fetch_tx_p2p(client: Bip158Client, txid: str) -> dict[str, Any]:
    """Reine ``getdata``-TX — scheitert bei historischen Tx oft mit notfound."""
    from core.p2p import hex_to_hash
    from embit.transaction import Transaction

    peer = client.scanner._ensure_peer()
    raw = peer.fetch_tx(hex_to_hash(txid))
    return _embit_tx_to_dict(Transaction.parse(raw))


def fetch_tx_from_block_p2p(
    client: Bip158Client,
    txid: str,
    height: int,
    *,
    on_log=None,
) -> dict[str, Any]:
    """
    Lädt den Block an *height* und extrahiert die Tx.

    Peers ohne Tx-Index liefern historische Tx nicht per ``getdata``, wohl
    aber den ganzen Block (wie beim BIP-158-Scan).
    """
    from core.p2p import (
        SEGWIT_HEIGHT,
        HeaderChain,
        hash_to_hex,
        hole_header,
    )
    from embit.transaction import Transaction

    key = (txid or "").strip().lower()
    hoehe = int(height)
    if hoehe <= 0:
        raise ValueError(f"ungültige Blockhöhe: {height}")

    scanner = client.scanner
    start = client.start_height or SEGWIT_HEIGHT
    chain = HeaderChain(scanner._header_path, start_height=start)
    if chain.tip_height() < hoehe:
        peer = scanner._ensure_peer()
        if on_log:
            on_log(f"Header bis Block {hoehe:,} nachziehen…".replace(",", "."))
        chain = hole_header(
            scanner._header_path, start, peer, on_log=on_log or scanner._log,
        )
    if chain.tip_height() < hoehe:
        raise ConnectionError(
            f"Header-Cache endet bei {chain.tip_height()}, braucht {hoehe}"
        )
    block_hash = chain.hash_at(hoehe)
    if on_log:
        on_log(
            f"hole Block {hoehe:,} ({hash_to_hex(block_hash)[:12]}…) "
            f"für Tx {key[:16]}…".replace(",", ".")
        )
    peer = scanner._ensure_peer()
    raw = peer.fetch_block(block_hash)
    header, txs = parse_raw_block(raw)
    block_time = _header_unixzeit(header)
    gefunden: dict[str, Any] | None = None
    for tx in txs:
        d = _embit_tx_to_dict(tx, height=hoehe, block_time=block_time)
        if d["txid"].lower() == key:
            gefunden = d
            break
    if gefunden is None:
        raise ConnectionError(
            f"Tx {key[:16]}… nicht in Block {hoehe} "
            f"(Peer lieferte {len(txs)} Transaktionen)"
        )
    return gefunden


def fetch_tx_p2p_mit_fallback(
    client: Bip158Client,
    txid: str,
    *,
    core_client=None,
    height: int | None = None,
    on_log=None,
) -> dict[str, Any]:
    """
    Tx-Lookup ohne Electrs: Core-RPC → P2P getdata → Block bei bekannter Höhe.

    *height* oder ``note_tx_height`` liefern die Höhe für den Block-Fallback.
    """
    key = (txid or "").strip().lower()
    hoehe = height if (height and int(height) > 0) else tx_height_hint(key)
    fehler: list[str] = []

    if core_client is not None:
        try:
            from core.bitcoind_rpc import fetch_tx_core

            if on_log:
                on_log(f"Tx {key[:16]}… über Core-RPC…")
            tx = fetch_tx_core(core_client, key)
            st = tx.get("status") or {}
            if st.get("block_height"):
                note_tx_height(key, st["block_height"])
            return tx
        except Exception as exc:
            fehler.append(f"Core: {exc}")

    try:
        return fetch_tx_p2p(client, key)
    except Exception as exc:
        fehler.append(f"P2P-Tx: {exc}")

    if hoehe:
        return fetch_tx_from_block_p2p(
            client, key, int(hoehe), on_log=on_log,
        )

    detail = "; ".join(fehler) if fehler else "unbekannt"
    raise ConnectionError(
        "Transaktion nicht auflösbar ohne Electrs: weder Core-RPC "
        f"(txindex?) noch P2P-getdata, und keine Blockhöhe bekannt ({detail}). "
        "UTXO-Scan-Höhe fehlt, oder Core mit -txindex=1 / Electrs nutzen."
    )


def fetch_address_utxos_bip158(client: Bip158Client, address: str) -> list[dict]:
    return fetch_addresses_utxos_bip158(client, [address])


def fetch_addresses_utxos_bip158(
    client: Bip158Client,
    addresses: Iterable[str],
    *,
    progress_label: str | None = None,
    start_height: int | None = None,
) -> list[dict]:
    _ = progress_label
    address_list = sorted(set(addresses))
    if not address_list:
        return []
    scan_from = client.start_height if start_height is None else start_height
    from display import Bip158ProgressLine, melde_zwischenstand

    tip = None
    try:
        tip = client.scanner.get_block_count()
    except Exception:
        pass
    progress_line = Bip158ProgressLine(verbose=client.verbose, tip_height=tip)

    def on_progress(event: ScanProgress) -> None:
        progress_line.update(
            event.height, event.utxo_id,
            checked=event.blocks_checked, total=event.total_blocks,
        )

    client.scanner._progress_callback = on_progress
    try:
        result = client.scanner.scan_addresses(
            address_list, start_height=scan_from,
        )
    finally:
        progress_line.finish()
    known = set(address_list)
    utxos = []
    for output in result.outputs:
        if output.address in known:
            utxos.append(_matched_output_to_utxo(output))
    melde_zwischenstand(f"BIP-158: {len(utxos)} unspent UTXO(s)")
    return utxos


def _matched_output_to_utxo(output: MatchedOutput) -> dict[str, Any]:
    return {
        "txid": output.txid,
        "vout": output.vout,
        "value": output.value_sats,
        "address": output.address,
        "status": {
            "confirmed": output.block_height > 0,
            "block_height": output.block_height,
        },
    }


#: Blöcke vor dem letzten Tip erneut scannen (Reorg-Puffer).
BIP158_REORG_BUFFER = 6
_LAST_SCAN_TIPS: dict[str, int] = {}


def take_last_scan_tip(xpub: str) -> int | None:
    """Einmaliger Tip-Abruf nach fetch_wallet_utxos_bip158."""
    return _LAST_SCAN_TIPS.pop(xpub, None)


def _seed_aus_cache(
    xpub: str,
    cache_dir: Path | None,
    *,
    ab_hoehe: int,
) -> tuple[dict[str, MatchedOutput], dict[str, dict[str, Any]]]:
    """UTXOs und Verlauf unter *ab_hoehe* als Startbestand für den Inkremental-Scan."""
    if cache_dir is None:
        return {}, {}
    import main as main_mod

    seed_out: dict[str, MatchedOutput] = {}
    entry = main_mod.load_xpub_cache_entry(xpub, cache_dir)
    for u in (entry or {}).get("utxos") or []:
        hoehe = int((u.get("status") or {}).get("block_height") or 0)
        if hoehe >= ab_hoehe:
            continue
        txid = str(u.get("txid") or "").lower()
        vout = int(u.get("vout") or 0)
        key = f"{txid}:{vout}"
        seed_out[key] = MatchedOutput(
            txid=txid,
            vout=vout,
            value_sats=int(u.get("value") or 0),
            address=u.get("address"),
            script_pubkey_hex="",
            block_height=hoehe,
            block_hash="",
        )
    seed_verlauf: dict[str, dict[str, Any]] = {}
    for e in main_mod.load_xpub_verlauf_cache(xpub, cache_dir) or []:
        txid = str(e.get("txid") or "").lower()
        vout = int(e.get("vout") or 0)
        seed_verlauf[f"{txid}:{vout}"] = e
    return seed_out, seed_verlauf


def fetch_wallet_utxos_bip158(
    client: Bip158Client,
    xpubs: list[str],
    *,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    max_addresses_by_xpub: dict[str, int] | None = None,
    on_utxos_update=None,
) -> list[dict]:
    from display import Bip158ProgressLine, melde_zwischenstand
    import main as main_mod

    utxos: list[dict] = []
    for xpub in xpubs:
        konfiguriert = (
            max_addresses_by_xpub.get(xpub, max_addresses)
            if max_addresses_by_xpub
            else max_addresses
        )
        xpub_max = max(int(konfiguriert), int(max_addresses))
        used = _used_scripts_aus_cache(xpub, client.cache_dir)
        start = client.start_height
        seed_out: dict[str, MatchedOutput] = {}
        seed_verlauf: dict[str, dict[str, Any]] = {}
        start_grund = "konfiguriert"
        if client.cache_dir is not None:
            entry = main_mod.load_xpub_cache_entry(xpub, client.cache_dir)
            roh = (entry or {}).get("raw") or {}
            prev_tip = roh.get("scan_tip_height")
            if prev_tip is not None:
                try:
                    prev_tip_i = int(prev_tip)
                except (TypeError, ValueError):
                    prev_tip_i = 0
                if prev_tip_i >= client.start_height:
                    start = max(
                        client.start_height,
                        prev_tip_i - BIP158_REORG_BUFFER + 1,
                    )
                    seed_out, seed_verlauf = _seed_aus_cache(
                        xpub, client.cache_dir, ab_hoehe=start,
                    )
                    start_grund = "tip"
            if start_grund != "tip":
                # UTXO-Cache weg, Alter bleibt: ab First-seen statt SegWit.
                alter_start = main_mod.bip158_start_aus_first_seen(
                    xpub,
                    client.cache_dir,
                    floor=client.start_height,
                    puffer=BIP158_REORG_BUFFER,
                )
                if alter_start is not None:
                    if alter_start > start:
                        start = alter_start
                        start_grund = "alter"
                    elif abs(start - alter_start) <= BIP158_REORG_BUFFER:
                        # Server/CLI hat bip158_start schon aufs Alter gesetzt.
                        start_grund = "alter"
        if seed_out or start_grund == "tip":
            keys_txt = f"{len(used)} used Keys, inkrementell"
        elif start_grund == "alter":
            keys_txt = "ab Wallet-Beginn"
        elif used:
            keys_txt = f"{len(used)} used Keys"
        else:
            keys_txt = "Erstscan"
        anfang = (
            f"P2P-BIP-158 {xpub[:20]}… ab Höhe {start:,} ({keys_txt})"
            .replace(",", ".")
        )
        print(f"\n{anfang}", flush=True)
        melde_zwischenstand(anfang)
        progress_line = Bip158ProgressLine(verbose=client.verbose)

        def on_progress(event: ScanProgress) -> None:
            progress_line.update(
                event.height, event.utxo_id,
                checked=event.blocks_checked, total=event.total_blocks,
            )

        client.scanner._progress_callback = on_progress

        def _bip158_zwischenstand(stand: list[dict], *, _xpub=xpub) -> None:
            if on_utxos_update:
                # Ein XPUB nach dem anderen — Zwischenstand ist der laufende
                # XPUB plus bereits fertige XPUBs dieses Aufrufs.
                on_utxos_update(utxos + stand)

        try:
            result = client.scanner.scan_from_xpub(
                xpub,
                max_index=max(xpub_max // 2, 1),
                start_height=start,
                used_scripts=used,
                seed_outputs=seed_out or None,
                seed_verlauf=seed_verlauf or None,
                on_utxos_update=_bip158_zwischenstand if on_utxos_update else None,
            )
        finally:
            progress_line.finish()
        _LAST_SCAN_TIPS[xpub] = int(result.stop_height)
        for output in result.outputs:
            utxos.append(_matched_output_to_utxo(output))
        if on_utxos_update:
            on_utxos_update(list(utxos))
        if client.cache_dir is not None and result.verlauf:
            main_mod.merke_bip158_verlauf(xpub, result.verlauf, client.cache_dir)
            melde_zwischenstand(
                f"BIP-158 Verlauf: {len(result.verlauf)} Ein- und Ausgänge"
            )
    fertig = f"BIP-158: {len(utxos)} unspent UTXO(s) nach Filter-Scan"
    print(f"\n{fertig}", flush=True)
    melde_zwischenstand(fertig)
    return utxos


def _run_chiabip158_self_test() -> None:
    if PyBIP158 is None:
        print("chiabip158 not installed — skip self-test")
        return
    script_a = bytes.fromhex("0014" + "ab" * 20)
    script_b = bytes.fromhex("0014" + "cd" * 20)
    built = PyBIP158([bytearray(script_a), bytearray(script_b)])
    encoded = bytes(built.filter_bytes) if hasattr(built, "filter_bytes") else bytes()
    if not encoded:
        print("chiabip158 self-test skipped (kein filter_bytes)")
        return
    matcher = PyBIP158(list(encoded))
    print("chiabip158 self-test OK (synthetic filter)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BIP-158 Compact-Filter-Scanner (Bitcoin-P2P)"
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        _run_chiabip158_self_test()
        return 0
    print("P2P-Scan: py main.py --bip158", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


