"""
.env-Scramble: eine Datei ``.env`` — scrambled (SSGB1) oder Klartext.

Mit Passwort: ``.env`` enthält Cipher (Argon2id + AES-GCM); Klartext nur im RAM.
Ohne Passwort: ``.env`` ist Klartext. Login-Hash getrennt (``.satsage-password``).
File-Key prozessweit im RAM. Legacy ``.env.gobbledigook`` wird nach ``.env``
migriert und gelöscht. Backups, CLI, Specter, Umbrel/Start9: ausgenommen.

Datei-Format scrambled (v1)::

    SSGB1\\n
    {json header}\\n
    \\n
    <binary: nonce(12) || ciphertext+tag>
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from pathlib import Path

_session_lock = threading.RLock()
_session: dict = {
    "key": None,
    "salt": None,
    "header": None,
}

MAGIC = b"SSGB1\n"
LEGACY_GOBBLE_NAME = ".env.gobbledigook"
HEADER_VERSION = 1

KDF_TIME = 3
KDF_MEMORY = 64 * 1024  # KiB
KDF_PARALLELISM = 2
KEY_LEN = 32
NONCE_LEN = 12


class ScrambleError(Exception):
    """Scramble/Unlock fehlgeschlagen (falsches Passwort, kaputte Datei, …)."""


class ScrambleLocked(ScrambleError):
    """``.env`` ist scrambled, Session-Key fehlt — Login/Unlock nötig."""


def env_path_of(env_path: Path | str) -> Path:
    return Path(env_path)


def legacy_gobbledigook_path(env_path: Path | str) -> Path:
    """Nur Migration: alte Neben-Datei."""
    return env_path_of(env_path).parent / LEGACY_GOBBLE_NAME


# Rückwärtskompatibel für Aufrufer/Tests.
def gobbledigook_path(env_path: Path | str) -> Path:
    """Früher Neben-Datei; jetzt = ``.env`` (Scramble steckt in derselben Datei)."""
    return env_path_of(env_path)


def _file_starts_with_magic(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open("rb") as fh:
            head = fh.read(len(MAGIC))
    except OSError:
        return False
    return head == MAGIC


def is_env_scrambled(env_path: Path | str) -> bool:
    """True, wenn ``.env`` das Scramble-Magic trägt."""
    return _file_starts_with_magic(env_path_of(env_path))


def is_scramble_file_present(env_path: Path | str) -> bool:
    """
    Scramble aktiv: scrambled ``.env`` oder noch unmigriertes Legacy-gobbledigook.
    """
    path = env_path_of(env_path)
    if is_env_scrambled(path):
        return True
    return legacy_gobbledigook_path(path).is_file()


def migrate_legacy_gobbledigook(env_path: Path | str) -> bool:
    """
    ``.env.gobbledigook`` → ``.env`` (Cipher), Legacy-Datei löschen.
    Rückgabe: True wenn migriert.
    """
    path = env_path_of(env_path)
    legacy = legacy_gobbledigook_path(path)
    if not legacy.is_file():
        return False
    data = legacy.read_bytes()
    if not data.startswith(MAGIC):
        raise ScrambleError("Legacy .env.gobbledigook ohne gültiges Magic.")
    # Cipher nach .env; vorhandener Klartext/.env wird ersetzt.
    _write_bytes_atomic(path, data)
    _unlink_quiet(legacy)
    return True


def set_session_key(key: bytes | None, *, salt: bytes | None = None, header: dict | None = None) -> None:
    if key is not None and len(key) != KEY_LEN:
        raise ScrambleError("Ungültige Schlüssel-Länge.")
    with _session_lock:
        _session["key"] = key
        if salt is not None:
            _session["salt"] = salt
        if header is not None:
            _session["header"] = header
        if key is None:
            _session["salt"] = None
            _session["header"] = None


def get_session_key() -> bytes | None:
    with _session_lock:
        return _session.get("key")


def get_session_header() -> dict | None:
    with _session_lock:
        h = _session.get("header")
        return dict(h) if isinstance(h, dict) else None


def get_session_salt() -> bytes | None:
    with _session_lock:
        return _session.get("salt")


def clear_session_key() -> None:
    set_session_key(None)


def _adopt_header(header: dict) -> None:
    with _session_lock:
        _session["header"] = header
        try:
            _session["salt"] = bytes.fromhex(str(header.get("salt") or ""))
        except ValueError:
            _session["salt"] = None


def structural_env_values(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        k = key.strip()
        if not k:
            continue
        result[k] = value.strip().strip('"').strip("'")
    return result


def structural_equal(a: str, b: str) -> bool:
    return structural_env_values(a) == structural_env_values(b)


def _derive_key_argon2(password: str, salt: bytes, *, t: int, m: int, p: int) -> bytes:
    try:
        from argon2.low_level import Type, hash_secret_raw
    except ImportError:
        return _derive_key_scrypt(password, salt, t=t, m=m, p=p)
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=t,
        memory_cost=m,
        parallelism=p,
        hash_len=KEY_LEN,
        type=Type.ID,
    )


def _derive_key_scrypt(password: str, salt: bytes, *, t: int, m: int, p: int) -> bytes:
    n = 2 ** 15
    r = 8
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=max(1, p),
        dklen=KEY_LEN,
        maxmem=128 * 1024 * 1024,
    )


def derive_file_key(
    password: str,
    salt: bytes,
    *,
    time_cost: int = KDF_TIME,
    memory_cost: int = KDF_MEMORY,
    parallelism: int = KDF_PARALLELISM,
) -> bytes:
    if not password:
        raise ScrambleError("Passwort fehlt.")
    if len(salt) < 8:
        raise ScrambleError("Salt zu kurz.")
    return _derive_key_argon2(
        password, salt, t=time_cost, m=memory_cost, p=parallelism,
    )


def _aes_gcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except ImportError as exc:
        raise ScrambleError(
            "Paket cryptography fehlt (AES-GCM für .env-Scramble). "
            "Im gleichen Python wie der Server: "
            "py -m pip install cryptography "
            "bzw. .venv: python -m pip install cryptography — "
            "danach Server neu starten."
        ) from exc


def _aes_gcm_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    return _aes_gcm()(key).encrypt(nonce, plaintext, aad)


def _aes_gcm_decrypt(key: bytes, nonce: bytes, blob: bytes, aad: bytes) -> bytes:
    try:
        return _aes_gcm()(key).decrypt(nonce, blob, aad)
    except ScrambleError:
        raise
    except Exception as exc:
        raise ScrambleError("Entschlüsselung fehlgeschlagen (Passwort oder Datei).") from exc


def _pack(header: dict, nonce: bytes, ciphertext: bytes) -> bytes:
    head = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return MAGIC + head + b"\n\n" + nonce + ciphertext


def _unpack(data: bytes) -> tuple[dict, bytes, bytes]:
    if not data.startswith(MAGIC):
        raise ScrambleError("Keine scrambled .env (Magic SSGB1).")
    rest = data[len(MAGIC):]
    sep = rest.find(b"\n\n")
    if sep < 0:
        raise ScrambleError(".env-Scramble-Header unlesbar.")
    try:
        header = json.loads(rest[:sep].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ScrambleError(".env-Scramble-Header JSON defekt.") from exc
    body = rest[sep + 2:]
    if len(body) < NONCE_LEN + 16:
        raise ScrambleError(".env-Scramble-Ciphertext zu kurz.")
    return header, body[:NONCE_LEN], body[NONCE_LEN:]


def encrypt_env_text(plaintext: str, password: str) -> tuple[bytes, bytes]:
    """Klartext → (scrambled-.env-Bytes, File-Key)."""
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(NONCE_LEN)
    header = {
        "v": HEADER_VERSION,
        "kdf": "argon2id",
        "t": KDF_TIME,
        "m": KDF_MEMORY,
        "p": KDF_PARALLELISM,
        "salt": salt.hex(),
    }
    key = derive_file_key(
        password, salt,
        time_cost=KDF_TIME, memory_cost=KDF_MEMORY, parallelism=KDF_PARALLELISM,
    )
    aad = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ct = _aes_gcm_encrypt(key, nonce, plaintext.encode("utf-8"), aad)
    return _pack(header, nonce, ct), key


def decrypt_env_blob(blob: bytes, password: str) -> tuple[str, bytes]:
    """Scrambled-Bytes → (Klartext, File-Key)."""
    header, nonce, ct = _unpack(blob)
    try:
        salt = bytes.fromhex(str(header.get("salt") or ""))
    except ValueError as exc:
        raise ScrambleError("Salt defekt.") from exc
    t = int(header.get("t") or KDF_TIME)
    m = int(header.get("m") or KDF_MEMORY)
    p = int(header.get("p") or KDF_PARALLELISM)
    key = derive_file_key(password, salt, time_cost=t, memory_cost=m, parallelism=p)
    aad = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    plain = _aes_gcm_decrypt(key, nonce, ct, aad)
    return plain.decode("utf-8"), key


def decrypt_env_blob_with_key(blob: bytes, key: bytes) -> str:
    header, nonce, ct = _unpack(blob)
    aad = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    plain = _aes_gcm_decrypt(key, nonce, ct, aad)
    return plain.decode("utf-8")


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
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
            try:
                path.unlink()
            except OSError:
                pass
        os.replace(tmp, path)


def _write_text_atomic(path: Path, text: str) -> None:
    body = text if text.endswith("\n") else text + "\n"
    _write_bytes_atomic(path, body.encode("utf-8"))


def _unlink_quiet(path: Path) -> None:
    if not path.is_file():
        return
    if os.name == "nt":
        try:
            os.chmod(path, 0o666)
        except OSError:
            pass
    try:
        path.unlink()
    except OSError:
        try:
            path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            if path.is_file():
                path.unlink()


def _ensure_scrambled_path(env_path: Path | str) -> Path:
    """Pfad zur scrambled ``.env``; migriert Legacy bei Bedarf."""
    path = env_path_of(env_path)
    migrate_legacy_gobbledigook(path)
    if is_env_scrambled(path):
        return path
    legacy = legacy_gobbledigook_path(path)
    if legacy.is_file():
        migrate_legacy_gobbledigook(path)
        return path
    raise ScrambleError("Keine scrambled .env.")


def write_scrambled_atomic(env_path: Path | str, plaintext: str, password: str) -> Path:
    """Schreibt scrambled ``.env``; setzt Session-Key (ein KDF)."""
    path = env_path_of(env_path)
    blob, key = encrypt_env_text(plaintext, password)
    header, _, _ = _unpack(blob)
    set_session_key(key, header=header)
    _adopt_header(header)
    _write_bytes_atomic(path, blob)
    _unlink_quiet(legacy_gobbledigook_path(path))
    return path


# Aliase (alte Namen)
write_gobbledigook_atomic = write_scrambled_atomic


def write_scrambled_with_key_atomic(
    env_path: Path | str, plaintext: str, key: bytes, *, header_template: dict | None = None,
) -> Path:
    path = env_path_of(env_path)
    salt = get_session_salt() or secrets.token_bytes(16)
    tpl = header_template if header_template is not None else get_session_header()
    if tpl:
        try:
            salt = bytes.fromhex(str(tpl.get("salt") or "")) or salt
        except ValueError:
            pass
    t = int((tpl or {}).get("t") or KDF_TIME)
    m = int((tpl or {}).get("m") or KDF_MEMORY)
    p = int((tpl or {}).get("p") or KDF_PARALLELISM)
    header = {
        "v": HEADER_VERSION,
        "kdf": "argon2id",
        "t": t,
        "m": m,
        "p": p,
        "salt": salt.hex(),
    }
    nonce = secrets.token_bytes(NONCE_LEN)
    aad = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ct = _aes_gcm_encrypt(key, nonce, plaintext.encode("utf-8"), aad)
    blob = _pack(header, nonce, ct)
    _write_bytes_atomic(path, blob)
    set_session_key(key, salt=salt, header=header)
    _unlink_quiet(legacy_gobbledigook_path(path))
    return path


write_gobbledigook_with_key_atomic = write_scrambled_with_key_atomic


def read_scrambled(env_path: Path | str, password: str) -> str:
    path = env_path_of(env_path)
    migrate_legacy_gobbledigook(path)
    if not is_env_scrambled(path):
        raise ScrambleError("Keine scrambled .env.")
    blob = path.read_bytes()
    plain, key = decrypt_env_blob(blob, password)
    header, _, _ = _unpack(blob)
    set_session_key(key, header=header)
    _adopt_header(header)
    return plain


read_gobbledigook = read_scrambled


def read_scrambled_with_session_key(env_path: Path | str) -> str:
    key = get_session_key()
    if not key:
        raise ScrambleLocked("Session-Key fehlt — Passwort eingeben.")
    path = env_path_of(env_path)
    migrate_legacy_gobbledigook(path)
    if not is_env_scrambled(path):
        raise ScrambleError("Keine scrambled .env.")
    return decrypt_env_blob_with_key(path.read_bytes(), key)


read_gobbledigook_with_session_key = read_scrambled_with_session_key


def probe_matches_plain(env_path: Path | str, password: str, plain_truth: str) -> None:
    gelesen = read_scrambled(env_path, password)
    if not structural_equal(gelesen, plain_truth):
        raise ScrambleError(
            "scrambled .env strukturell ungleich Klartext — Bug."
        )


def _backup_slots() -> int:
    try:
        from core.config import ENV_BACKUP_SLOTS
        return int(ENV_BACKUP_SLOTS)
    except Exception:
        return 10


def iter_env_backup_paths(env_path: Path | str, *, slots: int | None = None):
    """``.env.backup0`` … ``.env.backup{n-1}`` neben der Hauptdatei."""
    path = env_path_of(env_path)
    n = _backup_slots() if slots is None else max(0, int(slots))
    try:
        from core.config import env_backup_path
        for i in range(n):
            yield env_backup_path(path, i)
    except Exception:
        for i in range(n):
            yield path.with_name(f"{path.name}.backup{i}")


def scramble_sidecar_file(path: Path | str, password: str) -> bool:
    """
    Eine Backup-/Neben-``.env`` mit *password* scramblen.
    Session-Key der Haupt-``.env`` bleibt unberührt (eigenes Salt pro Datei).
    Rückgabe: True wenn geschrieben.
    """
    p = Path(path)
    if not p.is_file():
        return False
    if _file_starts_with_magic(p):
        return False
    try:
        plain = p.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ScrambleError(f"Backup unlesbar ({p.name}): {exc}") from exc
    blob, _key = encrypt_env_text(plain, password)
    _write_bytes_atomic(p, blob)
    return True


def unscramble_sidecar_file(path: Path | str, password: str) -> bool:
    """Scrambled Backup → Klartext. Session-Key unberührt. True wenn geschrieben."""
    p = Path(path)
    if not p.is_file():
        return False
    if not _file_starts_with_magic(p):
        return False
    plain, _key = decrypt_env_blob(p.read_bytes(), password)
    _write_text_atomic(p, plain)
    return True


def rescramble_sidecar_file(
    path: Path | str, old_password: str, new_password: str,
) -> bool:
    """Backup mit altem PW lesen (oder Klartext), mit neuem PW scramblen."""
    p = Path(path)
    if not p.is_file():
        return False
    if _file_starts_with_magic(p):
        plain, _ = decrypt_env_blob(p.read_bytes(), old_password)
    else:
        try:
            plain = p.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ScrambleError(f"Backup unlesbar ({p.name}): {exc}") from exc
    blob, _ = encrypt_env_text(plain, new_password)
    _write_bytes_atomic(p, blob)
    return True


def scramble_all_env_backups(env_path: Path | str, password: str, *, slots: int | None = None) -> int:
    """Alle ``.env.backup*`` scramblen (Klartext → Cipher). Anzahl geschrieben."""
    n = 0
    for backup in iter_env_backup_paths(env_path, slots=slots):
        if scramble_sidecar_file(backup, password):
            n += 1
    return n


def unscramble_all_env_backups(env_path: Path | str, password: str, *, slots: int | None = None) -> int:
    """Alle scrambled ``.env.backup*`` → Klartext. Anzahl geschrieben."""
    n = 0
    for backup in iter_env_backup_paths(env_path, slots=slots):
        if unscramble_sidecar_file(backup, password):
            n += 1
    return n


def rescramble_all_env_backups(
    env_path: Path | str, old_password: str, new_password: str, *, slots: int | None = None,
) -> int:
    """Backups auf neues Passwort umschlüsseln. Anzahl geschrieben."""
    n = 0
    for backup in iter_env_backup_paths(env_path, slots=slots):
        if rescramble_sidecar_file(backup, old_password, new_password):
            n += 1
    return n


def enable_scramble(env_path: Path | str, plaintext: str, password: str) -> None:
    """Passwort gesetzt: ``.env`` scrambled + alle ``.env.backup*``."""
    text = plaintext if plaintext.endswith("\n") else plaintext + "\n"
    write_scrambled_atomic(env_path, text, password)
    gelesen = read_scrambled_with_session_key(env_path)
    if not structural_equal(gelesen, text):
        raise ScrambleError(
            "scrambled .env strukturell ungleich Klartext — Bug."
        )
    scramble_all_env_backups(env_path, password)


def discard_locked_env(env_path: Path | str) -> None:
    """Passwort vergessen: verschlüsselte ``.env`` und Backups weg, ohne Klartext.

    Es bleibt eine leere Klartext-``.env``. Der alte Inhalt ist ohne Passwort
    nicht lesbar und wird nicht in ein Backup gerettet, das denselben Schlüssel
    bräuchte.
    """
    path = env_path_of(env_path)
    for extra in (legacy_gobbledigook_path(path), gobbledigook_path(path)):
        _unlink_quiet(extra)
    for backup in iter_env_backup_paths(path):
        _unlink_quiet(backup)
    _write_text_atomic(path, "")
    clear_session_key()


def disable_scramble(env_path: Path | str, password: str) -> str:
    """Passwort gelöscht: ``.env`` + alle ``.env.backup*`` → Klartext."""
    path = env_path_of(env_path)
    migrate_legacy_gobbledigook(path)
    if is_env_scrambled(path):
        plain = read_scrambled(path, password)
    elif path.is_file():
        plain = path.read_text(encoding="utf-8")
    else:
        raise ScrambleError("Keine .env.")
    _write_text_atomic(path, plain)
    _unlink_quiet(legacy_gobbledigook_path(path))
    # Backups best-effort (kaputte Einzeldateien blockieren Disable nicht).
    for backup in iter_env_backup_paths(path):
        try:
            unscramble_sidecar_file(backup, password)
        except ScrambleError:
            pass
    clear_session_key()
    return plain


def change_scramble_password(
    env_path: Path | str, old_password: str, new_password: str,
) -> None:
    path = env_path_of(env_path)
    migrate_legacy_gobbledigook(path)
    if is_env_scrambled(path):
        plain = read_scrambled(path, old_password)
    elif path.is_file():
        plain = path.read_text(encoding="utf-8")
    else:
        raise ScrambleError("Keine .env.")
    write_scrambled_atomic(path, plain, new_password)
    probe_matches_plain(path, new_password, plain)
    rescramble_all_env_backups(path, old_password, new_password)


def save_plaintext_or_scramble(env_path: Path | str, plaintext: str) -> None:
    """
    Write-Hook: mit Session-Key / aktivem Scramble → scrambled ``.env``;
    sonst Klartext-``.env``.
    """
    path = env_path_of(env_path)
    key = get_session_key()
    text = plaintext if plaintext.endswith("\n") else plaintext + "\n"
    active = is_scramble_file_present(path) or key is not None

    if active:
        if key is None:
            raise ScrambleLocked(
                "Passwort-Scramble aktiv — Session-Key fehlt, Speichern blockiert."
            )
        header = get_session_header()
        write_scrambled_with_key_atomic(path, text, key, header_template=header)
        gelesen = decrypt_env_blob_with_key(path.read_bytes(), key)
        if not structural_equal(gelesen, text):
            raise ScrambleError("Nach Write: scrambled .env ≠ RAM — Bug.")
        return

    _write_text_atomic(path, text)


def load_plaintext_or_scramble(env_path: Path | str) -> str:
    """
    Read-Hook: scrambled ``.env`` + Key → Text; scrambled ohne Key → Locked;
    sonst Klartext-``.env``.
    """
    path = env_path_of(env_path)
    migrate_legacy_gobbledigook(path)
    key = get_session_key()

    if is_env_scrambled(path):
        if key is None:
            raise ScrambleLocked(
                "Geschützte .env — Passwort eingeben (Login)."
            )
        return decrypt_env_blob_with_key(path.read_bytes(), key)

    if path.is_file():
        # Klartext — ggf. noch Legacy-Datei wegräumen wenn leer/irrelevant
        return path.read_text(encoding="utf-8")
    return ""


def unlock_with_password(env_path: Path | str, password: str) -> str:
    """Login/Unlock: File-Key setzen, Klartext im RAM."""
    path = env_path_of(env_path)
    migrate_legacy_gobbledigook(path)
    if is_env_scrambled(path):
        return read_scrambled(path, password)
    if path.is_file():
        plain = path.read_text(encoding="utf-8")
        # Passwort gesetzt, .env noch Klartext → jetzt scramblen
        enable_scramble(path, plain, password)
        return plain
    raise ScrambleError("Keine .env.")
