"""Log-Aufrufe für Import, Parser, Speicher und Zuordnung."""
from __future__ import annotations

from collections import Counter
from typing import Any

from core.log_redaktion import (
    dauer_ms,
    groessenordnung,
    schreibe,
    schreibe_ausnahme,
    tag_iso,
)


def nach_parse(boerse: str, ergebnis: Any, start: float) -> Any:
    nach_art = Counter(str(b.art) for b in ergebnis.buchungen)
    quar = [
        {
            "zeile": q.zeile,
            "grund": q.grund,
            "spalte": getattr(q, "spalte", None) or "-",
        }
        for q in ergebnis.quarantaene
    ]
    schreibe(
        "parse",
        boerse=boerse,
        variante=ergebnis.variante,
        n_buchungen=len(ergebnis.buchungen),
        nach_art=dict(nach_art),
        n_quarantaene=len(ergebnis.quarantaene),
        quarantaene=quar,
        dauer_ms=dauer_ms(start),
    )
    return ergebnis


def fehler(ereignis: str, exc: BaseException, **felder: object) -> None:
    schreibe_ausnahme(ereignis, exc, **felder)


def nach_vorschau(
    *,
    boerse: str | None,
    variante: str | None,
    erkannt: bool,
    nach_art: dict,
    n_buchungen: int,
    quarantaene: list,
    saldo: list,
    dauer_start: float,
    schon_importiert: bool = False,
) -> None:
    schreibe(
        "vorschau",
        boerse=boerse or "unbekannt",
        variante=variante or "-",
        erkannt=1 if erkannt else 0,
        n_buchungen=n_buchungen,
        nach_art=nach_art,
        n_quarantaene=len(quarantaene),
        quarantaene=quarantaene,
        n_saldo_luecken=len(saldo),
        saldo_luecken=saldo,
        schon_importiert=1 if schon_importiert else 0,
        dauer_ms=dauer_ms(dauer_start),
    )


def nach_import(bericht: dict, start: float, *, boerse: str | None = None) -> None:
    schreibe(
        "import",
        boerse=boerse or bericht.get("variante") or bericht.get("slug") or "-",
        variante=bericht.get("variante") or "-",
        fassung=bericht.get("fassung") or bericht.get("version") or "-",
        n_neu=bericht.get("neu") or bericht.get("imported_addresses") or 0,
        n_doppelt=bericht.get("doppelt") or 0,
        n_konflikte=bericht.get("konflikte") or 0,
        n_buchungen=bericht.get("buchungen") or bericht.get("rows_btc") or 0,
        n_quarantaene=bericht.get("quarantaene") or 0,
        schon_importiert=1 if bericht.get("schon_importiert") else 0,
        dauer_ms=dauer_ms(start),
    )


def nach_speicher(
    *,
    slug: str,
    variante: str | None,
    neu: int,
    doppelt: int,
    konflikte: int,
    konflikt_zeilen: list[int],
    n_buchungen: int,
    n_quarantaene: int,
    schon: bool,
    start: float,
) -> None:
    schreibe(
        "speicher",
        slug=slug,
        variante=variante or "-",
        n_neu=neu,
        n_doppelt=doppelt,
        n_konflikte=konflikte,
        konflikt_zeilen=konflikt_zeilen,
        n_buchungen=n_buchungen,
        n_quarantaene=n_quarantaene,
        schon_importiert=1 if schon else 0,
        dauer_ms=dauer_ms(start),
    )


def nach_zuordnung(
    *,
    n_auszahlungen: int,
    n_empfaenge: int,
    nach_status: dict,
    nach_methode: dict,
    n_luecken: int,
    n_quarantaene: int,
    n_kein_hop: int,
    kandidaten: list[int],
    quarantaene_gruende: list[str],
    start: float,
    slug: str | None = None,
) -> None:
    schreibe(
        "zuordnung",
        slug=slug or "-",
        n_auszahlungen=n_auszahlungen,
        n_empfaenge=n_empfaenge,
        nach_status=nach_status,
        nach_methode=nach_methode,
        n_luecken=n_luecken,
        n_quarantaene=n_quarantaene,
        n_kein_hop=n_kein_hop,
        n_kandidaten=len(kandidaten),
        kandidaten_max=max(kandidaten) if kandidaten else 0,
        kandidaten_summe=sum(kandidaten) if kandidaten else 0,
        quarantaene_gruende=quarantaene_gruende,
        dauer_ms=dauer_ms(start),
    )


def saldo_eintrag(*, zeile: int, differenz: object, zeit_ts: int | None, einheit: str) -> dict:
    return {
        "zeile": zeile,
        "groesse": groessenordnung(differenz, einheit=einheit),
        "tag": tag_iso(zeit_ts),
    }
