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
    """
    ziel = pfad(txid, vout, immutable_cache_dir)
    if ziel is None or not baum or not baum.get("found"):
        return None

    nutzlast = {
        "version": VERSION,
        "txid": main._normalize_txid(txid),
        "vout": int(vout),
        "erstellt_ts": int(time.time()),
        "adressen_fingerprint": fingerabdruck(adressen),
        "adressen_anzahl": len(adressen) if adressen else 0,
        "baum": baum,
    }

    if not main.cache_disk_write_allowed(ziel.parent):
        return None

    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        tmp = ziel.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(nutzlast, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(ziel)
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


def baum_ist_vollstaendig(baum: dict | None) -> bool:
    """
    Alle Sats enden an einer fremden Adresse oder als Coinbase (rot/lila).

    Unaufgelöste Sammel-Eingänge, leere interne Blätter, Zyklen und Fehler
    machen den Baum unvollständig — auch wenn irgendwo schon externe Enden
    existieren. „Irgendwo external_count > 0“ genügt nicht: CoinJoin-Bäume
    können hunderte grüne Blätter ohne Kinder haben und trotzdem externe
    Zähler > 0 führen.
    """
    if not baum or not baum.get("found"):
        return False
    z = baum.get("summary") or {}
    if int(z.get("unresolved_inputs") or 0) > 0:
        return False
    return _blaetter_ohne_luecke(baum.get("children") or [])


def _blaetter_ohne_luecke(knoten: list) -> bool:
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


def kopf(
    txid: str,
    vout: int,
    immutable_cache_dir: Path | str | None,
    adressen=None,
) -> dict | None:
    """
    Nur die Angaben *über* den Baum: wann erhoben, noch aktuell, vollständig?

    Für Listen gedacht, die je Eintrag eine Markierung brauchen, aber keinen
    Baum. Der Rückgabewert hält den Baum nicht fest — bei vielen UTXOs bleibt
    so nur die Kopfzeile im Speicher, nicht die gesamte Vorgeschichte.
    """
    geladen = laden(txid, vout, immutable_cache_dir, adressen)
    if geladen is None:
        return None
    # Veraltet (neue Adressen) ändert nicht, ob jeder Sat außen endet.
    # Die Unsicherheit steht an der Marke „verfolgt"; die jüngsten Sats
    # trotzdem zeigen, sonst wirkt ein vollständiger Baum in der Liste leer.
    baum = geladen["baum"]
    vollstaendig = baum_ist_vollstaendig(baum)
    mix_arten = mix_arten_im_baum(baum)
    root = baum.get("root") if isinstance(baum, dict) else None
    tx_class = ""
    if isinstance(root, dict):
        tx_class = str(root.get("tx_class") or "")
    if not tx_class:
        tx_class = str(baum.get("tx_class") or "") if isinstance(baum, dict) else ""
    return {
        "erstellt_ts": geladen["erstellt_ts"],
        "veraltet": geladen["veraltet"],
        "adressen_seither": geladen["adressen_seither"],
        "vollstaendig": vollstaendig,
        "mix_arten": mix_arten,
        "tx_class": tx_class,
    }
