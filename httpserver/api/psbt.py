"""FIFO-Spend: Coin-Auswahl-Vorschau und unsignierte PSBT (``core/psbt_bau.py``)."""

from __future__ import annotations

from typing import Any

#: Mehr UTXOs schickt die Ansicht nicht (Schutz vor Riesen-Körpern).
_MAX_UTXOS = 20_000


def api_psbt_auswahl(state: Any, payload: dict | None) -> dict:
    """
    ``POST /api/psbt/auswahl`` — welche grünen UTXOs, welches Wechselgeld,
    welche Gebühr? Körper: ``betrag`` (sats), ``modus`` (defensiv/offensiv),
    ``utxos`` (Zeitstrahl-Punkte des Wallets), ``pending`` (Schlüssel der
    Mempool-Ausgaben), ``strategie`` (wechselgeld/gebuehr/aelteste/staub,
    Standard wechselgeld), optional ``eigenes_ziel`` (Gesamtsaldo, gelb/grau
    erlaubt), optional ``wallet_id`` (nur für die vbytes: bei
    Multisig M-von-N-Inputs und P2WSH-Wechselgeld). Regel und Suche:
    ``core/coin_auswahl.py``.

    Vorschau: Die Antwort trägt nur ``txid:vout``, Beträge und grüne Anteile —
    kein Schlüsselmaterial. Erzeugt, signiert und sendet nichts.
    """
    from core.bitcoind_rpc import stelle_core_client_bereit, stelle_utxo_core_client_bereit
    from core.coin_auswahl import auswahl_vorschau
    from core.fee_vorschlag import schaetzung_holen
    from server import ApiError

    koerper = payload or {}
    try:
        betrag = int(koerper.get("betrag") or 0)
    except (TypeError, ValueError):
        raise ApiError(400, "„betrag“ ist keine ganze Zahl.")
    if betrag <= 0 or betrag > 21_000_000 * 100_000_000:
        raise ApiError(400, "Betrag außerhalb des Bereichs.")
    utxos = koerper.get("utxos")
    pending = koerper.get("pending")
    utxos = [] if utxos is None else utxos
    pending = [] if pending is None else pending
    if not isinstance(utxos, list) or not isinstance(pending, list):
        raise ApiError(400, "„utxos“ und „pending“ müssen Listen sein.")
    if len(utxos) > _MAX_UTXOS:
        raise ApiError(400, "Zu viele UTXOs.")
    from core.coin_auswahl import STANDARD_STRATEGIE, STRATEGIEN

    strategie = str(koerper.get("strategie") or STANDARD_STRATEGIE).strip().lower()
    if strategie not in STRATEGIEN:
        raise ApiError(400, f"„strategie“ muss {', '.join(STRATEGIEN)} sein.")
    env = state.env().values()

    def fabrik():
        return (
            stelle_core_client_bereit(env, timeout=5.0)
            or stelle_utxo_core_client_bereit(env, timeout=5.0)
        )

    feerate, fehler = schaetzung_holen(fabrik)
    groessen = _vorschau_groessen(state, koerper.get("wallet_id"))
    return auswahl_vorschau(
        utxos,
        modus=str(koerper.get("modus") or "defensiv"),
        betrag=betrag,
        pending=[str(k) for k in pending],
        feerate_btc_kvb=feerate,
        fehler=fehler,
        strategie=strategie,
        groessen=groessen,
        eigenes_ziel=bool(koerper.get("eigenes_ziel")),
    )


def _vorschau_groessen(state: Any, wallet_id: Any):
    """
    vbytes für die Vorschau: bei Multisig M-von-N-Inputs und P2WSH-/P2SH-
    Wechselgeld (wie ``POST /api/psbt/erzeugen``), sonst None (Schätzformel).
    Unbekanntes Wallet oder unlesbarer Deskriptor: None — die Vorschau bleibt
    eine Vorschau, die PSBT prüft ohnehin neu.
    """
    kennung = str(wallet_id or "").strip()
    if not kennung:
        return None
    try:
        from core import psbt_bau
        from core.coin_auswahl import Groessen
        from server import wallets_mod

        entry = wallets_mod.find_entry(getattr(state, "entries", None) or [], kennung)
        if entry is None or not entry.is_multisig:
            return None
        politik = psbt_bau.MultisigPolitik(entry.descriptor)
        return Groessen(input_vb=politik.input_vb,
                        wechsel_vb=psbt_bau.output_vbytes(politik.ableiten(1, 0).spk.data))
    except Exception:
        return None


#: Coin-Control: höchstens so viele ``txid:vout`` im Körper.
_MAX_NUR_INPUTS = 500


def _skripttyp(entry: Any, utxos: list[dict], netz) -> str | None:
    """
    Skripttyp fürs Bauen: ``segwit``/``nested``/``legacy`` oder None.

    Ausdrücklich gesetzt (oder SLIP-132-Präfix) gewinnt. Bei ``auto`` mit
    ``xpub``/``tpub`` entscheiden die Adressen des Bestands — gemischte
    Typen baut SatSage (noch) nicht.
    """
    from core.psbt_bau import UNTERSTUETZTE_SKRIPTE, ableiten
    from core.wallets import effective_script_type

    wirksam = str(getattr(entry, "script_typ_wirksam", "") or "")
    typ = {"p2wpkh": "segwit", "p2sh-p2wpkh": "nested", "p2pkh": "legacy"}.get(
        wirksam, effective_script_type(entry))
    if typ in UNTERSTUETZTE_SKRIPTE:
        return typ
    if typ != "alle":
        return None
    from embit.bip32 import HDKey

    try:
        hd = HDKey.from_string(entry.xpub)
    except Exception:
        return None
    adressen = {str(u.get("address") or "") for u in utxos} - {""}
    if not adressen:
        return "segwit"
    gefunden = set()
    for t in UNTERSTUETZTE_SKRIPTE:
        for change in (0, 1):
            for i in range(int(getattr(entry, "max_addresses", 50) or 50)):
                spk = ableiten(hd, t, change, i)[1]
                if (spk.address(netz) if netz is not None else spk.address()) in adressen:
                    gefunden.add(t)
                    break
            if t in gefunden:
                break
    return gefunden.pop() if len(gefunden) == 1 else None


def _steuer_abfrage(einstellungen: dict, lang: str, anschaffung: str | None) -> dict:
    """Dieselbe Abfrage wie ``fifoSpendAbfrage`` im Web — der Steuer-Cache greift."""
    import datetime

    q = {
        "jahr": [str(datetime.date.today().year)],
        "frist": [str(einstellungen.get("haltefrist_jahre", 1))],
        "stichtag": [str(einstellungen.get("stichtag") or "")],
        "seite": ["1"], "teil": ["alle"], "limit": ["0"], "limit_abgaenge": ["0"],
        "lang": [lang],
    }
    if anschaffung:
        q["anschaffung"] = [anschaffung]
    return q


def api_psbt_erzeugen(state: Any, payload: dict | None) -> dict:
    """
    ``POST /api/psbt/erzeugen`` — unsignierte PSBT (BIP174 v0) samt Übersicht.

    Körper: ``wallet_id``, ``betrag`` (sats), ``adresse``, ``fee`` (sat/vB,
    bis 3 Nachkommastellen), optional ``strategie``, ``modus`` (nur zur
    Kontrolle — es gilt die Steuer-Einstellung), ``nur_inputs``
    (Coin-Control, ``txid:vout``), ``lang`` (nur für den Steuer-Cache).

    Nichts vom Browser wird geglaubt: Bestand, Lot-Anteile, Mempool,
    Zulässigkeit, Maximum, Auswahl, Wechseladresse und Gebühr rechnet der
    Server neu. Signiert und sendet nichts; kein privater Schlüssel.
    """
    return _erzeugen(state, payload)


def api_psbt_max(state: Any, payload: dict | None) -> dict:
    """
    ``POST /api/psbt/max`` — Netto-Maximum für die FIFO-Spend-Kopfzeile.

    Körper: ``wallet_id``, optional ``fee`` (sat/vB wie im Gebührenfeld; ohne
    gilt die Schätzung mit Puffer, sonst 1 sat/vB) und ``adresse`` (ohne gilt
    die Größe der eigenen Wechseladresse). Bestand, Lot-Anteile und Mempool
    wie ``POST /api/psbt/erzeugen``; ``max_netto_sats`` ist der größte Betrag,
    den die PSBT bei dieser Rate deckt — ``max_netto_sats`` + 1 nicht mehr.
    Baut nichts.
    """
    return _erzeugen(state, payload, nur_max=True)


def _max_fee_text(state: Any) -> str:
    """Gebühr fürs Netto-Maximum ohne Eingabe: Schätzung + Puffer, sonst 1 sat/vB."""
    from core.bitcoind_rpc import stelle_core_client_bereit, stelle_utxo_core_client_bereit
    from core.fee_vorschlag import btc_kvb_zu_sat_vb, rate_mit_puffer, schaetzung_holen

    env = state.env().values()

    def fabrik():
        return (
            stelle_core_client_bereit(env, timeout=5.0)
            or stelle_utxo_core_client_bereit(env, timeout=5.0)
        )

    try:
        feerate, _fehler = schaetzung_holen(fabrik)
        rate = rate_mit_puffer(btc_kvb_zu_sat_vb(feerate) if feerate is not None else None)
    except Exception:
        rate = None
    return str(rate or 1)


def _erzeugen(
    state: Any, payload: dict | None, *, einstellungen: dict | None = None,
    nur_max: bool = False,
) -> dict:
    from core import tax as tax_mod
    from core.adresse_werkzeug import pruefe_zieladresse
    from core.bitcoind_rpc import stelle_core_client_bereit, stelle_utxo_core_client_bereit
    from core.coin_auswahl import STANDARD_STRATEGIE, STRATEGIEN
    from core.derivation import chain_network
    from core import psbt_bau
    from server import (
        ApiError,
        _cache_bekannt_adressen,
        _eigener_fulcrum_client,
        _mit_mempool_pending,
        utxos_mod,
        wallets_mod,
    )

    koerper = payload or {}
    if not state.context_bereit():
        raise ApiError(409, "Wallets werden noch vorbereitet. Einen Moment.")
    kennung = str(koerper.get("wallet_id") or "").strip()
    entry = wallets_mod.find_entry(state.entries, kennung) if kennung else None
    if entry is None:
        raise ApiError(404, "Wallet nicht gefunden.")
    multisig = None
    if entry.is_multisig:
        # Multisig: Skripte und Cosigner kommen nur aus dem Deskriptor.
        try:
            multisig = psbt_bau.MultisigPolitik(entry.descriptor)
        except psbt_bau.PsbtFehler as exc:
            raise ApiError(400, str(exc))
    try:
        betrag = int(koerper.get("betrag") or 0)
    except (TypeError, ValueError):
        raise ApiError(400, "„betrag“ ist keine ganze Zahl.")
    if nur_max:
        betrag = 0
    elif betrag <= 0 or betrag > 21_000_000 * 100_000_000:
        raise ApiError(400, "Betrag außerhalb des Bereichs.")
    fee_roh = koerper.get("fee")
    if nur_max and not str(fee_roh or "").strip():
        fee_roh = _max_fee_text(state)
    fee_milli = psbt_bau.fee_text_zu_milli(fee_roh)
    if fee_milli is None:
        raise ApiError(400, "Gebühr ungültig (sat/vB, mehr als 0 bis 10 000, höchstens 3 Nachkommastellen).")
    strategie = str(koerper.get("strategie") or STANDARD_STRATEGIE).strip().lower()
    if strategie not in STRATEGIEN:
        raise ApiError(400, f"„strategie“ muss {', '.join(STRATEGIEN)} sein.")
    nur = koerper.get("nur_inputs")
    if nur is not None:
        if not isinstance(nur, list) or not nur or len(nur) > _MAX_NUR_INPUTS:
            raise ApiError(400, "„nur_inputs“ muss eine Liste von txid:vout sein.")
        nur = [str(k).strip().lower() for k in nur]
    roh_adresse = str(koerper.get("adresse") or "")
    if len(roh_adresse) > 200:
        raise ApiError(400, "Adresse zu lang.")
    if nur_max and not roh_adresse.strip():
        ziel = {"address": "", "status": "", "wallet": ""}
    else:
        ziel = pruefe_zieladresse(state.wallet_ctx, roh_adresse)
        if ziel.get("status") not in ("meine", "fremd", "keine_wallets"):
            raise ApiError(400, "Zieladresse ungültig oder im falschen Netz.")

    env = state.env().values()
    einst = einstellungen or tax_mod.lese_steuer_einstellungen(env)
    modus = "offensiv" if einst.get("anschaffung") == "aelteste" else "defensiv"
    gewuenscht = koerper.get("modus")
    if gewuenscht and str(gewuenscht) != modus:
        raise ApiError(409, "Die Steuer-Einstellung hat sich geändert — bitte neu laden.")

    # Bestand: Cache + eigener Electrum-Server (Mempool-Ausgaben).
    state.wallet_ctx_fuer_ansicht()
    schluessel = entry.analyse_schluessel
    gecacht = utxos_mod.load_cached_utxos(
        schluessel, state.cache_dir, immutable_cache_dir=state.immutable_cache_dir,
    )
    if gecacht is None:
        raise ApiError(409, "Für dieses Wallet gibt es noch keinen Bestand (Scan fehlt).")
    electrum = _eigener_fulcrum_client(state)
    mempool_geprueft = False
    if electrum is not None:
        # Zwei Versuche auf frischen Kopien — ein abgebrochener Abgleich darf
        # keine halb markierte Liste hinterlassen.
        for _ in range(2):
            try:
                gecacht, _ = _mit_mempool_pending(
                    state, [dict(u) for u in gecacht], {}, limit=None, sort="datum",
                    xpub=schluessel,
                )
                mempool_geprueft = True
                break
            except Exception:
                continue
        if not mempool_geprueft:
            raise ApiError(503, "Mempool-Abgleich mit dem eigenen Electrum-Server fehlgeschlagen — bitte erneut versuchen.")
    pending = [
        f"{str(u.get('txid') or '').lower()}:{int(u.get('vout') or 0)}"
        for u in gecacht if u.get("spending_pending")
    ]

    # Lot-Anteile: Steuerauswertung des Servers (eigene Einstellung).
    from httpserver.api.tax import api_tax

    lang = str(koerper.get("lang") or "de")[:5]
    anschaffung = einst.get("anschaffung") if einstellungen else None
    auswertung = api_tax(state, _steuer_abfrage(einst, lang, anschaffung), None, lang)
    ids = {kennung, wallets_mod.eintrag_id(entry)}
    punkte = [
        e for e in ((auswertung.get("zeitstrahl") or {}).get("events") or [])
        if isinstance(e, dict) and str(e.get("wallet_id") or "") in ids
    ]
    eigenes_ziel = str(ziel.get("status") or "") == "meine"
    utxos = psbt_bau.zusammenfuehren(gecacht, punkte, eigenes_ziel=eigenes_ziel)

    netz = chain_network()
    if multisig is not None:
        typ = multisig.typ
        herkunft = None
    else:
        typ = _skripttyp(entry, utxos, netz)
        if typ is None:
            raise ApiError(400, "Skripttyp dieses Wallets wird für PSBTs noch nicht unterstützt (Taproot/gemischt).")
        try:
            herkunft = psbt_bau.herkunft_fuer(entry.xpub, entry.descriptor)
        except Exception:
            raise ApiError(400, "XPUB nicht lesbar.")

    if nur_max:
        try:
            erg = psbt_bau.erzeuge(
                xpub=entry.xpub, typ=typ, herkunft=herkunft, netz=netz, max_index=0,
                utxos=utxos, pending=pending, modus=modus, strategie=strategie,
                betrag=0, fee_milli=fee_milli, ziel_adresse=ziel["address"],
                ziel_status=ziel["status"], multisig=multisig, nur_max=True,
            )
        except psbt_bau.PsbtFehler as exc:
            raise ApiError(422, str(exc))
        erg.update({
            "wallet": entry.display_name,
            "wallet_id": wallets_mod.eintrag_id(entry),
            "mempool_geprueft": mempool_geprueft,
            "fee_milli": fee_milli,
        })
        return erg

    core = None
    try:
        core = stelle_core_client_bereit(env, timeout=10.0) or stelle_utxo_core_client_bereit(env, timeout=10.0)
    except Exception:
        core = None

    def electrum_frage(methode: str, params: list):
        """Eigener Electrum-Server; Verbindung bei Bedarf neu holen (ein Versuch)."""
        for _ in range(2):
            client = _eigener_fulcrum_client(state)
            if client is None:
                raise RuntimeError("kein eigener Electrum-Server")
            try:
                return client.request(methode, params)
            except Exception as exc:
                fehler = exc
        raise fehler

    roh_cache: dict[str, bytes | None] = {}

    def roh_tx_holen(txid: str) -> bytes | None:
        if txid in roh_cache:
            return roh_cache[txid]
        roh = None
        if core is not None:
            try:
                hexa = core.call("getrawtransaction", [txid, False])
                roh = bytes.fromhex(hexa) if isinstance(hexa, str) else None
            except Exception:
                roh = None
        if roh is None and electrum is not None:
            try:
                hexa = electrum_frage("blockchain.transaction.get", [txid, False])
                roh = bytes.fromhex(hexa) if isinstance(hexa, str) else None
            except Exception:
                roh = None
        roh_cache[txid] = roh
        return roh

    hoehe = None
    if core is not None:
        try:
            hoehe = int((core.call("getblockchaininfo") or {}).get("blocks") or 0) or None
        except Exception:
            hoehe = None
    if hoehe is None and electrum is not None:
        try:
            kopf = electrum_frage("blockchain.headers.subscribe", []) or {}
            hoehe = int(kopf.get("height") or 0) or None
        except Exception:
            hoehe = None

    wechsel_geprueft = [electrum is not None]

    def hat_history(adresse: str) -> bool:
        from fulcrum import address_to_scripthash

        try:
            sh = address_to_scripthash(adresse)
            return bool(electrum_frage("blockchain.scripthash.get_history", [sh]) or [])
        except Exception:
            # Nicht prüfbar: Schätzung aus dem Cache gilt (wie beim Empfangs-QR).
            wechsel_geprueft[0] = False
            return False

    bekannt, scan_end = _cache_bekannt_adressen(state, entry)
    max_index = max(int(entry.max_addresses or 0), int(scan_end or 0)) + 100
    try:
        erg = psbt_bau.erzeuge(
            xpub=entry.xpub, typ=typ, herkunft=herkunft, netz=netz, max_index=max_index,
            utxos=utxos, pending=pending, modus=modus, strategie=strategie,
            betrag=betrag, fee_milli=fee_milli,
            ziel_adresse=ziel["address"], ziel_status=ziel["status"],
            ziel_wallet=str(ziel.get("wallet") or ""),
            bekannte_adressen=bekannt,
            hat_history=hat_history if electrum is not None else None,
            roh_tx_holen=roh_tx_holen, hoehe=hoehe, nur_inputs=nur,
            multisig=multisig, quelle_wallet=str(entry.display_name or ""),
        )
    except psbt_bau.PsbtFehler as exc:
        raise ApiError(422, str(exc))
    erg.update({
        "wallet": entry.display_name,
        "wallet_id": wallets_mod.eintrag_id(entry),
        "skripttyp": typ,
        "mempool_geprueft": mempool_geprueft,
        "wechsel_geprueft": wechsel_geprueft[0],
        "netz": ziel.get("netz"),
    })
    return erg
