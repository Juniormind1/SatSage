"""
Adress-/XPUB-/Deskriptor-Ableitung (BIP32, Skripttypen, Output-Deskriptoren).

Aus main.py ausgelagert (Slice 3 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.
"""
from __future__ import annotations

from embit.bip32 import HDKey
from embit import script

#: Adress-HRP-Netz (None = embit-Default/main). Gesetzt via set_chain_network().
_CHAIN_NETWORK = None

#: Cache abgeleiteter HDKey-Objekte je XPUB-String.
_hdkey_by_xpub: dict[str, HDKey] = {}

DEFAULT_MAX_ADDRESSES = 50


def _script_address(sc) -> str:
    """Bech32/Base58-Adresse im konfigurierten Chain-Netz."""
    if _CHAIN_NETWORK is None:
        return sc.address()
    return sc.address(_CHAIN_NETWORK)


SCRIPT_TYPE_CHOICES = ("auto", "legacy", "nested", "segwit", "taproot")

#: Konfigurierter Skripttyp je XPUB. Global wie die übrigen Caches in diesem
#: Modul, damit auch Aufrufstellen ohne WalletContext (derive_address_at_index,
#: _address_belongs_to_xpub, consolidate.py) den gewählten Typ berücksichtigen.
_script_type_by_xpub: dict[str, str] = {}

_SCRIPT_TYPE_ALIASES = {
    "auto": "auto",
    "legacy": "legacy", "p2pkh": "legacy", "bip44": "legacy",
    "nested": "nested", "p2sh-p2wpkh": "nested", "bip49": "nested",
    "segwit": "segwit", "p2wpkh": "segwit", "bip84": "segwit", "native": "segwit",
    "taproot": "taproot", "p2tr": "taproot", "bip86": "taproot",
}


def normalize_script_type(value: str | None) -> str:
    """Vereinheitlicht Schreibweisen; alles Unbekannte wird zu 'auto'."""
    if not value:
        return "auto"
    return _SCRIPT_TYPE_ALIASES.get(value.strip().lower(), "auto")


def register_script_types(types_by_xpub: dict[str, str]) -> None:
    """Hinterlegt den konfigurierten Skripttyp je XPUB."""
    for xpub, value in types_by_xpub.items():
        _script_type_by_xpub[xpub] = normalize_script_type(value)


def script_type_for_xpub(xpub: str) -> str:
    """Konfigurierter Skripttyp eines XPUB, sonst 'auto'."""
    return _script_type_by_xpub.get(xpub, "auto")


def _encoders_for_xpub(xpub: str, script_type: str | None = None):
    """
    Wählt Adress-Encoder — bevorzugt nach konfiguriertem Skripttyp,
    sonst nach XPUB-Präfix (SLIP-132).

    SLIP-132 ist optional: Manche Wallets (u. a. Ledger Desktop) exportieren
    immer 'xpub', unabhängig vom tatsächlichen Ableitungspfad. Für 'xpub' und
    'tpub' werden deshalb alle gängigen Typen probiert, statt natives SegWit
    auszulassen — sonst finden solche Wallets keine UTXOs. Wer das nicht
    braucht, setzt den Typ ausdrücklich und spart die überflüssigen Ableitungen.

    Bei auto/xpub kommt **native SegWit (bc1q) zuerst** — Empfangsadresse/QR
    und erste Ableitung sollen modern sein; Legacy/Nested/Taproot folgen für
    den Gap-Scan. Explizit „legacy“ in den Einstellungen erzwingt weiter ``1…``.
    """
    pubkey = lambda pk: script.p2pkh(pk)
    nested = lambda pk: script.p2sh(script.p2wpkh(pk))
    segwit = lambda pk: script.p2wpkh(pk)
    taproot = lambda pk: script.p2tr(pk)

    chosen = normalize_script_type(script_type or script_type_for_xpub(xpub))
    by_type = {
        "legacy": [pubkey],
        "nested": [nested],
        "segwit": [segwit],
        "taproot": [taproot],
    }
    if chosen in by_type:
        return by_type[chosen]

    prefix = xpub[:4].lower()
    mapping = {
        "ypub": [nested],
        "zpub": [segwit],
        "upub": [nested],
        "vpub": [segwit],
    }
    # xpub/tpub/unbekannt: SegWit zuerst (Empfang/QR), dann Rest für den Scan.
    return mapping.get(prefix, [segwit, nested, taproot, pubkey])


def ist_deskriptor(text: str) -> bool:
    """
    Ist das ein Output-Deskriptor und kein einzelner XPUB?

    Klammern entscheiden: Ein Extended Public Key ist Base58 und enthält
    niemals welche. Damit lassen sich beide Formen in denselben Feldern
    führen, ohne sie zu verwechseln.
    """
    text = (text or "").strip()
    return "(" in text and ")" in text


def parse_deskriptor(text: str):
    """
    Liest einen Output-Deskriptor. None, wenn er nicht verwendbar ist.

    Deckt ab, was embit versteht — von ``sh(multi(…))`` über
    ``wsh(sortedmulti(…))`` bis zu Taproot mit ``multi_a`` und
    Miniscript-Policies mit Zeitschlössern (Liana). Nicht unterstützt sind
    aggregierte Taproot-Schlüssel (``musig``); dort scheitert der Parser, und
    das ist besser als eine falsche Adresse.
    """
    if not ist_deskriptor(text):
        return None
    try:
        from embit.descriptor import Descriptor

        return Descriptor.from_string(text.strip())
    except Exception:
        return None


def derive_descriptor_addresses(
    descriptor: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    start_index: int = 0,
) -> set:
    """
    Leitet Adressen aus einem Output-Deskriptor ab.

    Empfang und Change kommen aus den Zweigen des Deskriptors — bei der
    üblichen Schreibweise ``/<0;1>/*`` sind das genau zwei. Hat er nur einen
    Zweig, wird auch nur dieser abgeleitet: embit lieferte für den zweiten
    sonst stillschweigend dieselben Adressen noch einmal.

    Ohne Wildcard (``/*``) beschreibt der Deskriptor eine einzige feste
    Adresse; dann ist die Scan-Tiefe gegenstandslos.
    """
    desc = parse_deskriptor(descriptor)
    if desc is None:
        return set()

    addresses: set[str] = set()
    if not getattr(desc, "is_wildcard", True):
        try:
            addresses.add(_script_address(desc.derive(0)))
        except Exception:
            pass
        return addresses

    zweige = max(1, int(getattr(desc, "num_branches", 1) or 1))
    count_per_chain = max(1, max_addresses // max(1, zweige))
    for zweig in range(zweige):
        for i in range(start_index, start_index + count_per_chain):
            try:
                addresses.add(_script_address(desc.derive(i, branch_index=zweig)))
            except Exception:
                break
    return addresses


def derive_addresses(
    xpub: str,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    start_index: int = 0,
    script_type: str | None = None,
) -> set:
    """
    Leitet Adressen ab — aus einem XPUB (Bip44 + Bip49 + Bip84 + Bip86) oder
    aus einem Output-Deskriptor.

    Beide Formen laufen durch dieselbe Funktion, weil der ganze Analyse-Stack
    seine Wallets über einen Zeichenketten-Schlüssel führt. Für Multisig ist
    dieser Schlüssel der Deskriptor.
    """
    if ist_deskriptor(xpub):
        return derive_descriptor_addresses(xpub, max_addresses, start_index)

    addresses = set()

    try:
        hd = HDKey.from_string(xpub)
    except Exception:
        return addresses

    count_per_chain = max_addresses // 2
    for encoder in _encoders_for_xpub(xpub, script_type):
        for change in (0, 1):
            for i in range(start_index, start_index + count_per_chain):
                try:
                    child = hd.derive([change, i])
                    addr = _script_address(encoder(child.key))
                    addresses.add(addr)
                except Exception:
                    break

    return addresses


def _hdkey_for_xpub(xpub: str) -> HDKey | None:
    cached = _hdkey_by_xpub.get(xpub)
    if cached is not None:
        return cached
    try:
        hd = HDKey.from_string(xpub)
    except Exception:
        return None
    _hdkey_by_xpub[xpub] = hd
    return hd


def derive_addresses_at_index(
    xpub: str,
    change: int,
    index: int,
    script_type: str | None = None,
) -> list[str]:
    """
    Alle Adressformen an (change, index) — für Gap-Scan bei ``xpub``+auto.

    Bei ``auto`` und Prefix ``xpub``/`tpub`` gibt es mehrere mögliche Skripte
    (Legacy/Nested/SegWit/Taproot). Wer nur die erste Form prüft, übersieht
    Wasabi-/BIP84-Coins und bricht nach leerem Legacy-Gap ab.
    """
    if ist_deskriptor(xpub):
        addr = derive_address_at_index(xpub, change, index)
        return [addr] if addr else []

    hd = _hdkey_for_xpub(xpub)
    if hd is None:
        return []
    gefunden: list[str] = []
    gesehen: set[str] = set()
    try:
        child = hd.derive([change, index])
    except Exception:
        return []
    for encoder in _encoders_for_xpub(xpub, script_type):
        try:
            addr = _script_address(encoder(child.key))
        except Exception:
            continue
        if addr and addr not in gesehen:
            gesehen.add(addr)
            gefunden.append(addr)
    return gefunden


def derive_address_at_index(xpub: str, change: int, index: int) -> str | None:
    """
    Leitet eine Wallet-Adresse (change, index) ab.

    Auch aus einem Deskriptor: Der Gap-Scan geht Index für Index vor und
    braucht deshalb den Einzelzugriff. Hat der Deskriptor nur einen Zweig,
    liefert *change* dort keine eigene Kette.

    Bei mehreren Skripttypen (``xpub`` + auto) die erste Form — für den
    Gap-Scan ``derive_addresses_at_index`` verwenden.
    """
    if ist_deskriptor(xpub):
        desc = parse_deskriptor(xpub)
        if desc is None:
            return None
        zweige = max(1, int(getattr(desc, "num_branches", 1) or 1))
        if change >= zweige:
            return None
        try:
            return _script_address(desc.derive(index, branch_index=change))
        except Exception:
            return None

    varianten = derive_addresses_at_index(xpub, change, index)
    return varianten[0] if varianten else None


def derive_receive_address_at_index(
    xpub: str,
    index: int,
    script_type: str | None = None,
) -> tuple[str, int, HDKey | None, object | None] | None:
    """
    Leitet die Empfangsadresse (change=0) am Index ab.

    ``script_type`` überschreibt die XPUB-Registry (Wallet-Einstellung).
    Bei auto/xpub: natives SegWit zuerst (bc1q).
    """
    if ist_deskriptor(xpub):
        addr = derive_address_at_index(xpub, 0, index)
        if not addr:
            return None
        return addr, index, None, None

    try:
        hd = HDKey.from_string(xpub)
    except Exception:
        return None

    for encoder in _encoders_for_xpub(xpub, script_type):
        try:
            child = hd.derive([0, index])
            sc = encoder(child.key)
            return _script_address(sc), index, child, sc
        except Exception:
            continue
    return None

