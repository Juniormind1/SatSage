"""Fassung 2: Buchungen und Entscheidungen unter <exchange_dir>/<slug>/."""
from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from pathlib import Path

from core.boerse.modell import Art, Buchung, ParseErgebnis, Quarantaene, Zuordnung

FASSUNG = 2
DATEI_BUCHUNGEN = "buchungen.jsonl"
DATEI_QUELLEN = "quellen.json"
DATEI_QUARANTAENE = "quarantaene.jsonl"
DATEI_ZUORDNUNGEN = "zuordnungen.json"
DATEI_LABELS = "labels.json"  # Adressen/TxIDs für die bestehende Beschriftung

_FAKTEN = (
    "konto", "ref", "gruppe", "zeit_ts", "zeit_zone_belegt", "art",
    "sats", "gebuehr_sats", "fiat", "fiat_gebuehr", "waehrung", "kurs",
    "txid", "adresse", "lightning", "roh_typ", "roh_subtyp",
)


class SpeicherFehler(ValueError):
    """Lesen oder Schreiben der Fassung 2 ist fehlgeschlagen."""


def _atomar(pfad: Path, text: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(f"{pfad.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, pfad)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _json(wert):
    if isinstance(wert, Decimal):
        return str(wert)
    if isinstance(wert, Art):
        return str(wert)
    return wert


def buchung_zu_dict(b: Buchung) -> dict:
    return {
        "konto": b.konto,
        "ref": b.ref,
        "gruppe": b.gruppe,
        "zeit_ts": b.zeit_ts,
        "zeit_zone_belegt": b.zeit_zone_belegt,
        "art": str(b.art),
        "sats": b.sats,
        "gebuehr_sats": b.gebuehr_sats,
        "fiat": None if b.fiat is None else str(b.fiat),
        "fiat_gebuehr": None if b.fiat_gebuehr is None else str(b.fiat_gebuehr),
        "waehrung": b.waehrung,
        "kurs": None if b.kurs is None else str(b.kurs),
        "txid": b.txid,
        "adresse": b.adresse,
        "lightning": b.lightning,
        "roh_typ": b.roh_typ,
        "roh_subtyp": b.roh_subtyp,
        "datei": b.datei,
        "zeile": b.zeile,
    }


def buchung_aus_dict(d: dict) -> Buchung:
    def dec(v):
        return None if v is None or v == "" else Decimal(str(v))

    return Buchung(
        konto=str(d["konto"]),
        ref=str(d["ref"]),
        gruppe=d.get("gruppe"),
        zeit_ts=d.get("zeit_ts"),
        zeit_zone_belegt=bool(d.get("zeit_zone_belegt")),
        art=Art(str(d["art"])),
        sats=int(d.get("sats") or 0),
        gebuehr_sats=int(d.get("gebuehr_sats") or 0),
        fiat=dec(d.get("fiat")),
        fiat_gebuehr=dec(d.get("fiat_gebuehr")),
        waehrung=d.get("waehrung"),
        kurs=dec(d.get("kurs")),
        txid=d.get("txid"),
        adresse=d.get("adresse"),
        lightning=bool(d.get("lightning")),
        roh_typ=str(d.get("roh_typ") or ""),
        roh_subtyp=d.get("roh_subtyp"),
        datei=str(d.get("datei") or ""),
        zeile=int(d.get("zeile") or 0),
    )


def fakten(b: Buchung) -> tuple:
    """Vergleichsinhalt ohne Datei-Hash und Zeilennummer (Re-Import)."""
    d = buchung_zu_dict(b)
    return tuple(d[k] for k in _FAKTEN)


def zuordnung_zu_dict(z: Zuordnung) -> dict:
    return {
        "konto": z.konto,
        "auszahlung_ref": z.auszahlung_ref,
        "txid": z.txid,
        "vout": z.vout,
        "sats_onchain": z.sats_onchain,
        "methode": z.methode,
        "status": z.status,
        "bestaetigt_ts": z.bestaetigt_ts,
    }


def zuordnung_aus_dict(d: dict) -> Zuordnung:
    return Zuordnung(
        konto=str(d["konto"]),
        auszahlung_ref=str(d["auszahlung_ref"]),
        txid=str(d["txid"]).lower(),
        vout=int(d["vout"]),
        sats_onchain=int(d["sats_onchain"]),
        methode=str(d["methode"]),
        status=str(d["status"]),
        bestaetigt_ts=d.get("bestaetigt_ts"),
    )


def ordner(slug: str, cache_dir: Path) -> Path:
    return Path(cache_dir) / slug


def ist_v2(slug: str, cache_dir: Path) -> bool:
    ziel = ordner(slug, cache_dir)
    return (ziel / DATEI_QUELLEN).is_file() or (ziel / DATEI_BUCHUNGEN).is_file()


def _jsonl_lesen(pfad: Path) -> list[dict]:
    if not pfad.is_file():
        return []
    zeilen = []
    for roh in pfad.read_text(encoding="utf-8").splitlines():
        if not roh.strip():
            continue
        try:
            obj = json.loads(roh)
        except ValueError:
            continue
        if isinstance(obj, dict):
            zeilen.append(obj)
    return zeilen


def _jsonl_schreiben(pfad: Path, objekte: list[dict]) -> None:
    text = "".join(json.dumps(o, ensure_ascii=False, sort_keys=True) + "\n" for o in objekte)
    _atomar(pfad, text)


def lies_buchungen(slug: str, cache_dir: Path) -> tuple[Buchung, ...]:
    return tuple(
        buchung_aus_dict(d)
        for d in _jsonl_lesen(ordner(slug, cache_dir) / DATEI_BUCHUNGEN)
        if "ref" in d and "konto" in d
    )


def lies_quarantaene(slug: str, cache_dir: Path) -> tuple[dict, ...]:
    return tuple(_jsonl_lesen(ordner(slug, cache_dir) / DATEI_QUARANTAENE))


def lies_quellen(slug: str, cache_dir: Path) -> dict:
    pfad = ordner(slug, cache_dir) / DATEI_QUELLEN
    if not pfad.is_file():
        return {}
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return daten if isinstance(daten, dict) else {}


def lies_zuordnungen(slug: str, cache_dir: Path) -> tuple[Zuordnung, ...]:
    pfad = ordner(slug, cache_dir) / DATEI_ZUORDNUNGEN
    if not pfad.is_file():
        return ()
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    roh = daten.get("zuordnungen") if isinstance(daten, dict) else daten
    if not isinstance(roh, list):
        return ()
    return tuple(zuordnung_aus_dict(d) for d in roh if isinstance(d, dict))


def schreibe_zuordnungen(slug: str, cache_dir: Path, zuordnungen: list[Zuordnung]) -> None:
    payload = {
        "fassung": FASSUNG,
        "zuordnungen": [zuordnung_zu_dict(z) for z in zuordnungen],
    }
    _atomar(
        ordner(slug, cache_dir) / DATEI_ZUORDNUNGEN,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
    )


def datei_schon_importiert(slug: str, cache_dir: Path, datei_hash: str) -> bool:
    if not datei_hash:
        return False
    for q in lies_quellen(slug, cache_dir).get("quellen") or []:
        if not isinstance(q, dict):
            continue
        if q.get("datei") == datei_hash or q.get("datei_trades") == datei_hash:
            return True
    return False


def _labels_aus_buchungen(buchungen: list[Buchung]) -> dict:
    addresses: dict[str, dict] = {}
    txids: dict[str, dict] = {}
    for b in buchungen:
        rolle = None
        if b.art is Art.BTC_EINGANG:
            rolle = "deposit"
        elif b.art is Art.BTC_AUSGANG:
            rolle = "withdrawal"
        if b.adresse:
            ein = addresses.setdefault(b.adresse, {"roles": [], "quelle": "v2"})
            if rolle and rolle not in ein["roles"]:
                ein["roles"].append(rolle)
        if b.txid and not b.lightning:
            tid = b.txid.lower()
            ein = txids.setdefault(tid, {"roles": [], "addresses": [], "quelle": "v2"})
            if rolle and rolle not in ein["roles"]:
                ein["roles"].append(rolle)
            if b.adresse and b.adresse not in ein["addresses"]:
                ein["addresses"].append(b.adresse)
    return {"addresses": addresses, "txids": txids}


def lies_labels(slug: str, cache_dir: Path) -> dict:
    pfad = ordner(slug, cache_dir) / DATEI_LABELS
    if pfad.is_file():
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
            if isinstance(daten, dict):
                return daten
        except (OSError, ValueError):
            pass
    return _labels_aus_buchungen(list(lies_buchungen(slug, cache_dir)))


def importiere_ergebnis(
    ergebnis: ParseErgebnis,
    *,
    name: str,
    slug: str,
    cache_dir: Path,
    ersetzen: bool = False,
    datei_trades: str | None = None,
) -> dict:
    """Hängt neue Buchungen an. Gleicher Inhalt ist idempotent, abweichender Inhalt ein Konflikt."""
    if not slug:
        raise SpeicherFehler("Slug fehlt.")
    if datei_schon_importiert(slug, cache_dir, ergebnis.datei_hash) and not ersetzen:
        bestehend = lies_buchungen(slug, cache_dir)
        labels = lies_labels(slug, cache_dir)
        return {
            "slug": slug,
            "name": name,
            "fassung": FASSUNG,
            "schon_importiert": True,
            "neu": 0,
            "doppelt": 0,
            "konflikte": 0,
            "buchungen": len(bestehend),
            "quarantaene": len(lies_quarantaene(slug, cache_dir)),
            "addresses": len(labels.get("addresses") or {}),
            "txids": len(labels.get("txids") or {}),
            "variante": ergebnis.variante,
        }

    ziel = ordner(slug, cache_dir)
    if ersetzen:
        for name_d in (DATEI_BUCHUNGEN, DATEI_QUARANTAENE, DATEI_QUELLEN, DATEI_LABELS):
            p = ziel / name_d
            if p.is_file():
                p.unlink()
        bestehend: list[Buchung] = []
        quarantaene: list[dict] = []
        quellen: dict = {"fassung": FASSUNG, "slug": slug, "name": name, "quellen": []}
    else:
        bestehend = list(lies_buchungen(slug, cache_dir))
        quarantaene = list(lies_quarantaene(slug, cache_dir))
        quellen = lies_quellen(slug, cache_dir) or {
            "fassung": FASSUNG, "slug": slug, "name": name, "quellen": [],
        }

    index = {(b.konto, b.ref): b for b in bestehend}
    neu = doppelt = konflikte = 0
    for b in ergebnis.buchungen:
        alt = index.get((b.konto, b.ref))
        if alt is None:
            bestehend.append(b)
            index[(b.konto, b.ref)] = b
            neu += 1
            continue
        if fakten(alt) == fakten(b):
            doppelt += 1
            continue
        konflikte += 1
        quarantaene.append({
            "zeile": b.zeile,
            "grund": "Konflikt gleicher Schlüssel",
            "roh_typ": b.roh_typ,
            "datei": b.datei,
            "ref": b.ref,
            "konto": b.konto,
            "bestand": {k: buchung_zu_dict(alt)[k] for k in _FAKTEN},
            "neu": {k: buchung_zu_dict(b)[k] for k in _FAKTEN},
        })

    for q in ergebnis.quarantaene:
        quarantaene.append({
            "zeile": q.zeile,
            "grund": q.grund,
            "roh_typ": q.roh_typ,
            "datei": q.datei,
            "ref": q.ref,
        })

    labels = _labels_aus_buchungen(bestehend)
    jetzt = int(time.time())
    eintrag = {
        "datei": ergebnis.datei_hash,
        "variante": ergebnis.variante,
        "zeilen": len(ergebnis.buchungen) + len(ergebnis.quarantaene),
        "buchungen": len(ergebnis.buchungen),
        "quarantaene": len(ergebnis.quarantaene),
        "importiert_ts": jetzt,
        "neu": neu,
        "doppelt": doppelt,
        "konflikte": konflikte,
    }
    if datei_trades:
        eintrag["datei_trades"] = datei_trades
    quellen["fassung"] = FASSUNG
    quellen["slug"] = slug
    quellen["name"] = name
    quellen.setdefault("quellen", []).append(eintrag)
    # Kein Dateiname in quellen.json.

    ziel.mkdir(parents=True, exist_ok=True)
    _jsonl_schreiben(ziel / DATEI_BUCHUNGEN, [buchung_zu_dict(b) for b in bestehend])
    _jsonl_schreiben(ziel / DATEI_QUARANTAENE, quarantaene)
    _atomar(ziel / DATEI_QUELLEN, json.dumps(quellen, ensure_ascii=False, indent=2, sort_keys=True))
    _atomar(ziel / DATEI_LABELS, json.dumps(labels, ensure_ascii=False, indent=2, sort_keys=True))

    return {
        "slug": slug,
        "name": name,
        "fassung": FASSUNG,
        "schon_importiert": False,
        "neu": neu,
        "doppelt": doppelt,
        "konflikte": konflikte,
        "buchungen": len(bestehend),
        "quarantaene": len(quarantaene),
        "addresses": len(labels.get("addresses") or {}),
        "txids": len(labels.get("txids") or {}),
        "variante": ergebnis.variante,
    }


def loesche_v2(slug: str, cache_dir: Path) -> bool:
    ziel = ordner(slug, cache_dir)
    if not ziel.is_dir():
        return False
    getroffen = False
    for p in ziel.iterdir():
        if p.is_file():
            p.unlink()
            getroffen = True
    try:
        ziel.rmdir()
        getroffen = True
    except OSError:
        pass
    return getroffen


def v2_slugs(cache_dir: Path) -> list[str]:
    wurzel = Path(cache_dir)
    if not wurzel.is_dir():
        return []
    slugs = []
    for p in sorted(wurzel.iterdir()):
        if p.is_dir() and not p.name.startswith("_") and ist_v2(p.name, wurzel):
            slugs.append(p.name)
    return slugs


def kurzinfo(slug: str, cache_dir: Path) -> dict:
    quellen = lies_quellen(slug, cache_dir)
    labels = lies_labels(slug, cache_dir)
    return {
        "slug": slug,
        "name": quellen.get("name") or slug,
        "fassung": FASSUNG,
        "buchungen": len(lies_buchungen(slug, cache_dir)),
        "quarantaene": len(lies_quarantaene(slug, cache_dir)),
        "zuordnungen": len(lies_zuordnungen(slug, cache_dir)),
        "addresses": len(labels.get("addresses") or {}),
        "txids": len(labels.get("txids") or {}),
        "updated_ts": max(
            (int(q.get("importiert_ts") or 0) for q in (quellen.get("quellen") or []) if isinstance(q, dict)),
            default=None,
        ),
    }
