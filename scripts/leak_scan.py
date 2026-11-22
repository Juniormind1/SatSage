#!/usr/bin/env python3
"""Inhalts-Scan gegen versehentlich committete Geheimnisse und Börsen-Exporte.

Reines Python, keine Extra-Abhängigkeit. Aufruf:

    python scripts/leak_scan.py --staged
    python scripts/leak_scan.py --tracked
    python scripts/leak_scan.py PFAD [PFAD ...]

Exit 1, sobald ein Treffer vorliegt. Erlaubte Testvektoren stehen nur als
SHA-256 in der Allowlist, nicht als Klartext.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = (REPO_ROOT / "tests" / "fixtures" / "boerse").resolve()

# SHA-256 der bekannten öffentlichen Testvektoren (BIP-84 u. a. aus
# tests/fixtures.py) sowie fest im Repo stehender Descriptor-Schlüssel.
# Kein Klartext-Schlüssel in dieser Datei.
ALLOWLIST_SHA256 = frozenset({
    "e06675e6ba2f9dddf8e87123bb2d426b1b2b663382d500e47e4f1126996fd074",  # BIP-84 zpub
    "6b3ac4bc7086bb6ca2696a5b682806ee4e74eac5574562969f340a91d77e76bb",  # BIP-84 als xpub
    "7e2906784f6949e4e42a93b1f93f727e48371f188928e903063a7207c481411e",  # zweiter Test-zpub
    "0a84d841f4ce6645fcbe71f851ea132630ef4e6f1518e98a8728c3e5dd69e0fc",  # zweiter als xpub
    "9fccb3234066f7b5e1d029d019390324abd980d45a5d10f12610ca4a8e949400",  # BIP84 receive 0
    "0eb066812962c2bdf5237717179a2a7345ea46717049a521459d3f374c649e27",  # BIP84 receive 1
    "6272b35573be6deed933f875bfe092459734c915deacf9449000af5e01fdf873",  # BIP84 change 0
    "6cd42dab0217b54fdf5df95b892f055d2a462baa8c0b269e71e4ba6ec65ca66b",  # BIP-173 EXTERN_A
    "69bfba1ac9ac22d45219a82fd343747a51fcf3e51b7f2c91c49bb9c1fe123012",  # BIP-173 EXTERN_B
    # Bereits im öffentlichen Repo stehende Beispiel-/Testadressen
    "7273c851296e3e0e564b5ac6d1158611b83e20dae292d69982d3e0c74d36d83c",  # bc1qar0srrr7… (Wiki-Beispiel)
    "3893794d2870f0abbe0093dcbf6a9c6b48cf209cd1ab61064d887e72b4481694",  # 1BoatSLRHtKN… (Test)
    "f33ef20f4f0ea121ec6a4f2047b87f95c726cce73b3726fdb6d2bfbab71d9676",  # test_wallet_alter A
    "ee0dc4efc01b79055483f786a5caaebef100fe392aede3f5bddb95ce165359f7",  # test_wallet_alter B
    "67fd685eca7e75b229d724cb78aa0deaa42a6fad5eb89077593571035b8ae89c",  # BIP-341 test bc1p0xlxv…
    "dc130b6083549636f7cc50d79a01a57407859eadd004c5e1a494bd7222e74e6d",  # 1BvBMSEYstWe… (Beispiel)
    "76c6b868ba92933a4c04ee0cc13b6dc5483a6097d77676880077b89f30e49e17",  # 3J98t1WpEZ73… (Beispiel)
    # BIP-32 Master-xprv des öffentlichen Testvektors (seed 0001…0f)
    "2243ae4c730144699810edff877f309b57c9f62289420157926505582ea6d1f9",
})

ERLAUBTE_EMAILS = frozenset({
    "juniormind@proton.me",
    "busch21@tutamail.com",
    "submissions@start9.com",  # offizielle StartOS-Einreichung, steht in der Doku
})
# Platzhalter und URL-Nutzer, keine persönlichen Postfächer.
_EMAIL_DOMAIN_AUSNAHME = frozenset({
    "example.com", "example.org", "example.net", "example.edu",
    "github.com", "gitlab.com", "bitbucket.org",
})
_EMAIL_LOKAL_AUSNAHME = frozenset({"git", "noreply", "no-reply"})

RE_EXT_KEY = re.compile(
    r"\b[xyzYZtuvUV]pub[1-9A-HJ-NP-Za-km-z]{100,112}\b"
)
RE_EXT_PRV = re.compile(
    r"\b[xt]prv[1-9A-HJ-NP-Za-km-z]{100,112}\b"
)
RE_DESCRIPTOR_FP = re.compile(
    r"\[[0-9a-fA-F]{8}/\d+h?/"
)
RE_KRAKEN_LEDGER_KOPF = re.compile(
    r'"txid"\s*,\s*"refid"\s*,\s*"time"\s*,\s*"type"',
    re.I,
)
RE_KRAKEN_TRADES_KOPF = re.compile(
    r'"txid"\s*,\s*"ordertxid"\s*,\s*"pair"\s*,\s*"time"',
    re.I,
)
RE_COINBASE_PRAEAMBEL = re.compile(
    r"^Transactions\b.*\bUser,",
    re.I | re.M,
)
RE_COINBASE_KOPF = re.compile(
    r"ID\s*,\s*Timestamp\s*,\s*Transaction Type\s*,\s*Asset\s*,\s*Quantity Transacted",
    re.I,
)
RE_STRIKE_KOPF = re.compile(
    r"Reference\s*,\s*Date & Time \(UTC\)\s*,\s*Transaction Type",
    re.I,
)
RE_KRAKEN_LEDGER_ID = re.compile(
    r"\bL[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{6}\b"
)
RE_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
RE_EMAIL = re.compile(
    r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",
    re.I,
)
RE_BECH32 = re.compile(r"\bbc1[qp][a-z0-9]{25,87}\b")
RE_BASE58_ADDR = re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")

_B58 = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


@dataclass(frozen=True)
class Fund:
    pfad: str
    regel: str
    zeile: int
    auszug: str


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _erlaubt(text: str) -> bool:
    return _sha(text) in ALLOWLIST_SHA256


def _ist_fixture(pfad: Path) -> bool:
    try:
        pfad.resolve().relative_to(FIXTURE_DIR)
        return True
    except ValueError:
        return False


def _hat_herkunft(pfad: Path) -> bool:
    return pfad.with_name(pfad.name + ".herkunft.md").is_file() or (
        pfad.with_suffix(pfad.suffix + ".herkunft.md").is_file()
    )


def herkunft_datei(csv_pfad: Path) -> Path:
    """Begleitdatei ``<name>.csv.herkunft.md``."""
    return csv_pfad.with_name(csv_pfad.name + ".herkunft.md")


def _iban_gueltig(iban: str) -> bool:
    umgestellt = iban[4:] + iban[:4]
    zahlen = []
    for z in umgestellt:
        if "0" <= z <= "9":
            zahlen.append(z)
        elif "A" <= z <= "Z":
            zahlen.append(str(ord(z) - 55))
        else:
            return False
    rest = 0
    for z in "".join(zahlen):
        rest = (rest * 10 + int(z)) % 97
    return rest == 1


def _base58_check_ok(addr: str) -> bool:
    try:
        zahlen = {c: i for i, c in enumerate(_B58.decode("ascii"))}
        n = 0
        for c in addr:
            if c not in zahlen:
                return False
            n = n * 58 + zahlen[c]
        lead = 0
        for c in addr:
            if c == "1":
                lead += 1
            else:
                break
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
        raw = b"\x00" * lead + raw
        if len(raw) < 25:
            raw = raw.rjust(25, b"\x00")
        if len(raw) != 25:
            return False
        payload, pruef = raw[:-4], raw[-4:]
        digest = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        if digest != pruef:
            return False
        return payload[0] in (0x00, 0x05)
    except Exception:
        return False


def _bech32_polymod(werte: list[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in werte:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= gen[i]
    return chk


def _bech32_ok(addr: str) -> bool:
    if addr != addr.lower() or not addr.startswith("bc1"):
        return False
    try:
        pos = addr.rfind("1")
        if pos < 1:
            return False
        hrp, daten = addr[:pos], addr[pos + 1:]
        if hrp != "bc" or len(daten) < 6:
            return False
        werte = []
        for c in daten:
            i = _BECH32_CHARSET.find(c)
            if i < 0:
                return False
            werte.append(i)
        expand = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
        chk = _bech32_polymod(expand + werte)
        # bech32 (v0 / q) = 1, bech32m (v1+ / p) = 0x2bc830a3
        if addr[3] == "q":
            return chk == 1
        if addr[3] == "p":
            return chk == 0x2BC830A3
        return False
    except Exception:
        return False


def _auszug(zeile: str, treffer: str, breite: int = 80) -> str:
    text = zeile.strip().replace("\t", " ")
    if treffer and treffer in text:
        i = text.index(treffer)
        start = max(0, i - 12)
        ende = min(len(text), i + len(treffer) + 12)
        teil = text[start:ende]
    else:
        teil = text[:breite]
    if len(teil) > breite:
        teil = teil[:breite]
    return teil


def _email_erlaubt(mail: str) -> bool:
    if mail in ERLAUBTE_EMAILS:
        return True
    if "@" not in mail:
        return False
    lokal, _, domain = mail.partition("@")
    if domain in _EMAIL_DOMAIN_AUSNAHME:
        return True
    if domain.endswith(".onion") or domain.endswith(".example"):
        return True
    if lokal in _EMAIL_LOKAL_AUSNAHME:
        return True
    return False


def pruefe_text(text: str, pfad: Path) -> list[Fund]:
    funde: list[Fund] = []
    fixture = _ist_fixture(pfad)
    zeilen = text.splitlines() or [text]

    def add(regel: str, nr: int, roh: str, treffer: str = "") -> None:
        funde.append(Fund(str(pfad), regel, nr, _auszug(roh, treffer or roh)))

    if fixture and pfad.suffix.lower() in {".csv", ".tsv", ".xlsx"}:
        if not herkunft_datei(pfad).is_file():
            add("fixture-ohne-herkunft", 1, pfad.name)

    for nr, zeile in enumerate(zeilen, 1):
        for m in RE_EXT_PRV.finditer(zeile):
            if not _erlaubt(m.group(0)):
                add("erweiterter-privatschluessel", nr, zeile, m.group(0))
        for m in RE_EXT_KEY.finditer(zeile):
            if not _erlaubt(m.group(0)):
                add("erweiterter-schluessel", nr, zeile, m.group(0))
        if RE_DESCRIPTOR_FP.search(zeile):
            for m in RE_EXT_KEY.finditer(zeile):
                if not _erlaubt(m.group(0)):
                    add("deskriptor-fingerprint", nr, zeile, m.group(0))
        if RE_KRAKEN_LEDGER_KOPF.search(zeile) and not fixture:
            add("kraken-ledger-kopf", nr, zeile)
        if RE_KRAKEN_TRADES_KOPF.search(zeile) and not fixture:
            add("kraken-trades-kopf", nr, zeile)
        if RE_COINBASE_KOPF.search(zeile) and not fixture:
            add("coinbase-kopf", nr, zeile)
        if RE_STRIKE_KOPF.search(zeile) and not fixture:
            add("strike-kopf", nr, zeile)
        for m in RE_KRAKEN_LEDGER_ID.finditer(zeile):
            ident = m.group(0)
            if ident.startswith("LSYN"):
                continue
            add("kraken-ledger-id", nr, zeile, ident)
        for m in RE_IBAN.finditer(zeile):
            if _iban_gueltig(m.group(0)):
                add("iban", nr, zeile, m.group(0))
        for m in RE_EMAIL.finditer(zeile):
            mail = m.group(0).lower()
            if _email_erlaubt(mail):
                continue
            add("email", nr, zeile, mail)
        for m in RE_BECH32.finditer(zeile):
            addr = m.group(0)
            if _bech32_ok(addr) and not _erlaubt(addr):
                add("mainnet-adresse", nr, zeile, addr)
        for m in RE_BASE58_ADDR.finditer(zeile):
            addr = m.group(0)
            if _base58_check_ok(addr) and not _erlaubt(addr):
                add("mainnet-adresse", nr, zeile, addr)

    if RE_COINBASE_PRAEAMBEL.search(text) and not fixture:
        nr = 1
        for i, zeile in enumerate(zeilen, 1):
            if re.search(r"^Transactions\b", zeile, re.I):
                nr = i
                break
        funde.append(Fund(str(pfad), "coinbase-praeambel", nr, "Transactions / User,"))

    return funde


def _lese(pfad: Path) -> str | None:
    try:
        roh = pfad.read_bytes()
    except OSError:
        return None
    if b"\x00" in roh[:8192]:
        return None
    if len(roh) > 8_000_000:
        roh = roh[:8_000_000]
    return roh.decode("utf-8", errors="replace")


def pruefe_datei(pfad: Path) -> list[Fund]:
    text = _lese(pfad)
    if text is None:
        return []
    return pruefe_text(text, pfad)


def pruefe_staged(repo: Path | None = None) -> list[Fund]:
    wurzel = repo or REPO_ROOT
    try:
        aus = subprocess.check_output(
            ["git", "diff", "--cached", "-U0", "--no-color"],
            cwd=wurzel,
            text=True,
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"git diff --cached fehlgeschlagen: {exc}") from exc
    funde: list[Fund] = []
    pfad: Path | None = None
    plus: list[str] = []
    neue_dateien: list[Path] = []

    def flush() -> None:
        nonlocal pfad, plus
        if pfad is not None:
            funde.extend(pruefe_text("\n".join(plus), pfad))
        pfad, plus = None, []

    namen = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=wurzel,
        text=True,
        errors="replace",
    ).splitlines()
    for name in namen:
        p = (wurzel / name).resolve()
        if p.suffix.lower() in {".csv", ".tsv", ".xlsx"} and _ist_fixture(p):
            neue_dateien.append(p)

    zeile_nr = 0
    for roh in aus.splitlines():
        if roh.startswith("+++ b/"):
            flush()
            rel = roh[6:]
            pfad = (wurzel / rel).resolve() if rel != "/dev/null" else None
            zeile_nr = 0
            continue
        if roh.startswith("@@"):
            m = re.search(r"\+(\d+)", roh)
            zeile_nr = int(m.group(1)) if m else 0
            continue
        if roh.startswith("+") and not roh.startswith("+++"):
            plus.append(roh[1:])
            zeile_nr += 1
    flush()

    for p in neue_dateien:
        if not herkunft_datei(p).is_file():
            # auch prüfen, ob die Herkunftsdatei gestagt ist (noch nicht auf Disk
            # geschrieben? sie muss im Arbeitsbaum liegen).
            funde.append(Fund(str(p), "fixture-ohne-herkunft", 1, p.name))
    return funde


def pruefe_tracked(repo: Path | None = None) -> list[Fund]:
    wurzel = repo or REPO_ROOT
    aus = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=wurzel,
        text=True,
        errors="replace",
    )
    funde: list[Fund] = []
    for name in aus.split("\0"):
        if not name:
            continue
        pfad = wurzel / name
        if not pfad.is_file():
            continue
        funde.extend(pruefe_datei(pfad))
    return funde


def format_funde(funde: list[Fund]) -> str:
    zeilen = []
    for f in funde:
        zeilen.append(f"{f.pfad}:{f.zeile}: {f.regel}: {f.auszug}")
    return "\n".join(zeilen)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SatSage Leak-Scan")
    parser.add_argument("--staged", action="store_true", help="Gestagten Diff prüfen")
    parser.add_argument("--tracked", action="store_true", help="Alle getrackten Dateien prüfen")
    parser.add_argument("pfade", nargs="*", type=Path)
    args = parser.parse_args(argv)
    funde: list[Fund] = []
    if args.staged:
        funde.extend(pruefe_staged())
    if args.tracked:
        funde.extend(pruefe_tracked())
    for p in args.pfade:
        funde.extend(pruefe_datei(p))
    if not args.staged and not args.tracked and not args.pfade:
        parser.error("Bitte --staged, --tracked oder mindestens einen Pfad angeben.")
    if funde:
        print(format_funde(funde), file=sys.stderr)
        print(f"leak_scan: {len(funde)} Treffer", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
