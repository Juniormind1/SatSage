#!/usr/bin/env python3
"""Aktualisiert data/btc_price/{EUR,USD}.csv aus Bitstamp (CryptoDataDownload).

Für Release-/PyInstaller-Builds: die mitgelieferte Historie soll bis zum
aktuellen Tip reichen. Schreibt nur ins Repo-Bundle unter data/btc_price/,
nicht in immutable_cache/.

  ./scripts/refresh_btc_price_bundle.py
  SKIP_BTC_PRICE_REFRESH=1  → no-op (Offline-Builds)

Netz: öffentliches CDD — für CI ok; lokal braucht Netz oder Skip.
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
    roh = hist_sync.hole_bitstamp_cdd_csv(
        w,
        timeout=timeout,
        values={"SATSAGE_PRICE_HISTORY_OPT_IN": "1"},
    )
    remote = price_mod.parse_kurs_csv(roh)
    if not remote:
        raise SystemExit(f"Keine Kurse in CDD-Antwort für {w}")

    # Tage vor Remote-Start aus altem Bundle behalten (falls CDD später startet).
    lokal: dict[str, float] = {}
    if ziel.is_file():
        try:
            lokal = dict(price_mod._serie_aus_pfad(ziel))
        except (price_mod.PriceError, OSError):
            lokal = {}
    remote_min = min(remote)
    merged = {k: v for k, v in lokal.items() if k < remote_min}
    merged.update(remote)

    stand = datetime.now(timezone.utc).date().isoformat()
    price_mod.schreibe_kurs_csv(
        ziel,
        merged,
        currency=w,
        quelle=(
            f"Bitstamp via CryptoDataDownload; URL: {url}; Stand: {stand}"
        ),
    )
    # Explizite URL-Zeile wie im bisherigen Bundle-Format
    text = ziel.read_text(encoding="utf-8")
    if "# URL:" not in text:
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
