"""Empfang-/Mempool-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports.
"""

from __future__ import annotations

import threading

def _sortierung(query: dict) -> str:
    roh = (query.get("sort") or ["betrag"])[0]
    return roh if roh in ("betrag", "datum") else "betrag"

def _verlaufs_anhang(state: AppState, entries, *, limit: int | None = None,
                     sort: str = "datum") -> dict:
    """
    Ausgegebene Outputs aus dem Verlaufs-Cache — dieselbe Datei, die
    Steuerjahr und Herkunft lesen. Kein Netzzugriff.
    """

    from server import (
        main,
        utxos_mod,
        _eigene_adressen,
    )

    verlauf: list[dict] = []
    for entry in entries:
        gespeichert = main.load_xpub_verlauf_cache(
            entry.analyse_schluessel, state.cache_dir
        )
        if not gespeichert:
            continue
        # Name mitgeben: Sparrow-Tx-CSV-Einträge ohne Adresse sonst
        # „unbekanntes Wallet“, obwohl der Cache klar diesem Wallet gehört.
        name = entry.display_name
        for roh in gespeichert:
            if not isinstance(roh, dict):
                continue
            kopie = dict(roh)
            if name and not kopie.get("_wallet_fallback"):
                kopie["_wallet_fallback"] = name
            verlauf.append(kopie)
    return {
        "verlauf": utxos_mod.historische_eintraege(
            verlauf,
            wallet=state.wallet_ctx,
            immutable_cache_dir=state.immutable_cache_dir,
            own_addresses=_eigene_adressen(state),
            limit=limit,
            sort=sort,
        ),
        "hat_verlauf": bool(verlauf),
    }

def _merke_own_fulcrum_client(state: AppState, client) -> dict | None:
    """
    Eigener Electrum-Connect → sources_last + Job-tauglicher Stand.

    Tip-Sync und Empfang verbinden oft Minuten vor dem 30‑s-Peer-Takt;
    die Kopf-Pille soll dann schon grün mit libbitcoin/electrs/fulcrum sein.
    """

    from server import (
        LOGGER,
        source_mod,
    )

    stand = source_mod.own_fulcrum_stand_from_client(client)
    if not stand:
        return None
    try:
        werte = state.env().values()
        frisch = source_mod.describe_sources(werte)
        state.sources_last = source_mod.merke_own_fulcrum_in_sources(
            getattr(state, "sources_last", None),
            frisch,
            stand,
        )
    except Exception:
        LOGGER.debug("own_fulcrum Stand merken fehlgeschlagen", exc_info=True)
    return stand

def _eigener_fulcrum_client(state: AppState):
    """
    Eigener Electrs/Fulcrum oder None (kein öffentlicher Pool).

    Wiederverwendet eine Verbindung am AppState — sonst kostet jeder
    Empfangs-QR-Klick einen frischen TCP/TLS-Handshake (wirkt wie „Scan“).
    """

    from server import (
        main,
        _merke_own_fulcrum_client,
    )

    werte = state.env().values()
    if not (
        (werte.get("FULCRUM_HOST") or "").strip()
        or (werte.get("FULCRUM_TOR") or "").strip()
    ):
        return None

    lock = getattr(state, "_empfang_fulcrum_lock", None)
    if lock is None:
        lock = threading.Lock()
        state._empfang_fulcrum_lock = lock

    with lock:
        alt = getattr(state, "_empfang_fulcrum", None)
        if alt is not None:
            try:
                alt.request("server.ping")
                _merke_own_fulcrum_client(state, alt)
                return alt
            except Exception:
                try:
                    alt.close()
                except Exception:
                    pass
                state._empfang_fulcrum = None
        try:
            client = main._try_own_fulcrum_client(
                state.args_namespace(), werte,
            )
        except Exception:
            return None
        state._empfang_fulcrum = client
        if client is not None:
            _merke_own_fulcrum_client(state, client)
        return client

def _oeffentlicher_fulcrum_fuer_empfang(state: AppState):
    """
    Öffentlicher Electrum-Pool für Empfangs-History — nur mit Opt-in.

    Ohne ``OEFFENTLICHE_ELECTRUM`` bleibt es bei der Cache-Schätzung
    (keine Adress-Probes an Fremdserver). Mit Opt-in: dieselbe History-Probe
    wie beim eigenen Node; die Adressen sind dem Pool ohnehin schon bekannt,
    sobald Scans darüber laufen.
    """

    from server import (
        main,
        source_mod,
    )

    werte = state.env().values()
    if not source_mod.oeffentliche_electrum_erlaubt(werte):
        return None

    lock = getattr(state, "_empfang_fulcrum_lock", None)
    if lock is None:
        lock = threading.Lock()
        state._empfang_fulcrum_lock = lock

    with lock:
        alt = getattr(state, "_empfang_public_fulcrum", None)
        if alt is not None:
            try:
                alt.request("server.ping")
                return alt
            except Exception:
                try:
                    alt.close()
                except Exception:
                    pass
                state._empfang_public_fulcrum = None
        try:
            args = state.args_namespace()
            pool = main._try_public_onion_fulcrum(
                args, werte, interactive=False,
            )
            if pool is None:
                pool = main._setup_public_clearnet_fulcrum(args, werte)
        except Exception:
            return None
        state._empfang_public_fulcrum = pool
        return pool

def _empfang_electrum_client(state: AppState):
    """
    Electrum für Empfangs-QR: eigener Node, sonst öffentlicher nach Opt-in.
    """

    from server import (
        _eigener_fulcrum_client,
        _oeffentlicher_fulcrum_fuer_empfang,
    )

    eigen = _eigener_fulcrum_client(state)
    if eigen is not None:
        return eigen
    return _oeffentlicher_fulcrum_fuer_empfang(state)

def _adresse_hat_history(client, address: str) -> bool:
    """True wenn Electrs für die Adresse mindestens eine Tx kennt."""
    if not address:
        return False
    from fulcrum import address_to_scripthash

    sh = address_to_scripthash(address)
    hist = client.request("blockchain.scripthash.get_history", [sh]) or []
    return bool(hist)

def _naechste_freie_empfang_electrs(
    state: AppState,
    entry,
    client,
    *,
    max_index: int,
) -> tuple[str, int] | None:
    """
    Nächste freie Empfangsadresse per Electrs — **kein** Fullscan.

    Educated guess aus UTXO-/Verlaufs-Cache (``max bekannter Empfangs-Index + 1``,
    nach Tip-Sync typisch schon korrekt). Dann nur **vorwärts** per
    ``get_history`` prüfen, bis die erste leere Adresse kommt.

    Üblich: **1 RPC**. Wenn der Cache hinter der Chain liegt (Zahlung auf
    höherem Index), wenige weitere Probes — Obergrenze ``BIP44_GAP_LIMIT``,
    kein Walk ab #0 und kein electrs-seitiger Gap-Rescan.
    """

    from server import (
        main,
        _adresse_hat_history,
        _next_receive_index_from_cache,
    )

    gap = int(getattr(main, "BIP44_GAP_LIMIT", 20) or 20)
    skript = (
        None if entry.is_multisig or entry.descriptor else entry.script_type
    )
    xpub = entry.analyse_schluessel
    start = int(
        _next_receive_index_from_cache(state, entry, max_index=max_index)
    )
    if start < 0:
        start = 0
    # Nur vorwärts ab Schätzung — höchstens gap+1 History-Probes.
    limit = min(max_index, start + gap + 1)
    for i in range(start, limit):
        dest = main.derive_receive_address_at_index(
            xpub, i, script_type=skript,
        )
        if not dest or not dest[0]:
            break
        if _adresse_hat_history(client, dest[0]):
            continue
        return str(dest[0]), int(i)
    return None

def _schaerfe_empfang_nach_sync(
    state: AppState,
    eintraege: list,
    *,
    fulcrum=None,
    on_progress=None,
) -> int:
    """
    Einmal nach Tip-Nachzug / UTXO-Scan: Empfangs-QR schärfen.

    * Prozess-Cache leeren, dann pro Wallet **1–wenige** ``get_history`` ab
      Cache-Schätzung (kein Fullscan, siehe ``_naechste_freie_empfang_electrs``).
    * Electrum: eigener Node, oder öffentlicher Pool nach Opt-in
      (``OEFFENTLICHE_ELECTRUM``). Ohne beides: nur Cache leeren.
    """

    from server import (
        main,
        source_mod,
        wallets_mod,
        _empfang_electrum_client,
        _naechste_freie_empfang_electrs,
        _empfang_max_index,
        _next_receive_index_from_cache,
        _empfang_antwort,
        _empfang_gehoert_zu_wallet,
    )

    if not eintraege:
        return 0
    for entry in eintraege:
        try:
            state.empfang_cache.pop(wallets_mod.eintrag_id(entry), None)
        except Exception:
            pass

    client = fulcrum
    if client is not None:
        try:
            if not main.is_own_fulcrum_backend(client):
                # Öffentlicher Pool nur mit Opt-in — sonst keine Adress-Probes.
                if not source_mod.oeffentliche_electrum_erlaubt(
                    state.env().values()
                ):
                    client = None
        except Exception:
            client = None
    if client is None:
        client = _empfang_electrum_client(state)
    if client is None:
        return 0

    from core import wallet_watch

    watch = wallet_watch.wallet_watch_status()
    watch_active = bool(watch.get("running"))
    gap = int(getattr(main, "BIP44_GAP_LIMIT", 20) or 20)
    ok = 0

    def _cache_estimate_merker(entry) -> None:
        """Fallback-QR aus UTXO-Stand, falls Electrs scheitert / Belong-Check nein."""
        kennung = wallets_mod.eintrag_id(entry)
        try:
            max_index = _empfang_max_index(entry, state)
            next_index = _next_receive_index_from_cache(
                state, entry, max_index=max_index,
            )
            skript = (
                None
                if entry.is_multisig or entry.descriptor
                else entry.script_type
            )
            abgeleitet = main.derive_receive_address_at_index(
                entry.analyse_schluessel, next_index, script_type=skript,
            )
            if not abgeleitet or not abgeleitet[0]:
                return
            address, index = str(abgeleitet[0]), int(abgeleitet[1])
            # Belong-Check hier weich: sonst bleibt das Dock leer (500).
            state.empfang_cache[kennung] = _empfang_antwort(
                kennung=kennung,
                entry=entry,
                address=address,
                index=index,
                source="cache_estimate",
                subscribed=False,
                watch_active=watch_active,
                read_only=False,
            )
        except Exception:
            pass

    for entry in eintraege:
        if getattr(entry, "read_only", False) or not entry.is_valid():
            continue
        kennung = wallets_mod.eintrag_id(entry)
        try:
            if on_progress:
                on_progress(
                    f"Empfangsadresse „{entry.display_name}“ per Electrs…",
                    sofort=True,
                )
            max_index = _empfang_max_index(entry, state)
            treffer = _naechste_freie_empfang_electrs(
                state, entry, client, max_index=max_index,
            )
            if not treffer:
                _cache_estimate_merker(entry)
                continue
            address, index = treffer
            if not _empfang_gehoert_zu_wallet(state, entry, address):
                _cache_estimate_merker(entry)
                continue
            skript = (
                None
                if entry.is_multisig or entry.descriptor
                else entry.script_type
            )
            lookahead: list[str] = []
            for i in range(index, min(index + gap + 1, max_index)):
                dest = main.derive_receive_address_at_index(
                    entry.analyse_schluessel, i, script_type=skript,
                )
                if dest and dest[0] and dest[0] not in lookahead:
                    lookahead.append(dest[0])
            subscribed = False
            if watch_active and lookahead:
                subscribed = bool(
                    wallet_watch.subscribe_addresses(
                        lookahead, entry.analyse_schluessel,
                    )
                )
            state.empfang_cache[kennung] = _empfang_antwort(
                kennung=kennung,
                entry=entry,
                address=address,
                index=index,
                source="fulcrum",
                subscribed=subscribed,
                watch_active=watch_active,
                read_only=False,
            )
            ok += 1
        except Exception as exc:
            # Tip/Scan bleibt gültig — Empfang fällt auf Cache-Schätzung zurück.
            if on_progress:
                try:
                    on_progress(
                        f"Empfang „{entry.display_name}“: {exc}",
                        sofort=True,
                    )
                except Exception:
                    pass
            _cache_estimate_merker(entry)
            continue
    return ok

def _verlauf_anhang_fuer_xpub(
    state: AppState,
    xpub: str,
    *,
    limit: int | None,
    sort: str,
) -> dict:

    from server import (
        main,
        utxos_mod,
        _eigene_adressen,
    )

    gespeichert = main.load_xpub_verlauf_cache(xpub, state.cache_dir) or []
    name = ""
    for e in state.entries:
        if e.analyse_schluessel == xpub or e.xpub == xpub:
            name = e.display_name
            break
    if name:
        angereichert = []
        for roh in gespeichert:
            if not isinstance(roh, dict):
                continue
            kopie = dict(roh)
            if not kopie.get("_wallet_fallback"):
                kopie["_wallet_fallback"] = name
            angereichert.append(kopie)
        gespeichert = angereichert
    return {
        "verlauf": utxos_mod.historische_eintraege(
            gespeichert,
            wallet=state.wallet_ctx,
            immutable_cache_dir=state.immutable_cache_dir,
            own_addresses=_eigene_adressen(state),
            limit=limit,
            sort=sort,
        ),
        "hat_verlauf": bool(gespeichert),
    }

def _mit_mempool_pending(
    state: AppState,
    gecacht: list[dict],
    anhang: dict,
    *,
    limit: int | None,
    sort: str,
    xpub: str | None = None,
) -> tuple[list[dict], dict]:
    """
    Eigener Electrs: Pending + bestätigte Spends gezielt.

    * **Pending** (Mempool): UTXO bleibt, „wird gerade ausgegeben“;
      unter ausgegeben als pending.
    * **Bestätigt** (ein XPUB): Cache settlen — UTXO raus, Verlauf spent,
      listunspent der Adresse (Change) — kein Fullscan.

    Mit ``xpub`` (einzelne Wallet-Ansicht) nur diese Wallet prüfen — sonst
    ``listunspent`` über alle Adressen aller Wallets und spürbare Wartezeit
    schon beim Öffnen eines 1-UTXO-Wallets. Querschnitt bleibt bei
    Herkunft ``/api/utxos`` (``xpub is None``).
    """

    from server import (
        main,
        utxos_mod,
        _eigene_adressen,
        _eigener_fulcrum_client,
        _verlauf_anhang_fuer_xpub,
    )

    client = _eigener_fulcrum_client(state)
    if client is None:
        return gecacht, anhang

    pending: list[dict] = []
    confirmed: list[dict] = []
    live: list[dict] = []
    empfaenge: list[dict] = []
    # Verlauf-Pending (nach Light-Prune ohne Mempool-Nachzug): wieder prüfen.
    kandidaten = list(gecacht)
    gesehen_k = {
        f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        for u in kandidaten
    }
    for u in (anhang.get("verlauf") or {}).get("utxos") or []:
        if not u.get("spent_pending"):
            continue
        key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        if key in gesehen_k:
            continue
        gesehen_k.add(key)
        kandidaten.append({
            "txid": u.get("txid"),
            "vout": u.get("vout"),
            "value": u.get("value_sats") or u.get("value") or 0,
            "address": u.get("address"),
            "status": {
                "confirmed": bool(u.get("confirmed")),
                "block_height": u.get("block_height"),
                "block_time": u.get("block_time"),
            },
        })
    ziel_keys = {f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}" for u in kandidaten}
    ziel_adressen = {u.get("address") for u in kandidaten if u.get("address")}
    # Herkunft: alle Wallets in den Electrs-Check. Einzel-Wallet: nicht —
    # die Ergebnisse würden ohnehin auf ziel_keys gefiltert, die Roundtrips
    # kosten aber ~100 ms je Adresse.
    if xpub is None:
        for entry_anderes in state.analyse_entries:
            try:
                cache_anderes = main.load_xpub_cache_entry(entry_anderes.analyse_schluessel, state.cache_dir)
                andere_utxos = (cache_anderes or {}).get("utxos") or []
            except Exception:
                andere_utxos = []
            for u in andere_utxos:
                key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
                if key not in gesehen_k:
                    gesehen_k.add(key)
                    kandidaten.append(u)
            try:
                verlauf_anderes = main.load_xpub_verlauf_cache(entry_anderes.analyse_schluessel, state.cache_dir) or []
            except Exception:
                verlauf_anderes = []
            for e in verlauf_anderes:
                if not e.get("spent_pending"):
                    continue
                key = f"{str(e.get('txid') or '').lower()}:{int(e.get('vout') or 0)}"
                if key in gesehen_k:
                    continue
                gesehen_k.add(key)
                kandidaten.append({"txid": e.get("txid"), "vout": e.get("vout"), "value": int(e.get("value") or 0), "address": e.get("address"), "status": e.get("status") or {}})
    try:
        from fulcrum import (
            eigene_mempool_empfaenge,
            klassifiziere_utxo_spends,
            mempool_tx_hat_eigenen_output,
        )

        alle_pending, alle_confirmed, alle_live = klassifiziere_utxo_spends(client, kandidaten)
        pending = [p for p in alle_pending if not xpub or f"{str(p.get('txid') or '').lower()}:{int(p.get('vout') or 0)}" in ziel_keys]
        confirmed = [c for c in alle_confirmed if not xpub or f"{str(c.get('txid') or '').lower()}:{int(c.get('vout') or 0)}" in ziel_keys]
        live = [u for u in alle_live if not xpub or u.get("address") in ziel_adressen]
        # Intern = Output an irgendein SatSage-Wallet (nicht nur Change desselben).
        intern_tx: set[str] = set()
        if alle_pending and state.wallet_ctx is not None:
            try:
                if xpub:
                    ziel_name = state.wallet_ctx.xpub_label(xpub)
                    def _empfang_gehort(addr: str) -> bool:
                        return state.wallet_ctx.resolve_address(addr) == ziel_name
                else:
                    _empfang_gehort = state.wallet_ctx.is_own_address
                empfaenge = eigene_mempool_empfaenge(
                    client, alle_pending, is_own_address=_empfang_gehort,
                )
            except Exception:
                empfaenge = []
            try:
                is_own = state.wallet_ctx.is_own_address
                gesehen_tx: set[str] = set()
                for p in alle_pending:
                    tid = str(p.get("spent_txid") or "").strip().lower()
                    if not tid or tid in gesehen_tx:
                        continue
                    gesehen_tx.add(tid)
                    if mempool_tx_hat_eigenen_output(client, tid, is_own):
                        intern_tx.add(tid)
            except Exception:
                intern_tx = set()
    except Exception:
        return gecacht, anhang
    else:
        # Settle bevor close — Electrs-Tip für scan_tip_height noch erreichbar.
        if confirmed and xpub:
            try:
                neu = main.settle_gezielte_spends_im_cache(
                    xpub,
                    state.cache_dir,
                    confirmed_spent=confirmed,
                    live_auf_adressen=live,
                    source="fulcrum",
                    fulcrum=client,
                )
                if neu is not None:
                    gecacht = neu
                anhang = _verlauf_anhang_fuer_xpub(
                    state, xpub, limit=limit, sort=sort,
                )
            except Exception:
                conf_keys = {
                    f"{str(c.get('txid') or '').lower()}:"
                    f"{int(c.get('vout') or 0)}"
                    for c in confirmed
                }
                gecacht = [
                    u for u in gecacht
                    if f"{str(u.get('txid') or '').lower()}:"
                    f"{int(u.get('vout') or 0)}" not in conf_keys
                ]
                anhang = utxos_mod.merge_pending_spends_in_verlauf(
                    anhang,
                    [{**c, "spent_pending": False} for c in confirmed],
                    wallet=state.wallet_ctx,
                    immutable_cache_dir=state.immutable_cache_dir,
                    own_addresses=_eigene_adressen(state),
                    limit=limit,
                    sort=sort,
                )
        elif confirmed:
            # Kein XPUB: nur aus der Anzeige streichen, kein Cache-Settle.
            conf_keys = {
                f"{str(c.get('txid') or '').lower()}:{int(c.get('vout') or 0)}"
                for c in confirmed
            }
            gecacht = [
                u for u in gecacht
                if f"{str(u.get('txid') or '').lower()}:"
                f"{int(u.get('vout') or 0)}" not in conf_keys
            ]
            anhang = utxos_mod.merge_pending_spends_in_verlauf(
                anhang,
                [{**c, "spent_pending": False} for c in confirmed],
                wallet=state.wallet_ctx,
                immutable_cache_dir=state.immutable_cache_dir,
                own_addresses=_eigene_adressen(state),
                limit=limit,
                sort=sort,
            )
    finally:
        try:
            client.close()
        except Exception:
            pass

    # Auch ohne aktuelle Pending/Confirmed: Cache-Flags bereinigen
    # (Electrs erreichbar, klassifiziere lief durch). Bestätigte Spends
    # sind oben im try/else bereits gesettled.

    # --- Pending: markieren + ausgegeben + eigene Empfänge (Change/Self) ---
    by_key = {
        f"{str(p.get('txid') or '').lower()}:{int(p.get('vout') or 0)}": p
        for p in pending
    }
    empf_keys = {
        f"{str(e.get('txid') or '').lower()}:{int(e.get('vout') or 0)}"
        for e in empfaenge
    }
    markiert: list[dict] = []
    gesehen: set[str] = set()
    for u in gecacht:
        key = f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        gesehen.add(key)
        p = by_key.get(key)
        if p is None:
            # Veralteter Mempool-Empfang (Tx weg / ersetzt durch frische Liste)
            if u.get("receive_pending") and key not in empf_keys:
                status = u.get("status") or {}
                if not status.get("confirmed") and not status.get("block_height"):
                    continue
            neu = dict(u)
            if neu.get("spending_pending"):
                neu.pop("spending_pending", None)
                neu.pop("spent_txid", None)
            if neu.get("receive_pending") and (
                (neu.get("status") or {}).get("confirmed")
                or (neu.get("status") or {}).get("block_height")
            ):
                neu.pop("receive_pending", None)
            markiert.append(neu)
            continue
        neu = dict(u)
        neu["spending_pending"] = True
        neu["spent_txid"] = p.get("spent_txid") or ""
        stid = str(neu.get("spent_txid") or "").strip().lower()
        if stid and stid in intern_tx:
            neu["spending_internal"] = True
        markiert.append(neu)

    # Pending-Spends, die Light-Tip schon aus dem Cache genommen hat, wieder zeigen.
    for p in pending:
        key = f"{str(p.get('txid') or '').lower()}:{int(p.get('vout') or 0)}"
        if key in gesehen:
            continue
        gesehen.add(key)
        neu = dict(p)
        neu["spending_pending"] = True
        neu.pop("spent", None)
        neu.pop("spent_pending", None)
        stid = str(neu.get("spent_txid") or "").strip().lower()
        if stid and stid in intern_tx:
            neu["spending_internal"] = True
        markiert.append(neu)

    # Selbstüberweisung/Change: unbestätigte eigenen Outputs in den Bestand.
    for e in empfaenge:
        key = f"{str(e.get('txid') or '').lower()}:{int(e.get('vout') or 0)}"
        if key in gesehen:
            continue
        gesehen.add(key)
        markiert.append(dict(e))

    if pending:
        anhang = utxos_mod.merge_pending_spends_in_verlauf(
            anhang,
            pending,
            wallet=state.wallet_ctx,
            immutable_cache_dir=state.immutable_cache_dir,
            own_addresses=_eigene_adressen(state),
            limit=limit,
            sort=sort,
        )
    return markiert, anhang

def _query_flag(query: dict, name: str, *, default: bool = True) -> bool:
    """Query-Flag: fehlt → default; 0/false/off/no → aus, sonst an."""
    roh = (query.get(name) or [None])[0]
    if roh is None or str(roh).strip() == "":
        return default
    return str(roh).strip().lower() not in ("0", "false", "no", "off")

def _empfang_max_index(entry: WalletEntry, state: AppState | None = None) -> int:
    """
    Obergrenze Empfangs-Indizes.

    Basis: Scan-Tiefe/2 (Receive-Kette). Liegt ``scan_end_index`` höher
    (Tip/Fullscan hat weiter gelaufen), die Grenze mitziehen — sonst bleibt
    die „nächste“ Adresse künstlich bei max−1 und Electrs-Schärfung scheitert.
    """

    from server import (
        main,
        _cache_bekannt_adressen,
    )

    try:
        tief = int(entry.max_addresses or 0)
    except (TypeError, ValueError):
        tief = 0
    if tief >= 2:
        basis = max(1, tief // 2)
    else:
        basis = main.MAX_TRACE_ADDRESS_SEARCH
    if state is not None:
        try:
            _, scan_end = _cache_bekannt_adressen(state, entry)
            gap = int(getattr(main, "BIP44_GAP_LIMIT", 20) or 20)
            if scan_end > 0:
                basis = max(basis, int(scan_end) + gap + 1)
        except Exception:
            pass
    return max(1, basis)

def _cache_bekannt_adressen(
    state: AppState,
    entry: WalletEntry,
) -> tuple[set[str], int]:
    """Adressen aus UTXO-/Verlaufs-Cache plus ``scan_end_index``."""

    from server import main

    xpub = entry.analyse_schluessel
    bekannt: set[str] = set()
    scan_end = 0
    eintrag = main.load_xpub_cache_entry(xpub, state.cache_dir)
    if eintrag:
        for u in eintrag.get("utxos") or []:
            addr = u.get("address")
            if addr:
                bekannt.add(str(addr))
        roh = eintrag.get("raw") or {}
        for addr in roh.get("scanned_addresses") or []:
            if addr:
                bekannt.add(str(addr))
        try:
            scan_end = int(eintrag.get("scan_end_index") or 0)
        except (TypeError, ValueError):
            scan_end = 0
    for e in main.load_xpub_verlauf_cache(xpub, state.cache_dir) or []:
        addr = e.get("address")
        if addr:
            bekannt.add(str(addr))
    return bekannt, scan_end

def _next_receive_index_from_cache(
    state: AppState,
    entry: WalletEntry,
    *,
    max_index: int,
) -> int:
    """
    Nächste Empfangs-Index-Schätzung: ``max(bekannter Empfangs-Index) + 1``.

    Kein BIP44-Gap ab 0 (der oft fälschlich #0 lieferte, wenn ``scan_end``
    klein war und hohe Indizes gar nicht gematcht wurden). Mit Electrs
    kann die API später nachschärfen — die Cache-Schätzung soll sofort
    und hinter dem höchsten bekannten Empfang liegen.
    """

    from server import (
        main,
        _cache_bekannt_adressen,
    )

    bekannt, scan_end = _cache_bekannt_adressen(state, entry)
    if not bekannt and scan_end <= 0:
        return 0

    xpub = entry.analyse_schluessel
    skript = None if entry.is_multisig or entry.descriptor else entry.script_type
    # Volle Scan-Tiefe matchen — nicht nur scan_end+Gap (sonst #0-Falle).
    limit = max(1, min(max_index, max(scan_end + main.BIP44_GAP_LIMIT, max_index)))
    index_fuer: dict[str, int] = {}
    for i in range(limit):
        dest = main.derive_receive_address_at_index(xpub, i, script_type=skript)
        if dest and dest[0]:
            index_fuer[str(dest[0])] = i
        # auto/xpub: zusätzlich alle Skriptformen, falls Cache-Adressen anders typisiert
        if skript in (None, "", "auto") and not entry.descriptor:
            for addr in main.derive_addresses_at_index(xpub, 0, i) or []:
                index_fuer.setdefault(str(addr), i)

    max_used = -1
    for addr in bekannt:
        idx = index_fuer.get(addr)
        if idx is not None:
            max_used = max(max_used, idx)

    if max_used < 0 and bekannt and scan_end > 0:
        # Adressen da, Index-Match fehlgeschlagen — Scan-Ende als Untergrenze.
        return min(scan_end, max_index - 1) if max_index > 0 else 0

    next_index = max_used + 1
    if next_index >= max_index:
        return max(0, max_index - 1)
    return next_index

def _empfang_gehoert_zu_wallet(
    state: AppState,
    entry: WalletEntry,
    address: str,
) -> bool:
    """Belong-Check: Adresse gehört zu diesem Wallet (kein XPUB in der Antwort)."""
    if not address:
        return False
    ctx = state.wallet_ctx
    if ctx is None:
        return True
    xpub = entry.analyse_schluessel
    bekannt = ctx.xpub_for_address(address)
    if bekannt is not None:
        return bekannt == xpub
    label = ctx.resolve_address(address)
    if label is None:
        return False
    return label == entry.display_name or ctx.xpub_for_address(address) == xpub

def _empfang_antwort(
    *,
    kennung: str,
    entry: WalletEntry,
    address: str,
    index: int,
    source: str,
    subscribed: bool,
    watch_active: bool,
    read_only: bool = False,
) -> dict:
    return {
        "wallet_id": kennung,
        "wallet_name": entry.display_name,
        "address": address,
        "index": index,
        "change": 0,
        "source": source,
        "subscribed": subscribed,
        "watch_active": watch_active,
        "read_only": bool(read_only),
    }

def _empfang_finalize(
    state: AppState,
    entry: WalletEntry,
    *,
    kennung: str,
    address: str,
    index: int,
    source: str,
    max_index: int,
) -> dict:
    """Subscribe Gap + Prozess-Cache + Antwort (ohne XPUB)."""

    from server import (
        main,
        _empfang_antwort,
    )

    xpub = entry.analyse_schluessel
    skript = None if entry.is_multisig or entry.descriptor else entry.script_type
    gap = int(getattr(main, "BIP44_GAP_LIMIT", 20) or 20)
    lookahead: list[str] = []
    for i in range(index, min(index + gap + 1, max_index)):
        dest = main.derive_receive_address_at_index(
            xpub, i, script_type=skript,
        )
        if dest and dest[0] and dest[0] not in lookahead:
            lookahead.append(dest[0])

    from core import wallet_watch

    watch = wallet_watch.wallet_watch_status()
    watch_active = bool(watch.get("running"))
    subscribed = False
    if watch_active and lookahead:
        subscribed = bool(
            wallet_watch.subscribe_addresses(lookahead, xpub)
        )

    antwort = _empfang_antwort(
        kennung=kennung,
        entry=entry,
        address=address,
        index=index,
        source=source,
        subscribed=subscribed,
        watch_active=watch_active,
        read_only=False,
    )
    state.empfang_cache[kennung] = dict(antwort)
    return antwort

def _empfang_aus_cache_schaetzung(
    state: AppState,
    entry: WalletEntry,
    *,
    kennung: str,
    max_index: int,
) -> dict:
    """Fallback ohne Electrs: max(bekannter Index)+1 — UI warnt."""

    from server import (
        main,
        ApiError,
        _next_receive_index_from_cache,
        _empfang_finalize,
    )

    xpub = entry.analyse_schluessel
    next_index = _next_receive_index_from_cache(
        state, entry, max_index=max_index,
    )
    skript = None if entry.is_multisig or entry.descriptor else entry.script_type
    abgeleitet = main.derive_receive_address_at_index(
        xpub, next_index, script_type=skript,
    )
    if not abgeleitet or not abgeleitet[0]:
        raise ApiError(500, "Empfangsadresse konnte nicht abgeleitet werden.")
    address, index = str(abgeleitet[0]), int(abgeleitet[1])
    # Belong weich: Ableitung kommt vom Wallet-Schlüssel; harter 500 leert das Dock.
    return _empfang_finalize(
        state,
        entry,
        kennung=kennung,
        address=address,
        index=index,
        source="cache_estimate",
        max_index=max_index,
    )

def _seed_wallet_ctx_aus_caches(state: AppState) -> None:
    """UTXO-/Verlauf-/Resolution-Adressen ins Mapping — ohne teure HD-Suche."""

    from server import main

    ctx = state.wallet_ctx
    if ctx is None:
        return
    schluessel = [e.analyse_schluessel for e in state.analyse_entries]
    if not schluessel:
        return
    try:
        main.seed_wallet_addresses_from_utxo_cache(
            ctx, schluessel, state.cache_dir,
        )
    except Exception:
        pass
    try:
        # Verlauf kann weit über max_addresses reichen (Gap-Scan) —
        # ohne Seed hängt /api/utxos an resolve_address × MAX_TRACE.
        main.seed_wallet_addresses_from_verlauf_cache(
            ctx, schluessel, state.cache_dir,
        )
    except Exception:
        pass
    try:
        main.seed_wallet_addresses_from_resolution_cache(ctx, schluessel)
    except Exception:
        pass

