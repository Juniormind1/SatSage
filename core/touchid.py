"""Touch ID beim Login (nur macOS, opt-in).

Das SatSage-Passwort bleibt die Quelle der Wahrheit. Touch ID ersetzt nur
das Tippen: Nach einem Login mit Passwort kann der Nutzer Touch ID für
diesen Mac aktivieren. Das Hilfsprogramm ``satsage-touchid``
(``packaging/macos/satsage-touchid.swift``) legt das Passwort dann als
Generic Password im dateibasierten Login-Schlüsselbund ab. Beim nächsten
Login fragt es zuerst den Fingerabdruck ab
(``LAPolicy.deviceOwnerAuthenticationWithBiometrics``). Erst danach gibt es
das Passwort zurück. Der Server prüft es wie ein getipptes Passwort gegen
den Hash und entsperrt damit die ``.env``.

Protokoll zum Hilfsprogramm: eine JSON-Zeile auf stdin, eine JSON-Zeile
auf stdout. argv bleibt leer, das Passwort steht nie in der Prozessliste.

Linux, Windows, StartOS, Umbrel und Specter: ``MacHelperBackend.available``
ist dort immer ``False``. Ohne Marker-Datei ruft ``invalidate`` kein
Hilfsprogramm auf. Damit ändert sich auf diesen Plattformen nichts.

Diagnose: ``log_event`` schreibt eine Zeile pro Ereignis nach
``logs/touchid.log`` (nur macOS) und an den Logger ``satsage.server.touchid``.
Erlaubt sind nur Codes, Zahlen, ja/nein, Dauer und ein anonymisierter
Helper-Ort. Nie Passwort, Passwortlänge, Schlüsselbund-Inhalt,
DomainState-Bytes, voller Account-Hash oder Benutzername im Pfad.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

LOGGER = logging.getLogger("satsage.server.touchid")

HELPER_NAME = "satsage-touchid"
#: Nur für Entwicklung und Selbsttest am Mac: Pfad zu einem selbst
#: gebauten Hilfsprogramm, wenn SatSage aus dem Quellbaum läuft.
ENV_HELPER = "SATSAGE_TOUCHID_HELPER"
MARKER_NAME = ".satsage-touchid"
PROTOCOL_VERSION = 1

TIMEOUT_DIALOG = 60.0
TIMEOUT_PROBE = 5.0
PROBE_CACHE_SECONDS = 60.0

#: Fehlercodes des Hilfsprogramms und dieses Moduls.
CODES = frozenset({
    "cancelled",      # Abbruch durch Nutzer oder System
    "failed",         # Fingerabdruck nicht erkannt
    "not_available",  # kein Touch ID, nicht eingerichtet, keine GUI-Sitzung
    "locked_out",     # zu viele Fehlversuche, macOS will das Mac-Passwort
    "invalidated",    # Fingerabdrücke geändert (DomainState)
    "not_found",      # kein Schlüsselbund-Eintrag
    "keychain",       # Schlüsselbund-Fehler
    "timeout",        # Dialog nicht beantwortet
    "busy",           # anderer Touch-ID-Dialog läuft
    "helper_missing", # Hilfsprogramm fehlt
    "error",          # alles andere
})


class TouchIdError(Exception):
    """Touch ID hat kein Passwort geliefert. ``code`` aus ``CODES``.

    ``diag`` trägt nur Codes aus der Helper-Antwort (la_name, la_code,
    osstatus, domain_changed), nie Daten.
    """

    def __init__(self, code: str, message: str = "", *, diag: dict | None = None) -> None:
        self.code = code if code in CODES else "error"
        self.diag = dict(diag or {})
        super().__init__(message or self.code)


# ---------------------------------------------------------------------------
# Diagnose-Log: nur Codes, nie Daten
# ---------------------------------------------------------------------------

LOG_DATEI = "touchid.log"
_LOG_MAX_BYTES = 512 * 1024
_log_sperre = threading.Lock()
#: Tests: Zielpfad erzwingen (auch außerhalb von macOS).
_log_pfad_override: Path | None = None
_CODE_WERT = re.compile(r"^[A-Za-z0-9_.()+-]{1,48}$")
_SCHLUESSEL = re.compile(r"^[a-z_]{1,24}$")
#: Felder, deren Text-Wert ein Code ist. Alles andere muss Zahl/bool sein.
_TEXT_FELDER = frozenset({
    "cmd", "code", "route", "entscheidung", "grund", "ergebnis", "quelle",
    "datei", "biometry", "la", "la_name", "plattform", "verwaltung",
    "konto", "ausnahme", "stderr",
})
#: Felder mit eigenem, engem Format.
_FELD_MUSTER = {
    "konto": re.compile(r"^(?:[0-9a-f]{8}…|-)$"),
    "datei": re.compile(r"^(?:bin/)?[A-Za-z0-9_.-]{1,40}$"),
    "stderr": re.compile(r"^(?:-|[a-z_]{1,24}=[A-Za-z0-9_()+-]{1,40}(?:,[a-z_]{1,24}=[A-Za-z0-9_()+-]{1,40}){0,7})$"),
}
_HELPER_DIAG = ("la_name", "la_code", "osstatus", "domain_changed")


def setze_log_pfad(pfad: Path | str | None) -> None:
    """Tests: Diagnose-Log in diese Datei schreiben (``None``: Standard)."""
    global _log_pfad_override
    _log_pfad_override = Path(pfad) if pfad else None


def log_pfad() -> Path | None:
    """Ziel von ``touchid.log``; ``None`` außerhalb von macOS."""
    if _log_pfad_override is not None:
        return _log_pfad_override
    if sys.platform != "darwin":
        return None
    from core.paths import log_dir

    return log_dir() / LOG_DATEI


def konto_kurz(account: str) -> str:
    """Nur die ersten 8 Hex-Zeichen, damit Zeilen zuordenbar bleiben."""
    kopf = str(account or "")[:8]
    return f"{kopf}…" if re.fullmatch(r"[0-9a-f]{8}", kopf) else "-"


def _wert(schluessel: str, wert: object) -> str:
    if isinstance(wert, bool):
        return "ja" if wert else "nein"
    if isinstance(wert, int):
        return str(wert)
    if isinstance(wert, float):
        return f"{wert:.0f}" if wert.is_integer() else f"{wert:.1f}"
    if wert is None:
        return "-"
    text = str(wert)
    muster = _FELD_MUSTER.get(schluessel)
    if muster is not None:
        return text if muster.match(text) else "<gefiltert>"
    if schluessel in _TEXT_FELDER and _CODE_WERT.match(text):
        return text
    return "<gefiltert>"


def log_event(ereignis: str, *, warnung: bool = False, **felder: object) -> None:
    """Eine Diagnosezeile. Werte außer Codes/Zahlen/bool werden gefiltert.

    Darf nie einen Fehler werfen und nie den Login aufhalten.
    """
    try:
        name = ereignis if _CODE_WERT.match(str(ereignis)) else "ereignis"
        teile = [name]
        for schluessel, wert in felder.items():
            if not _SCHLUESSEL.match(schluessel):
                continue
            teile.append(f"{schluessel}={_wert(schluessel, wert)}")
        zeile = " ".join(teile)
        (LOGGER.warning if warnung else LOGGER.info)("Touch ID: %s", zeile)
        ziel = log_pfad()
        if ziel is None:
            return
        kopf = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with _log_sperre:
            ziel.parent.mkdir(parents=True, exist_ok=True)
            try:
                if ziel.stat().st_size > _LOG_MAX_BYTES:
                    os.replace(ziel, ziel.with_name(ziel.name + ".1"))
            except FileNotFoundError:
                pass
            with ziel.open("a", encoding="utf-8") as datei:
                datei.write(f"{kopf} {zeile}\n")
    except Exception:  # pragma: no cover - Diagnose darf nie stören
        pass


def helper_diag(exc_or_antwort: object) -> dict:
    """Nur die erlaubten Diagnosefelder aus einer Helper-Antwort/Exception."""
    quelle = exc_or_antwort.diag if isinstance(exc_or_antwort, TouchIdError) else exc_or_antwort
    if not isinstance(quelle, dict):
        return {}
    aus: dict = {}
    for key in _HELPER_DIAG:
        wert = quelle.get(key)
        if key == "domain_changed" and isinstance(wert, bool):
            aus[key] = wert
        elif key in ("la_code", "osstatus") and isinstance(wert, int) and not isinstance(wert, bool):
            aus[key] = wert
        elif key == "la_name" and isinstance(wert, str) and _CODE_WERT.match(wert):
            aus[key] = wert
    return aus


_STDERR_SCHLUESSEL = frozenset({"cmd", "code", "available", "la", "osstatus", "domain_changed"})


def _stderr_paar_ok(paar: str) -> bool:
    """Nur bekannte Schlüssel mit Code-Werten (k=v), sonst gilt die Zeile als fremd."""
    schluessel, _, wert = paar.partition("=")
    return schluessel in _STDERR_SCHLUESSEL and bool(re.fullmatch(r"[A-Za-z0-9_()+-]{1,40}", wert))


def _stderr_diag(stderr: bytes | None) -> str:
    """Letzte eigene Diagnosezeile des Helpers als Code-Kette, sonst '-'.

    Nur Zeilen im eigenen Format ``satsage-touchid: k=v …`` mit Code-Werten.
    Fremder Text (z. B. Absturzmeldungen) wird nicht übernommen.
    """
    for roh in reversed((stderr or b"").splitlines()):
        try:
            text = roh.decode("utf-8").strip()
        except UnicodeError:
            continue
        if not text.startswith("satsage-touchid: "):
            continue
        paare = text[len("satsage-touchid: "):].split()
        if paare and all(_stderr_paar_ok(p) for p in paare):
            return ",".join(paare)
    return "-"


class TouchIdBackend(Protocol):
    def available(self) -> bool: ...

    def enroll(self, account: str, password: str, reason: str) -> None: ...

    def unlock(self, account: str, reason: str) -> str: ...

    def remove(self, account: str) -> None: ...


def account_for(env_path: Path | str) -> str:
    """Schlüsselbund-Account: SHA-256 des absoluten ``.env``-Pfads.

    Mehrere Datenordner auf einem Mac bekommen damit getrennte Einträge.
    Der Pfad selbst steht nicht im Schlüsselbund.
    """
    pfad = Path(env_path).expanduser()
    try:
        pfad = pfad.resolve()
    except OSError:
        pfad = pfad.absolute()
    return hashlib.sha256(str(pfad).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Marker: nicht geheim, sagt nur „für diese .env ist Touch ID aktiv“.
# ---------------------------------------------------------------------------


def marker_path(env_path: Path | str) -> Path:
    return Path(env_path).expanduser().parent / MARKER_NAME


def is_enrolled(env_path: Path | str) -> bool:
    try:
        daten = json.loads(marker_path(env_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return False
    return isinstance(daten, dict) and daten.get("account") == account_for(env_path)


def write_marker(env_path: Path | str) -> None:
    pfad = marker_path(env_path)
    inhalt = json.dumps({
        "version": PROTOCOL_VERSION,
        "account": account_for(env_path),
        "aktiviert": int(time.time()),
    }) + "\n"
    tmp = pfad.with_name(f"{pfad.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(inhalt, encoding="utf-8")
        os.replace(tmp, pfad)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def remove_marker(env_path: Path | str) -> None:
    try:
        marker_path(env_path).unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def _ist_ausfuehrbar(pfad: Path) -> bool:
    return pfad.is_file() and os.access(pfad, os.X_OK)


class MacHelperBackend:
    """Ruft das Swift-Hilfsprogramm per subprocess auf (nur macOS)."""

    def __init__(self, helper: Path | str | None = None, *, platform: str | None = None) -> None:
        self._helper = Path(helper) if helper else None
        self._platform = platform or sys.platform
        self._probe_lock = threading.Lock()
        self._probe_stand: tuple[float, bool] | None = None

    def helper_path(self) -> Path | None:
        pfad, _quelle = self._helper_suche()
        return pfad

    def _helper_suche(self) -> tuple[Path | None, str]:
        """(Pfad, Quelle). Quelle: fest, env, bundle, app_dir oder keine."""
        if self._helper is not None:
            return (self._helper if _ist_ausfuehrbar(self._helper) else None), "fest"
        kandidaten: list[tuple[Path, str]] = []
        override = os.environ.get(ENV_HELPER, "").strip()
        if override:
            kandidaten.append((Path(override).expanduser(), "env"))
        from core.paths import app_dir, resource_dir

        gebuendelt = resource_dir() / "bin" / HELPER_NAME
        kandidaten.append((gebuendelt, "bundle"))
        kandidaten.append((app_dir() / HELPER_NAME, "app_dir"))
        # Onefile entpackt ins Temp-Verzeichnis. Fehlt dort das x-Bit,
        # einmal setzen (nur dieser Kopie, nur im eigenen _MEI-Ordner).
        if self._platform == "darwin" and gebuendelt.is_file() and not os.access(gebuendelt, os.X_OK):
            try:
                os.chmod(gebuendelt, 0o700)
                log_event("helper_xbit_gesetzt", quelle="bundle")
            except OSError as exc:
                log_event("helper_xbit_fehler", warnung=True, quelle="bundle", errno=exc.errno or 0)
        for kandidat, quelle in kandidaten:
            if _ist_ausfuehrbar(kandidat):
                return kandidat, quelle
        return None, "keine"

    def _helper_melden(self, pfad: Path | None, quelle: str) -> None:
        """Helper-Fund einmal pro Änderung loggen: Quelle und Dateiname, kein Pfad."""
        stand = (quelle, pfad is not None)
        if getattr(self, "_helper_stand", None) == stand:
            return
        self._helper_stand = stand
        if pfad is None:
            log_event("helper", warnung=True, vorhanden=False, quelle="keine")
        else:
            log_event(
                "helper",
                vorhanden=True,
                quelle=quelle,
                # Nur der Dateiname, nie ein Ordner (der könnte der Benutzername sein).
                datei=f"bin/{pfad.name}" if quelle == "bundle" else pfad.name,
                onefile_temp=("_MEI" in str(pfad)),
            )

    def _call(self, payload: dict, *, timeout: float) -> dict:
        """Helper aufrufen und das Ergebnis als Codes loggen.

        Geloggt werden cmd, Ergebnis-Code, Dauer, Exit-Code, LAError,
        OSStatus, DomainState geändert ja/nein und Timeout. Nie stdin,
        nie stdout roh, nie Passwort oder dessen Länge.
        """
        cmd = str(payload.get("cmd") or "-")
        konto = konto_kurz(str(payload.get("account") or ""))
        helper, quelle = self._helper_suche()
        self._helper_melden(helper, quelle)
        if helper is None:
            log_event("helper_call", warnung=True, cmd=cmd, ergebnis="helper_missing", konto=konto)
            raise TouchIdError("helper_missing", "Touch-ID-Hilfsprogramm fehlt.")
        daten = dict(payload)
        daten["v"] = PROTOCOL_VERSION
        eingabe = (json.dumps(daten, ensure_ascii=False) + "\n").encode("utf-8")
        del daten
        start = time.monotonic()

        def dauer() -> int:
            return int((time.monotonic() - start) * 1000)

        try:
            ergebnis = subprocess.run(
                [str(helper)],
                input=eingabe,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            # subprocess.run hat den Prozess beendet; der Dialog verschwindet mit.
            log_event(
                "helper_call", warnung=True, cmd=cmd, ergebnis="timeout",
                timeout_s=timeout, dauer_ms=dauer(), konto=konto,
            )
            raise TouchIdError("timeout", "Touch ID nicht rechtzeitig bestätigt.") from None
        except OSError as exc:
            log_event(
                "helper_call", warnung=True, cmd=cmd, ergebnis="helper_missing",
                errno=exc.errno or 0, dauer_ms=dauer(), konto=konto,
            )
            raise TouchIdError("helper_missing", "Hilfsprogramm nicht startbar.") from None
        finally:
            del eingabe
        zeile = (ergebnis.stdout or b"").strip().splitlines()
        try:
            antwort = json.loads(zeile[-1].decode("utf-8")) if zeile else {}
        except (ValueError, UnicodeError):
            antwort = {}
        stderr = _stderr_diag(ergebnis.stderr)
        if not isinstance(antwort, dict) or not antwort:
            log_event(
                "helper_call", warnung=True, cmd=cmd, ergebnis="keine_antwort",
                exit=ergebnis.returncode, stdout_zeilen=len(zeile), dauer_ms=dauer(),
                stderr=stderr, konto=konto,
            )
            raise TouchIdError("error", f"Hilfsprogramm ohne Antwort (Exit {ergebnis.returncode}).")
        diag = helper_diag(antwort)
        if not antwort.get("ok"):
            code = str(antwort.get("code") or "error")
            fehler = TouchIdError(code, "", diag=diag)
            log_event(
                "helper_call", warnung=fehler.code not in ("cancelled", "not_found"),
                cmd=cmd, ergebnis=fehler.code, exit=ergebnis.returncode, dauer_ms=dauer(),
                stderr=stderr, konto=konto, **diag,
            )
            raise fehler
        extra: dict = {}
        if cmd == "probe":
            extra = {
                "available": bool(antwort.get("available")),
                "grund": antwort.get("reason") or "-",
                "biometry": antwort.get("biometry") or "-",
                "eintrag": bool(antwort.get("has_item")),
            }
        log_event(
            "helper_call", cmd=cmd, ergebnis="ok", exit=ergebnis.returncode,
            dauer_ms=dauer(), konto=konto, **diag, **extra,
        )
        return antwort

    def available(self) -> bool:
        if self._platform != "darwin":
            # Kein Log: auf Linux/Windows/Docker fragt jede Statusseite.
            return False
        helper, quelle = self._helper_suche()
        self._helper_melden(helper, quelle)
        if helper is None:
            self._verfuegbar_melden(False, "helper_missing")
            return False
        jetzt = time.monotonic()
        with self._probe_lock:
            if self._probe_stand and jetzt - self._probe_stand[0] < PROBE_CACHE_SECONDS:
                return self._probe_stand[1]
            try:
                antwort = self._call({"cmd": "probe"}, timeout=TIMEOUT_PROBE)
                ok = bool(antwort.get("available"))
                grund = "ok" if ok else str(antwort.get("reason") or "not_available")
            except TouchIdError as exc:
                ok = False
                grund = exc.code
            self._probe_stand = (jetzt, ok)
            self._verfuegbar_melden(ok, grund)
            return ok

    def _verfuegbar_melden(self, ok: bool, grund: str) -> None:
        """Verfügbarkeit nur bei Änderung loggen, nicht bei jeder Statusseite."""
        stand = (ok, grund)
        if getattr(self, "_verfuegbar_stand", None) == stand:
            return
        self._verfuegbar_stand = stand
        log_event("backend", verfuegbar=ok, grund=grund, plattform=self._platform)

    def forget_probe(self) -> None:
        with self._probe_lock:
            self._probe_stand = None

    def enroll(self, account: str, password: str, reason: str) -> None:
        if not password:
            raise TouchIdError("error", "Passwort fehlt.")
        self._call(
            {"cmd": "enroll", "account": account, "password": password, "reason": reason},
            timeout=TIMEOUT_DIALOG,
        )

    def unlock(self, account: str, reason: str) -> str:
        antwort = self._call(
            {"cmd": "unlock", "account": account, "reason": reason},
            timeout=TIMEOUT_DIALOG,
        )
        password = antwort.get("password")
        if not isinstance(password, str) or not password:
            raise TouchIdError("not_found", "Kein Passwort im Schlüsselbund.")
        return password

    def remove(self, account: str) -> None:
        try:
            self._call({"cmd": "remove", "account": account}, timeout=TIMEOUT_PROBE)
        except TouchIdError as exc:
            if exc.code != "not_found":
                raise


class FakeBackend:
    """Nur für Tests. Wird ausschließlich über ``set_backend`` aktiv."""

    def __init__(self, *, available: bool = True) -> None:
        self.is_available = available
        self.store: dict[str, str] = {}
        #: Nächster Fehlercode für enroll/unlock (einmalig), z. B. "cancelled".
        self.next_error: str | None = None
        self.calls: list[tuple[str, str]] = []
        #: Optional: blockiert unlock, bis das Event gesetzt ist (Busy-Test).
        self.unlock_gate: threading.Event | None = None

    def available(self) -> bool:
        return self.is_available

    def _fehler_pruefen(self) -> None:
        if self.next_error:
            code, self.next_error = self.next_error, None
            raise TouchIdError(code)

    def enroll(self, account: str, password: str, reason: str) -> None:
        self.calls.append(("enroll", account))
        self._fehler_pruefen()
        self.store[account] = password

    def unlock(self, account: str, reason: str) -> str:
        self.calls.append(("unlock", account))
        if self.unlock_gate is not None:
            self.unlock_gate.wait(5)
        self._fehler_pruefen()
        if account not in self.store:
            raise TouchIdError("not_found")
        return self.store[account]

    def remove(self, account: str) -> None:
        self.calls.append(("remove", account))
        self.store.pop(account, None)


_backend_lock = threading.Lock()
_backend: TouchIdBackend | None = None


def get_backend() -> TouchIdBackend:
    global _backend
    with _backend_lock:
        if _backend is None:
            _backend = MacHelperBackend()
        return _backend


def set_backend(backend: TouchIdBackend | None) -> None:
    """Tests: Backend ersetzen. ``None`` setzt auf den Standard zurück."""
    global _backend
    with _backend_lock:
        _backend = backend


# ---------------------------------------------------------------------------
# Ein Dialog gleichzeitig
# ---------------------------------------------------------------------------

_dialog_lock = threading.Lock()


@contextmanager
def dialog_slot() -> Iterator[None]:
    """Nur ein Touch-ID-Dialog gleichzeitig; sonst ``TouchIdError('busy')``."""
    if not _dialog_lock.acquire(blocking=False):
        log_event("dialog_belegt", ergebnis="busy")
        raise TouchIdError("busy", "Ein Touch-ID-Dialog läuft bereits.")
    try:
        yield
    finally:
        _dialog_lock.release()


# ---------------------------------------------------------------------------
# Invalidierung
# ---------------------------------------------------------------------------


def invalidate(env_path: Path | str, grund: str = "unbekannt") -> bool:
    """Touch ID für diese ``.env`` abschalten: Marker und Schlüsselbund-Eintrag.

    Ohne Marker passiert nichts, auch kein Aufruf des Hilfsprogramms.
    Rückgabe True, wenn ein Marker da war. ``grund`` ist ein Code fürs Log.
    """
    if not marker_path(env_path).exists():
        return False
    account = account_for(env_path)
    remove_marker(env_path)
    try:
        get_backend().remove(account)
        log_event("invalidiert", grund=grund, eintrag_entfernt=True, konto=konto_kurz(account))
    except TouchIdError as exc:
        log_event(
            "invalidiert", warnung=True, grund=grund, eintrag_entfernt=False,
            code=exc.code, konto=konto_kurz(account), **helper_diag(exc),
        )
    except Exception as exc:  # pragma: no cover - defensiv
        log_event(
            "invalidiert", warnung=True, grund=grund, eintrag_entfernt=False,
            ausnahme=type(exc).__name__, konto=konto_kurz(account),
        )
    return True


def remove_entry(env_path: Path | str) -> None:
    """Wie ``invalidate``, aber auch ohne Marker den Eintrag entfernen.

    Für „Touch ID deaktivieren“: ein Rest im Schlüsselbund ohne Marker soll
    auch verschwinden.
    """
    account = account_for(env_path)
    remove_marker(env_path)
    backend = get_backend()
    if not backend.available():
        log_event("deaktiviert", eintrag_entfernt=False, grund="backend_aus", konto=konto_kurz(account))
        return
    try:
        backend.remove(account)
        log_event("deaktiviert", eintrag_entfernt=True, konto=konto_kurz(account))
    except TouchIdError as exc:
        log_event(
            "deaktiviert", warnung=True, eintrag_entfernt=False, code=exc.code,
            konto=konto_kurz(account), **helper_diag(exc),
        )
