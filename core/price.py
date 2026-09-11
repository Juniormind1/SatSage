"""
BTC/Fiat-Kurse für Anzeige und Steuer-Tageskurse.

Lokale Historie zuerst: gebündelte ``data/btc_price/{EUR,USD}.csv`` und
Import unter ``immutable_cache/btc_price/``. Erst fehlende Tage holt die
Mempool Price-API (Spot zusätzlich Coinbase-Fallback).

Öffentliches ``mempool.space`` für Netzabrufe — ohne Wallet-Adressen/TxIDs.
Eine konfigurierte ``MEMPOOL_URL`` wird zuerst versucht.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import ssl
from outbound_policy import ensure_url_allowed
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from core.paths import resource_dir

_USER_AGENT = "SatSage/1.0"

#: Öffentliche Mempool-API nur für Kurse (kein Explorer-Klick, keine Adressen).
MEMPOOL_PRICE_DEFAULT = "https://mempool.space"

COINBASE_SPOT_URL = "https://api.coinbase.com/v2/prices/{pair}/spot"

#: Spot erneut holen, wenn älter als das.
SPOT_TTL_SEKUNDEN = 10 * 60

#: Spot und Mempool-Tageskurs.
_WÄHRUNGEN = frozenset({"EUR", "USD", "GBP", "CAD", "CHF", "AUD", "JPY"})

#: Flatfile-Historie und CSV-Import.
HISTORIE_WAEHRUNGEN = frozenset({"EUR", "USD"})

SATS_PRO_BTC = 100_000_000

_DATE_SPALTEN = frozenset({
    "date", "datum", "day", "time", "timestamp", "observation_date",
    "px_date", "valuedate", "value_date",
})
_PRICE_SPALTEN = frozenset({
    "price", "preis", "close", "schluss", "last", "value", "kurs",
    "px_last", "px last", "btc-eur", "btc-usd", "btceur", "btcusd",
    "btc/eur", "btc/usd", "rate", "mid",
})

#: (mtime, serie) je CSV-Pfad — Steuerjahr liest denselben Tag oft.
_csv_mtime_cache: dict[str, tuple[float, dict[str, float]]] = {}


@dataclass(frozen=True)
class BtcPreis:
    """Ein BTC-Kurs in Fiat."""

    amount: float
    currency: str
    time: int
    source: str
    kind: str  # "spot" | "day"
    day: str | None = None
    #: Kurzer Hinweis fürs Log, wenn Spot aus Historie kommt.
    warning: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d.get("warning"):
            d.pop("warning", None)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> BtcPreis:
        return cls(
            amount=float(data["amount"]),
            currency=str(data["currency"]).upper(),
            time=int(data["time"]),
            source=str(data["source"]),
            kind=str(data["kind"]),
            day=data.get("day"),
            warning=data.get("warning"),
        )


class PriceError(Exception):
    """Kurs konnte nicht ermittelt werden."""


def normalisiere_waehrung(roh: str) -> str:
    code = (roh or "EUR").strip().upper()
    if code not in _WÄHRUNGEN:
        raise ValueError(
            f"Währung „{roh}“ wird nicht unterstützt "
            f"(erlaubt: {', '.join(sorted(_WÄHRUNGEN))})."
        )
    return code


def normalisiere_historie_waehrung(roh: str) -> str:
    code = (roh or "EUR").strip().upper()
    if code not in HISTORIE_WAEHRUNGEN:
        raise ValueError(
            f"Historie nur für {', '.join(sorted(HISTORIE_WAEHRUNGEN))} "
            f"(nicht „{roh}“)."
        )
    return code


def mempool_price_base(mempool_url: str | None = None) -> str:
    """
    Basis-URL für Kursabfragen.

    Konfigurierte Explorer-URL hat Vorrang; sonst öffentliches mempool.space.
    """
    text = (mempool_url or "").strip().rstrip("/")
    return text or MEMPOOL_PRICE_DEFAULT


def preis_cache_dir(immutable_cache_dir: Path | str) -> Path:
    root = Path(immutable_cache_dir) / "btc_price"
    root.mkdir(parents=True, exist_ok=True)
    return root


def bundel_historie_dir() -> Path:
    """Mitgelieferte Flatfiles unter ``data/btc_price/`` (auch im PyInstaller-Build)."""
    return resource_dir() / "data" / "btc_price"


def historie_csv_pfad(immutable_cache_dir: Path | str, currency: str) -> Path:
    w = normalisiere_historie_waehrung(currency)
    return preis_cache_dir(immutable_cache_dir) / f"{w}.csv"


def sats_in_fiat(sats: int, eur_pro_btc: float) -> float:
    """Sats → Fiat-Betrag bei gegebenem BTC-Kurs."""
    return (int(sats) / SATS_PRO_BTC) * float(eur_pro_btc)


def fiat_in_sats(betrag: float, eur_pro_btc: float) -> int:
    """Fiat → Sats (abgerundet)."""
    if eur_pro_btc <= 0:
        raise ValueError("Kurs muss positiv sein.")
    return int((float(betrag) / float(eur_pro_btc)) * SATS_PRO_BTC)


def tag_aus_unix(ts: int) -> date:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()


def unix_tagesbeginn(tag: date) -> int:
    """UTC-Mitternacht des Kalendertags."""
    return int(datetime(tag.year, tag.month, tag.day, tzinfo=timezone.utc).timestamp())


def parse_tag(wert: date | datetime | int | str) -> date:
    """date / datetime / Unix-Zeit / ISO-Tag → Kalendertag (UTC bei Zeitangaben)."""
    if isinstance(wert, date) and not isinstance(wert, datetime):
        return wert
    if isinstance(wert, datetime):
        if wert.tzinfo is None:
            wert = wert.replace(tzinfo=timezone.utc)
        return wert.astimezone(timezone.utc).date()
    if isinstance(wert, (int, float)):
        return tag_aus_unix(int(wert))
    text = str(wert).strip()
    if text.isdigit():
        return tag_aus_unix(int(text))
    return date.fromisoformat(text[:10])


# ---------------------------------------------------------------------------
# CSV-Historie
# ---------------------------------------------------------------------------

def _parse_zahl(roh: str) -> float:
    text = (roh or "").strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        raise ValueError("leer")
    # 69.013,45 (DE) vs 69013.45
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    return float(text)


def _parse_datumsfeld(roh: str) -> date | None:
    text = (roh or "").strip().strip('"').strip("'")
    if not text:
        return None
    if text.isdigit() and len(text) >= 9:
        try:
            return tag_aus_unix(int(text))
        except (ValueError, OSError, OverflowError):
            return None
    # ISO oder „2026-08-27 00:00:00“
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    # DE: 27.08.2026 oder 27.08.26
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$", text)
    if m:
        tag_n, monat, jahr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if jahr < 100:
            jahr += 2000
        try:
            return date(jahr, monat, tag_n)
        except ValueError:
            return None
    # US: 08/27/2026
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    if m:
        a, b, jahr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Bloomberg/Excel US: Monat/Tag; wenn a>12 → Tag/Monat
        try:
            if a > 12:
                return date(jahr, b, a)
            return date(jahr, a, b)
        except ValueError:
            return None
    return None


def _delimiter_raten(kopfzeile: str) -> str:
    for trenn in (";", "\t", ","):
        if trenn in kopfzeile:
            return trenn
    return ","


def parse_kurs_csv(text: str) -> dict[str, float]:
    """
    CSV mit Datum und Preis → ``{ISO-Tag: Kurs}``.

    Erste nicht-kommentierte Zeile = Kopf. Spalten per Alias (date/Datum,
    price/Preis/close/PX_LAST, …). Trennzeichen: Komma, Semikolon oder Tab.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    zeilen = []
    for roh in text.splitlines():
        s = roh.strip()
        if not s or s.startswith("#"):
            continue
        # CryptoDataDownload: erste Zeile oft die Portal-URL ohne „#“.
        if s.lower().startswith("http://") or s.lower().startswith("https://"):
            continue
        zeilen.append(roh)
    if not zeilen:
        raise PriceError("CSV enthält keine Datenzeilen")

    delim = _delimiter_raten(zeilen[0])
    reader = csv.reader(io.StringIO("\n".join(zeilen)), delimiter=delim)
    zeilen_list = list(reader)
    if not zeilen_list:
        raise PriceError("CSV leer")

    kopf = [ (c or "").strip().lower() for c in zeilen_list[0] ]
    # Ohne erkennbaren Kopf: zwei Spalten annehmen
    hat_kopf = any(h in _DATE_SPALTEN or h in _PRICE_SPALTEN for h in kopf)
    if hat_kopf:
        date_i = next((i for i, h in enumerate(kopf) if h in _DATE_SPALTEN), None)
        price_i = next((i for i, h in enumerate(kopf) if h in _PRICE_SPALTEN), None)
        if date_i is None or price_i is None:
            # zweite Chance: Spalte heißt z. B. „BTC EUR Close“
            if price_i is None:
                for i, h in enumerate(kopf):
                    if "close" in h or "preis" in h or "price" in h or "last" in h:
                        price_i = i
                        break
            if date_i is None:
                for i, h in enumerate(kopf):
                    if "date" in h or "datum" in h or "time" in h:
                        date_i = i
                        break
        if date_i is None or price_i is None:
            raise PriceError(
                "CSV-Kopf braucht eine Datums- und eine Preisspalte "
                f"(gefunden: {', '.join(zeilen_list[0])})."
            )
        daten_zeilen = zeilen_list[1:]
    else:
        if len(kopf) < 2:
            raise PriceError("CSV braucht mindestens zwei Spalten (Datum, Preis)")
        date_i, price_i = 0, 1
        daten_zeilen = zeilen_list

    serie: dict[str, float] = {}
    for z in daten_zeilen:
        if len(z) <= max(date_i, price_i):
            continue
        tag = _parse_datumsfeld(z[date_i])
        if tag is None:
            continue
        try:
            amount = _parse_zahl(z[price_i])
        except ValueError:
            continue
        if amount <= 0:
            continue
        serie[tag.isoformat()] = amount
    if not serie:
        raise PriceError("In der CSV wurden keine gültigen Kurszeilen gefunden")
    return serie


def schreibe_kurs_csv(
    path: Path,
    serie: dict[str, float],
    *,
    currency: str,
    quelle: str = "import",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(serie.items())
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        f.write(f"# BTC/{currency} Tageskurs\n")
        f.write(f"# Quelle: {quelle}\n")
        if ordered:
            f.write(f"# Zeitraum: {ordered[0][0]} … {ordered[-1][0]}\n")
        f.write("# Format: date,price\n")
        w = csv.writer(f)
        w.writerow(["date", "price"])
        for day, price in ordered:
            text = f"{price:.8f}".rstrip("0").rstrip(".")
            w.writerow([day, text])
    tmp.replace(path)
    _csv_mtime_cache.pop(str(path.resolve()), None)


def _serie_aus_pfad(path: Path) -> dict[str, float]:
    key = str(path.resolve())
    mtime = path.stat().st_mtime
    hit = _csv_mtime_cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    serie = parse_kurs_csv(path.read_text(encoding="utf-8"))
    _csv_mtime_cache[key] = (mtime, serie)
    return serie


def historie_lesepfad(
    immutable_cache_dir: Path | str | None,
    currency: str,
) -> tuple[Path | None, str]:
    """
    Lesepfad für die Tages-Serie: Cache-Import vor Bundle.

    Kein stilles Kopieren — Bundle bleibt unverändert im Repo/Build.
    """
    w = normalisiere_historie_waehrung(currency)
    if immutable_cache_dir is not None:
        cache = historie_csv_pfad(immutable_cache_dir, w)
        if cache.is_file():
            return cache, "cache"
    bundel = bundel_historie_dir() / f"{w}.csv"
    if bundel.is_file():
        return bundel, "bundle"
    return None, "keine"


def lade_tageskurs_csv(
    immutable_cache_dir: Path | str | None,
    tag: date | datetime | int | str,
    currency: str = "EUR",
) -> BtcPreis | None:
    """Tageskurs aus lokaler CSV (Import-Cache oder Bundle)."""
    if currency.upper() not in HISTORIE_WAEHRUNGEN:
        return None
    w = normalisiere_historie_waehrung(currency)
    kalender = parse_tag(tag)
    path, source = historie_lesepfad(immutable_cache_dir, w)
    if path is None:
        return None
    try:
        serie = _serie_aus_pfad(path)
    except (PriceError, OSError):
        return None
    amount = serie.get(kalender.isoformat())
    if amount is None:
        return None
    return BtcPreis(
        amount=float(amount),
        currency=w,
        time=unix_tagesbeginn(kalender),
        source=source,
        kind="day",
        day=kalender.isoformat(),
    )


def historie_status(
    immutable_cache_dir: Path | str | None,
    currency: str = "EUR",
    *,
    mit_serie: bool = False,
) -> dict:
    """Kurzinfo für die Oberfläche (Tage, Zeitraum, Herkunft).

    Mit ``mit_serie=True`` zusätzlich ``series``: ``{ISO-Tag: Preis}`` für
    Client-Lookups (ausgegeben am Datum → EUR), ohne Mempool-Nachzug.
    """
    try:
        w = normalisiere_historie_waehrung(currency)
    except ValueError as e:
        return {"currency": currency, "ok": False, "error": str(e)}
    path, herkunft = historie_lesepfad(immutable_cache_dir, w)
    if path is None or not path.is_file():
        return {
            "currency": w,
            "ok": False,
            "days": 0,
            "from": None,
            "to": None,
            "source": "keine",
            "path": "",
        }
    try:
        serie = _serie_aus_pfad(path)
    except (PriceError, OSError) as e:
        return {
            "currency": w,
            "ok": False,
            "days": 0,
            "error": str(e),
            "source": herkunft,
            "path": str(path),
        }
    tage = sorted(serie)
    stand = {
        "currency": w,
        "ok": True,
        "days": len(tage),
        "from": tage[0] if tage else None,
        "to": tage[-1] if tage else None,
        "source": herkunft,
        "path": str(path),
    }
    if mit_serie:
        stand["series"] = {tag: float(serie[tag]) for tag in tage}
    return stand


def importiere_kurs_csv(
    immutable_cache_dir: Path | str,
    currency: str,
    csv_text: str,
    *,
    dateiname: str = "",
    ersetzen: bool = False,
) -> dict:
    """
    CSV parsen und in den Kurs-Cache schreiben (Merge oder Ersetzen).

    Ohne *ersetzen*: bestehende Cache-Serie (sonst Bundle) als Basis, Import
    überschreibt gleiche Tage. Ergebnis liegt unter
    ``immutable_cache/btc_price/{EUR|USD}.csv``.
    """
    w = normalisiere_historie_waehrung(currency)
    neu = parse_kurs_csv(csv_text)
    ziel = historie_csv_pfad(immutable_cache_dir, w)
    if ersetzen:
        serie: dict[str, float] = {}
    else:
        basis, _herkunft = historie_lesepfad(immutable_cache_dir, w)
        if basis is not None and basis.is_file():
            try:
                serie = dict(_serie_aus_pfad(basis))
            except (PriceError, OSError):
                serie = {}
        else:
            serie = {}
    serie.update(neu)
    quelle = f"import{(' ' + dateiname) if dateiname else ''}".strip()
    schreibe_kurs_csv(ziel, serie, currency=w, quelle=quelle)
    if csv_text:
        roh = preis_cache_dir(immutable_cache_dir) / f"import_{w}_raw.csv"
        try:
            roh.write_text(
                csv_text if csv_text.endswith("\n") else csv_text + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    tage = sorted(serie)
    return {
        "currency": w,
        "ok": True,
        "imported": len(neu),
        "days": len(serie),
        "from": tage[0] if tage else None,
        "to": tage[-1] if tage else None,
        "path": str(ziel),
        "filename": dateiname or "",
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

FetchFn = Callable[[str, float], dict]

def _ssl_context() -> ssl.SSLContext:
    """SSL-Kontext mit brauchbarem CA-Bündel (siehe core.tls)."""
    from core.tls import ssl_context

    return ssl_context()


def _fetch_json(url: str, timeout: float = 15.0) -> dict:
    try:
        ensure_url_allowed(url, service="mempool")
    except Exception as exc:
        raise PriceError(str(exc)) from exc
    anfrage = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(
            anfrage, timeout=timeout, context=_ssl_context(),
        ) as ant:
            roh = ant.read()
    except urllib.error.HTTPError as e:
        raise PriceError(f"HTTP {e.code} bei Kursabruf ({url})") from e
    except urllib.error.URLError as e:
        raise PriceError(f"Netzfehler bei Kursabruf: {e.reason}") from e
    except TimeoutError as e:
        raise PriceError("Zeitüberschreitung bei Kursabruf") from e
    try:
        data = json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PriceError("Ungültige JSON-Antwort beim Kursabruf") from e
    if not isinstance(data, dict):
        raise PriceError("Unerwartetes Kurs-Antwortformat")
    return data


# ---------------------------------------------------------------------------
# Netz-Quellen
# ---------------------------------------------------------------------------

def hole_spot_mempool(
    currency: str = "EUR",
    *,
    base_url: str | None = None,
    timeout: float = 15.0,
    fetch: FetchFn | None = None,
) -> BtcPreis:
    """Aktueller Kurs über Mempool ``/api/v1/prices``."""
    w = normalisiere_waehrung(currency)
    basis = mempool_price_base(base_url)
    url = f"{basis}/api/v1/prices"
    data = (fetch or _fetch_json)(url, timeout)
    if w not in data:
        raise PriceError(f"Mempool-Antwort ohne {w}")
    try:
        amount = float(data[w])
        ts = int(data.get("time") or time.time())
    except (TypeError, ValueError) as e:
        raise PriceError("Mempool-Spotkurs nicht lesbar") from e
    if amount <= 0:
        raise PriceError("Mempool lieferte keinen positiven Kurs")
    return BtcPreis(
        amount=amount,
        currency=w,
        time=ts,
        source="mempool",
        kind="spot",
        day=tag_aus_unix(ts).isoformat(),
    )


def hole_spot_coinbase(
    currency: str = "EUR",
    *,
    timeout: float = 15.0,
    fetch: FetchFn | None = None,
) -> BtcPreis:
    """Fallback: Coinbase Public Spot ``BTC-{currency}``."""
    w = normalisiere_waehrung(currency)
    if w == "JPY":
        raise PriceError("Coinbase-Fallback unterstützt JPY hier nicht")
    url = COINBASE_SPOT_URL.format(pair=f"BTC-{w}")
    data = (fetch or _fetch_json)(url, timeout)
    try:
        amount = float(data["data"]["amount"])
    except (KeyError, TypeError, ValueError) as e:
        raise PriceError("Coinbase-Spotkurs nicht lesbar") from e
    if amount <= 0:
        raise PriceError("Coinbase lieferte keinen positiven Kurs")
    jetzt = int(time.time())
    return BtcPreis(
        amount=amount,
        currency=w,
        time=jetzt,
        source="coinbase",
        kind="spot",
        day=tag_aus_unix(jetzt).isoformat(),
    )


def hole_tageskurs_mempool(
    tag: date | datetime | int | str,
    currency: str = "EUR",
    *,
    base_url: str | None = None,
    timeout: float = 15.0,
    fetch: FetchFn | None = None,
) -> BtcPreis:
    """Historischer Tageskurs (UTC) über Mempool ``/api/v1/historical-price``."""
    w = normalisiere_waehrung(currency)
    kalender = parse_tag(tag)
    ts = unix_tagesbeginn(kalender)
    basis = mempool_price_base(base_url)
    query = urlencode({"currency": w, "timestamp": str(ts)})
    url = f"{basis}/api/v1/historical-price?{query}"
    data = (fetch or _fetch_json)(url, timeout)
    preise = data.get("prices")
    if not isinstance(preise, list) or not preise:
        raise PriceError(f"Kein historischer {w}-Kurs für {kalender.isoformat()}")
    eintrag = preise[0]
    if not isinstance(eintrag, dict) or w not in eintrag:
        raise PriceError(f"Historische Mempool-Antwort ohne {w}")
    try:
        amount = float(eintrag[w])
        antwort_ts = int(eintrag.get("time") or ts)
    except (TypeError, ValueError) as e:
        raise PriceError("Historischer Kurs nicht lesbar") from e
    if amount <= 0:
        raise PriceError("Historischer Kurs ist nicht positiv")
    return BtcPreis(
        amount=amount,
        currency=w,
        time=antwort_ts,
        source="mempool",
        kind="day",
        day=kalender.isoformat(),
    )


# ---------------------------------------------------------------------------
# Cache + Orchestrierung
# ---------------------------------------------------------------------------

def _spot_pfad(cache_dir: Path, currency: str) -> Path:
    return cache_dir / f"spot_{currency}.json"


def _tag_pfad(cache_dir: Path, currency: str, tag: date) -> Path:
    return cache_dir / currency / f"{tag.isoformat()}.json"


def _lese_cache(path: Path) -> BtcPreis | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return BtcPreis.from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _schreibe_cache(
    path: Path,
    preis: BtcPreis,
    *,
    fetched_at: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = preis.to_dict()
    payload["fetched_at"] = int(time.time() if fetched_at is None else fetched_at)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def lade_spot_cache(
    immutable_cache_dir: Path | str,
    currency: str = "EUR",
    *,
    ttl: int = SPOT_TTL_SEKUNDEN,
    jetzt: int | None = None,
) -> BtcPreis | None:
    """Gecachten Spotkurs, wenn noch frisch genug."""
    w = normalisiere_waehrung(currency)
    path = _spot_pfad(preis_cache_dir(immutable_cache_dir), w)
    if not path.is_file():
        return None
    try:
        roh = json.loads(path.read_text(encoding="utf-8"))
        fetched = int(roh.get("fetched_at") or roh.get("time") or 0)
        preis = BtcPreis.from_dict(roh)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    jetzt_ts = int(time.time() if jetzt is None else jetzt)
    alter = jetzt_ts - fetched
    if alter < 0 or alter > int(ttl):
        return None
    # Alte Caches: „Tageskurs von heute“ war fälschlich als Warnung gespeichert.
    heute = datetime.fromtimestamp(jetzt_ts, tz=timezone.utc).date().isoformat()
    if preis.warning and preis.day and preis.day >= heute:
        preis = BtcPreis(
            amount=preis.amount,
            currency=preis.currency,
            time=preis.time,
            source=preis.source,
            kind=preis.kind,
            day=preis.day,
            warning=None,
        )
    return preis


def lade_tageskurs_cache(
    immutable_cache_dir: Path | str,
    tag: date | datetime | int | str,
    currency: str = "EUR",
) -> BtcPreis | None:
    w = normalisiere_waehrung(currency)
    kalender = parse_tag(tag)
    return _lese_cache(_tag_pfad(preis_cache_dir(immutable_cache_dir), w, kalender))


def spot_preis(
    currency: str = "EUR",
    *,
    immutable_cache_dir: Path | str | None = None,
    mempool_url: str | None = None,
    ttl: int = SPOT_TTL_SEKUNDEN,
    timeout: float = 15.0,
    fetch: FetchFn | None = None,
    jetzt: int | None = None,
) -> BtcPreis:
    """
    Aktueller BTC-Kurs: Spot-Cache → Live (Mempool/Coinbase) →
    Tageskurs für heute (Historie-API/CSV) → letzter lokaler Tageskurs.

    Live-Fehler werden nicht als lange Pipe-Meldung ausgeworfen; bei
    Historie-Fallback setzt ``warning`` eine kurze Logzeile.
    """
    w = normalisiere_waehrung(currency)
    cache_root = Path(immutable_cache_dir) if immutable_cache_dir else None
    jetzt_ts = int(time.time() if jetzt is None else jetzt)
    heute = datetime.fromtimestamp(jetzt_ts, tz=timezone.utc).date()

    if cache_root is not None:
        cached = lade_spot_cache(cache_root, w, ttl=ttl, jetzt=jetzt_ts)
        if cached is not None:
            return cached

    preis: BtcPreis | None = None
    kandidaten: list[str | None] = []
    konfiguriert = (mempool_url or "").strip().rstrip("/")
    if konfiguriert and konfiguriert != MEMPOOL_PRICE_DEFAULT:
        kandidaten.append(konfiguriert)
    kandidaten.append(MEMPOOL_PRICE_DEFAULT)

    for basis in kandidaten:
        try:
            preis = hole_spot_mempool(
                w, base_url=basis, timeout=timeout, fetch=fetch,
            )
            break
        except PriceError:
            continue

    if preis is None:
        try:
            preis = hole_spot_coinbase(w, timeout=timeout, fetch=fetch)
        except PriceError:
            preis = None

    if preis is None:
        # Heutiger Tag aus Historie (CSV/API) — das ist der Tageskurs, kein Alarm.
        try:
            tag_preis = tageskurs(
                heute,
                w,
                immutable_cache_dir=cache_root,
                mempool_url=mempool_url,
                timeout=timeout,
                fetch=fetch,
            )
            tag = tag_preis.day or heute.isoformat()
            preis = BtcPreis(
                amount=tag_preis.amount,
                currency=w,
                time=jetzt_ts,
                source=f"{tag_preis.source}-day",
                kind="spot",
                day=tag,
                # Kein warning: heutiger Tageskurs ist der erwartete Stand
                # ohne Live-Spot (nicht „veraltet“).
            )
        except PriceError:
            preis = None

    if preis is None:
        # Älterer Bundle-/Import-Tag — nur dann kurz hinweisen (nicht bei heute).
        lokal = _neuester_tageskurs_csv(cache_root, w, bis=heute)
        if lokal is None:
            lokal = _letzter_tageskurs_csv(
                cache_root, w, bis=heute, max_tage=14,
            )
        if lokal is not None:
            warn = None
            if lokal.day and lokal.day < heute.isoformat():
                warn = (
                    f"aktueller Kurs nicht beschaffbar, "
                    f"letzter Kurs aus Historie von {lokal.day} wird verwendet"
                )
            preis = BtcPreis(
                amount=lokal.amount,
                currency=w,
                time=jetzt_ts,
                source=f"{lokal.source}-day",
                kind="spot",
                day=lokal.day,
                warning=warn,
            )

    if preis is None:
        raise PriceError("aktueller Kurs nicht beschaffbar")

    if cache_root is not None:
        _schreibe_cache(
            _spot_pfad(preis_cache_dir(cache_root), w),
            preis,
            fetched_at=jetzt_ts,
        )
    return preis


def _neuester_tageskurs_csv(
    immutable_cache_dir: Path | str | None,
    currency: str,
    *,
    bis: date,
) -> BtcPreis | None:
    """Neuester Tageskurs in der CSV an oder vor *bis* (UTC), ohne Tageslimit."""
    if currency.upper() not in HISTORIE_WAEHRUNGEN:
        return None
    path, source = historie_lesepfad(immutable_cache_dir, currency)
    if path is None:
        return None
    try:
        serie = _serie_aus_pfad(path)
    except (PriceError, OSError):
        return None
    bis_s = bis.isoformat()
    treffer = [d for d in serie if d <= bis_s]
    if not treffer:
        return None
    tag = max(treffer)
    return BtcPreis(
        amount=float(serie[tag]),
        currency=normalisiere_historie_waehrung(currency),
        time=unix_tagesbeginn(date.fromisoformat(tag)),
        source=source,
        kind="day",
        day=tag,
    )


def _letzter_tageskurs_csv(
    immutable_cache_dir: Path | str | None,
    currency: str,
    *,
    bis: date,
    max_tage: int = 14,
) -> BtcPreis | None:
    """Nächster vorhandener Tageskurs an oder vor *bis* (UTC), max. *max_tage* zurück."""
    if currency.upper() not in HISTORIE_WAEHRUNGEN:
        return None
    path, source = historie_lesepfad(immutable_cache_dir, currency)
    if path is None:
        return None
    try:
        serie = _serie_aus_pfad(path)
    except (PriceError, OSError):
        return None
    for i in range(max_tage + 1):
        tag = date.fromordinal(bis.toordinal() - i)
        amount = serie.get(tag.isoformat())
        if amount is not None:
            return BtcPreis(
                amount=float(amount),
                currency=normalisiere_historie_waehrung(currency),
                time=unix_tagesbeginn(tag),
                source=source,
                kind="day",
                day=tag.isoformat(),
            )
    return None


def tageskurs(
    tag: date | datetime | int | str,
    currency: str = "EUR",
    *,
    immutable_cache_dir: Path | str | None = None,
    mempool_url: str | None = None,
    timeout: float = 15.0,
    fetch: FetchFn | None = None,
) -> BtcPreis:
    """
    BTC-Tageskurs (UTC): Tages-JSON → lokale CSV (Import/Bundle) → Mempool.
    """
    w = normalisiere_waehrung(currency)
    kalender = parse_tag(tag)
    cache_root = Path(immutable_cache_dir) if immutable_cache_dir else None

    if cache_root is not None:
        cached = lade_tageskurs_cache(cache_root, kalender, w)
        if cached is not None:
            return cached

    lokal = lade_tageskurs_csv(cache_root, kalender, w)
    if lokal is not None:
        return lokal

    fehler: list[str] = []
    kandidaten: list[str | None] = []
    konfiguriert = (mempool_url or "").strip().rstrip("/")
    if konfiguriert and konfiguriert != MEMPOOL_PRICE_DEFAULT:
        kandidaten.append(konfiguriert)
    kandidaten.append(MEMPOOL_PRICE_DEFAULT)

    preis: BtcPreis | None = None
    for basis in kandidaten:
        try:
            preis = hole_tageskurs_mempool(
                kalender, w, base_url=basis, timeout=timeout, fetch=fetch,
            )
            break
        except PriceError as e:
            fehler.append(str(e))

    if preis is None:
        raise PriceError(
            f"Kein Tageskurs für {kalender.isoformat()}: " + " | ".join(fehler)
        )

    if cache_root is not None:
        _schreibe_cache(_tag_pfad(preis_cache_dir(cache_root), w, kalender), preis)
    return preis
