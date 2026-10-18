#!/usr/bin/env python3
"""Bestand am Stichtag gegen die Kette (REGTEST, nur lesend).

Die Steuerjahr-Auswertung zählt am 31.12. nur Outputs, die dann schon
existierten und noch nicht ausgegeben waren. Die Soll-Werte kommen hier
unabhängig von SatSage aus Core (``getblock`` Stufe 3 mit Prevouts): jeder
eigene Output mit Entstehungs- und Ausgabezeit, dazu die Spanne der
Anschaffung — wann das Wallet die Sats von außen empfing (Blockzeit der
Tx mit dem fremden Eingang bzw. der Coinbase). Interne Hops erben sie.

``verify_quellen_inventar.py`` ruft :func:`pruefe_stichtage` nach dem
Electrs-Klären auf, wenn jedes UTXO eine Herkunft hat. Ohne Ingress gälte
die Anschaffung = Entstehung, und eine Doppelzählung (Output aus dem
Folgejahr mit alter Herkunft) bliebe unsichtbar.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def chain_wahrheit(
    rpc_json: Callable[..., Any], eigene: set[str],
) -> dict[str, dict]:
    """
    Alle eigenen Outputs der Kette: ``txid:vout`` → Zeiten und Herkunft.

    *rpc_json* ruft Core und liefert JSON (``rpc_json("getblock", h, "3")``).
    ``juengste``/``aelteste``: jüngster und ältester Empfang von außen in der
    Herkunft dieses Outputs (Unix).
    """
    hoehe = int(rpc_json("getblockcount"))
    ausgaben: dict[str, dict] = {}
    ausgegeben: dict[str, tuple[str, int]] = {}
    jung: dict[str, int] = {}
    alt: dict[str, int] = {}
    for h in range(hoehe + 1):
        block_hash = rpc_json("getblockhash", str(h))
        block = rpc_json("getblock", block_hash, "3")
        zeit = int(block["time"])
        for tx in block["tx"]:
            eigene_prev: list[str] = []
            von_aussen = False
            for vin in tx["vin"]:
                if "coinbase" in vin:
                    von_aussen = True
                    continue
                key = f'{vin["txid"]}:{vin["vout"]}'
                adresse = (vin.get("prevout") or {}).get("scriptPubKey", {}).get("address")
                if adresse in eigene:
                    eigene_prev.append(key)
                    ausgegeben[key] = (tx["txid"], zeit)
                else:
                    von_aussen = True
            junge = [jung[p] for p in eigene_prev if p in jung]
            alte = [alt[p] for p in eigene_prev if p in alt]
            if von_aussen:
                junge.append(zeit)
                alte.append(zeit)
            for out in tx["vout"]:
                adresse = out.get("scriptPubKey", {}).get("address")
                if adresse not in eigene:
                    continue
                key = f'{tx["txid"]}:{out["n"]}'
                ausgaben[key] = {
                    "txid": tx["txid"],
                    "vout": int(out["n"]),
                    "address": adresse,
                    "value": int(round(float(out["value"]) * 1e8)),
                    "time": zeit,
                    "height": h,
                }
                if junge:
                    jung[key] = max(junge)
                    alt[key] = min(alte)
    for key, aus in ausgaben.items():
        spender = ausgegeben.get(key)
        aus["spent_txid"] = spender[0] if spender else None
        aus["spent_time"] = spender[1] if spender else None
        aus["juengste"] = jung.get(key)
        aus["aelteste"] = alt.get(key)
    return ausgaben


def als_verlauf(wahrheit: dict[str, dict]) -> list[dict]:
    """Die Kette als Verlaufs-Einträge (Form wie ``*_verlauf.json``)."""
    zeilen = []
    for aus in wahrheit.values():
        zeile = {
            "txid": aus["txid"],
            "vout": aus["vout"],
            "address": aus["address"],
            "value": aus["value"],
            "status": {
                "confirmed": True,
                "block_height": aus["height"],
                "block_time": aus["time"],
            },
            "spent": bool(aus["spent_txid"]),
        }
        if aus["spent_txid"]:
            zeile["spent_txid"] = aus["spent_txid"]
            zeile["spent_time_ts"] = aus["spent_time"]
        zeilen.append(zeile)
    return zeilen


def rpc_json(rpc) -> Callable[..., Any]:
    """``Rpc.call`` mit JSON, wo Core JSON liefert (Hash bleibt Text)."""
    def aufruf(*args: str) -> Any:
        roh = rpc.call(*[str(a) for a in args])
        try:
            return json.loads(roh)
        except ValueError:
            return roh
    return aufruf


def stichtag_ts(jahr: int) -> int:
    return int(datetime(jahr, 12, 31, 23, 59, 59).timestamp())


def bestand_soll(wahrheit: dict[str, dict], jahr: int) -> dict[str, dict]:
    """Was am 31.12. *jahr* auf eigenen Adressen lag."""
    ende = stichtag_ts(jahr)
    return {
        key: aus for key, aus in wahrheit.items()
        if aus["time"] <= ende
        and not (aus["spent_time"] and aus["spent_time"] <= ende)
    }


def abgeschlossene_jahre(wahrheit: dict[str, dict], jetzt: datetime | None = None) -> list[int]:
    jetzt = jetzt or datetime.now()
    jahre = {datetime.fromtimestamp(a["time"]).year for a in wahrheit.values()}
    return sorted(j for j in jahre if j < jetzt.year)


def pruefe_stichtage(
    wahrheit: dict[str, dict],
    *,
    imm: Path,
    ctx=None,
    env: dict[str, str] | None = None,
    jahre: list[int] | None = None,
) -> tuple[list[str], list[dict]]:
    """
    Wertet jedes abgeschlossene Jahr aus dem Ketten-Verlauf aus.

    Liefert *(fehler, zeilen)*; *zeilen* je Jahr Soll/Ist für den Bericht.
    """
    from core.tax import auswerten, lese_steuer_einstellungen, parse_stichtag

    einstellung = lese_steuer_einstellungen(env or {})
    verlauf = als_verlauf(wahrheit)
    fehler: list[str] = []
    zeilen: list[dict] = []
    for jahr in jahre if jahre is not None else abgeschlossene_jahre(wahrheit):
        soll = bestand_soll(wahrheit, jahr)
        ist = auswerten(
            verlauf, jahr,
            haltefrist_jahre=einstellung["haltefrist_jahre"],
            stichtag=parse_stichtag(einstellung["stichtag"]),
            anschaffung=einstellung["anschaffung"],
            wallet=ctx,
            immutable_cache_dir=imm,
            mit_lots=False,
        )
        k = ist["kennzahlen"]
        ist_keys = {f'{e["txid"]}:{e["vout"]}' for e in ist["eintraege"]}
        soll_sats = sum(a["value"] for a in soll.values())
        zeile = {
            "jahr": jahr,
            "soll_count": len(soll),
            "soll_sats": soll_sats,
            "ist_count": int(k["gesamt_count"]),
            "ist_sats": int(k["gesamt_sats"]),
        }
        zeilen.append(zeile)
        if zeile["ist_count"] != len(soll) or zeile["ist_sats"] != soll_sats:
            zuviel = sorted(ist_keys - set(soll))
            fehlt = sorted(set(soll) - ist_keys)
            fehler.append(
                f"Bestand 31.12.{jahr}: SatSage {zeile['ist_count']} Outputs / "
                f"{zeile['ist_sats']} sats, Kette {len(soll)} / {soll_sats} sats "
                f"(zu viel {len(zuviel)} {zuviel[:3]}, fehlt {len(fehlt)} {fehlt[:3]})"
            )
    return fehler, zeilen


def main() -> int:
    """Kommandozeile: Kette gegen einen SatSage-Cache (``--imm``)."""
    import argparse
    import sys

    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    sys.path.insert(0, str(here.parents[2]))
    from generate_scenarios import Rpc, choose_native

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imm", type=Path, required=True)
    parser.add_argument("--adressen", type=Path, required=True,
                        help="JSON-Liste der eigenen Adressen")
    args = parser.parse_args()
    rpc = Rpc(choose_native(False))
    eigene = set(json.loads(args.adressen.read_text(encoding="utf-8")))
    wahrheit = chain_wahrheit(rpc_json(rpc), eigene)
    fehler, zeilen = pruefe_stichtage(wahrheit, imm=args.imm)
    for z in zeilen:
        print(json.dumps(z), flush=True)
    for f in fehler:
        print("FAIL", f, flush=True)
    return 1 if fehler else 0


if __name__ == "__main__":
    raise SystemExit(main())
