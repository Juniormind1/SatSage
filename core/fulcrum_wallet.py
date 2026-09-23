"""Fulcrum wallet helpers: gap/indices scan and UTXO/mempool fetch."""
from __future__ import annotations

import threading

from core.fulcrum_client import (
    TOR_RPC_BATCH_SIZE,
    FulcrumClient,
    _GET_HISTORY_METHOD,
    _LISTUNSPENT_METHOD,
    _is_unknown_method_error,
    address_to_scripthash,
    parallel_ueber_pool,
)


def address_has_received_fulcrum(client: FulcrumClient, address: str) -> bool:
    """True, wenn die Adresse je eine On-Chain-Transaktion hatte."""
    sh = address_to_scripthash(address)
    history = client.request(_GET_HISTORY_METHOD, [sh])
    return bool(history)


def first_seen_height_fulcrum(
    client: FulcrumClient,
    addresses,
    *,
    on_progress=None,
) -> int | None:
    """
    Blockhöhe der ältesten Transaktion über alle genannten Adressen.

    Das ist das Alter eines Wallets. Der UTXO-Cache taugt dafür nicht: Er kennt
    nur Unverbrauchtes, und ein Wallet von 2019, das zwischendurch geleert und
    später neu befüllt wurde, sähe dort jung aus. Die Historie kennt dagegen
    auch längst ausgegebene Eingänge.

    Unbestätigte Transaktionen melden Höhe 0 oder −1 und werden übergangen —
    als „ältestes" gewertet ergäben sie ein Wallet-Alter von heute.

    Eine Adresse, die sich nicht abfragen lässt, wird übersprungen statt das
    ganze Ergebnis zu verwerfen: Ein Datum aus den übrigen ist mehr wert als
    gar keines.
    """
    liste = list(addresses)
    gesamt = len(liste)
    aeltester: int | None = None
    def _history_min_height(history) -> int | None:
        lokal: int | None = None
        for eintrag in history or []:
            try:
                hoehe = int(eintrag.get("height", 0))
            except (TypeError, ValueError):
                continue
            if hoehe <= 0:
                continue
            if lokal is None or hoehe < lokal:
                lokal = hoehe
        return lokal

    # Tor + viele Adressen: get_history bündeln (ein RTT statt N).
    if getattr(client, "tor_batch_sinnvoll", lambda _n: False)(gesamt):
        for start in range(0, gesamt, TOR_RPC_BATCH_SIZE):
            chunk = liste[start : start + TOR_RPC_BATCH_SIZE]
            calls = [
                (_GET_HISTORY_METHOD, [address_to_scripthash(a)])
                for a in chunk
            ]
            try:
                answers = client.request_batch(calls)
            except Exception:
                answers = [None] * len(chunk)
            for offset, history in enumerate(answers):
                try:
                    lokal = _history_min_height(history or [])
                except Exception:
                    lokal = None
                if lokal is not None and (
                    aeltester is None or lokal < aeltester
                ):
                    aeltester = lokal
                nummer = start + offset + 1
                if on_progress and (
                    nummer == 1 or nummer == gesamt or nummer % 10 == 0
                ):
                    on_progress(f"Wallet-Alter: Adresse {nummer} von {gesamt}…")
        return aeltester

    for nummer, address in enumerate(liste, start=1):
        try:
            sh = address_to_scripthash(address)
            history = client.request(_GET_HISTORY_METHOD, [sh]) or []
        except Exception:
            history = []
        lokal = _history_min_height(history)
        if lokal is not None and (aeltester is None or lokal < aeltester):
            aeltester = lokal
        if on_progress and (nummer == 1 or nummer == gesamt or nummer % 10 == 0):
            on_progress(f"Wallet-Alter: Adresse {nummer} von {gesamt}…")
    return aeltester


def first_seen_fulcrum(
    client: FulcrumClient,
    addresses,
    *,
    on_progress=None,
) -> dict | None:
    """
    Wann ein Wallet zum ersten Mal benutzt wurde — Höhe und Blockzeit.

    Liefert ``{"height": …, "time_ts": …}`` oder None, wenn keine der Adressen
    je eine bestätigte Transaktion hatte.

    Bleibt die Blockzeit unauflösbar, wird die Höhe trotzdem gemeldet: Sie ist
    der eigentliche Befund, die Zeit nur ihre Übersetzung.
    """
    hoehe = first_seen_height_fulcrum(
        client, addresses, on_progress=on_progress
    )
    if hoehe is None:
        return None
    from core.fulcrum_history import _block_time_for_height
    return {"height": hoehe, "time_ts": _block_time_for_height(client, hoehe)}


def _adressen_fuer_index(
    derive_address_at_index,
    xpub: str,
    change: int,
    index: int,
) -> list[str]:
    """Eine Adresse oder alle Skript-Varianten (xpub+auto) für Index *index*."""
    roh = derive_address_at_index(xpub, change, index)
    if isinstance(roh, (list, tuple, set)):
        return [a for a in roh if a]
    if roh:
        return [roh]
    return []


def _gap_progress(
    on_progress,
    *,
    kette: str,
    index: int,
    bisher: int,
    utxo_zahl: int,
    batch_n: int = 0,
) -> None:
    if not on_progress:
        return
    name = f"{kette} " if kette else ""
    wort = "UTXO" if bisher == 1 else "UTXOs"
    if utxo_zahl > 0:
        hier = "UTXO" if utxo_zahl == 1 else "UTXOs"
        text = (
            f"Gap-Scan {name}Index #{index} — darin {utxo_zahl} {hier} "
            f"gefunden · bisher {bisher} {wort}"
        )
    else:
        # Nicht „0 gefunden“: das würde den letzten Treffer in der
        # Statuszeile überschreiben und widerspräche dem Log.
        text = f"Gap-Scan {name}Index #{index} · bisher {bisher} {wort}"
        if batch_n > 1:
            text = f"{text} · Batch {batch_n}"
    try:
        on_progress(text, sofort=utxo_zahl > 0)
    except TypeError:
        on_progress(text)


def collect_used_chain_indices_fulcrum(
    client: FulcrumClient,
    xpub: str,
    change: int,
    max_index: int,
    gap_limit: int,
    derive_address_at_index,
    *,
    start_index: int = 0,
    on_progress=None,
    on_utxos_update=None,
    kette: str = "",
) -> tuple[set[int], int]:
    """
    Ermittelt benutzte Indizes einer Chain (change=0/1) per get_history
    mit Gap-Limit-Abbruch. Rückgabe: (used_indices, next_index).

    *on_utxos_update* erhält nach jedem Fund die bisher gefundenen UTXOs
    dieser Chain (voller Zwischenstand), damit die GUI schon während des
    Gap-Scans zeichnen kann.

    Über Tor: ``get_history`` in Fenstern (Batch), Auswertung weiter strikt
    indexweise inkl. Gap-Abbruch — fertige Treffer holen ``listunspent``
    gebündelt nach.
    """
    from display import is_list_abort_requested

    if getattr(client, "tor_batch_sinnvoll", lambda _n: False)(2):
        return _collect_used_chain_indices_tor_batch(
            client,
            xpub,
            change,
            max_index,
            gap_limit,
            derive_address_at_index,
            start_index=start_index,
            on_progress=on_progress,
            on_utxos_update=on_utxos_update,
            kette=kette,
        )

    used: set[int] = set()
    gap = 0
    next_index = start_index
    bisher = 0
    gefunden: list[dict] = []
    for i in range(start_index, max_index):
        if is_list_abort_requested():
            break
        next_index = i + 1
        adressen = _adressen_fuer_index(
            derive_address_at_index, xpub, change, i,
        )
        if not adressen:
            break
        utxo_zahl = 0
        getroffen = False
        for address in adressen:
            if not address_has_received_fulcrum(client, address):
                continue
            getroffen = True
            # Anzahl jetzt, nicht erst im späteren listunspent-Lauf —
            # die History sagt nur „je benutzt“, nicht wie viel noch liegt.
            try:
                addr_utxos = fetch_address_utxos_fulcrum(client, address)
                for utxo in addr_utxos:
                    utxo["address"] = address
                gefunden.extend(addr_utxos)
                utxo_zahl += len(addr_utxos)
            except Exception:
                pass
        if getroffen:
            used.add(i)
            gap = 0
            bisher += utxo_zahl
            if on_utxos_update and utxo_zahl > 0:
                on_utxos_update(list(gefunden))
        else:
            gap += 1
            if gap >= gap_limit:
                break
        _gap_progress(
            on_progress,
            kette=kette,
            index=i,
            bisher=bisher,
            utxo_zahl=utxo_zahl,
        )
    return used, next_index


def _collect_used_chain_indices_tor_batch(
    client: FulcrumClient,
    xpub: str,
    change: int,
    max_index: int,
    gap_limit: int,
    derive_address_at_index,
    *,
    start_index: int = 0,
    on_progress=None,
    on_utxos_update=None,
    kette: str = "",
) -> tuple[set[int], int]:
    """
    Gap-Scan über Tor: get_history-Fenster batchen, Gap in Index-Reihenfolge.

    Fenstergröße min(TOR_RPC_BATCH_SIZE, max(gap_limit, 8)) — nach gap_limit
    leeren Indizes abbrechen, auch mitten im Fenster.
    """
    from display import is_list_abort_requested

    used: set[int] = set()
    gap = 0
    next_index = start_index
    bisher = 0
    gefunden: list[dict] = []
    # Nicht größer als Gap-Limit unnötig vorabfragen (außer etwas Puffer).
    fenster = max(8, min(int(TOR_RPC_BATCH_SIZE), max(int(gap_limit), 8)))
    i = start_index

    while i < max_index:
        if is_list_abort_requested():
            break
        window_end = min(max_index, i + fenster)
        # (index, address) für alle Varianten im Fenster
        eintraege: list[tuple[int, str]] = []
        for idx in range(i, window_end):
            for addr in _adressen_fuer_index(
                derive_address_at_index, xpub, change, idx,
            ):
                eintraege.append((idx, addr))
        if not eintraege:
            break

        calls = [
            (_GET_HISTORY_METHOD, [address_to_scripthash(addr)])
            for _idx, addr in eintraege
        ]
        try:
            answers = client.request_batch(calls)
        except Exception:
            # Batch fehlgeschlagen → Index für Index wie bisher
            answers = []
            for _idx, addr in eintraege:
                try:
                    answers.append(
                        client.request(
                            _GET_HISTORY_METHOD,
                            [address_to_scripthash(addr)],
                        ) or []
                    )
                except Exception:
                    answers.append([])

        # index → [(address, history), ...]
        nach_index: dict[int, list[tuple[str, list]]] = {}
        for (idx, addr), hist in zip(eintraege, answers):
            nach_index.setdefault(idx, []).append((addr, hist or []))

        stop = False
        for idx in range(i, window_end):
            if is_list_abort_requested():
                stop = True
                break
            next_index = idx + 1
            varianten = nach_index.get(idx) or []
            if not varianten:
                stop = True
                break
            hit_addrs = [a for a, h in varianten if h]
            getroffen = bool(hit_addrs)
            utxo_zahl = 0
            if getroffen:
                used.add(idx)
                gap = 0
                # listunspent für Treffer-Adressen bündeln
                try:
                    lu_calls = [
                        (_LISTUNSPENT_METHOD, [address_to_scripthash(a)])
                        for a in hit_addrs
                    ]
                    if len(lu_calls) == 1:
                        lu_answers = [
                            client.request(lu_calls[0][0], lu_calls[0][1]) or []
                        ]
                    else:
                        lu_answers = client.request_batch(lu_calls)
                except RuntimeError as exc:
                    if _is_unknown_method_error(exc, _LISTUNSPENT_METHOD):
                        lu_answers = None
                    else:
                        lu_answers = None
                except Exception:
                    lu_answers = None

                if lu_answers is not None:
                    for address, entries in zip(hit_addrs, lu_answers):
                        try:
                            for utxo in _utxos_from_listunspent_entries(
                                client, entries or [],
                            ):
                                utxo["address"] = address
                                gefunden.append(utxo)
                                utxo_zahl += 1
                        except Exception:
                            try:
                                for utxo in fetch_address_utxos_fulcrum(
                                    client, address,
                                ):
                                    utxo["address"] = address
                                    gefunden.append(utxo)
                                    utxo_zahl += 1
                            except Exception:
                                pass
                else:
                    for address in hit_addrs:
                        try:
                            for utxo in fetch_address_utxos_fulcrum(
                                client, address,
                            ):
                                utxo["address"] = address
                                gefunden.append(utxo)
                                utxo_zahl += 1
                        except Exception:
                            pass
                bisher += utxo_zahl
                if on_utxos_update and utxo_zahl > 0:
                    on_utxos_update(list(gefunden))
            else:
                gap += 1
                if gap >= gap_limit:
                    stop = True
                    _gap_progress(
                        on_progress,
                        kette=kette,
                        index=idx,
                        bisher=bisher,
                        utxo_zahl=0,
                        batch_n=len(eintraege),
                    )
                    break

            _gap_progress(
                on_progress,
                kette=kette,
                index=idx,
                bisher=bisher,
                utxo_zahl=utxo_zahl,
                batch_n=len(eintraege) if not getroffen else 0,
            )
        if stop:
            break
        i = window_end
    return used, next_index


def collect_used_receive_indices_fulcrum(
    client: FulcrumClient,
    xpub: str,
    max_index: int,
    gap_limit: int,
    derive_receive_address_at_index,
) -> set[int]:
    """
    Ermittelt benutzte Empfangs-Indizes per get_history mit Gap-Limit-Abbruch.
    """
    print("  Finde freie Adresse...", end="", flush=True)
    try:
        used, _next_index = collect_used_chain_indices_fulcrum(
            client,
            xpub,
            0,
            max_index,
            gap_limit,
            lambda xp, _change, index: (
                derive_receive_address_at_index(xp, index)[0]
                if derive_receive_address_at_index(xp, index)
                else None
            ),
        )
        print("." * min(len(used), 20), end="", flush=True)
    finally:
        print(flush=True)
    return used


def _utxos_from_listunspent_entries(
    client: FulcrumClient,
    entries: list[dict],
) -> list[dict]:
    from core.fulcrum_history import _block_time_for_height

    utxos: list[dict] = []
    for entry in entries:
        height = int(entry.get("height", 0))
        status: dict[str, object] = {"confirmed": height > 0}
        if height > 0:
            status["block_height"] = height
            block_time = _block_time_for_height(client, height)
            if block_time is not None:
                status["block_time"] = block_time
        utxos.append({
            "txid": entry["tx_hash"],
            "vout": entry["tx_pos"],
            "value": int(entry["value"]),
            "status": status,
        })
    return utxos


def fetch_address_utxos_fulcrum(client: FulcrumClient, address: str) -> list[dict]:
    """Unspent UTXOs einer Adresse (listunspent, Fallback: Tx-Historie)."""
    sh = address_to_scripthash(address)
    try:
        entries = client.request(_LISTUNSPENT_METHOD, [sh]) or []
    except RuntimeError as exc:
        if _is_unknown_method_error(exc, _LISTUNSPENT_METHOD):
            from core.fulcrum_history import _fetch_address_utxos_from_history
            return _fetch_address_utxos_from_history(client, address, sh)
        raise
    return _utxos_from_listunspent_entries(client, entries)


def _spender_map_fuer_outpoints(
    client: FulcrumClient,
    address: str,
    outpoints: set[tuple[str, int]],
) -> dict[tuple[str, int], dict]:
    """
    Findet ausgebende Tx zu bekannten Outpoints über get_history.

    Liefert ``(txid, vout) → {txid, height, pending}``. Nur die History-Einträge
    der einen Adresse — kein Wallet-weiter Scan.
    """
    if not outpoints:
        return {}
    try:
        sh = address_to_scripthash(address)
        history = client.request(
            "blockchain.scripthash.get_history", [sh],
        ) or []
    except Exception:
        return {}

    # Neueste zuerst — Mempool und frische Bestätigungen früh finden.
    def _hoehe(entry: dict) -> int:
        try:
            return int(entry.get("height") or 0)
        except (TypeError, ValueError):
            return 0

    history_sorted = sorted(history, key=_hoehe)
    gefunden: dict[tuple[str, int], dict] = {}
    offen = set(outpoints)

    for entry in reversed(history_sorted):
        if not offen:
            break
        height = _hoehe(entry)
        spend_txid = str(entry.get("tx_hash") or "").strip()
        if not spend_txid:
            continue
        try:
            from core.fulcrum_history import fetch_tx_fulcrum
            tx = fetch_tx_fulcrum(
                client, spend_txid, enrich_block_info=(height > 0),
            )
        except Exception:
            continue
        for vin in tx.get("vin") or []:
            if vin.get("is_coinbase"):
                continue
            prev = str(vin.get("txid") or "").lower()
            if not prev:
                continue
            try:
                prev_vout = int(vin.get("vout", 0))
            except (TypeError, ValueError):
                continue
            key = (prev, prev_vout)
            if key not in offen:
                continue
            status = tx.get("status") or {}
            time_ts = status.get("block_time")
            if time_ts is None and height > 0:
                from core.fulcrum_history import _block_time_for_height
                time_ts = _block_time_for_height(client, height)
            gefunden[key] = {
                "txid": spend_txid.lower(),
                "height": height,
                "pending": height <= 0,
                "time_ts": int(time_ts) if time_ts else None,
            }
            offen.discard(key)
    return gefunden


def finde_mempool_spends_utxos(
    client: FulcrumClient,
    utxos: list[dict],
) -> list[dict]:
    """Nur unconfirmed Spends — Kompatibilität; siehe ``klassifiziere_utxo_spends``."""
    pending, _confirmed, _live = klassifiziere_utxo_spends(client, utxos)
    return pending


def klassifiziere_utxo_spends(
    client: FulcrumClient,
    utxos: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Gezielter Electrs-Check für Cache-UTXOs (eigener Node).

    Rückgabe ``(pending, confirmed_spent, live_auf_betroffenen_adressen)``:

    * **pending** — Mempool-Ausgabe (height ≤ 0)
    * **confirmed_spent** — bestätigte Ausgabe (height > 0), zum Cache-Settle
    * **live_…** — aktuelles ``listunspent`` der betroffenen Adressen
      (inkl. Change), mit ``address`` gesetzt

    Nur Adressen der übergebenen UTXOs — kein Gap, kein Fullscan.
    """
    if not utxos:
        return [], [], []

    nach_addr: dict[str, list[dict]] = {}
    for utxo in utxos:
        addr = (utxo.get("address") or "").strip()
        if not addr:
            continue
        nach_addr.setdefault(addr, []).append(utxo)

    pending: list[dict] = []
    confirmed: list[dict] = []
    live_all: list[dict] = []

    for address, gruppe in nach_addr.items():
        try:
            live = fetch_address_utxos_fulcrum(client, address)
        except Exception:
            continue
        for u in live:
            neu = dict(u)
            neu["address"] = address
            live_all.append(neu)
        live_keys = {
            f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
            for u in live
        }

        fehlt: list[dict] = []
        outpoints: set[tuple[str, int]] = set()
        for utxo in gruppe:
            txid = str(utxo.get("txid") or "").lower()
            try:
                vout = int(utxo.get("vout") or 0)
            except (TypeError, ValueError):
                continue
            if f"{txid}:{vout}" in live_keys:
                continue
            fehlt.append(utxo)
            outpoints.add((txid, vout))

        if not fehlt:
            continue

        spender = _spender_map_fuer_outpoints(client, address, outpoints)
        for utxo in fehlt:
            txid = str(utxo.get("txid") or "").lower()
            try:
                vout = int(utxo.get("vout") or 0)
            except (TypeError, ValueError):
                continue
            info = spender.get((txid, vout))
            if not info:
                continue
            eintrag = dict(utxo)
            eintrag["txid"] = txid
            eintrag["vout"] = vout
            eintrag["address"] = address
            eintrag["spent"] = True
            eintrag["spent_txid"] = info["txid"]
            eintrag["spent_height"] = int(info.get("height") or 0)
            eintrag["spent_time_ts"] = info.get("time_ts")
            if info.get("pending"):
                eintrag["spent_pending"] = True
                pending.append(eintrag)
            else:
                eintrag["spent_pending"] = False
                status = eintrag.setdefault("status", {})
                if eintrag["spent_height"] > 0:
                    status["block_height"] = eintrag["spent_height"]
                    status["confirmed"] = True
                if eintrag.get("spent_time_ts"):
                    status["block_time"] = eintrag["spent_time_ts"]
                confirmed.append(eintrag)

    return pending, confirmed, live_all


def mempool_tx_hat_eigenen_output(
    client: FulcrumClient,
    spent_txid: str,
    is_own_address,
) -> bool:
    """
    True, wenn die Mempool-Spend-Tx mindestens einen Output an eine eigene
    Adresse hat (Change oder Transfer an anderes SatSage-Wallet).
    """
    tid = str(spent_txid or "").strip().lower()
    if not tid or not callable(is_own_address):
        return False
    try:
        from core.fulcrum_history import _vout_addresses, fetch_tx_fulcrum
        tx = fetch_tx_fulcrum(client, tid, enrich_block_info=False)
    except Exception:
        return False
    for vout in tx.get("vout") or []:
        for addr in _vout_addresses(vout):
            try:
                if is_own_address(addr):
                    return True
            except Exception:
                continue
    return False


def eigene_mempool_empfaenge(
    client: FulcrumClient,
    pending_spends: list[dict],
    *,
    is_own_address,
) -> list[dict]:
    """
    Eigene Empfangs-Outputs aus Mempool-Spend-Txs (Selbstüberweisung / Change).

    ``is_own_address(addr) -> bool`` — typisch ``WalletContext.is_own_address``
    (erweiterte Index-Suche, damit Change jenseits der Gap-Limit gefunden wird).
    """
    if not pending_spends or not callable(is_own_address):
        return []

    txids: list[str] = []
    gesehen: set[str] = set()
    for p in pending_spends:
        tid = str(p.get("spent_txid") or "").strip().lower()
        if not tid or tid in gesehen:
            continue
        gesehen.add(tid)
        txids.append(tid)

    empfangen: list[dict] = []
    out_keys: set[str] = set()
    from core.fulcrum_history import _vout_addresses, _vout_value_sats, fetch_tx_fulcrum

    for tid in txids:
        try:
            tx = fetch_tx_fulcrum(client, tid, enrich_block_info=False)
        except Exception:
            continue
        for vout_idx, vout in enumerate(tx.get("vout") or []):
            own_addr = None
            for addr in _vout_addresses(vout):
                try:
                    if is_own_address(addr):
                        own_addr = addr
                        break
                except Exception:
                    continue
            if not own_addr:
                continue
            key = f"{tid}:{int(vout_idx)}"
            if key in out_keys:
                continue
            out_keys.add(key)
            empfangen.append({
                "txid": tid,
                "vout": int(vout_idx),
                "value": _vout_value_sats(vout),
                "address": own_addr,
                "status": {"confirmed": False},
                "receive_pending": True,
            })
    return empfangen



def fetch_wallet_utxos_fulcrum(
    client: FulcrumClient,
    addresses: set[str],
    *,
    pool=None,
    on_progress=None,
    on_utxos_update=None,
) -> list[dict]:
    """
    Lädt unspent UTXOs für alle Wallet-Adressen.

    Mit *pool* laufen die Adressen parallel über mehrere Verbindungen — bei
    einigen hundert Adressen ist das der Unterschied zwischen Minuten und
    Sekunden. Ohne Pool bleibt es beim sequenziellen Weg über die eine
    Verbindung; die Ergebnisse sind in beiden Fällen dieselben.

    *on_utxos_update* erhält den bisherigen Fund-Zwischenstand (voller
    Snapshot), sobald neue UTXOs dazukommen — parallel nur nach jedem
    abgeschlossenen Adress-Batch im Fortschrittstakt.
    """
    from display import is_list_abort_requested

    addr_list = sorted(addresses)
    total = len(addr_list)
    stand: list[dict] = []
    stand_lock = threading.Lock()

    def melde(done: int, gesamt: int) -> None:
        if done % 25 == 0 or done == gesamt:
            print(f"  Fulcrum Adressen {done}/{gesamt}...", flush=True)
        if on_progress:
            on_progress(f"Prüfe Adresse {done} von {gesamt}…")

    def melde_stand(neu: list[dict]) -> None:
        if not on_utxos_update or not neu:
            return
        with stand_lock:
            stand.extend(neu)
            snapshot = list(stand)
        on_utxos_update(snapshot)

    if pool is not None and len(pool) > 1 and total > 1:
        def hole(verbindung, adresse: str) -> list[dict]:
            return [
                dict(utxo, address=adresse)
                for utxo in fetch_address_utxos_fulcrum(verbindung, adresse)
            ]

        def fortschritt(done: int, gesamt: int) -> None:
            melde(done, gesamt)

        gefunden = parallel_ueber_pool(
            pool, addr_list, hole, fortschritt=fortschritt,
        )
        utxos = [utxo for teil in gefunden if teil for utxo in teil]
        if on_utxos_update and utxos:
            on_utxos_update(utxos)
        return utxos

    # Eigener Electrs über Tor: listunspent bündeln (kein Multi-Socket).
    if getattr(client, "tor_batch_sinnvoll", lambda _n: False)(total):
        return _fetch_wallet_utxos_tor_batch(
            client,
            addr_list,
            melde=melde,
            melde_stand=melde_stand,
        )

    utxos: list[dict] = []
    for done, address in enumerate(addr_list, start=1):
        if is_list_abort_requested():
            return utxos
        neu: list[dict] = []
        for utxo in fetch_address_utxos_fulcrum(client, address):
            utxo["address"] = address
            utxos.append(utxo)
            neu.append(utxo)
        if neu:
            melde_stand(neu)
        melde(done, total)
    return utxos


def _fetch_wallet_utxos_tor_batch(
    client: FulcrumClient,
    addr_list: list[str],
    *,
    melde,
    melde_stand,
) -> list[dict]:
    """
    UTXO-Scan über Tor: ``listunspent`` in JSON-RPC-Batches.

    Fallback: Server ohne listunspent → sequenziell History (selten).
    """
    from display import is_list_abort_requested

    total = len(addr_list)
    utxos: list[dict] = []
    listunspent_ok = True

    for start in range(0, total, TOR_RPC_BATCH_SIZE):
        if is_list_abort_requested():
            return utxos
        chunk = addr_list[start : start + TOR_RPC_BATCH_SIZE]
        if not listunspent_ok:
            for offset, address in enumerate(chunk):
                if is_list_abort_requested():
                    return utxos
                neu = []
                for utxo in fetch_address_utxos_fulcrum(client, address):
                    utxo["address"] = address
                    utxos.append(utxo)
                    neu.append(utxo)
                if neu:
                    melde_stand(neu)
                melde(start + offset + 1, total)
            continue

        calls = [
            (_LISTUNSPENT_METHOD, [address_to_scripthash(a)])
            for a in chunk
        ]
        try:
            answers = client.request_batch(calls)
        except RuntimeError as exc:
            if _is_unknown_method_error(exc, _LISTUNSPENT_METHOD):
                listunspent_ok = False
                for offset, address in enumerate(chunk):
                    if is_list_abort_requested():
                        return utxos
                    neu = []
                    for utxo in fetch_address_utxos_fulcrum(client, address):
                        utxo["address"] = address
                        utxos.append(utxo)
                        neu.append(utxo)
                    if neu:
                        melde_stand(neu)
                    melde(start + offset + 1, total)
                continue
            raise

        for offset, (address, entries) in enumerate(zip(chunk, answers)):
            if is_list_abort_requested():
                return utxos
            neu = []
            try:
                for utxo in _utxos_from_listunspent_entries(
                    client, entries or [],
                ):
                    utxo["address"] = address
                    utxos.append(utxo)
                    neu.append(utxo)
            except Exception:
                # Einzeladresse: History-Fallback
                for utxo in fetch_address_utxos_fulcrum(client, address):
                    utxo["address"] = address
                    utxos.append(utxo)
                    neu.append(utxo)
            if neu:
                melde_stand(neu)
            melde(start + offset + 1, total)
    return utxos
