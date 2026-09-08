"""
Sanktions- und Blacklist-Abgleich für die Oberfläche.

**Was dieser Abgleich leistet — und was nicht.**

Geprüft wird, ob eine Adresse selbst auf einer Liste steht. Das ist ein
Mengenvergleich gegen den lokalen Cache: schnell, offline, ohne jede Abfrage
nach außen.

Nicht geprüft wird damit die *Herkunft* der Sats. Ein UTXO auf einer
unauffälligen Adresse kann trotzdem aus gelisteter Quelle stammen — dafür
braucht es die Herkunftsanalyse, die jeden Zufluss einzeln verfolgt. Die
Oberfläche sagt das an jeder Stelle dazu, an der ein Ergebnis erscheint.

Ein Treffer bedeutet außerdem nicht automatisch etwas Rechtliches. Listen
enthalten Fehler, veralten und decken sich nicht zwischen Rechtsräumen.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import sanctioned

HINWEIS_UMFANG = (
    "Geprüft wird, ob eine Adresse selbst gelistet ist. Ob die Sats aus "
    "gelisteter Quelle stammen, beantwortet erst die Herkunftsanalyse."
)

HINWEIS_KEINE_RECHTSAUSKUNFT = (
    "Listen enthalten Fehler und veralten. Ein Treffer ist ein Anlass zur "
    "Prüfung, keine rechtliche Feststellung."
)

#: Hinweise der Bestandskarte.
#:
#: Dort steht, *was im Cache liegt* — geprüft wird nichts, und es gibt keinen
#: Treffer. Die beiden Sätze oben gehören deshalb ans Prüfergebnis und nicht
#: hierher; die Oberfläche zeigt sie dort auch. Erklärungsbedürftig ist an
#: dieser Stelle etwas anderes: dass die Summe der Quellen über der
#: Gesamtzahl liegen kann.
HINWEIS_MEHRFACHLISTUNG = (
    "Die Zahl je Quelle zählt deren Adressen. Dieselbe Adresse kann auf "
    "mehreren Listen stehen — die Summe liegt deshalb über der Gesamtzahl."
)

HINWEIS_LISTEN_FEHLBAR = "Listen enthalten Fehler und veralten."


@dataclass
class ListenStatus:
    """Zustand des lokalen Listen-Caches."""

    vorhanden: bool = False
    adressen: int = 0
    entitaeten: int = 0
    stand: str = ""
    quellen: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        hinweise = []
        summe = sum(q.get("adressen", 0) for q in self.quellen)
        # Nur erklären, was auch zu sehen ist: Deckt sich die Summe mit der
        # Gesamtzahl, gäbe der Hinweis eine Abweichung vor, die es nicht gibt.
        if summe > self.adressen:
            hinweise.append(HINWEIS_MEHRFACHLISTUNG)
        if self.vorhanden:
            hinweise.append(HINWEIS_LISTEN_FEHLBAR)
        return {
            "vorhanden": self.vorhanden,
            "adressen": self.adressen,
            "entitaeten": self.entitaeten,
            "stand": self.stand,
            "quellen": self.quellen,
            "hinweise": hinweise,
        }


def _quellen_aus_meta(meta: dict | None) -> list[dict]:
    """Liest die Quellenstatistik aus den Metadaten, so weit vorhanden."""
    if not isinstance(meta, dict):
        return []
    roh = meta.get("sources") or meta.get("quellen") or {}
    if isinstance(roh, dict):
        return [
            {"name": name, "adressen": _zahl(wert)}
            for name, wert in sorted(roh.items())
        ]
    if isinstance(roh, list):
        eintraege = []
        for eintrag in roh:
            if isinstance(eintrag, dict):
                eintraege.append({
                    "name": str(eintrag.get("name", eintrag.get("source", "?"))),
                    "adressen": _erste_zahl(
                        eintrag, "address_count", "count", "addresses", "adressen"
                    ),
                })
        return eintraege
    return []


def _erste_zahl(eintrag: dict, *schluessel: str) -> int:
    """
    Erste brauchbare Zahl unter mehreren Namen.

    ``sanctioned`` schreibt ``address_count``; ältere und fremde Stände nennen
    dasselbe ``count`` oder ``addresses``. Wird nur ein Name abgefragt, steht
    in der Oberfläche neben jeder Quelle eine 0, obwohl die Listen geladen
    sind — und eine 0 sieht dort aus wie „nichts gefunden".
    """
    for name in schluessel:
        if name in eintrag:
            wert = _zahl(eintrag[name])
            if wert:
                return wert
    return 0


def _zahl(wert) -> int:
    if isinstance(wert, int):
        return wert
    if isinstance(wert, dict):
        for schluessel in ("count", "addresses", "adressen", "total"):
            if isinstance(wert.get(schluessel), int):
                return wert[schluessel]
    if isinstance(wert, list):
        return len(wert)
    return 0


def _stand(meta: dict | None) -> str:
    if not isinstance(meta, dict):
        return ""
    for schluessel in ("updated_at", "fetched_at", "stand", "generated_at"):
        wert = meta.get(schluessel)
        if isinstance(wert, str) and wert:
            return wert
    return ""


def status(cache_dir: Path | None = None) -> ListenStatus:
    """Zustand der lokalen Listen — ohne Netzzugriff."""
    adressen, meta = sanctioned.load_sanctioned_xbt_addresses(cache_dir=cache_dir)
    entitaeten, entitaeten_meta = sanctioned.load_sanctioned_entities(
        cache_dir=cache_dir
    )
    return ListenStatus(
        vorhanden=bool(adressen),
        adressen=len(adressen),
        entitaeten=len(entitaeten),
        stand=_stand(meta) or _stand(entitaeten_meta),
        quellen=_quellen_aus_meta(meta),
    )


def lade_adressen(cache_dir: Path | None = None) -> frozenset[str]:
    """Die gelisteten Adressen als Menge. Leer, wenn kein Cache vorliegt."""
    adressen, _ = sanctioned.load_sanctioned_xbt_addresses(cache_dir=cache_dir)
    return adressen


def treffer_details(adresse: str, cache_dir: Path | None = None) -> dict:
    """Was der Index über eine gelistete Adresse weiß."""
    index = sanctioned.load_sanctioned_address_index(cache_dir=cache_dir)
    eintrag = index.get(adresse) or {}
    if not isinstance(eintrag, dict):
        return {}
    return {
        "person": eintrag.get("person") or eintrag.get("name") or "",
        "grund": eintrag.get("reason") or eintrag.get("grund") or "",
        "quellen": eintrag.get("sources") or eintrag.get("quellen") or [],
        "gelistet_am": eintrag.get("listed") or eintrag.get("listed_at") or "",
    }


def pruefe_adressen(
    adressen: list[str],
    *,
    cache_dir: Path | None = None,
) -> dict:
    """
    Vergleicht Adressen gegen die Listen.

    Liefert einen Befund, der auch dann eindeutig ist, wenn keine Listen
    vorliegen — „nichts gefunden“ und „nicht geprüft“ dürfen sich in der
    Anzeige nicht gleich anfühlen.
    """
    gelistet = lade_adressen(cache_dir)
    if not gelistet:
        return {
            "geprueft": False,
            "grund": "Keine Listen im Cache. Unter Einstellungen aktualisieren.",
            "treffer": [],
            "geprueft_count": 0,
        }

    treffer = []
    for adresse in dict.fromkeys(a for a in adressen if a):
        if adresse in gelistet:
            treffer.append({"address": adresse, **treffer_details(adresse, cache_dir)})

    return {
        "geprueft": True,
        "grund": "",
        "treffer": treffer,
        "geprueft_count": len(set(a for a in adressen if a)),
    }


def markiere_utxos(
    eintraege: list[dict],
    *,
    cache_dir: Path | None = None,
) -> dict:
    """
    Setzt bei jedem UTXO-Eintrag das Feld ``flagged`` und liefert den Befund.

    Verändert die übergebenen Wörterbücher an Ort und Stelle — sie stammen
    aus core.utxos und gehen direkt an die Oberfläche.
    """
    gelistet = lade_adressen(cache_dir)
    for eintrag in eintraege:
        eintrag["flagged"] = bool(gelistet) and eintrag.get("address") in gelistet

    befund = pruefe_adressen(
        [e.get("address", "") for e in eintraege], cache_dir=cache_dir
    )
    befund["flagged_count"] = sum(1 for e in eintraege if e.get("flagged"))
    befund["flagged_sats"] = sum(
        e.get("value_sats", 0) for e in eintraege if e.get("flagged")
    )
    return befund


# ---------------------------------------------------------------------------
# Ergebnis-Cache der Vorgeschichte-Prüfung
# ---------------------------------------------------------------------------
#
# Die Prüfung der externen Vorgeschichte (CLI-Menü 6.1, Web-Bereich
# „Sanktionscheck") kostet je nach Hop-Tiefe hunderte bis tausende
# get_tx-Abrufe und läuft Minuten. Sie bei jedem Seitenaufruf zu wiederholen
# wäre unzumutbar — also bleibt das letzte Ergebnis liegen und wird beim
# Öffnen der Ansicht angezeigt, sichtbar datiert.
#
# Die Datei liegt im Listen-Cache-Verzeichnis. Das ist wie die Listen selbst
# gitignoriert, und sie gehört dorthin: Sie enthält Wallet-Namen, UTXO- und
# Adressbezüge, also dieselbe Klasse von Daten wie utxo_cache/.

#: Dateiname des zuletzt gespeicherten Prüflaufs.
CHECK_ERGEBNIS_DATEI = "letzter_vorgeschichte_check.json"

#: Format der Ergebnisdatei. Ältere/neuere Stände werden verworfen statt
#: halb interpretiert — ein falsch gelesener Sanktionsbefund wäre schlimmer
#: als gar keiner.
CHECK_ERGEBNIS_VERSION = 1

#: Obergrenze für die gespeicherte Adressliste pro Wallet. Bei drei Hops
#: kommen leicht Zehntausende zusammen; die vollständige Liste würde die
#: Datei aufblähen, ohne mehr zu sagen als Anzahl plus Stichprobe.
CHECK_ADRESSEN_LIMIT = 2000


def check_ergebnis_pfad(cache_dir: Path | None) -> Path | None:
    if cache_dir is None:
        return None
    return Path(cache_dir) / CHECK_ERGEBNIS_DATEI


def check_ergebnis_laden(cache_dir: Path | None) -> dict | None:
    """
    Letztes Prüfergebnis oder None.

    Jeder Fehler — fehlende Datei, kaputtes JSON, fremde Version — führt zu
    None. Ein Sanktionsbefund, den man nicht sicher lesen kann, wird nicht
    angezeigt.
    """
    pfad = check_ergebnis_pfad(cache_dir)
    if pfad is None or not pfad.is_file():
        return None
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(daten, dict):
        return None
    if daten.get("version") != CHECK_ERGEBNIS_VERSION:
        return None
    return daten


def check_ergebnis_speichern(cache_dir: Path | None, ergebnis: dict) -> bool:
    """
    Schreibt das Ergebnis atomar. Rückgabe: ob geschrieben wurde.

    Ein fehlgeschlagener Cache-Schreibvorgang darf den Prüflauf nicht
    entwerten — das Ergebnis steht dem Aufrufer ja bereits zur Verfügung.
    """
    pfad = check_ergebnis_pfad(cache_dir)
    if pfad is None:
        return False
    nutzlast = dict(ergebnis)
    nutzlast["version"] = CHECK_ERGEBNIS_VERSION
    tmp = pfad.with_suffix(".tmp")
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(nutzlast, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(pfad)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def check_ergebnis_verwerfen(cache_dir: Path | None) -> bool:
    """Gespeichertes Ergebnis löschen. Rückgabe: ob eine Datei wegfiel."""
    pfad = check_ergebnis_pfad(cache_dir)
    if pfad is None or not pfad.is_file():
        return False
    try:
        pfad.unlink()
        return True
    except OSError:
        return False
