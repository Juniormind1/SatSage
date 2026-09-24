"""BIP-158 Compact-Filter-Scan über Bitcoin-P2P.

CFilter-Pipeline, Block-Extract, Live-Peers, ``BIP158Scanner`` und
Header-Vorab. Ableitung und UTXO-API: ``core.bip158_wallet`` (Late-Import).
Root-``bip158_scanner`` re-exportiert die Symbole.
"""
from __future__ import annotations

import io
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from core.bip158_filter import (
    MatchedOutput,
    MatchedTransaction,
    ProgressCallback,
    ScanProgress,
    ScanResult,
    _CoreBasicFilterMatcher,
)

logger = logging.getLogger(__name__)

DEFAULT_GAP_LIMIT = 20
DEFAULT_MAX_INDEX = 500
DEFAULT_MAX_ADDRESSES = 50
#: ~14 Tage. Ungenutzte Keys nur in diesem Fenster — Historie wäre nur FP.
TURBO_WINDOW = 2_016


# ---------------------------------------------------------------------------
# TurboSync (Wasabi): ungenutzte Keys nicht durch die Historie jagen
# ---------------------------------------------------------------------------

#: Marker: Filter-Treffer, Block wird asynchron geholt.
_BLOCK_PENDING = object()


def plane_filter_passes(
    start_height: int,
    tip: int,
    all_scripts: set[bytes],
    used_scripts: set[bytes],
    *,
    turbo_window: int = TURBO_WINDOW,
    gap_scripts: set[bytes] | None = None,
) -> list[tuple[str, int, int, frozenset[bytes]]]:
    """
    Filter-Pässe für Compact-Filter-Scan.

    Erstscan (keine used_scripts): Wasabi-Turbo —
      1. turbo: alle Keys × tip−window…tip (schneller Zwischenstand)
      2. historie: nur gap_scripts (klein) × start…turbo−1
    Danach (used gesetzt), chronologisch fürs UTXO-Set:
      1. historie: nur used Keys
      2. turbo: alle Keys im Fenster
    Ungenutzte Lookahead-Keys erzeugen in alten Filtern nur False Positives.
    """
    if tip < start_height:
        return []
    scripts_all = frozenset(all_scripts)
    turbo_from = max(start_height, tip - turbo_window + 1)
    if not used_scripts:
        # Turbo zuerst (UX); Historie nur mit kleiner Gap-Menge.
        passe: list[tuple[str, int, int, frozenset[bytes]]] = [
            ("turbo", turbo_from, tip, scripts_all),
        ]
        if start_height < turbo_from:
            gap = frozenset(gap_scripts or ())
            passe.append(("historie", start_height, turbo_from - 1, gap))
        return passe
    passe = []
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
    *,
    hash_at=None,
    cache_dir=None,
    block_queue: queue.Queue | None = None,
    stats: dict | None = None,
) -> list:
    """
    Filter holen/matchen. Blöcke nur bei *block_queue is None* synchron;
    sonst Treffer als ``_BLOCK_PENDING`` und Auftrag in die Queue.
    """
    from core.cfilter_cache import lade_cfilter_blob, speichere_cfilter_blob
    from core.p2p import hash_to_hex
    from display import melde_zwischenstand

    expect = bis - von + 1
    melde_zwischenstand(
        f"Filter Block {von:,}–{bis:,}…".replace(",", "."),
        log=False,
    )

    # Cache je Höhe (Hash aus Header-Kette, sonst aus Netzantwort).
    cached: dict[int, tuple[bytes, bytes]] = {}
    fehlend: list[int] = []
    for h in range(von, bis + 1):
        bh = None
        if hash_at is not None:
            try:
                bh = hash_at(h)
            except Exception:
                bh = None
        if bh is not None and cache_dir is not None:
            blob = lade_cfilter_blob(cache_dir, h, bh)
            if blob is not None:
                cached[h] = (bh, blob)
                if stats is not None:
                    stats["gecacht"] = int(stats.get("gecacht") or 0) + 1
                continue
        fehlend.append(h)

    filter_liste: list[tuple[bytes, bytes]] = []
    if not fehlend:
        for h in range(von, bis + 1):
            filter_liste.append(cached[h])
    else:
        # Wire-API ist range-basiert — fehlende Höhen über den Chunk nachladen.
        netz = peer.fetch_cfilters(von, stop_hash, expect=expect)
        if len(netz) != expect:
            raise ConnectionError(
                f"cfilter: {len(netz)} statt {expect} ab Höhe {von}"
            )
        if stats is not None:
            stats["geholt"] = int(stats.get("geholt") or 0) + len(netz)
        for offset, (block_hash, blob) in enumerate(netz):
            h = von + offset
            if h in cached:
                filter_liste.append(cached[h])
                continue
            if cache_dir is not None and blob:
                speichere_cfilter_blob(cache_dir, h, block_hash, blob)
            filter_liste.append((block_hash, blob))

    scripts_list = list(scripts) if not isinstance(scripts, list) else scripts
    zeilen = []
    for offset, (block_hash, blob) in enumerate(filter_liste):
        h = von + offset
        display = hash_to_hex(block_hash)
        matcher = _CoreBasicFilterMatcher(blob, display)
        roh = None
        if matcher.match_any(scripts_list):
            if on_log:
                on_log(f"{_filter_treffer_praefix(h)} — hole Block…")
            if block_queue is not None:
                block_queue.put((h, block_hash))
                roh = _BLOCK_PENDING
            else:
                roh = peer.fetch_block(block_hash)
        zeilen.append((h, block_hash, blob, roh))
    return zeilen


def _block_aus_warteschlange(
    hoehe: int,
    block_hash: bytes,
    *,
    ergebnisse: dict,
    wach: threading.Condition,
    timeout: float = 180.0,
    soll_enden=None,
) -> bytes | None:
    deadline = time.monotonic() + timeout
    with wach:
        while hoehe not in ergebnisse:
            if soll_enden and soll_enden():
                from core.jobs import Cancelled

                raise Cancelled()
            rest = deadline - time.monotonic()
            if rest <= 0:
                raise TimeoutError(
                    f"Block-Download Timeout Höhe {hoehe}"
                )
            wach.wait(timeout=min(1.0, rest))
        return ergebnisse.pop(hoehe)


def _zeilen_bloecke_aufloesen(
    zeilen: list,
    *,
    ergebnisse: dict,
    wach: threading.Condition,
    soll_enden=None,
) -> list:
    aufgeloest = []
    for h, block_hash, blob, roh in zeilen:
        if roh is _BLOCK_PENDING:
            roh = _block_aus_warteschlange(
                h, block_hash, ergebnisse=ergebnisse, wach=wach,
                soll_enden=soll_enden,
            )
        aufgeloest.append((h, block_hash, blob, roh))
    return aufgeloest


def verteile_cfilter_chunks(
    peers,
    chunks: list[tuple[int, int, bytes]],
    scripts,
    *,
    on_log=None,
    gesamt: int = 0,
    gezaehlt: list[int] | None = None,
    tor_proxy: tuple[str, int] | None = None,
    hash_at=None,
    cache_dir=None,
    stats: dict | None = None,
    hole_bloecke: bool = True,
):
    """
    Holt Filter-Chunks parallel (ein Auftrag je Peer).

    Liefert Chunks als Iterator in Höhenreihenfolge. Filter-Match und
    Block-Download sind entkoppelt: 1–2 Block-Worker bedienen eine Queue,
    False Positives blockieren den nächsten Filter-Batch nicht.
    """
    if not peers:
        raise RuntimeError("keine Compact-Filter-Peers")
    if not chunks:
        return
        yield  # macht die Funktion zum Generator
    stand = gezaehlt if gezaehlt is not None else [0]
    stats = stats if stats is not None else {}

    # Cancel-Event hier (Job-Thread) einfangen — Worker haben kein ContextVar.
    cancel_ev = None
    try:
        from core.jobs import aktueller_job as _aktueller_job_fn

        _j = _aktueller_job_fn()
        if _j is not None:
            cancel_ev = _j._cancel
    except Exception:
        cancel_ev = None

    # Async-Blöcke sobald hole_bloecke: Filter enqueued nur, Block-Worker
    # holen mit Peer-Lock (Socket nicht parallel getcfilters+getdata).
    async_blocks = bool(hole_bloecke)
    block_queue: queue.Queue | None = queue.Queue() if async_blocks else None
    peer_locks = {id(p): threading.Lock() for p in peers}
    filter_peers = list(peers)

    block_ergebnisse: dict = {}
    block_wach = threading.Condition()
    block_stop = threading.Event()
    block_threads: list[threading.Thread] = []

    def _soll_enden() -> bool:
        if cancel_ev is not None and cancel_ev.is_set():
            return True
        if block_stop.is_set():
            return True
        try:
            from core.jobs import job_abgebrochen
            from display import is_list_abort_requested

            return bool(job_abgebrochen() or is_list_abort_requested())
        except ImportError:
            return False

    def _abbruch_oder_raus() -> None:
        """Wirft Cancelled bzw. beendet den Generator sauber."""
        if not _soll_enden():
            return
        block_stop.set()
        try:
            from core.jobs import raise_if_job_cancelled

            raise_if_job_cancelled()
        except ImportError:
            pass
        # ContextVar fehlt (sollte hier nicht), aber Event ist gesetzt.
        from core.jobs import Cancelled

        raise Cancelled()

    def block_arbeit(peer) -> None:
        lock = peer_locks[id(peer)]
        while not block_stop.is_set():
            if _soll_enden():
                return
            try:
                auftrag = block_queue.get(timeout=0.4) if block_queue else None
            except queue.Empty:
                continue
            if auftrag is None:
                return
            hoehe, block_hash = auftrag
            try:
                with lock:
                    roh = peer.fetch_block(block_hash)
            except Exception as exc:
                try:
                    from core.jobs import ist_abbruch

                    if ist_abbruch(exc):
                        return
                except ImportError:
                    pass
                roh = None
            with block_wach:
                block_ergebnisse[hoehe] = roh
                block_wach.notify_all()

    if async_blocks and peers:
        n_block = min(2, len(peers))
        for peer in peers[:n_block]:
            t = threading.Thread(target=block_arbeit, args=(peer,), daemon=True)
            block_threads.append(t)
            t.start()

    def _chunk_laden(peer, von, bis, stop):
        lock = peer_locks[id(peer)]
        with lock:
            return _lade_cfilter_chunk(
                peer, von, bis, stop, scripts, on_log=on_log,
                hash_at=hash_at, cache_dir=cache_dir,
                block_queue=block_queue, stats=stats,
            )

    def _chunk_fertig(zeilen):
        if not async_blocks:
            return zeilen
        return _zeilen_bloecke_aufloesen(
            zeilen, ergebnisse=block_ergebnisse, wach=block_wach,
            soll_enden=_soll_enden,
        )

    try:
        if len(filter_peers) == 1:
            for von, bis, stop in chunks:
                _abbruch_oder_raus()
                zeilen = _chunk_laden(filter_peers[0], von, bis, stop)
                _tick_filter_stand(von, bis, stand, gesamt)
                yield _chunk_fertig(zeilen)
            return

        auftraege: queue.Queue = queue.Queue()
        for index, chunk in enumerate(chunks):
            auftraege.put((index, chunk, 0))
        fertig: dict[int, object] = {}
        sperre = threading.Lock()
        wach = threading.Condition(sperre)
        lebendig = len(filter_peers)
        max_versuche = 5
        stand_lock = threading.Lock()
        erledigt = [0]

        def arbeit(peer) -> None:
            nonlocal lebendig
            try:
                while True:
                    if _soll_enden():
                        return
                    try:
                        index, chunk, versuche = auftraege.get(timeout=0.4)
                    except queue.Empty:
                        with sperre:
                            if erledigt[0] >= len(chunks):
                                return
                        continue
                    von, bis, stop = chunk
                    try:
                        zeilen = _chunk_laden(peer, von, bis, stop)
                    except Exception as exc:
                        try:
                            from core.jobs import ist_abbruch

                            if ist_abbruch(exc):
                                return
                        except ImportError:
                            pass
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
            on_log(f"Filter über {len(filter_peers)} Peers parallel…")
        threads = [
            threading.Thread(target=arbeit, args=(peer,), daemon=True)
            for peer in filter_peers
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
            for index in range(len(chunks)):
                _abbruch_oder_raus()
                with wach:
                    while index not in fertig:
                        if _soll_enden():
                            break
                        if lebendig <= 0 and index not in fertig:
                            break
                        wach.wait(timeout=1.0)
                    if index not in fertig:
                        # Abbruch: keine neuen Peers anheuern — sonst läuft
                        # der Scan trotz Knopf weiter.
                        _abbruch_oder_raus()
                        if not _neuer_worker():
                            raise RuntimeError(
                                "alle Compact-Filter-Peers ausgefallen"
                            )
                        while index not in fertig:
                            _abbruch_oder_raus()
                            if lebendig <= 0 and index not in fertig:
                                raise RuntimeError(
                                    "alle Compact-Filter-Peers ausgefallen"
                                )
                            wach.wait(timeout=1.0)
                        if index not in fertig:
                            _abbruch_oder_raus()
                            raise RuntimeError(
                                "alle Compact-Filter-Peers ausgefallen"
                            )
                    wert = fertig.pop(index)
                if isinstance(wert, BaseException):
                    raise wert
                # Block-Auflösung außerhalb des Filter-Locks — nächste
                # Filter-Chunks laufen weiter (False-Positive-Blöcke stoppen nicht).
                yield _chunk_fertig(wert)
        finally:
            with sperre:
                erledigt[0] = max(erledigt[0], len(chunks))
            for t in threads:
                t.join(timeout=2.0)
    finally:
        block_stop.set()
        if block_queue is not None:
            for _ in block_threads:
                try:
                    block_queue.put(None)
                except Exception:
                    pass
        for t in block_threads:
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
        except Exception as exc:
            # Job-Abbruch darf hier nicht verschwinden (sonst läuft BIP-158
            # trotz Abbruch-Knopf bis zum Tip weiter).
            from core.jobs import ist_abbruch

            if ist_abbruch(exc):
                raise
            pass

    def _check_abbruch(self) -> None:
        """Web-Job-Abbruch → Cancelled; CLI-q → soft über is_list_abort."""
        from core.jobs import raise_if_job_cancelled

        raise_if_job_cancelled()

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
        self._check_abbruch()
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

    def _ensure_peer(self, *, still: bool = False):
        return self._ensure_peers(limit=1, still=still)[0]

    def _ensure_peers(self, limit: int | None = None, *, still: bool = False):
        from core.p2p import FILTER_PEERS_MAX, verbinde_compact_filter_peers

        # Über Tor weniger Parallelität — sonst reißen Peers und stecken
        # die Queue mit toten Sockets zu.
        # still: nur Header-Fortschritt dämpfen — Peer/Tor-Log bis 3 Peers bleibt.
        _ = still
        vorgabe = 2 if self._tor_proxy else FILTER_PEERS_MAX
        ziel = vorgabe if limit is None else max(1, min(limit, vorgabe if self._tor_proxy else limit))
        if self._peer is not None and self._peer not in self._pool:
            self._pool.insert(0, self._peer)
        if len(self._pool) >= ziel:
            return self._pool[:ziel]
        exclude = {(p.host, p.port) for p in self._pool}
        if not self._pool:
            self._log("Suche Compact-Filter-Peers…")
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

            # Ankündigung VOR dem langen SOCKS-/Binary-Schritt.
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
        from core.bip158_wallet import addresses_to_script_pubkeys

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
        from core.bip158_wallet import derive_script_pubkeys_from_xpub

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
            xpub=xpub,
            gap_limit=gap_limit,
            max_index=index_limit,
            include_change=include_change,
        )

    def scan_from_xpub_sync(self, xpub: str, **kwargs) -> ScanResult:
        return self.scan_from_xpub(xpub, **kwargs)

    def _immutable_dir(self) -> Path | None:
        if self._header_path is not None:
            return Path(self._header_path).parent
        return None

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
        xpub: str | None = None,
        gap_limit: int = DEFAULT_GAP_LIMIT,
        max_index: int = DEFAULT_MAX_INDEX,
        include_change: bool = True,
    ) -> ScanResult:
        from core.bip158_wallet import (
            _matched_output_to_utxo,
            gap_scripts_anfang,
            scripts_mit_gap_um_treffer,
        )
        from core.p2p import GETCFILTERS_MAX, hash_to_hex, hole_header

        if not watched:
            raise ValueError("keine Skripte zum Beobachten")
        chain = None
        tip = 0
        self._log("Synchronisiere Block-Header…")
        letzter_fehler: BaseException | None = None
        pool: list = []
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

        seed_out = dict(seed_outputs or {})
        seed_verl = dict(seed_verlauf or {})
        if seed_out:
            self._log(
                f"Inkrementell ab Block {start:,}: "
                f"{len(seed_out)} UTXOs aus dem Cache".replace(",", ".")
            )

        erstscan = not used_scripts
        gap0: set[bytes] = set()
        if erstscan and xpub:
            gap0 = gap_scripts_anfang(
                xpub, gap_limit=gap_limit, include_change=include_change,
            )
        elif erstscan:
            # Ohne XPUB: kleine Teilmenge der Watchlist als Historie-Seed.
            gap0 = set(list(watched.keys())[: max(1, gap_limit * 2)])

        passe = plane_filter_passes(
            start, end, set(watched), used_scripts, gap_scripts=gap0,
        )
        gesamt = _filter_umfang(passe)
        self._filter_gesamt = gesamt
        gezaehlt = [0]
        geprueft = 0
        filter_stats: dict[str, int] = {"geholt": 0, "gecacht": 0}
        cache_dir = self._immutable_dir()
        self._log(
            f"BIP-158 Start Höhe {start:,}, {len(watched)} Scripts, "
            f"{gesamt:,} Filter-Höhen"
            .replace(",", ".")
        )
        if gesamt:
            self._log(
                f"Filter {gesamt:,} Blöcke zu prüfen "
                f"({start:,}–{end:,}).".replace(",", ".")
            )

        # Block-Events für finalen chronologischen UTXO-Merge (Turbo-zuerst).
        block_events: list[tuple[int, str, bytes]] = []
        hit_scripts: set[bytes] = set(used_scripts)
        # Provisorischer Stand für UI nach Turbo.
        bestaende: dict[str, MatchedOutput] = dict(seed_out)
        verlauf: dict[str, dict[str, Any]] = dict(seed_verl)

        def _apply_block(
            h: int, display: str, roh: bytes, phase: str,
            *, provisional: bool,
        ) -> None:
            nonlocal bestaende, verlauf
            header, txs = parse_raw_block(roh)
            treffer, neu, spent_by = extract_from_parsed_block(
                header, txs, watched, h,
            )
            for spk_hex in (o.script_pubkey_hex for o in neu.values()):
                try:
                    hit_scripts.add(bytes.fromhex(spk_hex))
                except ValueError:
                    pass
            gesehen = set(bestaende) | set(neu)
            spent_ours = {
                key: spent_by[key] for key in spent_by if key in gesehen
            }
            self._log_block_treffer(h, neu, set(spent_ours))
            if not treffer and not spent_ours:
                if display not in result.false_positive_blocks:
                    result.false_positive_blocks.append(display)
                self._emit(h, end, geprueft, len(result.matched_blocks), phase)
                return
            if display not in result.matched_blocks:
                result.matched_blocks.append(display)
            result.transactions.extend(treffer)
            _uebernehme_block_verlauf(
                verlauf, neu, spent_ours,
                hoehe=h, block_time=_header_unixzeit(header),
            )
            for key in spent_ours:
                bestaende.pop(key, None)
            bestaende.update(neu)
            if provisional and on_utxos_update and (neu or spent_ours):
                on_utxos_update([
                    _matched_output_to_utxo(ausgabe)
                    for ausgabe in bestaende.values()
                ])
            latest = next(iter(neu), None)
            self._emit(
                h, end, geprueft, len(result.matched_blocks), "match",
                utxo_id=latest,
            )

        def _rebuild_chronologisch() -> None:
            """Final: Seed + alle Events nach Höhe — korrekt bei Turbo-zuerst."""
            nonlocal bestaende, verlauf
            bestaende = dict(seed_out)
            verlauf = dict(seed_verl)
            result.matched_blocks.clear()
            result.false_positive_blocks.clear()
            result.transactions.clear()
            for h, display, roh in sorted(block_events, key=lambda e: e[0]):
                header, txs = parse_raw_block(roh)
                treffer, neu, spent_by = extract_from_parsed_block(
                    header, txs, watched, h,
                )
                gesehen = set(bestaende) | set(neu)
                spent_ours = {
                    key: spent_by[key] for key in spent_by if key in gesehen
                }
                if not treffer and not spent_ours:
                    result.false_positive_blocks.append(display)
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
            if on_utxos_update:
                on_utxos_update([
                    _matched_output_to_utxo(a) for a in bestaende.values()
                ])

        for name, von, bis, scripts in passe:
            from display import is_list_abort_requested, melde_zwischenstand

            self._check_abbruch()
            if is_list_abort_requested():
                self._log("BIP-158 abgebrochen.")
                break

            # Historie-Pass beim Erstscan: Hits aus Turbo + Gap nachziehen.
            if name == "historie" and erstscan and xpub:
                scripts = frozenset(
                    scripts_mit_gap_um_treffer(
                        xpub, hit_scripts | gap0,
                        gap_limit=gap_limit,
                        max_index=max_index,
                        include_change=include_change,
                    )
                )
            elif name == "historie" and erstscan:
                scripts = frozenset(hit_scripts | gap0 | set(scripts))

            if not scripts and name == "historie":
                self._log(
                    f"BIP-158 historie übersprungen (keine Keys) "
                    f"{von:,}–{bis:,}".replace(",", ".")
                )
                continue

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
                hash_at=chain.hash_at,
                cache_dir=cache_dir,
                stats=filter_stats,
            )
            abgebrochen = False
            for zeilen in geladen:
                self._check_abbruch()
                if is_list_abort_requested():
                    abgebrochen = True
                    break
                for h, block_hash, _blob, roh in zeilen:
                    self._check_abbruch()
                    display = hash_to_hex(block_hash)
                    geprueft += 1
                    if roh is None:
                        self._emit(h, end, geprueft, len(result.matched_blocks), name)
                        continue
                    block_events.append((h, display, roh))
                    # Provisorisch anwenden (Turbo-UX); final rebuild am Ende.
                    _apply_block(
                        h, display, roh, name,
                        provisional=True,
                    )
            if abgebrochen or is_list_abort_requested():
                self._log("BIP-158 abgebrochen.")
                break

        if erstscan and block_events:
            _rebuild_chronologisch()
        elif not erstscan and block_events and any(
            p[0] == "turbo" for p in passe
        ) and any(p[0] == "historie" for p in passe):
            # historie→turbo ist schon chronologisch im Stream; kein Rebuild nötig.
            pass

        self._log(
            f"BIP-158 Filter: {filter_stats.get('geholt', 0)} geholt, "
            f"{filter_stats.get('gecacht', 0)} aus Cache"
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


def vorab_block_header(
    env: dict[str, str],
    *,
    cache_dir: Path | None = None,
    immutable_dir: Path | None = None,
    on_log=None,
) -> int:
    """
    Holt die Header-Kette ab SegWit in denselben Cache wie der Scan.

    Ohne XPUB, im Hintergrund — der erste Compact-Filter-Scan spart sich
    den Erstsync. Ein eigener Electrum-Server braucht das nicht.

    Ist der Cache schon weit, nur Tip-Nachzug (keine „ab SegWit“-Meldung).
    """
    from core.bip158_wallet import create_bip158_client_from_env
    from core.p2p import SEGWIT_HEIGHT, header_datei_tip, hole_header

    def _log(text: str) -> None:
        if on_log:
            on_log(text)

    if env.get("BIP158_P2P", "1").strip().lower() in ("0", "false", "nein", "off"):
        _log("P2P-Header-Vorab aus (BIP158_P2P=0).")
        return 0

    client = create_bip158_client_from_env(
        env,
        start_height=SEGWIT_HEIGHT,
        cache_dir=cache_dir,
        immutable_dir=immutable_dir,
    )
    path = client.scanner._header_path
    tip_bisher = header_datei_tip(path)
    tip_schon_da = tip_bisher is not None and tip_bisher > SEGWIT_HEIGHT
    if not tip_schon_da:
        _log(
            "Lade Block-Header ab SegWit (Block 481.824, August 2017) — "
            "einmalig, für alle späteren Wallets."
        )
    # Tip schon da: Peer/Tor still — nur bei echtem Höhenzuwachs melden.
    peer = client.scanner._ensure_peer(still=tip_schon_da)
    try:
        def _log_fortschritt(text: str) -> None:
            if tip_schon_da and (
                text.startswith("Frage Block-Header")
                or text.startswith("Header bis Block")
                or text.startswith("Header-Cache aktuell")
            ):
                return
            _log(text)

        chain = hole_header(
            path,
            SEGWIT_HEIGHT,
            peer,
            on_log=_log_fortschritt if tip_schon_da else _log,
        )
        tip = chain.tip_height()
        if tip_bisher is not None and tip <= tip_bisher:
            pass
        elif tip_schon_da:
            _log(
                f"Header-Cache nachgezogen bis Block {tip:,}.".replace(",", ".")
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
