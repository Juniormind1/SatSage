"""
Lange Listen seitenweise: sortieren und filtern auf Rohfeldern, anreichern
nur, was im Fenster steht (ISSUES P2).

Die Reihenfolge ist dieselbe wie bisher im Browser: erst die Server-Sortierung
(``betrag``/``datum``, Adressgruppen wie ``utxos.group_by_address``), dann der
Anzeigemodus der Oberfläche (``volume-desc`` = Gruppen nach Bestand,
``age-desc``/``age-asc`` = flache UTXO-Liste nach Alter, ``gruppen`` = Gruppen
wie geliefert). Der Stichwortfilter ist eine 1:1-Portierung von
``parseKopfFilter``/``_kopfFilterAdressGruppe``/``kopfFilterLabelText`` aus
``web/app.js`` bzw. ``web/api.js`` — damit er über alle Seiten wirkt statt nur
auf der gezeichneten.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from core import utxo_report

#: Größen des Seitenumschalters (Oberfläche: 10, 20, 50, 100).
SEITEN_GROESSEN = (10, 20, 50, 100)
MAX_LIMIT = 400

# --- Kopien aus web/api.js ------------------------------------------------

MIX_ICON_ORDER = ("whirlpool", "wasabi_classic", "wabisabi", "joinmarket", "bisq_payout")
MIX_ICON_KURZ = {
    "whirlpool": "Whirlpool",
    "wasabi_classic": "Wasabi",
    "wabisabi": "WabiSabi",
    "joinmarket": "JoinMarket",
    "bisq_payout": "Bisq",
}
_TX_CLASS_ICON = frozenset((
    "whirlpool", "wasabi_classic", "wabisabi", "joinmarket", "bisq_payout", "bisq_deposit",
))

_LOCALES = Path(__file__).resolve().parent.parent / "web" / "locales"
_katalog_cache: dict[str, tuple[float, dict]] = {}


def _katalog(lang: str) -> dict:
    """Sprachdatei der Oberfläche — dieselben Texte wie ``t()`` im Browser."""
    code = "en" if str(lang or "").lower().startswith("en") else "de"
    pfad = _LOCALES / f"{code}.json"
    try:
        mtime = pfad.stat().st_mtime
    except OSError:
        return {}
    alt = _katalog_cache.get(code)
    if alt and alt[0] == mtime:
        return alt[1]
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        daten = {}
    _katalog_cache[code] = (mtime, daten)
    return daten


def _js_wahr(wert) -> bool:
    """JavaScript-Wahrheitswert (leere Liste/Objekt sind wahr)."""
    if isinstance(wert, (list, dict)):
        return True
    return bool(wert)


def soft_tx_class_label(obj: dict, lang: str) -> str:
    """Port von ``softTxClassLabel``."""
    if not obj:
        return ""
    kind = obj.get("tx_class") or ""
    if not kind or kind == "unknown":
        return ""
    en = str(lang or "").lower().startswith("en")
    if kind == "exchange_batch":
        roh = obj.get("boerse_namen")
        namen = [n for n in roh if n] if isinstance(roh, list) else []
        if namen:
            liste = ", ".join(str(n) for n in namen)
            return f"incl. payout from {liste}" if en else f"u. a. Auszahlung von {liste}"
        backend = (
            (obj.get("tx_class_label_en") or obj.get("tx_class_label") or "")
            if en else (obj.get("tx_class_label") or "")
        )
        if backend:
            return backend
    uebersetzt = _katalog(lang).get(f"trace.txClass.{kind}")
    if uebersetzt:
        return uebersetzt
    return obj.get("tx_class_label") or obj.get("note") or ""


def _icon_art(kind) -> str:
    k = "bisq_payout" if kind == "bisq_deposit" else (kind or "")
    return k if k in _TX_CLASS_ICON else ""


def mix_arten_der_gruppe(gruppe: dict) -> list[str]:
    gesehen: set[str] = set()
    for u in gruppe.get("utxos") or []:
        for k in u.get("mix_arten") or []:
            if _icon_art(k):
                gesehen.add(_icon_art(k))
        if _icon_art(u.get("tx_class")):
            gesehen.add(_icon_art(u.get("tx_class")))
    return [k for k in MIX_ICON_ORDER if k in gesehen]


def boerse_namen_der_gruppe(gruppe: dict) -> list[str]:
    namen = {str(n) for u in gruppe.get("utxos") or [] for n in (u.get("boerse_namen") or []) if n}
    return sorted(namen, key=str.casefold)


def _boerse_name_aus_label(lab) -> str:
    if not isinstance(lab, dict):
        return ""
    name = str(lab.get("name") or "").strip()
    if not name:
        return ""
    if lab.get("kategorie") == "exchange" or lab.get("nutzer_import"):
        return name
    if lab.get("kategorie_label") == "Börse" or lab.get("quelle") == "Börsen-CSV":
        return name
    return ""


def filter_label_text(obj: dict, lang: str) -> str:
    """Port von ``kopfFilterLabelText`` (UTXO oder Adressgruppe)."""
    if not isinstance(obj, dict):
        return ""
    teile: list[str] = []
    mix = obj.get("mix_arten")
    if not _js_wahr(mix):
        mix = mix_arten_der_gruppe(obj) if _js_wahr(obj.get("utxos")) else []
    for k in mix or []:
        if not k:
            continue
        teile += [str(k), MIX_ICON_KURZ.get(k, ""), soft_tx_class_label({"tx_class": k}, lang)]
    txc = obj.get("tx_class")
    if txc:
        teile += [str(txc), MIX_ICON_KURZ.get(txc, ""), soft_tx_class_label({"tx_class": txc}, lang)]
    boerse = obj.get("boerse_namen")
    if not _js_wahr(boerse) and _js_wahr(obj.get("utxos")):
        boerse = boerse_namen_der_gruppe(obj)
    for n in boerse or []:
        if n:
            teile.append(str(n))
    for ziel in obj.get("exchange_spends") or []:
        name = str((ziel or {}).get("name") or "").strip() if isinstance(ziel, dict) else ""
        if name:
            teile.append(name)
    ein = _boerse_name_aus_label(obj.get("label")) or _boerse_name_aus_label(obj.get("exchange_label"))
    if ein:
        teile.append(ein)
    return " ".join(t for t in teile if t)


# --- Filter ---------------------------------------------------------------

_RE_DATUM = re.compile(r"^([<>])(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$")
_RE_SATS = re.compile(r"^([<>])(\d+(?:[.,]\d+)?)$")


def _datum_lokal(dd: str, mm: str, yy: str) -> datetime | None:
    try:
        tag, monat, jahr = int(dd), int(mm), int(yy)
    except ValueError:
        return None
    if len(yy) <= 2:
        jahr += 2000
    if not (1 <= monat <= 12 and 1 <= tag <= 31):
        return None
    try:
        return datetime(jahr, monat, tag)
    except ValueError:
        return None


def parse_filter(roh: str, *, nach_ts=None, vor_ts=None) -> dict:
    """
    Port von ``parseKopfFilter``: Freitext + ``>1234``/``<1234`` (sats) +
    ``>1.1.25``/``<05.12.2023`` (Datum), mehrere Tokens = UND.

    Datumsgrenzen hängen an der Zeitzone des Browsers. Er schickt sie als
    ``nach_ts``/``vor_ts`` mit; ohne sie rechnet der Server in seiner Zeit.
    """
    text = str(roh or "").strip()
    f = {"leer": not text, "terms": [], "min_sats": None, "max_sats": None,
         "after_ts": None, "before_ts": None}
    if not text:
        return f
    for tok in text.split():
        dm = _RE_DATUM.match(tok)
        if dm:
            start = _datum_lokal(dm.group(2), dm.group(3), dm.group(4))
            if start:
                if dm.group(1) == ">":
                    ts = int((start + timedelta(days=1)).timestamp())
                    f["after_ts"] = ts if f["after_ts"] is None else max(f["after_ts"], ts)
                else:
                    ts = int(start.timestamp())
                    f["before_ts"] = ts if f["before_ts"] is None else min(f["before_ts"], ts)
            continue
        sm = _RE_SATS.match(tok)
        if sm:
            n = float(sm.group(2).replace(",", "."))
            if sm.group(1) == ">":
                f["min_sats"] = n if f["min_sats"] is None else max(f["min_sats"], n)
            else:
                f["max_sats"] = n if f["max_sats"] is None else min(f["max_sats"], n)
            continue
        f["terms"].append(tok.lower())
    for feld, wert in (("after_ts", nach_ts), ("before_ts", vor_ts)):
        if wert not in (None, ""):
            try:
                f[feld] = int(float(wert))
            except (TypeError, ValueError):
                pass
    return f


def filter_aus_query(query: dict) -> dict:
    def eins(name):
        return (query.get(name) or [""])[0]
    return parse_filter(eins("q"), nach_ts=eins("q_nach") or None, vor_ts=eins("q_vor") or None)


def _nur_datum_betrag(f: dict) -> bool:
    return (f["min_sats"] is None and f["max_sats"] is None
            and f["after_ts"] is None and f["before_ts"] is None)


# --- Einheitlicher Zugriff auf Roh- und angereicherte Einträge -------------

def _status(e: dict) -> dict:
    s = e.get("status")
    return s if isinstance(s, dict) else {}


def _fertig(e: dict) -> bool:
    return "value_sats" in e


def wert(e: dict) -> int:
    return int((e.get("value_sats") if _fertig(e) else e.get("value")) or 0)


def schluessel(e: dict) -> str:
    if e.get("key"):
        return str(e["key"])
    return f"{e.get('txid', '')}:{int(e.get('vout', 0) or 0)}"


def hoehe(e: dict) -> int:
    return int((e.get("block_height") if _fertig(e) else _status(e).get("block_height")) or 0)


def blockzeit(e: dict) -> int:
    return int((e.get("block_time") if _fertig(e) else _status(e).get("block_time")) or 0)


def _eintrag_zeit(e: dict) -> int:
    return int(e.get("spent_time_ts") or blockzeit(e) or 0)


def zeit_label(e: dict) -> str:
    if _fertig(e):
        return str(e.get("time_label") or "")
    label = utxo_report._format_utxo_status(e)
    if label.startswith("Block ") and " · " in label:
        label = label.split(" · ", 1)[1]
    return label


_RE_ZEIT = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")


def ereignis_ts(e: dict) -> int:
    """Port von ``utxoEreignisTs`` (Ausgabe bevorzugt, sonst Ankunft)."""
    if e.get("spent") or e.get("spent_pending"):
        st = int(e.get("spent_time_ts") or e.get("spent_block_time")
                 or _status(e).get("spent_time_ts") or 0)
        if st > 0:
            return st
    bt = blockzeit(e)
    if bt > 0:
        return bt
    m = _RE_ZEIT.search(zeit_label(e))
    if m:
        jahr = int(m.group(3)) + (2000 if len(m.group(3)) <= 2 else 0)
        try:
            return int(datetime(jahr, int(m.group(2)), int(m.group(1)), int(m.group(4) or 0),
                                int(m.group(5) or 0), int(m.group(6) or 0)).timestamp())
        except ValueError:
            pass
    return int(e.get("juengste_sats_ts") or 0)


# --- Reihenfolge ----------------------------------------------------------

def sortiere_basis(eintraege: list[dict], sort: str, *, art: str) -> list[dict]:
    """Server-Sortierung wie ``rank_wallet_utxos`` (bestand) / ``historische_eintraege`` (verlauf)."""
    if art == "verlauf":
        if sort == "betrag":
            return sorted(eintraege, key=wert, reverse=True)
        return sorted(eintraege, key=lambda e: e.get("spent_time_ts") or 0, reverse=True)
    if sort == "datum":
        return sorted(eintraege, key=lambda e: (
            0 if (e.get("receive_pending") or e.get("spending_pending")) else 1, -blockzeit(e)))
    return sorted(eintraege, key=wert, reverse=True)


def gruppiere(eintraege: list[dict], sort: str) -> list[dict]:
    """Wie ``utxos.group_by_address``, nur auf Roh- oder Mischeinträgen."""
    gruppen: dict[str, dict] = {}
    for e in eintraege:
        adresse = e.get("address", "") or ""
        g = gruppen.setdefault(adresse, {"address": adresse, "total_sats": 0, "utxos": []})
        if not e.get("spending_pending"):
            g["total_sats"] += wert(e)
        g["utxos"].append(e)
    ergebnis = list(gruppen.values())
    for g in ergebnis:
        if sort == "datum":
            g["utxos"].sort(key=_eintrag_zeit, reverse=True)
        else:
            g["utxos"].sort(key=wert, reverse=True)
        zeiten = [_eintrag_zeit(e) for e in g["utxos"] if _eintrag_zeit(e)]
        g["last_seen"] = max(zeiten) if zeiten else None
    if sort == "datum":
        ergebnis.sort(key=lambda g: g.get("last_seen") or 0, reverse=True)
    else:
        ergebnis.sort(key=lambda g: g["total_sats"], reverse=True)
    return ergebnis


def _alter_hoehe(e: dict) -> int:
    return int(e.get("spent_block_height") or hoehe(e) or 0)


def _alter_ts(e: dict) -> int:
    return int(e.get("spent_time_ts") or e.get("spent_block_time") or blockzeit(e) or 0)


def ist_gruppen_modus(modus: str) -> bool:
    return modus in ("gruppen", "volume-desc")


def ordne(gruppen: list[dict], modus: str) -> list:
    """Anzeigemodus der Oberfläche (``fuelleTraceSortiert``)."""
    if modus == "gruppen":
        return list(gruppen)
    if modus == "volume-desc":
        return sorted(gruppen, key=lambda g: g["total_sats"], reverse=True)
    alle = [e for g in gruppen for e in g["utxos"]]
    if modus == "age-desc":
        return sorted(alle, key=lambda e: (-_alter_hoehe(e), -_alter_ts(e)))
    if modus == "age-asc":
        return sorted(alle, key=lambda e: (_alter_hoehe(e), _alter_ts(e)))
    return sorted(alle, key=wert, reverse=True)


# --- Fenster --------------------------------------------------------------

#: Felder, aus denen ``filter_label_text`` (auch über Gruppen) liest.
_LABEL_FELDER = ("mix_arten", "tx_class", "boerse_namen", "label", "exchange_label")


def label_auszug(voll: dict) -> dict:
    """Kleiner Auszug eines angereicherten Eintrags nur für den Stichwortfilter."""
    aus = {k: voll[k] for k in _LABEL_FELDER if k in voll}
    ziele = voll.get("exchange_spends")
    if ziele:
        aus["exchange_spends"] = [
            {"name": z.get("name")} if isinstance(z, dict) else z for z in ziele
        ]
    elif "exchange_spends" in voll:
        aus["exchange_spends"] = ziele
    return aus


# --- Kleine Fenster-Caches (ISSUES P2, Schritt 6) --------------------------

def datei_abdruck(*, dateien=(), ordner=()) -> str:
    """
    Abdruck für Cache-Gültigkeit aus Datei-Zeitstempeln — ohne Inhalte zu lesen.

    *dateien*: Verzeichnisse, deren Dateien (eine Ebene) einzeln zählen
    (Name, mtime, Größe) — für kleine Ordner wie den UTXO-/Verlaufs-Cache.
    *ordner*: große Verzeichnisse, deren eigener mtime genügt, weil dort
    nur per ``tmp.replace`` geschrieben wird (jede Änderung ändert den Ordner).
    """
    h = hashlib.sha256()
    for pfad in dateien:
        if not pfad:
            continue
        try:
            with os.scandir(pfad) as it:
                teile = sorted(
                    (e.name, e.stat().st_mtime_ns, e.stat().st_size)
                    for e in it if e.is_file()
                )
        except OSError:
            teile = []
        h.update(repr((str(pfad), teile)).encode("utf-8"))
    for pfad in ordner:
        if not pfad:
            continue
        try:
            st = os.stat(pfad)
            h.update(repr((str(pfad), st.st_mtime_ns)).encode("utf-8"))
        except OSError:
            h.update(repr((str(pfad), None)).encode("utf-8"))
    return h.hexdigest()


class KleinCache:
    """Winziger LRU-Cache (wenige Einträge) mit Lock — für Fenster-Ergebnisse."""

    def __init__(self, groesse: int = 2):
        self._groesse = max(1, int(groesse))
        self._daten: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def hole(self, schluessel):
        with self._lock:
            if schluessel not in self._daten:
                return None
            self._daten.move_to_end(schluessel)
            return self._daten[schluessel]

    def lege(self, schluessel, wert) -> None:
        with self._lock:
            self._daten[schluessel] = wert
            self._daten.move_to_end(schluessel)
            while len(self._daten) > self._groesse:
                self._daten.popitem(last=False)

    def lege_ausser_wenn(self, schluessel, wert, behalten) -> bool:
        """Legt *wert*, außer *behalten(bisher)* ist wahr. True wenn gelegt."""
        with self._lock:
            alt = self._daten.get(schluessel)
            if alt is not None and behalten(alt):
                self._daten.move_to_end(schluessel)
                return False
            self._daten[schluessel] = wert
            self._daten.move_to_end(schluessel)
            while len(self._daten) > self._groesse:
                self._daten.popitem(last=False)
            return True

    def leeren(self) -> None:
        with self._lock:
            self._daten.clear()


class Fenster:
    """
    Sortiert, filtert und schneidet eine Liste; reichert nur an, was nötig ist.

    *anreichern(roh) -> dict* liefert den Eintrag in der Form der Oberfläche
    (``utxo_as_dict`` bzw. Verlaufsform). Bereits angereicherte Einträge
    (Mempool-Pending) werden unverändert übernommen. Angereichert wird je
    Anfrage höchstens einmal pro Eintrag.
    """

    def __init__(self, anreichern: Callable[[dict], dict], *, lang: str = "de",
                 label_cache: dict | None = None):
        self._anreichern = anreichern
        self._fertig: dict[int, dict] = {}
        self.lang = lang
        # Label-Auszug je ``txid:vout`` über Anfragen hinweg (Stichwortsuche);
        # gültig, solange der Abdruck der Caches gleich bleibt (Aufrufer).
        self._label_cache = label_cache

    def label_quelle(self, e: dict) -> dict:
        """
        Was ``filter_label_text`` von einem Eintrag liest — aus dem Label-Cache
        oder einmal angereichert. Ergebnis wie mit dem vollen Eintrag.
        """
        if self._label_cache is None or _fertig(e):
            return self.fertig(e)
        key = schluessel(e)
        schon = self._label_cache.get(key)
        if schon is None:
            schon = label_auszug(self.fertig(e))
            self._label_cache[key] = schon
        return schon

    def fertig(self, e: dict) -> dict:
        if _fertig(e):
            return e
        schon = self._fertig.get(id(e))
        if schon is None:
            schon = self._anreichern(e)
            self._fertig[id(e)] = schon
        return schon

    def _text_ok(self, heu: str, terms: list[str]) -> bool:
        return all(t in heu for t in terms)

    def blatt_ok(self, e: dict, f: dict, *, text_schon_ok: bool = False) -> bool:
        """Port von ``_kopfFilterLeafOk``."""
        sats = wert(e)
        if f["min_sats"] is not None and not sats > f["min_sats"]:
            return False
        if f["max_sats"] is not None and not sats < f["max_sats"]:
            return False
        if f["after_ts"] is not None or f["before_ts"] is not None:
            ts = ereignis_ts(e)
            if ts <= 0 and not _fertig(e):
                ts = ereignis_ts(self.fertig(e))
            if ts <= 0:
                return False
            if f["after_ts"] is not None and not ts >= f["after_ts"]:
                return False
            if f["before_ts"] is not None and not ts < f["before_ts"]:
                return False
        if text_schon_ok or not f["terms"]:
            return True
        key = schluessel(e)
        ausgabe = str(e.get("spent_txid") or e.get("abgang_txid") or "")
        roh = " ".join([
            key, key.split(":")[0], str(e.get("address") or ""), zeit_label(e), ausgabe,
        ]).lower()
        if self._text_ok(roh, f["terms"]):
            return True
        # Labels (Mix-Formen, Börsen, Ausgabe-Ziele) gibt es erst angereichert.
        voll = self.label_quelle(e)
        if not ausgabe:
            ausgabe = str(voll.get("spent_txid") or voll.get("abgang_txid") or "")
        heu = roh + " " + filter_label_text(voll, self.lang).lower() + " " + ausgabe.lower()
        return self._text_ok(heu, f["terms"])

    def gruppe_ok(self, g: dict, f: dict) -> bool:
        """Port von ``_kopfFilterAdressGruppe``: sichtbar, wenn ein Blatt passt."""
        text_ok = not f["terms"]
        if not text_ok:
            heu = str(g.get("address") or "").lower()
            text_ok = self._text_ok(heu, f["terms"])
            if not text_ok:
                voll = {"utxos": [self.label_quelle(e) for e in g["utxos"]]}
                heu += " " + filter_label_text(voll, self.lang).lower()
                text_ok = self._text_ok(heu, f["terms"])
        if not g["utxos"]:
            return text_ok and _nur_datum_betrag(f)
        return any(self.blatt_ok(e, f, text_schon_ok=text_ok) for e in g["utxos"])

    def schneide(self, eintraege: list[dict], *, sort: str, art: str, modus: str,
                 f: dict, offset: int, limit: int, vorab: list[dict] | None = None) -> dict:
        """
        Liefert ``{"items": [...], "total": n, "art": "gruppen"|"utxos"}``.

        *vorab*: schon angereicherte Einträge, die vor der Sortierung vorne
        stehen (Mempool-Pending im Verlauf, wie ``merge_pending_spends_in_verlauf``).
        """
        basis = sortiere_basis(eintraege, sort, art=art)
        if vorab:
            gesehen = {schluessel(v) for v in vorab}
            basis = list(vorab) + [e for e in basis if schluessel(e) not in gesehen]
        gruppen = gruppiere(basis, sort)
        geordnet = ordne(gruppen, modus)
        gruppen_art = ist_gruppen_modus(modus)
        if not f["leer"]:
            if gruppen_art:
                geordnet = [g for g in geordnet if self.gruppe_ok(g, f)]
            else:
                geordnet = [e for e in geordnet if self.blatt_ok(e, f)]
        offset = max(0, int(offset or 0))
        limit = max(0, min(int(limit or 0), MAX_LIMIT))
        fenster = geordnet[offset:offset + limit]
        return {"items": fenster, "total": len(geordnet),
                "art": "gruppen" if gruppen_art else "utxos"}


def query_int(query: dict, name: str, default: int = 0) -> int:
    try:
        return int((query.get(name) or [default])[0])
    except (TypeError, ValueError):
        return default


def query_text(query: dict, name: str, default: str = "") -> str:
    return str((query.get(name) or [default])[0] or default)
