"""
Lokale Sparrow-/Wasabi-Wallets finden (übliche Datenverzeichnisse).

Kein Passwort, kein Entschlüsseln. Passwortgeschützte Dateien werden nur
gelistet (Schloss); importierbar sind lesbare Klartext-Artefakte
(Wasabi-JSON View-only/HW, Sparrow-JSON/Descriptor).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core import wallet_export_import as export_mod

_H2ENCRYPT = b"H2encrypt"


@dataclass
class GefundenesWallet:
    """Ein Treffer im Dateisystem."""

    id: str
    name: str
    app: str  # sparrow | wasabi
    path: str
    locked: bool = False
    importable: bool = False
    reason: str = ""
    descriptors: list[str] = field(default_factory=list)
    namen: list[str] = field(default_factory=list)
    network: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "app": self.app,
            "path": self.path,
            "locked": self.locked,
            "importable": self.importable,
            "reason": self.reason,
            "descriptor_count": len(self.descriptors),
            "network": self.network,
        }


def standard_suchwurzeln() -> list[Path]:
    """Übliche Sparrow-/Wasabi-Ordner je OS (existierende zuerst)."""
    home = Path.home()
    kandidaten: list[Path] = []
    appdata = os.environ.get("APPDATA") or ""
    local = os.environ.get("LOCALAPPDATA") or ""
    xdg = os.environ.get("XDG_DATA_HOME") or ""

    if appdata:
        kandidaten += [
            Path(appdata) / "Sparrow" / "wallets",
            Path(appdata) / "WalletWasabi" / "Client" / "Wallets",
        ]
    if local:
        kandidaten += [
            Path(local) / "Sparrow" / "wallets",
        ]
    # macOS
    kandidaten += [
        home / "Library" / "Application Support" / "Sparrow" / "wallets",
        home / "Library" / "Application Support" / "WalletWasabi" / "Client" / "Wallets",
        home / ".sparrow" / "wallets",
        home / ".walletwasabi" / "client" / "Wallets",
    ]
    # Linux / XDG
    if xdg:
        kandidaten += [
            Path(xdg) / "sparrow" / "wallets",
            Path(xdg) / "WalletWasabi" / "Client" / "Wallets",
        ]
    kandidaten += [
        home / ".local" / "share" / "sparrow" / "wallets",
        home / ".local" / "share" / "WalletWasabi" / "Client" / "Wallets",
    ]

    # Einmalig, existierende bevorzugen in der Reihenfolge.
    gesehen: set[str] = set()
    out: list[Path] = []
    for p in kandidaten:
        try:
            key = str(p.resolve()) if p.exists() else str(p)
        except OSError:
            key = str(p)
        if key in gesehen:
            continue
        gesehen.add(key)
        out.append(p)
    return out


def suche_lokale_wallets(
    *,
    vorhandene_wallet_ids: set[str] | None = None,
    wurzeln: list[Path] | None = None,
) -> list[GefundenesWallet]:
    """
    Scannt Standardordner. Liefert nur Treffer, die noch nicht in SatSage
    stecken (soweit die Kennung bekannt ist).
    """
    vorhanden = {str(x) for x in (vorhandene_wallet_ids or set()) if x}
    treffer: list[GefundenesWallet] = []
    gesehen_pfade: set[str] = set()

    for root in wurzeln or standard_suchwurzeln():
        if not root.is_dir():
            continue
        try:
            eintraege = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for pfad in eintraege:
            if not pfad.is_file():
                continue
            try:
                key = str(pfad.resolve())
            except OSError:
                key = str(pfad)
            if key in gesehen_pfade:
                continue
            gesehen_pfade.add(key)

            app = _app_fuer_pfad(root, pfad)
            if not app:
                continue
            fund = _analysiere_datei(pfad, app=app)
            if fund is None:
                continue
            # Schon importiert: alle Deskriptor-IDs abgleichen.
            if fund.descriptors and vorhanden:
                ids = {_deskriptor_wallet_id(d) for d in fund.descriptors}
                if ids and ids.issubset(vorhanden):
                    continue
            elif not fund.descriptors and fund.name:
                # Gesperrt / nicht lesbar: per Name+App grob filtern geht nicht
                # zuverlässig — anzeigen.
                pass
            treffer.append(fund)

    treffer.sort(key=lambda t: (t.app, t.name.lower(), t.path))
    return treffer


def importiere_pfade(
    pfade: list[str],
) -> export_mod.WalletExportErgebnis:
    """
    Liest gewählte Dateipfade und parst sie wie ein manueller Export-Import.
    """
    dateien: list[dict[str, str]] = []
    for roh in pfade:
        p = Path(str(roh or "")).expanduser()
        if not p.is_file():
            continue
        try:
            data = p.read_bytes()
        except OSError as exc:
            return export_mod.WalletExportErgebnis(
                fehler=f"„{p.name}“ nicht lesbar: {exc}"
            )
        if export_mod._sieht_aus_wie_h2_oder_binaer(
            data[:4000].decode("latin-1", errors="replace")
        ) or data.startswith(_H2ENCRYPT) or _H2ENCRYPT in data[:64]:
            return export_mod.WalletExportErgebnis(
                fehler=(
                    f"„{p.name}“ ist passwortgeschützt oder eine native "
                    "Sparrow-DB. Bitte in Sparrow File → Export Wallet → "
                    "Output Descriptor exportieren."
                )
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("latin-1", errors="replace")
        dateien.append({"name": p.name, "text": text})
    return export_mod.parse_wallet_export_dateien(dateien)


def _app_fuer_pfad(root: Path, pfad: Path) -> str | None:
    parts = [x.lower() for x in root.parts]
    name = pfad.name.lower()
    if "sparrow" in parts:
        if name.endswith((".mv.db", ".json", ".db", ".txt", ".desc")):
            return "sparrow"
    if "walletwasabi" in parts or "wasabi" in "".join(parts):
        if name.endswith(".json"):
            return "wasabi"
    # Heuristik Dateiname
    if name.endswith(".mv.db"):
        return "sparrow"
    return None


def _analysiere_datei(pfad: Path, *, app: str) -> GefundenesWallet | None:
    name = _anzeige_name(pfad)
    try:
        head = pfad.read_bytes()[:8192]
    except OSError:
        return GefundenesWallet(
            id=f"path:{pfad}",
            name=name,
            app=app,
            path=str(pfad),
            locked=True,
            importable=False,
            reason="Datei nicht lesbar",
        )

    if app == "sparrow":
        return _analysiere_sparrow(pfad, name, head)
    if app == "wasabi":
        return _analysiere_wasabi(pfad, name, head)
    return None


def _analysiere_sparrow(pfad: Path, name: str, head: bytes) -> GefundenesWallet:
    lower = pfad.name.lower()
    locked = _H2ENCRYPT in head[:128] or head[:20].startswith(b"H2encrypt")
    if lower.endswith(".mv.db") or lower.endswith(".db"):
        # Native H2: für SatSage wie gesperrt — kein Klartext-Deskriptor ohne
        # Sparrow-Export (Passwort und reines DB-Format gleich behandeln).
        return GefundenesWallet(
            id=f"sparrow:{pfad.name}:{pfad.stat().st_mtime_ns if pfad.exists() else 0}",
            name=name,
            app="sparrow",
            path=str(pfad),
            locked=True,
            importable=False,
            reason=(
                "Passwortgeschützt"
                if locked
                else "Sparrow-DB — Descriptor-Export nötig"
            ),
        )

    # JSON / Descriptor-Text
    try:
        text = pfad.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            text = pfad.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return GefundenesWallet(
                id=f"sparrow:{pfad.name}",
                name=name,
                app="sparrow",
                path=str(pfad),
                locked=True,
                importable=False,
                reason="Nicht als Text lesbar",
            )

    parsed = export_mod.parse_wallet_export_dateien(
        [{"name": pfad.name, "text": text}]
    )
    if not parsed.ok:
        return GefundenesWallet(
            id=f"sparrow:{pfad.name}",
            name=name,
            app="sparrow",
            path=str(pfad),
            locked=False,
            importable=False,
            reason=parsed.fehler or "Kein Deskriptor",
        )
    return GefundenesWallet(
        id=_deskriptor_wallet_id(parsed.descriptors[0]),
        name=(parsed.namen[0] if parsed.namen else name) or name,
        app="sparrow",
        path=str(pfad),
        locked=False,
        importable=True,
        descriptors=list(parsed.descriptors),
        namen=list(parsed.namen),
    )


def _analysiere_wasabi(pfad: Path, name: str, head: bytes) -> GefundenesWallet:
    try:
        text = pfad.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            text = pfad.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return GefundenesWallet(
                id=f"wasabi:{pfad.name}",
                name=name,
                app="wasabi",
                path=str(pfad),
                locked=True,
                importable=False,
                reason="Nicht lesbar",
            )

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return GefundenesWallet(
            id=f"wasabi:{pfad.name}",
            name=name,
            app="wasabi",
            path=str(pfad),
            locked=False,
            importable=False,
            reason="Kein JSON",
        )

    if not isinstance(data, dict):
        return None  # type: ignore[return-value]

    secret = data.get("EncryptedSecret")
    # Hot-Wallet hat Secret, View-only/HW oft null — beides importierbar öffentlich.
    has_secret = secret not in (None, "", "null")
    net = ""
    try:
        net = str((data.get("BlockchainState") or {}).get("Network") or "")
    except Exception:
        net = ""

    parsed = export_mod.parse_wallet_export_dateien(
        [{"name": pfad.name, "text": text}]
    )
    if not parsed.ok:
        return GefundenesWallet(
            id=f"wasabi:{pfad.name}",
            name=name,
            app="wasabi",
            path=str(pfad),
            locked=has_secret,
            importable=False,
            reason=parsed.fehler or "Kein ExtPubKey",
            network=net,
        )
    return GefundenesWallet(
        id=_deskriptor_wallet_id(parsed.descriptors[0]),
        name=(parsed.namen[0] if parsed.namen else name) or name,
        app="wasabi",
        path=str(pfad),
        # Schloss nur wenn wirklich passwortgeschütztes Material die Datei sperrt
        # — View-only bleibt ohne Schloss; Hot mit Secret: Schloss, aber
        # Öffentliches bleibt importierbar.
        locked=has_secret,
        importable=True,
        descriptors=list(parsed.descriptors),
        namen=list(parsed.namen),
        network=net,
        reason=("Hot-Wallet — nur Öffentliches" if has_secret else ""),
    )


def _anzeige_name(pfad: Path) -> str:
    stem = pfad.stem
    if stem.lower().endswith(".mv"):
        stem = stem[:-3]
    return stem or pfad.name


def _deskriptor_wallet_id(descriptor: str) -> str:
    try:
        from core.config import WalletEntry
        return WalletEntry(descriptor=descriptor).wallet_id()
    except Exception:
        import hashlib
        return hashlib.sha256(descriptor.encode("utf-8")).hexdigest()[:16]
