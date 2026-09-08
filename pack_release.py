#!/usr/bin/env python3
"""
Erzeugt ein ZIP-Archiv mit den essentiellen Projektdateien (ohne GitHub-Clone).

Enthält Quellcode, requirements.txt, .env.example und Doku.
Ausgeschlossen: .env, Caches, venv, IDE-Artefakte, Entwicklungs-Skripte.

Verwendung:
    py pack_release.py
    py pack_release.py -o C:\\Temp\\SatSage.zip
    py pack_release.py --with-electrum-servers
    py pack_release.py --fetch-electrum-servers
"""

from __future__ import annotations

import argparse
import fnmatch

import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARCHIVE_DIRNAME = "SatSage"
ELECTRUM_SERVERS_FILE = ROOT / "electrum_servers.json"

# Fallback, falls kein Git-Repo verfügbar ist.
ESSENTIAL_FILES = (
    ".env.example",
    ".gitignore",
    "AGENTS.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "requirements.txt",
    "main.py",
    "menu.py",
    "interact.py",
    "analyze.py",
    "trace_engine.py",
    "display.py",
    "sanctioned.py",
    "bip158_scanner.py",
    "fulcrum.py",
    "check_fulcrum_tor.py",
    "consolidate.py",
)

# Pfade/Patterns, die nie ins Release-ZIP gehören.
EXCLUDE_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".idea",
    "utxo_cache",
    "immutable_cache",
    "sanctioned_cache",
    "psbt_out",
    "terminals",
    "mcps",
    "node_modules",
}

EXCLUDE_FILE_GLOBS = (
    ".env",
    "*.pyc",
    "*.pyo",
    "*.tmp",
    "*~",
    "Thumbs.db",
    ".DS_Store",
    "_patch_*",
    "_test_*",
    "_profile_*",
    "_check_*",
    "_list_*",
    "_gen_*",
    "*.pptx",
    "pack_release.py",
)

EXCLUDE_IDE_PREFIXES = (".idea/",)


def _matches_glob(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def _path_excluded(rel_posix: str) -> bool:
    parts = rel_posix.split("/")
    if any(part in EXCLUDE_DIR_NAMES for part in parts):
        return True
    if any(rel_posix.startswith(prefix) for prefix in EXCLUDE_IDE_PREFIXES):
        return True
    filename = parts[-1]
    if _matches_glob(filename, EXCLUDE_FILE_GLOBS):
        return True
    return False


def _git_tracked_files() -> list[Path] | None:
    if not (ROOT / ".git").is_dir():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    rel_paths: list[Path] = []
    for entry in proc.stdout.split(b"\0"):
        if not entry:
            continue
        rel = Path(entry.decode("utf-8"))
        if rel.is_dir():
            continue
        rel_paths.append(rel)
    return rel_paths


def _fallback_files() -> list[Path]:
    return [Path(name) for name in ESSENTIAL_FILES]


def collect_release_files(include_electrum: bool) -> list[Path]:
    candidates = _git_tracked_files() or _fallback_files()
    selected: list[Path] = []
    seen: set[str] = set()

    for rel in sorted(candidates, key=lambda p: p.as_posix()):
        rel_posix = rel.as_posix()
        if _path_excluded(rel_posix):
            continue
        full = ROOT / rel
        if not full.is_file():
            continue
        seen.add(rel_posix)
        selected.append(rel)

    if include_electrum and ELECTRUM_SERVERS_FILE.is_file():
        rel = ELECTRUM_SERVERS_FILE.relative_to(ROOT)
        rel_posix = rel.as_posix()
        if rel_posix not in seen:
            selected.append(rel)
            seen.add(rel_posix)

    return selected


def default_output_path() -> Path:
    stamp = date.today().strftime("%Y%m%d")
    return ROOT / f"SatSage-release-{stamp}.zip"


def fetch_electrum_servers() -> None:
    from check_fulcrum_tor import fetch_electrum_servers_json

    fetch_electrum_servers_json(ELECTRUM_SERVERS_FILE)


def build_zip(files: list[Path], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            arcname = f"{ARCHIVE_DIRNAME}/{rel.as_posix()}"
            zf.write(ROOT / rel, arcname=arcname)

    print(f"ZIP erstellt: {output}")
    print(f"  Dateien: {len(files)}")
    print(f"  Größe:   {output.stat().st_size:,} Bytes")
    print()
    print("Entpacken → py -m venv .venv → pip install -r requirements.txt")
    print("           copy .env.example .env  (XPUBs/RPC lokal eintragen)")
    if ELECTRUM_SERVERS_FILE.name not in {p.name for p in files}:
        print("           py check_fulcrum_tor.py  (lädt electrum_servers.json nach)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Essentielle SatSage-Dateien in ein ZIP-Archiv packen.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Zielpfad der .zip-Datei (Default: SatSage-release-YYYYMMDD.zip)",
    )
    parser.add_argument(
        "--with-electrum-servers",
        action="store_true",
        help="electrum_servers.json mitpacken, falls lokal vorhanden",
    )
    parser.add_argument(
        "--fetch-electrum-servers",
        action="store_true",
        help="Vor dem Packen electrum_servers.json vom Electrum-Repo laden",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Nur Dateiliste anzeigen, kein ZIP erzeugen",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output or default_output_path()

    if args.fetch_electrum_servers:
        try:
            fetch_electrum_servers()
        except Exception as exc:
            print(f"Fehler beim Laden von electrum_servers.json: {exc}", file=sys.stderr)
            return 1

    include_electrum = args.with_electrum_servers or args.fetch_electrum_servers
    files = collect_release_files(include_electrum=include_electrum)
    if not files:
        print("Keine Dateien für das Release gefunden.", file=sys.stderr)
        return 1

    print("Release-Inhalt:")
    for rel in files:
        size = (ROOT / rel).stat().st_size
        print(f"  {rel.as_posix():<32} {size:>8,} B")

    if args.list_only:
        return 0

    build_zip(files, output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())