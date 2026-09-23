"""
Gespeicherte Herkunftsbäume.

Die Vorgeschichte eines bestätigten Outputs ändert sich nie. Ein einmal
gebauter Baum bleibt deshalb gültig und muss beim nächsten Seitenaufruf nicht
neu erhoben werden — das spart den Job, die Node-Verbindung und den Walk.

**Warum ein eigener Cache neben ``utxo_ingress``.** Dort liegt die
Zusammenfassung, die die Steuerauswertung braucht: rund ein Dutzend Felder je
UTXO. ``core.tax`` liest jede dieser Dateien bei jeder Berechnung. Läge der
Baum daneben, würde die Steuerauswertung dauerhaft ein Vielfaches an Daten
laden, das sie nie anfasst — bei CoinJoin-Historie sehr viel mehr. Getrennte
Dateien halten sie schlank.

**Die eine Einschränkung.** Ob ein Zweig als *intern* oder *extern* gilt,
hängt davon ab, welche Adressen als eigene bekannt sind. Kommt ein XPUB dazu
oder reicht ein Scan tiefer, kann aus einem externen Zufluss ein interner
werden — und damit verschiebt sich das Anschaffungsdatum. Der Baum wird
deshalb mit einem Fingerabdruck der Adressmenge abgelegt.

Weicht der Abdruck beim Laden ab, wird der Baum trotzdem geliefert, aber als
``veraltet`` gekennzeichnet. Verwerfen wäre Datenverlust für einen Verdacht;
die Oberfläche schreibt die Unsicherheit an den Baum und bietet an, ihn neu
zu verfolgen.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import main
from core import xpub_cache

#: Unterverzeichnis im Immutable-Cache.
UNTERVERZEICHNIS = "utxo_trace"

#: Format der Dateien. Fremde Stände werden verworfen statt halb gelesen —
#: ein falsch interpretierter Herkunftsbaum wäre schlimmer als gar keiner.
VERSION = 1


def fingerabdruck(adressen) -> str:
    """
    Kurzer, stabiler Abdruck einer Adressmenge.

    Sortiert, damit die Reihenfolge im Set keine Rolle spielt. Eine leere
    Menge hat bewusst keinen Abdruck: „keine Adressen bekannt" ist keine
    Aussage über die Adressen, sondern ihr Fehlen.
    """
    if not adressen:
        return ""
    roh = "\n".join(sorted(adressen)).encode("utf-8")
    return hashlib.sha256(roh).hexdigest()[:32]


def verzeichnis(immutable_cache_dir: Path | str | None) -> Path | None:
    if not immutable_cache_dir:
        return None
    return Path(immutable_cache_dir) / UNTERVERZEICHNIS


def pfad(txid: str, vout: int, immutable_cache_dir: Path | str | None) -> Path | None:
    ordner = verzeichnis(immutable_cache_dir)
    if ordner is None:
        return None
    return ordner / f"{main._normalize_txid(txid)}_{int(vout)}.json"


def meta_pfad(
    txid: str, vout: int, immutable_cache_dir: Path | str | None,
) -> Path | None:
    """Kleine Kopf-Datei für Listen — ohne den vollen Baum zu parsen."""
    ordner = verzeichnis(immutable_cache_dir)
    if ordner is None:
        return None
    return ordner / f"{main._normalize_txid(txid)}_{int(vout)}.meta.json"


#: Sanktions-Hop-Walk (xpub-blind) — Graph/Adressen; Liste wird neu gematcht.
#: v2: zusätzlich ``coinjoins`` (Form-Heuristik je Hop-Tx).
SANKTION_WALK_VERSION = 2


def sanction_walk_pfad(
    txid: str, vout: int, immutable_cache_dir: Path | str | None,
) -> Path | None:
    """Neben dem Herkunftsbaum: Hop-Walk für Sanktionscheck."""
    ordner = verzeichnis(immutable_cache_dir)
    if ordner is None:
        return None
    return ordner / f"{main._normalize_txid(txid)}_{int(vout)}.sanction_walk.json"


def sanction_walk_laden(
    txid: str,
    vout: int,
    immutable_cache_dir: Path | str | None,
) -> dict | None:
    """
    Gespeicherter xpub-blinder Hop-Walk.

    Liefert ``{max_hops, complete, events, coinjoins}`` oder None. Events =
    Adress-Hops (Graph); die aktuelle Sanktionsliste wird beim Lesen neu
    gematcht. ``coinjoins`` = Form-Hinweise (Wasabi/Whirlpool/…) im Fenster.
    """
    ziel = sanction_walk_pfad(txid, vout, immutable_cache_dir)
    if ziel is None or not ziel.is_file():
        return None
    try:
        daten = json.loads(ziel.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(daten, dict) or daten.get("version") != SANKTION_WALK_VERSION:
        return None
    if daten.get("txid") != main._normalize_txid(txid):
        return None
    if int(daten.get("vout", -1)) != int(vout):
        return None
    events = daten.get("events")
    if not isinstance(events, list):
        return None
    coinjoins = daten.get("coinjoins")
    if coinjoins is None:
        coinjoins = []
    if not isinstance(coinjoins, list):
        return None
    try:
        max_hops = int(daten.get("max_hops") or 0)
    except (TypeError, ValueError):
        return None
    return {
        "max_hops": max_hops,
        "complete": bool(daten.get("complete")),
        "events": events,
        "coinjoins": coinjoins,
    }


def sanction_walk_speichern(
    txid: str,
    vout: int,
    *,
    max_hops: int,
    complete: bool,
    events: list,
    immutable_cache_dir: Path | str | None,
    coinjoins: list | None = None,
) -> Path | None:
    """Schreibt den Hop-Walk neben dem Herkunftsbaum."""
    ziel = sanction_walk_pfad(txid, vout, immutable_cache_dir)
    if ziel is None:
        return None
    if not xpub_cache.cache_disk_write_allowed(ziel.parent):
        return None
    nutzlast = {
        "version": SANKTION_WALK_VERSION,
        "txid": main._normalize_txid(txid),
        "vout": int(vout),
        "erstellt_ts": int(time.time()),
        "max_hops": int(max_hops),
        "complete": bool(complete),
        "events": list(events or []),
        "coinjoins": list(coinjoins or []),
    }
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        tmp = ziel.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(nutzlast, ensure_ascii=False), encoding="utf-8")
        tmp.replace(ziel)
    except OSError:
        return None
    return ziel


def origin_tree_laden(
    txid: str,
    vout: int,
    immutable_cache_dir: Path | str | None,
) -> dict | None:
    """Roh-Herkunftsbaum (``origin_tree``), falls vorhanden."""
    geladen = laden(txid, vout, immutable_cache_dir, adressen=None)
    if not geladen:
        return None
    baum = geladen.get("baum")
    if not isinstance(baum, dict):
        return None
    origin = baum.get("origin_tree")
    return origin if isinstance(origin, dict) else None


def _tx_class_aus_baum(baum: dict | None) -> str:
    if not isinstance(baum, dict):
        return ""
    root = baum.get("root")
    if isinstance(root, dict):
        tc = str(root.get("tx_class") or "")
        if tc:
            return tc
    return str(baum.get("tx_class") or "")


def _schreibe_meta(
    ziel_meta: Path,
    *,
    txid: str,
    vout: int,
    erstellt_ts: int,
    adressen_fingerprint: str,
    adressen_anzahl: int,
    baum: dict,
) -> None:
    """Sidecar mit Listenkopf — kopf() liest nur diese Datei."""
    nutzlast = {
        "version": VERSION,
        "txid": main._normalize_txid(txid),
        "vout": int(vout),
        "erstellt_ts": int(erstellt_ts),
        "adressen_fingerprint": adressen_fingerprint or "",
        "adressen_anzahl": int(adressen_anzahl or 0),
        "vollstaendig": bool(baum_ist_vollstaendig(baum)),
        "steuer_ausreichend": bool(baum_ist_steuer_ausreichend(baum)),
        "mix_arten": mix_arten_im_baum(baum),
        "boerse_namen": boerse_namen_im_baum(baum),
        "tx_class": _tx_class_aus_baum(baum),
    }
    tmp = ziel_meta.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(nutzlast, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ziel_meta)


def speichern(
    txid: str,
    vout: int,
    baum: dict | None,
    immutable_cache_dir: Path | str | None,
    adressen=None,
) -> Path | None:
    """
    Legt einen Baum ab. Rückgabe: der Pfad, oder None wenn nichts geschrieben.

    Ohne Verzeichnis wird nichts geschrieben — ein Trace zum bloßen Ansehen
    soll keine Spuren hinterlassen. Erfolglose Analysen ebenfalls nicht: Ein
    gespeichertes „nicht gefunden" würde beim nächsten Aufruf einen Fehler
    zeigen, statt es noch einmal zu versuchen.

    Zusätzlich ``.meta.json``: Listenkopf (vollständig/Mix) ohne Baum-Parse.
    """
    ziel = pfad(txid, vout, immutable_cache_dir)
    if ziel is None or not baum or not baum.get("found"):
        return None

    fp = fingerabdruck(adressen)
    n_addr = len(adressen) if adressen else 0
    erstellt = int(time.time())
    nutzlast = {
        "version": VERSION,
        "txid": main._normalize_txid(txid),
        "vout": int(vout),
        "erstellt_ts": erstellt,
        "adressen_fingerprint": fp,
        "adressen_anzahl": n_addr,
        "baum": baum,
    }

    if not xpub_cache.cache_disk_write_allowed(ziel.parent):
        return None

    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        tmp = ziel.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(nutzlast, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(ziel)
        meta = meta_pfad(txid, vout, immutable_cache_dir)
        if meta is not None:
            try:
                _schreibe_meta(
                    meta,
                    txid=txid,
                    vout=vout,
                    erstellt_ts=erstellt,
                    adressen_fingerprint=fp,
                    adressen_anzahl=n_addr,
                    baum=baum,
                )
            except OSError:
                pass
    except OSError:
        return None
    return ziel


def laden(
    txid: str,
    vout: int,
    immutable_cache_dir: Path | str | None,
    adressen=None,
) -> dict | None:
    """
    Holt einen gespeicherten Baum.

    Liefert ``{baum, erstellt_ts, veraltet, adressen_seither}`` oder None.
    Jeder Zweifel — fehlende Datei, kaputtes JSON, fremde Version, falsches
    Ziel — führt zu None: lieber neu verfolgen als etwas Falsches zeigen.

    *veraltet* meldet, dass sich die Adressmenge seit der Analyse geändert
    hat. Ohne übergebene Adressmenge bleibt die Angabe leer — wer die eigenen
    Adressen nicht kennt, kann weder „aktuell" noch „veraltet" behaupten.
    """
    quelle = pfad(txid, vout, immutable_cache_dir)
    if quelle is None or not quelle.is_file():
        return None

    try:
        daten = json.loads(quelle.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(daten, dict) or daten.get("version") != VERSION:
        return None
    if daten.get("txid") != main._normalize_txid(txid):
        return None
    if int(daten.get("vout", -1)) != int(vout):
        return None
    baum = daten.get("baum")
    if not isinstance(baum, dict):
        return None

    veraltet = False
    seither = None
    if adressen:
        gespeichert = daten.get("adressen_fingerprint") or ""
        veraltet = bool(gespeichert) and gespeichert != fingerabdruck(adressen)
        seither = len(adressen) - int(daten.get("adressen_anzahl", 0) or 0)

    return {
        "baum": baum,
        "erstellt_ts": int(daten.get("erstellt_ts", 0) or 0),
        "veraltet": veraltet,
        "adressen_seither": seither,
    }


def vorhanden(
    txid: str,
    vout: int,
    immutable_cache_dir: Path | str | None,
) -> bool:
    """Ob ein Baum abgelegt ist — ohne ihn zu lesen."""
    ziel = pfad(txid, vout, immutable_cache_dir)
    return bool(ziel and ziel.is_file())


def loeschen(
    txid: str,
    vout: int,
    immutable_cache_dir: Path | str | None,
) -> bool:
    """
    Entfernt Herkunftsbaum + Meta (z. B. vor erzwungenem „Scan neu“).

    Lässt Sanktions-Walk unberührt. Rückgabe True wenn mindestens eine
    Datei weg war.
    """
    geloescht = False
    for ziel in (
        pfad(txid, vout, immutable_cache_dir),
        meta_pfad(txid, vout, immutable_cache_dir),
    ):
        if ziel is None or not ziel.is_file():
            continue
        try:
            ziel.unlink()
            geloescht = True
        except OSError:
            pass
    return geloescht


def baum_ist_vollstaendig(baum: dict | None) -> bool:
    """
    Alle Sats enden an einer fremden Adresse oder als Coinbase (rot/lila).

    Unaufgelöste Sammel-Eingänge, leere interne Blätter, Zyklen und Fehler
    machen den Baum unvollständig — auch wenn irgendwo schon externe Enden
    existieren. „Irgendwo external_count > 0“ genügt nicht: CoinJoin-Bäume
    können hunderte grüne Blätter ohne Kinder haben und trotzdem externe
    Zähler > 0 führen.

    Steuer-Horizont-Blätter (``tax_horizon``) zählen **nicht** — Herkunft
    tracen muss sie noch bis extern/Coinbase nachziehen.
    """
    if not baum or not baum.get("found"):
        return False
    z = baum.get("summary") or {}
    if int(z.get("unresolved_inputs") or 0) > 0:
        return False
    return _blaetter_ohne_luecke(
        baum.get("children") or [], erlaube_tax_horizon=False,
    )


def baum_ist_steuer_ausreichend(baum: dict | None) -> bool:
    """
    Fürs Steuerjahr reicht extern/Coinbase **oder** Horizont vor
    Stichtag/Haltefrist-Anfang. Voller Graph bis Coinbase ist optional.
    """
    if not baum or not baum.get("found"):
        return False
    z = baum.get("summary") or {}
    if int(z.get("unresolved_inputs") or 0) > 0:
        return False
    if baum.get("tax_horizon") or (baum.get("root") or {}).get("tax_horizon"):
        kinder = baum.get("children") or []
        if not kinder:
            return True
    if baum_ist_vollstaendig(baum):
        return True
    return _blaetter_ohne_luecke(
        baum.get("children") or [], erlaube_tax_horizon=True,
    )


def _blaetter_ohne_luecke(knoten: list, *, erlaube_tax_horizon: bool = False) -> bool:
    """Jedes Blatt muss external oder coinbase sein — sonst Lücke."""
    if not knoten:
        return False
    stapel = list(knoten)
    hat_ende = False
    while stapel:
        aktuell = stapel.pop()
        if not isinstance(aktuell, dict):
            return False
        kinder = aktuell.get("children") or []
        if kinder:
            stapel.extend(kinder)
            continue
        typ = aktuell.get("type")
        if typ in ("external", "coinbase"):
            hat_ende = True
            continue
        if erlaube_tax_horizon and (
            typ == "tax_horizon" or aktuell.get("tax_horizon")
        ):
            hat_ende = True
            continue
        # Börsen-CSV-Grenze: absichtliches Ende an Ein-/Auszahlung.
        if aktuell.get("exchange_stop"):
            hat_ende = True
            continue
        # CoinJoin: absichtlich nur eigene Ins — Blatt mit Soft-Label und
        # ohne Peer-Externals zählt als abgeschlossenes Mix-Ende, nicht als Lücke.
        if aktuell.get("coinjoin_noise_skipped") and aktuell.get("tx_class"):
            hat_ende = True
            continue
        if (
            typ == "internal"
            and aktuell.get("tx_class")
            and aktuell.get("coinjoin_noise_skipped")
        ):
            hat_ende = True
            continue
        # internal ohne Kinder, external_unresolved, cycle, error, unknown, …
        return False
    return hat_ende


#: Mix-Arten mit UI-Icon — Reihenfolge = Anzeige an der Adressgruppe.
MIX_ICON_KINDS = (
    "whirlpool",
    "wasabi_classic",
    "wabisabi",
    "joinmarket",
)
_MIX_ICON_SET = frozenset(MIX_ICON_KINDS)


def mix_arten_im_baum(baum: dict | None) -> list[str]:
    """
    Eindeutige Mix-Formen im gespeicherten Herkunftsbaum (nur Icon-Arten).

    Läuft über denselben Baum, den ``kopf`` ohnehin lädt — kein Extra-I/O.
    """
    if not isinstance(baum, dict):
        return []
    gefunden: set[str] = set()
    stapel: list = []
    root = baum.get("root")
    if isinstance(root, dict):
        stapel.append(root)
    stapel.extend(baum.get("children") or [])
    # Auch Top-Level-Feld (ältere/kompakte Speicherung).
    top = baum.get("tx_class")
    if top in _MIX_ICON_SET:
        gefunden.add(str(top))
    while stapel:
        knoten = stapel.pop()
        if not isinstance(knoten, dict):
            continue
        kind = knoten.get("tx_class")
        if kind in _MIX_ICON_SET:
            gefunden.add(str(kind))
        kinder = knoten.get("children") or []
        if kinder:
            stapel.extend(kinder)
    return [k for k in MIX_ICON_KINDS if k in gefunden]


def _boerse_name_aus_label(lab: object) -> str:
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


def boerse_namen_im_baum(baum: dict | None) -> list[str]:
    """Eindeutige Börsen-Namen (Kraken/Coinbase/…) aus Labels im Herkunftsbaum."""
    if not isinstance(baum, dict):
        return []
    gefunden: set[str] = set()
    stapel: list = []
    root = baum.get("root")
    if isinstance(root, dict):
        stapel.append(root)
    stapel.extend(baum.get("children") or [])
    while stapel:
        knoten = stapel.pop()
        if not isinstance(knoten, dict):
            continue
        for lab in (knoten.get("label"), knoten.get("exchange_label")):
            n = _boerse_name_aus_label(lab)
            if n:
                gefunden.add(n)
        for src in knoten.get("sources") or []:
            if not isinstance(src, dict):
                continue
            for lab in (src.get("label"), src.get("exchange_label")):
                n = _boerse_name_aus_label(lab)
                if n:
                    gefunden.add(n)
        kinder = knoten.get("children") or []
        if kinder:
            stapel.extend(kinder)
    return sorted(gefunden)


def kopf(
    txid: str,
    vout: int,
    immutable_cache_dir: Path | str | None,
    adressen=None,
) -> dict | None:
    """
    Nur die Angaben *über* den Baum: wann erhoben, noch aktuell, vollständig?

    Für Listen gedacht, die je Eintrag eine Markierung brauchen, aber keinen
    Baum. Liest bevorzugt die kleine ``.meta.json`` (kein Baum-Parse) —
    sonst Fallback auf volle Datei + einmaliges Meta-Nachziehen.
    """
    meta_ziel = meta_pfad(txid, vout, immutable_cache_dir)
    if meta_ziel is not None and meta_ziel.is_file():
        try:
            daten = json.loads(meta_ziel.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            daten = None
        if (
            isinstance(daten, dict)
            and daten.get("version") == VERSION
            and daten.get("txid") == main._normalize_txid(txid)
            and int(daten.get("vout", -1)) == int(vout)
            and "vollstaendig" in daten
        ):
            veraltet = False
            seither = None
            if adressen:
                gespeichert = daten.get("adressen_fingerprint") or ""
                veraltet = bool(gespeichert) and gespeichert != fingerabdruck(
                    adressen
                )
                seither = len(adressen) - int(
                    daten.get("adressen_anzahl", 0) or 0
                )
            voll = bool(daten.get("vollstaendig"))
            # Alt-Meta ohne Flag: voll ⇒ auch steuerlich ok.
            if "steuer_ausreichend" in daten:
                steuer_ok = bool(daten.get("steuer_ausreichend"))
            else:
                steuer_ok = voll
            return {
                "erstellt_ts": int(daten.get("erstellt_ts", 0) or 0),
                "veraltet": veraltet,
                "adressen_seither": seither,
                "vollstaendig": voll,
                "steuer_ausreichend": steuer_ok,
                "mix_arten": list(daten.get("mix_arten") or []),
                "boerse_namen": list(daten.get("boerse_namen") or []),
                "tx_class": str(daten.get("tx_class") or ""),
            }

    geladen = laden(txid, vout, immutable_cache_dir, adressen)
    if geladen is None:
        return None
    # Veraltet (neue Adressen) ändert nicht, ob jeder Sat außen endet.
    baum = geladen["baum"]
    vollstaendig = baum_ist_vollstaendig(baum)
    steuer_ok = baum_ist_steuer_ausreichend(baum)
    mix_arten = mix_arten_im_baum(baum)
    boerse_namen = boerse_namen_im_baum(baum)
    tx_class = _tx_class_aus_baum(baum)
    # Alte Caches: Meta nachziehen, damit der nächste Listen-Lauf billig bleibt.
    if meta_ziel is not None:
        try:
            quelle = pfad(txid, vout, immutable_cache_dir)
            fp = ""
            n_addr = 0
            if quelle and quelle.is_file():
                try:
                    roh = json.loads(quelle.read_text(encoding="utf-8"))
                    fp = str(roh.get("adressen_fingerprint") or "")
                    n_addr = int(roh.get("adressen_anzahl", 0) or 0)
                except (OSError, ValueError, TypeError):
                    pass
            if xpub_cache.cache_disk_write_allowed(meta_ziel.parent):
                _schreibe_meta(
                    meta_ziel,
                    txid=txid,
                    vout=vout,
                    erstellt_ts=geladen["erstellt_ts"],
                    adressen_fingerprint=fp,
                    adressen_anzahl=n_addr,
                    baum=baum,
                )
        except OSError:
            pass
    return {
        "erstellt_ts": geladen["erstellt_ts"],
        "veraltet": geladen["veraltet"],
        "adressen_seither": geladen["adressen_seither"],
        "vollstaendig": vollstaendig,
        "steuer_ausreichend": steuer_ok,
        "mix_arten": mix_arten,
        "boerse_namen": boerse_namen,
        "tx_class": tx_class,
    }
