"""Wallet-Export-/Indexer-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports.
"""

from __future__ import annotations

def _wallets_config_gesperrt(state: AppState) -> None:
    """Verhindert lokale Wallet-Änderungen im Specter-Modus."""

    from server import ApiError

    if state.managed_by == "specter":
        raise ApiError(403, "Wallets werden von Specter verwaltet und können hier nicht geändert werden.")


def _electrum_indexer(werte: dict | None) -> str:
    """``electrs`` oder ``fulcrum`` aus Plattform-Env.

    StartOS setzt den Wert über die Action „Select Indexer“, Umbrel über die
    gewählte ``electrs``-Dependency. Ohne Angabe bleibt es bei ``electrs``.
    """
    roh = str((werte or {}).get("SATSAGE_ELECTRUM_INDEXER") or "").strip().lower()
    if roh in ("fulcrum", "electrs"):
        return roh
    # Legacy: nur ELECTRS_HOST / FULCRUM_HOST ohne Indexer-Flag → electrs-Default.
    return "electrs"


def _wallet_export_anlegen_und_cache(
    state: AppState,
    neu_liste: list[WalletEntry],
    parsed,
    *,
    bestaetigt: bool,
    cache_source: str,
) -> dict:

    from server import (
        ApiError,
        BestaetigungNoetig,
        config_mod,
        main,
        wallets_mod,
        write_wallets,
    )

    if not neu_liste:
        raise ApiError(400, "Keine Wallets zum Anlegen.")

    from dataclasses import replace as dc_replace

    vorhanden_ids, _kenn = wallets_mod.vorhandene_abgleich(state.entries)
    entries = list(state.entries)
    angelegt = 0
    schon_da_n = 0
    origin_touch = False
    for neu in neu_liste:
        wid = neu.wallet_id()
        # zpub vs. Deskriptor: gleicher Schlüssel → nicht nochmal anlegen.
        alt = wallets_mod.finde_gleichwertigen_eintrag(entries, neu)
        if alt is None and wid in vorhanden_ids:
            alt = wallets_mod.find_entry(entries, wid)
        if alt is not None:
            schon_da_n += 1
            idx = next(
                (i for i, e in enumerate(entries) if e is alt or wallets_mod.eintrag_id(e) == wallets_mod.eintrag_id(alt)),
                None,
            )
            if idx is not None:
                alt_e = entries[idx]
                soll_origin = (
                    getattr(neu, "origin", "") or ""
                ).strip() or config_mod.WALLET_ORIGIN_WALLET_EXPORT
                if (getattr(alt_e, "origin", "") or "").strip() != soll_origin:
                    entries[idx] = dc_replace(alt_e, origin=soll_origin)
                    origin_touch = True
            continue
        entries.append(neu)
        vorhanden_ids |= wallets_mod.abgleich_ids_fuer_eintrag(neu)
        angelegt += 1

    if angelegt or origin_touch:
        try:
            write_wallets(state.env(), entries, bestaetigt=bestaetigt)
        except BestaetigungNoetig as exc:
            raise ApiError(409, " ".join(exc.warnungen)) from exc
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        except OSError as exc:
            raise ApiError(500, "Interner Serverfehler.") from exc
        state.reload()

    # Cache je angelegtem/bekanntem Wallet (SegWit+Taproot getrennt).
    utxo_n = 0
    verlauf_n = 0
    seed_keys: list[str] = []
    importierte: list[tuple[str, str, str]] = []  # name_lower, id, name
    try:
        for neu in neu_liste:
            wid_i = neu.wallet_id()
            ein = wallets_mod.find_entry(state.entries, wid_i) or neu
            schluessel = ein.analyse_schluessel
            seed_keys.append(schluessel)
            name_i = ein.display_name or neu.display_name or wid_i
            importierte.append((name_i.lower(), wid_i, name_i))
            utxos_i = _export_eintraege_fuer_wallet(parsed.utxos, ein)
            verlauf_i = _export_eintraege_fuer_wallet(parsed.verlauf, ein)
            addrs_i = _export_adressen_fuer_wallet(parsed.adressen, ein)
            # Immer UTXO-Cache anlegen (auch leer) — sonst has_cache/Pille fehlen
            # bei reinem Verlauf-Import (Wasabi ohne offene Coins).
            if utxos_i or verlauf_i or addrs_i or parsed.adressen:
                main.save_xpub_utxo_cache(
                    schluessel,
                    utxos_i or [],
                    state.cache_dir,
                    source=cache_source,
                    max_addresses=ein.max_addresses,
                )
                utxo_n += len(utxos_i or [])
            if verlauf_i:
                bisher = main.load_xpub_verlauf_cache(
                    schluessel, state.cache_dir
                ) or []
                merge = list(bisher)
                gesehen = {
                    f"{e.get('txid')}:{e.get('vout')}:{e.get('spent')}"
                    for e in merge
                    if isinstance(e, dict)
                }
                for e in verlauf_i:
                    key = f"{e.get('txid')}:{e.get('vout')}:{e.get('spent')}"
                    if key in gesehen:
                        continue
                    gesehen.add(key)
                    merge.append(e)
                # Store-/CSV-Verlauf gilt als vollständig genug; Adressen gesetzt.
                main.save_xpub_verlauf_cache(
                    schluessel,
                    merge,
                    state.cache_dir,
                    scanned_addresses=addrs_i or parsed.adressen or None,
                    incomplete=False if (utxos_i or verlauf_i) else True,
                )
                verlauf_n += len(verlauf_i)
            elif addrs_i or parsed.adressen:
                main.save_xpub_verlauf_cache(
                    schluessel,
                    main.load_xpub_verlauf_cache(schluessel, state.cache_dir)
                    or [],
                    state.cache_dir,
                    scanned_addresses=addrs_i or parsed.adressen,
                    incomplete=True,
                )
    except main.CacheDiskFullError as exc:
        raise ApiError(507, str(exc)) from exc
    except OSError as exc:
        raise ApiError(500, "Cache schreiben fehlgeschlagen.") from exc

    importierte.sort(key=lambda t: (t[0], t[1]))
    prim_id = importierte[0][1] if importierte else neu_liste[0].wallet_id()
    bekannt = wallets_mod.find_entry(state.entries, prim_id) or neu_liste[0]

    try:
        main.seed_wallet_addresses_from_utxo_cache(
            state.wallet_ctx, seed_keys or [bekannt.analyse_schluessel],
            state.cache_dir,
        )
    except Exception:
        pass

    erste = config_mod.erste_empfangsadresse(bekannt) or ""
    nachziehen = _export_adressen_nachziehen_meta(state, bekannt)
    return {
        "saved": True,
        "already_present": angelegt == 0 and schon_da_n > 0,
        "wallets_added": angelegt,
        "wallets_existing": schon_da_n,
        "wallet_id": prim_id,
        "wallet_ids": [t[1] for t in importierte],
        "wallets": [
            {"id": t[1], "name": t[2]} for t in importierte
        ],
        "name": bekannt.display_name,
        "format": parsed.format_label,
        "descriptor": bool(bekannt.descriptor),
        "is_multisig": bekannt.is_multisig,
        "erste_adresse": erste,
        "utxo_count": utxo_n,
        "verlauf_count": verlauf_n,
        "address_count": len(parsed.adressen),
        "files": parsed.dateien,
        "hinweise": parsed.hinweise,
        "wallet_count": len(state.entries),
        "address_nachziehen": nachziehen,
    }


def _export_script_familie(entry: WalletEntry) -> str:
    """Grobe Skriptfamilie für Wasabi-SegWit/Taproot-Split."""
    d = (getattr(entry, "descriptor", None) or "").lower()
    if d.startswith("tr(") or "/86h/" in d or "/86'/" in d:
        return "tr"
    if "wsh(" in d or "sh(wsh" in d:
        return "wsh"
    if "wpkh(" in d or "sh(wpkh" in d:
        return "wpkh"
    x = (getattr(entry, "xpub", None) or "").lower()
    if x.startswith(("zpub", "vpub")):
        return "wpkh"
    if x.startswith(("xpub", "tpub")):
        return "mixed"
    return "mixed"


def _export_adresse_familie(addr: str) -> str:
    a = (addr or "").strip().lower()
    if a.startswith(("bc1p", "tb1p", "bcrt1p")):
        return "tr"
    if a.startswith(("bc1q", "tb1q", "bcrt1q")):
        return "wpkh"
    if a.startswith(("3", "2")):
        return "sh"
    if a.startswith(("1", "m", "n")):
        return "pkh"
    return "other"


def _export_eintraege_fuer_wallet(
    eintraege: list | None, entry: WalletEntry,
) -> list:
    """Filtert UTXO/Verlauf-Einträge auf die Skriptfamilie des Wallets."""
    if not eintraege:
        return []
    fam = _export_script_familie(entry)
    if fam == "mixed":
        return list(eintraege)
    out = []
    for e in eintraege:
        if not isinstance(e, dict):
            continue
        addr = str(e.get("address") or "")
        if not addr:
            out.append(e)
            continue
        af = _export_adresse_familie(addr)
        if fam == "tr" and af == "tr":
            out.append(e)
        elif fam == "wpkh" and af in ("wpkh", "sh", "pkh"):
            out.append(e)
        elif fam == af:
            out.append(e)
    return out


def _export_adressen_fuer_wallet(
    adressen: list | None, entry: WalletEntry,
) -> list[str]:
    if not adressen:
        return []
    fam = _export_script_familie(entry)
    if fam == "mixed":
        return [str(a) for a in adressen if a]
    out = []
    for a in adressen:
        s = str(a or "").strip()
        if not s:
            continue
        af = _export_adresse_familie(s)
        if fam == "tr" and af == "tr":
            out.append(s)
        elif fam == "wpkh" and af in ("wpkh", "sh", "pkh"):
            out.append(s)
        elif fam == af:
            out.append(s)
    return out


def _indexer_konfiguriert(state: AppState) -> bool:
    """Eigener Electrs/Fulcrum in der .env (LAN oder Onion) — nicht öffentlicher Pool."""
    try:
        werte = state.env().values()
    except Exception:
        return False
    return bool(
        (werte.get("FULCRUM_HOST") or "").strip()
        or (werte.get("FULCRUM_TOR") or "").strip()
    )


#: Nach Import oft noch Tor-Bootstrap — Job wartet, statt still abzubrechen.
_INDEXER_WARTE_S = 120.0
_INDEXER_WARTE_SCHRITT_S = 3.0


def _warte_auf_eigenen_indexer(state: AppState, stand, job, *, timeout_s: float = _INDEXER_WARTE_S):
    """
    Electrs/Fulcrum holen; bei konfiguriertem Onion/Tor mehrfach versuchen.

    Loggt klar, wenn der Indexer noch fehlt (typisch: Tor startet länger als
    der Import dauert). Rückgabe Client oder ``None``.
    """
    import time

    from server import _eigener_fulcrum_client

    client = None
    try:
        client = _eigener_fulcrum_client(state)
    except Exception:
        client = None
    if client is not None:
        return client

    if not _indexer_konfiguriert(state):
        stand.phase(
            "Adressen nachziehen braucht Indexer "
            "(kein Electrs/Fulcrum konfiguriert)."
        )
        return None

    stand.phase(
        "Adressen nachziehen braucht Indexer — noch nicht verbunden "
        "(z. B. Tor startet noch). Warte…"
    )
    deadline = time.monotonic() + max(5.0, float(timeout_s))
    n = 0
    while time.monotonic() < deadline:
        job.raise_if_cancelled()
        time.sleep(_INDEXER_WARTE_SCHRITT_S)
        n += 1
        try:
            client = _eigener_fulcrum_client(state)
        except Exception:
            client = None
        if client is not None:
            stand.phase("Indexer verbunden — Adressen nachziehen…")
            return client
        if n == 1 or n % 5 == 0:
            rest = max(0, int(deadline - time.monotonic()))
            stand.phase(
                f"Adressen nachziehen braucht Indexer — warte weiter "
                f"(noch ~{rest}s)…"
            )
    stand.phase(
        "Adressen nachziehen braucht Indexer "
        "(Timeout — Tor/Electrs nicht erreichbar). "
        "Später erneut oder „Historie“."
    )
    return None


def _export_adressen_nachziehen_meta(state: AppState, entry: WalletEntry) -> dict:
    """
    Wie viele Tx im Verlauf noch ohne Adresse sind und ob Electrs greifbar ist.

    *indexer_configured*: FULCRUM_HOST/TOR gesetzt — Job kann auf Tor warten.
    *electrs*: jetzt schon verbunden (sonst warte der Job).
    """
    from server import _eigener_fulcrum_client, main, wallets_mod

    from core import export_adressen as adr_mod

    verlauf = main.load_xpub_verlauf_cache(
        entry.analyse_schluessel, state.cache_dir
    ) or []
    ohne = adr_mod.verlauf_ohne_adresse(verlauf)
    txids = adr_mod.unique_txids(ohne)
    n = len(txids)
    configured = _indexer_konfiguriert(state)
    electrs = False
    try:
        electrs = _eigener_fulcrum_client(state) is not None
    except Exception:
        electrs = False
    # Konfiguriert genügt für Auto/Nachfrage — Job wartet auf Tor-Bootstrap.
    kann = bool(configured and n > 0)
    return {
        "wallet_id": wallets_mod.eintrag_id(entry),
        "name": entry.display_name,
        "pending_txids": n,
        "pending_entries": len(ohne),
        "electrs": electrs,
        "indexer_configured": configured,
        "auto_max": adr_mod.NACHZIEHEN_AUTO_MAX,
        "auto_start": bool(kann and n <= adr_mod.NACHZIEHEN_AUTO_MAX),
        "needs_confirm": bool(kann and n > adr_mod.NACHZIEHEN_AUTO_MAX),
    }


def _wallets_aus_payload(state: AppState, payload: dict) -> list[WalletEntry]:
    """
    Wandelt die Wallet-Liste aus der Oberfläche in Einträge um.

    Enthält denselben Multisig-Schutz wie beim Speichern: ungesendete Multisig
    bleiben erhalten, damit eine ältere Oberfläche sie nicht still löscht.
    """
    from server import (
        ApiError,
        WalletEntry,
        config_mod,
        main,
        wallets_mod,
    )

    roh = payload.get("wallets")
    if not isinstance(roh, list):
        raise ApiError(400, "Feld 'wallets' fehlt oder ist keine Liste.")

    vorhanden = state.entries
    entries: list[WalletEntry] = []
    for index, eintrag in enumerate(roh, start=1):
        if not isinstance(eintrag, dict):
            raise ApiError(400, f"Wallet {index}: unerwartetes Format.")

        # Bestehende Wallets kommen mit ihrer Kennung zurück, nicht mit dem
        # Schlüssel: Die Oberfläche kennt nur die maskierte Fassung. Nur neu
        # eingefügte Wallets bringen einen XPUB im Klartext mit.
        # Neu angelegte Multisig: Sie kommt mit ihrem Deskriptor, nicht mit
        # einer Kennung — die entsteht erst daraus.
        neuer_deskriptor = str(eintrag.get("descriptor", "")).strip()
        if neuer_deskriptor and not str(eintrag.get("id", "")).strip():
            try:
                origin = str(eintrag.get("origin") or "").strip() or (
                    config_mod.WALLET_ORIGIN_DESCRIPTOR
                )
                entries.append(WalletEntry(
                    name=str(eintrag.get("name", "")),
                    descriptor=neuer_deskriptor,
                    max_addresses=int(
                        eintrag.get("max_addresses", main.DEFAULT_MAX_ADDRESSES)
                    ),
                    read_only=bool(eintrag.get("read_only", False)),
                    origin=origin,
                ))
            except (TypeError, ValueError) as exc:
                raise ApiError(400, f"Wallet {index}: {exc}") from exc
            continue

        kennung = str(eintrag.get("id", "")).strip()
        bekannt = None
        if kennung:
            bekannt = wallets_mod.find_entry(vorhanden, kennung)
            if bekannt is None:
                raise ApiError(400, f"Wallet {index}: unbekannte Kennung.")
            xpub = bekannt.xpub
        else:
            xpub = str(eintrag.get("xpub", ""))

        try:
            if bekannt is not None and bekannt.is_multisig:
                # Multisig kommt nur über die Kennung zurück — die Oberfläche
                # kann sie nicht bearbeiten. Cosigner, Schwellwert und
                # Skripttyp bleiben deshalb, wie sie in der .env stehen;
                # änderbar sind allein Name und Scan-Tiefe.
                entries.append(WalletEntry(
                    name=str(eintrag.get("name", "")) or bekannt.name,
                    xpubs=list(bekannt.xpubs),
                    threshold=bekannt.threshold,
                    script_type=bekannt.script_type,
                    descriptor=bekannt.descriptor,
                    max_addresses=int(
                        eintrag.get("max_addresses", bekannt.max_addresses)
                    ),
                    read_only=bool(
                        eintrag.get("read_only", bekannt.read_only)
                    ),
                    origin=bekannt.origin,
                ))
                continue

            if bekannt is not None and bekannt.descriptor and not bekannt.is_multisig:
                # Single-Sig-Policy (Wasabi WPKH …): Deskriptor behalten.
                entries.append(WalletEntry(
                    name=str(eintrag.get("name", "")) or bekannt.name,
                    descriptor=bekannt.descriptor,
                    script_type=str(
                        eintrag.get("script_type", bekannt.script_type)
                    ),
                    max_addresses=int(
                        eintrag.get("max_addresses", bekannt.max_addresses)
                    ),
                    read_only=bool(
                        eintrag.get("read_only", bekannt.read_only)
                    ),
                    origin=bekannt.origin,
                ))
                continue

            origin = str(eintrag.get("origin") or "").strip()
            if not origin and bekannt is not None:
                origin = bekannt.origin
            if not origin and not kennung:
                origin = config_mod.WALLET_ORIGIN_XPUB
            entries.append(WalletEntry(
                xpub=xpub,
                name=str(eintrag.get("name", "")),
                script_type=str(eintrag.get("script_type", "auto")),
                max_addresses=int(eintrag.get("max_addresses", main.DEFAULT_MAX_ADDRESSES)),
                read_only=bool(eintrag.get("read_only", False)),
                origin=origin,
            ))
        except (TypeError, ValueError) as exc:
            raise ApiError(400, f"Wallet {index}: {exc}") from exc

    # Netz für den Fall, dass die Oberfläche Multisig-Einträge gar nicht
    # zurückschickt — eine ältere Fassung kennt sie nicht. Sie stillschweigend
    # zu verlieren wäre nicht wiedergutzumachen: Die Cosigner stehen dann
    # nirgends mehr.
    gesendete_ids = {wallets_mod.eintrag_id(e) for e in entries}
    for vorhandener in vorhanden:
        if vorhandener.is_multisig and (
            wallets_mod.eintrag_id(vorhandener) not in gesendete_ids
        ):
            entries.append(vorhandener)
    return entries


def _entfernte_wallets(
    vorher: list[WalletEntry],
    nachher: list[WalletEntry],
) -> list[WalletEntry]:

    from server import wallets_mod

    behalten = {wallets_mod.eintrag_id(e) for e in nachher}
    return [e for e in vorher if wallets_mod.eintrag_id(e) not in behalten]
