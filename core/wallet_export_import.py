"""
Klartext-Wallet-Exporte → Deskriptor, UTXOs, Tx-Verlauf.

Unterstützte Formate (Auto-Erkennung, gemischt erlaubt):

- **Sparrow:** Output-Descriptor, UTXO-/Tx-/Address-CSV
- **Wasabi 2:** View-only-/Hardware-Wallet-JSON (``ExtPubKey`` / Taproot),
  optional Tx-Verlauf/UTXOs aus lokalem ``BitcoinStore`` (Transactions.sqlite),
  optional RPC-Dumps ``listunspentcoins`` / ``listcoins`` / ``gethistory``
- **Specter Desktop:** Wallet-JSON (``recv_descriptor`` / ``change_descriptor``)
  — gleiche Felder wie im Specter-Plugin-``bridge.wallet_to_info``
- **Electrum:** Wallet-JSON unverschlüsselt, nur Öffentliches (xpub); xprv/seed
  werden verworfen, nie gespeichert
- **Bitcoin Core:** Descriptor-Wallets per RPC (``listdescriptors``)

Kein Passwort, keine verschlüsselte Sparrow-``.mv.db``. Passwortgeschützte
Wasabi-Hot-Wallets (``EncryptedSecret``) und verschlüsselte Electrum-Dateien
werden abgelehnt.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import config as config_mod

# Wasabi: Mempool-/unbekannte Höhe in Transactions.sqlite
_WASABI_MEMPOOL_HEIGHT = 2_147_483_646
_WASABI_UNKNOWN_HEIGHT = 2_147_483_647

_TXID_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_OUTPOINT_RE = re.compile(r"^\s*([0-9a-fA-F]{64})\s*[:/]\s*(\d+)\s*$")
_PRIVKEY_HINT = re.compile(
    r"(?i)\b(xprv|yprv|zprv|tprv|vprv|uprv|mnemonic|seed\b|wif)\b"
)
_XPUB_RE = re.compile(
    r"\b([xyztuv]pub[1-9A-HJ-NP-Za-km-z]{50,})\b"
)
_PATH_CHUNK_RE = re.compile(r"(\d+)([hH']?)")


@dataclass
class WalletExportErgebnis:
    """Ergebnis eines multi-Datei-Imports (ein oder mehrere Wallets)."""

    descriptors: list[str] = field(default_factory=list)
    #: Anzeigenamen parallel zu ``descriptors`` (gleich lang oder leer).
    namen: list[str] = field(default_factory=list)
    name_vorschlag: str = ""
    utxos: list[dict] = field(default_factory=list)
    verlauf: list[dict] = field(default_factory=list)
    adressen: list[str] = field(default_factory=list)
    dateien: list[str] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)
    formate: list[str] = field(default_factory=list)
    fehler: str = ""

    @property
    def descriptor(self) -> str:
        return self.descriptors[0] if self.descriptors else ""

    @property
    def ok(self) -> bool:
        return bool(self.descriptors) and not self.fehler

    @property
    def format_label(self) -> str:
        if not self.formate:
            return ""
        uniq = []
        for f in self.formate:
            if f and f not in uniq:
                uniq.append(f)
        return "+".join(uniq)


def parse_wallet_export_dateien(
    dateien: list[dict[str, str]],
) -> WalletExportErgebnis:
    """
    Nimmt ``[{name, text}, …]`` und erkennt Sparrow-/Wasabi-Artefakte.

    Mindestens ein Output-Deskriptor (oder Wasabi-xpub→Deskriptor) muss
    herauskommen. CSV/RPC-Coins allein reichen nicht.
    """
    ergebnis = WalletExportErgebnis()
    if not dateien:
        ergebnis.fehler = "Keine Dateien übergeben."
        return ergebnis

    # (descriptor, anzeigename) — Name aus Datei/Wallet, nie ein globales Feld.
    sparte_deskriptoren: list[tuple[str, str]] = []

    for roh in dateien:
        if not isinstance(roh, dict):
            continue
        name = str(roh.get("name") or "").strip() or "export"
        text = str(roh.get("text") or "")
        pfad_hinweis = str(roh.get("path") or "").strip() or None
        # Suche/Liste: nur Deskriptor, kein Wasabi-Store-Walk (sonst ~10–20 s).
        nur_deskriptor = bool(roh.get("nur_deskriptor"))
        if not text.strip():
            ergebnis.hinweise.append(f"„{name}“ ist leer — übersprungen.")
            continue
        if _sieht_aus_wie_h2_oder_binaer(text):
            ergebnis.fehler = (
                f"„{name}“ wirkt wie eine verschlüsselte Sparrow-Wallet-Datei. "
                "Bitte Klartext-Exporte (Descriptor/CSV) oder Wasabi-View-only-"
                "JSON wählen."
            )
            return ergebnis

        ergebnis.dateien.append(name)
        datei_name = _name_aus_dateiname(name)
        art = _datei_art(name, text)

        # Electrum/Specter/Wasabi: Secrets ggf. im JSON — Parser nehmen nur
        # Öffentliches. Generischer Text mit xprv bleibt tabu.
        if art not in (
            "electrum_wallet", "specter_wallet", "wasabi_wallet",
            "core_descriptors",
        ):
            if _PRIVKEY_HINT.search(text) or config_mod._XPRV_RE.search(text):
                ergebnis.fehler = (
                    f"„{name}“ enthält private Schlüssel oder Seed-Material. "
                    "SatSage nimmt nur öffentliche Deskriptoren und "
                    "View-only-Exporte ohne Secrets."
                )
                return ergebnis

        if art == "csv_utxo":
            utxos, hinw = _parse_utxo_csv(text)
            ergebnis.utxos.extend(utxos)
            ergebnis.hinweise.extend(hinw)
            _merke_format(ergebnis, "sparrow")
        elif art == "csv_tx":
            verlauf, hinw = _parse_tx_csv(text, source="sparrow_csv")
            ergebnis.verlauf.extend(verlauf)
            ergebnis.hinweise.extend(hinw)
            _merke_format(ergebnis, "sparrow")
        elif art == "csv_addr":
            addrs, hinw = _parse_address_csv(text)
            ergebnis.adressen.extend(addrs)
            ergebnis.hinweise.extend(hinw)
            _merke_format(ergebnis, "sparrow")
        elif art == "wasabi_wallet":
            descs, addrs, utxos, verlauf, hinw = _parse_wasabi_wallet_json(
                text,
                name,
                wallet_pfad=pfad_hinweis,
                mit_verlauf=not nur_deskriptor,
            )
            if not descs and hinw:
                hart = next(
                    (
                        h for h in hinw
                        if "passwort" in h.lower()
                        or "ohne extpubkey" in h.lower()
                        or "json ungültig" in h.lower()
                    ),
                    None,
                )
                if hart:
                    ergebnis.fehler = hart
                    return ergebnis
            sparte_deskriptoren.extend(descs)
            ergebnis.adressen.extend(addrs)
            ergebnis.utxos.extend(utxos)
            ergebnis.verlauf.extend(verlauf)
            ergebnis.hinweise.extend(hinw)
            if not ergebnis.name_vorschlag and datei_name:
                ergebnis.name_vorschlag = datei_name
            _merke_format(ergebnis, "wasabi")
        elif art == "specter_wallet":
            descs, hinw = _parse_specter_wallet_json(text, name)
            if not descs and hinw:
                ergebnis.fehler = hinw[0]
                return ergebnis
            sparte_deskriptoren.extend(descs)
            ergebnis.hinweise.extend(hinw)
            if not ergebnis.name_vorschlag and datei_name:
                ergebnis.name_vorschlag = datei_name
            _merke_format(ergebnis, "specter")
        elif art == "electrum_wallet":
            descs, addrs, hinw = _parse_electrum_wallet_json(text, name)
            if not descs and hinw:
                hart = next(
                    (
                        h for h in hinw
                        if "passwort" in h.lower()
                        or "verschlüsselt" in h.lower()
                        or "kein xpub" in h.lower()
                        or "json ungültig" in h.lower()
                    ),
                    None,
                )
                if hart:
                    ergebnis.fehler = hart
                    return ergebnis
            sparte_deskriptoren.extend(descs)
            ergebnis.adressen.extend(addrs)
            ergebnis.hinweise.extend(hinw)
            if not ergebnis.name_vorschlag and datei_name:
                ergebnis.name_vorschlag = datei_name
            _merke_format(ergebnis, "electrum")
        elif art == "core_descriptors":
            descs, hinw = _parse_core_descriptors_json(text, name)
            sparte_deskriptoren.extend(descs)
            ergebnis.hinweise.extend(hinw)
            if not ergebnis.name_vorschlag and datei_name:
                ergebnis.name_vorschlag = datei_name
            _merke_format(ergebnis, "core")
        elif art == "wasabi_coins":
            utxos, verlauf, hinw = _parse_wasabi_coins_json(text)
            ergebnis.utxos.extend(utxos)
            ergebnis.verlauf.extend(verlauf)
            ergebnis.hinweise.extend(hinw)
            _merke_format(ergebnis, "wasabi")
        elif art == "wasabi_history":
            verlauf, hinw = _parse_wasabi_history_json(text)
            ergebnis.verlauf.extend(verlauf)
            ergebnis.hinweise.extend(hinw)
            _merke_format(ergebnis, "wasabi")
        else:
            # Sparrow-Descriptor / generischer Text — Name = Dateiname.
            gefunden = config_mod.deskriptoren_aus_text(text)
            label_json = _sparrow_label_aus_json(text)
            basis = label_json or datei_name or "Sparrow"
            if gefunden:
                _merke_format(ergebnis, "sparrow")
                if len(gefunden) == 1:
                    sparte_deskriptoren.append((gefunden[0], basis))
                else:
                    for i, d in enumerate(gefunden, start=1):
                        sparte_deskriptoren.append((d, f"{basis} #{i}"))
            elif not ergebnis.name_vorschlag and datei_name:
                ergebnis.name_vorschlag = datei_name

    # Reihenfolge behalten, Deskriptor-Duplikate streichen (erster Name gewinnt).
    unique: list[str] = []
    namen: list[str] = []
    for desc, anzeige in sparte_deskriptoren:
        if desc in unique:
            continue
        unique.append(desc)
        namen.append((anzeige or "").strip() or f"Import {len(unique)}")

    if not unique:
        ergebnis.fehler = (
            "Kein Output-Deskriptor / xpub gefunden. Unterstützt: Sparrow-"
            "Descriptor/CSV, Wasabi-View-only-JSON, Specter-Wallet-JSON, "
            "Electrum (unverschlüsselt, nur Öffentliches), Bitcoin-Core-"
            "listdescriptors."
        )
        return ergebnis

    if len(unique) > 1:
        ergebnis.hinweise.append(
            f"{len(unique)} Konten/Deskriptoren erkannt "
            f"({ergebnis.format_label or 'export'}) — werden als getrennte "
            "Wallets angelegt, soweit neu."
        )

    ergebnis.descriptors = unique
    ergebnis.namen = namen
    if not ergebnis.name_vorschlag and namen:
        ergebnis.name_vorschlag = namen[0]

    for u in ergebnis.utxos:
        addr = str(u.get("address") or "").strip()
        if addr and addr not in ergebnis.adressen:
            ergebnis.adressen.append(addr)

    ergebnis.utxos = _dedupe_utxos(ergebnis.utxos)
    ergebnis.verlauf = _dedupe_utxos(ergebnis.verlauf)
    return ergebnis


# Rückwärtskompatibel für bestehende Tests / Aufrufer.
def parse_sparrow_dateien(dateien: list[dict[str, str]]) -> WalletExportErgebnis:
    return parse_wallet_export_dateien(dateien)


def _merke_format(ergebnis: WalletExportErgebnis, name: str) -> None:
    if name not in ergebnis.formate:
        ergebnis.formate.append(name)


def _json_loads(text: str) -> Any:
    """``json.loads`` mit UTF-8-BOM-Toleranz (Wasabi speichert oft mit BOM)."""
    return json.loads((text or "").lstrip("\ufeff"))


def _datei_art(name: str, text: str) -> str:
    lower = name.lower()
    kopf = _csv_header_norm(text)
    stripped = text.lstrip("\ufeff").lstrip()

    # .csv zuerst: nie als Deskriptor/JSON (große Tx-Exports frieren sonst ein).
    if lower.endswith(".csv"):
        if "output" in kopf or "outpoint" in kopf:
            return "csv_utxo"
        if "txid" in kopf or "transaction" in kopf:
            return "csv_tx"
        if "address" in kopf and "value" in kopf:
            return "csv_utxo"
        if "address" in kopf:
            return "csv_addr"
        return "csv_tx"

    if stripped[:1] in "{[":
        try:
            data = _json_loads(stripped)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            art = _json_art(data)
            if art:
                return art

    # Tabellen-Header ohne .csv-Endung (selten)
    if kopf and ("," in kopf or ";" in kopf) and not stripped.lower().startswith(
        ("wpkh", "wsh", "tr(", "sh(", "pkh", "{", "[")
    ):
        if "output" in kopf or "outpoint" in kopf:
            return "csv_utxo"
        if "txid" in kopf or "transaction" in kopf or "value" in kopf:
            return "csv_tx"
        if "address" in kopf:
            return "csv_addr"

    # Deskriptor nur auf kurzem Prefix (Performance bei Fehl-Uploads).
    kopf_text = text if len(text) <= 50_000 else text[:50_000]
    if config_mod.deskriptoren_aus_text(kopf_text):
        return "descriptor"
    if lower.endswith((".txt", ".desc", ".json")):
        return "descriptor"
    return "descriptor"


def _json_art(data: Any) -> str | None:
    """Erkennt Wallet-JSON und RPC-Result-Arrays."""
    if isinstance(data, dict):
        # JSON-RPC-Hülle
        if "result" in data and data.get("result") is not None:
            inner = data["result"]
            art = _json_art(inner)
            if art:
                return art
            # Core listdescriptors: {descriptors: [...]}
            if isinstance(inner, dict) and "descriptors" in inner:
                return "core_descriptors"
        keys = {str(k) for k in data.keys()}
        if "ExtPubKey" in keys or "TaprootExtPubKey" in keys or (
            "HdPubKeys" in keys and "AccountKeyPath" in keys
        ):
            return "wasabi_wallet"
        # Specter Desktop Wallet-JSON (wie Plugin-Bridge)
        if "recv_descriptor" in keys or (
            "keys" in keys and "address_type" in keys and "alias" in keys
        ):
            return "specter_wallet"
        # Electrum Wallet-JSON
        if "wallet_type" in keys and (
            "keystore" in keys or "keystores" in keys or "seed_version" in keys
        ):
            return "electrum_wallet"
        if "descriptors" in keys and isinstance(data.get("descriptors"), list):
            return "core_descriptors"
        # Einzel-Coin
        if _ist_wasabi_coin(data):
            return "wasabi_coins"
        if _ist_wasabi_history(data):
            return "wasabi_history"
    if isinstance(data, list) and data:
        erste = next((x for x in data if isinstance(x, dict)), None)
        if erste is None:
            return None
        if _ist_wasabi_coin(erste):
            return "wasabi_coins"
        if _ist_wasabi_history(erste):
            return "wasabi_history"
        # Core: reine Descriptor-Liste
        if "desc" in {str(k).lower() for k in erste.keys()}:
            return "core_descriptors"
    return None


def _ist_wasabi_coin(obj: dict) -> bool:
    keys = {str(k).lower() for k in obj.keys()}
    if "txid" not in keys:
        return False
    if "index" in keys or "amount" in keys:
        # listunspentcoins / listcoins
        return "anonymityscore" in keys or "keypath" in keys or "address" in keys
    return False


def _ist_wasabi_history(obj: dict) -> bool:
    keys = {str(k).lower() for k in obj.keys()}
    return "tx" in keys and "amount" in keys and (
        "datetime" in keys or "islikelycoinjoin" in keys or "height" in keys
    )


def _deskriptor_brauchbar(desc: str) -> str | None:
    """Normalisiert/prüft Deskriptor; ``None`` wenn unbrauchbar."""
    d = (desc or "").strip()
    if not d:
        return None
    gefunden = config_mod.deskriptoren_aus_text(d)
    if gefunden:
        return gefunden[0]
    try:
        if __import__("main").derive_descriptor_addresses(d, max_addresses=2):
            return d
    except Exception:
        pass
    return None


def _merge_recv_change_deskriptor(recv: str, change: str) -> str | None:
    """
    Specter speichert Empfang ``…/0/*`` und Change ``…/1/*`` getrennt.
    SatSage bevorzugt kombiniert ``…/<0;1>/*``.
    """
    r = (recv or "").strip()
    c = (change or "").strip()
    if not r:
        return None
    if not c:
        return r
    # …/0/*)#chk  →  …/<0;1>/*)#chk   (Checksumme steht hinter der Klammer)
    def _kombiniere(s: str) -> str | None:
        m = re.search(r"/0/\*\)(#[a-z0-9]+)?\s*$", s, re.I)
        if not m:
            return None
        chk = m.group(1) or ""
        base = s[: m.start()]
        return f"{base}/<0;1>/*){chk}"

    komb = _kombiniere(r)
    if not komb:
        return r

    def _ohne_chk(s: str) -> str:
        return re.sub(r"#[a-z0-9]+\s*$", "", s, flags=re.I).strip()

    # Change …/1/* → Stamm wie Empfang …/0/*
    c_stamm = re.sub(r"/1/\*\)(#[a-z0-9]+)?\s*$", "/0/*)", c, flags=re.I)
    r_stamm = re.sub(r"/0/\*\)(#[a-z0-9]+)?\s*$", "/0/*)", r, flags=re.I)
    if _ohne_chk(c_stamm) == _ohne_chk(r_stamm) or "/1/*" in c:
        ok = _deskriptor_brauchbar(komb)
        if ok:
            return ok
        ohne = _ohne_chk(komb)
        return _deskriptor_brauchbar(ohne) or r
    return r


def _parse_specter_wallet_json(
    text: str, dateiname: str,
) -> tuple[list[tuple[str, str]], list[str]]:
    """
    Specter-Desktop-Wallet-JSON → Deskriptoren.

    Feldlayout wie ``specter_plugin…bridge.wallet_to_info`` (recv/change/
    keys/name) — Datei auf Disk statt In-Process-Objekt.
    """
    hinweise: list[str] = []
    try:
        data = _json_loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"„{dateiname}“: JSON ungültig ({exc})."]
    if not isinstance(data, dict):
        return [], [f"„{dateiname}“: kein Specter-Wallet-Objekt."]

    name = (
        str(data.get("name") or data.get("alias") or "").strip()
        or _name_aus_dateiname(dateiname)
        or "Specter"
    )
    recv = str(data.get("recv_descriptor") or "").strip()
    change = str(data.get("change_descriptor") or "").strip()
    descs: list[tuple[str, str]] = []

    komb = _merge_recv_change_deskriptor(recv, change) if recv else None
    if komb:
        ok = _deskriptor_brauchbar(komb)
        if ok:
            descs.append((ok, name))
    if not descs and recv:
        ok = _deskriptor_brauchbar(recv)
        if ok:
            descs.append((ok, f"{name} Empfang" if change else name))
        if change:
            ok_c = _deskriptor_brauchbar(change)
            if ok_c and ok_c not in {d for d, _ in descs}:
                descs.append((ok_c, f"{name} Change"))

    # Fallback: keys[].xpub + derivation (Single-Sig)
    if not descs:
        keys = data.get("keys") or []
        if isinstance(keys, list):
            for k in keys:
                if not isinstance(k, dict):
                    continue
                xpub = str(k.get("xpub") or k.get("original") or "").strip()
                m = _XPUB_RE.search(xpub)
                if not m:
                    continue
                xpub = m.group(1)
                fp = str(k.get("fingerprint") or "").strip().lower()
                fp = re.sub(r"[^0-9a-f]", "", fp)[:8]
                der = str(k.get("derivation") or "").strip()
                origin = _wasabi_origin_path(der) if der else ""
                at = str(data.get("address_type") or k.get("type") or "").lower()
                if "taproot" in at or at in ("p2tr", "tr"):
                    kind = "tr"
                elif "sh-w" in at or "p2sh-p2w" in at or at in ("p2sh_segwit",):
                    # Nested: sh(wpkh(...))
                    desc = _baue_deskriptor("wpkh", fp, origin, xpub)
                    desc = f"sh({desc})" if not desc.startswith("sh(") else desc
                    ok = _deskriptor_brauchbar(desc)
                    if ok:
                        descs.append((ok, name))
                    break
                elif "legacy" in at or at in ("p2pkh",):
                    kind = "pkh"
                else:
                    kind = "wpkh"
                if kind == "pkh":
                    if fp and origin:
                        key = f"[{fp}/{origin}]{xpub}/<0;1>/*"
                    elif origin:
                        key = f"[{origin}]{xpub}/<0;1>/*"
                    else:
                        key = f"{xpub}/<0;1>/*"
                    desc = f"pkh({key})"
                else:
                    desc = _baue_deskriptor(kind, fp, origin, xpub)
                ok = _deskriptor_brauchbar(desc)
                if ok:
                    descs.append((ok, name))
                    break

    if not descs:
        return [], [f"„{dateiname}“: Specter-JSON ohne ableitbaren Deskriptor."]
    return descs, hinweise


def _electrum_xtype_zu_kind(xtype: str, derivation: str) -> str:
    t = (xtype or "").lower().strip()
    if t in ("p2wpkh", "native_segwit", "segwit"):
        return "wpkh"
    if t in ("p2wpkh-p2sh", "p2sh-p2wpkh", "p2wsh-p2sh"):
        return "sh-wpkh"
    if t in ("p2wsh",):
        return "wsh"
    if t in ("p2tr", "taproot"):
        return "tr"
    # Ableitung raten
    d = derivation.replace("h", "'")
    if "86'" in d or "/86/" in d:
        return "tr"
    if "84'" in d or "/84/" in d:
        return "wpkh"
    if "49'" in d or "/49/" in d:
        return "sh-wpkh"
    if "48'" in d:
        return "wsh"
    return "pkh"


def _parse_electrum_wallet_json(
    text: str, dateiname: str,
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """
    Electrum-Wallet-JSON unverschlüsselt → Deskriptor aus xpub.

    ``xprv``/``seed`` werden ignoriert (Hinweis), nie in Deskriptoren übernommen.
    """
    hinweise: list[str] = []
    # Verschlüsselt: Base64-Blob, oft mit BIE1 (``QklF…``)
    stripped = (text or "").lstrip("\ufeff").lstrip()
    if stripped.startswith("QklF") or stripped.startswith("BIE1"):
        return [], [], [
            f"„{dateiname}“: Electrum-Wallet verschlüsselt (Passwort)."
        ]
    if stripped and stripped[0] not in "{[" and "wallet_type" not in stripped[:500]:
        return [], [], [
            f"„{dateiname}“: Electrum-Wallet verschlüsselt oder kein JSON."
        ]
    try:
        data = _json_loads(text)
    except json.JSONDecodeError as exc:
        return [], [], [f"„{dateiname}“: JSON ungültig ({exc})."]
    if not isinstance(data, dict):
        return [], [], [f"„{dateiname}“: kein Electrum-Wallet."]

    if data.get("use_encryption") in (True, 1, "1", "true"):
        return [], [], [
            f"„{dateiname}“: Electrum-Wallet ist kennwortgeschützt."
        ]

    name = _name_aus_dateiname(dateiname) or "Electrum"
    keystores: list[dict] = []
    ks = data.get("keystore")
    if isinstance(ks, dict):
        keystores.append(ks)
    kss = data.get("keystores")
    if isinstance(kss, list):
        keystores.extend([k for k in kss if isinstance(k, dict)])

    descs: list[tuple[str, str]] = []
    for i, k in enumerate(keystores):
        if k.get("xprv") or k.get("seed") or k.get("privkey"):
            hinweise.append(
                "Electrum: privates Material ignoriert — nur öffentlicher xpub."
            )
        xpub = str(k.get("xpub") or "").strip()
        m = _XPUB_RE.search(xpub)
        if not m:
            continue
        xpub = m.group(1)
        fp = str(k.get("root_fingerprint") or k.get("fingerprint") or "").strip()
        fp = re.sub(r"[^0-9a-fA-F]", "", fp)[:8].lower()
        der = str(k.get("derivation") or "").strip()
        origin = _wasabi_origin_path(der) if der else ""
        kind = _electrum_xtype_zu_kind(str(k.get("xtype") or ""), der)
        label = name if len(keystores) == 1 else f"{name} #{i + 1}"
        if kind == "sh-wpkh":
            inner = _baue_deskriptor("wpkh", fp, origin, xpub)
            desc = f"sh({inner})"
        elif kind == "pkh":
            if fp and origin:
                key = f"[{fp}/{origin}]{xpub}/<0;1>/*"
            elif origin:
                key = f"[{origin}]{xpub}/<0;1>/*"
            else:
                key = f"{xpub}/<0;1>/*"
            desc = f"pkh({key})"
        elif kind == "wsh":
            # Multisig bräuchte cosigner — einzeln wsh(sortedmulti) unvollständig
            hinweise.append(
                f"„{dateiname}“: Electrum-Multisig/wsh ohne volle Policy — "
                "übersprungen."
            )
            continue
        else:
            desc = _baue_deskriptor(kind if kind in ("wpkh", "tr") else "wpkh",
                                    fp, origin, xpub)
        ok = _deskriptor_brauchbar(desc)
        if ok:
            descs.append((ok, label))

    # Adressen aus Electrum-JSON (receiving/change)
    adressen: list[str] = []
    addrs_obj = data.get("addresses") or {}
    if isinstance(addrs_obj, dict):
        for kette in ("receiving", "change"):
            lst = addrs_obj.get(kette) or []
            if isinstance(lst, list):
                for a in lst:
                    s = str(a or "").strip()
                    if s and s not in adressen:
                        adressen.append(s)

    if not descs:
        wt = str(data.get("wallet_type") or "")
        if wt == "imported":
            return [], adressen, [
                f"„{dateiname}“: Electrum „imported“ ohne xpub — "
                "nur Adressliste, kein Deskriptor."
            ]
        return [], adressen, [f"„{dateiname}“: Electrum ohne öffentlichen xpub."]
    return descs, adressen, hinweise


def _parse_core_descriptors_json(
    text: str, dateiname: str,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Bitcoin Core ``listdescriptors``-Antwort → Deskriptoren."""
    hinweise: list[str] = []
    try:
        data = _json_loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"„{dateiname}“: JSON ungültig ({exc})."]

    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    items: list = []
    if isinstance(data, dict) and "descriptors" in data:
        items = list(data.get("descriptors") or [])
        wname = str(data.get("wallet_name") or data.get("name") or "").strip()
    elif isinstance(data, list):
        items = data
        wname = ""
    else:
        return [], [f"„{dateiname}“: keine Core-Descriptor-Liste."]

    basis = wname or _name_aus_dateiname(dateiname) or "Core"
    descs: list[tuple[str, str]] = []
    gesehen: set[str] = set()
    for it in items:
        if isinstance(it, str):
            raw = it
            internal = False
            active = True
        elif isinstance(it, dict):
            raw = str(it.get("desc") or it.get("descriptor") or "").strip()
            internal = bool(it.get("internal"))
            active = it.get("active", True) is not False
        else:
            continue
        if not raw or not active:
            continue
        # Nur Empfang (external) primär; Change steckt oft in multipath
        ok = _deskriptor_brauchbar(raw)
        if not ok:
            # Prüfsumme ab und nochmal
            ohne = re.sub(r"#[a-z0-9]+\s*$", "", raw, flags=re.I)
            ok = _deskriptor_brauchbar(ohne)
        if not ok or ok in gesehen:
            continue
        gesehen.add(ok)
        label = basis
        if internal and len(items) > 1:
            label = f"{basis} Change"
        descs.append((ok, label))

    if not descs:
        return [], [f"„{dateiname}“: Core-Descriptors leer oder nicht ableitbar."]
    return descs, hinweise


def _parse_wasabi_wallet_json(
    text: str,
    dateiname: str,
    *,
    wallet_pfad: str | None = None,
    mit_verlauf: bool = True,
) -> tuple[
    list[tuple[str, str]],
    list[str],
    list[dict],
    list[dict],
    list[str],
]:
    """
    View-only / Hardware: ExtPubKey + optional Taproot → Deskriptoren.

    Passwortgeschützte Hot-Wallets (EncryptedSecret) werden abgelehnt.
    Bei ``mit_verlauf=True``: Adressen aus HdPubKeys + UTXOs/Verlauf aus
    lokalem BitcoinStore (Import). Bei ``False`` (Suche/Liste): nur
    Deskriptoren — sonst dauert die Ordnersuche sekundenlang pro Wallet.
    """
    hinweise: list[str] = []
    try:
        data = _json_loads(text)
    except json.JSONDecodeError as exc:
        return ([], [], [], [], [f"„{dateiname}“: JSON ungültig ({exc})."])

    if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
        data = data["result"]
    if not isinstance(data, dict):
        return ([], [], [], [], [f"„{dateiname}“: kein Wasabi-Wallet-Objekt."])

    secret = data.get("EncryptedSecret")
    if secret not in (None, "", "null"):
        return ([], [], [], [], [
            f"„{dateiname}“: passwortgeschützte Wasabi-Hot-Wallet. "
            "SatSage importiert nur View-only-/Hardware-JSON ohne Secret "
            "(in Wasabi als Beobachtungswallet exportieren)."
        ])

    fp = _wasabi_fingerprint(data.get("MasterFingerprint"))
    segwit_path = _wasabi_origin_path(
        data.get("AccountKeyPath") or "84'/0'/0'"
    )
    tap_path = _wasabi_origin_path(
        data.get("TaprootAccountKeyPath") or "86'/0'/0'"
    )
    ext = str(data.get("ExtPubKey") or "").strip()
    tap = str(data.get("TaprootExtPubKey") or "").strip()

    basis = _name_aus_dateiname(dateiname) or "Wasabi"
    descs: list[tuple[str, str]] = []
    if ext and _XPUB_RE.search(ext):
        xpub = _XPUB_RE.search(ext).group(1)
        label = f"{basis} SegWit" if (tap and _XPUB_RE.search(str(tap))) else basis
        descs.append((
            _baue_deskriptor("wpkh", fp, segwit_path, xpub),
            label,
        ))
    if tap and _XPUB_RE.search(tap):
        xpub = _XPUB_RE.search(tap).group(1)
        label = (
            f"{basis} Taproot" if (ext and _XPUB_RE.search(str(ext))) else basis
        )
        descs.append((
            _baue_deskriptor("tr", fp, tap_path, xpub),
            label,
        ))

    if not descs:
        return ([], [], [], [], [
            f"„{dateiname}“: Wasabi-JSON ohne ExtPubKey/TaprootExtPubKey."
        ])

    # Ableitbarkeit prüfen — kaputte xpubs verwerfen.
    brauchbar: list[tuple[str, str]] = []
    for desc, anzeige in descs:
        if config_mod.deskriptoren_aus_text(desc):
            brauchbar.append((config_mod.deskriptoren_aus_text(desc)[0], anzeige))
        elif __import__("main").derive_descriptor_addresses(desc, max_addresses=2):
            brauchbar.append((desc, anzeige))
        else:
            hinweise.append(f"Deskriptor nicht ableitbar, übersprungen: {desc[:48]}…")

    if not brauchbar:
        return ([], [], [], [], [
            f"„{dateiname}“: xpubs vorhanden, aber keine ableitbaren Deskriptoren."
        ])

    if not mit_verlauf:
        # Nur Meta für die Suchliste — kein Store, keine HdPubKey-Ableitung.
        return brauchbar, [], [], [], hinweise

    net_name = ""
    try:
        net_name = str((data.get("BlockchainState") or {}).get("Network") or "")
    except Exception:
        net_name = ""
    embit_net, store_ordner = _wasabi_netzwerk(net_name)

    adressen, labels = _wasabi_adressen_aus_hdpubkeys(
        data.get("HdPubKeys") or [],
        network=embit_net,
    )
    gap = data.get("MinGapLimit")
    if gap is not None:
        try:
            g = int(gap)
            if g > 0:
                hinweise.append(f"Wasabi MinGapLimit={g} (Scan-Tiefe ggf. anpassen).")
        except (TypeError, ValueError):
            pass

    utxos: list[dict] = []
    verlauf: list[dict] = []
    if adressen:
        store_utxo, store_verlauf, store_hinw = _wasabi_coins_aus_bitcoin_store(
            set(adressen),
            store_ordner=store_ordner,
            embit_network=embit_net,
            wallet_pfad=wallet_pfad,
            address_labels=labels,
        )
        utxos.extend(store_utxo)
        verlauf.extend(store_verlauf)
        hinweise.extend(store_hinw)
    else:
        hinweise.append(
            f"„{dateiname}“: keine HdPubKeys-Adressen — Verlauf/UTXO erst nach Scan."
        )

    return brauchbar, adressen, utxos, verlauf, hinweise


def _wasabi_fingerprint(wert: Any) -> str:
    if wert is None or wert == "":
        return ""
    if isinstance(wert, int):
        return f"{wert & 0xFFFFFFFF:08x}"
    s = str(wert).strip()
    if s.startswith("0x"):
        s = s[2:]
    # Dezimal als String?
    if s.isdigit() and len(s) < 10:
        try:
            return f"{int(s) & 0xFFFFFFFF:08x}"
        except ValueError:
            pass
    s = re.sub(r"[^0-9a-fA-F]", "", s)
    if len(s) >= 8:
        return s[:8].lower()
    return s.lower()


def _wasabi_origin_path(path: Any) -> str:
    """``m/84'/0'/0'`` oder ``84'/0'/0'`` → ``84h/0h/0h``."""
    s = str(path or "").strip()
    if s.lower().startswith("m/"):
        s = s[2:]
    teile = []
    for roh in s.split("/"):
        roh = roh.strip()
        if not roh:
            continue
        m = _PATH_CHUNK_RE.fullmatch(roh)
        if not m:
            continue
        num, mark = m.group(1), m.group(2)
        if mark:
            teile.append(f"{num}h")
        else:
            teile.append(num)
    return "/".join(teile)


def _baue_deskriptor(kind: str, fp: str, origin: str, xpub: str) -> str:
    if fp and origin:
        key = f"[{fp}/{origin}]{xpub}/<0;1>/*"
    elif origin:
        key = f"[{origin}]{xpub}/<0;1>/*"
    else:
        key = f"{xpub}/<0;1>/*"
    if kind == "tr":
        return f"tr({key})"
    return f"wpkh({key})"


def _wasabi_netzwerk(name: str) -> tuple[str, str]:
    """→ (embit-Netzwerkname, BitcoinStore-Ordner)."""
    n = (name or "Main").strip().lower()
    if n in ("testnet", "test", "testnet3"):
        return "test", "TestNet"
    if n in ("testnet4",):
        return "test", "TestNet4"
    if n in ("regtest", "reg"):
        return "regtest", "RegTest"
    if n in ("signet",):
        return "signet", "Signet"
    return "main", "Main"


def _wasabi_script_art_aus_pfad(full_path: str) -> str:
    """``84'/0'/0'/0/1`` → wpkh | tr | sh-wpkh | pkh."""
    s = (full_path or "").replace("h", "'").replace("H", "'")
    if s.lower().startswith("m/"):
        s = s[2:]
    teile = [t.strip() for t in s.split("/") if t.strip()]
    if not teile:
        return "wpkh"
    erst = teile[0].rstrip("'hH")
    if erst == "86":
        return "tr"
    if erst == "49":
        return "sh-wpkh"
    if erst == "44":
        return "pkh"
    return "wpkh"


def _wasabi_adresse_aus_pubkey(
    pubkey_hex: str,
    *,
    script_art: str,
    network: str,
) -> str | None:
    try:
        from embit import ec, script
        from embit.networks import NETWORKS
    except ImportError:
        return None
    net = NETWORKS.get(network) or NETWORKS["main"]
    try:
        raw = bytes.fromhex(str(pubkey_hex or "").strip())
        pub = ec.PublicKey.parse(raw)
    except Exception:
        return None
    try:
        if script_art == "tr":
            # x-only: embit p2tr erwartet PublicKey; intern x-only
            return script.p2tr(pub).address(net)
        if script_art == "sh-wpkh":
            return script.p2sh(script.p2wpkh(pub)).address(net)
        if script_art == "pkh":
            return script.p2pkh(pub).address(net)
        return script.p2wpkh(pub).address(net)
    except Exception:
        return None


def _wasabi_adressen_aus_hdpubkeys(
    keys: Any,
    *,
    network: str = "main",
) -> tuple[list[str], dict[str, str]]:
    """
    Adressen + optionale Labels aus HdPubKeys.

    Wasabi speichert oft nur PubKey+FullKeyPath (kein Address-Feld).
    """
    addrs: list[str] = []
    labels: dict[str, str] = {}
    if not isinstance(keys, list):
        return addrs, labels
    gesehen: set[str] = set()
    for eintrag in keys:
        if not isinstance(eintrag, dict):
            continue
        addr = ""
        for k in ("Address", "address", "ScriptPubKey"):
            val = eintrag.get(k)
            if isinstance(val, str) and val.startswith(
                ("bc1", "tb1", "bcrt1", "1", "3")
            ):
                addr = val.strip()
                break
        if not addr:
            pk = str(eintrag.get("PubKey") or "").strip()
            path = str(
                eintrag.get("FullKeyPath")
                or eintrag.get("KeyPath")
                or eintrag.get("keyPath")
                or ""
            )
            if pk:
                addr = _wasabi_adresse_aus_pubkey(
                    pk,
                    script_art=_wasabi_script_art_aus_pfad(path),
                    network=network,
                ) or ""
        if not addr or addr in gesehen:
            continue
        gesehen.add(addr)
        addrs.append(addr)
        lab = str(eintrag.get("Label") or eintrag.get("label") or "").strip()
        if lab:
            labels[addr] = lab
    return addrs, labels


def _wasabi_client_wurzeln(wallet_pfad: str | None) -> list[Path]:
    """Mögliche Wasabi-Client-Verzeichnisse (enthalten BitcoinStore)."""
    out: list[Path] = []
    gesehen: set[str] = set()

    def _add(p: Path) -> None:
        try:
            key = str(p.resolve()) if p.exists() else str(p)
        except OSError:
            key = str(p)
        if key in gesehen:
            return
        gesehen.add(key)
        out.append(p)

    if wallet_pfad:
        p = Path(wallet_pfad).expanduser()
        # .../Client/Wallets/foo.json → Client
        for parent in list(p.parents)[:6]:
            if (parent / "BitcoinStore").is_dir() or parent.name.lower() in (
                "client", "walletwasabi",
            ):
                _add(parent)
                if (parent / "BitcoinStore").is_dir():
                    break
            if (parent.parent / "BitcoinStore").is_dir():
                _add(parent.parent)
                break

    home = Path.home()
    appdata = os.environ.get("APPDATA") or ""
    xdg = os.environ.get("XDG_DATA_HOME") or ""
    for c in (
        home / ".walletwasabi" / "client",
        home / "Library" / "Application Support" / "WalletWasabi" / "Client",
        Path(appdata) / "WalletWasabi" / "Client" if appdata else None,
        Path(xdg) / "WalletWasabi" / "Client" if xdg else None,
        home / ".local" / "share" / "WalletWasabi" / "Client",
    ):
        if c is not None:
            _add(c)
    return out


def _wasabi_sqlite_kandidaten(
    store_ordner: str,
    wallet_pfad: str | None,
) -> list[Path]:
    pfade: list[Path] = []
    gesehen: set[str] = set()
    for client in _wasabi_client_wurzeln(wallet_pfad):
        base = client / "BitcoinStore" / store_ordner
        for rel in (
            Path("ConfirmedTransactions") / "2" / "Transactions.sqlite",
            Path("ConfirmedTransactions") / "1" / "Transactions.sqlite",
            Path("ConfirmedTransactions") / "Transactions.sqlite",
            Path("Mempool") / "Transactions.sqlite",
        ):
            p = base / rel
            try:
                key = str(p.resolve()) if p.exists() else str(p)
            except OSError:
                key = str(p)
            if key in gesehen:
                continue
            gesehen.add(key)
            if p.is_file():
                pfade.append(p)
    return pfade


def _wasabi_coins_aus_bitcoin_store(
    adressen: set[str],
    *,
    store_ordner: str,
    embit_network: str,
    wallet_pfad: str | None,
    address_labels: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    """
    Liest Wasabi ``Transactions.sqlite`` und filtert Outputs zu ``adressen``.

    Liefert UTXOs (unspent) und Verlauf (spent + unspent als Bestandshistorie
    nur unspent in utxos; spent in verlauf).
    """
    hinweise: list[str] = []
    if not adressen:
        return [], [], hinweise

    try:
        from embit.networks import NETWORKS
        from embit.transaction import Transaction
    except ImportError:
        return [], [], ["embit fehlt — Wasabi-Store nicht lesbar."]

    net = NETWORKS.get(embit_network) or NETWORKS["main"]
    sqlites = _wasabi_sqlite_kandidaten(store_ordner, wallet_pfad)
    if not sqlites:
        hinweise.append(
            "Kein Wasabi-BitcoinStore (Transactions.sqlite) gefunden — "
            "nur Deskriptor/Adressen importiert; UTXO/Verlauf per Scan."
        )
        return [], [], hinweise

    # outpoint → meta
    our: dict[tuple[str, int], dict[str, Any]] = {}
    # spend: outpoint → (spend_txid, spend_height, spend_time)
    spends: dict[tuple[str, int], tuple[str, int | None, int | None]] = {}

    gelesen = 0
    for db in sqlites:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            cur = con.cursor()
            try:
                rows = cur.execute(
                    'SELECT block_height, labels, first_seen, tx '
                    'FROM "transaction"'
                )
            except sqlite3.Error:
                continue
            for height, labels, first_seen, txblob in rows:
                try:
                    tx = Transaction.parse(txblob)
                except Exception:
                    continue
                try:
                    txid = tx.txid().hex()
                except Exception:
                    continue
                gelesen += 1
                h = int(height) if height is not None else None
                if h is not None and h >= _WASABI_MEMPOOL_HEIGHT:
                    h = None
                ts = None
                try:
                    ts = int(first_seen) if first_seen not in (None, "") else None
                    if ts is not None and ts <= 0:
                        ts = None
                except (TypeError, ValueError):
                    ts = None
                lab_tx = str(labels or "").strip()

                for i, out in enumerate(tx.vout):
                    try:
                        addr = out.script_pubkey.address(net)
                    except Exception:
                        addr = None
                    if not addr or addr not in adressen:
                        continue
                    key = (txid, int(i))
                    if key not in our:
                        our[key] = {
                            "value": int(out.value),
                            "address": addr,
                            "height": h,
                            "first_seen": ts,
                            "labels": lab_tx,
                        }
                    else:
                        # confirmed schlägt mempool
                        if our[key].get("height") is None and h is not None:
                            our[key]["height"] = h
                        if not our[key].get("labels") and lab_tx:
                            our[key]["labels"] = lab_tx

                for vin in tx.vin:
                    try:
                        prev = vin.txid.hex()
                        vout = int(vin.vout)
                    except Exception:
                        continue
                    pkey = (prev, vout)
                    # Alle Spends merken; Zuordnung zu our-Outs erst danach
                    # (eine DB-Reihenfolge reicht nicht für „our zuerst“).
                    if pkey not in spends:
                        spends[pkey] = (txid, h, ts)
        finally:
            try:
                con.close()
            except Exception:
                pass

    if not our:
        hinweise.append(
            f"Wasabi-Store gelesen ({gelesen} Tx in {len(sqlites)} DB), "
            "keine Outputs zu Wallet-Adressen — ggf. anderer Store/Netz."
        )
        return [], [], hinweise

    labels_map = address_labels or {}
    utxos: list[dict] = []
    verlauf: list[dict] = []
    for (txid, vout), meta in our.items():
        addr = str(meta.get("address") or "")
        value = int(meta.get("value") or 0)
        h = meta.get("height")
        ts = meta.get("first_seen")
        confirmed = h is not None
        status: dict[str, Any] = {"confirmed": confirmed}
        if h is not None:
            status["block_height"] = int(h)
        if ts is not None:
            status["block_time"] = int(ts)
        lab = labels_map.get(addr) or str(meta.get("labels") or "").strip()
        eintrag: dict[str, Any] = {
            "txid": txid,
            "vout": int(vout),
            "value": value,
            "status": status,
            "address": addr,
            "source": "wasabi_store",
        }
        if lab:
            eintrag["label"] = lab

        sp = spends.get((txid, vout))
        if sp:
            spend_txid, spend_h, spend_ts = sp
            eintrag["spent"] = True
            eintrag["spent_txid"] = spend_txid
            if spend_h is not None:
                eintrag["spent_height"] = int(spend_h)
            if spend_ts is not None:
                eintrag["spent_time_ts"] = int(spend_ts)
            verlauf.append(eintrag)
        else:
            eintrag["spent"] = False
            utxos.append(eintrag)

    hinweise.append(
        f"Wasabi-BitcoinStore: {len(utxos)} UTXO, {len(verlauf)} ausgegeben "
        f"({gelesen} Tx in {len(sqlites)} DB)."
    )
    return utxos, verlauf, hinweise


def _parse_wasabi_coins_json(
    text: str,
) -> tuple[list[dict], list[dict], list[str]]:
    hinweise: list[str] = []
    try:
        data = _json_loads(text)
    except json.JSONDecodeError:
        return [], [], ["Wasabi-Coins-JSON ungültig."]
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    if isinstance(data, dict) and _ist_wasabi_coin(data):
        data = [data]
    if not isinstance(data, list):
        return [], [], ["Wasabi-Coins: Array erwartet."]

    utxos: list[dict] = []
    verlauf: list[dict] = []
    for obj in data:
        if not isinstance(obj, dict):
            continue
        txid = str(obj.get("txid") or "").strip().lower()
        if not _TXID_RE.match(txid):
            continue
        try:
            vout = int(obj.get("index", obj.get("vout", 0)))
        except (TypeError, ValueError):
            continue
        try:
            value = int(obj.get("amount", 0))
        except (TypeError, ValueError):
            continue
        if value < 0:
            continue
        confirmed = bool(obj.get("confirmed", True))
        addr = str(obj.get("address") or "").strip()
        label = str(obj.get("label") or "").strip()
        spent_by = str(obj.get("spentBy") or obj.get("spent_by") or "").strip()
        eintrag: dict[str, Any] = {
            "txid": txid,
            "vout": vout,
            "value": value,
            "status": _status(confirmed),
            "source": "wasabi_rpc",
        }
        if addr:
            eintrag["address"] = addr
        if label:
            eintrag["label"] = label
        if spent_by and _TXID_RE.match(spent_by):
            eintrag["spent"] = True
            eintrag["spent_txid"] = spent_by.lower()
            verlauf.append(eintrag)
        else:
            eintrag["spent"] = False
            utxos.append(eintrag)
    if not utxos and not verlauf:
        hinweise.append("Wasabi-Coins gelesen, aber keine Einträge erkannt.")
    return utxos, verlauf, hinweise


def _parse_wasabi_history_json(text: str) -> tuple[list[dict], list[str]]:
    hinweise: list[str] = []
    try:
        data = _json_loads(text)
    except json.JSONDecodeError:
        return [], ["Wasabi-History-JSON ungültig."]
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    if isinstance(data, dict) and _ist_wasabi_history(data):
        data = [data]
    if not isinstance(data, list):
        return [], ["Wasabi-History: Array erwartet."]

    eintraege: list[dict] = []
    for obj in data:
        if not isinstance(obj, dict):
            continue
        txid = str(obj.get("tx") or obj.get("txid") or "").strip().lower()
        if not _TXID_RE.match(txid):
            continue
        try:
            amount = int(obj.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0
        ts = _parse_zeit(str(obj.get("datetime") or ""))
        label = str(obj.get("label") or "").strip()
        abgang = amount < 0
        height = obj.get("height")
        eintrag: dict[str, Any] = {
            "txid": txid,
            "vout": 0,
            "value": abs(amount),
            "status": _status(ts is not None or height not in (None, 0, "0"), ts),
            "spent": abgang,
            "spent_txid": txid if abgang else None,
            "source": "wasabi_rpc",
        }
        if ts is not None and abgang:
            eintrag["spent_time_ts"] = ts
        if label:
            eintrag["label"] = label
        if obj.get("islikelycoinjoin") in (True, "true", "True"):
            eintrag["label"] = (
                f"{label + ' · ' if label else ''}coinjoin"
            )
        eintraege.append(eintrag)
    if not eintraege:
        hinweise.append("Wasabi-History gelesen, aber keine Txids erkannt.")
    return eintraege, hinweise


def _csv_header_norm(text: str) -> str:
    erste = (text or "").lstrip("\ufeff").splitlines()[:1]
    if not erste:
        return ""
    return erste[0].strip().lower()


def _sieht_aus_wie_h2_oder_binaer(text: str) -> bool:
    if not text:
        return False
    if "H2encrypt" in text[:64] or text.startswith("\x00"):
        return True
    stich = text[:4000]
    if not stich:
        return False
    steu = sum(1 for c in stich if ord(c) < 9 or (13 < ord(c) < 32))
    return (steu / max(len(stich), 1)) > 0.08


def _name_aus_dateiname(name: str) -> str:
    basis = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    for end in (".txt", ".csv", ".json", ".desc"):
        if basis.lower().endswith(end):
            basis = basis[: -len(end)]
            break
    for suffix in (
        "-descriptor", "_descriptor", "-utxos", "_utxos",
        "-transactions", "_transactions", "-labels", "_labels",
        "-output-descriptor", "_output-descriptor",
    ):
        if basis.lower().endswith(suffix):
            basis = basis[: -len(suffix)]
            break
    return basis.strip() or ""


def _sparrow_label_aus_json(text: str) -> str:
    """Sparrow-/Specter-JSON: ``label`` / ``name`` als Wallet-Name."""
    s = (text or "").lstrip("\ufeff").lstrip()
    if not s.startswith("{"):
        return ""
    try:
        data = _json_loads(s)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    for key in ("label", "name", "walletName", "wallet_name"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _parse_csv_rows(text: str) -> tuple[list[str], list[dict[str, str]]]:
    raw = (text or "").lstrip("\ufeff")
    # Sniffer nur auf kleinem Prefix — bei großen Exports sonst teuer/instabil.
    probe = raw[:8192]
    try:
        dialect = csv.Sniffer().sniff(probe, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    leser = csv.DictReader(io.StringIO(raw), dialect=dialect)
    if not leser.fieldnames:
        return [], []
    felder = [str(f or "").strip() for f in leser.fieldnames]
    zeilen: list[dict[str, str]] = []
    for row in leser:
        if not isinstance(row, dict):
            continue
        norm = {
            str(k or "").strip().lower(): str(v or "").strip()
            for k, v in row.items()
            if k is not None
        }
        if any(norm.values()):
            zeilen.append(norm)
    return [f.lower() for f in felder], zeilen


def _feld(row: dict[str, str], *kandidaten: str) -> str:
    for k in kandidaten:
        if k in row and row[k]:
            return row[k]
        for key, val in row.items():
            if key.startswith(k) and val:
                return val
    return ""


def _parse_sats(wert: str) -> int | None:
    s = (wert or "").strip()
    if not s or s.lower() in ("", "n/a", "-"):
        return None
    s = s.replace(" ", "").replace("BTC", "").replace("btc", "").replace("sats", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        teile = s.split(",")
        if len(teile) == 2 and len(teile[1]) <= 8:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        if "." in s:
            from decimal import Decimal, ROUND_DOWN
            sats = (Decimal(s) * Decimal(100_000_000)).quantize(
                Decimal("1"), rounding=ROUND_DOWN
            )
            return int(sats)
        return int(s)
    except Exception:
        return None


def _parse_zeit(wert: str) -> int | None:
    s = (wert or "").strip()
    if not s or s.lower() in ("unconfirmed", "unbestätigt", "pending"):
        return None
    # ISO mit Offset: 2019-10-01T12:31:57+00:00
    try:
        iso = s.replace("Z", "+00:00")
        if "T" in iso and ("+" in iso[10:] or iso.endswith("Z")):
            dt = datetime.fromisoformat(iso)
            return int(dt.timestamp())
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y",
    ):
        try:
            dt = datetime.strptime(s[:19], fmt) if len(s) >= 10 else datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return None


def _parse_outpoint(wert: str) -> tuple[str, int] | None:
    m = _OUTPOINT_RE.match(wert or "")
    if not m:
        return None
    return m.group(1).lower(), int(m.group(2))


def _status(confirmed: bool, block_time: int | None = None) -> dict[str, Any]:
    st: dict[str, Any] = {"confirmed": bool(confirmed)}
    if block_time is not None:
        st["block_time"] = int(block_time)
    return st


def _parse_utxo_csv(text: str) -> tuple[list[dict], list[str]]:
    _felder, zeilen = _parse_csv_rows(text)
    utxos: list[dict] = []
    hinweise: list[str] = []
    for row in zeilen:
        out = _feld(row, "output", "outpoint", "utxo")
        txid = _feld(row, "txid", "tx", "hash", "transaction id")
        vout_s = _feld(row, "vout", "index", "n", "output index")
        if out:
            op = _parse_outpoint(out)
            if op:
                txid, vout = op
            else:
                continue
        elif txid and _TXID_RE.match(txid) and vout_s.isdigit():
            vout = int(vout_s)
            txid = txid.lower()
        else:
            continue
        value = _parse_sats(_feld(row, "value", "amount", "sats", "btc"))
        if value is None or value < 0:
            continue
        addr = _feld(row, "address", "addr")
        ts = _parse_zeit(_feld(row, "date", "time", "confirmed"))
        label = _feld(row, "label", "labels", "name")
        eintrag: dict[str, Any] = {
            "txid": txid,
            "vout": vout,
            "value": value,
            "status": _status(True, ts),
            "source": "sparrow_csv",
        }
        if addr:
            eintrag["address"] = addr
        if label:
            eintrag["label"] = label
        utxos.append(eintrag)
    if not utxos and zeilen:
        hinweise.append("UTXO-CSV gelesen, aber keine Outpoints erkannt.")
    return utxos, hinweise


def _parse_tx_csv(text: str, *, source: str = "sparrow_csv") -> tuple[list[dict], list[str]]:
    _felder, zeilen = _parse_csv_rows(text)
    eintraege: list[dict] = []
    hinweise: list[str] = []
    _max_zeilen = 50_000
    if len(zeilen) > _max_zeilen:
        hinweise.append(
            f"Tx-CSV: {len(zeilen)} Zeilen — nur die ersten {_max_zeilen} gelesen."
        )
        zeilen = zeilen[:_max_zeilen]
    for row in zeilen:
        txid = _feld(row, "txid", "tx", "hash", "transaction id", "transaction")
        if not txid or not _TXID_RE.match(txid):
            continue
        txid = txid.lower()
        value_raw = _feld(row, "value", "amount", "sats", "btc")
        value = _parse_sats(value_raw) if value_raw else None
        if value is None:
            value = 0
        ts = _parse_zeit(_feld(row, "date", "time", "confirmed"))
        label = _feld(row, "label", "labels", "name")
        abgang = value < 0 or str(value_raw).strip().startswith("-")
        eintrag: dict[str, Any] = {
            "txid": txid,
            "vout": 0,
            "value": abs(value),
            "status": _status(ts is not None, ts),
            "spent": abgang,
            "spent_txid": txid if abgang else None,
            "source": source,
        }
        if ts is not None and abgang:
            eintrag["spent_time_ts"] = ts
        if label:
            eintrag["label"] = label
        eintraege.append(eintrag)
    if not eintraege and zeilen:
        hinweise.append("Tx-CSV gelesen, aber keine Txids erkannt.")
    return eintraege, hinweise


def _parse_address_csv(text: str) -> tuple[list[str], list[str]]:
    _felder, zeilen = _parse_csv_rows(text)
    addrs: list[str] = []
    for row in zeilen:
        addr = _feld(row, "address", "addr")
        if addr and addr not in addrs:
            addrs.append(addr)
    return addrs, []


def _dedupe_utxos(items: list[dict]) -> list[dict]:
    gesehen: set[str] = set()
    out: list[dict] = []
    for u in items:
        key = f"{u.get('txid')}:{u.get('vout')}:{u.get('spent')}"
        if key in gesehen:
            continue
        gesehen.add(key)
        out.append(u)
    return out
