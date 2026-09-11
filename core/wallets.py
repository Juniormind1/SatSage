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
            "has_cache": self.has_cache,
            "utxo_count": self.utxo_count,
            "total_sats": self.total_sats,
            "scan_end_index": self.scan_end_index,
            "first_seen_ts": self.first_seen_ts,
            "first_seen_height": self.first_seen_height,
            "cache_mtime": self.cache_mtime,
            "scan_tip_height": self.scan_tip_height,
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


def find_entry(entries: list[WalletEntry], kennung: str) -> WalletEntry | None:
    for entry in entries:
        if eintrag_id(entry) == kennung:
            return entry
    return None


def summarize(entries: list[WalletEntry], cache_dir: Path) -> list[WalletSummary]:
    """Baut die Übersicht ausschließlich aus dem lokalen Cache."""
    zusammenfassungen: list[WalletSummary] = []
    for entry in entries:
        eintrag = main.load_xpub_cache_entry(entry.analyse_schluessel, cache_dir)
        utxos = (eintrag or {}).get("utxos") or []
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
        zusammenfassungen.append(
            WalletSummary(
                entry=entry,
                has_cache=eintrag is not None,
                utxo_count=len(utxos),
                total_sats=sum(int(u.get("value", 0)) for u in utxos),
                scan_end_index=(eintrag or {}).get("scan_end_index"),
                first_seen_ts=alter.get("time_ts"),
                first_seen_height=alter.get("height"),
                cache_mtime=cache_mtime,
                scan_tip_height=scan_tip,
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
