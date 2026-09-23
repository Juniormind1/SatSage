"""Scramble-/Unlock-/Bootstrap-Passwort-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports / Mixin-Bindung.
"""

from __future__ import annotations

import os
from pathlib import Path


def _unlock_needed_after_auth(state) -> bool:
    """Ob nach Login-Auth noch File-Key/Scramble-Unlock nötig ist."""
    if not _env_scramble_erlaubt(state):
        return False
    st = _env_scramble_status(state)
    if st.get("locked"):
        return True
    # Passwort gesetzt, .env noch Klartext → Unlock scramblt nach.
    if st.get("allowed") and st.get("plain_env_present"):
        return True
    return False


def _env_scramble_erlaubt(state) -> bool:
    """Phase 1: kein Scramble unter Umbrel/Start9/Specter-managed."""
    from httpserver.app_state import _NODE_MANAGED

    return getattr(state, "managed_by", None) not in _NODE_MANAGED and (
        getattr(state, "managed_by", None) != "specter"
    )


def _env_scramble_status(state) -> dict:
    try:
        from core import env_scramble as sc

        scrambled = sc.is_scramble_file_present(state.env_path)
        path = Path(state.env_path)
        plain = path.is_file() and not sc.is_env_scrambled(path)
        locked = scrambled and sc.get_session_key() is None
        return {
            "active": scrambled,
            "locked": locked,
            "plain_env_present": plain,
            "allowed": _env_scramble_erlaubt(state),
        }
    except Exception:
        return {
            "active": False,
            "locked": False,
            "plain_env_present": Path(state.env_path).is_file(),
            "allowed": False,
        }


def _scramble_enable_for_password(state, password: str) -> None:
    """Nach Passwort-Setzen: ``.env`` scrambled (eine Datei)."""
    if not _env_scramble_erlaubt(state):
        return
    from core import env_scramble as sc

    try:
        env = state.env()
        plain = env.render()
    except Exception:
        plain = ""
    if not plain.strip() and Path(state.env_path).is_file():
        plain = Path(state.env_path).read_text(encoding="utf-8")
    if not plain.strip() and sc.is_scramble_file_present(state.env_path):
        sc.change_scramble_password(state.env_path, password, password)
        state.env_scramble_unlocked = True
        try:
            state.reload()
        except Exception:
            pass
        return
    if not plain.strip():
        plain = "\n"
    sc.enable_scramble(state.env_path, plain, password)
    state.env_scramble_unlocked = True
    try:
        state.reload()
    except Exception:
        pass


def _scramble_change_password(state, old_password: str, new_password: str) -> None:
    if not _env_scramble_erlaubt(state):
        return
    from core import env_scramble as sc

    if sc.is_scramble_file_present(state.env_path):
        sc.change_scramble_password(state.env_path, old_password, new_password)
        state.env_scramble_unlocked = True
        try:
            state.reload()
        except Exception:
            pass
        return
    _scramble_enable_for_password(state, new_password)


def _scramble_disable_for_password(state, password: str) -> None:
    if not _env_scramble_erlaubt(state):
        return
    from core import env_scramble as sc

    if not sc.is_scramble_file_present(state.env_path):
        sc.clear_session_key()
        state.env_scramble_unlocked = True
        return
    sc.disable_scramble(state.env_path, password)
    state.env_scramble_unlocked = True
    try:
        state.reload()
    except Exception:
        pass


def _scramble_unlock(state, password: str) -> None:
    """File-Key aus Passwort + Config neu laden (auch Dual-Write-Migration)."""
    from core import env_scramble as sc

    if not _env_scramble_erlaubt(state):
        state.env_scramble_unlocked = True
        return
    if not sc.is_scramble_file_present(state.env_path) and not Path(state.env_path).is_file():
        state.env_scramble_unlocked = True
        return
    sc.unlock_with_password(state.env_path, password)
    state.env_scramble_unlocked = True
    state.reload()


def _seed_managed_password(state) -> None:
    """Keep the platform password and the app hash in sync.

    On StartOS (uiPassword) and Umbrel (``APP_PASSWORD``) the platform value is
    the single source of truth for the SatSage login. Re-hash whenever the
    bootstrap value no longer verifies, e.g. after a password rotation while
    SatSage was stopped.
    """
    from httpserver.api.auth_session import (
        _auth_file,
        _verify_password,
        _write_password_hash,
    )
    from httpserver.app_state import _MANAGED_PLATTFORM, _NODE_MANAGED

    bootstrap = os.environ.get("SATSAGE_BOOTSTRAP_PASSWORD", "")
    if state.managed_by not in _NODE_MANAGED and not bootstrap:
        return
    path = _auth_file(state)
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("SatSage-Passwortdatei kann nicht gelesen werden") from exc
    if not bootstrap:
        if state.managed_by in _NODE_MANAGED and not existing:
            plattform = _MANAGED_PLATTFORM.get(state.managed_by, state.managed_by)
            raise RuntimeError(f"{plattform}-Bootstrap-Passwort fehlt")
        return
    if existing and _verify_password(bootstrap, existing):
        os.environ.pop("SATSAGE_BOOTSTRAP_PASSWORD", None)
        return

    _write_password_hash(state, bootstrap)
    # Do not retain the cleartext bootstrap value in the process environment.
    os.environ.pop("SATSAGE_BOOTSTRAP_PASSWORD", None)
