"""
Wallets: Übersicht, Cache-Zustand und Skripttyp-Erkennung.

Liefert Daten für die Oberfläche — keine Ausgabe, keine Prompts.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import main
from core.config import WalletEntry

#: Typen, die beim Erkennen durchprobiert werden. 'auto' ist kein Kandidat.
PROBE_TYPES = ("segwit", "nested", "legacy", "taproot")

SCRIPT_TYPE_LABELS = {
    "auto": "Automatisch",
    "legacy": "Legacy (P2PKH)",
    "nested": "Nested SegWit (P2SH)",
    "segwit": "Native SegWit (bc1q)",
    "taproot": "Taproot (bc1p)",
    # Multisig — die Sortierung der Cosigner folgt BIP-67 (sortedmulti).
    "wsh": "Multisig · Native SegWit (wsh)",
    "sh-wsh": "Multisig · Nested SegWit (sh-wsh)",
    "tr": "Multisig · Taproot (tr)",
}


@dataclass
class WalletSummary:
    """Was die Übersicht über ein Wallet weiß, ohne das Netz zu befragen."""

    entry: WalletEntry
    utxo_count: int = 0
    total_sats: int = 0
    scan_end_index: int | None = None
    has_cache: bool = False
    #: Wann das Wallet zum ersten Mal benutzt wurde — sein Alter. Wird beim
    #: Scan einmalig erhoben und bleibt None, solange das nicht geschehen ist.
    first_seen_ts: int | None = None
    first_seen_height: int | None = None
    #: Unix-Zeit der letzten Cache-Dateiänderung — None ohne Datei.
    cache_mtime: int | None = None
    #: Letzte bekannte Chain-Höhe des UTXO-Scans (v. a. BIP-158), sonst None.
    scan_tip_height: int | None = None
    #: Sparrow/Wasabi-Import: complete | partial | None (kein Export-Import).
    export_import: str | None = None
    #: Verlaufseinträge ohne Adresse (Export-Lücke).
    export_ohne_adresse: int = 0
    #: Verlaufseinträge gesamt (für Tooltip).
    export_verlauf_n: int = 0

    def as_dict(self) -> dict:
        typ = self.entry.script_type
        return {
            "id": eintrag_id(self.entry),
            "name": self.entry.display_name,
            "xpub_masked": self.entry.masked_xpub(),
            "prefix": self.entry.prefix,
            # Multisig: schreibgeschützt in der Oberfläche (Cosigner/.env).
            # Single-Sig-Deskriptoren (wpkh/…) sind normal analysierbar.
            "is_multisig": self.entry.is_multisig,
            "threshold": self.entry.threshold,
            "cosigner_count": self.entry.cosigner_count,
            "xpubs_masked": self.entry.masked_xpubs(),
            "descriptor": bool(self.entry.descriptor),
            "script_type": typ,
            "script_type_label": SCRIPT_TYPE_LABELS.get(typ, typ),
            "script_type_effective": effective_script_type(self.entry),
            "max_addresses": self.entry.max_addresses,
            "read_only": bool(self.entry.read_only),
            "origin": getattr(self.entry, "origin", "") or "",
            "has_cache": self.has_cache,
            "utxo_count": self.utxo_count,
            "total_sats": self.total_sats,
            "scan_end_index": self.scan_end_index,
            "first_seen_ts": self.first_seen_ts,
            "first_seen_height": self.first_seen_height,
            "cache_mtime": self.cache_mtime,
            "scan_tip_height": self.scan_tip_height,
            "export_import": self.export_import,
            "export_ohne_adresse": self.export_ohne_adresse,
            "export_verlauf_n": self.export_verlauf_n,
        }


def effective_script_type(entry: WalletEntry) -> str:
    """
    Welcher Typ tatsächlich zum Tragen kommt.

    Bei 'auto' entscheidet der Prefix — und 'xpub'/'tpub' tragen die
    Information nicht, dort werden alle Typen probiert.
    """
    if entry.is_multisig:
        return entry.script_type
    if entry.script_type != "auto":
        return entry.script_type
    return {
        "zpub": "segwit",
        "vpub": "segwit",
        "ypub": "nested",
        "upub": "nested",
    }.get(entry.prefix, "alle")


def wallet_id(xpub: str) -> str:
    """Stabile Kennung für URLs — derselbe Schlüssel wie beim UTXO-Cache."""
    return main._xpub_cache_key(xpub)


def eintrag_id(entry: WalletEntry) -> str:
    """
    Kennung eines Eintrags — Single-Sig wie Multisig.

    Bei Multisig aus M, Skripttyp und den sortierten Schlüsselkennungen, nicht
    aus einem einzelnen Cosigner: Sonst hätten eine Multisig und ihr Cosigner
    als Einzel-Wallet dieselbe Kennung.
    """
    return entry.wallet_id()


def _adress_basierte_id(schluessel: str, script_type: str | None = None) -> str | None:
    """
    Dieselbe ID-Basis wie Deskriptor-``wallet_id``: SHA256 der lexikografisch
    ersten abgeleiteten Adresse (``derive_addresses`` / max 2).

    Reiner zpub und ``wpkh(…xpub…)`` treffen sich hier — der Cache-Key aus dem
    zpub-String allein tut das nicht.
    """
    import hashlib

    if not schluessel:
        return None
    typ = script_type if script_type and script_type != "auto" else None
    try:
        addrs = main.derive_addresses(schluessel, max_addresses=2, script_type=typ)
    except Exception:
        return None
    if not addrs:
        return None
    grundlage = sorted(addrs)[0]
    return hashlib.sha256(grundlage.encode("utf-8")).hexdigest()[:16]


def abgleich_ids_fuer_eintrag(entry: WalletEntry) -> set[str]:
    """
    Alle IDs, unter denen dieser Eintrag als „schon bekannt“ gelten soll.

    Enthält die normale ``wallet_id`` und die adressbasierte Form — damit
    zpub in der .env und Specter-/Wasabi-Deskriptor denselben Treffer treffen.
    """
    ids = {eintrag_id(entry)}
    key = (entry.analyse_schluessel or "").strip()
    if not key:
        return ids
    adr = _adress_basierte_id(key, entry.script_type)
    if adr:
        ids.add(adr)
    return ids


def singlesig_schluessel_kennungen(entry: WalletEntry) -> set[str]:
    """
    Schlüsselmaterial-Kennungen nur für Single-Sig.

    Multisig-Cosigner absichtlich ausgelassen — sonst würde ein gefundenes
    Einzel-Wallet ausgeblendet, nur weil sein XPUB in einer Multisig steckt
    (oder umgekehrt eine Multisig, deren Cosigner schon einzeln da sind).
    """
    if entry.is_multisig:
        return set()
    from core.config import extract_xpubs_from_text, schluessel_kennung

    out: set[str] = set()
    if entry.xpub:
        k = schluessel_kennung(entry.xpub)
        if k:
            out.add(k)
    if entry.descriptor:
        for x in extract_xpubs_from_text(entry.descriptor):
            k = schluessel_kennung(x)
            if k:
                out.add(k)
    return out


def vorhandene_abgleich(
    entries: list[WalletEntry],
) -> tuple[set[str], set[str]]:
    """``(wallet_ids inkl. Adress-Form, singlesig-Schlüsselkennungen)``."""
    ids: set[str] = set()
    kennungen: set[str] = set()
    for entry in entries:
        ids |= abgleich_ids_fuer_eintrag(entry)
        kennungen |= singlesig_schluessel_kennungen(entry)
    return ids, kennungen


def finde_gleichwertigen_eintrag(
    entries: list[WalletEntry],
    neu: WalletEntry,
) -> WalletEntry | None:
    """
    Vorhandener Eintrag mit demselben Schlüsselmaterial wie *neu*.

    zpub „Cash & Carry“ und Deskriptor „Cash+Carry“ → Treffer.
    """
    neu_ids = abgleich_ids_fuer_eintrag(neu)
    neu_kenn = singlesig_schluessel_kennungen(neu)
    for entry in entries:
        if abgleich_ids_fuer_eintrag(entry) & neu_ids:
            return entry
        alt_kenn = singlesig_schluessel_kennungen(entry)
        if neu_kenn and alt_kenn and neu_kenn == alt_kenn:
            return entry
    return None


def find_entry(entries: list[WalletEntry], kennung: str) -> WalletEntry | None:
    for entry in entries:
        if eintrag_id(entry) == kennung:
            return entry
    # Deskriptor-ID vs. zpub-ID: Adress-Form mitprüfen.
    for entry in entries:
        if kennung in abgleich_ids_fuer_eintrag(entry):
            return entry
    return None


def _export_import_stand(
    entry: WalletEntry, cache_dir: Path,
) -> tuple[str | None, int, int]:
    """
    Status nach Sparrow/Wasabi-Export-Import.

    Rückgabe ``(status, ohne_adresse, verlauf_n)``:
    * ``complete`` — importiert, alle Verlaufs-Adressen zugeordnet (grün)
    * ``partial`` — importiert, einige ohne Adresse (gelb)
    * ``None`` — kein Wallet-Export-Ursprung
    """
    from core.config import WALLET_ORIGIN_WALLET_EXPORT
    from core import export_adressen as adr_mod

    origin = (getattr(entry, "origin", "") or "").strip()
    if origin != WALLET_ORIGIN_WALLET_EXPORT:
        return None, 0, 0
    verlauf = main.load_xpub_verlauf_cache(entry.analyse_schluessel, cache_dir) or []
    n = len(verlauf)
    ohne = len(adr_mod.verlauf_ohne_adresse(verlauf))
    # Nur Deskriptor ohne CSV-Verlauf: Import gilt als vollständig.
    if n == 0:
        return "complete", 0, 0
    if ohne > 0:
        return "partial", ohne, n
    return "complete", 0, n


def summarize(entries: list[WalletEntry], cache_dir: Path) -> list[WalletSummary]:
    """Baut die Übersicht ausschließlich aus dem lokalen Cache."""
    zusammenfassungen: list[WalletSummary] = []
    for entry in entries:
        eintrag = main.load_xpub_cache_entry(entry.analyse_schluessel, cache_dir)
        utxos = (eintrag or {}).get("utxos") or []
        verlauf = main.load_xpub_verlauf_cache(
            entry.analyse_schluessel, cache_dir
        ) or []
        alter = main.xpub_first_seen(entry.analyse_schluessel, cache_dir) or {}
        cache_mtime = None
        scan_tip = None
        if eintrag is not None:
            pfad = main._xpub_cache_path(entry.analyse_schluessel, cache_dir)
            try:
                cache_mtime = int(pfad.stat().st_mtime)
            except OSError:
                cache_mtime = None
            roh = eintrag.get("raw") or {}
            tip_roh = roh.get("scan_tip_height")
            if tip_roh is None:
                tip_roh = eintrag.get("scan_tip_height")
            if tip_roh is not None:
                try:
                    scan_tip = int(tip_roh)
                except (TypeError, ValueError):
                    scan_tip = None
        elif verlauf:
            # Nur Verlauf (z. B. Wasabi-Store ohne offene UTXOs): mtime der
            # Verlaufsdatei, damit die Oberfläche „hat Daten“ erkennt.
            vpfad = main._xpub_verlauf_cache_path(
                entry.analyse_schluessel, cache_dir
            )
            try:
                cache_mtime = int(vpfad.stat().st_mtime)
            except OSError:
                cache_mtime = None
        exp_status, exp_ohne, exp_n = _export_import_stand(entry, cache_dir)
        zusammenfassungen.append(
            WalletSummary(
                entry=entry,
                # UTXO-Datei oder Verlauf zählt als Cache (Import-Pille / Nav).
                has_cache=eintrag is not None or bool(verlauf),
                utxo_count=len(utxos),
                total_sats=sum(int(u.get("value", 0)) for u in utxos),
                scan_end_index=(eintrag or {}).get("scan_end_index"),
                first_seen_ts=alter.get("time_ts"),
                first_seen_height=alter.get("height"),
                cache_mtime=cache_mtime,
                scan_tip_height=scan_tip,
                export_import=exp_status,
                export_ohne_adresse=exp_ohne,
                export_verlauf_n=exp_n,
            )
        )
    return zusammenfassungen


# ---------------------------------------------------------------------------
# Skripttyp erkennen
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    """Ergebnis der Skripttyp-Erkennung für einen XPUB."""

    script_type: str
    example_address: str
    address_count: int
    hits: int = 0
    checked: bool = False

    def as_dict(self) -> dict:
        return {
            "script_type": self.script_type,
            "label": SCRIPT_TYPE_LABELS.get(self.script_type, self.script_type),
            "example_address": self.example_address,
            "address_count": self.address_count,
            "hits": self.hits,
            "checked": self.checked,
        }


def _receive_addresses(xpub: str, script_type: str, count: int) -> list[str]:
    """
    Empfangsadressen (Kette 0) in Ableitungsreihenfolge — Index 0 zuerst.

    derive_addresses liefert ein ungeordnetes Set über beide Ketten; für den
    Vergleich mit einer Wallet-Software braucht es die Reihenfolge.
    """
    hd = main._hdkey_for_xpub(xpub)
    if hd is None:
        return []

    encoder = main._encoders_for_xpub(xpub, script_type)[0]
    adressen: list[str] = []
    for index in range(count):
        try:
            adressen.append(encoder(hd.derive([0, index]).key).address())
        except Exception:
            break
    return adressen


def probe_script_types(
    xpub: str,
    *,
    sample_size: int = 4,
    has_history=None,
) -> list[ProbeResult]:
    """
    Leitet je Kandidatentyp Beispieladressen ab.

    Ohne *has_history* bleibt es bei der reinen Ableitung — die Oberfläche kann
    die Adressen dann anzeigen, damit man sie mit der eigenen Wallet-Software
    vergleicht. Das braucht keine Verbindung und verrät nichts nach außen.

    Mit *has_history* (Callable[[str], bool]) wird zusätzlich geprüft, welche
    Adressen die Blockchain kennt. Das ist die verlässliche Erkennung, kostet
    aber Abfragen und gibt Adressen an die Datenquelle preis.
    """
    if main._hdkey_for_xpub(xpub) is None:
        raise ValueError("Kein gültiger Extended Public Key.")

    ergebnisse: list[ProbeResult] = []
    for typ in PROBE_TYPES:
        adressen = _receive_addresses(xpub, typ, sample_size)
        if not adressen:
            continue

        ergebnis = ProbeResult(
            script_type=typ,
            # Bewusst die Empfangsadresse #0: Genau die zeigt jede Wallet-
            # Software als erste an, und nur damit ist ein Vergleich möglich.
            example_address=adressen[0],
            address_count=len(adressen),
        )
        if has_history is not None:
            ergebnis.checked = True
            for adresse in adressen:
                try:
                    if has_history(adresse):
                        ergebnis.hits += 1
                except Exception:
                    continue
        ergebnisse.append(ergebnis)

    ergebnisse.sort(key=lambda e: e.hits, reverse=True)
    return ergebnisse


def suggest_script_type(results: list[ProbeResult]) -> str | None:
    """
    Empfiehlt einen Typ — nur wenn genau einer Treffer hat.

    Bei mehreren Treffern (oder keinem) wird bewusst nichts empfohlen: Ein
    falscher Vorschlag ist hier schlimmer als gar keiner, weil er zu einem
    Wallet mit scheinbar 0 UTXO führt.
    """
    mit_treffern = [e for e in results if e.checked and e.hits > 0]
    if len(mit_treffern) == 1:
        return mit_treffern[0].script_type
    return None
