"""Auszahlung ↔ On-Chain-Empfang, nur als Erklärung (Stufe 1)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from core.boerse.modell import Art, Buchung, Zuordnung
from core.boerse.schwellen import (
    FENSTER_NACH_S,
    FENSTER_VOR_S,
    Schwellen,
    auto_erlaubt,
    betrag_delta_sats,
    betrag_passt,
    bucket_minuten,
    bucket_rel,
    im_fenster as _im_fenster,
    lese_zuordnung_einstellungen,
    standard as standard_schwellen,
    zeit_abstand_s,
)

# Re-Export: bestehende Tests und Aufrufer nutzen die Konstanten weiter.
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
    wallet: str | None = None


@dataclass(frozen=True)
class ZuordnungLauf:
    zuordnungen: tuple[Zuordnung, ...]
    luecken: tuple[str, ...]
    quarantaene: tuple[dict, ...]
    kein_hop: tuple[str, ...]  # Lightning-Auszahlungen


def erwarteter_output_sats(buchung: Buchung) -> int:
    """On-Chain-Output: |amount|, Gebühr kommt obendrauf (Kraken, Strike)."""
    return abs(int(buchung.sats))


def im_fenster(buchung_ts: int | None, ketten_ts: int | None, schwellen: Schwellen | None = None) -> bool:
    return _im_fenster(buchung_ts, ketten_ts, schwellen)


def schlage_vor(
    buchungen: list[Buchung] | tuple[Buchung, ...],
    empfange: list[KettenEmpfang] | tuple[KettenEmpfang, ...],
    bestehend: list[Zuordnung] | tuple[Zuordnung, ...] = (),
    schwellen: Schwellen | None = None,
) -> ZuordnungLauf:
    """Ordnet Auszahlungen Empfängen zu. Bestehende Entscheidungen bleiben."""
    s = schwellen or standard_schwellen()
    import time
    from collections import Counter
    from core.boerse import protokoll
    start = time.perf_counter()
    kandidaten: list[int] = []
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
        ergebnis = _txid_gruppe(gruppe, outs, belegt, kandidaten, s)
        zuordnungen.extend(ergebnis[0])
        quarantaene.extend(ergebnis[1])
        rest.extend(ergebnis[2])
        for z in ergebnis[0]:
            if z.status == "bestaetigt":
                belegt.add((z.txid, z.vout))

    for b in ohne_txid + rest:
        z, q, luecke = _adresse_oder_zeit(b, empfange, belegt, kandidaten, s)
        if z:
            zuordnungen.append(z)
            belegt.add((z.txid, z.vout))
        elif q:
            quarantaene.append(q)
        elif luecke:
            luecken.append(b.ref)

    lauf = ZuordnungLauf(tuple(zuordnungen), tuple(luecken), tuple(quarantaene), tuple(kein_hop))
    n_aus = sum(1 for b in buchungen if b.art is Art.BTC_AUSGANG)
    protokoll.nach_zuordnung(
        n_auszahlungen=n_aus,
        n_empfaenge=len(empfange),
        nach_status=dict(Counter(z.status for z in lauf.zuordnungen)),
        nach_methode=dict(Counter(z.methode for z in lauf.zuordnungen)),
        n_luecken=len(lauf.luecken),
        n_quarantaene=len(lauf.quarantaene),
        n_kein_hop=len(lauf.kein_hop),
        kandidaten=kandidaten,
        quarantaene_gruende=[
            str((q.get("grund") if isinstance(q, dict) else getattr(q, "grund", "")))
            for q in lauf.quarantaene
        ],
        start=start,
    )
    return lauf


def _txid_gruppe(
    gruppe: list[Buchung],
    outs: list[KettenEmpfang],
    belegt: set[tuple[str, int]],
    kandidaten: list[int] | None = None,
    schwellen: Schwellen | None = None,
) -> tuple[list[Zuordnung], list[dict], list[Buchung]]:
    frei = [o for o in outs if (o.txid.lower(), o.vout) not in belegt]
    if kandidaten is not None:
        kandidaten.append(len(frei))
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
            return [_zuordnung(b, o, "txid_exakt", "bestaetigt", durch="txid_exakt")], [], []
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
    return [_zuordnung(b, o, "txid_exakt", "bestaetigt", durch="txid_exakt") for b, o in paar], [], []


def _kandidaten(
    b: Buchung,
    empfange: list[KettenEmpfang] | tuple[KettenEmpfang, ...],
    belegt: set[tuple[str, int]],
    s: Schwellen,
    *,
    nur_adresse: bool = False,
) -> list[KettenEmpfang]:
    soll = erwarteter_output_sats(b)
    geb = int(b.gebuehr_sats or 0)
    treffer: list[KettenEmpfang] = []
    for e in empfange:
        if (e.txid.lower(), e.vout) in belegt:
            continue
        if nur_adresse and not (b.adresse and e.adresse == b.adresse):
            continue
        if not betrag_passt(soll, e.sats, geb, s):
            continue
        if not im_fenster(b.zeit_ts, e.zeit_ts, s):
            continue
        treffer.append(e)

    def _score(e: KettenEmpfang) -> tuple:
        adr = 0 if (b.adresse and e.adresse == b.adresse) else 1
        delta = betrag_delta_sats(soll, e.sats, geb, inkl_gebuehr=s.gebuehr_als_toleranz)
        abstand = zeit_abstand_s(b.zeit_ts, e.zeit_ts)
        zeit = abs(abstand) if abstand is not None else 10**12
        return (adr, delta, zeit)

    treffer.sort(key=_score)
    return treffer


def _abstand_zweit(b: Buchung, treffer: list[KettenEmpfang]) -> int | None:
    if len(treffer) < 2:
        return None
    a1 = zeit_abstand_s(b.zeit_ts, treffer[0].zeit_ts)
    a2 = zeit_abstand_s(b.zeit_ts, treffer[1].zeit_ts)
    if a1 is None or a2 is None:
        return None
    return abs(abs(a2) - abs(a1))


def _adresse_oder_zeit(
    b: Buchung,
    empfange: list[KettenEmpfang] | tuple[KettenEmpfang, ...],
    belegt: set[tuple[str, int]],
    kandidaten: list[int] | None = None,
    schwellen: Schwellen | None = None,
) -> tuple[Zuordnung | None, dict | None, bool]:
    s = schwellen or standard_schwellen()
    # Adresse zuerst, sonst Betrag+Zeit — gleiches Vorgehen wie bisher, nur mit Schwellen.
    if b.adresse:
        nach_adr = _kandidaten(b, empfange, belegt, s, nur_adresse=True)
        if kandidaten is not None:
            kandidaten.append(len(nach_adr))
        if len(nach_adr) == 1:
            return _entscheide_kandidat(b, nach_adr, "adresse", s)
        if len(nach_adr) > 1:
            _kalibrier_log(b, nach_adr, "adresse", "verworfen", s)
            return None, {"ref": b.ref, "konto": b.konto, "grund": "mehrere Kandidaten"}, False
    zeit = _kandidaten(b, empfange, belegt, s, nur_adresse=False)
    if kandidaten is not None and not b.adresse:
        kandidaten.append(len(zeit))
    elif kandidaten is not None and b.adresse:
        kandidaten.append(len(zeit))
    if len(zeit) == 1:
        methode = "adresse" if (b.adresse and zeit[0].adresse == b.adresse) else "betrag_zeit"
        return _entscheide_kandidat(b, zeit, methode, s)
    if len(zeit) > 1:
        _kalibrier_log(b, zeit, "betrag_zeit", "verworfen", s)
        return None, {"ref": b.ref, "konto": b.konto, "grund": "mehrere Kandidaten"}, False
    return None, None, True


def _entscheide_kandidat(
    b: Buchung,
    treffer: list[KettenEmpfang],
    methode: str,
    s: Schwellen,
) -> tuple[Zuordnung | None, dict | None, bool]:
    best = treffer[0]
    n = len(treffer)
    zweit = _abstand_zweit(b, treffer)
    adresse_trifft = bool(b.adresse and best.adresse == b.adresse)
    if auto_erlaubt(n, zweit, adresse_trifft, s):
        grund = "eindeutig_adresse" if adresse_trifft else "eindeutig_betrag_zeit"
        _kalibrier_log(b, treffer, methode, "auto", s)
        return _zuordnung(b, best, methode, "bestaetigt", durch="auto", auto_grund=grund), None, False
    _kalibrier_log(b, treffer, methode, "vorschlag", s)
    return _zuordnung(b, best, methode, "vorschlag"), None, False


def _zuordnung(
    b: Buchung,
    e: KettenEmpfang,
    methode: str,
    status: str,
    *,
    durch: str | None = None,
    auto_grund: str | None = None,
) -> Zuordnung:
    return Zuordnung(
        konto=b.konto,
        auszahlung_ref=b.ref,
        txid=e.txid.lower(),
        vout=e.vout,
        sats_onchain=e.sats,
        methode=methode,
        status=status,
        bestaetigt_ts=None,
        bestaetigt_durch=durch if status == "bestaetigt" else None,
        auto_grund=auto_grund if status == "bestaetigt" else None,
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
            durch = "manuell" if status == "bestaetigt" else None
            aus.append(Zuordnung(
                konto=z.konto,
                auszahlung_ref=z.auszahlung_ref,
                txid=(txid or z.txid).lower(),
                vout=z.vout if vout is None else int(vout),
                sats_onchain=z.sats_onchain if sats_onchain is None else int(sats_onchain),
                methode=methode or z.methode,
                status=status,
                bestaetigt_ts=bestaetigt_ts if status == "bestaetigt" else None,
                bestaetigt_durch=durch,
                auto_grund=None,
            ))
            _entscheidung_log(z, status)
        else:
            aus.append(z)
    if not gefunden:
        if not txid or vout is None:
            raise ValueError("Zuordnung nicht gefunden.")
        neu = Zuordnung(
            konto=konto,
            auszahlung_ref=auszahlung_ref,
            txid=txid.lower(),
            vout=int(vout),
            sats_onchain=int(sats_onchain or 0),
            methode=methode or "manuell",
            status=status,
            bestaetigt_ts=bestaetigt_ts if status == "bestaetigt" else None,
            bestaetigt_durch="manuell" if status == "bestaetigt" else None,
            auto_grund=None,
        )
        aus.append(neu)
        _entscheidung_log(neu, status)
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
            wallet = str(utxo.get("wallet") or utxo.get("_wallet_fallback") or "").strip() or None
            treffer.append(KettenEmpfang(
                txid=tid,
                vout=vout,
                sats=sats,
                zeit_ts=zeit,
                adresse=str(utxo.get("address") or "") or None,
                wallet=wallet,
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


def aktualisiere_zuordnungen(slug: str, exchange_dir, utxo_cache_dir, schwellen: Schwellen | None = None) -> dict:
    """Rechnet Vorschläge neu und speichert sie, bestätigt/abgelehnt bleibt."""
    from pathlib import Path
    from core.boerse import speicher

    wurzel = Path(exchange_dir)
    buchungen = speicher.lies_buchungen(slug, wurzel)
    bestehend = speicher.lies_zuordnungen(slug, wurzel)
    lauf = schlage_vor(buchungen, sammeln_empfaenge(utxo_cache_dir), bestehend, schwellen=schwellen)
    gem = mergen(bestehend, lauf)
    speicher.schreibe_zuordnungen(slug, wurzel, gem)
    _erklaerung_cache.clear()
    from core.log_redaktion import schreibe
    schreibe(
        "zuordnung_gespeichert",
        slug=slug,
        n_zuordnungen=len(gem),
        n_luecken=len(lauf.luecken),
        n_quarantaene=len(lauf.quarantaene),
        n_kein_hop=len(lauf.kein_hop),
    )
    return {
        "slug": slug,
        "zuordnungen": [speicher.zuordnung_zu_dict(z) for z in gem],
        "luecken": list(lauf.luecken),
        "quarantaene": list(lauf.quarantaene),
        "kein_hop": list(lauf.kein_hop),
    }

def _kalibrier_log(
    b: Buchung,
    treffer: list[KettenEmpfang],
    methode: str,
    entscheidung: str,
    s: Schwellen,
) -> None:
    """Kalibrierung ohne Kennungen: nur Buckets, Zähler und ref-Hash."""
    from core.log_redaktion import ref_hash, schreibe

    best = treffer[0] if treffer else None
    abstand = zeit_abstand_s(b.zeit_ts, best.zeit_ts) if best else None
    soll = erwarteter_output_sats(b)
    delta = (
        betrag_delta_sats(soll, best.sats, int(b.gebuehr_sats or 0), inkl_gebuehr=s.gebuehr_als_toleranz)
        if best else None
    )
    rel = (delta / max(soll, 1)) if delta is not None else None
    zweit = _abstand_zweit(b, treffer)
    schreibe(
        "zuordnung_kandidat",
        ref=ref_hash(b.ref),
        methode=methode,
        zeit_min_bucket=bucket_minuten(abstand),
        delta_rel_bucket=bucket_rel(rel),
        n_kandidaten=len(treffer),
        abstand_zweit_min_bucket=bucket_minuten(zweit),
        entscheidung=entscheidung,
    )


def _entscheidung_log(z: Zuordnung, status: str) -> None:
    from core.log_redaktion import ref_hash, schreibe

    schreibe(
        "zuordnung_entscheidung",
        ref=ref_hash(z.auszahlung_ref),
        status=status,
        vorher=z.status,
        methode=z.methode,
        bisher_durch=z.bestaetigt_durch or "-",
    )


def txid_kurz(txid: str, vor: int = 8, hinten: int = 8) -> str:
    text = str(txid or "")
    if len(text) <= vor + hinten:
        return text
    return f"{text[:vor]}…{text[-hinten:]}"


def _datum_de(ts: int | None) -> str:
    if ts is None:
        return ""
    from datetime import datetime
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def gui_felder(
    z: Zuordnung,
    buchung: Buchung | None = None,
    empfang: KettenEmpfang | None = None,
    wallet: str | None = None,
) -> dict:
    """Felder nur für die lokale GUI/API, nicht fürs Log."""
    from core.boerse import speicher

    d = speicher.zuordnung_zu_dict(z)
    aus_ts = buchung.zeit_ts if buchung is not None else None
    emp_ts = empfang.zeit_ts if empfang is not None else None
    soll = erwarteter_output_sats(buchung) if buchung is not None else None
    d.update({
        "txid_kurz": txid_kurz(z.txid),
        "auszahlung_ts": aus_ts,
        "auszahlung_datum": _datum_de(aus_ts),
        "auszahlung_sats": soll,
        "gebuehr_sats": int(buchung.gebuehr_sats or 0) if buchung is not None else None,
        "empfang_sats": z.sats_onchain,
        "wallet": wallet or (empfang.wallet if empfang is not None else None),
        "zeitabstand_s": zeit_abstand_s(aus_ts, emp_ts),
        "betrag_delta_sats": (int(z.sats_onchain) - int(soll)) if soll is not None else None,
    })
    return d


def anreichern_liste(
    zuordnungen: list[Zuordnung] | tuple[Zuordnung, ...],
    buchungen: list[Buchung] | tuple[Buchung, ...] = (),
    empfange: list[KettenEmpfang] | tuple[KettenEmpfang, ...] = (),
    wallet_fn=None,
) -> list[dict]:
    nach_ref = {b.ref: b for b in buchungen}
    nach_op = {(e.txid.lower(), int(e.vout)): e for e in empfange}
    aus: list[dict] = []
    for z in zuordnungen:
        b = nach_ref.get(z.auszahlung_ref)
        e = nach_op.get((z.txid.lower(), int(z.vout)))
        wallet = e.wallet if e is not None else None
        if not wallet and wallet_fn is not None and e is not None and e.adresse:
            try:
                wallet = wallet_fn(e.adresse) or wallet
            except Exception:
                pass
        aus.append(gui_felder(z, b, e, wallet))
    return aus
