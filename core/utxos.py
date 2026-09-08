"""
UTXO-Rangfolge als Daten.

Datenliefernde Entsprechung zu main.list_top_wallet_utxos / _print_utxo_rank_row
(die weiterhin das CLI bedienen). Dieselben Hilfsfunktionen, dieselbe
Sortierung — nur ohne Ausgabe, damit die Zahlen in beiden Oberflächen
garantiert übereinstimmen.
"""
from __future__ import annotations

from pathlib import Path

import labels
import main
from core import trace_cache


def _hold_days(utxo: dict) -> int | None:
    """Tage seit Bestätigung — Grundlage für die Haltedauer."""
    status = utxo.get("status") or {}
    block_time = status.get("block_time")
    if not block_time:
        return None
    import time

    return max(0, int((time.time() - int(block_time)) // 86_400))


def _zeit_ohne_block(label: str) -> str:
    """
    Entfernt das führende 'Block 857,930 · ' aus einem Zeitstempel.

    main._format_tx_time setzt Blockhöhe und Zeit zusammen; die Oberfläche
    zeigt beides getrennt und formatiert die Höhe selbst.
    """
    if label.startswith("Block ") and " · " in label:
        return label.split(" · ", 1)[1]
    return label


def utxo_as_dict(
    utxo: dict,
    *,
    wallet=None,
    immutable_cache_dir: Path | None = None,
    own_addresses=None,
) -> dict:
    """
    Ein UTXO in der Form, die die Oberfläche braucht.

    Beträge bleiben in Satoshis (int) — die Umrechnung in BTC passiert erst
    bei der Anzeige, damit unterwegs nichts durch float verloren geht.
    """
    address = utxo.get("address", "")
    label = wallet.resolve_address(address) if wallet else None

    # scantxoutset liefert oft nur die Höhe — Zeit aus lokalem Header-Cache.
    if immutable_cache_dir is not None:
        main.enrich_utxos_with_block_times([utxo], immutable_cache_dir)

    status = utxo.get("status") or {}
    eintrag = {
        "txid": utxo.get("txid", ""),
        "vout": int(utxo.get("vout", 0)),
        "address": address,
        "value_sats": int(utxo.get("value", 0)),
        "wallet": label,
        "confirmed": bool(status.get("confirmed", False)),
        "block_height": status.get("block_height"),
        "block_time": status.get("block_time"),
        # Nur Datum und Uhrzeit — die Blockhöhe steht als eigenes Feld daneben
        # und würde sonst doppelt erscheinen, dazu mit englischer
        # Tausendertrennung aus der CLI-Formatierung.
        "time_label": _zeit_ohne_block(main._format_utxo_status(utxo)),
        "status_label": main._format_utxo_status(utxo),
        "hold_days": _hold_days(utxo),
        "youngest_sats_time": None,
        "herkunft_label": None,
        "key": utxo_key(utxo),
        # Ob zu diesem UTXO schon ein Herkunftsbaum vorliegt. Die Liste zeigt
        # das an, damit man vor dem Aufklappen weiß, ob es sofort geht oder
        # eine Analyse startet.
        "verfolgt": False,
        "verfolgt_ts": None,
        "verfolgt_veraltet": False,
        "verfolgt_vollstaendig": False,
        "juengste_sats_ts": None,
        # Mempool: Ausgabe unterwegs (eigener Electrs).
        "spending_pending": bool(utxo.get("spending_pending")),
        "spent_txid": utxo.get("spent_txid") or "",
        # Mempool: eigener Empfang noch unbestätigt (Selbstüberweisung/Change).
        "receive_pending": bool(
            utxo.get("receive_pending")
            or (
                not status.get("confirmed", True)
                and status.get("block_height") in (None, 0)
                and not utxo.get("spending_pending")
            )
        ),
    }

    if immutable_cache_dir:
        ingress = main.load_utxo_ingress_cache(
            eintrag["txid"], eintrag["vout"], immutable_cache_dir
        )
        if ingress:
            eintrag["youngest_sats_time"] = ingress.get("youngest_time")
            # Woher die Sats zuletzt von außen kamen. Ist die Adresse einem
            # Dienst zuzuordnen, gehört das an das UTXO — sonst müsste man
            # für dieselbe Auskunft erst den Herkunftsbaum aufklappen.
            eintrag["herkunft_label"] = labels.beschrifte(
                ingress.get("external_address") or ""
            )

        gespeichert = trace_cache.kopf(
            eintrag["txid"], eintrag["vout"], immutable_cache_dir, own_addresses
        )
        if gespeichert:
            eintrag["verfolgt"] = True
            eintrag["verfolgt_ts"] = gespeichert["erstellt_ts"]
            eintrag["verfolgt_veraltet"] = gespeichert["veraltet"]
            # Nur bei vollständigem Baum: jeder Sat endet außen, das
            # jüngste Datum ist dann keine Untergrenze.
            voll = bool(gespeichert.get("vollstaendig"))
            if ingress and ingress.get("external_untergrenze"):
                voll = False
            eintrag["verfolgt_vollstaendig"] = voll
            if voll and ingress:
                eintrag["juengste_sats_ts"] = (
                    ingress.get("external_time_ts")
                    or ingress.get("youngest_time_ts")
                )

    return eintrag


def _roh_zeit(utxo: dict) -> int:
    status = utxo.get("status") or {}
    return int(status.get("block_time") or 0)


def _eintrag_zeit(eintrag: dict) -> int:
    return int(eintrag.get("spent_time_ts") or eintrag.get("block_time") or 0)


def rank_wallet_utxos(
    utxos: list[dict],
    *,
    limit: int | None = None,
    wallet=None,
    immutable_cache_dir: Path | None = None,
    own_addresses=None,
    sort: str = "betrag",
) -> dict:
    """
    Sortiert und reichert die Einträge an.

    *sort*: ``betrag`` (größte zuerst, Default) oder ``datum`` (neueste zuerst).
    Die Summen beziehen sich immer auf *alle* UTXOs, nicht nur auf die
    angezeigten — sonst liest man aus einer Top-10-Liste einen falschen
    Wallet-Bestand ab.
    """
    if sort == "datum":
        # Unbestätigte (Mempool) nach oben — block_time fehlt sonst am Ende.
        sortiert = sorted(
            utxos,
            key=lambda u: (
                0 if (u.get("receive_pending") or u.get("spending_pending")) else 1,
                -_roh_zeit(u),
            ),
        )
    else:
        sortiert = sorted(utxos, key=lambda u: int(u.get("value", 0)), reverse=True)
    # spending_pending zählt nicht in die Summe: Funds sind unterwegs;
    # Self-Tx-Empfänge (receive_pending) ersetzen den Betrag abzüglich Fee.
    gesamt_sats = sum(
        int(u.get("value", 0))
        for u in sortiert
        if not u.get("spending_pending")
    )
    pending_spending = sum(1 for u in sortiert if u.get("spending_pending"))
    pending_receive = sum(1 for u in sortiert if u.get("receive_pending"))

    ausschnitt = sortiert if limit is None else sortiert[:limit]
    eintraege = [
        dict(
            utxo_as_dict(
                utxo,
                wallet=wallet,
                immutable_cache_dir=immutable_cache_dir,
                own_addresses=own_addresses,
            ),
            rank=position,
        )
        for position, utxo in enumerate(ausschnitt, start=1)
    ]
    shown_sats = sum(
        e["value_sats"] for e in eintraege if not e.get("spending_pending")
    )

    return {
        "total_count": len(sortiert),
        "total_sats": gesamt_sats,
        "shown_count": len(eintraege),
        "shown_sats": shown_sats,
        "utxos": eintraege,
        "addresses": group_by_address(eintraege, sort=sort),
        "pending_spending_count": pending_spending,
        "pending_receive_count": pending_receive,
    }


def historische_eintraege(
    verlauf: list[dict],
    *,
    wallet=None,
    immutable_cache_dir: Path | None = None,
    own_addresses=None,
    limit: int | None = None,
    sort: str = "datum",
) -> dict:
    """
    Die bereits ausgegebenen Outputs aus dem Verlauf — in derselben Form wie
    UTXOs, damit die Herkunftsansicht sie ohne Sonderweg anzeigen und tracen
    kann.

    Sie sind aus dem UTXO-Cache verschwunden, sobald sie ausgegeben wurden.
    Wer nachsehen will, woher die Sats kamen, die das Gerät längst verlassen
    haben, findet sie nur hier.

    Sortiert nach Abgang, jüngster zuerst: Wonach man sucht, ist meist das
    zuletzt Bewegte.
    """
    ausgegeben = [e for e in verlauf if e.get("spent")]
    if sort == "betrag":
        ausgegeben.sort(key=lambda e: int(e.get("value", 0)), reverse=True)
    else:
        ausgegeben.sort(key=lambda e: e.get("spent_time_ts") or 0, reverse=True)

    ausschnitt = ausgegeben if limit is None else ausgegeben[:limit]
    eintraege = []
    for eintrag in ausschnitt:
        angereichert = utxo_as_dict(
            eintrag,
            wallet=wallet,
            immutable_cache_dir=immutable_cache_dir,
            own_addresses=own_addresses,
        )
        angereichert["spent"] = True
        angereichert["spent_txid"] = eintrag.get("spent_txid") or ""
        angereichert["spent_time_ts"] = eintrag.get("spent_time_ts")
        angereichert["spent_height"] = eintrag.get("spent_height")
        angereichert["spent_pending"] = bool(eintrag.get("spent_pending"))
        eintraege.append(angereichert)

    return {
        "total_count": len(ausgegeben),
        "total_sats": sum(int(e.get("value", 0)) for e in ausgegeben),
        "shown_count": len(eintraege),
        "utxos": eintraege,
        "addresses": group_by_address(eintraege, sort=sort),
    }


def merge_pending_spends_in_verlauf(
    anhang: dict,
    pending: list[dict],
    *,
    wallet=None,
    immutable_cache_dir: Path | None = None,
    own_addresses=None,
    limit: int | None = None,
    sort: str = "datum",
) -> dict:
    """
    Hängt Mempool-Pending-Spends vor den bestätigten Verlauf
    (jüngste/Pending zuerst in der ausgegeben-Liste).
    """
    if not pending:
        return anhang
    pending_form = historische_eintraege(
        pending,
        wallet=wallet,
        immutable_cache_dir=immutable_cache_dir,
        own_addresses=own_addresses,
        limit=None,
        sort=sort,
    )
    alt = anhang.get("verlauf") or {}
    # Pending vorne, dann bestätigte — gleiche keys nicht doppelt.
    gesehen = {u.get("key") for u in (pending_form.get("utxos") or [])}
    rest = [
        u for u in (alt.get("utxos") or [])
        if u.get("key") not in gesehen
    ]
    gemischt = list(pending_form.get("utxos") or []) + rest
    if limit is not None:
        gemischt = gemischt[:limit]
    total_sats = sum(int(u.get("value_sats") or 0) for u in gemischt)
    # total_count = alle (pending + bestätigt), nicht nur Ausschnitt
    total_count = (
        int(pending_form.get("total_count") or 0)
        + int(alt.get("total_count") or 0)
    )
    return {
        "verlauf": {
            "total_count": total_count,
            "total_sats": (
                int(pending_form.get("total_sats") or 0)
                + int(alt.get("total_sats") or 0)
            ),
            "shown_count": len(gemischt),
            "utxos": gemischt,
            "addresses": group_by_address(gemischt, sort=sort),
            "pending_count": int(pending_form.get("total_count") or 0),
        },
        "hat_verlauf": True,
        "pending_spends": int(pending_form.get("total_count") or 0),
    }


def utxo_key(utxo: dict) -> str:
    """Eindeutige Kennung eines UTXO — dieselbe Form wie im Trace."""
    return f"{utxo.get('txid', '')}:{int(utxo.get('vout', 0))}"


def group_by_address(eintraege: list[dict], *, sort: str = "betrag") -> list[dict]:
    """
    Fasst angereicherte UTXO-Einträge nach Adresse zusammen.

    *sort* ``betrag``: größter Bestand zuerst, darin größte UTXOs.
    *sort* ``datum``: zuletzt bewegte Adresse zuerst, darin neueste zuerst.
    """
    gruppen: dict[str, dict] = {}
    for eintrag in eintraege:
        adresse = eintrag.get("address", "")
        gruppe = gruppen.setdefault(adresse, {
            "address": adresse,
            "wallet": eintrag.get("wallet"),
            "utxo_count": 0,
            "total_sats": 0,
            "utxos": [],
        })
        gruppe["utxo_count"] += 1
        # spending_pending nicht in den Adress-Bestand — Funds unterwegs.
        if not eintrag.get("spending_pending"):
            gruppe["total_sats"] += eintrag["value_sats"]
        gruppe["utxos"].append(eintrag)

    ergebnis = list(gruppen.values())
    for gruppe in ergebnis:
        if sort == "datum":
            gruppe["utxos"].sort(key=_eintrag_zeit, reverse=True)
        else:
            gruppe["utxos"].sort(key=lambda e: e["value_sats"], reverse=True)
        zeiten = [_eintrag_zeit(e) for e in gruppe["utxos"] if _eintrag_zeit(e)]
        gruppe["first_seen"] = min(zeiten) if zeiten else None
        gruppe["last_seen"] = max(zeiten) if zeiten else None

    if sort == "datum":
        ergebnis.sort(key=lambda g: g.get("last_seen") or 0, reverse=True)
    else:
        ergebnis.sort(key=lambda g: g["total_sats"], reverse=True)
    return ergebnis


def load_cached_utxos(
    xpub: str,
    cache_dir: Path,
    *,
    immutable_cache_dir: Path | None = None,
    persist_times: bool = True,
) -> list[dict] | None:
    """
    UTXOs eines XPUB aus dem Cache — ohne Netzzugriff.

    Fehlende ``block_time`` werden aus dem lokalen Header-Cache
    (``block_header/`` bzw. ``p2p_headers.bin``) nachgezogen und optional
    zurückgeschrieben, damit scantxoutset-Bestände dieselbe Ankunftsanzeige
    bekommen wie BIP-158-Scans.
    """
    eintrag = main.load_xpub_cache_entry(xpub, cache_dir)
    if eintrag is None:
        return None
    utxos = eintrag.get("utxos") or []
    imm = immutable_cache_dir
    if imm is None:
        imm = main.resolve_immutable_cache_dir(utxo_cache_dir=cache_dir)
    angereichert = main.enrich_utxos_with_block_times(utxos, imm)
    if angereichert and persist_times:
        main.rewrite_utxo_cache_times(xpub, cache_dir, utxos)
    return utxos


def filter_for_wallet(utxos: list[dict], wallet_name: str, wallet) -> list[dict]:
    """Behält nur UTXOs, die dem genannten Wallet zugeordnet sind."""
    return [
        utxo
        for utxo in utxos
        if wallet.resolve_address(utxo.get("address", "")) == wallet_name
    ]
