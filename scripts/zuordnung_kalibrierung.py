#!/usr/bin/env python3
"""Wertet Kalibrier-Logs der Börsenzuordnung aus, ohne Kennungen zu erwarten.

Liest stdin oder Dateien. Sucht nach Ereignissen ``zuordnung_kandidat`` und
``zuordnung_entscheidung``. Gibt Verteilungen und eine Schätzung aus, wie viele
manuelle Bestätigungen eine Auto-Regel (eindeutig, optional nur Adresse)
erspart hätte und wie viele später abgelehnt worden wären.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

_FELD = re.compile(r"(\w+)=(\S+)")


def _parse_zeile(text: str) -> dict[str, str] | None:
    if "zuordnung_kandidat" not in text and "zuordnung_entscheidung" not in text:
        return None
    felder = dict(_FELD.findall(text))
    if "zuordnung_kandidat" in text:
        felder["ereignis"] = "kandidat"
    else:
        felder["ereignis"] = "entscheidung"
    return felder


def _lesen(pfade: list[Path], stdin: bool) -> list[dict[str, str]]:
    zeilen: list[str] = []
    if stdin or not pfade:
        zeilen.extend(sys.stdin.read().splitlines())
    for pfad in pfade:
        zeilen.extend(Path(pfad).read_text(encoding="utf-8", errors="replace").splitlines())
    aus = []
    for zeile in zeilen:
        parsed = _parse_zeile(zeile)
        if parsed:
            aus.append(parsed)
    return aus


def _zaehle(eintraege: list[dict[str, str]], feld: str) -> collections.Counter:
    return collections.Counter(e.get(feld, "-") for e in eintraege)


def auswerten(eintraege: list[dict[str, str]]) -> str:
    kands = [e for e in eintraege if e.get("ereignis") == "kandidat"]
    ents = [e for e in eintraege if e.get("ereignis") == "entscheidung"]
    zeilen = []
    zeilen.append(f"Kandidaten-Ereignisse: {len(kands)}")
    zeilen.append(f"Nutzer-Entscheidungen: {len(ents)}")
    if kands:
        zeilen.append("Entscheidungen der Zuordnung:")
        for k, n in _zaehle(kands, "entscheidung").most_common():
            zeilen.append(f"  {k}: {n}")
        zeilen.append("Methoden:")
        for k, n in _zaehle(kands, "methode").most_common():
            zeilen.append(f"  {k}: {n}")
        zeilen.append("Zeitabstand (Minuten-Bucket):")
        for k, n in _zaehle(kands, "zeit_min_bucket").most_common():
            zeilen.append(f"  {k}: {n}")
        zeilen.append("Betragsabweichung (relativ, Bucket):")
        for k, n in _zaehle(kands, "delta_rel_bucket").most_common():
            zeilen.append(f"  {k}: {n}")
        zeilen.append("Kandidatenzahl:")
        for k, n in _zaehle(kands, "n_kandidaten").most_common():
            zeilen.append(f"  {k}: {n}")

        vorschlaege = [e for e in kands if e.get("entscheidung") == "vorschlag"]
        eindeutig = [e for e in vorschlaege if e.get("n_kandidaten") == "1"]
        eindeutig_adr = [e for e in eindeutig if e.get("methode") == "adresse"]
        zeilen.append(
            "Auto-Schätzung (nur eindeutige Vorschläge, Auto war aus oder hat nicht gegriffen):"
        )
        zeilen.append(f"  eindeutig (n=1): {len(eindeutig)} von {len(vorschlaege)} Vorschlägen")
        zeilen.append(f"  davon Adresstreffer: {len(eindeutig_adr)}")

        # Nutzerentscheidungen nach ref koppeln, falls vorhanden.
        nach_ref = {e.get("ref"): e for e in ents if e.get("ref")}
        if nach_ref and eindeutig_adr:
            spaeter = [nach_ref[e["ref"]] for e in eindeutig_adr if e.get("ref") in nach_ref]
            abgelehnt = sum(1 for e in spaeter if e.get("status") == "abgelehnt")
            bestaetigt = sum(1 for e in spaeter if e.get("status") == "bestaetigt")
            zeilen.append(
                f"  von den Adress-Eindeutigen mit späterer Nutzerentscheidung: "
                f"{bestaetigt} bestätigt, {abgelehnt} abgelehnt "
                f"(falsche Autos, falls Auto an gewesen wäre)."
            )
    if ents:
        zeilen.append("Nutzerentscheidungen nach Status:")
        for k, n in _zaehle(ents, "status").most_common():
            zeilen.append(f"  {k}: {n}")
    return "\n".join(zeilen) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pfade", nargs="*", type=Path, help="Logdateien")
    parser.add_argument("--stdin", action="store_true", help="Zusätzlich stdin lesen")
    args = parser.parse_args(argv)
    daten = _lesen(args.pfade, args.stdin or not args.pfade)
    sys.stdout.write(auswerten(daten))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
