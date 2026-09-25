"""Steuer-/Selbstanzeige-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports.
Gemeinsame Cache-UTXO-Utils (_alle_gecachten_*, _utxo_schluessel) liegen hier,
weil Steuer der primäre Nutzer ist; Trace late-importiert über server.
"""

from __future__ import annotations


def _alle_gecachten_utxos(state: AppState) -> list[dict]:
    """UTXOs aller Wallets aus dem Cache — ohne Netzzugriff."""
    from server import utxos_mod

    gesammelt: list[dict] = []
    for entry in state.entries:
        gecacht = utxos_mod.load_cached_utxos(
            entry.analyse_schluessel,
            state.cache_dir,
            immutable_cache_dir=state.immutable_cache_dir,
        )
        if gecacht:
            gesammelt.extend(gecacht)
    return gesammelt


def _alle_gecachten_verlaeufe(state: AppState) -> list[dict]:
    """
    Vollständiger Verlauf aller Wallets aus dem Cache — auch ausgegebene
    Outputs. Leer, solange er nicht erhoben wurde.
    """
    from server import main

    gesammelt: list[dict] = []
    for entry in state.analyse_entries:
        eintraege = main.load_xpub_verlauf_cache(entry.analyse_schluessel, state.cache_dir)
        if eintraege:
            gesammelt.extend(eintraege)
    return gesammelt


def _utxo_schluessel(eintrag: dict) -> tuple[str, int] | None:
    txid = str(eintrag.get("txid") or "").strip().lower()
    if not txid:
        return None
    try:
        vout = int(eintrag.get("vout", 0))
    except (TypeError, ValueError):
        return None
    return (txid, vout)


def _steuer_verlauf_ohne_phantom_unspent(
    verlauf: list[dict],
    bestand: list[dict] | None,
) -> tuple[list[dict], int]:
    """
    Verlauf für Steuer: echte Abgänge behalten, Phantom-„unspent“ streichen.

    Phantom = im Verlauf ``spent`` falsch/fehlend (wirkt unspent), aber
    ``txid:vout`` steht nicht (mehr) im aktuellen UTXO-Cache — typisch nach
    Konsolidierung/Ausgaben, wenn der Verlauf ``spent`` nicht gesetzt hat.
    Ohne UTXO-Cache kein Abgleich möglich → Verlauf unverändert.
    """
    if not bestand:
        return list(verlauf), 0
    live = set()
    for u in bestand:
        key = _utxo_schluessel(u)
        if key:
            live.add(key)
    gefiltert: list[dict] = []
    phantome = 0
    gesehen: set[tuple[str, int]] = set()
    for eintrag in verlauf:
        key = _utxo_schluessel(eintrag)
        if eintrag.get("spent"):
            gefiltert.append(eintrag)
            if key:
                gesehen.add(key)
            continue
        if key is None:
            continue
        if key in live:
            gefiltert.append(eintrag)
            gesehen.add(key)
        else:
            phantome += 1
    # UTXOs, die der Verlauf noch nicht kennt (frischer Empfang).
    for u in bestand:
        key = _utxo_schluessel(u)
        if key is None or key in gesehen:
            continue
        neu = dict(u)
        neu.setdefault("spent", False)
        gefiltert.append(neu)
        gesehen.add(key)
    return gefiltert, phantome


def _steuer_grundlage(state: AppState) -> tuple[list[dict], list[str]]:
    """
    Woraus die Steuerauswertung rechnet — **je Wallet** entschieden.

    Der Verlauf gewinnt, wo er vorliegt (Abgänge + Empfänge). Unspent-Zeilen
    aus dem Verlauf, die nicht im aktuellen UTXO-Cache stehen, werden als
    Phantom verworfen. Wo kein Verlauf da ist, bleibt der UTXO-Bestand.

    Die Entscheidung darf nicht global fallen. Sonst verschwänden alle Wallets
    ohne Verlauf aus der Aufstellung, sobald ein einziges einen hat — in einer
    Steuerangabe ein stiller Verlust, den niemand bemerkt.

    Liefert *(eintraege, wallets_ohne_verlauf)*; die zweite Liste gehört in die
    Anzeige, damit eine gemischte Grundlage auffällt.
    """
    from server import (
        main,
        utxos_mod,
        _seed_wallet_ctx_aus_caches,
    )

    # Verlaufsadressen vor resolve_address (sonst HD-Suche × MAX_TRACE).
    _seed_wallet_ctx_aus_caches(state)

    eintraege: list[dict] = []
    ohne_verlauf: list[str] = []
    phantome_gesamt = 0

    for entry in state.analyse_entries:
        schluessel = entry.analyse_schluessel
        verlauf = main.load_xpub_verlauf_cache(schluessel, state.cache_dir)
        gecacht = utxos_mod.load_cached_utxos(
            schluessel,
            state.cache_dir,
            immutable_cache_dir=state.immutable_cache_dir,
        )
        if verlauf:
            bereinigt, phantome = _steuer_verlauf_ohne_phantom_unspent(
                verlauf, gecacht,
            )
            phantome_gesamt += phantome
            eintraege.extend(bereinigt)
            continue
        # Auch bei leerem Verlauf: Eine leere Liste kann ein abgebrochener
        # Lauf sein. Sie als „dieses Wallet ist leer" zu lesen wäre falsch.
        ohne_verlauf.append(entry.display_name)
        if gecacht:
            eintraege.extend(gecacht)

    if phantome_gesamt and hasattr(state, "_steuer_phantome"):
        state._steuer_phantome = phantome_gesamt
    else:
        try:
            state._steuer_phantome = phantome_gesamt  # type: ignore[attr-defined]
        except Exception:
            pass

    return eintraege, ohne_verlauf


def _steuer_auswertung(
    state: AppState, query: dict, lang: str | None = None,
) -> dict:
    from server import (
        ApiError,
        tax_mod,
    )

    utxos, ohne_verlauf = _steuer_grundlage(state)
    jahre = tax_mod.verfuegbare_jahre(utxos)

    try:
        jahr = int(query.get("jahr", [""])[0])
    except (ValueError, TypeError, IndexError):
        jahr = jahre[0] if jahre else __import__("datetime").date.today().year

    einstellungen = tax_mod.lese_steuer_einstellungen(state.env().values())
    try:
        frist = int(query.get("frist", [""])[0])
    except (ValueError, TypeError, IndexError):
        frist = einstellungen["haltefrist_jahre"]

    stichtag_roh = query.get("stichtag", [None])[0]
    if stichtag_roh is None:
        stichtag = tax_mod.parse_stichtag(einstellungen["stichtag"])
    else:
        try:
            stichtag = tax_mod.parse_stichtag(stichtag_roh)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc

    anschaffung_roh = query.get("anschaffung", [None])[0]
    if anschaffung_roh is None:
        anschaffung = einstellungen["anschaffung"]
    else:
        anschaffung = tax_mod.parse_anschaffung(anschaffung_roh)

    auswertung = tax_mod.auswerten(
        utxos, jahr,
        haltefrist_jahre=max(0, frist),
        stichtag=stichtag,
        anschaffung=anschaffung,
        wallet=state.wallet_ctx,
        immutable_cache_dir=state.immutable_cache_dir,
        lang=lang,
    )
    auswertung["verfuegbare_jahre"] = jahre
    auswertung["ohne_verlauf"] = ohne_verlauf
    phantome = int(getattr(state, "_steuer_phantome", 0) or 0)
    auswertung["phantom_unspent_count"] = phantome
    from core import i18n

    def _h(key: str, **vars) -> str:
        return i18n.t_lang(lang, key, **vars)

    if phantome:
        auswertung["hinweise"].insert(0, _h("tax.hintPhantom", anzahl=phantome))
    if ohne_verlauf:
        # Eine gemischte Grundlage muss auffallen: Für die einen Wallets sind
        # Veräußerungen erfasst, für die anderen nur der heutige Bestand.
        namen = ", ".join(
            _h("common.quoteOpen") + name + _h("common.quoteClose")
            for name in ohne_verlauf
        )
        schluessel = (
            "tax.hintNoHistoryOne" if len(ohne_verlauf) == 1
            else "tax.hintNoHistoryMany"
        )
        auswertung["hinweise"].insert(0, _h(schluessel, wallets=namen))
    return auswertung


def _selbstanzeige_report(state: AppState, payload: dict) -> dict:
    from core import selbstanzeige as sa

    from server import (
        ApiError,
        tax_mod,
    )

    utxos, _ohne = _steuer_grundlage(state)
    try:
        jahr = int(payload.get("jahr") or 0)
    except (TypeError, ValueError):
        jahr = 0
    if jahr <= 0:
        jahre = tax_mod.verfuegbare_jahre(utxos)
        jahr = jahre[0] if jahre else __import__("datetime").date.today().year
    einstellungen = tax_mod.lese_steuer_einstellungen(state.env().values())
    try:
        frist = int(payload.get("haltefrist_jahre", einstellungen["haltefrist_jahre"]))
    except (TypeError, ValueError):
        frist = einstellungen["haltefrist_jahre"]
    txids = payload.get("txids") or []
    if not isinstance(txids, list):
        raise ApiError(400, "txids muss eine Liste sein.")
    utxo_keys = payload.get("utxos") or []
    if not isinstance(utxo_keys, list):
        raise ApiError(400, "utxos muss eine Liste sein.")
    # TxIDs sanft normalisieren — ungültige → 400 statt Traceback 500
    saubere_txids: list[str] = []
    for roh in txids:
        text = str(roh or "").strip()
        if not text:
            continue
        try:
            saubere_txids.append(sa._norm_txid(text, strict=True))
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
    try:
        report = sa.auswerten(
            utxos,
            jahr,
            saubere_txids,
            haltefrist_jahre=max(0, frist),
            anschaffung=einstellungen.get(
                "anschaffung", tax_mod.STANDARD_ANSCHAFFUNG
            ),
            wallet=state.wallet_ctx,
            immutable_cache_dir=state.immutable_cache_dir,
            utxo_keys=[str(u) for u in utxo_keys],
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    report["person"] = sa.lese_steuer_person(state.env().values())
    return report
