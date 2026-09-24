"""Wallet UTXO sanctions check (Slice 4).

Live-Event-Sammlung, _pruefe_ein_utxo, Parallel-Check,
check_wallet_utxos_sanctions, print_sanction_check_report.
analyze.py re-exportiert die öffentliche API.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from display import (
    abbrev_display,
    cancellable_output,
    format_utxo_ref,
    is_list_abort_requested,
)

from core.trace import (
    CoinbaseFunding,
    FundingEdge,
    iter_funding_inputs,
)

from core.sanction_hops import (
    SanctionHitFound,
    _coinjoins_zusammenfuehren,
    _sanction_coinjoin_eintrag,
    _sanction_progress_status,
)

if TYPE_CHECKING:
    from main import WalletContext


def _main():
    import main
    return main


class _FortschrittsAdapter:
    """
    Übersetzt die ``update(**felder)``-Aufrufe aus
    ``scan_external_sanction_hops`` in ein ``progress_cb(felder)``.

    Damit meldet auch der Nicht-CLI-Aufrufer die tatsächliche Hop-Tiefe und
    Adresszahl, statt nur einmal pro UTXO ``hop=0``. Der Lock hält die
    Meldungen im Parallel-Lauf auseinander — sonst mischen sich die Zeilen
    zweier Worker zu einer, die keinen Zustand mehr beschreibt.
    """

    def __init__(self, callback, lock):
        self._callback = callback
        self._lock = lock

    def update(self, **felder):
        with self._lock:
            self._callback(felder)


def _event_gegen_liste(
    event: dict,
    sanctioned_addresses: frozenset[str],
    *,
    wallet_utxo_ref: str,
) -> dict | None:
    """Ein Hop-Event gegen die aktuelle Liste — None wenn kein Treffer."""
    addr = str(event.get("address") or "").strip()
    if not addr or addr not in sanctioned_addresses:
        return None
    return {
        "hop": int(event.get("hop") or 0),
        "address": addr,
        "from_utxo": str(event.get("from_utxo") or ""),
        "in_tx": str(event.get("in_tx") or ""),
        "amount_sats": int(event.get("amount_sats") or 0),
        "wallet_utxo": wallet_utxo_ref,
    }


def _events_aus_origin_tree(
    node: dict | None,
    *,
    max_hops: int,
    wallet_utxo_ref: str,
    depth: int = 0,
    events: list | None = None,
    frontiers: list | None = None,
    coinjoins: list | None = None,
) -> tuple[list, list, list]:
    """
    Liest Adress-Hops aus dem Herkunfts-Rohbaum (xpub-blind nutzbar).

    *frontiers*: (txid, vout, next_depth) wo der Baum endet, aber noch
    Hops bis *max_hops* fehlen (typisch externes Blatt).
    *coinjoins*: Soft-Labels aus dem Herkunftsbaum (``tx_class``).
    """
    from core.tx_classify import COINJOIN_KINDS

    if events is None:
        events = []
    if frontiers is None:
        frontiers = []
    if coinjoins is None:
        coinjoins = []
    if not isinstance(node, dict) or depth > max_hops:
        return events, frontiers, coinjoins

    txid = str(node.get("txid") or "").strip()
    try:
        vout = int(node.get("vout", 0))
    except (TypeError, ValueError):
        vout = 0
    utxo_k = f"{txid}:{vout}" if txid else ""
    amount = int(node.get("amount_sats") or 0)

    kind = str(node.get("tx_class") or "").strip()
    if kind in COINJOIN_KINDS and txid:
        cj = _sanction_coinjoin_eintrag(
            None,
            hop=depth,
            txid=txid,
            wallet_utxo_ref=wallet_utxo_ref,
            kind=kind,
        )
        if cj is not None:
            # Zeit aus dem Herkunftsknoten, falls Form-Label ohne get_tx.
            if node.get("time_ts") is not None and not cj.get("time_ts"):
                try:
                    cj["time_ts"] = int(node["time_ts"])
                except (TypeError, ValueError):
                    pass
            if node.get("time") and not cj.get("time"):
                cj["time"] = str(node.get("time") or "")
            if node.get("tx_class_label"):
                cj["label"] = str(node["tx_class_label"])
            if node.get("tx_class_label_en"):
                cj["label_en"] = str(node["tx_class_label_en"])
            coinjoins.append(cj)

    for addr in node.get("addresses") or []:
        if not addr:
            continue
        events.append({
            "hop": depth,
            "address": addr,
            "from_utxo": utxo_k or wallet_utxo_ref,
            "in_tx": txid,
            "amount_sats": amount,
        })

    if node.get("tax_horizon"):
        # Teilbaum: tiefer nur per get_tx
        if depth < max_hops and txid:
            frontiers.append((txid, vout, depth + 1))
        return events, frontiers, coinjoins

    quellen = node.get("sources") or []
    if not quellen:
        if depth < max_hops and txid and depth > 0:
            # Unvollständiger Knoten — Finanzierung unbekannt
            frontiers.append((txid, vout, depth + 1))
        return events, frontiers, coinjoins

    for src in quellen:
        if not isinstance(src, dict):
            continue
        typ = src.get("type")
        hop = depth + 1
        if hop > max_hops:
            continue
        if typ == "coinbase":
            continue
        if typ == "external_unresolved":
            continue
        addr = str(src.get("address") or "").strip()
        from_utxo = str(src.get("from_utxo") or "")
        amt = int(src.get("amount_sats") or 0)
        if addr:
            events.append({
                "hop": hop,
                "address": addr,
                "from_utxo": from_utxo,
                "in_tx": txid,
                "amount_sats": amt,
            })
        if typ == "internal" and isinstance(src.get("trace"), dict):
            _events_aus_origin_tree(
                src["trace"],
                max_hops=max_hops,
                wallet_utxo_ref=wallet_utxo_ref,
                depth=hop,
                events=events,
                frontiers=frontiers,
                coinjoins=coinjoins,
            )
        elif typ == "external" and hop < max_hops and ":" in from_utxo:
            # Externes Blatt: tiefer nur per Chain-Walk
            try:
                pt, _, pv = from_utxo.rpartition(":")
                frontiers.append((pt, int(pv), hop + 1))
            except ValueError:
                pass
        elif typ == "external" and hop < max_hops and src.get("txid") is not None:
            try:
                frontiers.append(
                    (str(src["txid"]), int(src.get("vout", 0)), hop + 1)
                )
            except (TypeError, ValueError):
                pass
    return events, frontiers, coinjoins


def _sammle_sanction_events_live(
    get_tx,
    txid: str,
    vout_index: int,
    utxo: dict,
    *,
    max_hops: int,
    wallet_utxo_ref: str,
    start_depth: int = 1,
    visited: set | None = None,
    cancel_cb=None,
) -> tuple[list[dict], list[dict]]:
    """
    xpub-blinder Hop-Walk → Event- und CoinJoin-Liste
    (get_tx füllt den Tx-Immutable-Cache).

    *start_depth*: 1 = Inputs der UTXO-Tx; >1 = Fortsetzung an einem Frontier.
    CoinJoin-Hop = Hop der Tx-Ausgabe Richtung Wallet-UTXO (0 = UTXO-Tx).
    *cancel_cb*: bei True Abbruch (Cancelled) — auch mitten im Hop-Walk.
    """
    from core.jobs import Cancelled

    events: list[dict] = []
    coinjoins: list[dict] = []
    if visited is None:
        visited = set()

    def _abbruch() -> None:
        if cancel_cb and cancel_cb():
            raise Cancelled()

    if start_depth <= 1:
        _abbruch()
        hop0: list[str] = []
        raw = str(utxo.get("address") or "").strip()
        if raw:
            hop0.append(raw)
        amount0 = int(utxo.get("value") or utxo.get("value_sats") or 0)
        tx0 = None
        try:
            tx0 = get_tx(txid)
            outs = tx0.get("vout") or []
            if 0 <= vout_index < len(outs):
                for a in _main()._extract_addresses(outs[vout_index]):
                    if a and a not in hop0:
                        hop0.append(a)
                try:
                    amount0 = int(_main()._extract_value_sats(outs[vout_index]))
                except Exception:
                    pass
        except Cancelled:
            raise
        except Exception:
            tx0 = None
        for a in hop0:
            events.append({
                "hop": 0,
                "address": a,
                "from_utxo": wallet_utxo_ref,
                "in_tx": txid,
                "amount_sats": amount0,
            })
        if tx0 is not None:
            cj0 = _sanction_coinjoin_eintrag(
                tx0, hop=0, txid=txid, wallet_utxo_ref=wallet_utxo_ref,
            )
            if cj0 is not None:
                coinjoins.append(cj0)

    def _walk(creator_txid: str, depth: int) -> None:
        _abbruch()
        if depth > max_hops:
            return
        key = f"{creator_txid}:walk"
        # creator-weit: Inputs einer Tx nur einmal (vout irrelevant für vin)
        if key in visited:
            return
        visited.add(key)
        try:
            # Tx laden (auch für CJ-Form); iter_funding_inputs lädt ggf. nochmal
            # aus Cache.
            try:
                _abbruch()
                tx = get_tx(creator_txid)
            except Cancelled:
                raise
            except Exception:
                tx = None
            # Hop der Ausgabe dieser Tx Richtung Wallet = depth-1 (depth≥1).
            # UTXO-Tx (start_depth≤1, depth=1, dieselbe txid) schon bei Hop 0.
            schon_hop0 = (
                start_depth <= 1 and depth == 1 and creator_txid == txid
            )
            if tx is not None and not schon_hop0:
                cj = _sanction_coinjoin_eintrag(
                    tx,
                    hop=max(0, int(depth) - 1),
                    txid=creator_txid,
                    wallet_utxo_ref=wallet_utxo_ref,
                )
                if cj is not None:
                    coinjoins.append(cj)

            for inp in iter_funding_inputs(get_tx, creator_txid):
                _abbruch()
                if isinstance(inp, CoinbaseFunding):
                    continue
                edge: FundingEdge = inp
                prev_ref = edge.prevout.key
                for addr in edge.addresses:
                    if not addr:
                        continue
                    events.append({
                        "hop": depth,
                        "address": addr,
                        "from_utxo": prev_ref,
                        "in_tx": creator_txid,
                        "amount_sats": edge.amount_sats,
                    })
                if depth < max_hops:
                    _walk(edge.prevout.txid, depth + 1)
        except Cancelled:
            raise
        except Exception:
            return

    _walk(txid, max(1, int(start_depth)))
    return events, coinjoins


def _pruefe_ein_utxo(
    get_tx,
    utxo: dict,
    own_addresses: set | None,
    sanctioned_addresses: frozenset[str],
    *,
    max_hops: int,
    wallet: WalletContext | None,
    abort_on_hit: bool,
    progress,
    immutable_cache_dir: Path | None = None,
    cancel_cb=None,
) -> tuple[str, list[dict], set[str], list[dict]] | None:
    """
    Ein UTXO prüfen. Rückgabe: (ref, treffer, gesehene Adressen, coinjoins)
    oder None.

    Cache-Reihenfolge:
    1. ``sanction_walk`` (Graph) → aktuelle Liste matchen
    2. Herkunfts-``origin_tree`` + ggf. Live-Lücken (get_tx / Tx-Cache)
    3. Live-Walk ab Root; Ergebnis als sanction_walk speichern

    Hop 0 = UTXO-Adresse; danach xpub-blind bis *max_hops*.
    CoinJoins: Form-Heuristik je Tx im Fenster (Soft-Label).
    """
    del own_addresses, wallet
    from core import trace_cache
    from core.jobs import Cancelled

    txid = str(utxo.get("txid", "")).strip()
    vout = utxo.get("vout")
    if not txid or vout is None:
        return None
    try:
        vout_index = int(vout)
    except (TypeError, ValueError):
        return None

    ref = f"{txid}:{vout_index}"
    treffer: list[dict] = []
    gesehen: set[str] = set()
    coinjoins: list[dict] = []
    counters = {"addrs_checked": 0}

    def _abbruch() -> None:
        if cancel_cb and cancel_cb():
            raise Cancelled()

    # UI nicht bei jedem Address-Match fluten (große Origin-Bäume).
    _last_prog = {"hop": -1, "n": 0, "t": 0.0}

    def _fortschritt(hop: int, *, force: bool = False) -> None:
        if progress is None:
            return
        import time as _time

        n = counters["addrs_checked"]
        jetzt = _time.monotonic()
        hop_i = min(int(hop), max_hops)
        if not force and hop_i == _last_prog["hop"] and n - _last_prog["n"] < 25:
            if jetzt - _last_prog["t"] < 0.4:
                return
        _last_prog["hop"] = hop_i
        _last_prog["n"] = n
        _last_prog["t"] = jetzt
        progress.update(
            wallet_utxo=ref,
            hop=hop_i,
            max_hops=max_hops,
            addrs_checked=n,
            status=_sanction_progress_status(treffer),
        )

    gematcht: set[tuple] = set()

    def _match_events(events: list) -> None:
        for ev in events:
            _abbruch()
            hop = int(ev.get("hop") or 0)
            if hop > max_hops:
                continue
            addr = str(ev.get("address") or "").strip()
            if not addr:
                continue
            schluessel = (
                hop,
                addr,
                str(ev.get("from_utxo") or ""),
                str(ev.get("in_tx") or ""),
            )
            if schluessel in gematcht:
                continue
            gematcht.add(schluessel)
            counters["addrs_checked"] += 1
            gesehen.add(addr)
            _fortschritt(hop)
            hit = _event_gegen_liste(
                ev, sanctioned_addresses, wallet_utxo_ref=ref,
            )
            if hit:
                treffer.append(hit)
                _fortschritt(hop, force=True)
                if abort_on_hit:
                    raise SanctionHitFound(hit)

    _abbruch()
    # Sofort Hop 0 aus dem UTXO melden — sonst bleibt die UI bei
    # „0 Adressen“ stehen, während Frontiers noch get_tx machen.
    hop0_addr = str(utxo.get("address") or "").strip()
    if hop0_addr:
        _match_events([{
            "hop": 0,
            "address": hop0_addr,
            "from_utxo": ref,
            "in_tx": txid,
            "amount_sats": int(utxo.get("value") or utxo.get("value_sats") or 0),
        }])
    elif progress is not None:
        _fortschritt(0)

    # 1) Fertiger Sanktions-Walk
    walk = (
        trace_cache.sanction_walk_laden(txid, vout_index, immutable_cache_dir)
        if immutable_cache_dir
        else None
    )
    if (
        walk
        and walk.get("complete")
        and int(walk.get("max_hops") or 0) >= max_hops
    ):
        _match_events(walk.get("events") or [])
        coinjoins = [
            c for c in (walk.get("coinjoins") or [])
            if int(c.get("hop") or 0) <= max_hops
        ]
        return ref, treffer, gesehen, coinjoins

    # 2+3) origin_tree und/oder Live-Walk → Event-Liste aufbauen
    events: list[dict] = []
    origin = (
        trace_cache.origin_tree_laden(txid, vout_index, immutable_cache_dir)
        if immutable_cache_dir
        else None
    )
    frontiers: list[tuple[str, int, int]] = []
    if origin:
        events, frontiers, coinjoins = _events_aus_origin_tree(
            origin,
            max_hops=max_hops,
            wallet_utxo_ref=ref,
        )
        # Bekannte Origin-Events sofort matchen — nicht erst nach Live-Lücken.
        _match_events(events)

    live_complete = True
    if not origin or frontiers:
        visited: set = set()
        if not origin:
            events, coinjoins = _sammle_sanction_events_live(
                get_tx,
                txid,
                vout_index,
                utxo,
                max_hops=max_hops,
                wallet_utxo_ref=ref,
                start_depth=1,
                visited=visited,
                cancel_cb=cancel_cb,
            )
            _match_events(events)
        else:
            # Lücken hinter externen Blättern nachziehen — je Frontier
            # matchen, damit Fortschritt/Abbruch nicht bis zum Schluss warten.
            for i, (f_txid, f_vout, f_depth) in enumerate(frontiers):
                _abbruch()
                if f_depth > max_hops:
                    continue
                if progress is not None:
                    progress.update(
                        wallet_utxo=ref,
                        hop=min(f_depth, max_hops),
                        max_hops=max_hops,
                        addrs_checked=counters["addrs_checked"],
                        status=(
                            f"{_sanction_progress_status(treffer)}"
                            f" · Lücke {i + 1}/{len(frontiers)}"
                        ),
                    )
                try:
                    extra, extra_cj = _sammle_sanction_events_live(
                        get_tx,
                        f_txid,
                        f_vout,
                        {"address": "", "value": 0},
                        max_hops=max_hops,
                        wallet_utxo_ref=ref,
                        start_depth=f_depth,
                        visited=visited,
                        cancel_cb=cancel_cb,
                    )
                except Exception as exc:
                    from core.jobs import ist_abbruch

                    if ist_abbruch(exc):
                        live_complete = False
                        raise
                    # Einzelne Frontier-Tx nicht erreichbar: weiter, Walk unvollständig.
                    live_complete = False
                    continue
                events.extend(extra)
                coinjoins.extend(extra_cj)
                _match_events(extra)

    coinjoins = _coinjoins_zusammenfuehren(coinjoins)

    if immutable_cache_dir and events:
        # Dedup Events (gleiche hop/address/from_utxo)
        gesehen_k: set[tuple] = set()
        unique: list[dict] = []
        for ev in events:
            k = (
                int(ev.get("hop") or 0),
                str(ev.get("address") or ""),
                str(ev.get("from_utxo") or ""),
                str(ev.get("in_tx") or ""),
            )
            if k in gesehen_k:
                continue
            gesehen_k.add(k)
            unique.append(ev)
        # Nur als complete speichern, wenn alle Frontiers gezogen wurden.
        trace_cache.sanction_walk_speichern(
            txid,
            vout_index,
            max_hops=max_hops,
            complete=live_complete and (not frontiers or origin is not None),
            events=unique,
            coinjoins=coinjoins,
            immutable_cache_dir=immutable_cache_dir,
        )

    return ref, treffer, gesehen, coinjoins


def _check_wallet_utxos_parallel(
    get_tx_je_worker,
    utxos: list[dict],
    own_addresses: set | None,
    sanctioned_addresses: frozenset[str],
    *,
    max_hops: int,
    wallet: WalletContext | None,
    worker_count: int,
    progress_cb,
    cancel_cb,
    gesehene_adressen: set[str] | None,
    immutable_cache_dir: Path | None = None,
) -> tuple[list[dict], int, dict | None]:
    """
    Verteilt die UTXOs auf mehrere Verbindungen — je Worker eine eigene.

    Ein Fulcrum-Client ist eine einzelne Socket-Verbindung und verträgt
    keine parallelen Anfragen; deshalb bekommt jeder Worker seinen eigenen
    (``pool.client_at``). Abbruch bei Treffer gibt es hier nicht: Der
    Web-Lauf will die vollständige Liste, und ein früher Ausstieg wäre bei
    laufenden Threads ohnehin nur ungefähr.
    """
    import queue
    import threading
    from concurrent.futures import ThreadPoolExecutor

    arbeit: queue.Queue = queue.Queue()
    for utxo in utxos:
        arbeit.put(utxo)

    sperre = threading.Lock()
    melde_sperre = threading.Lock()
    alle_treffer: list[dict] = []
    alle_coinjoins: list[dict] = []
    geprueft = 0
    fortschritt = (
        _FortschrittsAdapter(progress_cb, melde_sperre)
        if progress_cb is not None else None
    )

    def abbruch_gewuenscht() -> bool:
        return bool(cancel_cb and cancel_cb())

    def worker(worker_id: int) -> None:
        nonlocal geprueft
        from core.jobs import Cancelled

        roh_get_tx = get_tx_je_worker(worker_id)

        def get_tx(txid: str):
            if abbruch_gewuenscht():
                raise Cancelled()
            return roh_get_tx(txid)

        while not abbruch_gewuenscht():
            try:
                utxo = arbeit.get_nowait()
            except queue.Empty:
                return
            try:
                ergebnis = _pruefe_ein_utxo(
                    get_tx, utxo, own_addresses, sanctioned_addresses,
                    max_hops=max_hops, wallet=wallet, abort_on_hit=False,
                    progress=fortschritt,
                    immutable_cache_dir=immutable_cache_dir,
                    cancel_cb=abbruch_gewuenscht,
                )
            except Cancelled:
                # Restliche Queue leeren — andere Worker sollen auch enden.
                while True:
                    try:
                        arbeit.get_nowait()
                    except queue.Empty:
                        break
                return
            if ergebnis is None:
                continue
            _ref, treffer, gesehen, cjs = ergebnis
            with sperre:
                geprueft += 1
                alle_treffer.extend(treffer)
                alle_coinjoins.extend(cjs)
                if gesehene_adressen is not None:
                    gesehene_adressen.update(gesehen)

    arbeiter = min(worker_count, len(utxos))
    with ThreadPoolExecutor(max_workers=arbeiter) as executor:
        futures = [executor.submit(worker, i) for i in range(arbeiter)]
        for future in futures:
            future.result()

    # Stabile Reihenfolge: Ohne Sortierung hinge sie am Thread-Timing, und
    # zwei Läufe über dieselben Daten lieferten verschiedene Dateien.
    alle_treffer.sort(
        key=lambda t: (t.get("wallet_utxo", ""), t.get("hop", 0),
                       t.get("address", ""))
    )
    return alle_treffer, geprueft, None, _coinjoins_zusammenfuehren(alle_coinjoins)


def check_wallet_utxos_sanctions(
    get_tx,
    utxos: list[dict],
    own_addresses: set | None = None,
    sanctioned_addresses: frozenset[str] | None = None,
    *,
    max_hops: int,
    wallet: WalletContext | None = None,
    abort_on_hit: bool = True,
    progress_cb=None,
    cancel_cb=None,
    gesehene_adressen: set[str] | None = None,
    get_tx_je_worker=None,
    worker_count: int = 1,
    immutable_cache_dir: Path | None = None,
) -> tuple[list[dict], int, dict | None, list[dict]]:
    """
    Prüft Wallet-UTXOs xpub-blind auf sanktionierte Adressen (Drittperspektive).

    Je UTXO: Output-Adresse (Hop 0) plus bis *max_hops* Prevout-Hops rückwärts
    — ohne XPUB-Filter. Grün = keine gelistete Adresse in diesem Fenster.
    Rückgabe: (treffer, geprüfte_utxos, abbruch_treffer|None, coinjoins)

    *coinjoins*: Form-Heuristik (Wasabi/Whirlpool/JoinMarket/…) je Tx im
    Hop-Fenster — Soft-Label „vermutlich …“, keine forensische Sicherheit.

    Cache: ``sanction_walk`` und Herkunfts-``origin_tree`` unter
    *immutable_cache_dir*; Live-``get_tx`` füllt den Tx-Immutable-Cache
    (später Herkunft/Sanktion wiederverwendbar).

    *own_addresses* / *wallet* sind API-kompatibel und werden ignoriert.

    *progress_cb* ist ein Callable[[dict], None] mit Feldern
    (wallet_utxo, hop, max_hops, addrs_checked, status). *cancel_cb* ist ein
    Callable[[], bool] — liefert es True, bricht die Prüfung sauber ab.
    Beides optional; ohne Angabe läuft die CLI-Ausgabe über
    SanctionCheckProgressLine und die Tastatur-Abfrage.

    *gesehene_adressen* wird, wenn übergeben, mit jeder geprüften Adresse
    befüllt — der Aufrufer liest das Set nach dem Lauf aus.

    *get_tx_je_worker* ist ein Callable[[int], get_tx]: Liefert es zusammen
    mit *worker_count* > 1 eine eigene Verbindung je Worker, laufen die
    UTXOs parallel. Ohne das bleibt es beim seriellen Lauf über *get_tx* —
    der Weg, den die CLI mit ihrem Treffer-Abbruch nimmt.
    """
    if sanctioned_addresses is None:
        sanctioned_addresses = frozenset()
    if not utxos or not sanctioned_addresses or max_hops < 1:
        return [], 0, None, []

    if get_tx_je_worker is not None and worker_count > 1 and not abort_on_hit:
        return _check_wallet_utxos_parallel(
            get_tx_je_worker, utxos, own_addresses, sanctioned_addresses,
            max_hops=max_hops, wallet=wallet, worker_count=worker_count,
            progress_cb=progress_cb, cancel_cb=cancel_cb,
            gesehene_adressen=gesehene_adressen,
            immutable_cache_dir=immutable_cache_dir,
        )

    import threading

    from display import SanctionCheckProgressLine

    all_hits: list[dict] = []
    all_coinjoins: list[dict] = []
    checked = 0
    cli_progress = SanctionCheckProgressLine() if progress_cb is None else None
    # Ohne CLI-Zeile meldet der Adapter denselben Zustand an progress_cb —
    # inklusive echter Hop-Tiefe aus scan_external_sanction_hops.
    progress = cli_progress or (
        _FortschrittsAdapter(progress_cb, threading.Lock())
        if progress_cb is not None else None
    )
    abort_hit: dict | None = None

    def abbruch_gewuenscht() -> bool:
        if cancel_cb is not None:
            return cancel_cb()
        return is_list_abort_requested()

    try:
        for utxo in utxos:
            if abbruch_gewuenscht():
                break
            try:
                ergebnis = _pruefe_ein_utxo(
                    get_tx, utxo, own_addresses, sanctioned_addresses,
                    max_hops=max_hops, wallet=wallet,
                    abort_on_hit=abort_on_hit, progress=progress,
                    immutable_cache_dir=immutable_cache_dir,
                    cancel_cb=abbruch_gewuenscht,
                )
            except SanctionHitFound as exc:
                checked += 1
                abort_hit = exc.hit
                break
            except Exception as exc:
                from core.jobs import Cancelled, ist_abbruch

                if ist_abbruch(exc) or isinstance(exc, Cancelled):
                    break
                raise
            if ergebnis is None:
                continue
            _ref, treffer, gesehen, cjs = ergebnis
            checked += 1
            all_hits.extend(treffer)
            all_coinjoins.extend(cjs)
            if gesehene_adressen is not None:
                gesehene_adressen.update(gesehen)
    finally:
        if cli_progress is not None:
            cli_progress.finish()

    return all_hits, checked, abort_hit, _coinjoins_zusammenfuehren(all_coinjoins)


def print_sanction_check_report(
    hits: list[dict],
    *,
    wallet_name: str,
    max_hops: int,
    utxo_count: int,
    sanctioned_count: int,
    aborted: bool = False,
    coinjoins: list[dict] | None = None,
) -> None:
    """Gibt das Ergebnis der Sanktionsprüfung aus."""
    print(f"\n{'═' * 72}")
    print(f"  Sanktionsprüfung: {wallet_name}")
    print(
        f"  {utxo_count} UTXO(s) geprüft, {max_hops} Hop(s) xpub-blind, "
        f"{sanctioned_count:,} Adressen in der Liste"
    )
    if aborted:
        print("  ⚠️  Prüfung nach Treffer abgebrochen")
    print(f"{'═' * 72}")

    if not hits:
        print(
            f"\n  Keine sanktionierte Adresse in den letzten {max_hops} Hop(s)."
        )
    else:
        by_key: dict[tuple, dict] = {}
        for hit in hits:
            key = (hit["hop"], hit["address"], hit["from_utxo"], hit["in_tx"])
            entry = by_key.get(key)
            if entry is None:
                entry = {
                    "hop": hit["hop"],
                    "address": hit["address"],
                    "from_utxo": hit["from_utxo"],
                    "in_tx": hit["in_tx"],
                    "amount_sats": hit["amount_sats"],
                    "wallet_utxos": set(),
                }
                by_key[key] = entry
            entry["wallet_utxos"].add(hit.get("wallet_utxo", ""))

        print(
            f"\n  ⚠️  {len(by_key)} Treffer "
            f"(sanktionierte Adresse in der Hop-Vorgeschichte):\n"
        )
        with cancellable_output(hint="Trefferliste — q zum Abbrechen"):
            for index, entry in enumerate(
                sorted(by_key.values(), key=lambda e: (e["hop"], e["address"])),
                start=1,
            ):
                if is_list_abort_requested():
                    break
                addr = abbrev_display(entry["address"])
                from_utxo = format_utxo_ref(entry["from_utxo"])
                in_tx = abbrev_display(entry["in_tx"])
                wallet_refs = ", ".join(
                    format_utxo_ref(ref)
                    for ref in sorted(entry["wallet_utxos"])
                    if ref
                )
                print(
                    f"  [{index}] Hop {entry['hop']}: {addr} "
                    f"({entry['amount_sats']:,} sats)"
                )
                print(f"       UTXO: {from_utxo}  →  Tx {in_tx}")
                if wallet_refs:
                    print(f"       Betrifft Wallet-UTXO(s): {wallet_refs}")
                print()

    cjs = _coinjoins_zusammenfuehren(list(coinjoins or []))
    if not cjs:
        return
    print("\n  CoinJoins in der geprüften Vorgeschichte:")
    for cj in cjs:
        hop = cj.get("hop", 0)
        when = str(cj.get("time") or "").strip() or "Zeit unbekannt"
        label = str(cj.get("label") or "").strip() or "vermutlich CoinJoin/Mix"
        # „Wahrscheinlich X“ → „vermutlich X“ für den Report-Satz
        if label.lower().startswith("wahrscheinlich "):
            label = "vermutlich " + label[len("Wahrscheinlich "):]
        tid = abbrev_display(str(cj.get("txid") or ""))
        print(f"    Hop {hop} · {when} · {label}" + (f" · Tx {tid}" if tid else ""))
    print()
