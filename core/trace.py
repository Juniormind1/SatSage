"""
Herkunftsanalyse als Daten.

Wandelt den verschachtelten Baum aus analyze.trace_utxo_origin in eine flache,
für die Oberfläche brauchbare Form um — mit stabilen Knoten-Kennungen, damit
sich Zweige einzeln auf- und zuklappen lassen.

Zwei Eigenheiten des Bestands, die hier sichtbar gemacht werden müssen:

* Externe Zweige werden nicht weiterverfolgt. Hinter einer fremden Adresse
  endet die Analyse — sonst liefe sie über die halbe Blockchain.
* Nach dem ersten eigenen Eingang werden die restlichen Eingänge nur gezählt,
  nicht aufgelöst (``external_unresolved``). Deren Beträge fehlen, die Summe
  der externen Zuflüsse ist deshalb eine Untergrenze, keine Gesamtsumme.
"""
from __future__ import annotations

import json
from pathlib import Path

import analyze
import labels
import main
from core import trace_cache

#: Typen, die ein Knoten annehmen kann.
KNOTEN_TYPEN = ("utxo", "internal", "external", "external_unresolved",
                "coinbase", "cycle", "error", "unknown", "tax_horizon")


def parse_ziel(eingabe: str) -> tuple[str, int] | None:
    """
    Erkennt 'txid:vout' oder eine reine TxID (dann vout 0).

    Adressen werden hier nicht behandelt — die Oberfläche löst sie vorher
    über die UTXO-Liste auf.
    """
    text = (eingabe or "").strip()
    if not text:
        return None
    if ":" in text:
        txid, _, vout = text.rpartition(":")
        try:
            return main._normalize_txid(txid), int(vout)
        except ValueError:
            return None
    if len(text) == 64:
        try:
            int(text, 16)
        except ValueError:
            return None
        return main._normalize_txid(text), 0
    return None


def _blockhoehe_fuer_utxo(
    txid: str,
    vout: int,
    cache_dir: Path | None,
    wallet,
) -> int | None:
    """Höhe aus UTXO-Cache, falls der Scan sie schon kennt."""
    import json
    from pathlib import Path as _Path

    key_txid = main._normalize_txid(txid)
    ziel_vout = int(vout)
    root = _Path(cache_dir) if cache_dir else main.UTXO_CACHE_DIR
    if not root.is_dir():
        return None

    kandidaten: list[list] = []
    xpubs = list(getattr(wallet, "xpubs", None) or []) if wallet is not None else []
    for xpub in xpubs:
        try:
            liste = main.load_xpub_utxo_cache(xpub, root)
        except Exception:
            liste = None
        if liste:
            kandidaten.append(liste)
    if not kandidaten:
        for pfad in root.glob("*.json"):
            if (
                pfad.name.endswith("_alter.json")
                or "external" in pfad.name
                or "verlauf" in pfad.name
            ):
                continue
            try:
                data = json.loads(pfad.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            utxos = data.get("utxos") if isinstance(data, dict) else None
            if isinstance(utxos, list):
                kandidaten.append(utxos)

    for utxos in kandidaten:
        for u in utxos:
            if main._normalize_txid(str(u.get("txid") or "")) != key_txid:
                continue
            try:
                if int(u.get("vout", -1)) != ziel_vout:
                    continue
            except (TypeError, ValueError):
                continue
            status = u.get("status") or {}
            raw = status.get("block_height", u.get("height"))
            try:
                h = int(raw)
            except (TypeError, ValueError):
                return None
            return h if h > 0 else None
    return None


def erklaere_fehler(roh: str) -> str:
    """
    Übersetzt Meldungen der Datenquelle in verständlichen Text.

    Ein durchgereichtes ``DaemonError({'code': -5, …})`` sagt niemandem, was zu
    tun ist. Unbekannte Meldungen bleiben unverändert — lieber roh als falsch
    gedeutet.
    """
    text = str(roh or "").strip()
    if not text:
        return "Unbekannter Fehler."
    klein = text.lower()

    if "peer hat die transaktion nicht" in klein:
        return (
            "Der P2P-Peer kennt die Transaktion nicht als Einzelabruf "
            "(typisch ohne Tx-Index). Mit bekannter Blockhöhe wird der ganze "
            "Block geladen; sonst Core mit -txindex=1 oder ein Electrum-Server."
        )
    if "nicht auflösbar ohne electrs" in klein or "keine blockhöhe bekannt" in klein:
        return (
            "Ohne Electrs fehlt die Höhe dieser Vorgänger-Tx. Core mit "
            "-txindex=1 eintragen, oder einen Electrum-Server nutzen — ein "
            "Blindflug über die ganze Kette ist absichtlich nicht eingebaut."
        )
    if "no such mempool or blockchain transaction" in klein:
        return (
            "Die Datenquelle kennt diese Transaktion nicht. Entweder ist die "
            "TxID falsch, oder der Node hat den Block noch nicht — bei einem "
            "frisch synchronisierten Node kann das vorkommen."
        )
    if "vout" in klein and "ungültig" in klein:
        return (
            "Diesen Ausgang gibt es in der Transaktion nicht. Stimmt die "
            "Nummer hinter dem Doppelpunkt?"
        )
    if "timed out" in klein or "timeout" in klein:
        return (
            "Die Datenquelle hat nicht rechtzeitig geantwortet. Bei "
            "Tor-Verbindungen kommt das vor — noch einmal versuchen."
        )
    if "connection refused" in klein or "nicht erreichbar" in klein:
        return (
            "Keine Verbindung zur Datenquelle. Läuft der Node, und stimmen "
            "Host und Port in den Einstellungen?"
        )
    if "wrong version number" in klein:
        return (
            "TLS-Handshake fehlgeschlagen — der Port spricht vermutlich kein "
            "SSL. In den Einstellungen FULCRUM_SSL abschalten."
        )
    return text


def _format_time_ts(ts) -> str:
    """Unix-Zeit → Anzeige wie bei Tx-Zeiten (ohne Block-Präfix)."""
    try:
        wert = int(ts)
    except (TypeError, ValueError):
        return ""
    if wert <= 0:
        return ""
    try:
        from datetime import UTC, datetime

        return datetime.fromtimestamp(wert, UTC).strftime("%d.%m.%Y %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return ""


def _setze_externe_zeit(knoten: dict, quelle: dict | None = None) -> None:
    """
    Füllt time_label / block_time am UI-Knoten aus Analyse-Source oder
    bereits gesetzten Feldern (Cache-Nachzug).
    """
    quelle = quelle or {}
    if knoten.get("time_label") and knoten.get("block_time"):
        return
    ts = knoten.get("block_time") or knoten.get("time_ts") or quelle.get("time_ts")
    label = (knoten.get("time_label") or quelle.get("time") or "").strip()
    if not label and ts:
        label = _format_time_ts(ts)
    if not label and not ts:
        return
    if label:
        knoten["time_label"] = label
    try:
        if ts is not None and int(ts) > 0:
            knoten["block_time"] = int(ts)
            knoten["time_ts"] = int(ts)
    except (TypeError, ValueError):
        pass


def _anreichere_externe_zeiten(
    knoten_liste: list,
    immutable_cache_dir: Path | str | None = None,
) -> None:
    """
    Nachträglich Zeiten an externe Blätter hängen (alte Caches ohne time_label).

    Reihenfolge: vorhandenes time_ts → Tx-Cache zum from_utxo.
    """
    if not knoten_liste:
        return
    immutable: Path | None = None
    if immutable_cache_dir:
        try:
            immutable = Path(immutable_cache_dir)
        except TypeError:
            immutable = None

    def _aus_tx_cache(from_utxo: str) -> tuple[int | None, str]:
        if not immutable or not from_utxo or ":" not in str(from_utxo):
            return None, ""
        try:
            txid, _vout = str(from_utxo).rsplit(":", 1)
            txid = main._normalize_txid(txid)
        except Exception:
            return None, ""
        pfad = immutable / "tx" / f"{txid}.json"
        if not pfad.is_file():
            return None, ""
        try:
            roh = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None, ""
        if not isinstance(roh, dict):
            return None, ""
        # Flatfile oft {txid, source, tx: {...}} — Zeit sitzt im inneren tx.
        tx = roh.get("tx") if isinstance(roh.get("tx"), dict) else roh
        if not isinstance(tx, dict):
            return None, ""
        ts = main._tx_block_time(tx)
        if ts is None:
            return None, ""
        return int(ts), main._format_tx_time(tx)

    def _walk(knoten: dict) -> None:
        if not isinstance(knoten, dict):
            return
        if knoten.get("type") == "external":
            if not (knoten.get("time_label") and knoten.get("block_time")):
                _setze_externe_zeit(knoten)
            if not knoten.get("time_label") and not knoten.get("block_time"):
                ts, label = _aus_tx_cache(knoten.get("from_utxo") or "")
                if ts or label:
                    if label:
                        knoten["time_label"] = label
                    if ts:
                        knoten["block_time"] = ts
                        knoten["time_ts"] = ts
        for kind in knoten.get("children") or []:
            _walk(kind)

    for knoten in knoten_liste:
        _walk(knoten)


def _kind_knoten(quelle: dict, wallet, pfad: str, tiefe: int) -> dict:
    """Baut einen Knoten aus einem Quellen-Eintrag des Analysebaums."""
    typ = quelle.get("type", "unknown")
    adresse = quelle.get("address", "")

    knoten = {
        "id": pfad,
        "type": typ,
        "depth": tiefe,
        "address": adresse,
        "amount_sats": int(quelle.get("amount_sats", 0) or 0),
        "from_utxo": quelle.get("from_utxo", ""),
        "wallet": None,
        "time_label": "",
        "block_height": None,
        "children": [],
        "expandable": False,
        "note": "",
        # Nur externe Enden werden beschriftet — bei eigenen Adressen wäre die
        # Frage sinnlos. Der Schlüssel ist trotzdem immer da, damit sich
        # „nichts gefunden" nicht von „gar nicht nachgeschaut" unterscheidet.
        "label": None,
    }

    if typ == "internal":
        knoten["wallet"] = wallet.resolve_address(adresse) if wallet else None
        unterbaum = quelle.get("trace")
        if unterbaum:
            knoten["time_label"] = unterbaum.get("time", "")
            knoten["txid"] = unterbaum.get("txid", "")
            knoten["vout"] = unterbaum.get("vout")
            # Soft-Label der Erzeuger-Tx (CoinJoin-Art am eigenen Hop).
            if unterbaum.get("tx_class"):
                knoten["tx_class"] = unterbaum.get("tx_class")
                knoten["tx_class_label"] = unterbaum.get("tx_class_label") or ""
                knoten["tx_class_label_en"] = unterbaum.get("tx_class_label_en") or ""
                if knoten["tx_class_label"]:
                    knoten["note"] = knoten["tx_class_label"]
            quellen = unterbaum.get("sources") or []
            if unterbaum.get("tax_horizon") and not quellen:
                # Steuer-Frühabbruch: Blatt bis Stichtag/Haltefrist-Anfang.
                knoten["type"] = "tax_horizon"
                knoten["tax_horizon"] = True
                knoten["children"] = []
                knoten["note"] = (
                    "Für Steuerjahr ausreichend (vor Stichtag bzw. "
                    "Haltefrist-Anfang). Herkunft tracen führt bis "
                    "extern/Coinbase weiter."
                )
                if unterbaum.get("time_ts"):
                    knoten["block_time"] = int(unterbaum["time_ts"])
            elif unterbaum.get("exchange_stop"):
                # Börsen-Grenze: kein Walk hinter Ein-/Auszahlung.
                knoten["exchange_stop"] = True
                knoten["label"] = (
                    unterbaum.get("exchange_label")
                    or labels.beschrifte(
                        adresse or "",
                        txid=str(unterbaum.get("txid") or ""),
                    )
                )
                knoten["note"] = (
                    "Börse — Herkunft endet an der Ein-/Auszahlung "
                    "(keine Hops darüber hinaus)."
                )
                if quellen:
                    knoten["children"] = _quellen_zu_knoten(
                        unterbaum, wallet, pfad, tiefe + 1
                    )
                else:
                    knoten["children"] = []
                knoten["expandable"] = bool(knoten["children"])
            elif quellen:
                knoten["children"] = _quellen_zu_knoten(
                    unterbaum, wallet, pfad, tiefe + 1
                )
            elif unterbaum.get("coinjoin_noise_skipped") and unterbaum.get("tx_class"):
                # CJ ohne aufgelöste eigene Ins: Soft-Label reicht als Blatt —
                # absichtlicher Peer-Skip ist keine Herkunftslücke.
                knoten["children"] = []
                knoten["coinjoin_noise_skipped"] = True
            else:
                # cycle/error/unknown ohne Quellen: als Blatt sichtbar machen,
                # sonst wirkt der interne Knoten fälschlich „fertig grün“.
                marker = unterbaum.get("type") or "unknown"
                if marker == "utxo":
                    marker = "unknown"
                if unterbaum.get("tax_horizon"):
                    marker = "tax_horizon"
                knoten["children"] = [{
                    "id": f"{pfad}.0",
                    "type": marker,
                    "depth": tiefe + 1,
                    "address": "",
                    "amount_sats": 0,
                    "from_utxo": unterbaum.get("utxo") or quelle.get("from_utxo", ""),
                    "wallet": None,
                    "time_label": unterbaum.get("time") or "",
                    "block_height": None,
                    "block_time": unterbaum.get("time_ts"),
                    "tax_horizon": bool(unterbaum.get("tax_horizon")),
                    "children": [],
                    "expandable": False,
                    "note": (
                        unterbaum.get("error")
                        or (
                            "Für Steuerjahr ausreichend (vor Stichtag/Haltefrist)."
                            if marker == "tax_horizon"
                            else (
                                "Zyklus oder Maximaltiefe — Herkunft hier abgebrochen."
                                if marker == "cycle"
                                else "Herkunft dieses Zweigs konnte nicht ermittelt werden."
                            )
                        )
                    ),
                    "label": None,
                }]
            knoten["expandable"] = bool(knoten["children"])
    elif typ == "tax_horizon":
        knoten["tax_horizon"] = True
        knoten["note"] = (
            "Für Steuerjahr ausreichend (vor Stichtag bzw. "
            "Haltefrist-Anfang)."
        )
        _setze_externe_zeit(knoten, quelle)
    elif typ == "external":
        if quelle.get("exchange_stop"):
            knoten["exchange_stop"] = True
            knoten["note"] = (
                "Börse — Herkunft endet an der Ein-/Auszahlung "
                "(keine Hops darüber hinaus)."
            )
        else:
            knoten["note"] = "Externe Zweige werden nicht weiterverfolgt."
        # Genau hier endet die Verfolgung — und genau hier ist die Frage
        # „von wem kam das eigentlich" am interessantesten.
        # Börsen-CSV: Adresse oder TxID des Prevouts (Ein-/Auszahlung).
        from_utxo = str(quelle.get("from_utxo") or "")
        prev_txid = from_utxo.rsplit(":", 1)[0] if ":" in from_utxo else ""
        knoten["label"] = labels.beschrifte(adresse, txid=prev_txid)
        # Blockzeit des Prevouts: wann diese Sats die fremde Adresse erreichten
        # (bzw. der Funding-Output bestätigt wurde). analyze legt time_ts ab;
        # ohne das blieb die UI-Zeile ohne Datum, obwohl die jüngsten sats
        # genau aus diesen Zeiten berechnet werden.
        _setze_externe_zeit(knoten, quelle)
    elif typ == "external_unresolved":
        anzahl = int(quelle.get("input_count", 0) or 0)
        knoten["input_count"] = anzahl
        knoten["note"] = (
            f"{anzahl} weitere Eingänge wurden nicht aufgelöst — nach dem "
            "ersten eigenen Eingang bricht die Auflösung ab, um bei "
            "Sammel-Transaktionen nicht hunderte Abrufe auszulösen. "
            "Beträge dieser Eingänge fehlen."
        )
    elif typ == "coinbase":
        knoten["note"] = "Frisch geschürfte Sats — hier endet jede Herkunft."
    elif typ == "error":
        knoten["note"] = (
            quelle.get("error")
            or "Herkunft dieses Zweigs konnte nicht ermittelt werden."
        )
        if quelle.get("input_count"):
            knoten["input_count"] = int(quelle.get("input_count") or 0)
    elif typ == "unknown":
        knoten["note"] = (
            quelle.get("error")
            or "Herkunft unvollständig — kein externes oder Coinbase-Ende."
        )

    return knoten


def _quellen_zu_knoten(baum: dict, wallet, pfad: str, tiefe: int) -> list[dict]:
    kinder = []
    for nummer, quelle in enumerate(baum.get("sources", [])):
        kinder.append(
            _kind_knoten(quelle, wallet, f"{pfad}.{nummer}", tiefe)
        )
    return kinder


def _summen(knoten: list[dict]) -> dict:
    """Zählt Zuflüsse nach Art über den gesamten Baum."""
    ergebnis = {
        "internal_sats": 0,
        "external_sats": 0,
        "external_count": 0,
        "unresolved_inputs": 0,
        "coinbase": False,
        "max_depth": 0,
        "node_count": 0,
    }

    stapel = list(knoten)
    while stapel:
        aktuell = stapel.pop()
        ergebnis["node_count"] += 1
        ergebnis["max_depth"] = max(ergebnis["max_depth"], aktuell["depth"])
        typ = aktuell["type"]
        if typ == "internal":
            ergebnis["internal_sats"] += aktuell["amount_sats"]
        elif typ == "external":
            ergebnis["external_sats"] += aktuell["amount_sats"]
            ergebnis["external_count"] += 1
        elif typ == "external_unresolved":
            ergebnis["unresolved_inputs"] += aktuell.get("input_count", 0)
        elif typ == "coinbase":
            ergebnis["coinbase"] = True
        stapel.extend(aktuell["children"])
    return ergebnis


def interne_vorgaenger_anzahl(baum: dict | None) -> int:
    """
    Anzahl eindeutiger interner Creator-Txs im flachen UI-Baum.

    Entspricht grob der CLI-Heuristik für transaktionsorientierte Folgeanalyse
    (≥2 → Verzweigung lohnt sich oft).
    """
    if not baum:
        return 0
    txids: set[str] = set()
    stapel = list(baum.get("children") or [])
    while stapel:
        knoten = stapel.pop()
        if not isinstance(knoten, dict):
            continue
        if knoten.get("type") == "internal":
            tid = str(knoten.get("txid") or "").strip().lower()
            if tid:
                txids.add(tid)
            # from_utxo „txid:vout“ als Fallback
            roh = str(knoten.get("from_utxo") or "")
            if ":" in roh:
                txids.add(roh.rsplit(":", 1)[0].strip().lower())
        stapel.extend(knoten.get("children") or [])
    return len(txids)


def folge_meta(baum: dict | None) -> dict:
    """Signale für Opt-in-Folgeaktionen in der Oberfläche."""
    n = interne_vorgaenger_anzahl(baum)
    summary = (baum or {}).get("summary") or {}
    unresolved = int(summary.get("unresolved_inputs") or 0)
    # Immer an den Blättern messen — ältere Caches speicherten fälschlich
    # verfolgt_vollstaendig=True, sobald irgendwo external_count > 0 war.
    voll = trace_cache.baum_ist_vollstaendig(baum) if baum else False
    # „Done“ nur wenn wirklich jedes Blatt rot/lila ist — sonst bleibt der
    # Entwirren-Knopf sichtbar, auch nach einem abgebrochenen/lückigen Lauf.
    done_flag = bool((baum or {}).get("followup_tx_oriented_done")) and voll
    return {
        "internal_predecessor_count": n,
        "followup_tx_oriented_suggested": n >= 2 or (
            bool(baum and baum.get("found")) and not voll
        ),
        "followup_resolve_unresolved_suggested": unresolved > 0 or (
            bool(baum and baum.get("found")) and not voll
        ),
        "followup_tx_oriented_done": done_flag,
        "verfolgt_vollstaendig": voll,
        # Explizit für UI/Liste: Abbruch, fehlende Prevouts, Lücken, …
        "unvollstaendig": bool(baum and baum.get("found") and not voll),
    }


def trace_utxo(
    get_tx,
    txid: str,
    vout: int,
    own_addresses: set,
    *,
    wallet=None,
    cache_dir: Path | None = None,
    immutable_cache_dir: Path | None = None,
    fetch_address_utxos=None,
    cache_source: str | None = None,
    progress=None,
    resolve_bundled: bool = False,
    merke_tx_oriented_done: bool = False,
    stop_before_ts: int | None = None,
    resume_origin: dict | None = None,
) -> dict:
    """
    Führt die Herkunftsanalyse durch und liefert sie als Baum aus Wörterbüchern.

    Das Ergebnis wird im Ingress-Cache festgehalten — ohne das sähe die
    Steuerjahr-Auswertung nichts davon. *immutable_cache_dir* benennt dessen
    Ziel; fehlt es, wird es aus *cache_dir* abgeleitet.

    *progress* ist ein Callable[[str], None] — dieselbe Form wie
    trace_engine.ProgressCallback. Wird es von einem Job durchgereicht, wirkt
    ein Abbruch an jeder Fortschrittsmeldung.

    *resolve_bundled*: große Sammel-Txs vollständig auflösen (alle eigenen
    Inputs), Opt-in aus der GUI.

    *merke_tx_oriented_done*: nach erfolgreicher Folgeanalyse am Baum
    speichern — UI zeigt dann Hinweis statt Knopf.

    *stop_before_ts*: Steuer-Horizont — Trace endet an Hops vor Stichtag/
    Haltefrist-Anfang (siehe ``analyze.trace_utxo_origin``).

    *resume_origin*: gespeicherter Analyse-Rohbaum. Bei vollem Lauf werden
    Lücken nachgezogen (tax_horizon, error-Prevouts, unvollständige interne
    Zweige) — fertige Äste bleiben erhalten (kein Komplett-Neulauf).
    """
    fortschritt = _FortschrittsAdapter(progress) if progress else None
    txid_n = main._normalize_txid(txid)
    vout_n = int(vout)

    # Bekannte Scan-Höhe → P2P kann bei getdata-notfound den Block holen.
    hoehe = _blockhoehe_fuer_utxo(txid_n, vout_n, cache_dir, wallet)
    if hoehe:
        try:
            from bip158_scanner import note_tx_height

            note_tx_height(txid_n, hoehe)
        except Exception:
            pass

    if (
        resume_origin
        and isinstance(resume_origin, dict)
        and stop_before_ts is None
        and (
            analyze._hat_tax_horizon(resume_origin)
            or analyze._origin_hat_luecken(resume_origin)
        )
        and analyze.hat_brauchbaren_teilfortschritt(resume_origin)
    ):
        if progress:
            try:
                if analyze._hat_tax_horizon(resume_origin):
                    progress("Setze Steuer-Horizont bis extern/Coinbase fort…")
                else:
                    progress("Setze unvollständige Herkunft fort (Teilbaum)…")
            except Exception:
                pass
        roh = analyze.vertiefe_herkunft_luecken(
            resume_origin,
            get_tx,
            own_addresses,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
            progress=fortschritt,
            alle_eigenen_inputs=bool(resolve_bundled),
        )
    else:
        roh = analyze.trace_utxo_origin(
            get_tx,
            txid_n,
            vout_n,
            own_addresses,
            wallet=wallet,
            cache_dir=cache_dir,
            fetch_address_utxos=fetch_address_utxos,
            cache_source=cache_source,
            progress=fortschritt,
            alle_eigenen_inputs=bool(resolve_bundled),
            stop_before_ts=stop_before_ts,
        )

    if roh is None:
        return {
            "found": False,
            "error": "Keine Herkunft ermittelbar.",
            "root": None,
            "children": [],
            "summary": {},
        }

    if roh.get("type") == "error":
        return {
            "found": False,
            "error": erklaere_fehler(roh.get("error")),
            "error_raw": str(roh.get("error", "")),
            "root": {
                "txid": main._normalize_txid(txid),
                "vout": int(vout),
                "utxo": roh.get("utxo", ""),
            },
            "children": [],
            "summary": {},
        }

    kinder = _quellen_zu_knoten(roh, wallet, "0", 1)
    # Wurzel selbst ist Steuer-Horizont (Output alt genug) → künstliches Blatt.
    if roh.get("tax_horizon") and not kinder:
        kinder = [{
            "id": "0.0",
            "type": "tax_horizon",
            "depth": 1,
            "address": (roh.get("addresses") or [""])[0] if roh.get("addresses") else "",
            "amount_sats": int(roh.get("amount_sats", 0) or 0),
            "from_utxo": f"{roh.get('txid', '')}:{int(roh.get('vout', 0) or 0)}",
            "wallet": None,
            "time_label": roh.get("time") or "",
            "block_height": None,
            "block_time": roh.get("time_ts"),
            "tax_horizon": True,
            "children": [],
            "expandable": False,
            "note": (
                "Für Steuerjahr ausreichend (vor Stichtag bzw. "
                "Haltefrist-Anfang). Herkunft tracen führt bis "
                "extern/Coinbase weiter."
            ),
            "label": None,
        }]
    _anreichere_externe_zeiten(kinder, immutable_cache_dir)
    adressen = roh.get("addresses") or []
    wurzel_adresse = adressen[0] if adressen else ""

    # Ergebnis festhalten, sonst sieht das Steuerjahr nichts davon: Es liest
    # das Anschaffungsdatum allein aus dem Ingress-Cache und weist die Zeile
    # sonst weiter als "nur Output-Datum" aus. Dieselbe Funktion benutzt das
    # CLI — die Einträge beider Wege sind damit identisch.
    analyze.persist_utxo_ingress(
        roh,
        txid=roh.get("txid") or main._normalize_txid(txid),
        vout=int(roh.get("vout", vout) or 0),
        address=wurzel_adresse,
        amount_sats=int(roh.get("amount_sats", 0) or 0),
        wallet=wallet,
        cache_dir=cache_dir,
        immutable_cache_dir=immutable_cache_dir,
    )

    summary = _summen(kinder)
    baum_probe = {
        "found": True,
        "summary": summary,
        "children": kinder,
        "tx_class": roh.get("tx_class"),
        "coinjoin_noise_skipped": bool(roh.get("coinjoin_noise_skipped")),
        "tax_horizon": bool(roh.get("tax_horizon")),
    }
    voll = trace_cache.baum_ist_vollstaendig(baum_probe)
    steuer_ok = trace_cache.baum_ist_steuer_ausreichend(baum_probe)
    juengste = None
    if voll or steuer_ok:
        extern = analyze._youngest_external_ingress(roh)
        wallet_eingang = analyze._youngest_wallet_ingress(roh, wallet)
        horizon = analyze._youngest_tax_horizon(roh)
        if extern and extern.get("time_ts"):
            juengste = int(extern["time_ts"])
        elif wallet_eingang and wallet_eingang.get("time_ts"):
            juengste = int(wallet_eingang["time_ts"])
        elif horizon and horizon.get("time_ts"):
            juengste = int(horizon["time_ts"])

    root = {
        "id": "0",
        "txid": roh.get("txid", ""),
        "vout": roh.get("vout", 0),
        "address": wurzel_adresse,
        "wallet": wallet.resolve_address(wurzel_adresse) if wallet else None,
        "amount_sats": int(roh.get("amount_sats", 0) or 0),
        "time_label": roh.get("time", ""),
        "type": roh.get("type", "utxo"),
        "label": None,
    }
    # Börsen-CSV: Empfangs-Tx als Auszahlung der Börse markieren (wenn gelistet).
    root["label"] = labels.beschrifte(
        wurzel_adresse or "", txid=str(roh.get("txid") or ""),
    )
    if roh.get("tax_horizon"):
        root["tax_horizon"] = True
    if roh.get("tx_class"):
        root["tx_class"] = roh.get("tx_class")
        root["tx_class_label"] = roh.get("tx_class_label") or ""
        root["tx_class_label_en"] = roh.get("tx_class_label_en") or ""
        root["note"] = root["tx_class_label"]
        # Exchange-Batch: Soft-Label anhand bekannter Börsen in den Kindern
        # konkretisieren (Prevouts oft erst im Baum gelabelt).
        if str(root.get("tx_class") or "") == "exchange_batch":
            try:
                from core.trace_cache import boerse_namen_im_baum
                from core.tx_classify import soft_label_exchange_batch

                probe = {"root": root, "children": kinder}
                namen = boerse_namen_im_baum(probe)
                if not namen:
                    namen = boerse_namen_im_baum({"root": roh, "children": roh.get("sources") or []})
                if namen:
                    root["tx_class_label"] = soft_label_exchange_batch(namen, lang="de")
                    root["tx_class_label_en"] = soft_label_exchange_batch(namen, lang="en")
                    root["note"] = root["tx_class_label"]
                    root["boerse_namen"] = namen
            except Exception:
                pass
    if roh.get("exchange_stop"):
        root["exchange_stop"] = True
        if roh.get("exchange_label"):
            root["label"] = roh.get("exchange_label")
        root["note"] = (
            "Börse — Herkunft endet an der Ein-/Auszahlung "
            "(keine Hops darüber hinaus)."
        )

    ergebnis = {
        "found": True,
        "error": "",
        "root": root,
        "children": kinder,
        "summary": summary,
        "verfolgt_vollstaendig": voll,
        "steuer_ausreichend": steuer_ok,
        "juengste_sats_ts": juengste,
        "max_trace_depth": analyze.MAX_TRACE_DEPTH,
        "tx_class": roh.get("tx_class"),
        "tx_class_label": roh.get("tx_class_label") or "",
        # Rohbaum für späteren Voll-Lauf (nur Horizont nachziehen).
        "origin_tree": roh,
    }
    ergebnis.update(folge_meta(ergebnis))
    # Done nur bei echtem Blatt-Ende (external/coinbase). Sonst bleibt
    # Entwirren anwählbar und behauptet nicht fälschlich „Lücken geschlossen“.
    if merke_tx_oriented_done and voll:
        ergebnis["followup_tx_oriented_done"] = True
    else:
        ergebnis["followup_tx_oriented_done"] = False
    # Meta erneut, damit suggested/done zur finalen Vollständigkeit passen.
    ergebnis.update(folge_meta(ergebnis))

    # Den Baum selbst ablegen, damit ihn der nächste Seitenaufruf ohne Job und
    # ohne Node-Verbindung zeigen kann. Die Adressmenge wandert als
    # Fingerabdruck mit: Ob ein Zweig intern oder extern ist, hängt an ihr.
    trace_cache.speichern(
        ergebnis["root"]["txid"] or main._normalize_txid(txid),
        int(ergebnis["root"]["vout"] or 0),
        ergebnis,
        _immutable_ziel(cache_dir, immutable_cache_dir),
        own_addresses,
    )

    return ergebnis


def _immutable_ziel(cache_dir, immutable_cache_dir) -> Path | None:
    """
    Wohin unveränderliche Daten gehören.

    Ausdrücklich benanntes Verzeichnis gewinnt; sonst das neben dem
    UTXO-Cache — so macht es auch das CLI. Ohne beides: nirgendwohin.
    """
    if immutable_cache_dir:
        return Path(immutable_cache_dir)
    if cache_dir:
        return main.resolve_immutable_cache_dir(utxo_cache_dir=cache_dir)
    return None


class _FortschrittsAdapter:
    """
    analyze.trace_utxo_origin erwartet ein Objekt mit .update(text);
    core.jobs liefert eine schlichte Funktion. Dieser Adapter verbindet beide.
    """

    def __init__(self, callback):
        self._callback = callback

    def update(self, message: str) -> None:
        self._callback(message)

    def clear(self) -> None:
        pass
