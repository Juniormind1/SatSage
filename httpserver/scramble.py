"""Scramble-/Unlock-/Bootstrap-Passwort-Helfer — aus server.py extrahiert (Modularisierung).

Keine HTTP-Handler; Fassade bleibt in server.py für Late-Imports / Mixin-Bindung.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

LOGGER = logging.getLogger("satsage.server")


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
    """Scramble unter Start9 mit, sonst gäbe es dort kein Passwort.

    Umbrel und Specter bleiben außen: deren Netz ist nicht die StartOS-Tür,
    und ein erfundener Plattform-Wert darf die Klartext-``.env`` nicht
    nachträglich verschlüsseln.
    """
    if getattr(state, "managed_by", None) == "specter":
        return False
    if getattr(state, "managed_by", None) == "umbrel":
        return False
    return True


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


def _scramble_discard_locked(state) -> None:
    """Login · Passwort vergessen. Nur wenn ohne Schlüssel nichts lesbar ist."""
    from core import env_scramble as sc
    from httpserver.api.auth_session import _clear_password_hash

    if sc.get_session_key() is not None:
        raise RuntimeError("Sitzung ist entsperrt — Passwort in den Einstellungen entfernen.")
    sc.discard_locked_env(state.env_path)
    _clear_password_hash(state)
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


def _pending_password_path(state) -> Path:
    """Klartext-Drop der StartOS-Action, neben der Hash-Datei.

    Die Action schreibt hierhin, während der Dienst läuft. Der Prozess hasht
    den Wert und löscht die Datei. Sie bleibt nie als dauerhaftes Geheimnis.
    """
    from httpserver.api.auth_session import _auth_file

    return _auth_file(state).with_name(".satsage-password.pending")


def _read_pending_password(state) -> str:
    path = _pending_password_path(state)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("StartOS-Passwort-Drop kann nicht gelesen werden") from exc
    value = raw.strip()
    if not value or "\n" in value or "\x00" in value:
        return ""
    return value


def _consume_pending_password(state) -> str:
    """Liest und entfernt den Drop. Leer, wenn keiner da ist."""
    value = _read_pending_password(state)
    path = _pending_password_path(state)
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        if path.is_file():
            path.unlink()
    except OSError:
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
    return value


def _apply_managed_password(state, password: str, *, existing: str) -> bool:
    """Hasht *password*, wenn der bestehende Hash ihn nicht schon trägt.

    Rückgabe True, wenn der Hash neu geschrieben wurde.
    """
    from httpserver.api.auth_session import _verify_password, _write_password_hash

    if not password:
        return False
    if existing and _verify_password(password, existing):
        return False
    _write_password_hash(state, password)
    return True


def _seed_managed_password(state) -> None:
    """Umbrel hasht ``APP_PASSWORD``. StartOS hat kein eigenes Passwort.

    Ein Hash aus einem älteren StartOS-Paket (``uiPassword``) gehört nicht
    zum optionalen SatSage-Passwort. Ohne scrambled ``.env`` wird er beim
    Start gelöscht, sonst sperrt er die Oberfläche mit einem Passwort, das
    der Nutzer nie gesetzt hat.
    """
    from httpserver.api.auth_session import _clear_password_hash
    from httpserver.app_state import _NODE_MANAGED

    bootstrap = os.environ.get("SATSAGE_BOOTSTRAP_PASSWORD", "")
    _consume_pending_password(state)
    if getattr(state, "managed_by", None) == "umbrel":
        _seed_umbrel_hash(state, bootstrap)
        return
    if getattr(state, "managed_by", None) == "start9":
        os.environ.pop("SATSAGE_BOOTSTRAP_PASSWORD", None)
        from core import env_scramble as sc

        if not sc.is_scramble_file_present(state.env_path):
            _clear_password_hash(state)
        return
    if state.managed_by not in _NODE_MANAGED:
        os.environ.pop("SATSAGE_BOOTSTRAP_PASSWORD", None)


def _seed_umbrel_hash(state, bootstrap: str) -> None:
    """Umbrel-Login-Hash. Kein Scramble, kein SatSage-Passwort-Begriff."""
    from httpserver.api.auth_session import _auth_file
    from httpserver.app_state import _MANAGED_PLATTFORM

    try:
        existing = _auth_file(state).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("SatSage-Passwortdatei kann nicht gelesen werden") from exc
    if not bootstrap:
        if not existing:
            plattform = _MANAGED_PLATTFORM.get("umbrel", "umbrel")
            raise RuntimeError(f"{plattform}-Bootstrap-Passwort fehlt")
        return
    _apply_managed_password(state, bootstrap, existing=existing)
    os.environ.pop("SATSAGE_BOOTSTRAP_PASSWORD", None)


def starte_passwort_drop_wache(state, *, stop: threading.Event | None = None) -> None:
    """StartOS rotiert kein Passwort mehr. Die Wache bleibt aus."""
    del state, stop
    return
    import threading as _threading

    if stop is None:
        stop = _threading.Event()

    def _wache() -> None:
        while not stop.wait(2.0):
            try:
                if not _pending_password_path(state).is_file():
                    continue
                _seed_managed_password(state)
            except Exception as exc:
                LOGGER.warning("Passwort-Drop nicht übernommen: %s", exc)

    _threading.Thread(
        target=_wache, name="satsage-password-drop", daemon=True,
    ).start()
