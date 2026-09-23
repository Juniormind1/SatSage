"""Trace-/Verlauf-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations

import core.wallet_sync_engine as wallet_sync_engine

from typing import Any


def api_trace_alle(state: AppState, payload: dict) -> dict:
    """
    Verfolgt die Herkunft von UTXOs.

    *modus*:
    - ``steuer`` (Steuerjahr): Stop an Stichtag/Haltefrist-Anfang oder
      extern/Coinbase — schneller, für Anschaffungsdatum ausreichend.
    - ``voll`` / Default (Herkunft tracen): immer bis extern/Coinbase;
      setzt Steuer-Teilbäume fort (origin_tree), rechnet nicht alles neu.
    - ``vollstaendig=true`` (Wallet „Herkunft“): Tiefenlauf inkl. Lücken.

    Mit ``vollstaendig=true``: optional ``wallet_id``, alle UTXOs ohne
    vollständigen Baum — derselbe Pfad wie „Herkunftslücken schließen“.
    """
    from server import (
        ApiError,
        Cancelled,
        _eigene_adressen,
        _seed_wallet_ctx_aus_caches,
        _stop_before_ts_aus_payload,
        _trace_ein_utxo_tief,
        _trace_offen_basis,
        _trace_offen_steuer,
        _trace_offen_tief,
        _utxos_fuer_trace,
        analyze,
        main,
        threading,
        trace_cache,
        trace_mod,
        wallets_mod,
    )

    wallet_ctx = state.wallet_ctx
    if wallet_ctx is None:
        raise ApiError(400, "Kein gültiges Wallet konfiguriert.")

    # scan_end_index → Change jenseits max_addresses (sonst Intern→Extern)
    _seed_wallet_ctx_aus_caches(state)

    roh = payload if isinstance(payload, dict) else {}
    vollstaendig = bool(roh.get("vollstaendig") or roh.get("tief") or roh.get("deep"))
    modus_roh = str(roh.get("modus") or "").strip().lower()
    if vollstaendig:
        modus = "tief"
    elif modus_roh in ("steuer", "tax", "haltefrist"):
        modus = "steuer"
    else:
        # Herkunft tracen / Default: voll bis extern
        modus = "voll"

    wallet_id = str(roh.get("wallet_id") or "").strip()
    if vollstaendig and not wallet_id:
        raise ApiError(
            400,
            "Herkunft vollständig braucht eine wallet_id "
            "(Knopf in der Wallet-Ansicht).",
        )

    stop_before_ts = None
    if modus == "steuer":
        stop_before_ts = _stop_before_ts_aus_payload(roh)

    eigene_jetzt = _eigene_adressen(state)
    utxos = _utxos_fuer_trace(state, wallet_id=wallet_id)

    # Optional: nur bestimmte UTXOs tracen (z. B. nur gelbe aus Steuerjahr)
    nur_keys = roh.get("utxo_keys")
    if nur_keys:
        gewuenscht = set()
        for k in nur_keys:
            if isinstance(k, str) and ":" in k:
                try:
                    tx, vo = k.split(":", 1)
                    gewuenscht.add((tx.strip(), int(vo)))
                except (ValueError, TypeError):
                    pass
        if gewuenscht:
            utxos = [u for u in utxos if (u.get("txid"), int(u.get("vout", -1))) in gewuenscht]

    if not utxos:
        # Leerer Bestand ≠ „alles schon getracet“ — sonst wirkt „Herkünfte
        # UTXOs“ nach frischem Lab/Cache fälschlich fertig (grüner Hinweis).
        return {
            "nichts_zu_tun": True,
            "keine_utxos": True,
            "offen": 0,
            "utxos": 0,
            "vollstaendig": vollstaendig,
            "modus": modus,
            "wallet_id": wallet_id,
        }
    if modus == "tief":
        offen = _trace_offen_tief(state, utxos, eigene_jetzt)
    elif modus == "steuer":
        offen = _trace_offen_steuer(state, utxos, eigene_jetzt)
    else:
        offen = _trace_offen_basis(state, utxos, eigene_jetzt)

    if not offen:
        return {
            "nichts_zu_tun": True,
            "keine_utxos": False,
            "offen": 0,
            "utxos": len(utxos),
            "vollstaendig": vollstaendig,
            "modus": modus,
            "wallet_id": wallet_id,
        }

    eigene = set(wallet_ctx.address_to_wallet)
    wallet_name = ""
    if wallet_id:
        entry = wallets_mod.find_entry(state.entries, wallet_id)
        wallet_name = entry.display_name if entry else wallet_id

    def lauf(job):
        from core.jobs import Fortschritt, herzschlag

        stand = Fortschritt(job)
        halt = threading.Event()
        threading.Thread(
            target=herzschlag, args=(stand, halt), daemon=True,
        ).start()
        gesamt = len(offen)
        try:
            if modus == "tief" and wallet_name:
                stand.phase(
                    f"Herkunft vollständig für „{wallet_name}“ "
                    f"({gesamt} UTXOs)…"
                )
            elif modus == "steuer":
                stand.phase(
                    f"Steuerrelevantes Alter für {gesamt} UTXOs"
                    + (
                        f" (Horizont bis {stop_before_ts})…"
                        if stop_before_ts
                        else "…"
                    )
                )
            else:
                stand.phase(f"Herkunft bis extern für {gesamt} UTXOs…")
            stand.phase(f"Verbinde für {gesamt} UTXOs…")
            args = state.args_namespace()
            quelle, backend = main._setup_blockchain_client(args, state.env().values())
            job.raise_if_cancelled()

            fetchers = main._build_blockchain_fetchers(
                quelle, backend, args, wallet_ctx,
                immutable_cache_dir=state.immutable_cache_dir,
            )

            fertig = 0
            fehler = 0
            juengste = 0
            voll_ok = 0
            steuer_ok_n = 0

            def _zwischenstand() -> None:
                job.result = {
                    "verfolgt": fertig,
                    "fehlgeschlagen": fehler,
                    "offen": gesamt,
                    "juengste_sats": juengste,
                    "vollstaendig_ok": voll_ok,
                    "steuer_ok": steuer_ok_n,
                    "vollstaendig": vollstaendig,
                    "modus": modus,
                    "partial": True,
                }

            for index, (txid, vout) in enumerate(offen):
                job.raise_if_cancelled()
                rest = gesamt - index
                if modus == "tief":
                    text = (
                        f"Herkunft vollständig — noch {rest} von {gesamt} UTXOs"
                        f" · {txid[:12]}…:{vout}"
                    )
                elif modus == "steuer":
                    text = (
                        f"Steuerrelevantes Alter — noch {rest} von {gesamt} UTXOs"
                        f" · {txid[:12]}…:{vout}"
                    )
                else:
                    text = (
                        f"Herkunft — noch {rest} von {gesamt} UTXOs"
                        f" · {txid[:12]}…:{vout}"
                    )
                if index == 0:
                    stand.phase(text)
                else:
                    stand.tick(text)
                try:
                    fetch_addr = fetchers.get("fetch_address_utxos")
                    if modus == "tief":
                        # Gleicher Pfad wie Einzel-Knopf „Herkunftslücken schließen“.
                        def _tief_fortschritt(text: str) -> None:
                            t = str(text or "").strip()
                            job.raise_if_cancelled()
                            if not t:
                                return
                            if t.startswith("↻") or t.startswith("Eigene Vorgänger"):
                                stand.tick(t)
                            else:
                                stand.phase(t)

                        resume_tief = None
                        geladen_tief = trace_cache.laden(
                            txid, vout, state.immutable_cache_dir, eigene,
                        )
                        if geladen_tief and isinstance(
                            geladen_tief.get("baum"), dict
                        ):
                            origin_t = geladen_tief["baum"].get("origin_tree")
                            if (
                                isinstance(origin_t, dict)
                                and analyze.hat_brauchbaren_teilfortschritt(
                                    origin_t
                                )
                            ):
                                resume_tief = origin_t
                        ergebnis = _trace_ein_utxo_tief(
                            get_tx=fetchers["get_tx"],
                            txid=txid,
                            vout=vout,
                            eigene=eigene,
                            wallet_ctx=wallet_ctx,
                            cache_dir=state.cache_dir,
                            immutable_cache_dir=state.immutable_cache_dir,
                            fetch_addr=fetch_addr,
                            cache_source=quelle,
                            progress=_tief_fortschritt,
                            cancel_cb=lambda: job.cancelled,
                            folge_bundled=True,
                            folge_tx=True,
                            resume_origin=resume_tief,
                        )
                    else:
                        resume = None
                        if modus in ("voll", "steuer"):
                            geladen = trace_cache.laden(
                                txid, vout, state.immutable_cache_dir, eigene,
                            )
                            if geladen and isinstance(geladen.get("baum"), dict):
                                origin = geladen["baum"].get("origin_tree")
                                if (
                                    isinstance(origin, dict)
                                    and analyze.hat_brauchbaren_teilfortschritt(
                                        origin
                                    )
                                ):
                                    resume = origin
                        ergebnis = trace_mod.trace_utxo(
                            fetchers["get_tx"], txid, vout, eigene,
                            wallet=wallet_ctx,
                            cache_dir=state.cache_dir,
                            immutable_cache_dir=state.immutable_cache_dir,
                            fetch_address_utxos=fetch_addr,
                            cache_source=quelle,
                            stop_before_ts=(
                                stop_before_ts if modus == "steuer" else None
                            ),
                            # voll: Lücken fortsetzen; steuer: Horizont neu
                            # mit stop — Resume nur bei voll.
                            resume_origin=resume if modus == "voll" else None,
                        )
                    fertig += 1
                    if isinstance(ergebnis, dict) and ergebnis.get("found"):
                        if ergebnis.get("verfolgt_vollstaendig"):
                            voll_ok += 1
                        if ergebnis.get("steuer_ausreichend") or ergebnis.get(
                            "verfolgt_vollstaendig"
                        ):
                            steuer_ok_n += 1
                        if ergebnis.get("juengste_sats_ts"):
                            juengste += 1
                    _zwischenstand()
                except Cancelled:
                    raise          # Abbruch muss durchschlagen
                except Exception:
                    fehler += 1    # eine unerreichbare Tx stoppt nicht den Rest
                    _zwischenstand()
                    continue

            if modus == "tief":
                fertig_text = (
                    f"{fertig} von {gesamt} durchgezogen"
                    f" · {voll_ok} vollständig"
                    + (f", {fehler} fehlgeschlagen" if fehler else "")
                )
            elif modus == "steuer":
                fertig_text = (
                    f"{fertig} von {gesamt} verfolgt"
                    f" · {steuer_ok_n} steuerlich ok"
                    + (f", {fehler} fehlgeschlagen" if fehler else "")
                )
            else:
                fertig_text = (
                    f"{fertig} von {gesamt} verfolgt"
                    f" · {voll_ok} bis extern"
                    + (f", {fehler} fehlgeschlagen" if fehler else "")
                )
            stand.phase(fertig_text)
            return {
                "verfolgt": fertig,
                "fehlgeschlagen": fehler,
                "offen": gesamt,
                "juengste_sats": juengste,
                "vollstaendig_ok": voll_ok,
                "steuer_ok": steuer_ok_n,
                "vollstaendig": vollstaendig,
                "modus": modus,
                "partial": False,
            }
        finally:
            halt.set()
            stand.close()

    if modus == "tief":
        titel = (
            f"Herkunft vollständig {wallet_name or wallet_id} "
            f"({len(offen)} UTXOs)"
        )
        art = "trace-tief"
    elif modus == "steuer":
        titel = f"Steuerrelevantes Alter für {len(offen)} UTXOs"
        art = "trace-alle"
    else:
        titel = f"Herkunft für {len(offen)} UTXOs"
        art = "trace-alle"
    job = state.jobs.start(
        art,
        titel,
        lauf,
        meta={
            "art": art,
            "anzahl": len(offen),
            "wallet_id": wallet_id,
            "wallet_name": wallet_name,
            "vollstaendig": vollstaendig,
            "modus": modus,
            "stop_before_ts": stop_before_ts,
        },
    )
    return job.as_dict()


def api_verlauf(state: AppState, payload: dict) -> dict:
    """
    Erhebt den vollständigen Verlauf — und schreibt dabei den UTXO-Bestand.

    Ohne Verlauf kennt die Steuerauswertung nur den heutigen Bestand; ein 2023
    empfangener und 2024 verkaufter Betrag taucht nirgends auf, obwohl gerade
    die Veräußerung der steuerlich maßgebliche Vorgang ist. Der reine
    UTXO-Scan liefert dagegen nur Unverbrauchtes — der Verlaufsscan macht
    beides: Historie inkl. ausgegebener Outputs **und** aktuellen Bestand.

    Mit *wallet_id* nur dieses Wallet (Knopf in der Wallet-Ansicht), ohne
    Angabe alle ableitbaren Wallets (Steuerjahr). Derselbe Cache.

    Kostet Historien- und Bestands-Abfragen je Adresse und braucht einen
    Electrum-Server — deshalb ausdrücklich angestoßen und nicht beiläufig.
    """
    from server import (
        ApiError,
        ScanSchonGeplant,
        _seed_wallet_ctx_aus_caches,
        main,
        threading,
        wallets_mod,
    )

    wallet_ctx = state.wallet_ctx
    if wallet_ctx is None:
        raise ApiError(400, "Kein gültiges Wallet konfiguriert.")

    kennung = str(payload.get("wallet_id") or "").strip()
    if kennung:
        entry = wallets_mod.find_entry(state.entries, kennung)
        if entry is None or not entry.is_valid():
            raise ApiError(404, "Wallet nicht gefunden.")
        ziele = [entry]
        label = f"Verlaufsscan {entry.display_name}"
    else:
        ziele = list(state.analyse_entries)
        label = "Verlauf aller Wallets"
    if not ziele:
        raise ApiError(400, "Keine ableitbaren Wallets konfiguriert.")

    xpubs = [e.analyse_schluessel for e in ziele]
    namen = ", ".join(e.display_name for e in ziele)

    def lauf(job):
        from core.jobs import Fortschritt, herzschlag

        stand = Fortschritt(job)
        halt = threading.Event()
        threading.Thread(
            target=herzschlag, args=(stand, halt), daemon=True,
        ).start()
        try:
            stand.phase(f"Starte Verlaufsscan für {namen}…")
            # Adressen bis scan_end_index (Change jenseits max_addresses)
            _seed_wallet_ctx_aus_caches(state)
            stand.phase("Verbinde mit der Verlaufs-Datenquelle…")
            args = state.args_namespace()
            # Eigene Priorität: Electrs LAN → Onion → BIP-158 → öffentlich.
            # Nicht _setup_blockchain_client (dort kann BIP-158 vor öffentlich
            # gewinnen und History fehlte früher ganz).
            werte = state.env().values()
            quelle, backend = main._setup_verlauf_client(args, werte)
            job.raise_if_cancelled()

            fetchers = main._build_blockchain_fetchers(
                quelle, backend, args, wallet_ctx,
                immutable_cache_dir=state.immutable_cache_dir,
            )
            holen = fetchers.get("fetch_wallet_history")
            if holen is None:
                raise RuntimeError(
                    f"Verlauf: Datenquelle {quelle} liefert keine Historie."
                )

            def mit_fortschritt(adressen, **kwargs):
                job.raise_if_cancelled()
                gesamt = len(adressen)
                skip = set(kwargs.get("skip_addresses") or [])
                offen = max(0, gesamt - len(skip))
                stand.phase(
                    f"Frage Verlauf für {gesamt} Adressen — "
                    f"noch {offen} von {gesamt} Adressen"
                    + (f" (setze fort, {len(skip)} schon da)" if skip else "")
                )

                def on_progress(text, *, sofort=False):
                    job.raise_if_cancelled()
                    if sofort:
                        stand.phase(text)
                    else:
                        stand.tick(text)

                try:
                    return holen(adressen, on_progress=on_progress, **kwargs)
                except TypeError:
                    return holen(adressen)

            ergebnis = wallet_sync_engine.resolve_wallet_verlauf(
                xpubs, mit_fortschritt, state.cache_dir, wallet_ctx
            )
            gesamt = sum(len(v) for v in ergebnis.values())
            stand.phase(f"{gesamt} Ein- und Ausgänge erfasst")

            # Bestand: nur nachziehen wenn kein frischer UTXO-Cache da ist
            # (sonst doppelte Gap-Arbeit direkt nach UTXO-Scan).
            frisch, frisch_grund = main.utxo_cache_frisch_genug(
                xpubs, state.cache_dir,
            )
            if frisch is not None:
                stand.phase(frisch_grund)
                gefunden = frisch
            else:
                stand.phase(
                    f"Erfasse UTXO-Bestand… ({frisch_grund})"
                )
                hol_utxo = fetchers.get("fetch_wallet_utxos")
                if hol_utxo is None:
                    raise RuntimeError(
                        f"Verlauf: Datenquelle {quelle} liefert keine UTXOs."
                    )

                def on_utxos_update(stand_utxos: list) -> None:
                    job.result = {
                        "eintraege": gesamt,
                        "wallets": len(ergebnis),
                        "utxo_count": len(stand_utxos),
                        "partial": True,
                    }
                    wort = "UTXO" if len(stand_utxos) == 1 else "UTXOs"
                    stand.tick(f"{len(stand_utxos)} {wort} bisher…")

                gefunden = wallet_sync_engine.resolve_wallet_utxos(
                    xpubs,
                    hol_utxo,
                    fetchers["fetch_address_utxos"],
                    fetchers.get("fetch_addresses_utxos"),
                    state.cache_dir,
                    quelle,
                    rescan=True,
                    max_addresses=max(e.max_addresses for e in ziele),
                    wallet=wallet_ctx,
                    verify_utxo_spent=fetchers.get("verify_utxo_spent"),
                    fulcrum=fetchers.get("fulcrum"),
                    on_missing_xpubs=lambda fehlend: True,
                    on_progress=lambda text, *, sofort=False: (
                        stand.phase(text) if sofort else stand.tick(text)
                    ),
                    on_utxos_update=on_utxos_update,
                )
            job.raise_if_cancelled()
            wort = "UTXO" if len(gefunden) == 1 else "UTXOs"
            stand.phase(
                f"{gesamt} Ein- und Ausgänge, {len(gefunden)} {wort}"
            )
            return {
                "eintraege": gesamt,
                "wallets": len(ergebnis),
                "utxo_count": len(gefunden),
                "partial": False,
                "utxo_from_cache": frisch is not None,
            }
        finally:
            halt.set()
            stand.close()

    # Einzel-Wallet in die Scan-Pipeline; „alle Wallets“ parallel wie bisher
    # (kein wallet_id → kein Dedupe-Konflikt mit Einzelscans).
    if kennung and len(ziele) == 1:
        entry = ziele[0]
        wid = wallets_mod.eintrag_id(entry)
        try:
            return state.scan_queue.einreihen(
                kind="verlauf",
                wallet_id=wid,
                wallet_name=entry.display_name,
                label=label,
                factory=lauf,
            )
        except ScanSchonGeplant as exc:
            raise ApiError(409, str(exc)) from exc
    job = state.jobs.start(
        "verlauf",
        label,
        lauf,
        meta={
            "wallet_id": "",
            "wallet_name": namen,
            "art": "verlauf",
            "alle": True,
        },
    )
    return job.as_dict()


def api_trace_gespeichert(state: AppState, query: dict) -> dict:
    """
    Liefert einen bereits verfolgten Baum — ohne Job, ohne Node-Verbindung.

    Die Vorgeschichte eines bestätigten Outputs ändert sich nicht, ein einmal
    gebauter Baum bleibt also gültig. Liegt keiner vor, sagt die Antwort das
    schlicht; die Oberfläche startet dann den regulären Lauf.
    """
    from server import (
        ApiError,
        _seed_wallet_ctx_aus_caches,
        trace_cache,
        trace_mod,
    )

    ziel = trace_mod.parse_ziel(str((query.get("target") or [""])[0]))
    if ziel is None:
        raise ApiError(
            400,
            "Bitte eine TxID oder ein UTXO in der Form txid:vout angeben.",
        )
    txid, vout = ziel

    wallet_ctx = state.wallet_ctx
    # Vor Fingerprint/veraltet: Mapping bis scan_end (Change jenseits max_addresses)
    if wallet_ctx is not None:
        _seed_wallet_ctx_aus_caches(state)
    eigene = set(wallet_ctx.address_to_wallet) if wallet_ctx else None

    gespeichert = trace_cache.laden(txid, vout, state.immutable_cache_dir, eigene)
    if gespeichert is None:
        return {"vorhanden": False}

    baum = gespeichert["baum"] or {}
    if isinstance(baum, dict):
        baum = dict(baum)
        # Alte Bäume: externe Blätter ohne time_label nachziehen (Tx-Cache).
        # Kein lokales ``import trace as trace_mod`` — sonst UnboundLocalError
        # auf dem Modul-Import weiter unten (Python-Scoping).
        try:
            kinder0 = baum.get("children") or []
            if kinder0:
                trace_mod._anreichere_externe_zeiten(
                    kinder0, state.immutable_cache_dir,
                )
        except Exception:
            pass
        # Vollständigkeit und Done-Flag frisch aus den Blättern — nicht dem
        # ggf. veralteten Cache-Flag vertrauen (ältere Läufe markierten
        # Bäume mit leeren grünen Blättern fälschlich als fertig).
        baum.update(trace_mod.folge_meta(baum))

    return {
        "vorhanden": True,
        "erstellt_ts": gespeichert["erstellt_ts"],
        "veraltet": gespeichert["veraltet"],
        "adressen_seither": gespeichert["adressen_seither"],
        "ergebnis": baum,
    }


def api_trace(state: AppState, payload: dict) -> dict:
    """
    Startet die Herkunftsanalyse als Hintergrund-Vorgang.

    Optional ``followup``:
    - ``full`` — Lücken schließen: gebündelte eigene Eingänge **und**
      Vorgänger-Txs (UI-Standard)
    - ``tx_oriented`` — nur Vorgänger-Txs gründlicher (Legacy/API)
    - ``resolve_unresolved`` — nur gebündelte Eingänge (Legacy/API)

    Ein Trace über mehrere Ebenen dauert Minuten und muss abbrechbar bleiben —
    deshalb kein synchroner Aufruf.
    """
    from server import (
        ApiError,
        _seed_wallet_ctx_aus_caches,
        _trace_ein_utxo_tief,
        _wallet_name_fuer_utxo,
        analyze,
        main,
        threading,
        trace_cache,
        trace_mod,
    )

    ziel = trace_mod.parse_ziel(str(payload.get("target", "")))
    if ziel is None:
        raise ApiError(
            400,
            "Bitte eine TxID oder ein UTXO in der Form txid:vout angeben.",
        )
    txid, vout = ziel

    followup_roh = str(payload.get("followup") or "").strip().lower()
    if followup_roh in ("", "none", "null"):
        followup = None
    elif followup_roh in ("full", "tx_oriented", "resolve_unresolved"):
        followup = followup_roh
    else:
        raise ApiError(
            400,
            "followup muss fehlen, „full“, „tx_oriented“ oder "
            "„resolve_unresolved“ sein.",
        )
    # full = beides; Legacy-Werte bleiben einzeln steuerbar.
    folge_bundled = followup in ("full", "resolve_unresolved")
    folge_tx = followup in ("full", "tx_oriented")
    # „Scan neu“: nicht stumm aus Cache; brauchbaren Teilbaum fortsetzen
    # statt alles zu löschen. Nur leere/kaputte Stände werden verworfen.
    force = bool(
        payload.get("force")
        or payload.get("neu")
        or payload.get("rescan")
    )

    wallet_ctx = state.wallet_ctx
    if wallet_ctx is None:
        raise ApiError(400, "Kein gültiges Wallet konfiguriert.")
    _seed_wallet_ctx_aus_caches(state)
    eigene = set(wallet_ctx.address_to_wallet)
    wallet_name = _wallet_name_fuer_utxo(
        state,
        txid,
        vout,
        hinweis=str(
            payload.get("wallet")
            or payload.get("wallet_name")
            or ""
        ),
    )
    resume_origin = None
    if force or followup is not None:
        try:
            geladen = trace_cache.laden(
                txid, vout, state.immutable_cache_dir, eigene,
            )
            if geladen and isinstance(geladen.get("baum"), dict):
                origin = geladen["baum"].get("origin_tree")
                if (
                    isinstance(origin, dict)
                    and analyze.hat_brauchbaren_teilfortschritt(origin)
                ):
                    resume_origin = origin
                elif force:
                    # Nichts Brauchbares — alten Stand weg, echter Neustart.
                    trace_cache.loeschen(txid, vout, state.immutable_cache_dir)
        except Exception:
            if force:
                try:
                    trace_cache.loeschen(txid, vout, state.immutable_cache_dir)
                except Exception:
                    pass

    def lauf(job):
        from core.jobs import Fortschritt, herzschlag

        # Nochmals Cache (Race: GET und POST parallel) — bevor Electrs startet.
        # force: nie stiller Cache-Hit (Resume läuft unten mit Netz).
        if followup is None and not force:
            treffer = trace_cache.laden(
                txid, vout, state.immutable_cache_dir, eigene,
            )
            if treffer is not None:
                baum = treffer.get("baum") or {}
                if isinstance(baum, dict) and baum.get("found"):
                    baum = dict(baum)
                    try:
                        kinder = baum.get("children") or []
                        if kinder:
                            trace_mod._anreichere_externe_zeiten(
                                kinder, state.immutable_cache_dir,
                            )
                        baum.update(trace_mod.folge_meta(baum))
                    except Exception:
                        pass
                    baum["source"] = "cache"
                    job.message = "Aus Herkunfts-Cache."
                    return baum

        stand = Fortschritt(job)
        halt = threading.Event()
        threading.Thread(
            target=herzschlag, args=(stand, halt), daemon=True,
        ).start()
        try:
            # log=True: Nav und Fokus-UI sehen mehr als nur die letzte message.
            stand.phase("Verbinde mit der Datenquelle…")
            args = state.args_namespace()
            quelle, backend = main._setup_blockchain_client(args, state.env().values())
            job.raise_if_cancelled()

            fetchers = main._build_blockchain_fetchers(
                quelle, backend, args, wallet_ctx,
                immutable_cache_dir=state.immutable_cache_dir,
            )
            get_tx = fetchers["get_tx"]
            fetch_addr = fetchers.get("fetch_address_utxos")

            label = {
                None: f"Verfolge Herkunft über {quelle}…",
                "full": f"Schließe Herkunftslücken über {quelle}…",
                "tx_oriented": f"Speichere gründlichere Herkunft über {quelle}…",
                "resolve_unresolved": f"Löse gebündelte Eingänge über {quelle}…",
            }[followup]
            if force and resume_origin is not None:
                label = f"Setze Herkunft fort über {quelle}…"
            elif force:
                label = f"Scan neu über {quelle}…"
            stand.phase(label)

            def _fortschritt(text: str) -> None:
                """Engine-Fortschritt → Job-message + Log (Meilensteine)."""
                t = str(text or "").strip()
                job.raise_if_cancelled()
                if not t:
                    return
                # Längere Meilensteine / Hop-Wechsel: sofort ins Log.
                if (
                    t.startswith("↻")
                    or t.startswith("Lücken")
                    or t.startswith("Eigene Vorgänger")
                    or t.startswith("Aktualisiere")
                    or t.startswith("Folgeanalyse")
                    or t.startswith("Schließe")
                    or t.startswith("Verfolge")
                    or t.startswith("Setze")
                ):
                    # tick speichert Stand; phase bei echten Phasen-Texten.
                    if t.startswith("↻") or t.startswith("Eigene Vorgänger"):
                        stand.tick(t)
                    else:
                        stand.phase(t)
                else:
                    stand.tick(t)

            if folge_tx or folge_bundled:
                ergebnis = _trace_ein_utxo_tief(
                    get_tx=get_tx,
                    txid=txid,
                    vout=vout,
                    eigene=eigene,
                    wallet_ctx=wallet_ctx,
                    cache_dir=state.cache_dir,
                    immutable_cache_dir=state.immutable_cache_dir,
                    fetch_addr=fetch_addr,
                    cache_source=quelle,
                    progress=_fortschritt,
                    cancel_cb=lambda: job.cancelled,
                    folge_bundled=folge_bundled,
                    folge_tx=folge_tx,
                    resume_origin=resume_origin,
                )
            else:
                ergebnis = trace_mod.trace_utxo(
                    get_tx,
                    txid,
                    vout,
                    eigene,
                    wallet=wallet_ctx,
                    cache_dir=state.cache_dir,
                    immutable_cache_dir=state.immutable_cache_dir,
                    fetch_address_utxos=fetch_addr,
                    cache_source=quelle,
                    progress=_fortschritt,
                    resume_origin=resume_origin,
                )
            ergebnis["source"] = quelle
            ergebnis["followup"] = followup
            job.message = (
                f"{ergebnis['summary'].get('node_count', 0)} Zuflüsse ermittelt."
                if ergebnis.get("found") else "Keine Herkunft ermittelbar."
            )
            return ergebnis
        finally:
            halt.set()
            stand.close()

    target = f"{txid}:{vout}"
    followup_meta = followup or ""
    # Derselbe UTXO + derselbe followup: laufenden Job wiederverwenden —
    # sonst stapeln sich „Herkunft …:1“ in der Nav und blockieren sich.
    bestehend = state.jobs.finde_laufenden(
        "trace",
        meta={"target": target, "followup": followup_meta},
    )
    if bestehend is not None:
        return bestehend.as_dict()

    # Cache-first (ohne followup, ohne force): vorhandener Baum → kein Job.
    # Unvollständige Bäume bleiben sichtbar (rote Marke); „Scan neu“ setzt force.
    if followup is None and not force:
        eigene_cache = set(wallet_ctx.address_to_wallet) if wallet_ctx else None
        treffer = trace_cache.laden(
            txid, vout, state.immutable_cache_dir, eigene_cache,
        )
        if treffer is not None:
            baum = treffer.get("baum") or {}
            if isinstance(baum, dict) and baum.get("found"):
                baum = dict(baum)
                try:
                    kinder = baum.get("children") or []
                    if kinder:
                        trace_mod._anreichere_externe_zeiten(
                            kinder, state.immutable_cache_dir,
                        )
                    baum.update(trace_mod.folge_meta(baum))
                except Exception:
                    pass
                baum.setdefault("source", "cache")
                if wallet_name and not (baum.get("root") or {}).get("wallet"):
                    root = dict(baum.get("root") or {})
                    root["wallet"] = wallet_name
                    baum["root"] = root
                return {
                    "id": f"cache-{txid[:12]}-{vout}",
                    "kind": "trace",
                    "label": f"Herkunft {txid[:12]}…:{vout} (Cache)",
                    "status": "done",
                    "message": "Aus Herkunfts-Cache.",
                    "log": [],
                    "running": False,
                    "elapsed_s": 0,
                    "error": "",
                    "meta": {
                        "art": "trace",
                        "target": target,
                        "txid": txid,
                        "vout": vout,
                        "followup": "",
                        "from_cache": True,
                        "wallet_name": wallet_name,
                    },
                    "started_at": treffer.get("erstellt_ts") or 0,
                    "finished_at": treffer.get("erstellt_ts") or 0,
                    "result": baum,
                    "from_cache": True,
                    "erstellt_ts": treffer.get("erstellt_ts"),
                    "veraltet": treffer.get("veraltet"),
                    "adressen_seither": treffer.get("adressen_seither"),
                }

    titel = f"Herkunft {txid[:12]}…:{vout}"
    if force and resume_origin is not None and followup is None:
        titel = f"Herkunft fortsetzen {txid[:12]}…:{vout}"
    elif force and followup is None:
        titel = f"Scan neu {txid[:12]}…:{vout}"
    elif followup == "full":
        titel = f"Lücken schließen {txid[:12]}…:{vout}"
    elif followup == "tx_oriented":
        titel = f"Folgeanalyse {txid[:12]}…:{vout}"
    elif followup == "resolve_unresolved":
        titel = f"Nachziehen {txid[:12]}…:{vout}"
    if wallet_name:
        titel = f"{titel} · {wallet_name}"
    job = state.jobs.start(
        "trace",
        titel,
        lauf,
        meta={
            "art": "trace",
            "target": target,
            "txid": txid,
            "vout": vout,
            "followup": followup_meta,
            "force": force,
            "resume": bool(resume_origin),
            "wallet_name": wallet_name,
        },
    )
    return job.as_dict()
