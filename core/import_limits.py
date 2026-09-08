"""Begrenzte ZIP-Entpackung für lokale Import-Dateien."""
from __future__ import annotations

from dataclasses import dataclass
import io
import zipfile

MAX_IMPORT_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_IMPORT_FILES = 1000
MAX_IMPORT_COMPRESSION_RATIO = 1000


class ImportLimitError(ValueError):
    """Ein Import überschreitet eine Sicherheitsgrenze."""


@dataclass
class ImportBudget:
    """Gemeinsames Budget für mehrere Dateien und ZIP-Archive."""

    unpacked_bytes: int = 0
    file_count: int = 0

    def add_file(self, size: int, *, name: str = "Datei") -> None:
        if size < 0:
            raise ImportLimitError(f"{name}: ungültige Dateigröße.")
        if self.file_count + 1 > MAX_IMPORT_FILES:
            raise ImportLimitError(f"Entpackgrenze: höchstens {MAX_IMPORT_FILES} Dateien erlaubt.")
        if self.unpacked_bytes + size > MAX_IMPORT_UNPACKED_BYTES:
            raise ImportLimitError("Entpackgrenze: insgesamt höchstens " f"{MAX_IMPORT_UNPACKED_BYTES // (1024 * 1024)} MB erlaubt.")
        self.file_count += 1
        self.unpacked_bytes += size


def unpack_zip_limited(payload: bytes, *, budget: ImportBudget | None = None) -> list[tuple[str, bytes]]:
    """Entpackt ein ZIP nur innerhalb des gemeinsamen Importbudgets."""
    budget = budget or ImportBudget()
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ValueError(f"ZIP-Import ungültig: {exc}") from exc

    try:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if budget.file_count + len(infos) > MAX_IMPORT_FILES:
            raise ImportLimitError(f"Entpackgrenze: höchstens {MAX_IMPORT_FILES} Dateien erlaubt.")
        for info in infos:
            compressed = max(int(info.compress_size), 0)
            unpacked = int(info.file_size)
            if unpacked < 0 or compressed < 0:
                raise ImportLimitError(f"ZIP-Datei {info.filename}: ungültige Größe.")
            ratio = float("inf") if unpacked and compressed == 0 else (unpacked / compressed if compressed else 0)
            if ratio > MAX_IMPORT_COMPRESSION_RATIO:
                raise ImportLimitError(f"Kompressionsverhältnis für {info.filename} zu groß (maximal {MAX_IMPORT_COMPRESSION_RATIO}:1).")
            if budget.unpacked_bytes + unpacked > MAX_IMPORT_UNPACKED_BYTES:
                raise ImportLimitError("Entpackgrenze: insgesamt höchstens " f"{MAX_IMPORT_UNPACKED_BYTES // (1024 * 1024)} MB erlaubt.")

        ergebnis: list[tuple[str, bytes]] = []
        for info in infos:
            try:
                inhalt = archive.read(info)
            except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
                raise ValueError(f"ZIP-Datei {info.filename} konnte nicht gelesen werden: {exc}") from exc
            if len(inhalt) != int(info.file_size):
                raise ValueError(f"ZIP-Datei {info.filename}: Größenprüfung fehlgeschlagen.")
            budget.add_file(len(inhalt), name=info.filename)
            ergebnis.append((info.filename, inhalt))
        return ergebnis
    finally:
        archive.close()


def add_direct_file(budget: ImportBudget, name: str, payload: bytes) -> None:
    """Nimmt eine nicht gezippte Importdatei in dasselbe Budget auf."""
    budget.add_file(len(payload), name=name)
