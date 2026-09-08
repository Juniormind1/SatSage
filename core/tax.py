"""
Steuerjahr: Haltefristen, Stichtage und Export.

**Was diese Auswertung abdeckt — und was nicht.**

Zwei Grundlagen sind möglich, und die Auswertung sagt jeweils, welche gilt:

*Mit Verlauf* (``main.resolve_wallet_verlauf``, Feld ``spent`` je Eintrag)
sind alle je empfangenen Outputs erfasst — auch längst ausgegebene. Dann
trennt die Auswertung, was am Stichtag noch im Bestand lag, von dem, was im
Jahr abgegangen ist. Erst damit wird die *Veräußerung* sichtbar, und die ist
nach § 23 EStG der maßgebliche Vorgang.

*Ohne Verlauf* bleiben nur die aktuell unverbrauchten UTXOs aus dem lokalen
Cache. Ein inzwischen ausgegebenes UTXO steht dort nicht mehr; für
zurückliegende Steuerjahre ist die Auswertung dann eine Bestandsaufnahme des
heutigen Guthabens. Der Vorbehalt steht in diesem Fall in Oberfläche und
Export.

Keine Steuerberatung. Die Zahlen sind ein Hilfsmittel und vor jeder
Verwendung selbst zu prüfen. Der kanonische Absatz steht in
``HINWEIS_ONCHAIN`` — Oberfläche, Exporte und Doku zitieren denselben
Wortlaut.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import main

#: Übliche Haltefrist nach § 23 EStG (private Veräußerungsgeschäfte, DE).
STANDARD_HALTEFRIST_JAHRE = 1

#: Österreich: Altbestand bis einschließlich 28.02.2021 (BMF, ökosoziale
#: Steuerreform). Anschaffungen danach sind Neuvermögen — Halten macht sie
#: nicht steuerfrei. Nicht die Vorgabe: ohne gesetzten Stichtag gilt die
#: Haltefrist für alle Anschaffungen.
OESTERREICH_ALTBESTAND = date(2021, 2, 28)

#: Vorgabe: keine Stichtagsregel.
STANDARD_STICHTAG = None

#: Auswahl in den Einstellungen: 1…n Jahre plus „keine“.
HALTEFRIST_MAX_JAHRE = 20

#: Anschaffungsdatum aus Herkunft: defensiv (jüngster externer Zufluss) oder
#: offensiv (ältester). Default bleibt defensiv.
ANSCHAFFUNG_JUENGSTE = "juengste"
ANSCHAFFUNG_AELTESTE = "aelteste"
ANSCHAFFUNG_MODI = (ANSCHAFFUNG_JUENGSTE, ANSCHAFFUNG_AELTESTE)
STANDARD_ANSCHAFFUNG = ANSCHAFFUNG_JUENGSTE

#: Einmaliger Bestätigungs-Merker in der .env (diese Installation).
ENV_HINWEIS_ONCHAIN_BESTAETIGT = "HINWEIS_ONCHAIN_BESTAETIGT"

# Der eine Absatz. UI, Exporte, Handbuch und README zitieren denselben Wortlaut.
HINWEIS_ONCHAIN = (
    "SatSage rekonstruiert aus der Blockchain, wann Sats diese "
    "Wallet-Adressen erreicht oder verlassen haben. Das ist ein "
    "On-Chain-Beleg, kein vollständiger Anschaffungsnachweis. "
    "Börsenhistorien, Kaufbelege, Kontoauszüge und ähnliche Unterlagen "
    "ersetzt das nicht — es kann sie nur ergänzen. Ob ein Stichtag oder "
    "eine Haltefrist greift, prüft nicht dieses Programm."
)

HINWEIS_KEINE_BERATUNG = (
    "Diese Aufstellung ist keine Steuerberatung. " + HINWEIS_ONCHAIN
)


def hinweis_onchain_bestaetigt(werte: dict[str, str] | None) -> bool:
    """Ob der On-Chain-Hinweis auf dieser Installation bestätigt wurde."""
    roh = (werte or {}).get(ENV_HINWEIS_ONCHAIN_BESTAETIGT, "").strip().lower()
    return roh in ("1", "true", "ja", "yes", "on")


HINWEIS_UMFANG = (
    "Erfasst sind ausschließlich zum Erstellungszeitpunkt unverbrauchte "
    "UTXOs. Bereits ausgegebene Beträge sind nicht enthalten; für "
    "zurückliegende Jahre ist die Aufstellung deshalb keine lückenlose "
    "Historie."
)


def parse_stichtag(wert: str | None) -> date | None:
    """Liest TT.MM.JJJJ oder JJJJ-MM-TT. Leer ist „keine Stichtagsregel“."""
    text = (wert or "").strip()
    if not text:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Stichtag unlesbar: {wert!r} (TT.MM.JJJJ)")


def format_stichtag(tag: date | None) -> str:
    if tag is None:
        return ""
    return tag.strftime("%d.%m.%Y")


def parse_anschaffung(roh: str | None) -> str:
    """``juengste`` (Default) oder ``aelteste``; Unbekanntes → Default."""
    wert = (roh or "").strip().lower()
    if wert in ANSCHAFFUNG_MODI:
        return wert
    return STANDARD_ANSCHAFFUNG


def lese_steuer_einstellungen(werte: dict[str, str] | None) -> dict:
    """
    Haltefrist, Stichtag und Anschaffungslesart aus der .env.

    Fehlt der Stichtag oder ist er leer, gilt die Haltefrist für alle
    Anschaffungen (Deutschland). Ein gesetztes Datum ist eine Cutoff-Regel
    wie der österreichische Altbestand.

    *anschaffung*: ``juengste`` = defensiv (Default), ``aelteste`` = offensiv.
    """
    werte = werte or {}
    roh_frist = werte.get("STEUER_HALTEFRIST_JAHRE", "").strip()
    if roh_frist == "":
        frist = STANDARD_HALTEFRIST_JAHRE
    else:
        try:
            frist = max(0, min(HALTEFRIST_MAX_JAHRE, int(roh_frist)))
        except ValueError:
            frist = STANDARD_HALTEFRIST_JAHRE

    stichtag = parse_stichtag(werte.get("STEUER_STICHTAG"))
    anschaffung = parse_anschaffung(werte.get("STEUER_ANSCHAFFUNG"))

    return {
        "haltefrist_jahre": frist,
        "stichtag": format_stichtag(stichtag),
        "stichtag_iso": stichtag.isoformat() if stichtag else "",
        "haltefrist_jahre_auswahl": list(range(1, HALTEFRIST_MAX_JAHRE + 1)),
        "anschaffung": anschaffung,
        "anschaffung_auswahl": list(ANSCHAFFUNG_MODI),
    }


def haltefrist_entscheidung(
    anschaffung: datetime,
    bezug: datetime,
    haltefrist_jahre: int,
    stichtag: date | None,
) -> tuple[datetime | None, bool, bool]:
    """
    Ob die Haltefrist an diesem Bezugstag erfüllt ist.

    Liefert ``(frist_ende, erfuellt, neuvermoegen)``.

    *stichtag*: Anschaffungen **danach** (österr. Neuvermögen) werden nicht
    durch Halten steuerfrei. Ohne Stichtag gilt die Frist für alle.
    """
    neu = bool(stichtag and anschaffung.date() > stichtag)
    if haltefrist_jahre <= 0:
        return None, True, neu
    if neu:
        return None, False, True
    ende = plus_jahre(anschaffung, haltefrist_jahre)
    return ende, ende <= bezug, False


def plus_jahre(zeitpunkt: datetime, jahre: int) -> datetime:
    """
    Addiert Jahre. Der 29. Februar wird auf den 28. gelegt, weil das Zieljahr
    kein Schaltjahr sein muss.
    """
    try:
        return zeitpunkt.replace(year=zeitpunkt.year + jahre)
    except ValueError:
        return zeitpunkt.replace(year=zeitpunkt.year + jahre, day=28)


def stichtag(jahr: int) -> datetime:
    """Ende des Steuerjahres: 31.12. um 23:59:59."""
    return datetime(jahr, 12, 31, 23, 59, 59)


def bezugsdatum(jahr: int, jetzt: datetime | None = None) -> tuple[datetime, bool]:
    """
    Der Zeitpunkt, gegen den Haltefristen gerechnet werden.

    Für abgeschlossene Jahre ist das der 31.12. — der Rückblick auf das Jahr.
    Für das **laufende** Jahr ist es der heutige Tag, denn sonst gälten
    Beträge schon als fristerfüllt, deren Jahr erst später abläuft. Wer danach
    entscheidet, was er heute verkaufen kann, bekäme zu viel angezeigt.

    Liefert *(zeitpunkt, laeuft_noch)*.
    """
    ende = stichtag(jahr)
    jetzt = jetzt or datetime.now()
    if jetzt < ende:
        return jetzt, True
    return ende, False


#: Grundlage, auf der das Anschaffungsdatum eines UTXO beruht.
GRUNDLAGE_HERKUNFT = "herkunft"   # jüngster externer Zufluss — steuerlich richtig
#: Herkunftsanalyse liegt vor, aber ohne datierte externe Zuflüsse (die
#: Datenquelle liefert keine Blockzeiten der Vorgänger). Rückfall auf den
#: jüngsten Wallet-Eingang.
GRUNDLAGE_WALLET_EINGANG = "wallet_eingang"
GRUNDLAGE_OUTPUT = "output"       # nur das Entstehungsdatum des Outputs

HINWEIS_UNGEPRUEFT = (
    "Für UTXOs ohne Herkunftsanalyse gilt das Entstehungsdatum des Outputs. "
    "Bei Wechselgeld, Konsolidierungen und Eigenüberträgen ist das zu jung — "
    "die Coins gehörten vorher schon dazu. Die Haltefrist wird dort also "
    "**unterschätzt**, nie überschätzt. Betroffene Zeilen sind als „nur "
    "Output-Datum“ gekennzeichnet; eine Herkunftsanalyse korrigiert sie."
)

HINWEIS_UNTERGRENZE = (
    "Bei einigen UTXOs konnten nicht alle externen Vorgänger aufgelöst "
    "werden (Sammel-Transaktion mit sehr vielen Eingängen). Das ausgewiesene "
    "Anschaffungsdatum ist dort eine Untergrenze — die tatsächliche "
    "Anschaffung kann jünger sein, die Haltefrist also kürzer. Betroffene "
    "Zeilen sind als „Untergrenze“ gekennzeichnet."
)

HINWEIS_OFFENSIV = (
    "Anschaffungsdatum aus Herkunft: **offensiv** (ältester externer "
    "Zufluss). Das kann eine längere Haltedauer ausweisen als die defensive "
    "Lesart (jüngster Zufluss). Bei unvollständigem Baum ist das besonders "
    "riskant — betroffene Zeilen bleiben gekennzeichnet."
)

HINWEIS_OFFENSIV_OHNE_AELTESTE = (
    "Für den offensiven Modus fehlt bei manchen UTXOs das älteste "
    "Zuflussdatum im Cache (ältere Herkunftsläufe). Dort gilt vorübergehend "
    "der jüngste bekannte Zufluss — Herkunft erneut tracen, um Offensiv "
    "korrekt zu füllen."
)

HINWEIS_WALLET_EINGANG = (
    "Bei einigen UTXOs liegt eine Herkunftsanalyse vor, die Datenquelle "
    "liefert aber keine Blockzeiten der externen Vorgänger. Dort gilt der "
    "jüngste Wallet-Eingang: Bei Eigenüberträgen ist der zu jung, die "
    "Haltefrist wird also **unterschätzt**, nie überschätzt. Ein eigener "
    "Fulcrum liefert das genaue Datum. Betroffene Zeilen sind als „nur "
    "Wallet-Eingang“ gekennzeichnet."
)


HINWEIS_MIT_VERLAUF = (
    "Grundlage ist der vollständige Verlauf der Wallet-Adressen: erfasst sind "
    "auch Beträge, die inzwischen ausgegeben wurden. Abgänge des Jahres sind "
    "getrennt ausgewiesen."
)


def _hat_verlauf(utxos: list[dict]) -> bool:
    """
    Liegen Verlaufsdaten vor?

    Entscheidend ist das Vorhandensein des Schlüssels, nicht sein Wert: Ein
    Eintrag mit ``spent: False`` ist eine Aussage („nicht ausgegeben"), ein
    fehlender Schlüssel keine.
    """
    return any("spent" in utxo for utxo in utxos)


def _grundlage_label(
    grundlage: str,
    untergrenze: bool = False,
    *,
    anschaffung: str = STANDARD_ANSCHAFFUNG,
    offensiv_fallback: bool = False,
) -> str:
    """
    Worauf das Anschaffungsdatum beruht — in Worten.

    Als Funktion und nicht nur als Eigenschaft am Eingang: Die Veräußerungen
    im Export brauchen dieselbe Beschriftung, und zwei Fassungen desselben
    Textes gehen früher oder später auseinander.
    """
    if grundlage == GRUNDLAGE_HERKUNFT:
        if anschaffung == ANSCHAFFUNG_AELTESTE:
            basis = "Herkunft verfolgt (offensiv, älteste)"
            if offensiv_fallback:
                basis = "Herkunft verfolgt (offensiv, Fallback jüngste)"
        else:
            basis = "Herkunft verfolgt"
        if untergrenze:
            return f"{basis} (Untergrenze)"
        return basis
    if grundlage == GRUNDLAGE_WALLET_EINGANG:
        return "Herkunft verfolgt (nur Wallet-Eingang)"
    return "nur Output-Datum"


HINWEIS_EIGENUEBERTRAG = (
    "{anzahl} Vorgang/Vorgänge waren Eigenüberträge — Aufteilen, "
    "Zusammenlegen oder Umschichten zwischen eigenen Adressen. Sie sind keine "
    "Veräußerung und deshalb nicht aufgeführt; abgeflossen ist dort nur die "
    "Netzwerkgebühr."
)


def _abgang_je_transaktion(utxos: list[dict]) -> dict[str, int]:
    """
    Wie viel je ausgebender Transaktion **netto** abgeflossen ist.

    Wer ein großes UTXO aufteilt oder viele kleine zusammenlegt, gibt Outputs
    aus und verkauft trotzdem nichts. Maßgeblich ist deshalb nicht, was
    hineinging, sondern was nicht wieder auf eigenen Adressen landete:

        netto = eingesetzt − zurückgeflossen

    Bleibt davon nur die Gebühr, war es ein Eigenübertrag. Kommt mehr zurück
    als hineinging — bei einer Transaktion mit fremden Eingängen, etwa einem
    CoinJoin —, ist ebenfalls nichts abgeflossen.

    Bewusst je Transaktion und nicht je Output: Ein einzelner Output sagt
    nichts darüber, wohin das Geld ging.
    """
    eingesetzt: dict[str, int] = {}
    zurueck: dict[str, int] = {}

    for utxo in utxos:
        spender = utxo.get("spent_txid")
        if utxo.get("spent") and spender:
            eingesetzt[spender] = eingesetzt.get(spender, 0) + int(
                utxo.get("value", 0)
            )
        # Was diese Transaktion uns wiedergegeben hat, steht als eigener
        # Eintrag mit ihrer TxID.
        erzeuger = str(utxo.get("txid", ""))
        if erzeuger:
            zurueck[erzeuger] = zurueck.get(erzeuger, 0) + int(
                utxo.get("value", 0)
            )

    return {
        txid: betrag - zurueck.get(txid, 0)
        for txid, betrag in eingesetzt.items()
    }, zurueck


#: Anteil des Einsatzes, unterhalb dessen ein Nettoabfluss als Gebühr gilt.
#:
#: Ohne die ausgebende Transaktion lässt sich Gebühr nicht von Zahlung
#: trennen. Ein Prozent trennt beides in der Praxis zuverlässig: Gebühren
#: liegen weit darunter, Zahlungen weit darüber. Wer wirklich ein halbes
#: Prozent eines UTXO verkauft, wird hier zu wohlwollend behandelt — das steht
#: im Hinweis.
_GEBUEHR_ANTEIL = 0.01


def _ist_eigenuebertrag(eingesetzt: int, netto: int, zurueck: int) -> bool:
    """
    Blieb vom Abfluss nur die Netzwerkgebühr?

    Voraussetzung ist, dass überhaupt etwas zurückkam — sonst ist der ganze
    Betrag weg und es war eine Veräußerung.
    """
    if zurueck <= 0:
        return False
    if netto <= 0:
        return True
    return netto <= max(1, int(eingesetzt * _GEBUEHR_ANTEIL))


def _abgang_zeitpunkt(utxo: dict) -> datetime | None:
    """Wann dieser Output ausgegeben wurde — None, wenn er noch liegt."""
    if not utxo.get("spent"):
        return None
    stempel = utxo.get("spent_time_ts")
    if not stempel:
        return None
    try:
        return datetime.fromtimestamp(int(stempel))
    except (ValueError, OSError, OverflowError):
        return None


def _output_zeitpunkt(utxo: dict) -> datetime | None:
    """Wann dieser Output entstanden ist."""
    status = utxo.get("status") or {}
    block_time = status.get("block_time")
    if not block_time:
        return None
    return datetime.fromtimestamp(int(block_time))


def _anschaffung(
    utxo: dict,
    ingress: dict | None,
    *,
    anschaffung: str = STANDARD_ANSCHAFFUNG,
) -> tuple[datetime | None, str, bool, bool]:
    """
    Wann die Sats dieses UTXO angeschafft wurden — und woher die Angabe stammt.

    *anschaffung*: ``juengste`` (defensiv, Default) nutzt ``external_time_ts``;
    ``aelteste`` (offensiv) nutzt ``external_oldest_time_ts``. Interne
    Überträge zwischen eigenen Wallets verändern die Haltedauer nicht.

    Fehlt der Wert — ältere Cache-Einträge, oder eine Datenquelle ohne
    Blockzeiten zu den Vorgänger-Outputs —, gilt der jüngste Wallet-Eingang
    (``youngest_time_ts``, Grundlage ``GRUNDLAGE_WALLET_EINGANG``). Der kann
    bei Eigenüberträgen zu jung sein, ist aber nie zu alt; die Haltefrist
    wird also höchstens unterschätzt. Zuletzt das Entstehungsdatum des
    Outputs.

    Liefert *(zeitpunkt, grundlage, untergrenze, offensiv_fallback)*.
    *offensiv_fallback* ist True, wenn Offensiv gewählt war, aber kein
    Oldest-Feld im Ingress lag und deshalb der jüngste Wert genutzt wurde.
    """
    modus = parse_anschaffung(anschaffung)
    if ingress:
        untergrenze = bool(ingress.get("external_untergrenze"))
        if modus == ANSCHAFFUNG_AELTESTE:
            stempel = ingress.get("external_oldest_time_ts")
            if stempel:
                try:
                    return (
                        datetime.fromtimestamp(int(stempel)),
                        GRUNDLAGE_HERKUNFT,
                        untergrenze,
                        False,
                    )
                except (ValueError, OSError, OverflowError):
                    pass
            # Alt-Cache ohne Oldest: nicht still als Offensiv verkaufen.
            stempel = ingress.get("external_time_ts")
            if stempel:
                try:
                    return (
                        datetime.fromtimestamp(int(stempel)),
                        GRUNDLAGE_HERKUNFT,
                        untergrenze,
                        True,
                    )
                except (ValueError, OSError, OverflowError):
                    pass
        else:
            stempel = ingress.get("external_time_ts")
            if stempel:
                try:
                    return (
                        datetime.fromtimestamp(int(stempel)),
                        GRUNDLAGE_HERKUNFT,
                        untergrenze,
                        False,
                    )
                except (ValueError, OSError, OverflowError):
                    pass
        stempel = ingress.get("youngest_time_ts")
        if stempel:
            try:
                return (
                    datetime.fromtimestamp(int(stempel)),
                    GRUNDLAGE_WALLET_EINGANG,
                    False,
                    False,
                )
            except (ValueError, OSError, OverflowError):
                pass
    return _output_zeitpunkt(utxo), GRUNDLAGE_OUTPUT, False, False


@dataclass
class Eingang:
    """Ein Zufluss in ein Wallet, bezogen auf ein Steuerjahr."""

    txid: str
    vout: int
    address: str
    wallet: str
    value_sats: int
    zeitpunkt: datetime
    frist_ende: datetime | None
    erfuellt: bool
    haltedauer_tage: int
    herkunft: str = ""
    grundlage: str = GRUNDLAGE_OUTPUT
    #: True, wenn externe Vorgänger unaufgelöst blieben und das
    #: Anschaffungsdatum deshalb zu alt sein kann.
    untergrenze: bool = False
    #: True: Anschaffung nach dem Stichtag — Halten macht nicht steuerfrei.
    neuvermoegen: bool = False
    #: juengste|aelteste — welche Lesart das Datum gewählt hat.
    anschaffung: str = STANDARD_ANSCHAFFUNG
    #: Offensiv gewählt, aber nur jüngstes Datum im Cache vorhanden.
    offensiv_fallback: bool = False

    @property
    def geprueft(self) -> bool:
        """Eine Herkunftsanalyse liegt vor — gleich auf welcher Grundlage."""
        return self.grundlage in (GRUNDLAGE_HERKUNFT, GRUNDLAGE_WALLET_EINGANG)

    @property
    def grundlage_label(self) -> str:
        return _grundlage_label(
            self.grundlage,
            self.untergrenze,
            anschaffung=self.anschaffung,
            offensiv_fallback=self.offensiv_fallback,
        )

    def as_dict(self) -> dict:
        return {
            "txid": self.txid,
            "vout": self.vout,
            "address": self.address,
            "wallet": self.wallet,
            "value_sats": self.value_sats,
            "datum": self.zeitpunkt.strftime("%d.%m.%Y"),
            "zeit": self.zeitpunkt.strftime("%H:%M:%S"),
            "frist_ende": self.frist_ende.strftime("%d.%m.%Y") if self.frist_ende else "",
            "erfuellt": self.erfuellt,
            "haltedauer_tage": self.haltedauer_tage,
            "herkunft": self.herkunft,
            "grundlage": self.grundlage,
            "geprueft": self.geprueft,
            "untergrenze": self.untergrenze,
            "grundlage_label": self.grundlage_label,
            "neuvermoegen": self.neuvermoegen,
            "anschaffung": self.anschaffung,
            "offensiv_fallback": self.offensiv_fallback,
        }


def verfuegbare_jahre(utxos: list[dict]) -> list[int]:
    """Jahre, für die überhaupt Eingänge vorliegen — absteigend."""
    jahre = set()
    for utxo in utxos:
        zeitpunkt = _output_zeitpunkt(utxo)
        if zeitpunkt:
            jahre.add(zeitpunkt.year)
    if not jahre:
        return []
    return sorted(range(min(jahre), datetime.now().year + 1), reverse=True)


def auswerten(
    utxos: list[dict],
    jahr: int,
    *,
    haltefrist_jahre: int = STANDARD_HALTEFRIST_JAHRE,
    stichtag: date | None = None,
    anschaffung: str = STANDARD_ANSCHAFFUNG,
    wallet=None,
    immutable_cache_dir: Path | None = None,
    jetzt: datetime | None = None,
) -> dict:
    """
    Wertet die Eingänge bis zum Bezugsdatum des Steuerjahres aus.

    Bezugsdatum ist der 31.12. — beim laufenden Jahr jedoch der heutige Tag,
    siehe bezugsdatum(). Eingänge danach bleiben außen vor.

    *anschaffung*: ``juengste`` (defensiv) oder ``aelteste`` (offensiv).

    *jetzt* dient dem Test; im Betrieb bleibt es leer.
    """
    modus = parse_anschaffung(anschaffung)
    ende, laufend = bezugsdatum(jahr, jetzt)
    eintraege: list[Eingang] = []
    abgaenge: list[dict] = []
    ohne_datum = 0
    mit_verlauf = _hat_verlauf(utxos)
    jahresbeginn = datetime(jahr, 1, 1)
    # Je ausgebender Transaktion: Was ist netto abgeflossen? Nur das ist eine
    # Veräußerung. Aufteilen und Zusammenlegen bleiben außen vor.
    netto_je_tx, zurueck_je_tx = _abgang_je_transaktion(utxos)
    einsatz_je_tx: dict[str, int] = {}
    for eintrag_roh in utxos:
        if eintrag_roh.get("spent") and eintrag_roh.get("spent_txid"):
            schluessel = eintrag_roh["spent_txid"]
            einsatz_je_tx[schluessel] = einsatz_je_tx.get(schluessel, 0) + int(
                eintrag_roh.get("value", 0)
            )
    eigenuebertraege: set[str] = set()

    for utxo in utxos:
        txid = utxo.get("txid", "")
        vout = int(utxo.get("vout", 0))

        # Zuerst die Herkunft: Sie liefert das steuerlich maßgebliche Datum,
        # das Entstehungsdatum des Outputs ist nur der Rückfall.
        ingress = None
        if immutable_cache_dir:
            ingress = main.load_utxo_ingress_cache(txid, vout, immutable_cache_dir)

        zeitpunkt, grundlage, untergrenze, offensiv_fb = _anschaffung(
            utxo, ingress, anschaffung=modus,
        )
        if zeitpunkt is None:
            ohne_datum += 1
            continue
        if zeitpunkt > ende:
            continue

        adresse = utxo.get("address", "")

        # Ausgegeben: Was vor dem Stichtag abging, lag dort nicht mehr im
        # Wallet und gehört nicht in den Bestand. Steuerlich ist gerade die
        # Veräußerung der maßgebliche Vorgang — sie wird eigens ausgewiesen.
        abgang = _abgang_zeitpunkt(utxo)
        if abgang is not None and abgang <= ende:
            spender = utxo.get("spent_txid") or ""
            netto = netto_je_tx.get(spender, int(utxo.get("value", 0)))
            if _ist_eigenuebertrag(
                einsatz_je_tx.get(spender, 0), netto,
                zurueck_je_tx.get(spender, 0),
            ):
                # Alles wieder auf eigenen Adressen gelandet: umgeschichtet,
                # nicht veräußert. Der Betrag steht als neues UTXO im Bestand.
                if jahresbeginn <= abgang <= ende:
                    eigenuebertraege.add(spender)
                continue
            if jahresbeginn <= abgang <= ende:
                if spender in {a["abgang_txid"] for a in abgaenge}:
                    # Mehrere unserer Outputs in derselben Transaktion: Der
                    # Nettoabfluss gilt für sie gemeinsam, nicht je Stück.
                    continue
                _frist, erfuellt_ab, neu_ab = haltefrist_entscheidung(
                    zeitpunkt, abgang, haltefrist_jahre, stichtag
                )
                abgaenge.append({
                    "txid": txid,
                    "vout": vout,
                    "address": adresse,
                    "wallet": (
                        wallet.resolve_address(adresse) if wallet else None
                    ) or "unbekannt",
                    "value_sats": netto,
                    "datum": zeitpunkt.strftime("%d.%m.%Y"),
                    "abgang_datum": abgang.strftime("%d.%m.%Y"),
                    "abgang_txid": utxo.get("spent_txid") or "",
                    "haltedauer_tage": max(0, (abgang - zeitpunkt).days),
                    "frist_erfuellt": erfuellt_ab,
                    "neuvermoegen": neu_ab,
                    "grundlage": grundlage,
                    "untergrenze": untergrenze,
                    "anschaffung": modus,
                    "offensiv_fallback": offensiv_fb,
                })
            continue

        frist_ende, erfuellt, neuvermoegen = haltefrist_entscheidung(
            zeitpunkt, ende, haltefrist_jahre, stichtag
        )
        eintrag = Eingang(
            txid=txid,
            vout=vout,
            address=adresse,
            wallet=(wallet.resolve_address(adresse) if wallet else None) or "unbekannt",
            value_sats=int(utxo.get("value", 0)),
            zeitpunkt=zeitpunkt,
            frist_ende=frist_ende,
            erfuellt=erfuellt,
            haltedauer_tage=max(0, (ende - zeitpunkt).days),
            grundlage=grundlage,
            untergrenze=untergrenze,
            neuvermoegen=neuvermoegen,
            anschaffung=modus,
            offensiv_fallback=offensiv_fb,
        )

        if eintrag.geprueft:
            ausgabe = _output_zeitpunkt(utxo)
            eintrag.herkunft = (
                f"Output entstand {ausgabe.strftime('%d.%m.%Y')}"
                if ausgabe and ausgabe.date() != zeitpunkt.date() else ""
            )

        eintraege.append(eintrag)

    eintraege.sort(key=lambda e: e.zeitpunkt)

    erfuellt = [e for e in eintraege if e.erfuellt]
    offen = [e for e in eintraege if not e.erfuellt]
    naechste = min((e.frist_ende for e in offen if e.frist_ende), default=None)

    ungeprueft = [e for e in eintraege if not e.geprueft]
    untergrenzen = [e for e in eintraege if e.untergrenze]
    wallet_eingaenge = [
        e for e in eintraege if e.grundlage == GRUNDLAGE_WALLET_EINGANG
    ]
    offensiv_fallbacks = [e for e in eintraege if e.offensiv_fallback]

    hinweise = [
        HINWEIS_MIT_VERLAUF if mit_verlauf else HINWEIS_UMFANG,
        HINWEIS_KEINE_BERATUNG,
    ]
    if ungeprueft:
        hinweise.insert(0, HINWEIS_UNGEPRUEFT)
    if wallet_eingaenge:
        hinweise.insert(0, HINWEIS_WALLET_EINGANG)
    if untergrenzen:
        hinweise.insert(0, HINWEIS_UNTERGRENZE)
    if modus == ANSCHAFFUNG_AELTESTE:
        hinweise.insert(0, HINWEIS_OFFENSIV)
    if offensiv_fallbacks:
        hinweise.insert(0, HINWEIS_OFFENSIV_OHNE_AELTESTE)
    if eigenuebertraege:
        hinweise.insert(0, HINWEIS_EIGENUEBERTRAG.format(
            anzahl=len(eigenuebertraege)
        ))
    if stichtag:
        hinweise.insert(0, (
            f"Stichtagsregel: Anschaffungen nach dem {format_stichtag(stichtag)} "
            "werden nicht durch Halten steuerfrei (österr. Neuvermögen)."
        ))
    if laufend:
        hinweise.insert(0, (
            f"Das Steuerjahr {jahr} läuft noch. Fristen sind deshalb gegen "
            f"den heutigen Tag gerechnet, nicht gegen den 31.12.{jahr} — "
            "sonst gälten Beträge als fristerfüllt, deren Jahr erst später "
            "abläuft."
        ))

    return {
        "jahr": jahr,
        "stichtag": ende.strftime("%d.%m.%Y"),
        "laufend": laufend,
        "stichtag_label": (
            f"Stand heute, {ende.strftime('%d.%m.%Y')}" if laufend
            else f"Stichtag {ende.strftime('%d.%m.%Y')}"
        ),
        "haltefrist_jahre": haltefrist_jahre,
        "stichtag_regel": format_stichtag(stichtag),
        "anschaffung": modus,
        "erstellt": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "eintraege": [e.as_dict() for e in eintraege],
        "kennzahlen": {
            "gesamt_count": len(eintraege),
            "gesamt_sats": sum(e.value_sats for e in eintraege),
            "erfuellt_count": len(erfuellt),
            "erfuellt_sats": sum(e.value_sats for e in erfuellt),
            "offen_count": len(offen),
            "offen_sats": sum(e.value_sats for e in offen),
            "ohne_datum": ohne_datum,
            "naechste_frist": naechste.strftime("%d.%m.%Y") if naechste else "",
            # Wie viel der Aufstellung auf dem bloßen Output-Datum beruht und
            # damit eine zu kurze Haltefrist ausweisen kann.
            "ungeprueft_count": len(ungeprueft),
            "ungeprueft_sats": sum(e.value_sats for e in ungeprueft),
            "geprueft_count": len(eintraege) - len(ungeprueft),
            "untergrenze_count": len(untergrenzen),
            "untergrenze_sats": sum(e.value_sats for e in untergrenzen),
            "wallet_eingang_count": len(wallet_eingaenge),
            "wallet_eingang_sats": sum(e.value_sats for e in wallet_eingaenge),
            # Veräußerungen des Jahres — nur mit Verlaufsdaten überhaupt
            # sichtbar. Ohne sie bleiben beide Zahlen null.
            "abgang_count": len(abgaenge),
            "abgang_sats": sum(a["value_sats"] for a in abgaenge),
            "abgang_steuerpflichtig_count": sum(
                1 for a in abgaenge if not a["frist_erfuellt"]
            ),
            "abgang_steuerpflichtig_sats": sum(
                a["value_sats"] for a in abgaenge if not a["frist_erfuellt"]
            ),
            # Umgeschichtet statt veräußert — muss sichtbar sein, sonst wirkt
            # die Aufstellung lückenhaft, wo sie bloß richtig ist.
            "eigenuebertrag_count": len(eigenuebertraege),
        },
        "hat_verlauf": mit_verlauf,
        "abgaenge": sorted(abgaenge, key=lambda a: a["abgang_datum"]),
        "zeitstrahl": zeitstrahl(
            eintraege, ende, haltefrist_jahre, stichtag=stichtag,
        ),
        "hinweise": hinweise,
        "_objekte": eintraege,
    }


# ---------------------------------------------------------------------------
# Zeitstrahl
# ---------------------------------------------------------------------------

def quartalsbeginn_vor(tag: date) -> date:
    """
    Letzter Quartalsanfang, der strikt vor *tag* liegt.

    19.08. → 01.07.; fällt *tag* selbst auf einen Quartalsanfang, gilt
    das Quartal davor (01.07. → 01.04.).
    """
    monat = ((tag.month - 1) // 3) * 3 + 1
    beginn = date(tag.year, monat, 1)
    if beginn < tag:
        return beginn
    if monat == 1:
        return date(tag.year - 1, 10, 1)
    return date(tag.year, monat - 3, 1)


def _groessenklasse(sats: int, gesamt: int) -> str:
    """Drei Stufen statt stufenloser Skalierung — sonst wird nichts erkennbar."""
    if gesamt <= 0:
        return "klein"
    anteil = sats / gesamt
    if anteil >= 0.10:
        return "gross"
    if anteil >= 0.01:
        return "mittel"
    return "klein"


def zeitstrahl(
    eintraege: list[Eingang],
    ende: datetime,
    haltefrist_jahre: int,
    stichtag: date | None = None,
) -> dict:
    """
    Rechnet die Eingänge auf Positionen einer Fläche um.

    X: Zeit vom gebündelten linken Rand bis zum Bezugstag. UTXOs vor der
    Haltefrist oder vor dem Stichtag sitzen gemeinsam am Quartalsbeginn
    davor — sonst quetscht ein sehr alter Coin den aktuellen Rand.
    Y: Betrag dieses UTXO, relativ zum größten. Prozentwerte, damit die
    Darstellung ohne feste Pixelbreite auskommt.

    ``aeltere_sats`` ist die Summe aller zeitlich früheren UTXOs — der
    Saldo, der schon da war, als dieser Eingang dazukam.

    Die Fristgrenze (Bezug minus Haltefrist) trennt sichtbar, was die Frist
    erfüllt hat. Liegt sie außerhalb des dargestellten Zeitraums, wird sie
    nicht gezeichnet — eine Linie am Rand würde etwas Falsches suggerieren.
    """
    if not eintraege:
        return {"vorhanden": False, "events": [], "ticks": [], "frist_pos": None}

    frist_grenze = (
        plus_jahre(ende, -haltefrist_jahre) if haltefrist_jahre > 0 else None
    )
    # Bündelpunkt: Quartalsbeginn vor der jüngeren der beiden Grenzen,
    # damit die Achse beim aktuellen Rand bleibt.
    if frist_grenze is not None:
        anker = frist_grenze.date()
    elif stichtag is not None:
        anker = stichtag
    else:
        anker = None
    buendel = (
        datetime.combine(quartalsbeginn_vor(anker), datetime.min.time())
        if anker is not None else None
    )

    def _gruppe(eintrag: Eingang) -> str | None:
        if anker is None:
            return None
        if stichtag is not None and eintrag.zeitpunkt.date() <= stichtag:
            return "stichtag"
        if frist_grenze is not None and eintrag.zeitpunkt <= frist_grenze:
            return "haltefrist"
        return None

    sortiert = sorted(eintraege, key=lambda e: (e.zeitpunkt, e.txid, e.vout))
    gruppen_zahl = {"stichtag": 0, "haltefrist": 0}
    for eintrag in sortiert:
        name = _gruppe(eintrag)
        if name:
            gruppen_zahl[name] += 1

    def _plotzeit(eintrag: Eingang) -> datetime:
        return buendel if _gruppe(eintrag) and buendel is not None else eintrag.zeitpunkt

    plotzeiten = [_plotzeit(e) for e in sortiert]
    von = min(plotzeiten)
    bis = max(max(plotzeiten), ende)

    spanne = (bis - von).total_seconds()
    if spanne <= 0:
        # Ein einziger Eingang, oder alle am selben Tag: künstliche Spanne,
        # damit die Punkte nicht alle auf 0 % liegen.
        von = von - timedelta(days=180)
        bis = bis + timedelta(days=180)
        spanne = (bis - von).total_seconds()

    def prozent(zeitpunkt: datetime) -> float:
        return max(0.0, min(100.0, (zeitpunkt - von).total_seconds() / spanne * 100))

    gesamt = sum(e.value_sats for e in eintraege)
    buendel_summe = {
        name: sum(e.value_sats for e in sortiert if _gruppe(e) == name)
        for name in ("stichtag", "haltefrist")
    }
    hoechst = max(
        [e.value_sats for e in sortiert if _gruppe(e) is None]
        + [s for s in buendel_summe.values() if s]
        or [0]
    ) or 1

    def _event(eintrag: Eingang, *, sats: int, gruppe: str | None,
               gruppe_n: int, aeltere_sats: int, datum: str,
               wallet: str) -> dict:
        return {
            "pos": round(prozent(_plotzeit(eintrag)), 3),
            "y": round(sats / hoechst * 100, 3),
            "erfuellt": eintrag.erfuellt,
            "geprueft": eintrag.geprueft,
            "neuvermoegen": eintrag.neuvermoegen,
            "value_sats": sats,
            "aeltere_sats": aeltere_sats,
            "datum": datum,
            "wallet": wallet,
            "groesse": _groessenklasse(sats, gesamt),
            "gruppe": gruppe,
            "gruppe_n": gruppe_n,
        }

    events: list[dict] = []
    aeltere = 0
    ausgegeben = set()
    for eintrag in sortiert:
        gruppe = _gruppe(eintrag)
        if gruppe:
            if gruppe in ausgegeben:
                continue
            ausgegeben.add(gruppe)
            mitglieder = [e for e in sortiert if _gruppe(e) == gruppe]
            namen = []
            for m in mitglieder:
                if m.wallet and m.wallet not in namen:
                    namen.append(m.wallet)
            daten = [m.zeitpunkt.strftime("%d.%m.%Y") for m in mitglieder]
            ev = _event(
                eintrag,
                sats=buendel_summe[gruppe],
                gruppe=gruppe,
                gruppe_n=len(mitglieder),
                aeltere_sats=aeltere,
                datum=daten[0] if len(daten) == 1 else f"{daten[0]} – {daten[-1]}",
                wallet=", ".join(namen) if namen else "unbekannt",
            )
            ev["gruppe_daten"] = daten
            events.append(ev)
            aeltere += buendel_summe[gruppe]
            continue
        events.append(_event(
            eintrag,
            sats=eintrag.value_sats,
            gruppe=None,
            gruppe_n=0,
            aeltere_sats=aeltere,
            datum=eintrag.zeitpunkt.strftime("%d.%m.%Y"),
            wallet=eintrag.wallet,
        ))
        aeltere += eintrag.value_sats

    frist_pos = None
    frist_datum = ""
    if frist_grenze is not None and von <= frist_grenze <= bis:
        frist_pos = round(prozent(frist_grenze), 3)
        frist_datum = frist_grenze.strftime("%d.%m.%Y")

    schritte = 4
    ticks = [
        {
            "pos": round(i / schritte * 100, 3),
            "label": (von + timedelta(seconds=spanne * i / schritte)).strftime("%m/%Y"),
        }
        for i in range(schritte + 1)
    ]

    return {
        "vorhanden": True,
        "von": von.strftime("%d.%m.%Y"),
        "bis": bis.strftime("%d.%m.%Y"),
        "frist_pos": frist_pos,
        "frist_datum": frist_datum,
        "events": events,
        "ticks": ticks,
        "max_sats": hoechst,
        "verdeckt": gruppen_zahl["stichtag"] + gruppen_zahl["haltefrist"],
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _btc(sats: int) -> str:
    """Betrag in BTC mit deutscher Dezimaltrennung und acht Nachkommastellen."""
    return f"{sats / 1e8:.8f}".replace(".", ",")


def als_csv(auswertung: dict) -> bytes:
    """
    CSV für Tabellenkalkulation und Steuerberatung.

    Semikolon als Trenner und ein UTF-8-BOM, weil Excel unter Windows sonst
    weder die Spalten noch die Umlaute richtig erkennt. Beträge mit
    Dezimalkomma, damit sie ohne Nacharbeit als Zahl gelesen werden.
    """
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";", quoting=csv.QUOTE_MINIMAL,
                           lineterminator="\r\n")

    schreiber.writerow([f"Aufstellung Steuerjahr {auswertung['jahr']}"])
    schreiber.writerow([
        "Stand heute" if auswertung.get("laufend") else "Stichtag",
        auswertung["stichtag"],
    ])
    schreiber.writerow(["Haltefrist (Jahre)", auswertung["haltefrist_jahre"] or "keine"])
    schreiber.writerow([
        "Stichtagsregel (Altbestand bis)",
        auswertung.get("stichtag_regel") or "keine — Haltefrist für alle",
    ])
    schreiber.writerow(["Erstellt am", auswertung["erstellt"]])
    schreiber.writerow(["Quelle", "SatSage, lokale Auswertung der Blockchain"])
    schreiber.writerow([])
    for hinweis in auswertung["hinweise"]:
        schreiber.writerow(["Hinweis", hinweis])
    schreiber.writerow([])

    schreiber.writerow([
        "UTXO Datum", "UTXO Zeit", "Wallet", "Adresse",
        "Betrag BTC", "Betrag sats", "Haltedauer Tage",
        "Frist erfüllt am", "Frist erfüllt", "Grundlage Anschaffungsdatum",
        "Anmerkung", "Transaktion", "Output",
    ])
    for eintrag in auswertung["eintraege"]:
        schreiber.writerow([
            eintrag["datum"], eintrag["zeit"], eintrag["wallet"], eintrag["address"],
            _btc(eintrag["value_sats"]), eintrag["value_sats"],
            eintrag["haltedauer_tage"], eintrag["frist_ende"],
            "ja" if eintrag["erfuellt"] else "nein",
            eintrag["grundlage_label"],
            eintrag["herkunft"], eintrag["txid"], eintrag["vout"],
        ])

    kennzahlen = auswertung["kennzahlen"]
    schreiber.writerow([])
    schreiber.writerow(["Summe", "", "", "", _btc(kennzahlen["gesamt_sats"]),
                        kennzahlen["gesamt_sats"], "", "", ""])
    schreiber.writerow(["davon Frist erfüllt", "", "", "",
                        _btc(kennzahlen["erfuellt_sats"]),
                        kennzahlen["erfuellt_sats"], "", "", "ja"])
    schreiber.writerow(["davon Frist offen", "", "", "",
                        _btc(kennzahlen["offen_sats"]),
                        kennzahlen["offen_sats"], "", "", "nein"])
    if kennzahlen.get("ungeprueft_count"):
        schreiber.writerow([
            "davon ohne Herkunftsanalyse", "", "", "",
            _btc(kennzahlen["ungeprueft_sats"]), kennzahlen["ungeprueft_sats"],
            "", "", "", "Haltefrist kann zu kurz ausgewiesen sein",
        ])
    if kennzahlen.get("wallet_eingang_count"):
        schreiber.writerow([
            "davon nur Wallet-Eingang", "", "", "",
            _btc(kennzahlen["wallet_eingang_sats"]),
            kennzahlen["wallet_eingang_sats"],
            "", "", "", "Haltefrist kann zu kurz ausgewiesen sein",
        ])
    if kennzahlen.get("untergrenze_count"):
        schreiber.writerow([
            "davon Anschaffungsdatum als Untergrenze", "", "", "",
            _btc(kennzahlen["untergrenze_sats"]),
            kennzahlen["untergrenze_sats"],
            "", "", "", "Haltefrist kann zu LANG ausgewiesen sein",
        ])

    # Veräußerungen als eigener Block. Nach § 23 EStG ist die Veräußerung der
    # steuerlich maßgebliche Vorgang — sie gehört in die Datei, die zum
    # Steuerberater geht, nicht nur in die Bildschirmansicht.
    abgaenge = auswertung.get("abgaenge") or []
    if abgaenge:
        schreiber.writerow([])
        schreiber.writerow([f"Veräußerungen im Steuerjahr {auswertung['jahr']}"])
        schreiber.writerow([
            "Anschaffung", "Veräußerung", "Wallet", "Adresse",
            "Betrag BTC", "Betrag sats", "Haltedauer Tage",
            "Frist erfüllt", "Grundlage Anschaffungsdatum",
            "Transaktion", "Output", "Ausgegeben in Tx",
        ])
        for abgang in abgaenge:
            schreiber.writerow([
                abgang["datum"], abgang["abgang_datum"], abgang["wallet"],
                abgang["address"], _btc(abgang["value_sats"]),
                abgang["value_sats"], abgang["haltedauer_tage"],
                "ja" if abgang["frist_erfuellt"] else "nein",
                _grundlage_label(
                    abgang["grundlage"],
                    abgang["untergrenze"],
                    anschaffung=abgang.get("anschaffung", STANDARD_ANSCHAFFUNG),
                    offensiv_fallback=bool(abgang.get("offensiv_fallback")),
                ),
                abgang["txid"], abgang["vout"], abgang["abgang_txid"],
            ])
        schreiber.writerow([])
        schreiber.writerow([
            "Summe Veräußerungen", "", "", "",
            _btc(kennzahlen["abgang_sats"]), kennzahlen["abgang_sats"],
        ])
        schreiber.writerow([
            "davon innerhalb der Haltefrist", "", "", "",
            _btc(kennzahlen["abgang_steuerpflichtig_sats"]),
            kennzahlen["abgang_steuerpflichtig_sats"], "", "nein",
            "", "", "", "steuerlich relevant",
        ])

    return b"\xef\xbb\xbf" + puffer.getvalue().encode("utf-8")


def _html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def als_bericht(auswertung: dict) -> bytes:
    """
    Druckbarer Bericht als eigenständige HTML-Datei.

    Bewusst ohne externe Ressourcen: Die Datei lässt sich weitergeben, im
    Browser öffnen und über „Drucken → Als PDF sichern" in ein PDF wandeln —
    auf allen drei Plattformen gleich, ohne Zusatzsoftware.
    """
    kennzahlen = auswertung["kennzahlen"]
    zeilen = []
    for eintrag in auswertung["eintraege"]:
        zeilen.append(
            "<tr>"
            f"<td>{_html_escape(eintrag['datum'])}</td>"
            f"<td class='mono'>{_html_escape(eintrag['wallet'])}</td>"
            f"<td class='mono klein'>{_html_escape(eintrag['address'])}</td>"
            f"<td class='r mono'>{_btc(eintrag['value_sats'])}</td>"
            f"<td class='r'>{eintrag['haltedauer_tage']}</td>"
            f"<td>{_html_escape(eintrag['frist_ende'])}</td>"
            f"<td>{'ja' if eintrag['erfuellt'] else 'nein'}</td>"
            f"<td class='klein'>{_html_escape(eintrag['grundlage_label'])}</td>"
            "</tr>"
        )

    hinweise = "".join(
        f"<li>{_html_escape(h)}</li>" for h in auswertung["hinweise"]
    )

    # Veräußerungen als eigener Abschnitt — der steuerlich maßgebliche Vorgang
    # gehört in den Bericht, nicht nur in die Bildschirmansicht.
    abgaenge = auswertung.get("abgaenge") or []
    abgang_block = ""
    if abgaenge:
        abgang_zeilen = "".join(
            "<tr>"
            f"<td>{_html_escape(a['abgang_datum'])}</td>"
            f"<td>{_html_escape(a['datum'])}</td>"
            f"<td class='mono'>{_html_escape(a['wallet'])}</td>"
            f"<td class='r mono'>{_btc(a['value_sats'])}</td>"
            f"<td class='r'>{a['haltedauer_tage']}</td>"
            f"<td>{'ja' if a['frist_erfuellt'] else '<b>nein</b>'}</td>"
            f"<td class='klein'>"
            f"{_html_escape(_grundlage_label(a['grundlage'], a['untergrenze'], anschaffung=a.get('anschaffung', STANDARD_ANSCHAFFUNG), offensiv_fallback=bool(a.get('offensiv_fallback'))))}"
            "</td>"
            "</tr>"
            for a in abgaenge
        )
        steuerpflichtig = kennzahlen.get("abgang_steuerpflichtig_count", 0)
        abgang_block = f"""
<h2>Veräußerungen im Steuerjahr</h2>
<p class="unter">
  {kennzahlen['abgang_count']} Vorgänge ·
  {_btc(kennzahlen['abgang_sats'])} BTC ·
  {'davon ' + str(steuerpflichtig) + ' innerhalb der Haltefrist'
   if steuerpflichtig else 'alle nach Ablauf der Haltefrist'}
</p>
<table>
  <thead><tr>
    <th>Veräußert</th><th>Angeschafft</th><th>Wallet</th>
    <th class="r">Betrag BTC</th><th class="r">Tage</th>
    <th>Frist erfüllt</th><th>Grundlage</th>
  </tr></thead>
  <tbody>{abgang_zeilen}</tbody>
</table>
"""

    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<title>Aufstellung Steuerjahr {auswertung['jahr']}</title>
<style>
  body {{ font-family: Georgia, "Times New Roman", serif; color: #1a1a1a;
         max-width: 20cm; margin: 2cm auto; line-height: 1.5; }}
  h1 {{ font-size: 20pt; margin: 0 0 4pt; }}
  .unter {{ color: #555; margin: 0 0 20pt; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 9pt; }}
  th {{ text-align: left; border-bottom: 1.5px solid #333; padding: 4pt 6pt 4pt 0;
        font-size: 8pt; text-transform: uppercase; letter-spacing: .06em; }}
  td {{ border-bottom: 1px solid #ddd; padding: 4pt 6pt 4pt 0; }}
  .r {{ text-align: right; }}
  .mono {{ font-family: "Courier New", monospace; }}
  .klein {{ font-size: 7.5pt; }}
  .kennzahlen {{ display: flex; gap: 24pt; margin: 0 0 20pt; flex-wrap: wrap; }}
  .kennzahl {{ border-left: 2px solid #333; padding-left: 8pt; }}
  .kennzahl b {{ display: block; font-size: 14pt; }}
  .kennzahl span {{ font-size: 8pt; text-transform: uppercase;
                    letter-spacing: .06em; color: #555; }}
  .hinweise {{ margin-top: 24pt; padding-top: 10pt; border-top: 1px solid #333;
               font-size: 8.5pt; color: #444; }}
  .hinweise li {{ margin-bottom: 5pt; }}
  @media print {{ body {{ margin: 0; }} }}
</style></head><body>

<h1>Aufstellung Steuerjahr {auswertung['jahr']}</h1>
<p class="unter">
  {'Stand heute' if auswertung.get('laufend') else 'Stichtag'} {auswertung['stichtag']} ·
  Haltefrist {auswertung['haltefrist_jahre'] or '—'} Jahr(e) ·
  Stichtagsregel {auswertung.get('stichtag_regel') or 'aus'} ·
  erstellt am {auswertung['erstellt']}
</p>

<div class="kennzahlen">
  <div class="kennzahl"><span>Bestand gesamt</span>
    <b>{_btc(kennzahlen['gesamt_sats'])} BTC</b>
    {kennzahlen['gesamt_count']} UTXOs</div>
  <div class="kennzahl"><span>Haltefrist erfüllt</span>
    <b>{_btc(kennzahlen['erfuellt_sats'])} BTC</b>
    {kennzahlen['erfuellt_count']} UTXOs</div>
  <div class="kennzahl"><span>Haltefrist offen</span>
    <b>{_btc(kennzahlen['offen_sats'])} BTC</b>
    {kennzahlen['offen_count']} UTXOs</div>
</div>

<table>
  <thead><tr>
    <th>UTXO</th><th>Wallet</th><th>Adresse</th>
    <th class="r">Betrag BTC</th><th class="r">Tage</th>
    <th>Frist erfüllt am</th><th>Erfüllt</th><th>Grundlage</th>
  </tr></thead>
  <tbody>{''.join(zeilen)}</tbody>
</table>
{abgang_block}
<div class="hinweise"><ul>{hinweise}</ul>
<p>Erzeugt mit SatSage aus lokal abgefragten Blockchain-Daten.</p></div>

</body></html>
""".encode("utf-8")
