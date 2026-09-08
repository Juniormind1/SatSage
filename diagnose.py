#!/usr/bin/env python3
"""
Diagnose der konfigurierten Wallets.

Beantwortet die Frage „warum zeigen zwei Wallets dasselbe an?" bzw. „warum
findet ein Wallet nichts?", ohne dass dafür Schlüssel weitergegeben werden
müssen: Die Ausgabe enthält **keine vollständigen XPUBs**, nur gekürzte
Fassungen, abgeleitete Adressen und Prüfsummen. Sie lässt sich bedenkenlos
kopieren und weitergeben.

Aufruf:

    python3 diagnose.py            # Windows: py diagnose.py
    python3 diagnose.py --env pfad/zur/.env
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import main
from core.config import (
    EnvFile,
    bloecke_nach_luecke,
    erste_empfangsadresse,
    read_wallets,
    schluessel_kennung,
)
from core.utxos import load_cached_utxos
from core.wallets import SCRIPT_TYPE_LABELS, effective_script_type, wallet_id


def _konsole_auf_utf8() -> None:
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _kurz(kennung: str | None) -> str:
    """Gekürzte Prüfsumme des Schlüsselmaterials — nie der Schlüssel selbst."""
    return kennung[:12] if kennung else "—"


def diagnose(env_pfad: Path, cache_dir: Path) -> int:
    env = EnvFile.load(env_pfad)
    wallets = read_wallets(env)

    print("SatSage — Wallet-Diagnose")
    print(f"  Konfiguration : {env_pfad}")
    print(f"  UTXO-Cache    : {cache_dir}")
    print(f"  Wallets       : {len(wallets)}")

    # Die Liste endet an der ersten fehlenden Nummer. Blöcke dahinter wären
    # sonst spurlos weg — mitsamt dem Wallet, das sie beschreiben.
    uebersprungen = bloecke_nach_luecke(env.values())
    if uebersprungen:
        nummern = ", ".join(f"WALLET_{n}_…" for n in uebersprungen)
        print(f"  Übersprungen  : {nummern}")
        print("                  Die Nummerierung muss bei 0 beginnen und darf")
        print("                  keine Lücke haben.")
    print()

    if not wallets:
        print("Keine Wallets konfiguriert. WALLET_0_XPUB in der .env setzen")
        print("oder die Web-Oberfläche unter Einstellungen benutzen.")
        return 1

    kennungen: dict[str, list[str]] = {}
    adressen: dict[str, list[str]] = {}

    for nummer, eintrag in enumerate(wallets, start=1):
        typ = eintrag.script_type
        wirksam = effective_script_type(eintrag)

        if eintrag.is_multisig:
            # Keine Empfangsadresse: Sie ergäbe sich aus allen Cosignern
            # zusammen. Die eines einzelnen zu zeigen wäre falsch — wer darauf
            # einzahlt, zahlt an einen Mitunterzeichner allein.
            print(f"[{nummer}] {eintrag.display_name}")
            art = (
                f"Multisig {eintrag.threshold} von {eintrag.cosigner_count}"
                if eintrag.threshold
                else f"Policy mit {eintrag.cosigner_count} Schlüsseln"
            )
            print(f"     Art             {art}")
            print(f"     Skripttyp       {SCRIPT_TYPE_LABELS.get(typ, typ)}")
            for cosigner in eintrag.masked_xpubs():
                print(f"     Cosigner        {cosigner}")
            print(f"     Cache-Datei     {eintrag.wallet_id()}.json")
            print()
            continue

        kennung = schluessel_kennung(eintrag.xpub)
        erste = erste_empfangsadresse(eintrag)
        gecacht = load_cached_utxos(eintrag.xpub, cache_dir)

        print(f"[{nummer}] {eintrag.display_name}")
        print(f"     XPUB            {eintrag.masked_xpub()}  (Prefix {eintrag.prefix})")
        print(f"     Schlüssel-Prüfsumme  {_kurz(kennung)}")
        print(f"     Skripttyp       {SCRIPT_TYPE_LABELS.get(typ, typ)}"
              + (f"  → wirksam: {wirksam}" if typ == "auto" else ""))
        print(f"     Erste Adresse   {erste or '— (nicht ableitbar)'}")
        print(f"     Scan-Tiefe      {eintrag.max_addresses} Adressen (beide Ketten)")
        print(f"     Cache-Datei     {wallet_id(eintrag.xpub)}.json")

        if gecacht is None:
            print("     UTXOs           kein Cache — noch nie gescannt")
        else:
            summe = sum(int(u.get("value", 0)) for u in gecacht)
            # Tausendertrennung nur auf die Zahl anwenden, nicht auf die Zeile.
            betrag = f"{summe:,}".replace(",", ".")
            print(f"     UTXOs           {len(gecacht)} Stück, {betrag} sats")
        print()

        if kennung:
            kennungen.setdefault(kennung, []).append(eintrag.display_name)
        if erste:
            adressen.setdefault(erste, []).append(eintrag.display_name)

    print("-" * 68)
    doppelt = {k: v for k, v in kennungen.items() if len(v) > 1}
    gleiche_adresse = {a: v for a, v in adressen.items() if len(v) > 1}

    if doppelt:
        print()
        print("BEFUND: gleiches Schlüsselmaterial")
        for namen in doppelt.values():
            print(f"  {' und '.join(namen)} enthalten denselben Schlüssel.")
        print()
        print("  Das sind nicht zwei Konten, sondern ein Konto in zwei")
        print("  Fassungen — üblicherweise derselbe Schlüssel einmal als zpub")
        print("  und einmal als xpub. Beide leiten dieselben Adressen ab, daher")
        print("  zeigen sie dieselben Transaktionen.")
        print()
        print("  Verschiedene Konten aus einem Seed (m/84'/0'/0', m/84'/0'/1' …)")
        print("  haben unterschiedliche Prüfsummen und wären hier nicht")
        print("  aufgeführt. Prüfe in deiner Wallet-Software, ob du wirklich")
        print("  zwei verschiedene Konten exportiert hast — die erste Adresse")
        print("  oben muss sich zwischen den Konten unterscheiden.")
    elif gleiche_adresse:
        print()
        print("BEFUND: verschiedene Schlüssel, aber gleiche erste Adresse")
        for adresse, namen in gleiche_adresse.items():
            print(f"  {' und '.join(namen)} beginnen beide bei {adresse}")
        print()
        print("  Das ist unerwartet und sollte gemeldet werden.")
    else:
        print()
        print("BEFUND: alle Wallets sind eigenständig.")
        print("  Unterschiedliche Schlüssel, unterschiedliche erste Adressen.")
        print("  Zeigen sie dennoch dieselben Transaktionen, liegt ein Fehler")
        print("  vor — bitte diese Ausgabe melden.")

    print()
    print("Diese Ausgabe enthält keine vollständigen Schlüssel und kann")
    print("weitergegeben werden.")
    return 0


def main_cli(argv=None) -> int:
    _konsole_auf_utf8()
    parser = argparse.ArgumentParser(
        description="Prüft die konfigurierten Wallets auf Überschneidungen"
    )
    parser.add_argument("--env", default=None, help="Pfad zur .env")
    parser.add_argument("--cache-dir", default=None, help="UTXO-Cache-Verzeichnis")
    args = parser.parse_args(argv)

    return diagnose(
        Path(args.env or main.ENV_FILE),
        Path(args.cache_dir or main.UTXO_CACHE_DIR),
    )


if __name__ == "__main__":
    raise SystemExit(main_cli())
