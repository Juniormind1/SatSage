"""Auth-/Session-Passwort-API — aus server.py extrahiert (Modularisierung Slice 1)."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Any

try:
    from argon2 import PasswordHasher
    from argon2 import Type as ArgonType
except ImportError:  # pragma: no cover - optional dependency
    PasswordHasher = None
    ArgonType = None


def _auth_file(state) -> Path:
    """Liefert die Passwortdatei, niemals einen Pfad in der .env selbst."""
    from server import _env_setting

    configured = _env_setting(state, "SATSAGE_PASSWORD_FILE")
    return Path(configured).expanduser() if configured else state.env_path.parent / ".satsage-password"


def _password_hash(state) -> str:
    from server import _env_setting

    path = _auth_file(state)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        value = ""
    # Für Tests/Bootstrap erlaubt, aber nicht empfohlen: ein bereits gehashter
    # Wert aus der Umgebung. Niemals ein Klartext-Passwort daraus lesen.
    return value or _env_setting(state, "SATSAGE_PASSWORD_HASH")


def _password_is_set(state) -> bool:
    return bool(_password_hash(state))


def _hash_password(password: str) -> str:
    if PasswordHasher is not None:
        hasher = PasswordHasher(
            time_cost=3,
            memory_cost=64 * 1024,
            parallelism=2,
            type=ArgonType.ID,
        )
        return hasher.hash(password)
    # Dokumentierter Fallback für Minimal-Installationen ohne argon2-cffi.
    # scrypt ist ebenfalls ein speicherharter Passwort-KDF und wird mit
    # zufälligem Salt gespeichert; neue Pakete sollten argon2-cffi installieren.
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 15, 8, 1
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024)
    return "scrypt${}${}${}${}${}".format(n, r, p, salt.hex(), digest.hex())


def _verify_password(password: str, stored: str) -> bool:
    if not password or not stored:
        return False
    if stored.startswith("$argon2") and PasswordHasher is not None:
        try:
            return bool(PasswordHasher().verify(stored, password))
        except Exception:
            return False
    if stored.startswith("scrypt$"):
        try:
            _, n, r, p, salt_hex, digest_hex = stored.split("$", 5)
            candidate = hashlib.scrypt(
                password.encode("utf-8"),
                salt=bytes.fromhex(salt_hex),
                n=int(n), r=int(r), p=int(p), maxmem=128 * 1024 * 1024,
            )
            return hmac.compare_digest(candidate.hex(), digest_hex)
        except (ValueError, TypeError, UnicodeError):
            return False
    return False


def _write_password_hash(state, password: str) -> None:
    """Schreibt den Login-Hash atomar (tmp + replace), ohne fd-chmod-APIs."""
    path = _auth_file(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = (_hash_password(password) + "\n").encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    if tmp.is_file() and os.name == "nt":
        try:
            os.chmod(tmp, 0o666)
        except OSError:
            pass
    tmp.write_bytes(value)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    if path.is_file() and os.name == "nt":
        try:
            os.chmod(path, 0o666)
        except OSError:
            pass
    try:
        os.replace(tmp, path)
    except PermissionError:
        if path.is_file():
            try:
                os.chmod(path, 0o666)
            except OSError:
                pass
            path.unlink()
        os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _clear_password_hash(state) -> None:
    """Entfernt die Passwortdatei (optionales App-Passwort). Env-Hash unberührt."""
    path = _auth_file(state)
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        # Python < 3.8 missing_ok — hier 3.10+
        if path.is_file():
            path.unlink()
    except OSError:
        if path.is_file():
            path.unlink()


def api_save_app_password(state: AppState, payload: dict) -> dict:
    """
    Einstellungen · Passwort setzen/ändern (Token-API, wie übrige Config).

    Reihenfolge: zuerst Login-Hash (atomar), dann Scramble
    (``.env`` als Cipher).
    """
    from server import (
        ApiError,
        _env_scramble_status,
        _scramble_change_password,
        _scramble_enable_for_password,
    )

    current = str(payload.get("current_password") or payload.get("old_password") or "")
    password = str(payload.get("new_password") or payload.get("password") or "")
    confirm = str(
        payload.get("confirm") or payload.get("password_confirm") or password
    )
    stored = _password_hash(state)
    if stored and not _verify_password(current, stored):
        raise ApiError(403, "Aktuelles Passwort ist falsch.")
    if not password or password != confirm:
        raise ApiError(400, "Passwörter stimmen nicht überein oder sind leer.")
    try:
        _write_password_hash(state, password)
    except OSError as exc:
        raise ApiError(500, f"Passwort-Hash konnte nicht geschrieben werden: {exc}") from exc
    except Exception as exc:
        raise ApiError(500, f"Passwort-Hash fehlgeschlagen: {exc}") from exc
    try:
        from core import env_scramble as sc_mod

        if stored and sc_mod.is_scramble_file_present(state.env_path):
            _scramble_change_password(state, current, password)
        else:
            _scramble_enable_for_password(state, password)
    except Exception as exc:
        raise ApiError(400, f"env-scramble: {exc}") from exc
    return {
        "ok": True,
        "password_set": True,
        "env_scramble": _env_scramble_status(state),
    }


def api_delete_app_password(state: AppState, payload: dict) -> dict:
    """Einstellungen · Passwort entfernen + Klartext-.env wiederherstellen."""
    from server import (
        ApiError,
        _env_scramble_status,
        _scramble_disable_for_password,
    )

    current = str(payload.get("current_password") or payload.get("old_password") or "")
    if not _password_is_set(state):
        return {
            "ok": True,
            "password_set": False,
            "env_scramble": _env_scramble_status(state),
        }
    if not current or not _verify_password(current, _password_hash(state)):
        raise ApiError(403, "Aktuelles Passwort ist falsch.")
    try:
        _scramble_disable_for_password(state, current)
    except Exception as exc:
        raise ApiError(400, f"env-scramble: {exc}") from exc
    _clear_password_hash(state)
    return {
        "ok": True,
        "password_set": False,
        "env_scramble": _env_scramble_status(state),
    }


def api_unlock_env(state: AppState, payload: dict) -> dict:
    """Nach Neustart: gobbledigook mit Passwort öffnen (File-Key nur RAM)."""
    from server import (
        ApiError,
        _env_scramble_status,
        _scramble_unlock,
    )

    password = str(payload.get("password") or payload.get("current_password") or "")
    if not password:
        raise ApiError(400, "Passwort fehlt.")
    if _password_is_set(state) and not _verify_password(password, _password_hash(state)):
        raise ApiError(403, "Passwort ist falsch.")
    try:
        _scramble_unlock(state, password)
    except Exception as exp:
        raise ApiError(403, f"Unlock fehlgeschlagen: {exp}") from exp
    return {"ok": True, "env_scramble": _env_scramble_status(state)}

