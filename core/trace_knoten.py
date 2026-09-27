"""
Herkunftsbaum knotenweise (ISSUES P2): Die Oberfläche bekommt die Wurzel und
die erste Seite der Kinder; tiefer geht es pro Knoten beim Aufklappen,
breite Knoten seitenweise. Der Baum selbst bleibt im Herkunfts-Cache.

Knoten werden über ihren Pfad adressiert: Kindindizes ab der obersten
Ebene, mit Punkt getrennt (``"0.3.1"``; leer = oberste Ebene).
"""
from __future__ import annotations

import json

from core import listen_fenster as lf

#: Felder der Baum-Marken — genug für ``mixArtenAusErgebnis`` und
#: ``boerseNamenAusErgebnis`` im Browser.
_MARKEN_FELDER = ("tx_class", "label", "exchange_label", "abfluss")


def pfad_teile(pfad: str | None) -> list[int] | None:
    """``"0.3"`` → ``[0, 3]``; leer → ``[]``; ungültig → ``None``."""
    text = str(pfad or "").strip()
    if not text:
        return []
    teile = []
    for stueck in text.split("."):
        if not stueck.isdigit():
            return None
        teile.append(int(stueck))
    return teile


def kinder_an(baum: dict, teile: list[int]) -> list | None:
    """Kinderliste des Knotens unter *teile* (``[]`` = oberste Ebene)."""
    kinder = baum.get("children") if isinstance(baum, dict) else None
    for i in teile:
        if not isinstance(kinder, list) or not (0 <= i < len(kinder)):
            return None
        knoten = kinder[i]
        if not isinstance(knoten, dict):
            return None
        kinder = knoten.get("children") or []
    return kinder if isinstance(kinder, list) else None


def schlank(knoten: dict, pfad: str) -> dict:
    """Knoten ohne Unterbaum, dafür mit ``pfad`` und ``kinder_count``."""
    if not isinstance(knoten, dict):
        return knoten
    aus = {k: v for k, v in knoten.items() if k != "children"}
    aus["pfad"] = pfad
    aus["kinder_count"] = len(knoten.get("children") or [])
    return aus


def seite(kinder: list, teile: list[int], offset: int, limit: int) -> dict:
    offset = max(0, int(offset or 0))
    limit = max(0, min(int(limit or 0), lf.MAX_LIMIT))
    praefix = ".".join(str(i) for i in teile)
    items = [
        schlank(k, f"{praefix}.{offset + j}" if praefix else str(offset + j))
        for j, k in enumerate(kinder[offset:offset + limit])
    ]
    return {"items": items, "total": len(kinder), "offset": offset, "limit": limit}


def marken(baum: dict) -> list[dict]:
    """
    Alle Knoten mit Form-/Börsenbezug in der Reihenfolge, in der die
    Browser-Funktionen (Stapel: Wurzel, Kinder; pop) sie besuchen.

    Doppelte Marken fallen weg, die letzte bleibt stehen — so ist das
    Ergebnis dasselbe wie über den ganzen Baum („out“ sticht, sonst gilt
    die zuletzt gesehene Richtung).
    """
    stapel = []
    if isinstance(baum.get("root"), dict):
        stapel.append(baum["root"])
    stapel.extend(baum.get("children") or [])
    folge: list[dict] = []
    while stapel:
        knoten = stapel.pop()
        if not isinstance(knoten, dict):
            continue
        marke = {k: knoten[k] for k in _MARKEN_FELDER if lf._js_wahr(knoten.get(k))}
        quellen = [
            {k: q[k] for k in ("label", "exchange_label") if isinstance(q, dict) and lf._js_wahr(q.get(k))}
            for q in (knoten.get("sources") or [])
        ]
        quellen = [q for q in quellen if q]
        if quellen:
            marke["sources"] = quellen
        if marke and (set(marke) - {"abfluss"}):
            folge.append(marke)
        stapel.extend(knoten.get("children") or [])
    zuletzt: dict[str, int] = {}
    for i, m in enumerate(folge):
        zuletzt[json.dumps(m, sort_keys=True, ensure_ascii=False)] = i
    behalten = sorted(zuletzt.values())
    return [folge[i] for i in behalten]


def seitenweise(ergebnis: dict, limit: int) -> dict:
    """Ergebnis mit Wurzel und erster Kinderseite statt ganzem Baum."""
    if not isinstance(ergebnis, dict) or not ergebnis.get("found"):
        return ergebnis
    kinder = ergebnis.get("children") or []
    aus = {k: v for k, v in ergebnis.items() if k not in ("children", "origin_tree")}
    if isinstance(aus.get("root"), dict) and "children" in aus["root"]:
        aus["root"] = schlank(aus["root"], "")
    s = seite(kinder, [], 0, limit)
    aus["children"] = s["items"]
    aus["children_total"] = s["total"]
    aus["seitenweise"] = True
    aus["baum_marken"] = marken(ergebnis)
    return aus
