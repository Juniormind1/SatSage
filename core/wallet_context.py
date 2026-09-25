"""
WalletContext, Adress-Seeding und externer Adress-Auflösungs-Cache.

Aus main.py ausgelagert (Slice 3 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.

Cache-Loader und Disk-Gate liegen in core.xpub_cache.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from display import abbrev_display

from core.derivation import (
    DEFAULT_MAX_ADDRESSES,
    _encoders_for_xpub,
    _hdkey_for_xpub,
    _script_address,
    derive_addresses,
    normalize_script_type,
    register_script_types,
)

# Python 3.10-kompatibel (datetime.UTC erst ab 3.11)
UTC = timezone.utc

#: Trace-Suchtiefe; Spiegel von main.MAX_TRACE_ADDRESS_SEARCH (Default-Arg).
MAX_TRACE_ADDRESS_SEARCH = 500

_xpub_address_positive_cache: set[tuple[str, str]] = set()
_xpub_address_negative_cache: set[tuple[str, str, int]] = set()

EXTERNAL_ADDRESS_CACHE_NAME = "external_addresses.json"
_external_cache_dir: Path | None = None
_external_cache_fingerprint: str = ""
_external_cache_max_index: int = 0
_known_external_addresses: set[str] = set()
_xpub_disk_negatives: dict[str, set[str]] = {}
_known_wallet_addresses: dict[str, str] = {}
_external_cache_lock = threading.Lock()


def _sync_main_scalar_facade() -> None:
    """Hält main._external_cache_* nach Rebind auf demselben Stand (Tests/Fassade)."""
    import sys

    main_mod = sys.modules.get("main")
    if main_mod is None:
        return
    main_mod._external_cache_dir = _external_cache_dir
    main_mod._external_cache_fingerprint = _external_cache_fingerprint
    main_mod._external_cache_max_index = _external_cache_max_index


def _xpub_set_fingerprint(xpubs: list[str]) -> str:
    """Stabiler Schlüssel für die aktuelle XPUB-Kombination."""
    return hashlib.sha256("\n".join(sorted(xpubs)).encode("utf-8")).hexdigest()


def _xpub_fingerprint(xpub: str) -> str:
    return hashlib.sha256(xpub.encode("utf-8")).hexdigest()


def _external_address_cache_path(cache_dir: Path) -> Path:
    return cache_dir / EXTERNAL_ADDRESS_CACHE_NAME


def init_external_address_cache(
    cache_dir: Path,
    xpubs: list[str],
    max_index: int = MAX_TRACE_ADDRESS_SEARCH,
) -> tuple[int, int, int]:
    """
    Lädt Adress-Auflösungs-Cache von Platte (extern, XPUB-Negativ, Wallet-Positiv).
    Ungültig bei anderem XPUB-Set oder kleinerem max_index als aktuell gefordert.
    """
    global _external_cache_dir, _external_cache_fingerprint, _external_cache_max_index

    fingerprint = _xpub_set_fingerprint(xpubs)
    _external_cache_dir = cache_dir
    _external_cache_fingerprint = fingerprint
    _external_cache_max_index = 0
    # In-place clear — Fassade in main behält dieselbe Objekt-Identität.
    _known_external_addresses.clear()
    _xpub_disk_negatives.clear()
    _known_wallet_addresses.clear()
    _sync_main_scalar_facade()


    path = _external_address_cache_path(cache_dir)
    if not path.is_file():
        return 0, 0, 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0, 0

    if data.get("xpub_set_hash") != fingerprint:
        return 0, 0, 0

    file_max = int(data.get("max_index", 0))
    if file_max < max_index:
        return 0, 0, 0

    addresses = data.get("addresses", [])
    if not isinstance(addresses, list):
        return 0, 0, 0

    _known_external_addresses.clear()
    _known_external_addresses.update(str(addr) for addr in addresses if addr)
    _external_cache_max_index = file_max
    _sync_main_scalar_facade()

    xpub_negs = data.get("xpub_negatives", {})
    if isinstance(xpub_negs, dict):
        for xpub in xpubs:
            fp = _xpub_fingerprint(xpub)
            addrs = xpub_negs.get(fp, [])
            if not isinstance(addrs, list):
                continue
            bucket = {str(a) for a in addrs if a}
            if bucket:
                _xpub_disk_negatives[fp] = bucket
                for addr in bucket:
                    _xpub_address_negative_cache.add((xpub, addr, file_max))


    known = data.get("known_wallet_addresses", {})
    if isinstance(known, dict):
        _known_wallet_addresses.clear()
        _known_wallet_addresses.update({
            str(addr): str(fp)
            for addr, fp in known.items()
            if addr and fp
        })

    _sync_main_scalar_facade()
    return len(_known_external_addresses), sum(
        len(v) for v in _xpub_disk_negatives.values()
    ), len(_known_wallet_addresses)


def _is_known_external_address(
    address: str,
    xpubs: list[str],
    max_search: int,
) -> bool:
    if not address or not _known_external_addresses:
        return False
    if _xpub_set_fingerprint(xpubs) != _external_cache_fingerprint:
        return False
    if max_search > _external_cache_max_index:
        return False
    return address in _known_external_addresses


def _persist_external_address_cache() -> None:
    if _external_cache_dir is None:
        return
    from core.xpub_cache import _dump_cache_json, cache_disk_write_allowed

    if not cache_disk_write_allowed(_external_cache_dir):
        return
    _external_cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "xpub_set_hash": _external_cache_fingerprint,
        "max_index": _external_cache_max_index,
        "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "addresses": sorted(_known_external_addresses),
        "xpub_negatives": {
            fp: sorted(addrs)
            for fp, addrs in sorted(_xpub_disk_negatives.items())
            if addrs
        },
        "known_wallet_addresses": dict(sorted(_known_wallet_addresses.items())),
    }
    path = _external_address_cache_path(_external_cache_dir)
    path.write_text(_dump_cache_json(payload), encoding="utf-8")


def _mark_external_address(
    address: str,
    xpubs: list[str],
    max_search: int,
) -> None:
    global _external_cache_max_index
    if not address:
        return
    fingerprint = _xpub_set_fingerprint(xpubs)
    with _external_cache_lock:
        if fingerprint != _external_cache_fingerprint:
            return
        _known_external_addresses.add(address)
        _known_wallet_addresses.pop(address, None)
        _external_cache_max_index = max(_external_cache_max_index, max_search)
        _sync_main_scalar_facade()
        _persist_external_address_cache()


def _remove_external_address_if_present(address: str) -> None:
    with _external_cache_lock:
        if address not in _known_external_addresses:
            return
        _known_external_addresses.discard(address)
        _persist_external_address_cache()


def _mark_xpub_negative(xpub: str, address: str, max_index: int) -> None:
    global _external_cache_max_index
    if not xpub or not address:
        return
    fp = _xpub_fingerprint(xpub)
    with _external_cache_lock:
        if _external_cache_dir is None:
            return
        bucket = _xpub_disk_negatives.setdefault(fp, set())
        if address in bucket and max_index <= _external_cache_max_index:
            return
        bucket.add(address)
        _external_cache_max_index = max(_external_cache_max_index, max_index)
        _sync_main_scalar_facade()
        _persist_external_address_cache()


def _is_known_xpub_negative(xpub: str, address: str, max_index: int) -> bool:
    if not xpub or not address:
        return False
    if max_index > _external_cache_max_index:
        return False
    return address in _xpub_disk_negatives.get(_xpub_fingerprint(xpub), set())


def _remove_xpub_negative_if_present(xpub: str, address: str) -> None:
    fp = _xpub_fingerprint(xpub)
    with _external_cache_lock:
        bucket = _xpub_disk_negatives.get(fp)
        if not bucket or address not in bucket:
            return
        bucket.discard(address)
        if not bucket:
            _xpub_disk_negatives.pop(fp, None)
        _persist_external_address_cache()




def _mark_wallet_address_positive(xpub: str, address: str) -> None:
    """Persistiert eine per XPUB verifizierte Wallet-Adresse (ohne API-Scan)."""
    if not xpub or not address:
        return
    fp = _xpub_fingerprint(xpub)
    with _external_cache_lock:
        if _external_cache_dir is None:
            return
        if _known_wallet_addresses.get(address) == fp:
            return
        _known_wallet_addresses[address] = fp
        _persist_external_address_cache()


def _remove_wallet_address_positive_if_present(address: str) -> None:
    with _external_cache_lock:
        if address not in _known_wallet_addresses:
            return
        _known_wallet_addresses.pop(address, None)
        _persist_external_address_cache()


def seed_wallet_addresses_from_resolution_cache(
    wallet: "WalletContext | None",
    xpubs: list[str],
) -> int:
    """Lädt verifizierte Wallet-Adressen aus dem Auflösungs-Cache ins Mapping."""
    if not wallet or not _known_wallet_addresses:
        return 0
    fp_to_xpub = {_xpub_fingerprint(xpub): xpub for xpub in xpubs}
    loaded = 0
    for address, fp in _known_wallet_addresses.items():
        xpub = fp_to_xpub.get(fp)
        if xpub:
            _register_wallet_address(wallet, xpub, address)
            loaded += 1
    return loaded


def _register_wallet_address(
    wallet: "WalletContext",
    xpub: str,
    address: str,
) -> None:
    """Merkt eine Adresse im Wallet-Mapping und im XPUB-Treffer-Cache."""
    label = wallet.names_by_xpub.get(xpub)
    if not label or not address:
        return
    wallet.address_to_wallet[address] = label
    wallet.address_to_xpub[address] = xpub
    _xpub_address_positive_cache.add((xpub, address))


def _address_belongs_to_xpub(xpub: str, address: str, max_index: int) -> bool:
    """Prüft, ob eine Adresse aus dem XPUB stammt (bis max_index pro Chain)."""
    if (xpub, address) in _xpub_address_positive_cache:
        return True
    neg_key = (xpub, address, max_index)
    if neg_key in _xpub_address_negative_cache:
        return False
    if _is_known_xpub_negative(xpub, address, max_index):
        _xpub_address_negative_cache.add(neg_key)
        return False

    hd = _hdkey_for_xpub(xpub)
    if hd is None:
        return False

    for encoder in _encoders_for_xpub(xpub):
        for change in (0, 1):
            for i in range(max_index):
                try:
                    child = hd.derive([change, i])
                    if _script_address(encoder(child.key)) == address:
                        _xpub_address_positive_cache.add((xpub, address))
                        return True
                except Exception:
                    break
    _xpub_address_negative_cache.add(neg_key)
    _mark_xpub_negative(xpub, address, max_index)
    return False


def _default_wallet_name(xpub: str) -> str:
    """Fallback-Bezeichnung: SHA256-Hex des XPUB-Strings."""
    return hashlib.sha256(xpub.encode()).hexdigest()


@dataclass
class WalletContext:
    """Zuordnung XPUB/Adresse → Anzeigename für Berichte."""
    xpubs: list[str]
    names_by_xpub: dict[str, str]
    address_to_wallet: dict[str, str]
    address_to_xpub: dict[str, str]
    max_addresses_by_xpub: dict[str, int]
    script_type_by_xpub: dict[str, str] = field(default_factory=dict)

    def xpub_label(self, xpub: str) -> str:
        return self.names_by_xpub.get(xpub, _default_wallet_name(xpub))

    def script_type_for(self, xpub: str) -> str:
        return self.script_type_by_xpub.get(xpub, "auto")

    def max_addresses_for(
        self,
        xpub: str,
        default: int = DEFAULT_MAX_ADDRESSES,
    ) -> int:
        return self.max_addresses_by_xpub.get(xpub, default)

    def xpub_for_address(self, address: str) -> str | None:
        return self.address_to_xpub.get(address)

    def own_label(self, address: str) -> str | None:
        return self.address_to_wallet.get(address)

    def resolve_address(
        self,
        address: str,
        max_search: int = MAX_TRACE_ADDRESS_SEARCH,
    ) -> str | None:
        """
        Ordnet eine Adresse einem Wallet zu.
        Nutzt den Scan-Cache; bei Bedarf erweiterte XPUB-Suche für die Trace-Analyse.
        """
        if not address:
            return None
        cached = self.address_to_wallet.get(address)
        if cached:
            return cached
        if _is_known_external_address(address, self.xpubs, max_search):
            return None
        for xpub in self.xpubs:
            # Pro Wallet nicht tiefer als nötig + max_search (Gap/Trace).
            xpub_cap = max(
                int(self.max_addresses_for(xpub, max_search) or 0),
                int(max_search or 0),
            )
            if xpub_cap <= 0:
                xpub_cap = max_search
            if _address_belongs_to_xpub(xpub, address, xpub_cap):
                _register_wallet_address(self, xpub, address)
                _mark_wallet_address_positive(xpub, address)
                _remove_external_address_if_present(address)
                _remove_xpub_negative_if_present(xpub, address)
                return self.names_by_xpub[xpub]
        _mark_external_address(address, self.xpubs, max_search)
        return None

    def is_own_address(self, address: str) -> bool:
        return self.resolve_address(address) is not None

    def own_labels(self, addresses: list[str]) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for addr in addresses:
            label = self.resolve_address(addr)
            if label and label not in seen:
                labels.append(label)
                seen.add(label)
        return labels

    def format_addresses(self, addresses: list[str]) -> str:
        """Eigene Adressen als Wallet-Namen, sonst Rohadresse."""
        if not addresses:
            return "?"
        parts: list[str] = []
        for addr in addresses:
            label = self.resolve_address(addr)
            parts.append(label if label else abbrev_display(addr))
        return ", ".join(parts)

    def scope_label(self) -> str:
        names = [self.xpub_label(x) for x in self.xpubs]
        if len(names) == 1:
            return names[0]
        return " + ".join(names)


def _max_addresses_for_xpub(
    xpub: str,
    wallet: WalletContext | None = None,
    default: int = DEFAULT_MAX_ADDRESSES,
) -> int:
    if wallet:
        return wallet.max_addresses_for(xpub, default)
    return default


def build_wallet_context(
    xpubs: list[str],
    wallet_names: list[str] | None = None,
    max_addresses: int = DEFAULT_MAX_ADDRESSES,
    max_addresses_per_xpub: list[int] | None = None,
    script_types: list[str] | None = None,
) -> WalletContext:
    """Baut Namenszuordnung aus XPUBs und optionalen CLI-Namen."""
    names_by_xpub: dict[str, str] = {}
    max_by_xpub: dict[str, int] = {}
    type_by_xpub: dict[str, str] = {}
    for index, xpub in enumerate(xpubs):
        if wallet_names and index < len(wallet_names):
            names_by_xpub[xpub] = wallet_names[index]
        else:
            names_by_xpub[xpub] = _default_wallet_name(xpub)
        if max_addresses_per_xpub and index < len(max_addresses_per_xpub):
            max_by_xpub[xpub] = max_addresses_per_xpub[index]
        else:
            max_by_xpub[xpub] = max_addresses
        if script_types and index < len(script_types):
            type_by_xpub[xpub] = normalize_script_type(script_types[index])
        else:
            type_by_xpub[xpub] = "auto"

    # Vor der Ableitung registrieren: Aufrufstellen ohne WalletContext
    # (derive_address_at_index, _address_belongs_to_xpub, consolidate.py)
    # lesen den Typ aus dieser Registry.
    register_script_types(type_by_xpub)

    address_to_wallet: dict[str, str] = {}
    address_to_xpub: dict[str, str] = {}
    for xpub in xpubs:
        wallet_name = names_by_xpub[xpub]
        xpub_max = max_by_xpub[xpub]
        for addr in derive_addresses(xpub, xpub_max, script_type=type_by_xpub[xpub]):
            address_to_wallet[addr] = wallet_name
            address_to_xpub[addr] = xpub

    return WalletContext(
        xpubs=xpubs,
        names_by_xpub=names_by_xpub,
        address_to_wallet=address_to_wallet,
        address_to_xpub=address_to_xpub,
        max_addresses_by_xpub=max_by_xpub,
        script_type_by_xpub=type_by_xpub,
    )




def _seed_wallet_addresses_from_cache(
    wallet: WalletContext | None,
    cached_by_xpub: dict[str, list[dict]],
    *,
    cache_dir: Path | None = None,
    xpubs: list[str] | None = None,
) -> None:
    """UTXO- und scanned_addresses aus dem Scan-Cache ins Wallet-Mapping."""
    if not wallet:
        return
    targets = xpubs or list(cached_by_xpub.keys())
    for xpub in targets:
        if xpub not in wallet.names_by_xpub:
            continue
        for utxo in cached_by_xpub.get(xpub, []):
            addr = utxo.get("address")
            if addr:
                _register_wallet_address(wallet, xpub, str(addr))
        if cache_dir is None:
            continue
        from core.xpub_cache import load_xpub_cache_entry

        entry = load_xpub_cache_entry(xpub, cache_dir)
        if not entry:
            continue
        for addr in entry["raw"].get("scanned_addresses", []):
            if addr:
                _register_wallet_address(wallet, xpub, str(addr))
        for utxo in entry.get("utxos", []):
            addr = utxo.get("address")
            if addr:
                _register_wallet_address(wallet, xpub, str(addr))


def seed_wallet_addresses_from_utxo_cache(
    wallet: WalletContext | None,
    xpubs: list[str],
    cache_dir: Path,
) -> None:
    """Lädt alle bekannten Wallet-Adressen aus dem UTXO-Flatfile-Cache."""
    from core.xpub_cache import load_xpub_utxo_cache

    cached_by_xpub: dict[str, list[dict]] = {}
    for xpub in xpubs:
        cached = load_xpub_utxo_cache(xpub, cache_dir)
        if cached is not None:
            cached_by_xpub[xpub] = cached
    _seed_wallet_addresses_from_cache(
        wallet,
        cached_by_xpub,
        cache_dir=cache_dir,
        xpubs=xpubs,
    )
    # Ausgegebene Change-Adressen jenseits max_addresses: nicht in utxos[],
    # oft auch nicht im Verlauf — scan_end_index kennt den Scan-Horizont.
    seed_wallet_addresses_from_scan_end(wallet, xpubs, cache_dir)


def seed_wallet_addresses_from_scan_end(
    wallet: WalletContext | None,
    xpubs: list[str],
    cache_dir: Path,
) -> int:
    """
    Leitet Adressen bis ``scan_end_index`` ab und registriert sie.

    Der UTXO-Scan hat diese Indizes bereits geprüft. Ausgegebene Change-
    Adressen stehen danach oft weder in ``utxos[]`` noch im Verlauf (wenn
    der Verlauf nur bis ``max_addresses`` geplant war). ``match_own_address``
    macht absichtlich keine HD-Suche — ohne diesen Seed stuft die Herkunft
    interne Überträge (Change jenseits der Start-Ableitung) als Extern ein.
    """
    if wallet is None:
        return 0
    from core.xpub_cache import load_xpub_cache_entry

    n = 0
    for xpub in xpubs:
        if xpub not in wallet.names_by_xpub:
            continue
        entry = load_xpub_cache_entry(xpub, cache_dir)
        if not entry:
            continue
        try:
            scan_end = int(entry.get("scan_end_index") or 0)
        except (TypeError, ValueError):
            scan_end = 0
        if scan_end <= 0:
            continue
        # derive_addresses: max//2 Indizes je Chain → Indizes 0 .. scan_end-1
        max_addr = max(scan_end * 2, int(wallet.max_addresses_for(xpub) or 0))
        configured = int(wallet.max_addresses_for(xpub) or 0)
        # Schon in build_wallet_context abgedeckt?
        if scan_end <= max(1, configured // 2):
            continue
        script = wallet.script_type_for(xpub)
        for addr in derive_addresses(xpub, max_addr, script_type=script):
            if addr in wallet.address_to_wallet:
                continue
            _register_wallet_address(wallet, xpub, addr)
            n += 1
        if max_addr > configured:
            wallet.max_addresses_by_xpub[xpub] = max_addr
    return n


def seed_wallet_addresses_from_verlauf_cache(
    wallet: WalletContext | None,
    xpubs: list[str],
    cache_dir: Path,
) -> int:
    """
    Adressen aus dem Verlaufs-Cache ins Mapping — **ohne** HD-Suche.

    Nach Gap-Scan liegen oft hunderte Indizes über ``max_addresses`` im
    Verlauf. ``resolve_address`` würde sonst je Adresse bis
    ``MAX_TRACE_ADDRESS_SEARCH`` über alle XPUBs ableiten (Minuten).
    Zugehörigkeit ist hier durch die Cache-Datei pro XPUB bekannt.
    """
    if wallet is None:
        return 0
    from core.xpub_cache import load_xpub_verlauf_cache

    n = 0
    for xpub in xpubs:
        eintraege = load_xpub_verlauf_cache(xpub, cache_dir) or []
        for e in eintraege:
            addr = (e.get("address") or "").strip()
            if not addr:
                continue
            if addr in wallet.address_to_wallet:
                continue
            _register_wallet_address(wallet, xpub, addr)
            n += 1
    return n
