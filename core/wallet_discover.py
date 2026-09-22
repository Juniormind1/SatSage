"""
Lokale Wallets finden (übliche Datenverzeichnisse) + optional Bitcoin Core RPC.

Kein Passwort, kein Entschlüsseln. Passwortgeschützte Dateien werden nur
gelistet (Schloss); importierbar sind lesbare Klartext-Artefakte
(Wasabi/Specter/Electrum-JSON, Sparrow-Descriptor, Core-listdescriptors).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from core import wallet_export_import as export_mod

_H2ENCRYPT = b"H2encrypt"
_CORERPC_PREFIX = "corerpc:"


@dataclass
class GefundenesWallet:
    """Ein Treffer im Dateisystem oder per Core-RPC."""

    id: str
    name: str
    app: str  # sparrow | wasabi | specter | electrum | core
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
            "origin_label": _app_anzeige(self.app),
        }


def _app_anzeige(app: str) -> str:
    return {
        "sparrow": "Sparrow",
        "wasabi": "Wasabi",
        "specter": "Specter",
        "electrum": "Electrum",
        "core": "Bitcoin Core",
    }.get((app or "").lower(), (app or "?").title())


def standard_suchwurzeln() -> list[Path]:
    """Übliche Wallet-Ordner je OS (existierende zuerst)."""
    home = Path.home()
    kandidaten: list[Path] = []
    appdata = os.environ.get("APPDATA") or ""
    local = os.environ.get("LOCALAPPDATA") or ""
    xdg = os.environ.get("XDG_DATA_HOME") or ""

    if appdata:
        kandidaten += [
            Path(appdata) / "Sparrow" / "wallets",
            Path(appdata) / "WalletWasabi" / "Client" / "Wallets",
            Path(appdata) / "Electrum" / "wallets",
            Path(appdata) / "specter" / "wallets",
        ]
    if local:
        kandidaten += [
            Path(local) / "Sparrow" / "wallets",
        ]
    # macOS
    kandidaten += [
        home / "Library" / "Application Support" / "Sparrow" / "wallets",
        home / "Library" / "Application Support" / "WalletWasabi" / "Client" / "Wallets",
        home / "Library" / "Application Support" / "Electrum" / "wallets",
        home / "Library" / "Application Support" / "specter" / "wallets",
        home / ".sparrow" / "wallets",
        home / ".walletwasabi" / "client" / "Wallets",
        home / ".electrum" / "wallets",
        home / ".specter" / "wallets",
    ]
    # Linux / XDG
    if xdg:
        kandidaten += [
            Path(xdg) / "sparrow" / "wallets",
            Path(xdg) / "WalletWasabi" / "Client" / "Wallets",
            Path(xdg) / "electrum" / "wallets",
            Path(xdg) / "specter" / "wallets",
        ]
    kandidaten += [
        home / ".local" / "share" / "sparrow" / "wallets",
        home / ".local" / "share" / "WalletWasabi" / "Client" / "Wallets",
        home / ".local" / "share" / "electrum" / "wallets",
        home / ".local" / "share" / "specter" / "wallets",
    ]

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


def _app_label_fuer_wurzel(root: Path) -> str | None:
    """Anzeigename fürs Log: Sparrow / Wasabi / Specter / Electrum."""
    # Teile können ``.electrum`` / ``.specter`` heißen — Substring, nicht exakt.
    parts = [x.lower() for x in root.parts]

    def _hat(*needles: str) -> bool:
        return any(any(n in p for n in needles) for p in parts)

    if _hat("sparrow"):
        return "Sparrow"
    if _hat("walletwasabi", "wasabi"):
        return "Wasabi"
    if _hat("specter"):
        return "Specter"
    if _hat("electrum"):
        return "Electrum"
    return None


def _specter_wallet_json_dateien(root: Path) -> list[Path]:
    """Specter: ``wallets/**/*.json`` (kein config/devices)."""
    treffer: list[Path] = []
    if not root.is_dir():
        return treffer
    gesehen: set[str] = set()
    try:
        files = list(root.rglob("*.json"))
    except OSError:
        return treffer
    for p in files:
        if not p.is_file():
            continue
        if p.name.lower() in ("config.json", "devices.json"):
            continue
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in gesehen:
            continue
        gesehen.add(key)
        treffer.append(p)
    return sorted(treffer, key=lambda p: p.name.lower())


def suche_lokale_wallets(
    *,
    vorhandene_wallet_ids: set[str] | None = None,
    wurzeln: list[Path] | None = None,
    on_log=None,
    env: dict[str, str] | None = None,
    mit_core_rpc: bool = True,
) -> list[GefundenesWallet]:
    """
    Scannt Standardordner (+ optional Bitcoin Core per RPC).

    *on_log*: optional ``callable(str)`` — z. B. „Suche Wasabi…“.
    """
    vorhanden = {str(x) for x in (vorhandene_wallet_ids or set()) if x}
    treffer: list[GefundenesWallet] = []
    gesehen_pfade: set[str] = set()

    reihenfolge: list[str] = []
    roots_pro_app: dict[str, list[Path]] = {}
    for root in wurzeln or standard_suchwurzeln():
        if not root.is_dir():
            continue
        label = _app_label_fuer_wurzel(root)
        if not label:
            continue
        if label not in roots_pro_app:
            roots_pro_app[label] = []
            reihenfolge.append(label)
        roots_pro_app[label].append(root)

    def _log(text: str) -> None:
        if on_log:
            try:
                on_log(text)
            except Exception:
                pass

    if not reihenfolge and not mit_core_rpc:
        _log("Keine Wallet-Ordner gefunden.")
        return treffer
    if not reihenfolge:
        _log("Keine lokalen Wallet-Ordner gefunden.")

    for label in reihenfolge:
        _log(f"Suche {label}…")
        n_vor = len(treffer)
        for root in roots_pro_app[label]:
            if label == "Specter":
                dateien = _specter_wallet_json_dateien(root)
            else:
                try:
                    dateien = [
                        p for p in root.iterdir() if p.is_file()
                    ]
                except OSError:
                    continue
                dateien = sorted(dateien, key=lambda p: p.name.lower())

            for pfad in dateien:
                try:
                    key = str(pfad.resolve())
                except OSError:
                    key = str(pfad)
                if key in gesehen_pfade:
                    continue
                gesehen_pfade.add(key)

                app = _app_fuer_pfad(root, pfad)
                if not app:
                    # Specter-JSON unter wallets/main/
                    if label == "Specter" and pfad.suffix.lower() == ".json":
                        app = "specter"
                    else:
                        continue
                fund = _analysiere_datei(pfad, app=app)
                if fund is None:
                    continue
                if fund.descriptors and vorhanden:
                    ids = {_deskriptor_wallet_id(d) for d in fund.descriptors}
                    if ids and ids.issubset(vorhanden):
                        continue
                treffer.append(fund)
        _log(f"Suche {label}… {len(treffer) - n_vor} gefunden")

    if mit_core_rpc:
        treffer.extend(
            suche_core_rpc_wallets(
                env=env,
                vorhandene_wallet_ids=vorhanden,
                on_log=_log,
            )
        )

    treffer.sort(
        key=lambda t: (
            0 if t.importable else 1,
            (t.name or "").lower(),
            t.app or "",
            t.path or "",
        )
    )
    return treffer


def suche_core_rpc_wallets(
    *,
    env: dict[str, str] | None = None,
    vorhandene_wallet_ids: set[str] | None = None,
    on_log=None,
) -> list[GefundenesWallet]:
    """Listet Descriptor-Wallets am angeschlossenen Bitcoin Core."""
    vorhanden = {str(x) for x in (vorhandene_wallet_ids or set()) if x}
    out: list[GefundenesWallet] = []

    def _log(text: str) -> None:
        if on_log:
            try:
                on_log(text)
            except Exception:
                pass

    try:
        from core import bitcoind_rpc as rpc_mod
    except ImportError:
        return out

    werte = dict(env or {})
    if not werte:
        try:
            import main as main_mod
            werte = dict(getattr(main_mod, "_ENV", {}) or {})
            if not werte and hasattr(main_mod, "load_env_dict"):
                werte = main_mod.load_env_dict()  # type: ignore[attr-defined]
        except Exception:
            werte = {}
    # Server übergibt state.env().values()
    cfg = rpc_mod.config_from_env(werte) or rpc_mod.config_utxo_from_env(werte)
    if cfg is None or not cfg.configured:
        _log("Bitcoin Core: nicht konfiguriert — übersprungen.")
        return out

    _log("Suche Bitcoin Core…")
    try:
        client = rpc_mod.BitcoinRpcClient(cfg, timeout=20.0)
        geladen = list(client.call("listwallets") or [])
    except Exception as exc:
        _log(f"Bitcoin Core: nicht erreichbar ({type(exc).__name__}).")
        return out

    namen: set[str] = set()
    for n in geladen:
        namen.add(str(n or ""))
    try:
        wdir = client.call("listwalletdir") or {}
        for ein in wdir.get("wallets") or []:
            if isinstance(ein, dict):
                namen.add(str(ein.get("name") or ""))
            elif ein is not None:
                namen.add(str(ein))
    except Exception:
        pass

    n_vor = len(out)
    for wname in sorted(namen, key=lambda s: (s == "", s.lower())):
        anzeige = wname if wname else "(Standard-Wallet)"
        path = f"{_CORERPC_PREFIX}{wname}"
        # Wallet laden falls nötig
        if wname and wname not in [str(x or "") for x in geladen]:
            try:
                client.call("loadwallet", [wname])
            except Exception:
                out.append(GefundenesWallet(
                    id=f"core:{wname or 'default'}",
                    name=anzeige,
                    app="core",
                    path=path,
                    locked=True,
                    importable=False,
                    reason="Wallet nicht ladbar",
                ))
                continue

        wcfg = replace(cfg, wallet=wname if wname else None)
        try:
            wclient = rpc_mod.BitcoinRpcClient(wcfg, timeout=30.0)
            roh = wclient.call("listdescriptors")
        except Exception as exc:
            msg = str(exc)
            if "legacy" in msg.lower() or "descriptor" in msg.lower():
                reason = "Legacy-Wallet (keine Descriptoren)"
            else:
                reason = "listdescriptors fehlgeschlagen"
            out.append(GefundenesWallet(
                id=f"core:{wname or 'default'}",
                name=anzeige,
                app="core",
                path=path,
                locked=False,
                importable=False,
                reason=reason,
            ))
            continue

        payload = {
            "name": anzeige,
            "wallet_name": anzeige,
            "descriptors": (
                roh.get("descriptors") if isinstance(roh, dict) else roh
            ),
        }
        text = json.dumps(payload)
        parsed = export_mod.parse_wallet_export_dateien(
            [{"name": f"{anzeige}.json", "text": text, "path": path}]
        )
        if not parsed.ok or not parsed.descriptors:
            out.append(GefundenesWallet(
                id=f"core:{wname or 'default'}",
                name=anzeige,
                app="core",
                path=path,
                locked=False,
                importable=False,
                reason=parsed.fehler or "Keine Descriptoren",
            ))
            continue
        wid = _deskriptor_wallet_id(parsed.descriptors[0])
        if wid in vorhanden:
            continue
        if all(_deskriptor_wallet_id(d) in vorhanden for d in parsed.descriptors):
            continue
        out.append(GefundenesWallet(
            id=wid,
            name=(parsed.namen[0] if parsed.namen else anzeige) or anzeige,
            app="core",
            path=path,
            locked=False,
            importable=True,
            descriptors=list(parsed.descriptors),
            namen=list(parsed.namen) or [anzeige],
            reason="",
        ))
    _log(f"Suche Bitcoin Core… {len(out) - n_vor} gefunden")
    return out


def importiere_core_rpc_wallet(
    path: str,
    *,
    env: dict[str, str] | None = None,
) -> export_mod.WalletExportErgebnis:
    """Importiert eine Core-Wallet per ``corerpc:<name>``."""
    roh = str(path or "")
    if not roh.startswith(_CORERPC_PREFIX):
        return export_mod.WalletExportErgebnis(fehler="Kein Core-RPC-Pfad.")
    wname = roh[len(_CORERPC_PREFIX):]
    from core import bitcoind_rpc as rpc_mod

    werte = dict(env or {})
    cfg = rpc_mod.config_from_env(werte) or rpc_mod.config_utxo_from_env(werte)
    if cfg is None or not cfg.configured:
        return export_mod.WalletExportErgebnis(
            fehler="Bitcoin Core ist nicht konfiguriert."
        )
    try:
        root = rpc_mod.BitcoinRpcClient(cfg, timeout=20.0)
        geladen = [str(x or "") for x in (root.call("listwallets") or [])]
        if wname and wname not in geladen:
            root.call("loadwallet", [wname])
        wcfg = replace(cfg, wallet=wname if wname else None)
        client = rpc_mod.BitcoinRpcClient(wcfg, timeout=30.0)
        roh_desc = client.call("listdescriptors")
    except Exception as exc:
        return export_mod.WalletExportErgebnis(
            fehler=f"Core-RPC: {exc}"
        )
    anzeige = wname if wname else "Core"
    payload = {
        "name": anzeige,
        "wallet_name": anzeige,
        "descriptors": (
            roh_desc.get("descriptors")
            if isinstance(roh_desc, dict)
            else roh_desc
        ),
    }
    return export_mod.parse_wallet_export_dateien(
        [{"name": f"{anzeige}.json", "text": json.dumps(payload), "path": path}]
    )


def importiere_pfade(
    pfade: list[str],
    *,
    env: dict[str, str] | None = None,
) -> export_mod.WalletExportErgebnis:
    """
    Liest gewählte Dateipfade (oder ``corerpc:…``) und parst sie.
    """
    dateien: list[dict[str, str]] = []
    gemerged: export_mod.WalletExportErgebnis | None = None

    for roh in pfade:
        s = str(roh or "").strip()
        if not s:
            continue
        if s.startswith(_CORERPC_PREFIX):
            teil = importiere_core_rpc_wallet(s, env=env)
            if not teil.ok:
                return teil
            if gemerged is None:
                gemerged = teil
            else:
                gemerged.descriptors.extend(teil.descriptors)
                gemerged.namen.extend(teil.namen)
                gemerged.adressen.extend(teil.adressen)
                gemerged.utxos.extend(teil.utxos)
                gemerged.verlauf.extend(teil.verlauf)
                gemerged.hinweise.extend(teil.hinweise)
                for f in teil.formate:
                    if f not in gemerged.formate:
                        gemerged.formate.append(f)
                gemerged.dateien.extend(teil.dateien)
            continue

        p = Path(s).expanduser()
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
        # Electrum verschlüsselt
        head = data[:8]
        if head.startswith(b"QklF") or (
            data[:1] not in (b"{", b"[", b"\xef") and b"wallet_type" not in data[:200]
            and p.parent.name.lower() == "wallets"
            and "electrum" in "".join(x.lower() for x in p.parts)
        ):
            # QklF = base64 BIE1
            if data[:4] == b"QklF" or data.decode("latin-1", errors="replace")[:4] == "QklF":
                return export_mod.WalletExportErgebnis(
                    fehler=f"„{p.name}“: Electrum-Wallet verschlüsselt."
                )
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1", errors="replace")
        dateien.append({"name": p.name, "text": text, "path": str(p)})

    if dateien:
        parsed = export_mod.parse_wallet_export_dateien(dateien)
        if gemerged is None:
            return parsed
        if not parsed.ok:
            return parsed
        gemerged.descriptors.extend(parsed.descriptors)
        gemerged.namen.extend(parsed.namen)
        gemerged.adressen.extend(parsed.adressen)
        gemerged.utxos.extend(parsed.utxos)
        gemerged.verlauf.extend(parsed.verlauf)
        gemerged.hinweise.extend(parsed.hinweise)
        for f in parsed.formate:
            if f not in gemerged.formate:
                gemerged.formate.append(f)
        gemerged.dateien.extend(parsed.dateien)
        return gemerged

    if gemerged is not None:
        return gemerged
    return export_mod.WalletExportErgebnis(fehler="Keine Dateien gelesen.")


def _app_fuer_pfad(root: Path, pfad: Path) -> str | None:
    parts = [x.lower() for x in root.parts]
    name = pfad.name.lower()

    def _hat(*needles: str) -> bool:
        return any(any(n in p for n in needles) for p in parts)

    if _hat("sparrow"):
        if name.endswith((".mv.db", ".json", ".db", ".txt", ".desc")):
            return "sparrow"
    if _hat("walletwasabi", "wasabi"):
        if name.endswith(".json"):
            return "wasabi"
    if _hat("specter"):
        if name.endswith(".json"):
            return "specter"
    if _hat("electrum"):
        # Electrum: oft ohne Endung
        return "electrum"
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
    if app == "specter":
        return _analysiere_specter(pfad, name, head)
    if app == "electrum":
        return _analysiere_electrum(pfad, name, head)
    return None


def _analysiere_sparrow(pfad: Path, name: str, head: bytes) -> GefundenesWallet:
    lower = pfad.name.lower()
    locked = _H2ENCRYPT in head[:128] or head[:20].startswith(b"H2encrypt")
    if lower.endswith(".mv.db") or lower.endswith(".db"):
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
        data = export_mod._json_loads(text)
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
    has_secret = secret not in (None, "", "null")
    net = ""
    try:
        net = str((data.get("BlockchainState") or {}).get("Network") or "")
    except Exception:
        net = ""

    if has_secret:
        return GefundenesWallet(
            id=f"wasabi:{pfad.name}",
            name=name,
            app="wasabi",
            path=str(pfad),
            locked=True,
            importable=False,
            reason="Passwortgeschützt",
            network=net,
        )

    # Suche: nur Deskriptor — kein BitcoinStore-Walk (sonst ~1–2 s pro Wallet).
    parsed = export_mod.parse_wallet_export_dateien(
        [{
            "name": pfad.name,
            "text": text,
            "path": str(pfad),
            "nur_deskriptor": True,
        }]
    )
    if not parsed.ok:
        return GefundenesWallet(
            id=f"wasabi:{pfad.name}",
            name=name,
            app="wasabi",
            path=str(pfad),
            locked=False,
            importable=False,
            reason=parsed.fehler or "Kein ExtPubKey",
            network=net,
        )
    return GefundenesWallet(
        id=_deskriptor_wallet_id(parsed.descriptors[0]),
        name=(parsed.namen[0] if parsed.namen else name) or name,
        app="wasabi",
        path=str(pfad),
        locked=False,
        importable=True,
        descriptors=list(parsed.descriptors),
        namen=list(parsed.namen),
        network=net,
        reason="",
    )


def _analysiere_specter(pfad: Path, name: str, head: bytes) -> GefundenesWallet | None:
    try:
        text = pfad.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return GefundenesWallet(
            id=f"specter:{pfad.name}",
            name=name,
            app="specter",
            path=str(pfad),
            locked=True,
            importable=False,
            reason="Nicht lesbar",
        )
    try:
        data = export_mod._json_loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    # Kein Wallet-JSON (z. B. config)
    if not (
        data.get("recv_descriptor")
        or (data.get("keys") and data.get("address_type") is not None)
        or data.get("alias")
    ):
        return None

    parsed = export_mod.parse_wallet_export_dateien(
        [{"name": pfad.name, "text": text, "path": str(pfad)}]
    )
    anzeige = str(data.get("name") or data.get("alias") or name)
    if not parsed.ok:
        return GefundenesWallet(
            id=f"specter:{pfad.name}",
            name=anzeige,
            app="specter",
            path=str(pfad),
            locked=False,
            importable=False,
            reason=parsed.fehler or "Kein Deskriptor",
        )
    return GefundenesWallet(
        id=_deskriptor_wallet_id(parsed.descriptors[0]),
        name=(parsed.namen[0] if parsed.namen else anzeige) or anzeige,
        app="specter",
        path=str(pfad),
        locked=False,
        importable=True,
        descriptors=list(parsed.descriptors),
        namen=list(parsed.namen),
    )


def _analysiere_electrum(pfad: Path, name: str, head: bytes) -> GefundenesWallet:
    # Verschlüsselt: Base64 BIE1
    if head.startswith(b"QklF") or (
        head[:1] not in (b"{", b"[", b"\xef") and b"wallet_type" not in head
    ):
        return GefundenesWallet(
            id=f"electrum:{pfad.name}",
            name=name,
            app="electrum",
            path=str(pfad),
            locked=True,
            importable=False,
            reason="Passwortgeschützt",
        )
    try:
        text = pfad.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return GefundenesWallet(
            id=f"electrum:{pfad.name}",
            name=name,
            app="electrum",
            path=str(pfad),
            locked=True,
            importable=False,
            reason="Nicht lesbar",
        )
    parsed = export_mod.parse_wallet_export_dateien(
        [{"name": pfad.name or name, "text": text, "path": str(pfad)}]
    )
    if not parsed.ok:
        reason = parsed.fehler or "Kein xpub"
        # Kurzer Grund für die Liste
        low = reason.lower()
        if "verschlüssel" in low or "passwort" in low:
            reason = "Passwortgeschützt"
            locked = True
        elif "imported" in low:
            reason = "Nur Adressen (kein xpub)"
            locked = False
        elif "kein" in low and "xpub" in low:
            reason = "Kein xpub"
            locked = False
        else:
            locked = "passwort" in low or "verschlüssel" in low
        return GefundenesWallet(
            id=f"electrum:{pfad.name}",
            name=name,
            app="electrum",
            path=str(pfad),
            locked=locked,
            importable=False,
            reason=reason,
        )
    return GefundenesWallet(
        id=_deskriptor_wallet_id(parsed.descriptors[0]),
        name=(parsed.namen[0] if parsed.namen else name) or name,
        app="electrum",
        path=str(pfad),
        locked=False,
        importable=True,
        descriptors=list(parsed.descriptors),
        namen=list(parsed.namen),
        reason="",
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
