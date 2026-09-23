"""Labels-/Sanktions-/Börsen-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations

from typing import Any


def api_sanctions(state: AppState, query: dict) -> dict:
    """Zustand der lokalen Listen — ohne Netzzugriff."""
    from server import sanctions_mod

    return sanctions_mod.status(state.sanctions_dir).as_dict()


def api_sanctions_update(state: AppState, payload: dict) -> dict:
    """Lädt die Listen neu. Läuft als Job, der Download dauert."""

    def lauf(job):
        job.progress("Lade Sanktions- und Blacklists…", log=True)
        import sanctioned

        adressen, meta = sanctioned.update_sanctioned_lists(
            cache_dir=state.sanctions_dir
        )
        job.raise_if_cancelled()
        job.message = f"{len(adressen):,} Adressen geladen.".replace(",", ".")
        return {"adressen": len(adressen)}

    job = state.jobs.start(
        "sanctions",
        "Sanktionslisten aktualisieren",
        lauf,
        meta={"art": "sanctions"},
    )
    return job.as_dict()


def api_labels(state: AppState, query: dict) -> dict:
    """Zustand des Labelbestands — ohne Netzzugriff."""
    from server import labels

    return labels.status(state.label_dir)


def api_labels_update(state: AppState, payload: dict) -> dict:
    """Lädt den Labelbestand herunter. Die volle Fassung sind 35 MB."""
    from server import (
        ApiError,
        labels,
    )

    variante = str(payload.get("variante") or "kern")
    if variante not in labels.VARIANTEN:
        raise ApiError(400, f"Unbekannte Variante: {variante}")

    def lauf(job):
        def fortschritt(dateiname: str, geladen: int, gesamt: int) -> None:
            anteil = f" von {gesamt // 1024:,} KB".replace(",", ".") if gesamt else ""
            job.progress(
                f"{dateiname}: {geladen // 1024:,} KB{anteil}".replace(",", ".")
            )

        job.progress("Lade Adress-Labels…", log=True)
        stand = labels.aktualisiere(
            state.label_dir, variante=variante, fortschritt=fortschritt
        )
        job.raise_if_cancelled()
        job.message = (
            f"{stand['adressen']:,} Adressen, davon {stand['benannt']:,} benannt."
            .replace(",", ".")
        )
        return stand

    job = state.jobs.start(
        "labels",
        "Adress-Labels laden",
        lauf,
        meta={"art": "labels", "variante": variante},
    )
    return job.as_dict()


def api_labels_verwerfen(state: AppState, query: dict) -> dict:
    from server import labels

    return {"entfernt": labels.verwirf(state.label_dir)}


def api_labels_import(state: AppState, payload: dict) -> dict:
    """Manueller Label-Import (Dateien lokal beschafft)."""
    from server import (
        ApiError,
        labels,
        _dateien_aus_import_payload,
    )

    dateien = _dateien_aus_import_payload(payload)
    variante = payload.get("variante")
    try:
        stand = labels.importiere_dateien(
            dateien,
            state.label_dir,
            variante=str(variante) if variante else None,
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    return stand


def api_exchange_reports(state: AppState, query: dict) -> dict:
    """Status der importierten Börsen-CSV-Reports."""
    from core import exchange_reports as boerse

    return boerse.status(state.exchange_reports_dir)


def api_exchange_reports_import(state: AppState, payload: dict) -> dict:
    """
    Börsen-Transaktionsreport (CSV) einlesen.

    Body: ``name`` (Börse), ``csv`` (Text), optional ``filename``,
    ``ersetzen`` (true = Datei der Börse neu statt mergen).
    Nur BTC-Adressen/TxIDs — Kurse und Shitcoins werden verworfen.
    """
    from server import ApiError

    from core import exchange_reports as boerse

    if not isinstance(payload, dict):
        raise ApiError(400, "JSON-Objekt erwartet.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ApiError(400, "Feld „name“ (Börse) fehlt.")
    csv_text = payload.get("csv")
    if csv_text is None:
        raise ApiError(400, "Feld „csv“ fehlt.")
    if not isinstance(csv_text, str):
        raise ApiError(400, "Feld „csv“ muss Text sein.")
    if len(csv_text) > 40 * 1024 * 1024:
        raise ApiError(400, "CSV zu groß (max. 40 MB).")
    dateiname = str(payload.get("filename") or "").strip()[:200]
    ersetzen = bool(payload.get("ersetzen"))
    try:
        ergebnis = boerse.importiere_csv(
            csv_text,
            name=name,
            filename=dateiname,
            cache_dir=state.exchange_reports_dir,
            ersetzen=ersetzen,
        )
    except boerse.ExchangeReportError as exc:
        raise ApiError(400, str(exc)) from exc
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    ergebnis["status"] = boerse.status(state.exchange_reports_dir)
    return ergebnis


def api_exchange_reports_loesche(state: AppState, query: dict) -> dict:
    """Eine Börse oder alle Reports löschen. Query: ``slug`` oder ``all=1``."""
    from server import ApiError

    from core import exchange_reports as boerse

    if str(query.get("all") or "").strip() in ("1", "true", "yes"):
        n = 0
        for e in boerse.liste(state.exchange_reports_dir):
            if boerse.loesche(str(e.get("slug") or ""), state.exchange_reports_dir):
                n += 1
        return {"geloescht": n, "status": boerse.status(state.exchange_reports_dir)}
    slug = str(query.get("slug") or "").strip()
    if not slug:
        raise ApiError(400, "Query „slug“ oder „all=1“ fehlt.")
    ok = boerse.loesche(slug, state.exchange_reports_dir)
    return {
        "geloescht": 1 if ok else 0,
        "slug": slug,
        "status": boerse.status(state.exchange_reports_dir),
    }


def api_sanctions_import(state: AppState, payload: dict) -> dict:
    """Manueller Sanktionslisten-Import (JSON/TXT/XML/ZIP)."""
    from server import (
        ApiError,
        sanctions_mod,
        _dateien_aus_import_payload,
    )

    import sanctioned as sanctioned_mod

    dateien = _dateien_aus_import_payload(payload)
    try:
        adressen, meta = sanctioned_mod.importiere_dateien(
            dateien, cache_dir=state.sanctions_dir
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc
    return {
        "adressen": len(adressen),
        "meta": meta,
        "status": sanctions_mod.status(state.sanctions_dir).as_dict(),
    }


def _sanctions_get_tx_pool(state: AppState):
    """
    (get_tx je Worker, Zahl der Verbindungen) für Sanktionsabfragen.

    Nutzt den eigenen Server, wenn er privat adressiert ist (LAN/Loopback —
    Anfragen nach gelisteten Fremdadressen bleiben im eigenen Netz); sonst
    den öffentlichen Clearnet-Pool. Liefert ``(None, 0)``, wenn nichts
    erreichbar ist.

    Jeder Worker bekommt seinen eigenen Client: Ein Fulcrum-Client ist eine
    einzelne Socket-Verbindung und verträgt keine parallelen Anfragen.
    """
    from server import main

    pool, _quelle, _aus_cache = main.resolve_sanctions_preferred_pool(
        state.env().values()
    )
    if pool is None:
        return None, 0

    def get_tx_je_worker(worker_id: int):
        return main.make_cached_fulcrum_get_tx(
            pool.client_at(worker_id), state.immutable_cache_dir
        )

    return get_tx_je_worker, len(pool)


def api_sanctions_check_ergebnis(state: AppState, query: dict) -> dict:
    """
    Zuletzt gespeichertes Ergebnis der Vorgeschichte-Prüfung.

    Die Oberfläche zeigt es beim Öffnen der Ansicht an, statt jedes Mal
    einen minutenlangen Lauf zu verlangen. ``vorhanden: false`` heißt
    schlicht: noch nie geprüft.
    """
    from server import sanctions_mod

    daten = sanctions_mod.check_ergebnis_laden(state.sanctions_dir)
    if not daten:
        return {"vorhanden": False}
    return {"vorhanden": True, **daten}


def api_sanctions_check_verwerfen(state: AppState) -> dict:
    """Gespeichertes Ergebnis löschen — etwa nach Wallet-Änderungen."""
    from server import sanctions_mod

    return {"geloescht": sanctions_mod.check_ergebnis_verwerfen(state.sanctions_dir)}


def api_sanctions_check(state: AppState, payload: dict) -> dict:
    """
    Prüft Wallet-UTXOs xpub-blind auf sanktionierte Adressen (CLI-Menü 6.1)
    — Drittperspektive ohne XPUB, bis *max_hops* Prevouts — als Job.

    Payload: {"wallet_id": "<kennung|leer=alle>", "max_hops": 3}
    """
    from server import (
        ApiError,
        wallets_mod,
        utxos_mod,
        sanctions_mod,
        time,
        datetime,
    )

    import analyze
    import sanctioned

    wallet_ctx = state.wallet_ctx
    if wallet_ctx is None:
        raise ApiError(400, "Kein gültiges Wallet konfiguriert.")

    kennung = str(payload.get("wallet_id", "")).strip()
    if kennung:
        ziel = wallets_mod.find_entry(state.entries, kennung)
        if ziel is None:
            raise ApiError(404, "Wallet nicht gefunden.")
        ziele = [ziel]
    else:
        ziele = [e for e in state.entries if e.is_valid()]
    if not ziele:
        raise ApiError(400, "Kein gültiges Wallet konfiguriert.")

    try:
        max_hops = int(payload.get("max_hops", 3))
    except (TypeError, ValueError):
        max_hops = 3
    from core.sanctions import clamp_sanktion_max_hops

    max_hops = clamp_sanktion_max_hops(max_hops, default=3)

    eigene = set(wallet_ctx.address_to_wallet)

    def lauf(job):
        adressen, _ = sanctioned.load_sanctioned_xbt_addresses(
            cache_dir=state.sanctions_dir
        )
        if not adressen:
            raise ApiError(
                412,
                "Keine Sanktionslisten vorhanden — bitte zuerst aktualisieren.",
            )

        job.progress("Verbinde mit dem Sanktions-Server…")
        print("Sanktionsprüfung: verbinde Datenquelle…", flush=True)
        get_tx_je_worker, verbindungen = _sanctions_get_tx_pool(state)
        job.raise_if_cancelled()
        if get_tx_je_worker is None:
            raise ApiError(
                503,
                "Kein Fulcrum für Sanktionsabfragen erreichbar — weder der "
                "eigene Server noch ein Clearnet-Server.",
            )
        get_tx = get_tx_je_worker(0)
        print(
            f"Sanktionsprüfung: {verbindungen} Verbindung(en), "
            f"{max_hops} Hop(s), {len(adressen):,} Listen-Adressen."
            .replace(",", "."),
            flush=True,
        )

        ergebnisse = []
        for ziel_entry in ziele:
            job.raise_if_cancelled()
            name = ziel_entry.display_name
            gecacht = utxos_mod.load_cached_utxos(
                ziel_entry.analyse_schluessel,
                state.cache_dir,
                immutable_cache_dir=state.immutable_cache_dir,
            )
            utxos = [
                u for u in (gecacht or [])
                if wallet_ctx.resolve_address(u.get("address", "")) == name
            ]
            if not utxos:
                ergebnisse.append({
                    "wallet": name, "geprueft": 0, "treffer": [],
                    "coinjoins": [],
                    "abgebrochen": False,
                })
                continue

            print(
                f"Sanktionsprüfung „{name}“: {len(utxos)} UTXO(s)…",
                flush=True,
            )

            # Parallel: Statuszeile = zuletzt meldender Worker (nicht „fertig“).
            def fortschritt(felder):
                if job.cancelled:
                    return
                job.progress(
                    f"{name}: {felder.get('status', '')} "
                    f"(UTXO {felder.get('wallet_utxo', '')}, "
                    f"Hop {felder.get('hop', 0)}/{max_hops}, "
                    f"{felder.get('addrs_checked', 0)} Adressen"
                    + (f", {verbindungen} Verbindungen" if verbindungen > 1 else "")
                    + ")"
                )

            gesehen: set[str] = set()
            try:
                treffer, geprueft, abbruch, coinjoins = (
                    analyze.check_wallet_utxos_sanctions(
                        get_tx,
                        utxos,
                        eigene,
                        adressen,
                        max_hops=max_hops,
                        wallet=wallet_ctx,
                        abort_on_hit=False,
                        progress_cb=fortschritt,
                        cancel_cb=lambda: job.cancelled,
                        gesehene_adressen=gesehen,
                        get_tx_je_worker=get_tx_je_worker,
                        worker_count=verbindungen,
                        immutable_cache_dir=state.immutable_cache_dir,
                    )
                )
            except Exception as exc:
                from core.jobs import Cancelled, ist_abbruch

                if job.cancelled or ist_abbruch(exc) or isinstance(exc, Cancelled):
                    treffer, geprueft, abbruch, coinjoins = [], 0, None, []
                else:
                    raise
            job.raise_if_cancelled()
            ergebnisse.append({
                "wallet": name,
                "geprueft": geprueft,
                "treffer": treffer,
                "coinjoins": coinjoins,
                "abgebrochen": abbruch is not None or job.cancelled,
                "adressen_geprueft": len(gesehen),
                # Sortiert und gekappt: die Datei soll auch bei tiefen Läufen
                # lesbar bleiben, und die Reihenfolge stabil, damit zwei
                # Läufe vergleichbar sind.
                "adressen": sorted(gesehen)[
                    :sanctions_mod.CHECK_ADRESSEN_LIMIT
                ],
                "adressen_gekappt": (
                    len(gesehen) > sanctions_mod.CHECK_ADRESSEN_LIMIT
                ),
                "utxos": sorted(
                    f"{u.get('txid', '')}:{u.get('vout')}" for u in utxos
                ),
            })

        gesamt_treffer = sum(len(e["treffer"]) for e in ergebnisse)
        job.message = (
            f"{gesamt_treffer} Treffer in {len(ergebnisse)} Wallet(s) "
            f"({max_hops} Hop(s))."
        )
        ergebnis = {
            "max_hops": max_hops,
            "listen_adressen": len(adressen),
            "wallets": ergebnisse,
            "erstellt_ts": int(time.time()),
            "erstellt": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "vollstaendig": not job.cancelled,
            "verbindungen": verbindungen,
        }
        # Auch ein abgebrochener Lauf wird gespeichert — er ist als
        # unvollständig markiert, und die bereits geprüften Wallets sind
        # mehr wert als eine leere Ansicht.
        ergebnis["gespeichert"] = sanctions_mod.check_ergebnis_speichern(
            state.sanctions_dir, ergebnis
        )
        return ergebnis

    namen = ", ".join(e.display_name for e in ziele)
    job = state.jobs.start(
        "sanctions-check",
        f"Sanktionsprüfung {namen} ({max_hops} Hops)",
        lauf,
        meta={"art": "sanctions-check", "hops": max_hops},
    )
    return job.as_dict()
