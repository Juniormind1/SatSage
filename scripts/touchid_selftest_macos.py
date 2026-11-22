#!/usr/bin/env python3
"""Selbsttest Touch ID am Mac (Spike M0 + Abnahme Hilfsprogramm).

Nur macOS. Baut ``packaging/macos/satsage-touchid.swift`` nach
``build/touchid-selftest/`` (im Worktree), signiert ad hoc und spielt die
Befehle mit einem **Test-Account** durch. Dein echter SatSage-Eintrag im
Schlüsselbund bleibt unberührt. Das Testpasswort ist zufällig und wird nie
ausgegeben.

    python3 scripts/touchid_selftest_macos.py            # interaktiv
    python3 scripts/touchid_selftest_macos.py --helper dist/…/satsage-touchid

Jeder Schritt druckt OK / FEHLER / HINWEIS. Die Antworten auf die Fragen
(„Kam ein Schlüsselbund-Dialog?“) bitte ins Testprotokoll
``doc/testprotokoll-touchid-macos.md`` übernehmen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import touchid  # noqa: E402

SWIFT = ROOT / "packaging" / "macos" / "satsage-touchid.swift"
OUT = ROOT / "build" / "touchid-selftest"
TEST_ACCOUNT = hashlib.sha256(b"satsage-touchid-selftest").hexdigest()
REASON = "den SatSage-Selbsttest zu bestätigen"

ergebnisse: list[tuple[str, str, str]] = []


def melde(schritt: str, status: str, text: str = "") -> None:
    ergebnisse.append((schritt, status, text))
    print(f"[{status:7}] {schritt}{(' — ' + text) if text else ''}", flush=True)


def frage(text: str) -> bool:
    try:
        return input(f"    {text} [j/N] ").strip().lower() in ("j", "ja", "y", "yes")
    except EOFError:
        return False


def baue(ziel: Path, *, optimierung: str = "-O") -> Path:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    import platform

    target = f"{platform.machine()}-apple-macos11.0"
    subprocess.run(
        ["swiftc", optimierung, "-swift-version", "5", "-target", target,
         "-framework", "LocalAuthentication", "-framework", "Security",
         "-o", str(ziel), str(SWIFT)],
        check=True,
    )
    subprocess.run(["codesign", "--force", "--sign", "-", str(ziel)], check=True)
    return ziel


def roh(helper: Path, payload: dict, *, args: list[str] | None = None) -> dict:
    eingabe = (json.dumps({"v": touchid.PROTOCOL_VERSION, **payload}) + "\n").encode()
    lauf = subprocess.run([str(helper), *(args or [])], input=eingabe,
                          capture_output=True, timeout=90, check=False)
    try:
        return json.loads(lauf.stdout.decode().strip().splitlines()[-1])
    except (IndexError, ValueError):
        # Nur die eigene Code-Zeile des Helpers, nie freien stderr-Text.
        return {"ok": False, "code": "kein_json", "message": touchid._stderr_diag(lauf.stderr)}


def codes(exc: touchid.TouchIdError) -> str:
    """Fehlercode plus LAError/OSStatus, ohne Daten."""
    teile = [exc.code] + [f"{k}={v}" for k, v in touchid.helper_diag(exc).items()]
    return " ".join(teile)


def anzeige_pfad(pfad: Path) -> str:
    """Pfad ohne Benutzernamen: relativ zum Repo oder mit ~."""
    if pfad.is_relative_to(ROOT):
        return str(pfad.relative_to(ROOT))
    if pfad.is_relative_to(Path.home()):
        return "~/" + str(pfad.relative_to(Path.home()))
    return pfad.name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--helper", help="vorhandenes Hilfsprogramm statt neu zu bauen")
    parser.add_argument("--ohne-neubau-test", action="store_true",
                        help="Schritt „neu gebautes Programm“ auslassen")
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("Nur auf macOS sinnvoll.", file=sys.stderr)
        return 2
    if args.helper:
        helper = Path(args.helper).resolve()
    else:
        if not shutil.which("swiftc"):
            print("swiftc fehlt: xcode-select --install", file=sys.stderr)
            return 2
        helper = baue(OUT / "a" / touchid.HELPER_NAME)
    melde("Hilfsprogramm", "OK", anzeige_pfad(helper))
    log_datei = OUT / "touchid-selftest.log"
    log_datei.parent.mkdir(parents=True, exist_ok=True)
    log_datei.write_text("", encoding="utf-8")
    touchid.setze_log_pfad(log_datei)

    sig = subprocess.run(["codesign", "-dv", str(helper)], capture_output=True, text=True)
    signatur = next((z for z in sig.stderr.splitlines() if z.startswith("Signature=")), "?")
    melde("Signatur", "HINWEIS", signatur)

    antwort = roh(helper, {"cmd": "probe"}, args=["--passwort", "x"])
    melde("argv wird abgelehnt", "OK" if not antwort.get("ok") else "FEHLER", str(antwort.get("message", "")))

    antwort = roh(helper, {"cmd": "probe", "account": TEST_ACCOUNT})
    verfuegbar = bool(antwort.get("available"))
    melde("probe", "OK" if verfuegbar else "FEHLER",
          f"available={verfuegbar} biometry={antwort.get('biometry')} reason={antwort.get('reason', '-')} "
          f"la={antwort.get('la_name', '-')}({antwort.get('la_code', '-')})")
    if not verfuegbar:
        print("Ohne Touch ID (oder in SSH-/Clamshell-Sitzung) endet der Test hier.")
        return 1

    backend = touchid.MacHelperBackend(helper)
    melde("Python-Backend available()", "OK" if backend.available() else "FEHLER")

    test_pw = "selftest-" + secrets.token_urlsafe(18)
    print("\n→ Aktivieren: Gleich erscheint der Touch-ID-Dialog. Finger auflegen.")
    try:
        backend.enroll(TEST_ACCOUNT, test_pw, REASON)
        melde("enroll", "OK")
    except touchid.TouchIdError as exc:
        melde("enroll", "FEHLER", codes(exc))
        return 1
    melde("Dialogtext lesbar", "OK" if frage("Stand im Dialog „… den SatSage-Selbsttest zu bestätigen“?") else "HINWEIS")

    print("\n→ Entsperren: Finger auflegen.")
    try:
        gelesen = backend.unlock(TEST_ACCOUNT, REASON)
        melde("unlock liefert dasselbe Passwort", "OK" if gelesen == test_pw else "FEHLER")
    except touchid.TouchIdError as exc:
        melde("unlock", "FEHLER", codes(exc))
    melde("kein Schlüsselbund-Dialog beim selben Programm",
          "OK" if not frage("Kam zusätzlich ein Schlüsselbund-Dialog (Mac-Passwort)?") else "HINWEIS")

    print("\n→ Abbrechen: Im nächsten Dialog bitte auf „Abbrechen“ klicken.")
    try:
        backend.unlock(TEST_ACCOUNT, REASON)
        melde("Abbruch erkannt", "FEHLER", "Dialog wurde bestätigt")
    except touchid.TouchIdError as exc:
        melde("Abbruch erkannt", "OK" if exc.code == "cancelled" else "FEHLER", codes(exc))

    print("\n→ Anderer Pfad (wie PyInstaller-_MEI-Ordner): Finger auflegen.")
    kopie = OUT / "kopie" / touchid.HELPER_NAME
    kopie.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(helper, kopie)
    try:
        gelesen = touchid.MacHelperBackend(kopie).unlock(TEST_ACCOUNT, REASON)
        melde("unlock aus kopiertem Programm", "OK" if gelesen == test_pw else "FEHLER")
    except touchid.TouchIdError as exc:
        melde("unlock aus kopiertem Programm", "FEHLER", codes(exc))
    melde("kein Schlüsselbund-Dialog nach Pfadwechsel",
          "OK" if not frage("Kam ein Schlüsselbund-Dialog?") else "HINWEIS",
          "wichtig für Onefile")

    if not args.ohne_neubau_test and shutil.which("swiftc"):
        print("\n→ Neu gebautes Programm (wie nach einem Update, andere cdhash): Finger auflegen.")
        neu = baue(OUT / "b" / touchid.HELPER_NAME, optimierung="-Onone")
        try:
            gelesen = touchid.MacHelperBackend(neu).unlock(TEST_ACCOUNT, REASON)
            melde("unlock nach Neubau", "OK" if gelesen == test_pw else "FEHLER")
        except touchid.TouchIdError as exc:
            melde("unlock nach Neubau", "HINWEIS", codes(exc))
        melde("Schlüsselbund-Dialog nach Neubau",
              "HINWEIS", "ja" if frage("Kam ein Schlüsselbund-Dialog (Mac-Passwort, „Immer erlauben“)?") else "nein")

    try:
        backend.remove(TEST_ACCOUNT)
        melde("remove", "OK")
    except touchid.TouchIdError as exc:
        melde("remove", "FEHLER", codes(exc))
    antwort = roh(helper, {"cmd": "probe", "account": TEST_ACCOUNT})
    melde("Eintrag weg", "OK" if antwort.get("has_item") is False else "FEHLER")

    print("\nZusammenfassung (ins Testprotokoll übernehmen):")
    for schritt, status, text in ergebnisse:
        print(f"  - {status}: {schritt}{(' — ' + text) if text else ''}")
    print(f"\nDiagnose-Log (nur Codes, ohne Passwort): {anzeige_pfad(log_datei)}")
    print("Bitte Zusammenfassung und diese Datei zurückschicken.")
    return 0 if all(s != "FEHLER" for _, s, _ in ergebnisse) else 1


if __name__ == "__main__":
    raise SystemExit(main())
