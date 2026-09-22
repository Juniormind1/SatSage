"""
Gemeinsames .env-Scramble für Unittests.

Festes Testpasswort ``tralala123``: Dateien werden damit gescrambelt und
wieder gelesen. Roh-``read_text`` auf eine scrambled ``.env`` wirft
``UnicodeDecodeError`` — Tests nutzen ``read_env_plaintext`` /
``write_env_scrambled``.
"""
from __future__ import annotations

from pathlib import Path

from core import env_scramble as sc

#: Einziges Passwort für Scramble in der Unittest-Suite (außer
#: bewusste Falsch-/Wechsel-Fälle in test_env_scramble).
TEST_SCRAMBLE_PASSWORD = "tralala123"


def clear_scramble_session() -> None:
    sc.clear_session_key()


def write_env_scrambled(
    path: Path | str,
    text: str,
    *,
    password: str = TEST_SCRAMBLE_PASSWORD,
) -> None:
    """Klartext → scrambled ``.env`` (SSGB1) mit Testpasswort; Session-Key gesetzt."""
    path = Path(path)
    plain = text if text.endswith("\n") else (text + "\n" if text else "\n")
    if not plain.endswith("\n"):
        plain += "\n"
    sc.enable_scramble(path, plain, password)


def read_env_plaintext(
    path: Path | str,
    *,
    password: str = TEST_SCRAMBLE_PASSWORD,
) -> str:
    """
    Scrambled ``.env``: mit Session-Key oder ``password`` entschlüsseln.
    Klartext-``.env``: UTF-8 lesen.
    """
    path = Path(path)
    if not path.is_file():
        return ""
    if sc.is_env_scrambled(path):
        key = sc.get_session_key()
        if key is not None:
            try:
                return sc.decrypt_env_blob_with_key(path.read_bytes(), key)
            except sc.ScrambleError:
                pass
        return sc.read_scrambled(path, password)
    return path.read_text(encoding="utf-8")


def assert_env_scrambled(path: Path | str) -> None:
    if not sc.is_env_scrambled(path):
        raise AssertionError(f"erwartet scrambled .env, war Klartext: {path}")
