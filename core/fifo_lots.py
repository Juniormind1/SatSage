"""
FIFO je Output: welche Lose eine Transaktion an welchen Output weitergibt.

Eine Regel für beide Seiten (ISSUES „Herkunft · FIFO je Output“, Entscheidung
Maintainer 2026-10-04): die Herkunftsverfolgung (``core.herkunftsnetz.flach``)
und die PSBT-Vorschau (``core.psbt_bau``) rufen dieselbe ``verteilen``.

**Lose.** Jeder Eingang bringt seine Lose mit (Anschaffungszeit, sats). Alle
Lose aller Eingänge werden gemeinsam geordnet:

1. nach Anschaffungszeit, älteste zuerst;
2. Lose ohne Zeit nehmen als Sortierzeit die Zeit der ersten datierten
   Transaktion, die sie ausgibt (früher können sie nicht angeschafft sein);
   ohne jede Zeit kommen sie ganz ans Ende;
3. Gleichstand: Eingangsposition (``vin``), dann die Reihenfolge innerhalb
   des Eingangs — deterministisch, ohne Zufall.

**Verbraucher.** Die geordneten Lose werden der Reihe nach verbraucht von

1. allen Outputs, die das Wallet der Eingänge **verlassen** (fremde Adressen
   und andere eigene Wallets), nach ``vout`` aufsteigend;
2. der Gebühr;
3. den Outputs zurück an ein Wallet der Eingänge (Wechselgeld), nach ``vout``
   aufsteigend — sie behalten den Rest.

**Mehrere Rückflüsse.** Gehen zwei oder mehr Outputs zurück an ein Wallet der
Eingänge (tx0 mit Premix und Wechselgeld, WabiSabi mit mehreren eigenen
Outputs, Umbuchung ins selbe Wallet), laufen sie nach ``vout`` aufsteigend
durch dieselben Lose (``je_output``). Die Tx-Zeit ist dabei nie das
Anschaffungsdatum: Die Lose kommen aus den echten Eingängen.

Ein Los, das nicht ganz in einen Verbraucher passt, wird geteilt; beide Teile
behalten Zeit und Herkunft. Mit ganzzahligen sats rechnet die Verteilung exakt
(keine Rundung). Die Gebühr steht vor dem Wechselgeld: Sie verlässt das Wallet
genauso wie eine Zahlung. Weil grüne Lose älter sind als gelbe, zahlt FIFO die
Gebühr damit aus den ältesten (grünen) sats — dasselbe, was die PSBT-Vorschau
zusagt.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Hashable, Iterable

#: Sortierzeit für Lose ganz ohne Zeit (nach allen datierten).
ZEIT_UNBEKANNT = float("inf")

GEBUEHR = ("gebuehr",)


def output_schluessel(vout: int) -> tuple:
    """Schlüssel eines Outputs in ``verteilen``."""
    return ("vout", int(vout))


@dataclass(frozen=True)
class Los:
    """Ein Stück Anschaffung: *sats* mit Sortierzeit *zeit* (Unix, None = offen)."""

    sats: float
    zeit: float | None = None
    rang: tuple = ()
    marke: Any = None


def _sortier(los: Los) -> tuple:
    zeit = ZEIT_UNBEKANNT if los.zeit is None else float(los.zeit)
    return (zeit, los.rang)


def ordnen(lose: Iterable[Los]) -> list[Los]:
    """Älteste zuerst; ohne Zeit zuletzt; Gleichstand nach ``rang``."""
    return sorted((l for l in lose if l.sats > 0), key=_sortier)


def verbraucher(
    ausgaenge: Iterable[tuple[int, float, bool]],
    gebuehr: float,
) -> list[tuple[Hashable, float]]:
    """
    Verbraucher-Reihenfolge aus *(vout, sats, zurueck)*: erst die Outputs, die
    das Wallet verlassen (``zurueck`` False), nach vout; dann die Gebühr; dann
    die Rückflüsse nach vout.
    """
    liste = list(ausgaenge)
    raus = sorted((a for a in liste if not a[2]), key=lambda a: int(a[0]))
    zurueck = sorted((a for a in liste if a[2]), key=lambda a: int(a[0]))
    reihe: list[tuple[Hashable, float]] = [
        (output_schluessel(n), sats) for n, sats, _ in raus
    ]
    if gebuehr and gebuehr > 0:
        reihe.append((GEBUEHR, gebuehr))
    reihe.extend((output_schluessel(n), sats) for n, sats, _ in zurueck)
    return reihe


def verteilen(
    lose: Iterable[Los],
    reihe: Iterable[tuple[Hashable, float]],
) -> dict[Hashable, list[Los]]:
    """
    Verteilt die (schon geordneten) *lose* der Reihe nach auf die Verbraucher.

    Liefert je Verbraucher seine Lose. Reichen die Lose nicht, bekommen die
    letzten Verbraucher weniger (fehlende Eingangswerte); ein Überschuss
    bleibt unverteilt.
    """
    stapel = [l for l in lose if l.sats > 0]
    i = 0
    rest = stapel[0].sats if stapel else 0
    aus: dict[Hashable, list[Los]] = {}
    for schluessel, bedarf in reihe:
        teile = aus.setdefault(schluessel, [])
        offen = bedarf
        while offen > 0 and i < len(stapel):
            nimm = min(rest, offen)
            if nimm > 0:
                teile.append(replace(stapel[i], sats=nimm))
            offen -= nimm
            rest -= nimm
            if rest <= 0:
                i += 1
                rest = stapel[i].sats if i < len(stapel) else 0
    return aus


def je_output(
    lose: Iterable[Los],
    ausgaenge: Iterable[tuple[int, float, bool]],
    gebuehr: float,
) -> dict[Hashable, list[Los]]:
    """
    FIFO je Output.

    *ausgaenge* wie bei ``verbraucher``. Outputs, die das Wallet verlassen, und
    die Gebühr nehmen die ältesten Lose; die Rückflüsse danach, nach ``vout``
    aufsteigend — auch wenn es mehrere sind.
    """
    return verteilen(ordnen(lose), verbraucher(ausgaenge, gebuehr))


def summe(lose: Iterable[Los]) -> float:
    return sum(l.sats for l in lose)


# --- PSBT-Vorschau: Klassen statt Zeiten ------------------------------------

#: Klassen-Rang als Sortierzeit: grün ist immer älter als gelb (Fristgrenze),
#: grau (ohne Datum) kommt zuletzt — wie ``ordnen`` es mit echten Zeiten täte.
KLASSEN = ("gruen", "gelb", "grau")


def klassen_lose(inputs: Iterable[tuple[int, int, int]]) -> list[Los]:
    """
    Lose der PSBT-Inputs *(gruen, gelb, grau)* in Input-Reihenfolge. Die
    Sortierzeit ist der Klassen-Rang; Gleichstand nach Input-Position.
    """
    lose: list[Los] = []
    for pos, werte in enumerate(inputs):
        for rang, (klasse, sats) in enumerate(zip(KLASSEN, werte)):
            if int(sats or 0) > 0:
                lose.append(Los(sats=int(sats), zeit=rang, rang=(pos,), marke=klasse))
    return ordnen(lose)


def klassen_summen(lose: Iterable[Los]) -> dict[str, int]:
    """sats je Klasse (``sats_gruen``/``sats_gelb``/``sats_grau``)."""
    aus = {f"sats_{k}": 0 for k in KLASSEN}
    for l in lose:
        aus[f"sats_{l.marke}"] += int(l.sats)
    return aus
