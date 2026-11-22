#!/usr/bin/env python3
"""Prüft die Börsen-Zuordnung am Regtest-Szenario, vor Stufe 2.

Voraussetzung: Labor läuft, ``boerse_szenario.py`` hat den Bericht und die
CSVs geschrieben. Die Wallets stehen nicht in der Lab-Env.

Strike mit echter TxID muss über ``txid_exakt`` bestätigt werden, Kraken
ohne TxID genau einen Vorschlag liefern. Haltefrist und Lot-Ring bleiben
nach der Bestätigung unverändert (Zuordnung ist in dieser Stufe nur
Erklärung). Nur Regtest. Startet kein Docker.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
HERE = SCRIPTS.parent
REPO = HERE.parents[1]
ENV_PATH = HERE / ".data" / ".regtest.env"
REPORT = HERE / ".data" / "scenario-report-boerse.json"
WORK = HERE / ".data" / "boerse-pruefung"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCRIPTS))

from infra_check import abbrechen, brauche, pinne_lab_env  # noqa: E402
from core.log_redaktion import ref_hash  # noqa: E402


def _load_env(path: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    if not path.is_file():
        return werte
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        werte[k.strip()] = v.strip().strip('"').strip("'")
    return werte


def lade_bericht(pfad: Path = REPORT) -> dict[str, Any]:
    if not pfad.is_file():
        raise RuntimeError(
            f"Szenario-Bericht fehlt: {pfad}. Zuerst boerse_szenario.py."
        )
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    if not isinstance(daten, dict) or not daten.get("buendel") or not daten.get("einzeln"):
        raise RuntimeError("Börsen-Szenario unvollständig im Bericht.")
    if daten.get("network") != "regtest":
        raise RuntimeError("Bericht ist nicht für Regtest.")
    return daten


def eigen_buendel(bericht: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        a for a in (bericht["buendel"].get("ausgaben") or [])
        if a.get("rolle") == "eigen"
    ]


def empfaenge_aus_bericht(bericht: dict[str, Any]):
    from core.boerse.zuordnung import KettenEmpfang

    rows = eigen_buendel(bericht) + [bericht["einzeln"]]
    return [
        KettenEmpfang(
            txid=str(r["txid"]).lower(),
            vout=int(r["vout"]),
            sats=int(r["sats"]),
            zeit_ts=int(r["block_time"]),
            adresse=str(r.get("address") or "") or None,
            eigene_eingaenge=False,
        )
        for r in rows
    ]


def pruefe_zuordnungen(
    *,
    strike,
    kraken,
    bericht: dict[str, Any],
) -> list[str]:
    """Fehlertexte, leer wenn Strike bestätigt und Kraken einen Vorschlag hat."""
    fehler: list[str] = []
    buendel_txid = str(bericht["buendel"]["txid"]).lower()
    eigen = eigen_buendel(bericht)
    soll_outs = {(str(a["txid"]).lower(), int(a["vout"]), int(a["sats"])) for a in eigen}

    best = [z for z in strike.zuordnungen if z.status == "bestaetigt"]
    if len(best) != 2:
        fehler.append(f"Strike: {len(best)} bestätigt, erwartet 2")
    gefunden: set[tuple[str, int, int]] = set()
    for z in best:
        if z.methode != "txid_exakt":
            fehler.append(f"Strike: Methode {z.methode}, erwartet txid_exakt")
        if z.txid != buendel_txid:
            fehler.append("Strike: TxID trifft die Sammel-Tx nicht")
        gefunden.add((z.txid, int(z.vout), int(z.sats_onchain)))
    if best and gefunden != soll_outs:
        fehler.append("Strike: bestätigte Ausgänge treffen die Sammel-Tx nicht")

    vorschlaege = [z for z in kraken.zuordnungen if z.status == "vorschlag"]
    sonst = [z for z in kraken.zuordnungen if z.status != "vorschlag"]
    if len(vorschlaege) != 1:
        fehler.append(f"Kraken: {len(vorschlaege)} Vorschläge, erwartet 1")
    if sonst:
        fehler.append(f"Kraken: {len(sonst)} Zuordnungen ohne Vorschlag-Status")
    if vorschlaege:
        v = vorschlaege[0]
        einzel = bericht["einzeln"]
        if v.txid != str(einzel["txid"]).lower() or int(v.vout) != int(einzel["vout"]):
            fehler.append("Kraken: Vorschlag trifft die Einzelauszahlung nicht")
        if int(v.sats_onchain) != int(einzel["sats"]):
            fehler.append("Kraken: Betrag des Vorschlags passt nicht")
        if v.methode not in {"betrag_zeit", "adresse"}:
            fehler.append(f"Kraken: Methode {v.methode}, erwartet betrag_zeit oder adresse")
    return fehler


def steuer_kern(zeile: dict[str, Any], herkunft: dict[str, Any] | None = None) -> dict[str, Any]:
    """Haltefrist und Lot-Ring, ohne Börsen-Erklärung."""
    kern = {
        "time_ts": zeile.get("time_ts"),
        "erfuellt": zeile.get("erfuellt"),
        "haltedauer_tage": zeile.get("haltedauer_tage"),
        "frist_ende": zeile.get("frist_ende"),
        "grundlage": zeile.get("grundlage"),
        "untergrenze": zeile.get("untergrenze"),
        "buendel_obergrenze": zeile.get("buendel_obergrenze"),
        "sats_gruen": zeile.get("sats_gruen"),
        "sats_orange": zeile.get("sats_orange"),
        "sats_grau": zeile.get("sats_grau"),
        "sats_ohne_datum": zeile.get("sats_ohne_datum"),
    }
    if herkunft is not None:
        kern["unvollstaendig"] = bool(herkunft.get("unvollstaendig"))
    return kern


def _aktiviere(data_dir: Path, werte: dict[str, str]) -> Path:
    from core.paths import aktualisiere_modulkonstanten, setze_data_dir

    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    env_pfad = data_dir / ".env"
    env_pfad.write_text(
        "\n".join(f"{k}={v}" for k, v in werte.items()) + "\n",
        encoding="utf-8",
    )
    setze_data_dir(data_dir)
    pinne_lab_env(env_pfad)
    for key in list(os.environ):
        if key.startswith("WALLET_") or key.startswith("FULCRUM") or key.startswith("UTXO_RPC"):
            if key not in werte:
                os.environ.pop(key, None)
    os.environ.update(werte)
    os.environ["SATSAGE_DATA_DIR"] = str(data_dir)
    os.environ["NETWORK"] = "regtest"
    os.environ["ENV_FILE"] = str(env_pfad)
    import main

    pinne_lab_env(env_pfad)
    main.set_chain_network("regtest")
    aktualisiere_modulkonstanten()
    return env_pfad


def _steuer_stand(bericht: dict[str, Any], data_dir: Path, lab: dict[str, str], ctx, wallets, env: dict[str, str]):
    from verify_quellen_inventar import _scan_core, _steuer_stand as _stand

    cache_dir = data_dir / "utxo_cache"
    imm = data_dir / "immutable_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    imm.mkdir(parents=True, exist_ok=True)
    gefunden, _get_tx, _cores = _scan_core(env, cache_dir, ctx, wallets)
    soll = []
    for row in eigen_buendel(bericht) + [bericht["einzeln"]]:
        key = f"{str(row['txid']).lower()}:{int(row['vout'])}"
        if key not in gefunden:
            raise RuntimeError(
                f"Empfang {ref_hash(str(row['txid']))}:{row['vout']} fehlt im Scan"
            )
        soll.append(gefunden[key])
    zeilen, steuer, _keys, _auswertung = _stand(soll, ctx, imm, env)
    stand: dict[str, dict[str, Any]] = {}
    herkunft = {str(z.get("key") or f"{z.get('txid')}:{z.get('vout')}"): z for z in zeilen}
    for key, zeile in steuer.items():
        stand[key] = steuer_kern(zeile, herkunft.get(key) or herkunft.get(key.lower()))
    return stand


def _vergleich(vorher: dict, nachher: dict) -> list[str]:
    fehler = []
    if set(vorher) != set(nachher):
        fehler.append("Steuerstand: andere Outpoints vor und nach der Bestätigung")
        return fehler
    for key, alt in vorher.items():
        neu = nachher[key]
        if alt != neu:
            fehler.append(
                f"Haltefrist oder Lot-Ring hat sich bei {ref_hash(key.split(':')[0])} geändert"
            )
    return fehler


def pruefe(bericht: dict[str, Any], *, mit_steuer: bool = True) -> list[str]:
    from core import exchange_reports as boerse
    from core.boerse import kraken, speicher, strike, zuordnung
    from core.paths import exchange_dir

    csv_kraken = HERE / str(bericht["csv"]["kraken"])
    csv_strike = HERE / str(bericht["csv"]["strike"])
    if not csv_kraken.is_file() or not csv_strike.is_file():
        return ["Synthetische CSVs fehlen. Zuerst boerse_szenario.py."]

    lab = _load_env(ENV_PATH)
    werte = {
        "NETWORK": "regtest",
        "STEUER_HALTEFRIST_JAHRE": lab.get("STEUER_HALTEFRIST_JAHRE") or "1",
        "OEFFENTLICHE_ELECTRUM": "0",
        "BIP158_P2P": "0",
        "TOR_AUTOSTART": "0",
        "WALLETS_IMMER_AKTUELL": "0",
        "NODE_IP": lab.get("NODE_IP") or "127.0.0.1",
        "RPCPORT": lab.get("RPCPORT") or "18443",
        "RPCUSER": lab.get("RPCUSER") or "bitcoin",
        "RPCPASSWORD": lab.get("RPCPASSWORD") or "secret",
        "RPC_SSL": lab.get("RPC_SSL") or "false",
        "WALLET_0_NAME": "Lab Boerse-Empfang",
        "WALLET_0_XPUB": str(bericht["empfang_xpub"]),
        "WALLET_0_SCRIPT": str(bericht.get("empfang_script") or "segwit"),
        "WALLET_0_MAX_ADDRESSES": "20",
    }
    env_pfad = _aktiviere(WORK, werte)
    wurzel = exchange_dir()
    wurzel.mkdir(parents=True, exist_ok=True)

    boerse.importiere_csv(
        csv_strike.read_text(encoding="utf-8"),
        name="Strike",
        cache_dir=wurzel,
    )
    boerse.importiere_csv(
        csv_kraken.read_text(encoding="utf-8"),
        name="Kraken",
        cache_dir=wurzel,
    )

    empfange = empfaenge_aus_bericht(bericht)
    strike_buch = speicher.lies_buchungen("strike", wurzel)
    kraken_buch = speicher.lies_buchungen("kraken", wurzel)
    lauf_s = zuordnung.schlage_vor(strike_buch, empfange)
    speicher.schreibe_zuordnungen("strike", wurzel, list(lauf_s.zuordnungen))
    lauf_k = zuordnung.schlage_vor(kraken_buch, empfange)
    speicher.schreibe_zuordnungen("kraken", wurzel, list(lauf_k.zuordnungen))

    fehler = pruefe_zuordnungen(strike=lauf_s, kraken=lauf_k, bericht=bericht)
    if fehler or not mit_steuer:
        return fehler

    import main as satsage_main
    from core.config import EnvFile, read_wallets

    pinne_lab_env(env_pfad)
    wallets = read_wallets(EnvFile.load(env_pfad))
    if not wallets:
        return fehler + ["Isolierte Env ohne Wallet."]
    ctx = satsage_main.build_wallet_context(
        [w.xpub for w in wallets],
        wallet_names=[w.name for w in wallets],
        max_addresses_per_xpub=[w.max_addresses for w in wallets],
        script_types=[w.script_type for w in wallets],
    )
    try:
        vorher = _steuer_stand(bericht, WORK, lab, ctx, wallets, werte)
    except Exception as exc:
        return fehler + [f"Steuerstand vor der Bestätigung nicht lesbar: {type(exc).__name__}"]

    vorschlag = next(z for z in lauf_k.zuordnungen if z.status == "vorschlag")
    neu = zuordnung.setze_status(
        list(lauf_k.zuordnungen),
        konto=vorschlag.konto,
        auszahlung_ref=vorschlag.auszahlung_ref,
        status="bestaetigt",
        bestaetigt_ts=int(time.time()),
    )
    speicher.schreibe_zuordnungen("kraken", wurzel, neu)
    zuordnung._erklaerung_cache.clear()
    try:
        nachher = _steuer_stand(bericht, WORK, lab, ctx, wallets, werte)
    except Exception as exc:
        return fehler + [f"Steuerstand nach der Bestätigung nicht lesbar: {type(exc).__name__}"]
    fehler.extend(_vergleich(vorher, nachher))
    return fehler


def main() -> int:
    os.environ.setdefault("NETWORK", "regtest")
    fehlend = brauche("bitcoind")
    if fehlend is not None:
        return fehlend
    if not ENV_PATH.is_file():
        return abbrechen("Lab-Env fehlt. Zuerst generate_scenarios.py und boerse_szenario.py.")
    try:
        bericht = lade_bericht()
        fehler = pruefe(bericht)
    except RuntimeError as exc:
        return abbrechen(str(exc))
    if fehler:
        for zeile in fehler:
            print(zeile, file=sys.stderr)
        return 1
    print(
        "Börsen-Zuordnung: Strike über txid_exakt bestätigt, "
        "Kraken genau ein Vorschlag, Haltefrist und Lot-Ring unverändert.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
