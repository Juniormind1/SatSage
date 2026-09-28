"""
Herkunftsnetz als Overlay im Steuerjahr-Zeitstrahl (ISSUES: Steuerjahr ·
Herkunftsnetz als Overlay, Schritt 1).

Aus dem **einen** gespeicherten Herkunftsbaum eines UTXO wird ein flaches
Netz für die Oberfläche: eigene Vorfahren als Knoten, Kanten mit dem
Sat-Anteil am gewählten Output. Der Baum selbst geht nicht an den Browser
(Lazy-Tree-Invariante); ``zeitstrahl()`` und seine ``events[]`` bleiben
unberührt — das Netz ist ein ephemerer Zusatz.

X der Knoten ist die **Output-Zeit** des Hops (Blockzeit aus der Höhe über
den ``block_header``-Cache, sonst die im Baum abgelegte Blockzeit) — auf
derselben 0..100-Skala wie ``core.tax.zeitstrahl``. Y ist dieselbe
log1p-Skala. Beides wird hier nicht geklemmt: Vorfahren dürfen älter als
der Achsenbeginn und größer als das Skalenende sein; die Oberfläche setzt
sie an den Rand.

Anteile: Jeder Hop verteilt seinen Anteil anteilig (pro rata) auf die
aufgelösten Eingänge seiner Erzeuger-Tx. So summieren sich die Kanten in
einen Knoten zu dessen Anteil am gewählten Output.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from core.tax import _minus_monate, _y_log_prozent
from core.trace import FULL_RESOLUTION_INPUT_LIMIT
from core.tx_classify import COINJOIN_KINDS

#: Obergrenze eindeutiger Knoten — darüber werden weitere Eingänge zu je
#: einem Bündel „n Eingänge“ (kein Haarnetz, auch bei tiefen Bäumen).
MAX_KNOTEN = 600

TYP_EIGEN = "eigen"
TYP_HORIZONT = "horizont"
TYP_FREMD = "fremd"
TYP_COINBASE = "coinbase"
TYP_BUENDEL = "buendel"
TYP_LUECKE = "luecke"

_BLOCK_RE = re.compile(r"Block\s+([\d.,]+)")
_DATUM_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?")


@dataclass(frozen=True)
class Skala:
    """Dieselbe X/Y-Abbildung wie ``core.tax.zeitstrahl``."""

    von: datetime
    bis: datetime
    hoechst: int

    def pos(self, zeitpunkt: datetime) -> float:
        """X in % — ungeklemmt (vor dem Achsenbeginn negativ)."""
        spanne = (self.bis - self.von).total_seconds()
        return round((zeitpunkt - self.von).total_seconds() / spanne * 100, 3)

    def y(self, sats: int) -> float:
        return _y_log_prozent(int(sats), self.hoechst)


def skala_aus_auswertung(auswertung: dict) -> Skala | None:
    """
    Rekonstruiert die Zeitstrahl-Skala aus einer Steuer-Auswertung.

    Wie ``zeitstrahl()``: Beginn 6 Monate vor dem ältesten Eingang, Ende
    beim jüngsten Eingang oder dem Bezugstag (``bezug_ts``), was später
    liegt; Y-Ende ist ``max_sats``. Ohne Zeitstrahl: ``None``.
    """
    strahl = auswertung.get("zeitstrahl") or {}
    events = strahl.get("events") or []
    if not strahl.get("vorhanden") or not events:
        return None
    zeiten = [
        datetime.fromtimestamp(int(e["time_ts"]))
        for e in events if e.get("time_ts") is not None
    ]
    if not zeiten:
        return None
    von = _minus_monate(min(zeiten), 6)
    bis = max(zeiten)
    bezug = auswertung.get("bezug_ts")
    if bezug is not None:
        bis = max(bis, datetime.fromtimestamp(float(bezug)))
    if (bis - von).total_seconds() <= 0:
        bis = von + timedelta(days=180)
    return Skala(von=von, bis=bis, hoechst=int(strahl.get("max_sats") or 1))


def output_zeit(
    knoten: dict, block_zeit: Callable[[int], int | None] | None = None,
) -> datetime | None:
    """
    Output-Zeit eines Baumknotens.

    Reihenfolge: Blockhöhe (Feld oder „Block N“ im Label) → ``block_header``-
    Cache; sonst ``block_time``/``time_ts`` des Knotens; sonst das Datum im
    ``time_label``. Ohne jede Zeit: ``None``.
    """
    label = str(knoten.get("time_label") or "")
    hoehe = knoten.get("block_height")
    if not hoehe:
        treffer = _BLOCK_RE.search(label)
        if treffer:
            try:
                hoehe = int(re.sub(r"[.,]", "", treffer.group(1)))
            except ValueError:
                hoehe = None
    if hoehe and block_zeit is not None:
        try:
            ts = block_zeit(int(hoehe))
        except Exception:
            ts = None
        if ts:
            return datetime.fromtimestamp(int(ts))
    for feld in ("block_time", "time_ts"):
        wert = knoten.get(feld)
        if wert:
            try:
                return datetime.fromtimestamp(int(wert))
            except (TypeError, ValueError, OverflowError, OSError):
                pass
    treffer = _DATUM_RE.search(label)
    if treffer:
        t, m, j, hh, mm, ss = treffer.groups()
        try:
            return datetime(
                int(j), int(m), int(t), int(hh or 0), int(mm or 0), int(ss or 0),
            )
        except ValueError:
            return None
    return None


def _typ(knoten: dict) -> str:
    typ = knoten.get("type")
    if typ == "internal":
        return TYP_HORIZONT if knoten.get("tax_horizon") else TYP_EIGEN
    if typ == "tax_horizon":
        return TYP_HORIZONT
    if typ == "external":
        return TYP_FREMD
    if typ == "coinbase":
        return TYP_COINBASE
    return TYP_LUECKE


def _schluessel(knoten: dict, typ: str, eltern: str, nummer: int) -> str:
    herkunft = str(knoten.get("from_utxo") or "").strip()
    if typ in (TYP_EIGEN, TYP_HORIZONT) and herkunft:
        return herkunft
    if typ == TYP_FREMD:
        return herkunft or f"fremd:{eltern}:{nummer}"
    if typ == TYP_COINBASE:
        return f"coinbase:{eltern}"
    return f"{knoten.get('type') or 'luecke'}:{herkunft or eltern}"


def _buendeln(eltern: dict, kinder: list[dict]) -> bool:
    """CoinJoin, Sammel-Tx über dem Auflöse-Limit oder abgebrochene Auflösung."""
    if str(eltern.get("tx_class") or "") in COINJOIN_KINDS:
        return True
    if len(kinder) > FULL_RESOLUTION_INPUT_LIMIT:
        return True
    return any(k.get("type") == "external_unresolved" for k in kinder)


def flach(
    baum: dict,
    fokus_key: str,
    skala: Skala,
    *,
    block_zeit: Callable[[int], int | None] | None = None,
    max_knoten: int = MAX_KNOTEN,
) -> dict:
    """
    Flaches Herkunftsnetz des Fokus-UTXO aus dem gespeicherten UI-Baum.

    ``vorfahren`` enthält den Fokus selbst (``tiefe`` 0, Layer B an seiner
    Output-Zeit) und alle Vorfahren; ``kanten`` laufen vom Eingang (``von``)
    zum Output, den er mitfinanziert (``nach``). ``sats`` ist der Anteil am
    Fokus-Output. Fremd/Coinbase/Bündel/Horizont sind Endknoten (``ende``).
    """
    wurzel = dict(baum.get("root") or {})
    wurzel["children"] = baum.get("children") or []
    fokus_sats = int(wurzel.get("amount_sats") or 0)

    knoten: dict[str, dict] = {}
    kanten: dict[tuple[str, str], float] = {}
    reihenfolge: list[str] = []

    def zeitfelder(zeit: datetime | None) -> dict:
        if zeit is None:
            return {"pos_output": None, "zeit": ""}
        return {
            "pos_output": skala.pos(zeit),
            "zeit": zeit.strftime("%d.%m.%Y %H:%M"),
        }

    def neu(key: str, eintrag: dict, anteil: float) -> None:
        if key in knoten:
            alt = knoten[key]
            alt["anteil_sats"] += anteil
            alt["tiefe"] = min(alt["tiefe"], eintrag["tiefe"])
            return
        eintrag["anteil_sats"] = anteil
        knoten[key] = eintrag
        reihenfolge.append(key)

    def kante(von: str, nach: str, sats: float, eigen: bool) -> None:
        schluessel = (von, nach)
        kanten[schluessel] = kanten.get(schluessel, 0.0) + sats
        eigen_kante[schluessel] = eigen_kante.get(schluessel, True) and eigen

    eigen_kante: dict[tuple[str, str], bool] = {}

    zeit0 = output_zeit(wurzel, block_zeit)
    neu(fokus_key, {
        "key": fokus_key,
        "typ": TYP_EIGEN,
        "value_sats": fokus_sats,
        "y": skala.y(fokus_sats),
        "wallet": wurzel.get("wallet") or "",
        "eigen": True,
        "ende": not wurzel["children"],
        "tiefe": 0,
        "n": 0,
        **zeitfelder(zeit0),
    }, float(fokus_sats))

    gekappt = False
    schlange: deque = deque([(wurzel, fokus_key, float(fokus_sats), 0)])
    while schlange:
        eltern, eltern_key, anteil, tiefe = schlange.popleft()
        kinder = [k for k in (eltern.get("children") or []) if isinstance(k, dict)]
        if not kinder:
            continue
        voll = len(knoten) >= max_knoten
        gekappt = gekappt or (voll and not _buendeln(eltern, kinder))
        if voll or _buendeln(eltern, kinder):
            _buendel(
                kinder, eltern_key, anteil, tiefe + 1,
                neu=neu, kante=kante, zeitfelder=zeitfelder, skala=skala,
                block_zeit=block_zeit,
            )
            continue
        summe = sum(int(k.get("amount_sats") or 0) for k in kinder)
        for nummer, kind in enumerate(kinder):
            typ = _typ(kind)
            key = _schluessel(kind, typ, eltern_key, nummer)
            if key == eltern_key:
                # Marker-Blatt am Hop selbst (Steuer-Horizont, Zyklus, …):
                # kein eigener Knoten, der Hop endet hier.
                knoten[key]["ende"] = True
                knoten[key]["abbruch"] = typ
                continue
            sats = int(kind.get("amount_sats") or 0)
            teil = (
                anteil * sats / summe if summe > 0 else anteil / len(kinder)
            )
            eigen = typ in (TYP_EIGEN, TYP_HORIZONT)
            enkel = kind.get("children") or []
            ende = typ != TYP_EIGEN or not enkel
            neu(key, {
                "key": key,
                "typ": typ,
                "value_sats": sats,
                "y": skala.y(sats),
                "wallet": kind.get("wallet") or "",
                "eigen": eigen,
                "ende": ende,
                "tiefe": tiefe + 1,
                "n": 0,
                **zeitfelder(output_zeit(kind, block_zeit)),
            }, teil)
            kante(key, eltern_key, teil, eigen)
            if typ == TYP_EIGEN and enkel:
                schlange.append((kind, key, teil, tiefe + 1))

    vorfahren = []
    for key in reihenfolge:
        eintrag = knoten[key]
        eintrag["anteil_sats"] = int(round(eintrag["anteil_sats"]))
        vorfahren.append(eintrag)
    return {
        "fokus_key": fokus_key,
        "fokus_sats": fokus_sats,
        "vorfahren": vorfahren,
        "kanten": [
            {
                "von": von,
                "nach": nach,
                "sats": int(round(sats)),
                "eigen": bool(eigen_kante.get((von, nach))),
            }
            for (von, nach), sats in kanten.items()
        ],
        "gekappt": gekappt,
    }


def _buendel(
    kinder, eltern_key, anteil, tiefe, *, neu, kante, zeitfelder, skala, block_zeit,
) -> None:
    """Alle Eingänge eines Hops als ein Endknoten „n Eingänge“."""
    anzahl = 0
    sats = 0
    eigen = False
    zeiten: list[datetime] = []
    for kind in kinder:
        if kind.get("type") == "external_unresolved":
            anzahl += int(kind.get("input_count") or 0)
            continue
        anzahl += 1
        sats += int(kind.get("amount_sats") or 0)
        eigen = eigen or _typ(kind) in (TYP_EIGEN, TYP_HORIZONT)
        zeit = output_zeit(kind, block_zeit)
        if zeit is not None:
            zeiten.append(zeit)
    key = f"buendel:{eltern_key}"
    # X: jüngste bekannte Output-Zeit im Bündel (die defensiv maßgebliche).
    felder = zeitfelder(max(zeiten) if zeiten else None)
    if zeiten:
        felder["zeit_von"] = min(zeiten).strftime("%d.%m.%Y %H:%M")
    neu(key, {
        "key": key,
        "typ": TYP_BUENDEL,
        "value_sats": sats,
        "y": skala.y(sats),
        "wallet": "",
        "eigen": eigen,
        "ende": True,
        "tiefe": tiefe,
        "n": anzahl,
        **felder,
    }, anteil)
    kante(key, eltern_key, anteil, eigen)
