"""Kleine lokale Werkzeuge."""

from __future__ import annotations

from typing import Any


def api_tools_adresse(state: Any, payload: dict | None) -> dict:
    """Gehört die Adresse zu einem hinterlegten Wallet? Auch unbenutzt."""
    from core.adresse_werkzeug import pruefe_eigene_adresse
    from server import ApiError

    if not state.context_bereit():
        raise ApiError(
            409,
            "Wallets werden noch vorbereitet. Einen Moment.",
        )

    koerper = payload or {}
    return pruefe_eigene_adresse(
        state.wallet_ctx,
        str(koerper.get("address") or ""),
    )


def api_address_owner(state: Any, query: dict | None) -> dict:
    """
    Zieladresse fürs FIFO-Spend live prüfen (``GET /api/address/owner?addr=``).

    Gültig, im laufenden Netz, zu welchem Wallet? Nur Status und
    Wallet-Name — kein Schlüsselmaterial. Netz zur Laufzeit gelesen.
    """
    from core.adresse_werkzeug import pruefe_zieladresse
    from server import ApiError

    werte = (query or {}).get("addr") or [""]
    roh = str(werte[0] if isinstance(werte, (list, tuple)) else werte)
    if len(roh) > 200:
        raise ApiError(400, "Adresse zu lang.")
    if not state.context_bereit():
        raise ApiError(409, "Wallets werden noch vorbereitet. Einen Moment.")
    return pruefe_zieladresse(state.wallet_ctx, roh)


def _query_int(query: dict | None, name: str, standard: int) -> int:
    werte = (query or {}).get(name) or [""]
    roh = str(werte[0] if isinstance(werte, (list, tuple)) else werte).strip()
    try:
        return int(roh) if roh else standard
    except ValueError:
        from server import ApiError

        raise ApiError(400, f"„{name}“ ist keine ganze Zahl.")


def api_fee_suggestion(state: Any, query: dict | None) -> dict:
    """
    Gebührenvorschlag fürs FIFO-Spend (``GET /api/fee/suggestion?betrag=&inputs=``).

    ``estimatesmartfee`` (conf_target 1) am verbundenen Core, Regel in
    ``core/fee_vorschlag.py``. Ohne Schätzung 1 sat/vB mit ``quelle=fallback``.
    """
    from core.bitcoind_rpc import stelle_core_client_bereit, stelle_utxo_core_client_bereit
    from core.fee_vorschlag import gebuehr_vorschlag, schaetzung_holen
    from server import ApiError

    betrag = _query_int(query, "betrag", 0)
    inputs = _query_int(query, "inputs", 1)
    if betrag < 0 or betrag > 21_000_000 * 100_000_000:
        raise ApiError(400, "Betrag außerhalb des Bereichs.")
    if inputs < 1 or inputs > 10_000:
        raise ApiError(400, "Inputs außerhalb des Bereichs.")
    env = state.env().values()

    def fabrik():
        return (
            stelle_core_client_bereit(env, timeout=5.0)
            or stelle_utxo_core_client_bereit(env, timeout=5.0)
        )

    feerate, fehler = schaetzung_holen(fabrik)
    return gebuehr_vorschlag(feerate, betrag_sats=betrag, inputs=inputs, fehler=fehler)


def api_tools_cache_suche(state: Any, payload: dict | None = None) -> dict:
    """
    Durchsucht UTXO- und Verlaufs-Cache aller Wallets.

    Dieselbe Grammatik wie der Kopf-Filter. Läuft als Job, weil ein großer
    Cache das Anreichern der Labels dauern lässt. 409, solange schon eine
    Suche läuft.
    """
    from server import ApiError

    from core.cache_suche import suche_cache

    for job in state.jobs.list():
        if job.kind == "cache_suche" and job.status == "running":
            raise ApiError(409, "Die Cache-Suche läuft schon.")

    koerper = payload or {}
    roh = str(koerper.get("q") or "").strip()
    if not roh:
        raise ApiError(400, "Bitte einen Suchtext eingeben.")
    nach_ts = koerper.get("q_nach")
    vor_ts = koerper.get("q_vor")
    lang = str(koerper.get("lang") or "de")

    def lauf(job):
        from server import main, utxos_mod

        def fortschritt(text: str) -> None:
            job.progress(text, log=True)

        ctx = state.wallet_ctx_fuer_ansicht()
        imm = state.immutable_cache_dir

        def anreichere(e: dict, *, verlauf: bool) -> dict:
            if verlauf:
                return utxos_mod.verlauf_eintrag_als_dict(
                    e, wallet=ctx, immutable_cache_dir=imm,
                )
            return utxos_mod.utxo_as_dict(
                e, wallet=ctx, immutable_cache_dir=imm,
            )

        ergebnis = suche_cache(
            eintraege=state.analyse_entries,
            roh=roh,
            lang=lang,
            lade_bestand=lambda s: main.load_xpub_utxo_cache(s, state.cache_dir),
            lade_verlauf=lambda s: main.load_xpub_verlauf_cache(s, state.cache_dir),
            anreichere_bestand=lambda e: anreichere(e, verlauf=False),
            anreichere_verlauf=lambda e: anreichere(e, verlauf=True),
            nach_ts=nach_ts,
            vor_ts=vor_ts,
            on_progress=fortschritt,
            raise_if_cancelled=job.raise_if_cancelled,
        )
        n = int(ergebnis["total"])
        job.progress(
            f"{n} Treffer." if n else "Keine Treffer im Cache.",
            log=True,
        )
        return ergebnis

    job = state.jobs.start(
        "cache_suche",
        "Gesamten Cache durchsuchen",
        lauf,
        meta={"art": "cache_suche", "q": roh},
    )
    return job.as_dict()


def api_tools_schatzsuche(state: Any, payload: dict | None = None) -> dict:
    """
    Startet scantxoutset jenseits des Suchfensters.

    409, wenn kein Core mit scantxoutset verbunden ist oder ein UTXO-Scan
    den Node gerade selbst mit scantxoutset belegt.
    """
    from server import ApiError

    from core.schatzsuche import core_fuer_scantxoutset, jage_verlorene_schaetze

    for job in state.jobs.list():
        if job.kind == "schatzsuche" and job.status == "running":
            raise ApiError(409, "Die Schatzsuche läuft schon.")
    laufend = state.scan_queue.snapshot().get("current") or {}
    if laufend.get("kind") == "rescan":
        raise ApiError(
            409,
            "Ein UTXO-Scan läuft. scantxoutset ist auf dem Node belegt.",
        )

    probe = core_fuer_scantxoutset(state.env().values())
    if probe is None:
        raise ApiError(
            409,
            "Keine verbundene Bitcoin-Core-Quelle mit scantxoutset.",
        )
    try:
        probe.close()
    except Exception:
        pass

    koerper = payload or {}
    ziel = str(koerper.get("wallet_id") or "").strip()
    wallets = list(state.analyse_entries)
    if ziel and ziel != "*":
        wallets = [e for e in wallets if e.wallet_id() == ziel]
        if not wallets:
            raise ApiError(404, "Wallet nicht gefunden.")
    label = wallets[0].display_name if ziel and ziel != "*" and wallets else "alle Wallets"

    def lauf(job):
        def fortschritt(text: str, sofort: bool = False) -> None:
            if sofort:
                job.progress(text, log=True)
            else:
                job.progress(text, log=False)

        funde = jage_verlorene_schaetze(
            env=state.env().values(),
            wallets=wallets,
            wallet_ctx=state.wallet_ctx,
            cache_dir=state.cache_dir,
            on_log=lambda text: job.progress(text, log=True),
            on_progress=fortschritt,
            raise_if_cancelled=job.raise_if_cancelled,
        )
        n = len(funde)
        wort = "UTXO" if n == 1 else "UTXOs"
        job.progress(
            f"{n} {wort} außerhalb des Suchfensters." if n else
            "Kein UTXO außerhalb des Suchfensters.",
            log=True,
        )
        return {
            "count": n,
            "funde": funde,
            "sats": max((int(f.get("sats") or 0) for f in funde), default=0),
        }

    job = state.jobs.start(
        "schatzsuche",
        f"Jäger der verlorene Schätze · {label}",
        lauf,
        meta={"art": "schatzsuche", "wallet_id": ziel or "*"},
    )
    return job.as_dict()
