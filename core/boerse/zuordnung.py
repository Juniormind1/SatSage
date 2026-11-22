"""Auszahlung ↔ On-Chain-Empfang, nur als Erklärung (Stufe 1)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from core.boerse.modell import Art, Buchung, Zuordnung

FENSTER_VOR_S = 3600
FENSTER_NACH_S = 72 * 3600
# Idee nach Kassiber (MIT): exakte TxID mit genau einem eigenen Output
# und passendem Betrag gilt als bestätigt; sonst nicht raten.


@dataclass(frozen=True)
class KettenEmpfang:
    """Ein eigener Empfangs-Output. Nur die für die Zuordnung nötigen Felder."""

    txid: str
    vout: int
    sats: int
    zeit_ts: int | None = None
    adresse: str | None = None
    eigene_eingaenge: bool = False


@dataclass(frozen=True)
class ZuordnungLauf:
    zuordnungen: tuple[Zuordnung, ...]
    luecken: tuple[str, ...]
    quarantaene: tuple[dict, ...]
    kein_hop: tuple[str, ...]  # Lightning-Auszahlungen


def erwarteter_output_sats(buchung: Buchung) -> int:
    """On-Chain-Output: |amount|, Gebühr kommt obendrauf (Kraken, Strike)."""
    return abs(int(buchung.sats))


def im_fenster(buchung_ts: int | None, ketten_ts: int | None) -> bool:
    if buchung_ts is None or ketten_ts is None:
        return False
    return buchung_ts - FENSTER_VOR_S <= ketten_ts <= buchung_ts + FENSTER_NACH_S


def schlage_vor(
    buchungen: list[Buchung] | tuple[Buchung, ...],
    empfange: list[KettenEmpfang] | tuple[KettenEmpfang, ...],
    bestehend: list[Zuordnung] | tuple[Zuordnung, ...] = (),
) -> ZuordnungLauf:
    """Ordnet Auszahlungen Empfängen zu. Bestehende Entscheidungen bleiben."""
    entschieden = {
        (z.konto, z.auszahlung_ref): z
        for z in bestehend
        if z.status in {"bestaetigt", "abgelehnt", "vorschlag"}
    }
    # Offene Vorschläge dürfen durch einen neuen Lauf ersetzt werden.
    fest = {
        k: z for k, z in entschieden.items()
        if z.status in {"bestaetigt", "abgelehnt"}
    }
    belegt: set[tuple[str, int]] = {
        (z.txid, z.vout) for z in fest.values() if z.status == "bestaetigt"
    }

    zuordnungen: list[Zuordnung] = list(fest.values())
    luecken: list[str] = []
    quarantaene: list[dict] = []
    kein_hop: list[str] = []

    nach_txid: dict[str, list[KettenEmpfang]] = defaultdict(list)
    for e in empfange:
        nach_txid[e.txid.lower()].append(e)

    offen: list[Buchung] = []
    for b in buchungen:
        if b.art is not Art.BTC_AUSGANG:
            continue
        if (b.konto, b.ref) in fest:
            continue
        if b.lightning:
            kein_hop.append(b.ref)
            continue
        offen.append(b)

    # Zuerst Gruppen mit gleicher TxID (inkl. Batch).
    rest: list[Buchung] = []
    gruppen: dict[str, list[Buchung]] = defaultdict(list)
    ohne_txid: list[Buchung] = []
    for b in offen:
        if b.txid:
            gruppen[b.txid.lower()].append(b)
        else:
            ohne_txid.append(b)
    for tid, gruppe in gruppen.items():
        outs = nach_txid.get(tid, [])
        if not outs:
            rest.extend(gruppe)
            continue
        ergebnis = _txid_gruppe(gruppe, outs, belegt)
        zuordnungen.extend(ergebnis[0])
        quarantaene.extend(ergebnis[1])
        rest.extend(ergebnis[2])
        for z in ergebnis[0]:
            if z.status == "bestaetigt":
                belegt.add((z.txid, z.vout))

    for b in ohne_txid + rest:
        z, q, luecke = _adresse_oder_zeit(b, empfange, belegt)
        if z:
            zuordnungen.append(z)
            belegt.add((z.txid, z.vout))
        elif q:
            quarantaene.append(q)
        elif luecke:
            luecken.append(b.ref)

    return ZuordnungLauf(tuple(zuordnungen), tuple(luecken), tuple(quarantaene), tuple(kein_hop))


def _txid_gruppe(
    gruppe: list[Buchung],
    outs: list[KettenEmpfang],
    belegt: set[tuple[str, int]],
) -> tuple[list[Zuordnung], list[dict], list[Buchung]]:
    frei = [o for o in outs if (o.txid.lower(), o.vout) not in belegt]
    if any(o.eigene_eingaenge for o in outs):
        return [], [
            {"ref": b.ref, "konto": b.konto, "grund": "eigene Eingänge in der Tx"}
            for b in gruppe
        ], []
    if len(gruppe) == 1 and len(frei) > 1:
        return [], [{"ref": gruppe[0].ref, "konto": gruppe[0].konto, "grund": "zwei eigene Outputs"}], []
    if len(gruppe) == 1 and len(frei) == 1:
        b, o = gruppe[0], frei[0]
        if o.sats == erwarteter_output_sats(b):
            return [_zuordnung(b, o, "txid_exakt", "bestaetigt")], [], []
        return [], [{"ref": b.ref, "konto": b.konto, "grund": "Betrag passt nicht zur Tx"}], []

    # Mehrere Auszahlungen, mehrere Outputs: eindeutige Betragspaarung.
    benutzt: set[int] = set()
    paar: list[tuple[Buchung, KettenEmpfang]] = []
    mehrdeutig = False
    for b in gruppe:
        soll = erwarteter_output_sats(b)
        treffer = [o for i, o in enumerate(frei) if i not in benutzt and o.sats == soll]
        if len(treffer) == 1:
            benutzt.add(frei.index(treffer[0]))
            paar.append((b, treffer[0]))
        elif len(treffer) > 1:
            mehrdeutig = True
        else:
            # Vielleicht Summe mehrerer Buchungen auf einen Output.
            mehrdeutig = True
    if mehrdeutig or len(paar) != len(gruppe):
        # Summe: alle Buchungen auf genau einen freien Output mit passender Summe.
        if len(frei) == 1 and sum(erwarteter_output_sats(b) for b in gruppe) == frei[0].sats:
            return [
                _zuordnung(b, frei[0], "txid_exakt", "vorschlag")
                for b in gruppe
            ], [], []
        return [], [
            {"ref": b.ref, "konto": b.konto, "grund": "Batch nicht eindeutig zuordenbar"}
            for b in gruppe
        ], []
    return [_zuordnung(b, o, "txid_exakt", "bestaetigt") for b, o in paar], [], []


def _adresse_oder_zeit(
    b: Buchung,
    empfange: list[KettenEmpfang] | tuple[KettenEmpfang, ...],
    belegt: set[tuple[str, int]],
) -> tuple[Zuordnung | None, dict | None, bool]:
    soll = erwarteter_output_sats(b)
    frei = [
        e for e in empfange
        if (e.txid.lower(), e.vout) not in belegt and e.sats == soll
    ]
    if b.adresse:
        nach_adr = [e for e in frei if e.adresse == b.adresse and im_fenster(b.zeit_ts, e.zeit_ts)]
        if len(nach_adr) == 1:
            return _zuordnung(b, nach_adr[0], "adresse", "vorschlag"), None, False
        if len(nach_adr) > 1:
            return None, {"ref": b.ref, "konto": b.konto, "grund": "mehrere Kandidaten"}, False
    zeit = [e for e in frei if im_fenster(b.zeit_ts, e.zeit_ts)]
    if len(zeit) == 1:
        return _zuordnung(b, zeit[0], "betrag_zeit", "vorschlag"), None, False
    if len(zeit) > 1:
        return None, {"ref": b.ref, "konto": b.konto, "grund": "mehrere Kandidaten"}, False
    return None, None, True


def _zuordnung(b: Buchung, e: KettenEmpfang, methode: str, status: str) -> Zuordnung:
    return Zuordnung(
        konto=b.konto,
        auszahlung_ref=b.ref,
        txid=e.txid.lower(),
        vout=e.vout,
        sats_onchain=e.sats,
        methode=methode,
        status=status,
        bestaetigt_ts=None,
    )


def mergen(bestehend: list[Zuordnung] | tuple[Zuordnung, ...], lauf: ZuordnungLauf) -> list[Zuordnung]:
    """Neue Vorschläge ersetzen alte Vorschläge; bestätigt/abgelehnt bleibt."""
    fest = [z for z in bestehend if z.status in {"bestaetigt", "abgelehnt"}]
    schluessel = {(z.konto, z.auszahlung_ref) for z in fest}
    neu = [z for z in lauf.zuordnungen if (z.konto, z.auszahlung_ref) not in schluessel]
    return fest + neu


def setze_status(
    zuordnungen: list[Zuordnung] | tuple[Zuordnung, ...],
    *,
    konto: str,
    auszahlung_ref: str,
    status: str,
    bestaetigt_ts: int | None,
    txid: str | None = None,
    vout: int | None = None,
    sats_onchain: int | None = None,
    methode: str | None = None,
) -> list[Zuordnung]:
    if status not in {"bestaetigt", "abgelehnt", "vorschlag"}:
        raise ValueError("Unbekannter Zuordnungsstatus.")
    gefunden = False
    aus: list[Zuordnung] = []
    for z in zuordnungen:
        if z.konto == konto and z.auszahlung_ref == auszahlung_ref:
            gefunden = True
            aus.append(Zuordnung(
                konto=z.konto,
                auszahlung_ref=z.auszahlung_ref,
                txid=(txid or z.txid).lower(),
                vout=z.vout if vout is None else int(vout),
                sats_onchain=z.sats_onchain if sats_onchain is None else int(sats_onchain),
                methode=methode or z.methode,
                status=status,
                bestaetigt_ts=bestaetigt_ts if status == "bestaetigt" else None,
            ))
        else:
            aus.append(z)
    if not gefunden:
        if not txid or vout is None:
            raise ValueError("Zuordnung nicht gefunden.")
        aus.append(Zuordnung(
            konto=konto,
            auszahlung_ref=auszahlung_ref,
            txid=txid.lower(),
            vout=int(vout),
            sats_onchain=int(sats_onchain or 0),
            methode=methode or "manuell",
            status=status,
            bestaetigt_ts=bestaetigt_ts if status == "bestaetigt" else None,
        ))
    return aus


def nach_outpoint(zuordnungen: list[Zuordnung] | tuple[Zuordnung, ...]) -> dict[str, Zuordnung]:
    """txid:vout → erste nicht abgelehnte Zuordnung."""
    index: dict[str, Zuordnung] = {}
    for z in zuordnungen:
        if z.status == "abgelehnt":
            continue
        key = f"{z.txid}:{z.vout}"
        # Bestätigt gewinnt vor Vorschlag.
        alt = index.get(key)
        if alt is None or (alt.status != "bestaetigt" and z.status == "bestaetigt"):
            index[key] = z
    return index



def sammeln_empfaenge(utxo_cache_dir: "Path | None" = None) -> list[KettenEmpfang]:
    """Liest eigene Empfangs-Outputs aus dem UTXO-Cache (unspent)."""
    from pathlib import Path

    from core import xpub_cache
    from core.wallet_context import EXTERNAL_ADDRESS_CACHE_NAME

    cache = Path(utxo_cache_dir or xpub_cache.UTXO_CACHE_DIR)
    if not cache.is_dir():
        return []
    treffer: list[KettenEmpfang] = []
    gesehen: set[tuple[str, int]] = set()
    for pfad in sorted(cache.glob("*.json")):
        if pfad.name == EXTERNAL_ADDRESS_CACHE_NAME:
            continue
        try:
            import json
            daten = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(daten, dict):
            continue
        for utxo in daten.get("utxos") or []:
            if not isinstance(utxo, dict):
                continue
            tid = str(utxo.get("txid") or "").strip().lower()
            if len(tid) != 64:
                continue
            try:
                vout = int(utxo.get("vout", -1))
                sats = int(utxo.get("value", 0))
            except (TypeError, ValueError):
                continue
            if vout < 0 or sats < 0 or (tid, vout) in gesehen:
                continue
            status = utxo.get("status") or {}
            try:
                zeit = int(status.get("block_time") or 0) or None
            except (TypeError, ValueError):
                zeit = None
            gesehen.add((tid, vout))
            treffer.append(KettenEmpfang(
                txid=tid,
                vout=vout,
                sats=sats,
                zeit_ts=zeit,
                adresse=str(utxo.get("address") or "") or None,
            ))
    return treffer


_erklaerung_cache: dict[str, tuple[str, dict]] = {}


def erklaerung_fuer_outpoint(txid: str, vout: int, cache_dir=None) -> dict | None:
    """Konto, Status und Methode zu einem Empfang, oder None. Keine Datumsfelder."""
    from core.paths import exchange_dir
    from core.boerse import speicher

    wurzel = cache_dir or exchange_dir()
    from pathlib import Path
    wurzel = Path(wurzel)
    sig = "0"
    if wurzel.is_dir():
        try:
            sig = str(sum(int(p.stat().st_mtime) for p in wurzel.glob("*/zuordnungen.json")))
        except OSError:
            sig = "0"
    key = str(wurzel)
    if _erklaerung_cache.get(key, ("", None))[0] != sig:
        index: dict[str, dict] = {}
        for slug in speicher.v2_slugs(wurzel):
            for z in nach_outpoint(speicher.lies_zuordnungen(slug, wurzel)).values():
                index[f"{z.txid}:{z.vout}"] = {
                    "konto": z.konto,
                    "status": z.status,
                    "methode": z.methode,
                }
        _erklaerung_cache.clear()
        _erklaerung_cache[key] = (sig, index)
    index = _erklaerung_cache[key][1]
    tid = (txid or "").strip().lower()
    try:
        n = int(vout)
    except (TypeError, ValueError):
        return None
    return index.get(f"{tid}:{n}")


def aktualisiere_zuordnungen(slug: str, exchange_dir, utxo_cache_dir) -> dict:
    """Rechnet Vorschläge neu und speichert sie, bestätigt/abgelehnt bleibt."""
    from pathlib import Path
    from core.boerse import speicher

    wurzel = Path(exchange_dir)
    buchungen = speicher.lies_buchungen(slug, wurzel)
    bestehend = speicher.lies_zuordnungen(slug, wurzel)
    lauf = schlage_vor(buchungen, sammeln_empfaenge(utxo_cache_dir), bestehend)
    gem = mergen(bestehend, lauf)
    speicher.schreibe_zuordnungen(slug, wurzel, gem)
    _erklaerung_cache.clear()
    return {
        "slug": slug,
        "zuordnungen": [speicher.zuordnung_zu_dict(z) for z in gem],
        "luecken": list(lauf.luecken),
        "quarantaene": list(lauf.quarantaene),
        "kein_hop": list(lauf.kein_hop),
    }
