"""Täglicher Nachzug der BTC-Tageskurs-Historie.

Einmal pro UTC-Tag: Lücke bis gestern füllen. Primär Bitstamp-CSV
(CryptoDataDownload), bei Ausfall Mempool-Tageskurse Tag für Tag.
Kein Opt-in — nur Fiat-Kurse, keine Wallet-Daten. CSV-Import bleibt
für Puristen. Schreibt nur ``immutable_cache/btc_price/``, nie das Bundle.
"""
from __future__ import annotations

import statistics
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from outbound_policy import ensure_url_allowed

from core import price as price_mod

LogFn = Callable[[str], None]

#: CryptoDataDownload — dieselbe Quelle wie das mitgelieferte Bundle.
CDD_BITSTAMP = {
    "EUR": "https://www.cryptodatadownload.com/cdd/Bitstamp_BTCEUR_d.csv",
    "USD": "https://www.cryptodatadownload.com/cdd/Bitstamp_BTCUSD_d.csv",
}

OVERLAP_TAGE = 28
DISKREPANZ_MEDIAN_PCT = 1.5
SMOOTH_TAGE = 7
#: Veraltet — Historie braucht kein Opt-in mehr; bleibt für alte API/Tests.
ENV_OPT_IN = "SATSAGE_PRICE_HISTORY_OPT_IN"

_USER_AGENT = "SatSage/1.0"


def price_history_opt_in(values: dict[str, str] | None) -> bool:
    """Immer an — Nachzug läuft ohne Einstellungs-Schalter."""
    _ = values
    return True


def _log(on_log: LogFn | None, text: str) -> None:
    if on_log:
        on_log(text)


def _stamp_pfad(immutable_cache_dir: Path | str) -> Path:
    return price_mod.preis_cache_dir(immutable_cache_dir) / ".history_sync_utc"


def _heute_utc(jetzt: int | None = None) -> date:
    ts = int(time.time() if jetzt is None else jetzt)
    return datetime.fromtimestamp(ts, tz=timezone.utc).date()


def schon_heute_geprueft(
    immutable_cache_dir: Path | str,
    *,
    jetzt: int | None = None,
) -> bool:
    """True, wenn der tägliche Check für den aktuellen UTC-Tag schon lief."""
    pfad = _stamp_pfad(immutable_cache_dir)
    if not pfad.is_file():
        return False
    try:
        stand = pfad.read_text(encoding="utf-8").strip()[:10]
        return stand == _heute_utc(jetzt).isoformat()
    except OSError:
        return False


def _merke_check(
    immutable_cache_dir: Path | str,
    *,
    jetzt: int | None = None,
) -> None:
    pfad = _stamp_pfad(immutable_cache_dir)
    try:
        pfad.write_text(_heute_utc(jetzt).isoformat() + "\n", encoding="utf-8")
    except OSError:
        pass


def historie_luecke_bis(
    immutable_cache_dir: Path | str | None,
    currency: str,
    *,
    bis: date | None = None,
) -> date | None:
    """
    Erster fehlender Tag nach dem lokalen Serienende, oder None wenn aktuell.

    *bis* default: gestern UTC (heutiger Schlusskurs oft noch unvollständig).
    """
    w = price_mod.normalisiere_historie_waehrung(currency)
    ziel = bis or (_heute_utc() - timedelta(days=1))
    path, _herkunft = price_mod.historie_lesepfad(immutable_cache_dir, w)
    if path is None or not path.is_file():
        return date(2009, 1, 3)  # Genesis-Nähe — voller Nachzug
    try:
        serie = price_mod._serie_aus_pfad(path)
    except (price_mod.PriceError, OSError):
        return date(2009, 1, 3)
    if not serie:
        return date(2009, 1, 3)
    ende = date.fromisoformat(max(serie))
    if ende >= ziel:
        return None
    return ende + timedelta(days=1)


def hole_bitstamp_cdd_csv(
    currency: str,
    *,
    timeout: float = 60.0,
    fetch: Callable[[str, float], str] | None = None,
    values: dict[str, str] | None = None,
) -> str:
    """Roh-CSV von CryptoDataDownload (Bitstamp daily)."""
    w = price_mod.normalisiere_historie_waehrung(currency)
    url = CDD_BITSTAMP[w]
    if fetch is not None:
        return fetch(url, timeout)
    ensure_url_allowed(url, service="price_history", values=values)
    anfrage = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(anfrage, timeout=timeout) as ant:
            return ant.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise price_mod.PriceError(f"HTTP {e.code} bei Historie-Download ({url})") from e
    except urllib.error.URLError as e:
        raise price_mod.PriceError(f"Netzfehler bei Historie-Download: {e.reason}") from e
    except TimeoutError as e:
        raise price_mod.PriceError("Zeitüberschreitung bei Historie-Download") from e


def _mempool_basis(values: dict[str, str] | None) -> str | None:
    if values:
        roh = (values.get("MEMPOOL_URL") or "").strip().rstrip("/")
        if roh:
            return roh
    return price_mod.MEMPOOL_PRICE_DEFAULT


def hole_historie_mempool_luecke(
    currency: str,
    *,
    ab: date,
    bis: date,
    values: dict[str, str] | None = None,
    timeout: float = 20.0,
    on_log: LogFn | None = None,
) -> dict[str, float]:
    """
    Fehlende Tage einzeln über Mempool ``/historical-price`` (UTC-Tageskurs).

    Fallback, wenn die Bitstamp-CSV nicht greifbar ist. Begrenzt auf 400 Tage
    pro Lauf, damit ein leerer Cache nicht ewig tagweise pullt.
    """
    w = price_mod.normalisiere_historie_waehrung(currency)
    if w not in ("EUR", "USD"):
        return {}
    basis_liste: list[str] = []
    konfiguriert = _mempool_basis(values)
    if konfiguriert:
        basis_liste.append(konfiguriert)
    if price_mod.MEMPOOL_PRICE_DEFAULT not in basis_liste:
        basis_liste.append(price_mod.MEMPOOL_PRICE_DEFAULT)

    serie: dict[str, float] = {}
    d = ab
    geholt = 0
    max_tage = 400
    while d <= bis and geholt < max_tage:
        ds = d.isoformat()
        preis = None
        for basis in basis_liste:
            try:
                preis = price_mod.hole_tageskurs_mempool(
                    d, w, base_url=basis, timeout=timeout,
                )
                break
            except price_mod.PriceError:
                continue
        if preis is not None and preis.amount > 0:
            serie[ds] = float(preis.amount)
            geholt += 1
        d += timedelta(days=1)
    if serie:
        _log(
            on_log,
            f"Kurs-Historie {w}: Mempool lieferte {len(serie)} Tag(e) "
            f"({min(serie)}…{max(serie)}).",
        )
    return serie


def lade_remote_historie(
    currency: str,
    *,
    luecke_ab: date,
    bis: date,
    values: dict[str, str] | None = None,
    timeout: float = 60.0,
    fetch: Callable[[str, float], str] | None = None,
    on_log: LogFn | None = None,
) -> tuple[dict[str, float], str]:
    """
    Remote-Serie: Bitstamp/CDD zuerst, sonst Mempool-Tageskurse.

    Rückgabe ``(serie, quelle)``.
    """
    w = price_mod.normalisiere_historie_waehrung(currency)
    try:
        roh = hole_bitstamp_cdd_csv(
            w, timeout=timeout, fetch=fetch, values=values,
        )
        remote = price_mod.parse_kurs_csv(roh)
        if remote:
            return remote, "bitstamp-cdd"
    except price_mod.PriceError as exc:
        _log(on_log, f"Kurs-Historie {w}: Bitstamp/CDD nicht nutzbar ({exc}).")

    if fetch is not None:
        # Tests injizieren nur CDD-Fetch — kein stiller Mempool-Pfad.
        raise price_mod.PriceError("keine Remote-Historie (Fetch-Stub ohne Treffer)")

    mem = hole_historie_mempool_luecke(
        w, ab=luecke_ab, bis=bis, values=values, timeout=min(timeout, 25.0),
        on_log=on_log,
    )
    if mem:
        return mem, "mempool-day"
    raise price_mod.PriceError("keine vertrauenswürdige Kurs-Quelle erreichbar")


def _median_abs_pct(
    lokal: dict[str, float],
    remote: dict[str, float],
    tage: list[str],
) -> float | None:
    deltas: list[float] = []
    for tag in tage:
        a = lokal.get(tag)
        b = remote.get(tag)
        if a is None or b is None or a <= 0:
            continue
        deltas.append(abs(b - a) / a * 100.0)
    if not deltas:
        return None
    return float(statistics.median(deltas))


def _smooth_uebergang(
    serie: dict[str, float],
    *,
    anker_tag: str,
    anker_wert: float,
    remote: dict[str, float],
    ab: date,
    tage: int = SMOOTH_TAGE,
) -> list[str]:
    """Lineare Blend von *anker_wert* zu Remote über *tage* ab *ab*."""
    geaendert: list[str] = []
    for i in range(tage):
        tag = (ab + timedelta(days=i)).isoformat()
        ziel = remote.get(tag)
        if ziel is None:
            continue
        w = (i + 1) / float(tage)
        serie[tag] = anker_wert * (1.0 - w) + float(ziel) * w
        geaendert.append(tag)
    return geaendert


def merge_historie_mit_overlap(
    lokal: dict[str, float],
    remote: dict[str, float],
    *,
    luecke_ab: date,
    bis: date,
    overlap_tage: int = OVERLAP_TAGE,
    diskr_median_pct: float = DISKREPANZ_MEDIAN_PCT,
    smooth_tage: int = SMOOTH_TAGE,
    on_log: LogFn | None = None,
) -> tuple[dict[str, float], dict]:
    """
    Lokal halten, Lücke aus Remote füllen; Überlappung prüfen.

    Rückgabe: (merged, meta) mit Keys ``diskrepanz``, ``smooth``, ``neu_tage``.
    """
    out = dict(lokal)
    meta: dict = {
        "diskrepanz": False,
        "diskrepanz_median_pct": None,
        "smooth": False,
        "neu_tage": 0,
        "overlap_tage": 0,
    }

    # Überlappung: letzte *overlap_tage* vor der Lücke (bzw. vor Remote-Tip).
    overlap_ende = luecke_ab - timedelta(days=1)
    overlap_start = overlap_ende - timedelta(days=overlap_tage - 1)
    overlap = []
    d = overlap_start
    while d <= overlap_ende:
        ds = d.isoformat()
        if ds in lokal and ds in remote:
            overlap.append(ds)
        d += timedelta(days=1)
    meta["overlap_tage"] = len(overlap)

    median = _median_abs_pct(lokal, remote, overlap)
    meta["diskrepanz_median_pct"] = median
    if median is not None and median > diskr_median_pct:
        meta["diskrepanz"] = True
        _log(
            on_log,
            f"Kurs-Historie: Diskrepanz in {len(overlap)} Überlappungs-Tagen "
            f"(Median |Δ| {median:.2f} % > {diskr_median_pct} %) — "
            f"Überlappung aus neuer Bitstamp-Historie.",
        )
        for tag in overlap:
            out[tag] = float(remote[tag])

    # Lücke + ggf. frische Tage bis *bis*
    neu = 0
    d = luecke_ab
    while d <= bis:
        ds = d.isoformat()
        if ds in remote:
            out[ds] = float(remote[ds])
            neu += 1
        d += timedelta(days=1)
    meta["neu_tage"] = neu

    # Sprung am Wechsel: letzter lokaler Anker vs. erster Remote-Tag der Lücke
    anker_tag = (luecke_ab - timedelta(days=1)).isoformat()
    anker = out.get(anker_tag)
    if anker is None and lokal:
        # nach Diskrepanz-Replace immer noch da
        anker = lokal.get(anker_tag)
    erster = remote.get(luecke_ab.isoformat())
    if (
        anker is not None
        and anker > 0
        and erster is not None
        and abs(erster - anker) / anker * 100.0 > diskr_median_pct
    ):
        sprung = abs(erster - anker) / anker * 100.0
        _log(
            on_log,
            f"Kurs-Historie: Kurssprung am Quellenwechsel {luecke_ab.isoformat()} "
            f"(|Δ| {sprung:.2f} %) — {smooth_tage}-Tage-Smoothing.",
        )
        _smooth_uebergang(
            out,
            anker_tag=anker_tag,
            anker_wert=float(anker),
            remote=remote,
            ab=luecke_ab,
            tage=smooth_tage,
        )
        meta["smooth"] = True

    return out, meta


def historie_nachziehen(
    immutable_cache_dir: Path | str,
    currency: str = "EUR",
    *,
    values: dict[str, str] | None = None,
    on_log: LogFn | None = None,
    timeout: float = 60.0,
    fetch: Callable[[str, float], str] | None = None,
    jetzt: int | None = None,
    force: bool = False,
) -> dict:
    """
    Einmal prüfen/nachziehen für *currency*.

    Immer Netz, wenn Lücke — kein Opt-in. ``force`` ignoriert den Tages-Stamp
    (manueller Knopf „Jetzt nachziehen“).
    """
    w = price_mod.normalisiere_historie_waehrung(currency)
    root = Path(immutable_cache_dir)
    heute = _heute_utc(jetzt)
    bis = heute - timedelta(days=1)

    if not force and schon_heute_geprueft(root, jetzt=jetzt):
        return {"ok": True, "noop": True, "reason": "already_checked_today", "currency": w}

    luecke = historie_luecke_bis(root, w, bis=bis)
    if luecke is None:
        _merke_check(root, jetzt=jetzt)
        _log(on_log, f"Kurs-Historie {w}: aktuell bis {bis.isoformat()}.")
        return {"ok": True, "noop": True, "reason": "current", "currency": w}

    _log(
        on_log,
        f"Kurs-Historie {w}: Lücke ab {luecke.isoformat()} — hole Kurse…",
    )
    try:
        remote, quelle = lade_remote_historie(
            w,
            luecke_ab=luecke,
            bis=bis,
            values=values,
            timeout=timeout,
            fetch=fetch,
            on_log=on_log,
        )
    except price_mod.PriceError as exc:
        _merke_check(root, jetzt=jetzt)
        _log(on_log, f"Kurs-Historie {w}: Nachzug fehlgeschlagen — {exc}")
        return {"ok": False, "reason": "fetch", "currency": w, "error": str(exc)}

    path, herkunft = price_mod.historie_lesepfad(root, w)
    if path is not None and path.is_file():
        try:
            lokal = dict(price_mod._serie_aus_pfad(path))
        except (price_mod.PriceError, OSError):
            lokal = {}
    else:
        lokal = {}

    merged, meta = merge_historie_mit_overlap(
        lokal,
        remote,
        luecke_ab=luecke,
        bis=bis,
        on_log=on_log,
    )
    ziel = price_mod.historie_csv_pfad(root, w)
    price_mod.schreibe_kurs_csv(
        ziel,
        merged,
        currency=w,
        quelle=f"{quelle}-sync",
    )
    _merke_check(root, jetzt=jetzt)
    _log(
        on_log,
        f"Kurs-Historie {w}: {meta['neu_tage']} Tag(e) ergänzt "
        f"(bis {bis.isoformat()}, Quelle {quelle}, vorher {herkunft}).",
    )
    return {
        "ok": True,
        "currency": w,
        "gap_from": luecke.isoformat(),
        "to": bis.isoformat(),
        "source": quelle,
        **meta,
    }


def historie_nachziehen_alle(
    immutable_cache_dir: Path | str,
    *,
    values: dict[str, str] | None = None,
    on_log: LogFn | None = None,
    timeout: float = 60.0,
    fetch: Callable[[str, float], str] | None = None,
    jetzt: int | None = None,
    force: bool = False,
) -> list[dict]:
    """EUR und USD nacheinander (ein Stamp für beide über ersten Lauf)."""
    ergebnisse = []
    for w in ("EUR", "USD"):
        ergebnisse.append(
            historie_nachziehen(
                immutable_cache_dir,
                w,
                values=values,
                on_log=on_log,
                timeout=timeout,
                fetch=fetch,
                jetzt=jetzt,
                force=force,
            )
        )
    return ergebnisse
