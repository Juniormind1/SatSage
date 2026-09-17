"""
Börsen-Transaktionsreports (CSV) → lokale Adress-/TxID-Zuordnung.

SatSage bleibt minimalistisch: nur Bitcoin-TxIDs und -Adressen aus dem Report
werden behalten und bei Herkunft/Labels als Klarname der Börse genutzt.
Kurse, Fiat und Shitcoin-Zeilen werden verworfen.

Speicher: ``exchange_reports/<slug>.json`` (eine Datei je Börse) unter
``app_dir()`` bzw. dem vom Server gesetzten Verzeichnis.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from pathlib import Path

from core.paths import app_dir

VERSION = 1
META_NAME = "_index.json"

#: Verzeichnis-Override (Server setzt beim Start).
_aktives_verzeichnis: Path | None = None

_BTC_ASSETS = frozenset({
    "btc", "xbt", "bitcoin", "xxbt", "btc.s", "xbt.s", "btc-usd", "btc-eur",
})

_ADDRESS_HEADERS = frozenset({
    "address", "addr", "btc address", "bitcoin address", "wallet address",
    "deposit address", "withdrawal address", "to address", "from address",
    "crypto address", "destination", "destination address", "receiving address",
    "send address", "recipient", "recipient address", "wallet",
})

_TXID_HEADERS = frozenset({
    "txid", "tx id", "tx_id", "transaction id", "transaction hash", "txhash",
    "tx hash", "hash", "blockchain transaction id", "transaction",
    "blockchain hash", "chain transaction id", "refid", "reference",
})

_ASSET_HEADERS = frozenset({
    "asset", "currency", "coin", "symbol", "crypto", "currency code",
    "asset symbol", "base currency", "coin type", "ticker",
})

_TYPE_HEADERS = frozenset({
    "type", "transaction type", "tx type", "side", "direction", "operation",
    "activity", "event", "transfer type",
})

_DEPOSIT_TOKENS = frozenset({
    "deposit", "einzahlung", "receive", "received", "credit", "in", "incoming",
})
_WITHDRAW_TOKENS = frozenset({
    "withdraw", "withdrawal", "auszahlung", "send", "sent", "debit", "out",
    "outgoing", "payout",
})

# bc1… / 1… / 3… — grob, nur Formatfilter (kein Checksum-Zwang).
_RE_ADDR = re.compile(
    r"^(?:bc1[a-z0-9]{25,90}|tb1[a-z0-9]{25,90}|bcrt1[a-z0-9]{25,90}"
    r"|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$"
)
_RE_TXID = re.compile(r"^[0-9a-fA-F]{64}$")
_RE_SLUG = re.compile(r"[^a-z0-9]+")


class ExchangeReportError(ValueError):
    """Ungültiger Import oder fehlende Pflichtangabe."""


def setze_verzeichnis(pfad: Path | None) -> None:
    global _aktives_verzeichnis
    _aktives_verzeichnis = Path(pfad) if pfad else None


def verzeichnis(cache_dir: Path | str | None = None) -> Path:
    if cache_dir is not None:
        return Path(cache_dir)
    if _aktives_verzeichnis is not None:
        return _aktives_verzeichnis
    return app_dir() / "exchange_reports"


def slug_aus_name(name: str) -> str:
    roh = (name or "").strip().lower()
    slug = _RE_SLUG.sub("-", roh).strip("-")
    if not slug:
        raise ExchangeReportError("Börsenname fehlt oder ist ungültig.")
    return slug[:80]


def _norm_header(zell: str) -> str:
    t = (zell or "").strip().lower().replace("_", " ").replace("-", " ")
    t = re.sub(r"\s+", " ", t)
    return t


def _ist_btc_asset(wert: str) -> bool:
    v = (wert or "").strip().lower()
    if not v:
        return True  # keine Angabe → nicht verwerfen
    if v in _BTC_ASSETS:
        return True
    # Paare wie BTC/EUR, XBT-USD
    for sep in ("/", "-", "_", " "):
        if sep in v:
            teile = [p.strip() for p in v.split(sep) if p.strip()]
            if teile and teile[0] in _BTC_ASSETS:
                return True
    return False


def _rolle_aus_typ(wert: str) -> str | None:
    v = (wert or "").strip().lower()
    if not v:
        return None
    # Nur erstes Token / Wortgruppe
    for tok in _DEPOSIT_TOKENS:
        if tok in v:
            return "deposit"
    for tok in _WITHDRAW_TOKENS:
        if tok in v:
            return "withdrawal"
    return None


def _spalten_zuordnen(headers: list[str]) -> dict[str, list[int]]:
    """Welche Spalten-Indizes Adresse / TxID / Asset / Type sind."""
    zu: dict[str, list[int]] = {
        "address": [], "txid": [], "asset": [], "type": [],
    }
    for i, h in enumerate(headers):
        n = _norm_header(h)
        if not n:
            continue
        if n in _ADDRESS_HEADERS or n.endswith(" address") or n.startswith("address "):
            zu["address"].append(i)
        elif n in _TXID_HEADERS or n.endswith(" txid") or "transaction id" in n:
            zu["txid"].append(i)
        elif n in _ASSET_HEADERS:
            zu["asset"].append(i)
        elif n in _TYPE_HEADERS:
            zu["type"].append(i)
    return zu


def _zelle(row: list[str], idx: int) -> str:
    if idx < 0 or idx >= len(row):
        return ""
    return str(row[idx] or "").strip()


def _finde_adressen_in_zeile(row: list[str], spalten: list[int] | None) -> list[str]:
    treffer: list[str] = []
    gesehen: set[str] = set()
    indizes = spalten if spalten else range(len(row))
    for i in indizes:
        roh = _zelle(row, i)
        if not roh:
            continue
        # Mehrere Werte in einer Zelle (selten)
        teile = re.split(r"[\s,;|]+", roh) if len(roh) > 70 else [roh]
        for t in teile:
            t = t.strip()
            if not t or t in gesehen:
                continue
            if _RE_ADDR.match(t):
                gesehen.add(t)
                treffer.append(t)
    return treffer


def _finde_txids_in_zeile(row: list[str], spalten: list[int] | None) -> list[str]:
    treffer: list[str] = []
    gesehen: set[str] = set()
    indizes = spalten if spalten else range(len(row))
    for i in indizes:
        roh = _zelle(row, i)
        if not roh:
            continue
        teile = re.split(r"[\s,;|]+", roh)
        for t in teile:
            t = t.strip()
            if not t or t in gesehen:
                continue
            if _RE_TXID.match(t):
                tid = t.lower()
                gesehen.add(tid)
                treffer.append(tid)
    return treffer


def _zeile_hat_btc_ref(row: list[str]) -> bool:
    """True wenn in der Zeile eine BTC-Adresse (bc1/1/3…) oder TxID steckt."""
    return bool(_finde_adressen_in_zeile(row, None) or _finde_txids_in_zeile(row, None))


def _erste_zeile_ist_kopf(headers: list[str]) -> bool:
    """
    Bekannte Spaltennamen → Kopfzeile.
    Sieht die erste Zeile selbst wie Adresse/TxID aus → Datenzeile (Liste).
    """
    if _zeile_hat_btc_ref(headers):
        return False
    zu = _spalten_zuordnen(headers)
    return bool(zu["address"] or zu["txid"] or zu["asset"] or zu["type"])


def parse_csv_btc_refs(csv_text: str) -> dict:
    """
    Liest CSV **oder** einfache Adress-/TxID-Listen (eine je Zeile, ohne Kopf).

    Unterstützt bc1…, Legacy ``1…`` und P2SH ``3…``. Shitcoin-/Kurszeilen
    werden verworfen, sobald Asset-Spalten erkennbar sind.

    Rückgabe::
        {
          "rows_total": int,
          "rows_btc": int,
          "addresses": {addr: {"roles": [...]}},
          "txids": {txid: {"roles": [...], "addresses": [...]}},
        }
    """
    if not isinstance(csv_text, str):
        raise ExchangeReportError("CSV muss Text sein.")
    if len(csv_text) > 40 * 1024 * 1024:
        raise ExchangeReportError("CSV zu groß (max. 40 MB).")
    if not csv_text.strip():
        raise ExchangeReportError("CSV ist leer.")

    # BOM / Latin-1-Fallback über decode-Pfad: Aufrufer liefert str.
    text = csv_text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
        if text.count(";") > text.count(","):
            dialect.delimiter = ";"

    reader = csv.reader(io.StringIO(text), dialect)
    try:
        erste = next(reader)
    except StopIteration:
        raise ExchangeReportError("Datei ist leer.") from None

    erste = [str(h or "") for h in erste]
    mit_kopf = _erste_zeile_ist_kopf(erste)
    if mit_kopf:
        zu = _spalten_zuordnen(erste)
        hat_adress_spalte = bool(zu["address"])
        hat_txid_spalte = bool(zu["txid"])
        hat_asset_spalte = bool(zu["asset"])
        hat_typ_spalte = bool(zu["type"])
        daten_zeilen: list[list[str]] = list(reader)
    else:
        # Reine Liste / Report ohne erkannte Header — erste Zeile mitnehmen.
        zu = {"address": [], "txid": [], "asset": [], "type": []}
        hat_adress_spalte = False
        hat_txid_spalte = False
        hat_asset_spalte = False
        hat_typ_spalte = False
        daten_zeilen = [erste, *reader]

    addresses: dict[str, dict] = {}
    txids: dict[str, dict] = {}
    rows_total = 0
    rows_btc = 0

    for row in daten_zeilen:
        if not row or all(not str(c or "").strip() for c in row):
            continue
        rows_total += 1
        # Asset-Filter
        if hat_asset_spalte:
            assets = [_zelle(row, i) for i in zu["asset"]]
            if assets and not any(_ist_btc_asset(a) for a in assets):
                continue
        rows_btc += 1

        rolle = None
        if hat_typ_spalte:
            for i in zu["type"]:
                rolle = _rolle_aus_typ(_zelle(row, i))
                if rolle:
                    break

        if hat_adress_spalte or hat_txid_spalte:
            addrs = _finde_adressen_in_zeile(
                row, zu["address"] if hat_adress_spalte else None,
            )
            tids = _finde_txids_in_zeile(
                row, zu["txid"] if hat_txid_spalte else None,
            )
            # Spalten erkannt, aber Zelle leer → Rest der Zeile nicht
            # mit Shitcoin-Müll vollscannen; nur wenn gar nichts kam.
            if not addrs and not tids:
                addrs = _finde_adressen_in_zeile(row, None)
                tids = _finde_txids_in_zeile(row, None)
        else:
            addrs = _finde_adressen_in_zeile(row, None)
            tids = _finde_txids_in_zeile(row, None)

        if not addrs and not tids:
            continue

        for a in addrs:
            ein = addresses.setdefault(a, {"roles": []})
            if rolle and rolle not in ein["roles"]:
                ein["roles"].append(rolle)

        for tid in tids:
            ein = txids.setdefault(tid, {"roles": [], "addresses": []})
            if rolle and rolle not in ein["roles"]:
                ein["roles"].append(rolle)
            for a in addrs:
                if a not in ein["addresses"]:
                    ein["addresses"].append(a)

    if not addresses and not txids:
        raise ExchangeReportError(
            "Keine Bitcoin-Adressen oder TxIDs gefunden "
            "(bc1…/1…/3… bzw. 64-Hex; Shitcoin-/Kurszeilen werden verworfen)."
        )

    return {
        "rows_total": rows_total,
        "rows_btc": rows_btc,
        "addresses": addresses,
        "txids": txids,
    }


def _pfad(slug: str, cache_dir: Path | None = None) -> Path:
    return verzeichnis(cache_dir) / f"{slug}.json"


def _index_pfad(cache_dir: Path | None = None) -> Path:
    return verzeichnis(cache_dir) / META_NAME


def _lies(slug: str, cache_dir: Path | None = None) -> dict | None:
    ziel = _pfad(slug, cache_dir)
    if not ziel.is_file():
        return None
    try:
        daten = json.loads(ziel.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(daten, dict) or int(daten.get("version") or 0) != VERSION:
        return None
    return daten


def _schreibe(daten: dict, cache_dir: Path | None = None) -> Path:
    slug = str(daten.get("slug") or "")
    if not slug:
        raise ExchangeReportError("Intern: slug fehlt.")
    ordner = verzeichnis(cache_dir)
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = _pfad(slug, cache_dir)
    tmp = ziel.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(ziel)
    _index_aktualisieren(cache_dir)
    return ziel


def _index_aktualisieren(cache_dir: Path | None = None) -> None:
    ordner = verzeichnis(cache_dir)
    eintraege = []
    if ordner.is_dir():
        for p in sorted(ordner.glob("*.json")):
            if p.name.startswith("_"):
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(d, dict) or int(d.get("version") or 0) != VERSION:
                continue
            eintraege.append({
                "slug": d.get("slug") or p.stem,
                "name": d.get("name") or p.stem,
                "addresses": len(d.get("addresses") or {}),
                "txids": len(d.get("txids") or {}),
                "updated_ts": d.get("updated_ts"),
            })
    pfad = _index_pfad(cache_dir)
    try:
        pfad.write_text(
            json.dumps({"version": VERSION, "exchanges": eintraege},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _merge_maps(ziel: dict, quell: dict, *, addr_link: bool = False) -> None:
    for key, roh in (quell or {}).items():
        if not isinstance(roh, dict):
            continue
        ein = ziel.setdefault(key, {"roles": []})
        if "addresses" in roh or addr_link:
            ein.setdefault("addresses", [])
        for r in roh.get("roles") or []:
            if r not in ein["roles"]:
                ein["roles"].append(r)
        for a in roh.get("addresses") or []:
            if a not in ein.setdefault("addresses", []):
                ein["addresses"].append(a)


def importiere_csv(
    csv_text: str,
    *,
    name: str,
    filename: str = "",
    cache_dir: Path | None = None,
    ersetzen: bool = False,
) -> dict:
    """
    CSV einlesen und in ``<slug>.json`` mergen (oder ersetzen).

    *name*: Anzeigename der Börse (Kraken, Binance, …).
    """
    anzeige = (name or "").strip()
    if not anzeige:
        raise ExchangeReportError("Bitte einen Börsennamen angeben.")
    slug = slug_aus_name(anzeige)
    parsed = parse_csv_btc_refs(csv_text)
    jetzt = int(time.time())

    if ersetzen:
        daten = {
            "version": VERSION,
            "slug": slug,
            "name": anzeige,
            "created_ts": jetzt,
            "updated_ts": jetzt,
            "sources": [],
            "addresses": {},
            "txids": {},
        }
    else:
        daten = _lies(slug, cache_dir) or {
            "version": VERSION,
            "slug": slug,
            "name": anzeige,
            "created_ts": jetzt,
            "updated_ts": jetzt,
            "sources": [],
            "addresses": {},
            "txids": {},
        }
        # Name aktualisieren (Schreibweise vom Nutzer)
        daten["name"] = anzeige
        daten["slug"] = slug

    _merge_maps(daten.setdefault("addresses", {}), parsed["addresses"])
    _merge_maps(daten.setdefault("txids", {}), parsed["txids"], addr_link=True)

    sources = list(daten.get("sources") or [])
    sources.append({
        "filename": (filename or "")[:200],
        "imported_ts": jetzt,
        "rows_total": parsed["rows_total"],
        "rows_btc": parsed["rows_btc"],
        "addresses_new": len(parsed["addresses"]),
        "txids_new": len(parsed["txids"]),
    })
    daten["sources"] = sources[-50:]  # Historie begrenzen
    daten["updated_ts"] = jetzt

    _schreibe(daten, cache_dir)
    return {
        "slug": slug,
        "name": anzeige,
        "addresses": len(daten.get("addresses") or {}),
        "txids": len(daten.get("txids") or {}),
        "imported_addresses": len(parsed["addresses"]),
        "imported_txids": len(parsed["txids"]),
        "rows_total": parsed["rows_total"],
        "rows_btc": parsed["rows_btc"],
        "filename": (filename or "")[:200],
    }


def liste(cache_dir: Path | None = None) -> list[dict]:
    """Kurzliste aller importierten Börsen."""
    _index_aktualisieren(cache_dir)
    pfad = _index_pfad(cache_dir)
    if not pfad.is_file():
        return []
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(daten.get("exchanges") or [])


def status(cache_dir: Path | None = None) -> dict:
    ein = liste(cache_dir)
    return {
        "exchanges": ein,
        "count": len(ein),
        "addresses": sum(int(e.get("addresses") or 0) for e in ein),
        "txids": sum(int(e.get("txids") or 0) for e in ein),
    }


def loesche(slug: str, cache_dir: Path | None = None) -> bool:
    s = slug_aus_name(slug)
    ziel = _pfad(s, cache_dir)
    if not ziel.is_file():
        return False
    try:
        ziel.unlink()
    except OSError:
        return False
    _index_aktualisieren(cache_dir)
    return True


def _rolle_label(roles: list) -> str:
    rs = [str(r) for r in (roles or [])]
    if "deposit" in rs and "withdrawal" in rs:
        return "Ein-/Auszahlung"
    if "deposit" in rs:
        return "Einzahlung"
    if "withdrawal" in rs:
        return "Auszahlung"
    return ""


def _label_dict(name: str, roles: list | None = None) -> dict:
    rolle = _rolle_label(roles or [])
    kat = "exchange"
    return {
        "name": name,
        "benannt": True,
        "art": "dienst",
        "kategorie": kat,
        "kategorie_label": "Börse",
        "land": "",
        "status": "",
        "ofac": False,
        "quelle": "Börsen-CSV",
        "stand": "",
        "hinweis": (
            "Zuordnung aus importiertem Börsen-Report (nur Adressen/TxIDs). "
            "Kein vollständiger Handelsnachweis."
        ),
        "rolle": rolle,
        "nutzer_import": True,
    }


# In-Memory-Index: Adresse/TxID → (name, roles)
_lookup_cache: dict[str, tuple[dict[str, tuple[str, list]], dict[str, tuple[str, list]]]] = {}


def _baue_lookup(cache_dir: Path | None = None) -> tuple[
    dict[str, tuple[str, list]], dict[str, tuple[str, list]]
]:
    ordner = verzeichnis(cache_dir)
    key = str(ordner.resolve()) if ordner.exists() else str(ordner)
    # mtime-Summe als Invalidierung
    mtime_sig = "0"
    if ordner.is_dir():
        try:
            mtime_sig = str(sum(int(p.stat().st_mtime) for p in ordner.glob("*.json")))
        except OSError:
            mtime_sig = "0"
    cache_key = f"{key}:{mtime_sig}"
    if cache_key in _lookup_cache:
        return _lookup_cache[cache_key]

    by_addr: dict[str, tuple[str, list]] = {}
    by_txid: dict[str, tuple[str, list]] = {}
    if ordner.is_dir():
        for p in ordner.glob("*.json"):
            if p.name.startswith("_"):
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(d, dict) or int(d.get("version") or 0) != VERSION:
                continue
            name = str(d.get("name") or p.stem)
            for addr, meta in (d.get("addresses") or {}).items():
                if not addr:
                    continue
                roles = list((meta or {}).get("roles") or [])
                by_addr[str(addr)] = (name, roles)
            for tid, meta in (d.get("txids") or {}).items():
                if not tid:
                    continue
                roles = list((meta or {}).get("roles") or [])
                by_txid[str(tid).lower()] = (name, roles)

    # Nur den aktuellen Eintrag behalten
    _lookup_cache.clear()
    _lookup_cache[cache_key] = (by_addr, by_txid)
    return by_addr, by_txid


def beschrifte_adresse(
    adresse: str, cache_dir: Path | None = None,
) -> dict | None:
    """Label aus Nutzer-Börsen-CSV, oder None."""
    a = (adresse or "").strip()
    if not a:
        return None
    by_addr, _ = _baue_lookup(cache_dir)
    treffer = by_addr.get(a)
    if not treffer:
        return None
    name, roles = treffer
    return _label_dict(name, roles)


def beschrifte_txid(
    txid: str, cache_dir: Path | None = None,
) -> dict | None:
    """Label über TxID aus Nutzer-Börsen-CSV, oder None."""
    t = (txid or "").strip().lower()
    if not t or not _RE_TXID.match(t):
        return None
    _, by_txid = _baue_lookup(cache_dir)
    treffer = by_txid.get(t)
    if not treffer:
        return None
    name, roles = treffer
    return _label_dict(name, roles)


def beschrifte(
    *,
    adresse: str = "",
    txid: str = "",
    cache_dir: Path | None = None,
) -> dict | None:
    """Adresse zuerst, sonst TxID."""
    hit = beschrifte_adresse(adresse, cache_dir)
    if hit:
        return hit
    return beschrifte_txid(txid, cache_dir)


def grenze(
    *,
    adressen: list[str] | tuple[str, ...] | None = None,
    txid: str = "",
    cache_dir: Path | None = None,
) -> dict | None:
    """
    Börsen-Grenze für den Herkunfts-Walk.

    Treffer auf importierte Adresse oder TxID → Trace endet hier
    (keine Hops hinter die Ein-/Auszahlung).
    """
    for a in adressen or ():
        hit = beschrifte_adresse(str(a or ""), cache_dir)
        if hit is not None:
            return hit
    return beschrifte_txid(txid, cache_dir)


def ist_boerse_adresse(adresse: str, cache_dir: Path | None = None) -> bool:
    return beschrifte_adresse(adresse, cache_dir) is not None


def ist_boerse_txid(txid: str, cache_dir: Path | None = None) -> bool:
    return beschrifte_txid(txid, cache_dir) is not None
