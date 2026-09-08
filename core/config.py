"""
Konfiguration: .env lesen und strukturerhaltend zurückschreiben.

Die .env bleibt die einzige Wahrheit — CLI und Web-Oberfläche lesen dieselbe
Datei. Deshalb darf ein Schreibvorgang aus der Oberfläche nichts zerstören,
was jemand von Hand hineingeschrieben hat: Kommentare, Reihenfolge und
unbekannte Schlüssel überleben unverändert.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import main

DEFAULT_MAX_ADDRESSES = main.DEFAULT_MAX_ADDRESSES
SCRIPT_TYPE_CHOICES = main.SCRIPT_TYPE_CHOICES

#: Skripttypen einer Multisig-Wallet. Die Sortierung der Cosigner folgt
#: BIP-67 (sortedmulti) und wird deshalb nicht eigens gespeichert.
MULTISIG_SCRIPT_CHOICES = ("wsh", "sh-wsh")

#: Erkennt Extended Public Keys in freiem Text — dieselbe Form wie im
#: Specter-Plugin, damit beide Seiten dieselben Schlüssel finden.
_XPUB_RE = re.compile(r"\b([xyztuv]pub[1-9A-HJ-NP-Za-km-z]{50,})\b")

#: „sortedmulti(2,…" oder „multi(2,…" — die Zahl ist M.
#: sortedmulti(M,… / multi(M,… / multi_a(M,… — multi_a ist die Taproot-Form.
_MULTI_RE = re.compile(r"\b(?:sorted)?multi(?:_a)?\s*\(\s*(\d+)")


# ---------------------------------------------------------------------------
# Wallet-Modell
# ---------------------------------------------------------------------------


def extract_xpubs_from_text(text: str | None) -> list[str]:
    """Alle Extended Public Keys aus einem Text, Reihenfolge erhalten."""
    if not text:
        return []
    return list(dict.fromkeys(_XPUB_RE.findall(text)))


def _threshold_aus_deskriptor(descriptor: str) -> int | None:
    """
    M aus sortedmulti(M,…), multi(M,…) oder multi_a(M,…).

    Nur eine Beschriftung für die Anzeige, keine Grundlage für die Ableitung —
    die kommt aus dem geparsten Deskriptor. Bei Policies mit mehreren
    Ausgabepfaden (Liana: Primärschlüssel jetzt, Recovery nach Sperrfrist)
    gibt es kein „m von n"; dann bleibt der Wert leer, statt eine Zahl zu
    erfinden.
    """
    treffer = _MULTI_RE.search(descriptor or "")
    if not treffer:
        return None
    for gruppe in treffer.groups():
        if gruppe:
            try:
                return int(gruppe)
            except (TypeError, ValueError):
                return None
    return None


def deskriptor_aus_kurzform(
    threshold: int | None,
    script_type: str,
    xpubs: list[str],
) -> str:
    """
    Baut aus M/Skripttyp/Cosignern einen Deskriptor.

    Die Kurzform bleibt als Eingabe erlaubt — drei XPUBs von drei Geräten
    einzusammeln ist der übliche Weg, und einen Deskriptor dafür von Hand zu
    tippen wäre fehleranfällig. Gespeichert wird aber der Deskriptor: Er ist
    die einzige Form, die auch Taproot und Miniscript ausdrücken kann.

    ``/<0;1>/*`` ist die übliche Schreibweise für Empfang und Change — dieselbe
    Aufteilung, die der Single-Sig-Pfad seit jeher benutzt.
    """
    if not xpubs or not threshold:
        return ""
    if script_type not in MULTISIG_SCRIPT_CHOICES:
        # Nicht stillschweigend auf wsh ausweichen: Wer „tr" schreibt, meint
        # Taproot und bekäme sonst wortlos etwas anderes. Die Prüfung meldet
        # den Fall; für Taproot ist der Deskriptor der Weg.
        return ""
    schluessel = ",".join(f"{x}/<0;1>/*" for x in xpubs)
    kern = f"sortedmulti({int(threshold)},{schluessel})"
    roh = f"sh(wsh({kern}))" if script_type == "sh-wsh" else f"wsh({kern})"
    try:
        from embit.descriptor.checksum import add_checksum

        return add_checksum(roh)
    except Exception:
        return roh


#: Enthält der Text einen privaten Schlüssel? Der gehört nie hierher.
_XPRV_RE = re.compile(r"\b[xyztuv]prv[1-9A-HJ-NP-Za-km-z]{50,}\b")


def _deskriptor_kandidaten(text: str) -> list[str]:
    """
    Alle deskriptorförmigen Stellen im Text — auch aus JSON.

    Bewusst über den rohen Text und nicht über eine JSON-Struktur: Die
    Exporte von Sparrow, Specter und Bitcoin Core verschachteln
    unterschiedlich tief, und die Zeichenkette sieht überall gleich aus.
    """
    if not text:
        return []
    # Die Klammer-Regex kommt mit einer Verschachtelungsebene aus; Taproot mit
    # Skriptbaum hat mehr. Deshalb zusätzlich ab jeder Hülle bis zur passenden
    # schließenden Klammer greifen.
    kandidaten: list[str] = []
    for treffer in re.finditer(r"\b(sh|wsh|tr|wpkh|pkh|combo)\s*\(", text):
        start = treffer.start()
        tiefe = 0
        for stelle in range(treffer.end() - 1, len(text)):
            zeichen = text[stelle]
            if zeichen == "(":
                tiefe += 1
            elif zeichen == ")":
                tiefe -= 1
                if tiefe == 0:
                    ende = stelle + 1
                    pruef = re.match(r"#[a-z0-9]{8}", text[ende:])
                    if pruef:
                        ende += pruef.end()
                    kandidaten.append(text[start:ende])
                    break
            elif zeichen in "\"'\n" and tiefe == 0:
                break
    return kandidaten


def _mehrpfad(descriptor: str) -> str | None:
    """
    Macht aus einem Einzelpfad-Deskriptor die Empfangs-Variante.

    ``…/0/*`` und ``…/1/*`` beschreiben dieselbe Wallet in zwei Ketten. Um sie
    zu paaren, wird der Kettenindex durch eine Marke ersetzt; stimmen zwei
    Deskriptoren danach überein, gehören sie zusammen.
    """
    ohne_pruefsumme = descriptor.split("#", 1)[0]
    if "<" in ohne_pruefsumme:
        return None
    ersetzt, anzahl = re.subn(r"/[01]/\*", "/<CHAIN>/*", ohne_pruefsumme)
    return ersetzt if anzahl else None


def _vereinige_paare(kandidaten: list[str]) -> list[str]:
    """
    Führt Empfangs- und Change-Deskriptor zu einem mehrpfadigen zusammen.

    Getrennt gelesen fiele die Change-Kette unter den Tisch — und mit ihr das
    Wechselgeld, oft der größere Teil des Bestands.
    """
    ergebnis: list[str] = []
    nach_muster: dict[str, str] = {}

    for kandidat in kandidaten:
        muster = _mehrpfad(kandidat)
        if muster is None:
            if kandidat not in ergebnis:
                ergebnis.append(kandidat)
            continue
        if muster in nach_muster:
            continue
        nach_muster[muster] = kandidat

    for muster in nach_muster:
        ergebnis.append(muster.replace("/<CHAIN>/*", "/<0;1>/*"))
    return ergebnis


def _ergaenze_standard_ableitung(descriptor: str) -> str:
    """
    Hängt ``/<0;1>/*`` an xpubs ohne Wildcard — Specter/BlueWallet-Export.

    Specter speichert Multisig oft nur auf Kontoebene
    (``[fp/48h/0h/0h/2h]xpub…`` ohne ``/0/*``). Empfang und Change entstehen
    erst durch die Standardableitung. Specter DIY hängt ``/{0,1}/*`` an; wir
    nutzen die Core-Form ``/<0;1>/*``. Hat mindestens ein Schlüssel schon
    eine Wildcard, bleibt der Text unverändert.
    """
    if not descriptor:
        return descriptor
    roh = descriptor.split("#", 1)[0]
    if "*" in roh:
        return descriptor
    if not _XPUB_RE.search(roh):
        return descriptor
    erweitert = re.sub(
        r"([xyztuv]pub[1-9A-HJ-NP-Za-km-z]+)(?=[,)])",
        r"\1/<0;1>/*",
        roh,
    )
    if erweitert == roh:
        return descriptor
    try:
        from embit.descriptor.checksum import add_checksum

        return add_checksum(erweitert)
    except Exception:
        return erweitert


def deskriptoren_aus_text(text: str) -> list[str]:
    """
    Zieht brauchbare Output-Deskriptoren aus beliebigem Text.

    Nimmt, was Wallets tatsächlich herausgeben: eine nackte Zeile, den
    JSON-Export von Sparrow oder Specter, die Liste aus ``listdescriptors``.
    Empfangs- und Change-Kette werden zu einer mehrpfadigen Form vereinigt.
    Fehlt die Wildcard-Ableitung (Specter auf Kontoebene), wird
    ``/<0;1>/*`` ergänzt.

    Geliefert wird nur, was sich auch ableiten lässt — ein Deskriptor, der
    später still keine Adressen ergibt, hilft niemandem. Private Schlüssel
    führen zur Ablehnung des gesamten Textes: Sie gehören nicht in ein
    Werkzeug, das nur zusieht.
    """
    if not text or _XPRV_RE.search(text):
        return []

    kandidaten = _deskriptor_kandidaten(text)
    if not kandidaten:
        return []

    brauchbar: list[str] = []
    for kandidat in _vereinige_paare(kandidaten):
        kandidat = _ergaenze_standard_ableitung(kandidat)
        if main.derive_descriptor_addresses(kandidat, max_addresses=2):
            if kandidat not in brauchbar:
                brauchbar.append(kandidat)
    return brauchbar


def _script_aus_deskriptor(descriptor: str) -> str:
    """
    Skripttyp aus der Hülle: wsh(…) oder sh(wsh(…)).

    Ein reines sh(multi(…)) — Legacy-P2SH-Multisig — wird hier nicht
    unterstützt und bleibt leer, statt als sh-wsh durchzugehen.
    """
    text = (descriptor or "").strip().lower()
    if text.startswith("sh(wsh("):
        return "sh-wsh"
    if text.startswith("wsh("):
        return "wsh"
    return ""


def _normalize_multisig_script(value: str | None) -> str:
    """Vereinheitlicht den Multisig-Skripttyp; Unbekanntes bleibt stehen."""
    text = (value or "").strip().lower().replace("_", "-")
    if text in ("wsh", "p2wsh", "segwit"):
        return "wsh"
    if text in ("sh-wsh", "shwsh", "p2sh-p2wsh", "nested"):
        return "sh-wsh"
    return text


@dataclass
class WalletEntry:
    """
    Ein konfiguriertes Wallet — Single-Sig oder Multisig.

    Single-Sig: *xpub* gesetzt, *threshold* None, *xpubs* leer.
    Multisig: *xpubs* mit den Cosignern, *threshold* mit M; alternativ nur
    *descriptor*, aus dem beides abgeleitet wird.

    Beide liegen bewusst in einem Modell: Sie stehen in derselben Liste,
    tragen denselben Namen und dieselbe Scan-Tiefe. Ein zweites Parallelmodell
    müsste jede Stelle doppelt bedienen.
    """

    xpub: str = ""
    name: str = ""
    script_type: str = "auto"
    max_addresses: int = DEFAULT_MAX_ADDRESSES
    #: Cosigner einer Multisig-Wallet.
    xpubs: list[str] = field(default_factory=list)
    #: M einer m-aus-n-Wallet.
    threshold: int | None = None
    #: Output-Deskriptor — die kanonische Form einer Multisig-Wallet.
    descriptor: str = ""
    #: Vom Deskriptor gemeldeter Skripttyp (p2wsh, p2tr, p2sh). Wird in
    #: __post_init__ gefüllt und ist bei Taproot die einzige verlässliche
    #: Angabe — „wsh" stünde dort schlicht falsch.
    script_typ_wirksam: str = ""

    def __post_init__(self):
        self.xpub = (self.xpub or "").strip()
        self.name = (self.name or "").strip()
        self.descriptor = (self.descriptor or "").strip()
        self.xpubs = [x.strip() for x in (self.xpubs or []) if x and x.strip()]
        self.max_addresses = max(2, int(self.max_addresses))

        # Aus dem Deskriptor ergänzen, was nicht ausdrücklich angegeben ist.
        # Er ist die knappere Schreibweise, nicht die schwächere.
        if self.descriptor:
            if not self.xpubs:
                self.xpubs = extract_xpubs_from_text(self.descriptor)
            if self.threshold is None:
                self.threshold = _threshold_aus_deskriptor(self.descriptor)
            # Ein ausdrücklich gesetzter, gültiger Skripttyp gewinnt; sonst
            # zählt die Hülle des Deskriptors.
            abgeleitet = _script_aus_deskriptor(self.descriptor)
            if abgeleitet and _normalize_multisig_script(
                self.script_type
            ) not in MULTISIG_SCRIPT_CHOICES:
                self.script_type = abgeleitet

        if self.is_multisig:
            self.script_type = _normalize_multisig_script(self.script_type) or "wsh"
            # Kurzform in die kanonische Form überführen. Gespeichert und
            # abgeleitet wird immer über den Deskriptor: Nur er kann auch
            # Taproot und Miniscript ausdrücken.
            if not self.descriptor:
                self.descriptor = deskriptor_aus_kurzform(
                    self.threshold, self.script_type, self.xpubs
                )
            self._uebernimm_aus_deskriptor()
        else:
            self.script_type = main.normalize_script_type(self.script_type)

    def _uebernimm_aus_deskriptor(self) -> None:
        """
        Schlüssel und Skripttyp aus dem geparsten Deskriptor übernehmen.

        Der Parser weiß mehr als eine Zeichenketten-Prüfung: Bei Taproot
        gehört der interne Schlüssel dazu, und der Skripttyp steht als
        ``p2wsh``/``p2tr``/``p2sh`` fest, statt aus der Schreibweise geraten
        zu werden. Lässt sich der Deskriptor nicht lesen, bleibt alles, wie es
        angegeben wurde — die Prüfung meldet ihn dann als ungültig.
        """
        desc = main.parse_deskriptor(self.descriptor)
        if desc is None:
            return
        try:
            schluessel = [str(k) for k in desc.keys]
        except Exception:
            schluessel = []
        gefunden = [x for k in schluessel for x in extract_xpubs_from_text(k)]
        if gefunden:
            self.xpubs = list(dict.fromkeys(gefunden))
        try:
            self.script_typ_wirksam = desc.scriptpubkey_type()
        except Exception:
            self.script_typ_wirksam = ""

        # Bei Taproot wäre „wsh" oder „auto" schlicht falsch. Der Parser weiß
        # es genau; die Kurzform-Angabe wird deshalb überschrieben, sobald ein
        # Deskriptor vorliegt.
        nach_typ = {"p2wsh": "wsh", "p2sh": "sh-wsh", "p2tr": "tr"}
        if self.script_typ_wirksam in nach_typ:
            self.script_type = nach_typ[self.script_typ_wirksam]

    # -- Art ----------------------------------------------------------------

    @property
    def is_multisig(self) -> bool:
        """Mehrere Cosigner, ein Schwellwert oder ein Deskriptor."""
        return bool(self.xpubs) or self.threshold is not None or bool(self.descriptor)

    @property
    def cosigner_count(self) -> int:
        return len(self.xpubs)

    @property
    def alle_xpubs(self) -> list[str]:
        """Alle Schlüssel des Eintrags — einer bei Single-Sig, n bei Multisig."""
        return list(self.xpubs) if self.is_multisig else ([self.xpub] if self.xpub else [])

    # -- Darstellung --------------------------------------------------------

    @property
    def prefix(self) -> str:
        quelle = self.xpubs[0] if self.is_multisig and self.xpubs else self.xpub
        return quelle[:4].lower()

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.is_multisig:
            return f"Multisig {self.threshold or '?'}/{self.cosigner_count or '?'}"
        return main._default_wallet_name(self.xpub)

    def masked_xpub(self, head: int = 6, tail: int = 4) -> str:
        """
        Gekürzte Darstellung für die Oberfläche — nie der volle Schlüssel.

        Bei Multisig der erste Cosigner; die vollständige Liste liefert
        masked_xpubs().
        """
        quelle = self.xpubs[0] if self.is_multisig and self.xpubs else self.xpub
        return _maskiere(quelle, head, tail)

    def masked_xpubs(self, head: int = 6, tail: int = 4) -> list[str]:
        """Alle Schlüssel maskiert — für die Anzeige einer Multisig-Wallet."""
        return [_maskiere(x, head, tail) for x in self.alle_xpubs]

    # -- Prüfung ------------------------------------------------------------

    def is_valid(self) -> bool:
        if not self.is_multisig:
            return bool(self.xpub) and main._hdkey_for_xpub(self.xpub) is not None
        # Über den Parser statt über Einzelprüfungen: Er akzeptiert genau das,
        # was sich anschließend auch ableiten lässt — einschließlich Taproot
        # und Miniscript, wo „M zwischen 1 und Zahl der Cosigner" gar keine
        # sinnvolle Bedingung mehr ist.
        return main.parse_deskriptor(self.descriptor) is not None

    @property
    def analyse_schluessel(self) -> str:
        """
        Der Schlüssel, unter dem dieses Wallet im Analyse-Stack geführt wird.

        Bei Single-Sig der XPUB, bei Multisig der Deskriptor. Beide sind
        Zeichenketten, aus denen sich Adressen ableiten lassen — mehr braucht
        der Stack nicht zu wissen.
        """
        return self.descriptor if self.is_multisig else self.xpub

    # -- Kennung ------------------------------------------------------------

    def wallet_id(self) -> str:
        """
        Stabile Kennung für Cache-Dateien und die Oberfläche.

        Bei Multisig aus M, Skripttyp und den *sortierten* Schlüsselkennungen —
        nicht aus der Reihenfolge in der Datei. Wer die Cosigner umsortiert,
        meint dieselbe Wallet und soll denselben Cache behalten.
        """
        # Dieselbe Funktion, die auch den Namen der Cache-Datei bestimmt —
        # sonst suchte die Oberfläche unter einer anderen Kennung als der,
        # unter der der Scan geschrieben hat. Sie ist deskriptorfähig und
        # richtet sich bei Multisig nach der ersten abgeleiteten Adresse.
        return main._xpub_cache_key(self.analyse_schluessel)


def _maskiere(wert: str, head: int = 6, tail: int = 4) -> str:
    if not wert:
        return ""
    if len(wert) <= head + tail:
        return wert
    return f"{wert[:head]}…{wert[-tail:]}"


def schluessel_kennung(xpub: str) -> str | None:
    """
    Kennung des Schlüsselmaterials, unabhängig vom SLIP-132-Prefix.

    zpub und xpub desselben Schlüssels ergeben dieselbe Kennung. Nötig, weil
    beide Fassungen bei gesetztem Skripttyp exakt dieselben Adressen ableiten
    — stünden sie beide in der Liste, wäre die Wallet-Zuordnung mehrdeutig und
    Berichte wiesen Beträge dem falschen Wallet zu.
    """
    hd = main._hdkey_for_xpub(xpub)
    if hd is None:
        return None
    try:
        return (hd.key.serialize() + hd.chain_code).hex()
    except Exception:
        return None


def erste_empfangsadresse(entry: WalletEntry) -> str:
    """
    Empfangsadresse #0 — die Adresse, die jede Wallet-Software als erste zeigt.

    Damit lässt sich von Hand nachsehen, ob zwei Einträge wirklich dasselbe
    Konto meinen.

    Für Multisig leer: Die Adresse ergibt sich dort aus allen Cosignern
    zusammen (wsh/sortedmulti), und diese Ableitung gibt es noch nicht. Die
    Single-Sig-Adresse eines einzelnen Cosigners wäre nicht bloß nutzlos,
    sondern falsch — wer darauf einzahlt, zahlt an einen der Mitunterzeichner
    allein.
    """
    if entry.is_multisig:
        return ""
    hd = main._hdkey_for_xpub(entry.xpub)
    if hd is None:
        return ""
    try:
        encoder = main._encoders_for_xpub(entry.xpub, entry.script_type)[0]
        return encoder(hd.derive([0, 0]).key).address()
    except Exception:
        return ""


def validate_wallets(entries: list[WalletEntry]) -> tuple[list[str], list[str]]:
    """
    Prüft eine Wallet-Liste.

    Liefert *(fehler, warnungen)*. Fehler verhindern das Speichern — die Daten
    wären schlicht unbrauchbar. Warnungen beschreiben Folgen, die der Benutzer
    kennen sollte, aber selbst abwägen darf; sie lassen sich bestätigen.
    """
    fehler: list[str] = []
    warnungen: list[str] = []
    gesehen: set[str] = set()
    kennungen: dict[str, WalletEntry] = {}

    #: Schlüssel, die als Cosigner einer Multisig-Wallet auftauchen.
    cosigner: dict[str, WalletEntry] = {}

    for index, entry in enumerate(entries, start=1):
        if entry.is_multisig:
            fehler.extend(_pruefe_multisig(index, entry))
            for xpub in entry.xpubs:
                cosigner.setdefault(xpub, entry)
            continue

        if not entry.xpub:
            fehler.append(f"Wallet {index}: kein XPUB angegeben.")
            continue
        if not entry.is_valid():
            fehler.append(
                f"Wallet {index} ({entry.masked_xpub()}): kein gültiger "
                "Extended Public Key."
            )
            continue
        if entry.xpub in gesehen:
            fehler.append(
                f"Wallet {index} ({entry.masked_xpub()}): dieser XPUB steht "
                "bereits in der Liste."
            )
        gesehen.add(entry.xpub)

        kennung = schluessel_kennung(entry.xpub)
        if kennung:
            zwilling = kennungen.get(kennung)
            if zwilling is not None:
                adresse = erste_empfangsadresse(entry)
                warnungen.append(
                    f"„{entry.display_name}“ und „{zwilling.display_name}“ "
                    "enthalten denselben Schlüssel, nur mit anderem Prefix "
                    f"({zwilling.prefix} und {entry.prefix}). "
                    + (f"Beide beginnen bei {adresse}. " if adresse else "")
                    + "Verschiedene Konten aus demselben Seed sind davon nicht "
                    "betroffen — die haben unterschiedliche Schlüssel. Hier "
                    "handelt es sich um dasselbe Konto in zwei Fassungen: "
                    "Beträge würden in Summen und im Steuer-Export doppelt "
                    "gezählt."
                )
            else:
                kennungen[kennung] = entry

        if entry.script_type not in SCRIPT_TYPE_CHOICES:
            fehler.append(
                f"Wallet {index}: unbekannter Skripttyp '{entry.script_type}'."
            )

    # Ein Cosigner, der zusätzlich als eigenes Single-Sig-Wallet steht: Seine
    # Beträge zählten in Summen und im Steuer-Export doppelt — einmal für sich,
    # einmal als Teil der Multisig.
    for xpub in sorted(gesehen & set(cosigner)):
        multisig = cosigner[xpub]
        fehler.append(
            f"{_maskiere(xpub)} steht einzeln in der Liste und ist zugleich "
            f"Cosigner von „{multisig.display_name}“. Beträge würden doppelt "
            "gezählt — bitte eines von beidem entfernen."
        )

    namen = [e.name for e in entries if e.name]
    doppelte = {n for n in namen if namen.count(n) > 1}
    for name in sorted(doppelte):
        fehler.append(
            f"Der Name „{name}“ ist mehrfach vergeben — Berichte wären nicht "
            "mehr zuzuordnen."
        )
    return fehler, warnungen


def _pruefe_multisig(index: int, entry: WalletEntry) -> list[str]:
    """
    Prüft eine Multisig-Wallet.

    Maßgeblich ist, ob sich der Deskriptor lesen und ableiten lässt — nicht,
    ob er einer bestimmten Form entspricht. Alles andere wäre eine Vorschrift
    darüber, wie jemand seine Wallet einrichten darf.
    """
    fehler: list[str] = []
    name = entry.display_name

    if not entry.descriptor:
        if entry.xpubs and entry.script_type not in MULTISIG_SCRIPT_CHOICES:
            fehler.append(
                f"Wallet {index} („{name}“): Skripttyp "
                f"'{entry.script_type}' lässt sich als Kurzform nicht "
                f"ausdrücken — erlaubt sind {' und '.join(MULTISIG_SCRIPT_CHOICES)}. "
                "Für Taproot und Policies mit Zeitschloss WALLET_n_DESC "
                "benutzen."
            )
        else:
            fehler.append(
                f"Wallet {index} („{name}“): weder WALLET_n_DESC noch "
                "WALLET_n_M mit WALLET_n_XPUBS angegeben."
            )
        return fehler

    if entry.threshold is not None and entry.xpubs:
        if not 1 <= entry.threshold <= len(entry.xpubs):
            fehler.append(
                f"Wallet {index} („{name}“): {entry.threshold} von "
                f"{len(entry.xpubs)} Unterschriften ist nicht möglich."
            )
            return fehler

    if main.parse_deskriptor(entry.descriptor) is None:
        fehler.append(
            f"Wallet {index} („{name}“): der Deskriptor lässt sich nicht "
            "lesen. Aggregierte Taproot-Schlüssel (musig) werden nicht "
            "unterstützt; alles andere deutet auf einen Tippfehler oder eine "
            "falsche Prüfsumme hin."
        )
        return fehler

    if not main.derive_descriptor_addresses(entry.descriptor, max_addresses=2):
        fehler.append(
            f"Wallet {index} („{name}“): aus dem Deskriptor lässt sich keine "
            "Adresse ableiten."
        )

    doppelt = {x for x in entry.xpubs if entry.xpubs.count(x) > 1}
    for xpub in sorted(doppelt):
        fehler.append(
            f"Wallet {index} („{name}“): {_maskiere(xpub)} steht mehrfach "
            "unter den Cosignern."
        )
    return fehler


# ---------------------------------------------------------------------------
# Block-Explorer (eigene mempool.space-Instanz)
# ---------------------------------------------------------------------------

#: Endungen, die eine Instanz im eigenen Netz kennzeichnen.
#:
#: `.ts.net` gehört dazu: Tailscale-Adressen sind nur im eigenen Tailnet
#: erreichbar, sehen aber wie eine öffentliche Domain aus.
_LOKALE_ENDUNGEN = (
    ".onion", ".local", ".lan", ".home", ".internal", ".home.arpa",
    ".ts.net", ".tailscale.net",
)
_LOKALE_NAMEN = ("localhost", "127.0.0.1", "::1", "[::1]")

#: Bekannte öffentliche Dienste. Nur hier ist „fremd“ eine Feststellung und
#: keine Vermutung — bei jeder anderen Domain kann es die eigene sein.
_OEFFENTLICHE_DIENSTE = (
    "mempool.space", "blockstream.info", "mempool.emzy.de",
    "mempool.bitaroo.net", "blockchair.com", "btcscan.org",
    "blockchain.com", "blockchain.info", "oxt.me",
)


def normalize_mempool_url(roh: str) -> str:
    """
    Prüft und säubert die Adresse — rein formal, ohne Verbindungsaufbau.

    Ein Verbindungstest wäre schon der erste Abruf, den der Benutzer
    vielleicht gar nicht will. Ungültige Eingaben werfen ValueError.
    """
    text = (roh or "").strip()
    if not text:
        return ""

    from urllib.parse import urlparse

    # Das Schema muss geprüft werden, *bevor* https:// ergänzt wird. Sonst
    # würde aus „javascript:alert(1)“ ein scheinbar gültiges
    # „https://javascript:alert(1)“ und die Prüfung liefe ins Leere.
    if "://" in text:
        schema, _, rest = text.partition("://")
        if schema.lower() not in ("http", "https"):
            raise ValueError(
                f"Nur http und https sind zulässig, nicht „{schema}“."
            )
        if not rest.strip("/"):
            raise ValueError("Die Adresse enthält keinen Host.")
    else:
        kopf, _, rest = text.partition(":")
        # Ein Doppelpunkt ohne Schema ist nur als Portangabe zulässig.
        if rest and not rest.split("/")[0].isdigit():
            raise ValueError(f"Nur http und https sind zulässig, nicht „{kopf}“.")
        text = f"https://{text}"

    zerlegt = urlparse(text)
    if not zerlegt.netloc:
        raise ValueError("Die Adresse enthält keinen Host.")
    if zerlegt.query or zerlegt.fragment:
        raise ValueError("Die Adresse darf keine Parameter enthalten.")

    # Erst jetzt kürzen — sonst verstümmelt der Schrägstrich das Schema.
    return f"{zerlegt.scheme}://{zerlegt.netloc}{zerlegt.path.rstrip('/')}"


def _host_ohne_port(host: str) -> str:
    """Trennt den Port ab — auch bei IPv6 in eckigen Klammern."""
    name = host.strip().lower()
    if name.startswith("["):
        return name.split("]")[0] + "]"
    return name.rsplit(":", 1)[0] if ":" in name else name


def _ist_lokal(host: str) -> bool:
    """Erreichbar nur im eigenen Netz? Bewusst großzügig ausgelegt."""
    name = _host_ohne_port(host)
    if name in _LOKALE_NAMEN or name.endswith(_LOKALE_ENDUNGEN):
        return True
    if name.startswith(("192.168.", "10.", "127.", "169.254.")):
        return True

    # IPv6: Loopback sowie Unique Local Addresses (fc00::/7)
    if name.startswith("[") and (name.startswith(("[fd", "[fc")) or name == "[::1]"):
        return True

    def _oktett(stelle: int) -> int | None:
        try:
            return int(name.split(".")[stelle])
        except (IndexError, ValueError):
            return None

    # 172.16.0.0/12
    if name.startswith("172."):
        zweites = _oktett(1)
        return zweites is not None and 16 <= zweites <= 31

    # 100.64.0.0/10 — Tailscale vergibt Adressen aus diesem Bereich.
    if name.startswith("100."):
        zweites = _oktett(1)
        return zweites is not None and 64 <= zweites <= 127

    # Ein Name ohne Punkt ist ein Host im eigenen Netz, kein öffentlicher.
    return "." not in name


def _ist_bekannter_dienst(host: str) -> bool:
    name = _host_ohne_port(host)
    return any(
        name == dienst or name.endswith(f".{dienst}")
        for dienst in _OEFFENTLICHE_DIENSTE
    )


def mempool_info(roh: str) -> dict:
    """
    Beschreibt die konfigurierte Instanz für die Oberfläche.

    Ohne Konfiguration werden **keine** Verweise angezeigt. Es gibt bewusst
    keinen Standardwert auf mempool.space: Jeder solche Klick verriete einem
    fremden Server, welche Transaktion und welche Adresse den Benutzer
    interessieren — bei einer Wallet-Adresse also die Wallet-Zugehörigkeit.
    Wer das will, trägt die Adresse ausdrücklich ein.
    """
    try:
        url = normalize_mempool_url(roh)
    except ValueError:
        url = ""

    if not url:
        return {
            "url": "",
            "configured": False,
            "local": False,
            "stufe": "keine",
            "host": "",
            "hinweis": (
                "Nicht eingetragen. Ohne Instanz erscheinen keine Verweise nach "
                "außen — jeder solche Aufruf würde verraten, welche Adressen "
                "dich interessieren."
            ),
        }

    from urllib.parse import urlparse

    host = urlparse(url).netloc
    lokal = _ist_lokal(host)
    bekannter_dienst = _ist_bekannter_dienst(host)

    # Drei Stufen statt zwei. Ob eine öffentlich erreichbare Domain die eigene
    # Instanz ist, kann das Programm nicht wissen — mempool.meinedomain.de
    # sieht aus wie ein fremder Dienst und ist doch der eigene Server. Nur bei
    # bekannten öffentlichen Diensten ist „fremd“ eine Feststellung.
    if lokal:
        stufe, hinweis = "lokal", (
            "Nur in deinem Netz erreichbar — Aufrufe bleiben bei dir."
        )
    elif bekannter_dienst:
        stufe, hinweis = "fremd", (
            "Bekannter öffentlicher Dienst: Jeder Verweis verrät ihm, welche "
            "Transaktion oder Adresse du ansiehst."
        )
    else:
        stufe, hinweis = "oeffentlich", (
            "Öffentlich erreichbare Adresse. Ist das deine eigene Instanz, ist "
            "alles in Ordnung — andernfalls erfährt dieser Server, was du "
            "ansiehst."
        )

    return {
        "url": url,
        "configured": True,
        "local": lokal,
        "stufe": stufe,
        "host": host,
        "hinweis": hinweis,
    }


# ---------------------------------------------------------------------------
# .env-Datei
# ---------------------------------------------------------------------------

_ANHANG_MARKER = "# --- von der Web-Oberfläche verwaltet ---"

_VERSUCH_ANFANG = (
    "# Erfolgreicher Verbindungsversuch am ",
    "# Erfolgloser Verbindungsversuch am ",
)


def _ist_verbindungsversuch(zeile: str) -> bool:
    text = zeile.strip()
    return text.startswith(_VERSUCH_ANFANG[0].strip()) or text.startswith(
        _VERSUCH_ANFANG[1].strip()
    )


@dataclass
class EnvFile:
    """
    Strukturerhaltender Zugriff auf eine .env.

    set()/unset() ändern nur die betroffene Zeile; alles andere bleibt, wie es
    war. save() schreibt atomar und legt vorher eine Sicherung an.
    """

    path: Path
    lines: list[str] = field(default_factory=list)
    runtime_values: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str) -> "EnvFile":
        path = Path(path)
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
        else:
            lines = []
        return cls(path=path, lines=lines)

    # -- lesen --------------------------------------------------------------

    @staticmethod
    def _split(line: str) -> tuple[str, str] | None:
        """Zerlegt eine echte Zuweisungszeile; Kommentare ergeben None."""
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            return None
        key, _, value = stripped.partition("=")
        return key.strip(), value.strip().strip('"').strip("'")

    def values(self) -> dict[str, str]:
        """Alle gesetzten Werte — spätere Zeilen überschreiben frühere."""
        result: dict[str, str] = {}
        for line in self.lines:
            paar = self._split(line)
            if paar:
                result[paar[0]] = paar[1]
        result.update(self.runtime_values)
        return result

    def get(self, key: str, default: str = "") -> str:
        return self.values().get(key, default)

    # -- schreiben ----------------------------------------------------------

    def _index_of(self, key: str) -> int | None:
        treffer = None
        for nummer, line in enumerate(self.lines):
            paar = self._split(line)
            if paar and paar[0] == key:
                treffer = nummer
        return treffer

    def set(self, key: str, value: str) -> None:
        """Setzt einen Wert; vorhandene Zeilen werden an Ort und Stelle ersetzt."""
        neue_zeile = f"{key}={value}"
        stelle = self._index_of(key)
        if stelle is not None:
            self.lines[stelle] = neue_zeile
            return

        if _ANHANG_MARKER not in self.lines:
            if self.lines and self.lines[-1].strip():
                self.lines.append("")
            self.lines.append(_ANHANG_MARKER)
        self.lines.append(neue_zeile)

    def unset(self, key: str) -> None:
        """Entfernt einen Schlüssel vollständig."""
        self.lines = [
            line
            for line in self.lines
            if not (self._split(line) and self._split(line)[0] == key)
        ]

    def apply(self, updates: dict[str, str | None]) -> None:
        """Mehrere Änderungen; None entfernt den Schlüssel."""
        for key, value in updates.items():
            if value is None:
                self.unset(key)
            else:
                self.set(key, value)

    def kommentar_vor(self, schluessel: tuple[str, ...] | list[str], kommentar: str) -> None:
        """
        Setzt eine Kommentarzeile unmittelbar vor den ersten der Schlüssel.

        Ein älterer Verbindungsversuch-Kommentar an derselben Stelle wird
        ersetzt, damit die Datei nicht zuwächst.
        """
        erste = None
        for key in schluessel:
            i = self._index_of(key)
            if i is not None:
                erste = i
                break
        if erste is None:
            return
        while erste > 0 and _ist_verbindungsversuch(self.lines[erste - 1]):
            del self.lines[erste - 1]
            erste -= 1
        text = kommentar if kommentar.lstrip().startswith("#") else f"# {kommentar}"
        self.lines.insert(erste, text)

    def render(self) -> str:
        return "\n".join(self.lines) + "\n"

    def save(self, *, backup: bool = True) -> Path | None:
        """
        Schreibt atomar (temporäre Datei + os.replace) und legt vorher eine
        Sicherung an. Gibt den Pfad der Sicherung zurück, falls eine entstand.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sicherung: Path | None = None
        if backup and self.path.is_file():
            sicherung = self.path.with_suffix(self.path.suffix + ".bak")
            shutil.copy2(self.path, sicherung)

        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(self.render(), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, self.path)
        return sicherung


# ---------------------------------------------------------------------------
# Wallets ⇄ .env
# ---------------------------------------------------------------------------


def _split_list(raw: str, trenner: str) -> list[str]:
    return [teil.strip() for teil in raw.split(trenner)] if raw.strip() else []


#: Felder eines Wallet-Blocks.
_BLOCK_FELDER = ("NAME", "XPUB", "XPUBS", "DESC", "M", "SCRIPT", "MAX_ADDRESSES")

_BLOCK_RE = re.compile(r"^WALLET_(\d+)_([A-Z_]+)$")


def _block_indizes(values: dict[str, str]) -> set[int]:
    """
    Alle Nummern, zu denen ein Wallet-Block existiert.

    Es wird über die tatsächlich vorhandenen Schlüssel gegangen, nicht über
    einen festen Zahlenbereich: Eine harte Obergrenze würde WALLET_100_… still
    verschlucken.
    """
    indizes: set[int] = set()
    for key, wert in values.items():
        treffer = _BLOCK_RE.match(key)
        if treffer and treffer.group(2) in _BLOCK_FELDER and wert.strip():
            indizes.add(int(treffer.group(1)))
    return indizes


def bloecke_nach_luecke(values: dict[str, str]) -> list[int]:
    """
    Block-Nummern hinter der ersten Lücke.

    Die Liste endet an der ersten fehlenden Nummer — WALLET_0 und WALLET_2
    ohne WALLET_1 ergibt genau ein Wallet. Damit das nicht unbemerkt bleibt,
    lassen sich die übergangenen Nummern hier abfragen und anzeigen.
    """
    vorhandene = _block_indizes(values)
    if not vorhandene:
        return []
    ende = 0
    while ende in vorhandene:
        ende += 1
    return sorted(n for n in vorhandene if n > ende)


def _block_eintrag(values: dict[str, str], nummer: int, standard: int) -> WalletEntry:
    """Baut einen WalletEntry aus einem WALLET_n_*-Block."""

    def feld(name: str) -> str:
        return values.get(f"WALLET_{nummer}_{name}", "").strip()

    try:
        tiefe = int(feld("MAX_ADDRESSES")) if feld("MAX_ADDRESSES") else standard
    except ValueError:
        tiefe = standard

    schwelle: int | None = None
    if feld("M"):
        try:
            schwelle = int(feld("M"))
        except ValueError:
            # Unlesbares M nicht verschlucken: Der Eintrag gilt als Multisig
            # und fällt in der Prüfung mit klarer Meldung durch.
            schwelle = -1

    return WalletEntry(
        xpub=feld("XPUB"),
        name=feld("NAME"),
        script_type=feld("SCRIPT") or "auto",
        max_addresses=tiefe,
        xpubs=feld("XPUBS").split(),
        threshold=schwelle,
        descriptor=feld("DESC"),
    )


def _hat_bloecke(values: dict[str, str]) -> bool:
    """Ist das neue Format in Gebrauch? Entscheidet Block 0."""
    return any(
        values.get(f"WALLET_0_{feld}", "").strip()
        for feld in ("XPUB", "XPUBS", "DESC")
    )


def read_wallets(env: EnvFile) -> list[WalletEntry]:
    """
    Liest die konfigurierten Wallets aus einer .env.

    Die einzige Quelle für Wallet-Konfiguration — CLI wie Oberfläche. Sobald
    ein WALLET_0_XPUB / _XPUBS / _DESC vorhanden ist, gilt ausschließlich das
    Blockformat; die alten Sammelzeilen werden dann ignoriert, damit nicht
    zwei Schreibweisen nebeneinander stehen und sich widersprechen.
    """
    values = env.values()
    standard = _standard_tiefe(values)

    if _hat_bloecke(values):
        vorhandene = _block_indizes(values)
        eintraege: list[WalletEntry] = []
        nummer = 0
        while nummer in vorhandene:
            eintraege.append(_block_eintrag(values, nummer, standard))
            nummer += 1
        return eintraege

    return _read_legacy_wallets(values, standard)


def _standard_tiefe(values: dict[str, str]) -> int:
    roh = values.get("MAX_ADDRESSES", "").strip()
    try:
        return int(roh) if roh else DEFAULT_MAX_ADDRESSES
    except ValueError:
        return DEFAULT_MAX_ADDRESSES


def _read_legacy_wallets(values: dict[str, str], standard: int) -> list[WalletEntry]:
    """
    Die alten Schreibweisen: XPUBS-Sammelzeile oder XPUB_0/XPUB_1.

    Bleibt erhalten, damit eine bestehende .env ohne Zutun weiterläuft. Beim
    nächsten Speichern aus der Oberfläche wird sie ins Blockformat überführt.
    """
    xpubs = main._xpubs_from_env(values) or []
    namen = main._wallet_names_from_env(values) or []
    typen = main._script_types_from_env(values) or []

    tiefen_roh = _split_list(values.get("MAX_ADDRESSES_PER_XPUB", ""), "|")
    standard_tiefe = values.get("MAX_ADDRESSES", "").strip()
    try:
        standard = int(standard_tiefe) if standard_tiefe else DEFAULT_MAX_ADDRESSES
    except ValueError:
        standard = DEFAULT_MAX_ADDRESSES

    eintraege: list[WalletEntry] = []
    for index, xpub in enumerate(xpubs):
        try:
            tiefe = int(tiefen_roh[index]) if index < len(tiefen_roh) else standard
        except ValueError:
            tiefe = standard
        eintraege.append(
            WalletEntry(
                xpub=xpub,
                name=namen[index] if index < len(namen) else "",
                script_type=typen[index] if index < len(typen) else "auto",
                max_addresses=tiefe,
            )
        )
    return eintraege


#: Sammelzeilen der alten Schreibweise.
_LEGACY_SAMMELZEILEN = (
    "XPUBS", "WALLET_NAMES", "SCRIPT_TYPES", "MAX_ADDRESSES_PER_XPUB",
)

#: Präfixe der alten indizierten Schreibweise.
_LEGACY_INDIZIERT = ("XPUB", "WALLET_NAME", "SCRIPT_TYPE")

_LEGACY_INDEX_RE = re.compile(
    r"^(" + "|".join(_LEGACY_INDIZIERT) + r")_(\d+)$"
)


def _alte_schluessel(values: dict[str, str]) -> list[str]:
    """
    Jeder Wallet-Schlüssel, den es zu entfernen gilt.

    Über die tatsächlich vorhandenen Schlüssel, nicht über einen festen
    Zahlenbereich: Ein `range(20)` ließe XPUB_23 stehen, und beim nächsten
    Lesen stünden zwei Wahrheiten in der Datei.
    """
    treffer = [key for key in values if key in _LEGACY_SAMMELZEILEN]
    treffer += [key for key in values if _LEGACY_INDEX_RE.match(key)]
    treffer += [key for key in values if _BLOCK_RE.match(key)]
    return treffer


def wallet_updates(
    entries: list[WalletEntry],
    vorhandene: dict[str, str] | None = None,
) -> dict[str, str | None]:
    """
    Übersetzt eine Wallet-Liste in .env-Zuweisungen.

    Geschrieben wird ausschließlich das Blockformat (WALLET_0_NAME …). Alle
    alten Schreibweisen werden entfernt, damit nicht zwei nebeneinander stehen
    und sich widersprechen — dazu gehören auch Blöcke einer früheren, längeren
    Liste.

    *vorhandene* sind die aktuellen .env-Werte; ohne sie lassen sich nur die
    fest benannten Sammelzeilen abräumen.
    """
    updates: dict[str, str | None] = {}
    for key in _alte_schluessel(vorhandene or {}):
        updates[key] = None
    for key in _LEGACY_SAMMELZEILEN:
        updates[key] = None

    for nummer, eintrag in enumerate(entries):
        praefix = f"WALLET_{nummer}"
        updates[f"{praefix}_NAME"] = eintrag.display_name
        if eintrag.is_multisig:
            # Immer der Deskriptor: Die Kurzform (_M/_SCRIPT/_XPUBS) bleibt als
            # Eingabe erlaubt, kann aber weder Taproot noch Miniscript
            # ausdrücken. Zwei Darstellungen nebeneinander wären zwei
            # Wahrheiten — bei Abweichung gälte welche?
            updates[f"{praefix}_DESC"] = eintrag.descriptor
        else:
            updates[f"{praefix}_XPUB"] = eintrag.xpub
            updates[f"{praefix}_SCRIPT"] = eintrag.script_type
        updates[f"{praefix}_MAX_ADDRESSES"] = str(eintrag.max_addresses)

    return updates


class BestaetigungNoetig(Exception):
    """
    Die Liste ist speicherbar, hat aber Folgen, die bestätigt werden sollten.

    Trägt die Warnungen mit, damit die Oberfläche sie anzeigen und ein
    „Trotzdem speichern“ anbieten kann.
    """

    def __init__(self, warnungen: list[str]):
        super().__init__(" ".join(warnungen))
        self.warnungen = warnungen


def write_wallets(
    env: EnvFile,
    entries: list[WalletEntry],
    *,
    bestaetigt: bool = False,
) -> Path | None:
    """
    Schreibt die Wallet-Liste in die .env.

    Fehler brechen immer ab. Warnungen brechen ab, bis *bestaetigt* gesetzt
    ist — die Entscheidung darüber gehört dem Benutzer, nicht dem Programm.
    """
    fehler, warnungen = validate_wallets(entries)
    if fehler:
        raise ValueError("; ".join(fehler))
    if warnungen and not bestaetigt:
        raise BestaetigungNoetig(warnungen)
    env.apply(wallet_updates(entries, env.values()))
    return env.save()
