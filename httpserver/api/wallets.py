"""Wallets-/UTXO-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations

from typing import Any


def api_cache_wallet_leeren(state: AppState, kennung: str) -> dict:
    """
    Löscht den Analyse-Cache eines Wallets: UTXO-Datei, Verlauf und
    Herkunftsbäume seiner bekannten Outputs. Gemeinsame Tx-/Block-Dateien
    und die Caches der anderen Wallets bleiben. Wallet-Alter bleibt.

    Auch verwaiste Cache-Kennungen (kein Wallet in der .env) sind erlaubt.
    """
    from server import (
        ApiError,
        _cache_kennung_hat_dateien,
        _wallet_cache_loeschen,
        _wallet_cache_loeschen_kennung,
        re,
        wallets_mod,
    )

    logs: list[str] = []

    def _log(text: str) -> None:
        s = str(text or "").strip()
        if s:
            logs.append(s)

    entry = wallets_mod.find_entry(state.entries, kennung)
    if entry is not None:
        bericht = _wallet_cache_loeschen(
            state, entry, mit_alter=False, on_log=_log,
        )
    else:
        kid = (kennung or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{16}", kid or ""):
            raise ApiError(404, "Wallet nicht gefunden.")
        if not _cache_kennung_hat_dateien(state, kid):
            raise ApiError(404, "Kein Cache zu dieser Kennung.")
        bericht = _wallet_cache_loeschen_kennung(
            state, kid, name=f"Cache {kid[:8]}…", mit_alter=True, on_log=_log,
        )
    return {
        "ok": True,
        "wallet_id": bericht["wallet_id"],
        "wallet_name": bericht["wallet_name"],
        "utxo_eintraege": bericht["utxo_eintraege"],
        "verlauf_eintraege": bericht["verlauf_eintraege"],
        "herkunft_eintraege": bericht["herkunft_eintraege"],
        "configured": entry is not None,
        "logs": logs,
    }


def api_cache_wallet_zeilen(state: AppState) -> dict:
    """
    Alle Cache-Zeilen für Danger Zone: konfigurierte Wallets + verwaiste
    Kennungen (stale cache ohne .env-Eintrag).
    """
    from server import (
        _aktive_cache_kennungen,
        _cache_datei_kennung,
        _cache_kennung_hat_dateien,
        json,
        main,
        utxos_mod,
        wallets_mod,
    )

    aktiv = _aktive_cache_kennungen(state)
    zeilen: list[dict] = []
    for entry in state.entries:
        kid = main._xpub_cache_key(entry.analyse_schluessel)
        utxos = utxos_mod.load_cached_utxos(
            entry.analyse_schluessel, state.cache_dir
        ) or []
        verlauf = main.load_xpub_verlauf_cache(
            entry.analyse_schluessel, state.cache_dir
        ) or []
        has = bool(utxos) or bool(verlauf) or _cache_kennung_hat_dateien(
            state, kid
        )
        # Auch leere konfigurierte Wallets listen (Löschen disabled client-side)
        zeilen.append({
            "id": wallets_mod.eintrag_id(entry),
            "name": entry.display_name,
            "configured": True,
            "has_cache": has,
            "utxo_count": len(utxos),
            "verlauf_count": len(verlauf),
            "stale": False,
        })

    gesehen = {str(z["id"]).lower() for z in zeilen}
    if state.cache_dir.is_dir():
        orphans: dict[str, dict] = {}
        for kind in state.cache_dir.iterdir():
            if not kind.is_file():
                continue
            kid = _cache_datei_kennung(kind.name)
            if not kid or kid in aktiv or kid in gesehen:
                continue
            slot = orphans.setdefault(kid, {
                "id": kid,
                "name": f"Cache {kid[:8]}…",
                "configured": False,
                "has_cache": True,
                "utxo_count": 0,
                "verlauf_count": 0,
                "stale": True,
            })
            low = kind.name.lower()
            if low == f"{kid}.json":
                try:
                    roh = json.loads(kind.read_text(encoding="utf-8"))
                    u = roh.get("utxos") if isinstance(roh, dict) else None
                    if isinstance(u, list):
                        slot["utxo_count"] = len(u)
                except (OSError, json.JSONDecodeError, UnicodeError):
                    pass
            elif low.endswith("_verlauf.json"):
                try:
                    roh = json.loads(kind.read_text(encoding="utf-8"))
                    e = (
                        roh.get("eintraege")
                        if isinstance(roh, dict)
                        else roh if isinstance(roh, list) else []
                    )
                    if isinstance(e, list):
                        slot["verlauf_count"] = len(e)
                except (OSError, json.JSONDecodeError, UnicodeError):
                    pass
        zeilen.extend(orphans.values())

    zeilen.sort(
        key=lambda z: (
            0 if z.get("configured") else 1,
            str(z.get("name") or "").lower(),
            str(z.get("id") or ""),
        )
    )
    return {"wallets": zeilen, "count": len(zeilen)}



def api_deskriptor_pruefen(state: AppState, payload: dict) -> dict:
    from server import (
        WalletEntry,
        _wallets_config_gesperrt,
        config_mod,
        main,
        re,
        wallets_mod,
    )

    _wallets_config_gesperrt(state)
    """
    Prüft einen eingefügten Text und beschreibt, was daraus würde.

    Bedient beides: den von Hand getippten Deskriptor und den kopierten
    Wallet-Export. Der Unterschied liegt nur im Text, nicht in der Absicht.

    Zurück kommt neben dem Befund die **erste Empfangsadresse**. Nur an ihr
    lässt sich vor dem Speichern erkennen, ob wirklich die eigene Wallet
    gemeint ist — ein Deskriptor sieht auch dann richtig aus, wenn ein
    Schlüssel vertauscht wurde.
    """
    text = str(payload.get("text", ""))
    if not text.strip():
        return {"gefunden": [], "fehler": ""}

    gefunden = config_mod.deskriptoren_aus_text(text)
    if not gefunden:
        if config_mod._XPRV_RE.search(text):
            return {
                "gefunden": [],
                "fehler": (
                    "Der Text enthält einen privaten Schlüssel. SatSage "
                    "schaut nur zu und darf ihn nicht entgegennehmen — bitte "
                    "den öffentlichen Deskriptor verwenden."
                ),
            }
        # BlueWallet-Cosigner-Datei: Name/Policy/Format + Fingerprint:xpub,
        # aber kein Output-Deskriptor — der steckt in der Specter-JSON.
        if re.search(r"(?i)bluewallet\s+multisig\s+setup", text) or (
            re.search(r"(?i)^policy:\s*\d+\s+of\s+\d+", text, re.M)
            and re.search(r"(?i)^format:\s*P2", text, re.M)
        ):
            return {
                "gefunden": [],
                "fehler": (
                    "Das ist eine BlueWallet-Cosigner-Datei (nur Schlüssel), "
                    "kein Output-Deskriptor. Bitte die Specter-JSON "
                    "(label/blockheight/descriptor) oder den Deskriptor "
                    "aus Sparrow/Core importieren."
                ),
            }
        return {
            "gefunden": [],
            "fehler": (
                "Kein verwendbarer Deskriptor gefunden. Bitkey: beide Zeilen "
                "„External:“ und „Internal:“ einfügen. Aggregierte "
                "Taproot-Schlüssel (musig) werden nicht unterstützt; sonst "
                "Tippfehler oder falsche Prüfsumme."
            ),
        }

    beschreibungen = []
    vorhanden_ids, _vorhanden_kenn = wallets_mod.vorhandene_abgleich(state.entries)
    for descriptor in gefunden:
        eintrag = WalletEntry(descriptor=descriptor)
        # Empfang #0 — nie Change, nie lexikografische Sortierung (Bitkey-Check).
        erste = config_mod.erste_empfangsadresse(eintrag)
        if not erste:
            erste = main.derive_address_at_index(descriptor, 0, 0) or ""
        schon = wallets_mod.finde_gleichwertigen_eintrag(state.entries, eintrag) is not None
        if not schon:
            schon = bool(
                wallets_mod.abgleich_ids_fuer_eintrag(eintrag) & vorhanden_ids
            )
        beschreibungen.append({
            "descriptor": descriptor,
            "is_multisig": eintrag.is_multisig,
            "script_type": eintrag.script_type,
            "script_type_label": wallets_mod.SCRIPT_TYPE_LABELS.get(
                eintrag.script_type, eintrag.script_type
            ),
            "threshold": eintrag.threshold,
            "cosigner_count": eintrag.cosigner_count,
            "xpubs_masked": (
                eintrag.masked_xpubs()
                if eintrag.is_multisig
                else ([eintrag.masked_xpub()] if eintrag.masked_xpub() else [])
            ),
            "erste_adresse": erste,
            "bereits_vorhanden": schon,
        })
    return {"gefunden": beschreibungen, "fehler": ""}


def api_sparrow_import(state: AppState, payload: dict) -> dict:
    """Alias — historischer Pfad; siehe ``api_wallet_export_import``."""
    from server import api_wallet_export_import

    return api_wallet_export_import(state, payload)


def api_wallet_export_import(state: AppState, payload: dict) -> dict:
    """
    Klartext-Exporte Sparrow / Wasabi (Auto-Erkennung) → .env + Cache.

    Kein Passwort. Sparrow: Descriptor + optional CSV. Wasabi: View-only-/
    Hardware-JSON (``ExtPubKey``) und optional RPC-Dumps. Mehrere Deskriptoren
    (z. B. SegWit+Taproot) werden als getrennte Wallets angelegt.
    """
    from server import (
        ApiError,
        LOGGER,
        WalletEntry,
        _dateien_aus_import_payload,
        _wallet_export_anlegen_und_cache,
        _wallets_config_gesperrt,
        config_mod,
        main,
    )

    _wallets_config_gesperrt(state)
    from core import wallet_export_import as export_mod

    try:
        roh_dateien = _dateien_aus_import_payload(payload)
        dateien = []
        for name, roh in roh_dateien.items():
            try:
                text = roh.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = roh.decode("latin-1", errors="replace")
            # Anzeigename ohne internen #2-Suffix aus Kollisions-Schutz.
            anzeige = name.split("#", 1)[0] if "#" in name else name
            dateien.append({"name": anzeige, "text": text})

        parsed = export_mod.parse_wallet_export_dateien(dateien)
        if not parsed.ok:
            raise ApiError(400, parsed.fehler or "Import fehlgeschlagen.")

        max_addr = int(payload.get("max_addresses", main.DEFAULT_MAX_ADDRESSES))
        read_only = bool(payload.get("read_only", False))
        bestaetigt = bool(payload.get("confirm", False))
        cache_source = (
            "wasabi_export" if "wasabi" in (parsed.formate or [])
            else "sparrow_csv"
        )

        neu_liste: list[WalletEntry] = []
        for i, desc in enumerate(parsed.descriptors):
            if i < len(parsed.namen) and str(parsed.namen[i] or "").strip():
                name = str(parsed.namen[i]).strip()
            elif parsed.name_vorschlag:
                name = (
                    parsed.name_vorschlag
                    if len(parsed.descriptors) == 1
                    else f"{parsed.name_vorschlag} #{i + 1}"
                )
            else:
                name = f"Import {i + 1}"
            try:
                neu = WalletEntry(
                    name=name,
                    descriptor=desc,
                    max_addresses=max_addr,
                    read_only=read_only,
                    origin=config_mod.WALLET_ORIGIN_WALLET_EXPORT,
                )
            except (TypeError, ValueError) as exc:
                raise ApiError(400, str(exc)) from exc
            if not neu.is_valid():
                raise ApiError(
                    400, f"Deskriptor lässt sich nicht ableiten: {desc[:64]}"
                )
            neu_liste.append(neu)

        return _wallet_export_anlegen_und_cache(
            state,
            neu_liste,
            parsed,
            bestaetigt=bestaetigt,
            cache_source=cache_source,
        )
    except ApiError:
        raise
    except Exception as exc:
        LOGGER.exception("wallet-export-import fehlgeschlagen")
        raise ApiError(500, f"Import fehlgeschlagen: {exc}") from exc


def api_wallet_export_suchen(state: AppState, *, on_log=None) -> dict:
    """Übliche Sparrow-/Wasabi-Ordner scannen (ohne Passwort)."""
    from server import (
        _wallets_config_gesperrt,
        wallets_mod,
    )

    _wallets_config_gesperrt(state)
    from core import wallet_discover as discover_mod

    logs: list[str] = []

    def _log(text: str) -> None:
        s = str(text or "").strip()
        if not s:
            return
        logs.append(s)
        if on_log:
            try:
                on_log(s)
            except Exception:
                pass

    vorhanden_ids, vorhanden_kenn = wallets_mod.vorhandene_abgleich(state.entries)
    try:
        env_werte = state.env().values()
    except Exception:
        env_werte = {}
    treffer = discover_mod.suche_lokale_wallets(
        vorhandene_wallet_ids=vorhanden_ids,
        vorhandene_schluessel_kennungen=vorhanden_kenn,
        on_log=_log,
        env=env_werte,
        mit_core_rpc=True,
    )
    wurzeln = [
        str(p) for p in discover_mod.standard_suchwurzeln() if p.is_dir()
    ]
    return {
        "wallets": [t.as_dict() for t in treffer],
        "roots": wurzeln,
        "count": len(treffer),
        "importable": sum(1 for t in treffer if t.importable),
        "logs": logs,
    }


def api_wallet_export_import_pfade(state: AppState, payload: dict) -> dict:
    """Importiert per Such-Liste gewählte lokale Dateipfade."""
    from server import (
        ApiError,
        Path,
        WalletEntry,
        _pfad_unter,
        _wallet_export_anlegen_und_cache,
        _wallets_config_gesperrt,
        config_mod,
        main,
    )

    _wallets_config_gesperrt(state)
    from core import wallet_discover as discover_mod

    pfade = payload.get("paths")
    if not isinstance(pfade, list) or not pfade:
        raise ApiError(400, "Feld 'paths' fehlt oder ist leer.")
    sauber = [str(p).strip() for p in pfade if str(p or "").strip()]
    if not sauber:
        raise ApiError(400, "Keine Pfade gewählt.")

    # Nur unter bekannten Wallet-Wurzeln bzw. corerpc: (kein beliebiges Lesen).
    erlaubt = discover_mod.standard_suchwurzeln()
    # Specter: …/wallets und Unterordner (main/test…)
    for w in list(erlaubt):
        if w.name.lower() == "wallets" and w.is_dir():
            try:
                erlaubt.extend([p for p in w.iterdir() if p.is_dir()])
            except OSError:
                pass
    for p in sauber:
        if str(p).startswith("corerpc:"):
            continue
        path = Path(p).expanduser()
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise ApiError(400, f"Pfad ungültig: {exc}") from exc
        if not any(
            _pfad_unter(resolved, w.resolve() if w.exists() else w)
            for w in erlaubt
        ):
            raise ApiError(
                400,
                f"„{path.name}“ liegt nicht in einem bekannten "
                "Wallet-Ordner (Sparrow/Wasabi/Specter/Electrum).",
            )

    try:
        env_werte = state.env().values()
    except Exception:
        env_werte = {}
    parsed = discover_mod.importiere_pfade(sauber, env=env_werte)
    if not parsed.ok:
        raise ApiError(400, parsed.fehler or "Import fehlgeschlagen.")

    max_addr = int(payload.get("max_addresses", main.DEFAULT_MAX_ADDRESSES))
    read_only = bool(payload.get("read_only", False))
    bestaetigt = bool(payload.get("confirm", False))
    formate = set(parsed.formate or [])
    if "wasabi" in formate:
        cache_source = "wasabi_export"
    elif "core" in formate:
        cache_source = "core_rpc"
    elif "specter" in formate:
        cache_source = "specter_export"
    elif "electrum" in formate:
        cache_source = "electrum_export"
    else:
        cache_source = "sparrow_csv"
    neu_liste: list[WalletEntry] = []
    for i, desc in enumerate(parsed.descriptors):
        if i < len(parsed.namen) and str(parsed.namen[i] or "").strip():
            name = str(parsed.namen[i]).strip()
        elif parsed.name_vorschlag:
            name = (
                parsed.name_vorschlag
                if len(parsed.descriptors) == 1
                else f"{parsed.name_vorschlag} #{i + 1}"
            )
        else:
            name = f"Import {i + 1}"
        try:
            neu = WalletEntry(
                name=name,
                descriptor=desc,
                max_addresses=max_addr,
                read_only=read_only,
                origin=config_mod.WALLET_ORIGIN_WALLET_EXPORT,
            )
        except (TypeError, ValueError) as exc:
            raise ApiError(400, str(exc)) from exc
        if not neu.is_valid():
            raise ApiError(400, f"Deskriptor lässt sich nicht ableiten: {desc[:64]}")
        neu_liste.append(neu)

    return _wallet_export_anlegen_und_cache(
        state,
        neu_liste,
        parsed,
        bestaetigt=bestaetigt,
        cache_source=cache_source,
    )


def api_wallet_export_adressen_nachziehen(state: AppState, payload: dict) -> dict:
    """
    Job: Adressen zu Export-Verlauf per eigenem Electrs nachziehen.

    Indexer muss konfiguriert sein; die Verbindung darf im Job noch kommen
    (Tor-Bootstrap nach Serverstart).
    """
    from server import (
        ApiError,
        _indexer_konfiguriert,
        _wallets_config_gesperrt,
        _warte_auf_eigenen_indexer,
        main,
        threading,
        wallets_mod,
    )

    _wallets_config_gesperrt(state)
    from core import export_adressen as adr_mod

    kennung = str(payload.get("wallet_id") or "").strip()
    if not kennung:
        raise ApiError(400, "wallet_id fehlt.")
    entry = wallets_mod.find_entry(state.entries, kennung)
    if entry is None:
        raise ApiError(404, "Wallet nicht gefunden.")

    if not _indexer_konfiguriert(state):
        raise ApiError(
            503,
            "Adressen nachziehen braucht Indexer "
            "(kein Electrs/Fulcrum konfiguriert). Später „Historie“ nutzen.",
        )

    schluessel = entry.analyse_schluessel
    name = entry.display_name
    max_a = entry.max_addresses

    def lauf(job):
        from core.jobs import Fortschritt, herzschlag

        stand = Fortschritt(job)
        halt = threading.Event()
        threading.Thread(
            target=herzschlag, args=(stand, halt), daemon=True,
        ).start()
        try:
            job.raise_if_cancelled()
            verlauf = main.load_xpub_verlauf_cache(schluessel, state.cache_dir) or []
            ohne = adr_mod.verlauf_ohne_adresse(verlauf)
            txids = adr_mod.unique_txids(ohne)
            if not txids:
                stand.phase("Keine Einträge ohne Adresse.")
                return {"filled": 0, "txids": 0}

            stand.phase(
                f"Adressen nachziehen für {name}: {len(txids)} Tx "
                f"ohne Adresse…"
            )
            client = _warte_auf_eigenen_indexer(state, stand, job)
            if client is None:
                raise RuntimeError(
                    "Adressen nachziehen braucht Indexer "
                    "(noch nicht verbunden — Tor startet ggf. noch). "
                    "Später erneut oder „Historie“."
                )

            own = adr_mod.eigene_adressen_mengen(
                entry, wallet_ctx=state.wallet_ctx,
            )
            if not own:
                # Ableitung erzwingen
                try:
                    if state.wallet_ctx is not None:
                        main.seed_wallet_addresses_from_utxo_cache(
                            state.wallet_ctx, [schluessel], state.cache_dir,
                        )
                except Exception:
                    pass
                own = adr_mod.eigene_adressen_mengen(
                    entry, wallet_ctx=state.wallet_ctx,
                )
            if not own:
                raise RuntimeError(
                    "Keine Ableitungs-Adressen für dieses Wallet — "
                    "Deskriptor prüfen."
                )

            def on_prog(text: str, *, sofort: bool = False) -> None:
                # sofort=True: neue Zwischenstände ins Log (Chunk-Grenzen)
                if sofort:
                    stand.phase(text)
                else:
                    stand.tick(text)

            # Electrs@Tor: request_batch (Chunk TOR_RPC_BATCH_SIZE); LAN: seriell.
            neu, stats = adr_mod.nachziehen_verlauf_adressen(
                verlauf,
                own=own,
                fulcrum_client=client,
                immutable_cache_dir=state.immutable_cache_dir,
                on_progress=on_prog,
                raise_if_cancelled=job.raise_if_cancelled,
            )
            job.raise_if_cancelled()
            main.save_xpub_verlauf_cache(
                schluessel,
                neu,
                state.cache_dir,
                incomplete=True,
            )
            try:
                main.seed_wallet_addresses_from_utxo_cache(
                    state.wallet_ctx, [schluessel], state.cache_dir,
                )
            except Exception:
                pass
            quelle = str(stats.get("quelle") or "")
            if quelle == "electrs-batch":
                q_hinweis = " · Electrs-Batch"
            elif quelle == "electrs":
                q_hinweis = " · Electrs"
            elif quelle == "cache":
                q_hinweis = " · nur lokaler Tx-Cache"
            else:
                q_hinweis = ""
            prev_n = int(stats.get("prev_txids") or 0)
            prev_hinweis = f", {prev_n} Prevout-Tx" if prev_n else ""
            cache_n = int(stats.get("cache_hits") or 0)
            electrs_n = int(stats.get("electrs_n") or 0)
            stand.phase(
                f"Adressen nachziehen fertig: {stats.get('filled', 0)} "
                f"Einträge, {stats.get('failed', 0)} ohne Treffer "
                f"({stats.get('txids', 0)} Tx{prev_hinweis}; "
                f"Cache {cache_n}, Electrs {electrs_n})"
                f"{q_hinweis}."
            )
            return stats
        finally:
            halt.set()
            stand.close()

    job = state.jobs.start(
        "export_adressen",
        f"Adressen nachziehen · {name}",
        lauf,
        meta={
            "art": "export_adressen",
            "wallet_id": kennung,
            "wallet_name": name,
            "max_addresses": max_a,
        },
    )
    return job.as_dict()


def api_wallets_cache_vorschau(state: AppState, payload: dict) -> dict:
    from server import (
        _entfernte_wallets,
        _wallet_cache_umfang,
        _wallets_aus_payload,
        _wallets_config_gesperrt,
        format_dateigroesse,
    )

    _wallets_config_gesperrt(state)
    """
    Welche Caches entfallen, wenn die übergebene Wallet-Liste gespeichert wird.

    Dieselbe Auflösung wie beim Speichern — damit Multisig-Schutz und
    Kennungen nicht von der Oberfläche nachgebaut werden müssen.
    """
    nachher = _wallets_aus_payload(state, payload)
    entfernt = _entfernte_wallets(state.entries, nachher)
    eintraege = [
        _wallet_cache_umfang(state, e, mit_alter=True) for e in entfernt
    ]
    bytes_gesamt = sum(int(e["bytes"]) for e in eintraege)
    return {
        "entfernt": eintraege,
        "bytes": bytes_gesamt,
        "groesse_label": format_dateigroesse(bytes_gesamt),
        "groesse_mb": round(bytes_gesamt / (1024 * 1024), 3),
    }


def api_save_wallets(state: AppState, payload: dict) -> dict:
    from server import (
        ApiError,
        BestaetigungNoetig,
        _entfernte_wallets,
        _wallet_cache_loeschen,
        _wallets_aus_payload,
        _wallets_config_gesperrt,
        format_dateigroesse,
        write_wallets,
    )

    _wallets_config_gesperrt(state)
    vorher = list(state.entries)
    entries = _wallets_aus_payload(state, payload)
    entfernt = _entfernte_wallets(vorher, entries)

    bestaetigt = bool(payload.get("confirm", False))
    try:
        sicherung = write_wallets(state.env(), entries, bestaetigt=bestaetigt)
    except BestaetigungNoetig as exc:
        # 409: nichts ist kaputt, es fehlt nur die Zustimmung. Die Oberfläche
        # zeigt die Warnungen und bietet ein "Trotzdem speichern" an.
        raise ApiError(409, " ".join(exc.warnungen)) from exc
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except OSError as exc:
        raise ApiError(500, "Interner Serverfehler.") from exc

    cache_bericht: list[dict] = []
    logs: list[str] = []

    def _log(text: str) -> None:
        s = str(text or "").strip()
        if s:
            logs.append(s)

    if bool(payload.get("cache_entfernte_loeschen")) and entfernt:
        # Vor reload: Einträge und Cache-Pfade beziehen sich noch auf den
        # vorherigen Zustand — genau die entfernten Wallets.
        # Teuer bei großen Import-Verläufen (je Tx Herkunftsdatei).
        for entry in entfernt:
            cache_bericht.append(
                _wallet_cache_loeschen(
                    state, entry, mit_alter=True, on_log=_log,
                )
            )

    state.reload()
    bytes_gesamt = sum(int(b.get("bytes") or 0) for b in cache_bericht)
    return {
        "saved": True,
        "backup": str(sicherung) if sicherung else None,
        "wallet_count": len(entries),
        "cache_entfernt": cache_bericht,
        "cache_bytes": bytes_gesamt,
        "cache_groesse_label": format_dateigroesse(bytes_gesamt) if cache_bericht else "",
        "logs": logs,
    }


def api_probe(state: AppState, payload: dict) -> dict:
    """
    Erkennt den Skripttyp — entweder für ein gespeichertes Wallet (wallet_id)
    oder für einen noch nicht gespeicherten Schlüssel (xpub).

    Gespeicherte Wallets werden über die Kennung angesprochen, weil die
    Oberfläche nur die maskierte Fassung kennt. Der volle Schlüssel bleibt so
    im Server und muss nicht durch den Browser zurückwandern.
    """
    from server import (
        ApiError,
        wallets_mod,
    )

    kennung = str(payload.get("wallet_id", "")).strip()
    if kennung:
        entry = wallets_mod.find_entry(state.entries, kennung)
        if entry is None:
            raise ApiError(404, "Wallet nicht gefunden.")
        xpub = entry.analyse_schluessel
    else:
        xpub = str(payload.get("xpub", "")).strip()
    if not xpub:
        raise ApiError(400, "Kein XPUB angegeben.")
    try:
        ergebnisse = wallets_mod.probe_script_types(xpub)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    return {
        "candidates": [e.as_dict() for e in ergebnisse],
        "suggestion": wallets_mod.suggest_script_type(ergebnisse),
        "note": (
            "Ohne Verbindung zur Blockchain lässt sich der Typ nicht sicher "
            "bestimmen. Vergleiche die Beispieladresse mit der ersten Adresse "
            "in deiner Wallet-Software."
        ),
    }


def api_wallet_utxos(state: AppState, kennung: str, query: dict) -> dict:
    from server import (
        ApiError,
        _eigene_adressen,
        _mit_mempool_pending,
        _query_flag,
        _seed_wallet_ctx_aus_caches,
        _sortierung,
        _verlaufs_anhang,
        sanctions_mod,
        utxos_mod,
        wallets_mod,
    )

    entry = wallets_mod.find_entry(state.entries, kennung)
    if entry is None:
        raise ApiError(404, "Wallet nicht gefunden.")

    try:
        limit = int(query.get("limit", ["0"])[0]) or None
    except (ValueError, TypeError):
        limit = None
    sort = _sortierung(query)
    # mempool=0: nur Cache (schneller Erst-Paint). Default: Pending über Electrs.
    mempool = _query_flag(query, "mempool", default=True)

    _seed_wallet_ctx_aus_caches(state)
    anhang = _verlaufs_anhang(state, [entry], limit=limit, sort=sort)
    gecacht = utxos_mod.load_cached_utxos(
        entry.analyse_schluessel,
        state.cache_dir,
        immutable_cache_dir=state.immutable_cache_dir,
    )
    if gecacht is None:
        return {
            "wallet": entry.display_name,
            "wallet_id": kennung,
            "has_cache": False,
            "total_count": 0,
            "total_sats": 0,
            "shown_count": 0,
            "shown_sats": 0,
            "utxos": [],
            "mempool_checked": False,
            **anhang,
        }

    if mempool:
        gecacht, anhang = _mit_mempool_pending(
            state,
            gecacht,
            anhang,
            limit=limit,
            sort=sort,
            xpub=entry.analyse_schluessel,
        )

    ergebnis = utxos_mod.rank_wallet_utxos(
        gecacht,
        limit=limit,
        wallet=state.wallet_ctx,
        immutable_cache_dir=state.immutable_cache_dir,
        own_addresses=_eigene_adressen(state),
        sort=sort,
    )
    ergebnis["sanctions"] = sanctions_mod.markiere_utxos(
        ergebnis["utxos"], cache_dir=state.sanctions_dir
    )
    ergebnis.update({
        "wallet": entry.display_name,
        "wallet_id": kennung,
        "has_cache": True,
        "mempool_checked": bool(mempool),
        **anhang,
    })
    return ergebnis


def api_wallet_empfang(state: AppState, kennung: str) -> dict:
    """
    Nächste Empfangsadresse für QR/Anzeige.

    * **Electrs/Fulcrum erreichbar** (eigener Node, oder öffentlicher nach
      Opt-in): unbenutzte Adresse per ``get_history`` / BIP44-Gap.
      Prozess-Cache nur, wenn die gemerkte Adresse noch history-frei ist
      (ein RPC).
    * **Sonst:** Schätzung aus UTXO-/Verlaufs-Cache + ``source=cache_estimate``
      (UI-Warnhinweis). Liefert nie XPUB/Deskriptor.
    """
    from server import (
        ApiError,
        _adresse_hat_history,
        _cache_bekannt_adressen,
        _empfang_antwort,
        _empfang_aus_cache_schaetzung,
        _empfang_electrum_client,
        _empfang_finalize,
        _empfang_max_index,
        _naechste_freie_empfang_electrs,
        wallets_mod,
    )

    if not state.context_bereit():
        raise ApiError(
            409,
            "Wallets werden noch vorbereitet. Einen Moment.",
        )
    entry = wallets_mod.find_entry(state.entries, kennung)
    if entry is None:
        raise ApiError(404, "Wallet nicht gefunden.")
    if not entry.is_valid():
        raise ApiError(400, "Wallet lässt sich nicht ableiten.")

    if getattr(entry, "read_only", False):
        return _empfang_antwort(
            kennung=kennung,
            entry=entry,
            address="",
            index=0,
            source="read_only",
            subscribed=False,
            watch_active=False,
            read_only=True,
        )

    max_index = _empfang_max_index(entry, state)
    bekannt, _ = _cache_bekannt_adressen(state, entry)
    client = _empfang_electrum_client(state)

    gemerkt = state.empfang_cache.get(kennung)
    if (
        gemerkt
        and gemerkt.get("address")
        and not gemerkt.get("read_only")
        and gemerkt["address"] not in bekannt
    ):
        if client is not None:
            if gemerkt.get("source") == "fulcrum":
                # Schnellpfad: eine History-Probe — Adresse noch unbenutzt?
                try:
                    if not _adresse_hat_history(client, gemerkt["address"]):
                        return dict(gemerkt)
                except Exception:
                    pass
                # Benutzt oder Electrs-Fehler → neu ermitteln.
            # cache_estimate bei lebendem Electrs verwerfen.
            state.empfang_cache.pop(kennung, None)
        else:
            # Ohne Electrs: gemerkte Adresse behalten, aber nicht als „unbenutzt“ behaupten.
            out = dict(gemerkt)
            if out.get("source") == "fulcrum":
                out["source"] = "cache_estimate"
            return out

    if client is not None:
        try:
            treffer = _naechste_freie_empfang_electrs(
                state, entry, client, max_index=max_index,
            )
            if treffer:
                address, index = treffer
                return _empfang_finalize(
                    state,
                    entry,
                    kennung=kennung,
                    address=address,
                    index=index,
                    source="fulcrum",
                    max_index=max_index,
                )
        except Exception:
            pass
        # Electrs erreichbar konfiguriert, Abfrage gescheitert → Schätzung + Warnung.

    return _empfang_aus_cache_schaetzung(
        state, entry, kennung=kennung, max_index=max_index,
    )


#: Lab-Regtest: Fountain/Faucet — nicht in SatSage-WALLET_*, nur als Fremdquelle.
_LAB_FAUCET_WALLET = "lab-faucet"


def api_lab_faucet_senden(state: AppState, payload: dict) -> dict:
    """
    Regtest: sendet Sats von ``lab-faucet`` an eine Empfangsadresse.

    Nur bei ``NETWORK=regtest``. Lässt die Tx im Mempool (kein Auto-Mine),
    damit Incoming-Animationen testbar bleiben.
    """
    from server import (
        ApiError,
        _LAB_FAUCET_WALLET,
    )

    werte = state.env().values()
    netz = (werte.get("NETWORK") or "").strip().lower()
    if netz not in ("regtest", "reg"):
        raise ApiError(403, "Lab-Faucet nur unter NETWORK=regtest.")

    adresse = str(payload.get("address") or payload.get("adresse") or "").strip()
    if not adresse:
        raise ApiError(400, "Empfangsadresse fehlt.")
    try:
        sats = int(payload.get("sats") or payload.get("amount_sats") or 0)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "Ungültige Satoshi-Menge.") from exc
    if sats < 546:
        raise ApiError(400, "Mindestens 546 sats (Dust-Grenze).")
    if sats > 50_000_000_000:
        raise ApiError(400, "Menge zu groß.")

    from core import bitcoind_rpc

    from dataclasses import replace

    cfg = bitcoind_rpc.config_from_env(werte) or bitcoind_rpc.config_utxo_from_env(werte)
    if cfg is None or not cfg.configured:
        raise ApiError(503, "Kein Core-RPC konfiguriert (NODE_IP / RPC*).")
    btc = sats / 100_000_000.0
    try:
        # loadwallet am Node-Root; Senden am Wallet-Pfad.
        root = bitcoind_rpc.BitcoinRpcClient(cfg, timeout=60.0)
        try:
            root.call("loadwallet", [_LAB_FAUCET_WALLET])
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "already loaded" not in msg and "duplicate" not in msg:
                pass
        client = bitcoind_rpc.BitcoinRpcClient(
            replace(cfg, wallet=_LAB_FAUCET_WALLET), timeout=60.0,
        )
        txid = client.call("sendtoaddress", [adresse, btc])
    except Exception as exc:
        raise ApiError(502, f"Faucet-Send fehlgeschlagen: {exc}") from exc

    return {
        "ok": True,
        "txid": txid,
        "address": adresse,
        "sats": sats,
        "from_wallet": _LAB_FAUCET_WALLET,
        "network": netz,
    }


def api_alle_utxos(state: AppState, query: dict) -> dict:
    """
    UTXOs über alle Wallets — Einstieg für die Herkunftsansicht.

    Bestand und Verlauf aus dem Cache. Optional Mempool-Pending-Spends
    nur über den eigenen Electrs (sonst kein Netz).

    ``mempool=0``: kein Electrs-Rundlauf (Herkunftsliste / Sprung aus Wallet).
    """
    from server import (
        _eigene_adressen,
        _mit_mempool_pending,
        _seed_wallet_ctx_aus_caches,
        _sortierung,
        _verlaufs_anhang,
        sanctions_mod,
        utxos_mod,
    )

    _seed_wallet_ctx_aus_caches(state)
    gesammelt: list[dict] = []
    ohne_cache: list[str] = []
    for entry in state.entries:
        gecacht = utxos_mod.load_cached_utxos(
            entry.analyse_schluessel,
            state.cache_dir,
            immutable_cache_dir=state.immutable_cache_dir,
        )
        if gecacht is None:
            ohne_cache.append(entry.display_name)
            continue
        gesammelt.extend(gecacht)

    try:
        limit = int(query.get("limit", ["0"])[0]) or None
    except (ValueError, TypeError):
        limit = None
    sort = _sortierung(query)
    mempool_an = str((query.get("mempool") or ["1"])[0]).strip().lower() not in (
        "0", "false", "no", "nein", "off",
    )

    anhang = _verlaufs_anhang(
        state, state.analyse_entries, limit=limit, sort=sort,
    )
    if mempool_an:
        gesammelt, anhang = _mit_mempool_pending(
            state, gesammelt, anhang, limit=limit, sort=sort,
        )

    ergebnis = utxos_mod.rank_wallet_utxos(
        gesammelt,
        limit=limit,
        wallet=state.wallet_ctx,
        immutable_cache_dir=state.immutable_cache_dir,
        own_addresses=_eigene_adressen(state),
        sort=sort,
    )
    ergebnis["sanctions"] = sanctions_mod.markiere_utxos(
        ergebnis["utxos"], cache_dir=state.sanctions_dir
    )
    ergebnis["wallets_ohne_cache"] = ohne_cache
    ergebnis.update(anhang)
    ergebnis["wallet_count"] = len(state.entries)
    return ergebnis


def api_wallet_tip_sync(state: AppState, payload: dict | None = None) -> dict:
    """
    Tip-Nachzug manuell (ohne Server-Neustart).

    Kein Fullscan — wie Start-Aktualisierung. Optional ``wallet_id`` für ein
    Wallet; sonst alle mit Cache.
    """
    from server import (
        ApiError,
        main,
        starte_wallet_aktualisierung,
        tip_sync_laeuft,
        wallets_mod,
    )

    payload = payload if isinstance(payload, dict) else {}
    wid = str(payload.get("wallet_id") or "").strip()
    ids = [wid] if wid else None
    if wid:
        entry = wallets_mod.find_entry(state.entries, wid)
        if entry is None:
            raise ApiError(404, "Wallet nicht gefunden.")
        if not main.load_xpub_cache_entry(
            entry.analyse_schluessel, state.cache_dir
        ):
            raise ApiError(
                409,
                "Kein UTXO-Cache — zuerst UTXO-Scan (Fullscan), "
                "danach Tip-Nachzug.",
            )
    if tip_sync_laeuft(state):
        raise ApiError(409, "Tip-Nachzug läuft bereits.")
    daten = starte_wallet_aktualisierung(
        state, erzwingen=True, wallet_ids=ids,
    )
    if daten is None:
        raise ApiError(
            409,
            "Nichts zu aktualisieren (kein Cache oder Job läuft schon).",
        )
    return {"job": daten, "job_id": daten.get("id")}
