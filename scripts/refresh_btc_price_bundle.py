#!/usr/bin/env python3
"""Aktualisiert data/btc_price/{EUR,USD}.csv bis zum Tip.

Für Release-/PyInstaller-Builds: die mitgelieferte Historie soll bis zum
aktuellen Tip reichen. Schreibt nur ins lokale Bundle unter data/btc_price/,
nicht in immutable_cache/ und nicht ins Git (die CSVs sind gitignore).

Primär Bitstamp/CryptoDataDownload (volle Serie). Fällt CDD aus — etwa ein
abgelaufenes TLS-Zertifikat — holt das Skript nur die Lücke über Mempool,
Tag für Tag, und behält das vorhandene Bundle. Ein totes CDD bricht den
StartOS-/Release-Build damit nicht ab.

  ./scripts/refresh_btc_price_bundle.py
  SKIP_BTC_PRICE_REFRESH=1  → no-op (Offline-Builds)

Netz: öffentliches CDD oder Mempool — für CI ok; lokal braucht Netz oder Skip.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import price as price_mod  # noqa: E402
from core import price_history_sync as hist_sync  # noqa: E402


def _ziel_tip() -> date:
    """Mindest-Tip: gestern UTC (heutiger Schluss oft noch unvollständig)."""
    return datetime.now(timezone.utc).date() - timedelta(days=1)


def _bundle_tip(ziel: Path) -> date | None:
    if not ziel.is_file():
        return None
    try:
        serie = price_mod._serie_aus_pfad(ziel)
    except (price_mod.PriceError, OSError):
        return None
    if not serie:
        return None
    return date.fromisoformat(max(serie))


def _lokal_serie(ziel: Path) -> dict[str, float]:
    if not ziel.is_file():
        return {}
    try:
        return dict(price_mod._serie_aus_pfad(ziel))
    except (price_mod.PriceError, OSError):
        return {}


def _schreibe_mit_url(ziel: Path, serie: dict[str, float], *, currency: str, quelle: str, url: str) -> None:
    price_mod.schreibe_kurs_csv(ziel, serie, currency=currency, quelle=quelle)
    text = ziel.read_text(encoding="utf-8")
    if "# URL:" in text:
        return
    zeilen = text.splitlines(keepends=True)
    out: list[str] = []
    eingefuegt = False
    for z in zeilen:
        out.append(z)
        if not eingefuegt and z.startswith("# Quelle:"):
            out.append(f"# URL: {url}\n")
            eingefuegt = True
    if not eingefuegt:
        out.insert(1, f"# URL: {url}\n")
    ziel.write_text("".join(out), encoding="utf-8")


def _fuelle_luecke_mempool(
    w: str,
    ziel: Path,
    *,
    ab: date,
    bis: date,
    timeout: float,
    grund: str,
) -> dict:
    """Nur fehlende Tage über Mempool. Vorhandenes Bundle bleibt."""
    print(
        f"→ Mempool {w} ab {ab.isoformat()} bis {bis.isoformat()} "
        f"(CDD nicht nutzbar: {grund}) …",
        flush=True,
    )
    remote = hist_sync.hole_historie_mempool_luecke(
        w,
        ab=ab,
        bis=bis,
        timeout=min(timeout, 25.0),
        on_log=lambda text: print(f"  {text}", flush=True),
    )
    if not remote:
        raise SystemExit(
            f"Keine Kurse für {w}: CDD nicht nutzbar ({grund}) "
            f"und Mempool lieferte keine Tage ab {ab.isoformat()}."
        )
    letzter = date.fromisoformat(max(remote))
    if letzter < bis:
        raise SystemExit(
            f"Mempool-Lücke für {w} endet bei {letzter.isoformat()}, "
            f"Ziel ist {bis.isoformat()}."
        )
    lokal = _lokal_serie(ziel)
    # Nur die Lücke anhängen. Ältere Tage aus dem Bundle nicht überschreiben.
    merged = dict(lokal)
    for tag, preis in remote.items():
        if tag >= ab.isoformat():
            merged[tag] = preis
    stand = datetime.now(timezone.utc).date().isoformat()
    url = price_mod.MEMPOOL_PRICE_DEFAULT
    _schreibe_mit_url(
        ziel,
        merged,
        currency=w,
        quelle=f"Bitstamp-Bundle plus Mempool-Lücke; Stand: {stand}",
        url=url,
    )
    return merged


def refresh_currency(currency: str, *, timeout: float = 90.0) -> dict:
    w = price_mod.normalisiere_historie_waehrung(currency)
    ziel = ROOT / "data" / "btc_price" / f"{w}.csv"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    url = hist_sync.CDD_BITSTAMP[w]
    soll = _ziel_tip()

    tip = _bundle_tip(ziel)
    if tip is not None and tip >= soll:
        print(
            f"→ {w}: Bundle schon aktuell bis {tip.isoformat()} "
            f"(≥ {soll.isoformat()}) — kein Download.",
            flush=True,
        )
        return {
            "currency": w,
            "from": None,
            "to": tip.isoformat(),
            "days": None,
            "skipped": True,
        }

    if tip is None:
        print(f"→ Bitstamp/CDD {w} (kein Bundle) …", flush=True)
    else:
        print(
            f"→ Bitstamp/CDD {w} (Bundle bis {tip.isoformat()}, "
            f"Ziel ≥ {soll.isoformat()}) …",
            flush=True,
        )
    try:
        roh = hist_sync.hole_bitstamp_cdd_csv(
            w,
            timeout=timeout,
            values={"SATSAGE_PRICE_HISTORY_OPT_IN": "1"},
        )
    except price_mod.PriceError as exc:
        if tip is None:
            raise SystemExit(
                f"CDD für {w} nicht nutzbar ({exc}) und kein lokales Bundle, "
                "aus dem sich nur die Lücke füllen ließe."
            ) from exc
        merged = _fuelle_luecke_mempool(
            w, ziel, ab=tip + timedelta(days=1), bis=soll,
            timeout=timeout, grund=str(exc),
        )
        tage = sorted(merged)
        print(
            f"  {w}: {len(tage)} Tage · {tage[0]} … {tage[-1]} "
            f"→ {ziel.relative_to(ROOT)} (Mempool-Lücke)",
            flush=True,
        )
        return {
            "currency": w,
            "from": tage[0],
            "to": tage[-1],
            "days": len(tage),
            "skipped": False,
            "source": "mempool-gap",
        }

    remote = price_mod.parse_kurs_csv(roh)
    if not remote:
        raise SystemExit(f"Keine Kurse in CDD-Antwort für {w}")

    # Tage vor Remote-Start aus altem Bundle behalten (falls CDD später startet).
    lokal = _lokal_serie(ziel)
    remote_min = min(remote)
    merged = {k: v for k, v in lokal.items() if k < remote_min}
    merged.update(remote)

    stand = datetime.now(timezone.utc).date().isoformat()
    _schreibe_mit_url(
        ziel,
        merged,
        currency=w,
        quelle=(
            f"Bitstamp via CryptoDataDownload; URL: {url}; Stand: {stand}"
        ),
        url=url,
    )
    tage = sorted(merged)
    print(
        f"  {w}: {len(tage)} Tage · {tage[0]} … {tage[-1]} "
        f"→ {ziel.relative_to(ROOT)}",
        flush=True,
    )
    return {
        "currency": w,
        "from": tage[0],
        "to": tage[-1],
        "days": len(tage),
        "skipped": False,
        "source": "bitstamp-cdd",
    }


def main() -> int:
    if os.environ.get("SKIP_BTC_PRICE_REFRESH", "").strip().lower() in (
        "1", "true", "yes", "ja", "on",
    ):
        print("→ BTC-Preis-Bundle: übersprungen (SKIP_BTC_PRICE_REFRESH=1)")
        return 0

    print("→ BTC-Preis-Bundle aktualisieren (Release bis Tip)…")
    for w in ("EUR", "USD"):
        refresh_currency(w)
    print("→ BTC-Preis-Bundle fertig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
