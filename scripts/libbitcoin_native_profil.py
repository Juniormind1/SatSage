#!/usr/bin/env python3
"""Electrum gegen die libbitcoin-Abfrage am eigenen Indexer.

Opt-in. Nicht Teil der Testsuite und nicht des Regtest-Labors. Startet nur,
wer es selbst aufruft. Liest Host und xpub aus der lokalen .env, leitet
Adressen nur lokal ab. Ausgabe: Zeiten, Anfragen, Antwortbytes. Keine
Adressen, keine Txids.

Beispiel:
  .venv/bin/python scripts/libbitcoin_native_profil.py
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_LUECKE = 20
_BESTAND = 5
_TIEFE = 3
_KANTEN = 20
_SCAN = 200


def _rede(text: str) -> str:
    text = re.sub(r"\b[0-9a-fA-F]{64}\b", "<id>", text)
    text = re.sub(r"\b(?:bc1|tb1|bcrt1)[0-9a-z]{10,}\b", "<adresse>", text, flags=re.I)
    return text


def _bool(raw: str, default: bool) -> bool:
    text = str(raw or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "ja", "on"}


def _median(werte: list[float]) -> float:
    geordnet = sorted(werte)
    return geordnet[len(geordnet) // 2]


def _groesse(antwort) -> int:
    if isinstance(antwort, str):
        return len(antwort)
    try:
        return len(json.dumps(antwort, separators=(",", ":")))
    except TypeError:
        return len(str(antwort))


def _kalt() -> None:
    from core import fulcrum_history as historie

    historie._HEADER_TIME_CACHE.clear()
    historie._TX_HEIGHT_CACHE.clear()
    historie._VERBOSE_TX_CACHE.clear()


def _wallet(env: dict[str, str]):
    from core.config import read_wallets

    class _Datei:
        def values(self) -> dict[str, str]:
            return env

    for eintrag in read_wallets(_Datei()):
        schluessel = (eintrag.descriptor or eintrag.xpub or "").strip()
        if schluessel:
            return schluessel, eintrag.script_type or "auto"
    return "", ""


def _adresse(schluessel: str, script_type: str, change: int, index: int) -> str | None:
    from core.derivation import derive_address_at_index, derive_receive_address_at_index

    if change == 0:
        treffer = derive_receive_address_at_index(schluessel, index, script_type)
        return treffer[0] if treffer else None
    return derive_address_at_index(schluessel, change, index)


def _kanten(get_tx, start: str, eigene: set[str]) -> list[tuple]:
    from core.trace import FundingEdge, iter_trace_funding_inputs

    ergebnis: list[tuple] = []
    fronte = [start]
    for _tiefe in range(_TIEFE):
        weiter: list[str] = []
        for txid in fronte:
            for stueck in iter_trace_funding_inputs(get_tx, txid, eigene):
                if not isinstance(stueck, FundingEdge):
                    continue
                ergebnis.append((
                    stueck.prevout.txid,
                    stueck.prevout.vout,
                    int(stueck.amount_sats),
                    stueck.prev_time_ts,
                ))
                weiter.append(stueck.prevout.txid)
                if len(ergebnis) >= _KANTEN:
                    return ergebnis
        fronte = weiter
        if not fronte:
            break
    return ergebnis


def _verbinde(env: dict[str, str]):
    from core.fulcrum_client import connect_fulcrum

    host = str(env.get("FULCRUM_HOST") or "").strip()
    onion = str(env.get("FULCRUM_TOR") or "").strip()
    try:
        port = int(str(env.get("FULCRUM_PORT") or "50002").strip())
    except ValueError:
        port = 50002
    ssl = _bool(env.get("FULCRUM_SSL", ""), True)
    proxy = None
    ziel = host
    if not ziel:
        ziel = onion
        roh = str(env.get("FULCRUM_TOR_PROXY") or env.get("TOR_PROXY") or "").strip()
        if not ziel:
            print("In der .env steht kein eigener Indexer (FULCRUM_HOST oder FULCRUM_TOR).")
            return None
        if ":" not in roh:
            print("Für den Onion-Indexer fehlt FULCRUM_TOR_PROXY.")
            return None
        name, nummer = roh.rsplit(":", 1)
        if not nummer.isdigit():
            print("FULCRUM_TOR_PROXY hat keinen Port.")
            return None
        proxy = (name, int(nummer))
    client, fehler = connect_fulcrum(
        ziel,
        port,
        use_ssl=ssl,
        tor_proxy=proxy,
    )
    if client is None:
        print("Der eigene Indexer ist über Electrum nicht erreichbar.")
        if fehler:
            print(_rede(fehler))
        return None
    return client


def _grund(text: str) -> str:
    if text == "index":
        return "Die Abfrage-Schnittstelle hat keinen Adressindex. Kein Vergleich."
    if text == "hash":
        return "Die native UTXO-Liste trifft listunspent nicht. Kein Vergleich."
    if text == "antwort":
        return "Die native Antwort hat eine unbekannte Form. Kein Vergleich."
    if text == "software":
        return "Der eigene Indexer meldet sich nicht als libbitcoin. Kein Vergleich."
    return "Die Abfrage-Schnittstelle antwortet nicht. Kein Vergleich."


class _Zaehler:
    def __init__(self, original) -> None:
        self.original = original
        self.n = 0
        self.bytes = 0

    def __call__(self, method, params=None):
        antwort = self.original(method, params)
        self.n += 1
        self.bytes += _groesse(antwort)
        return antwort

    def reset(self) -> None:
        self.n = 0
        self.bytes = 0


def _messe(sitzung, zaehler: _Zaehler, nativ: bool, lauf):
    zeiten: list[float] = []
    anfragen: list[int] = []
    groessen: list[int] = []
    ergebnis = None
    for runde in range(4):
        _kalt()
        sitzung.anfragen = 0
        sitzung.antwort_bytes = 0
        zaehler.reset()
        sitzung.unterdrueckt = not nativ
        start = time.perf_counter()
        ergebnis = lauf()
        dauer = time.perf_counter() - start
        if nativ and zaehler.n:
            raise RuntimeError("zurueckgefallen")
        if not nativ and sitzung.anfragen:
            raise RuntimeError("electrum-hat-nativ")
        if runde == 0:
            continue
        zeiten.append(dauer)
        if nativ:
            anfragen.append(sitzung.anfragen)
            groessen.append(sitzung.antwort_bytes)
        else:
            anfragen.append(zaehler.n)
            groessen.append(zaehler.bytes)
    return ergebnis, _median(zeiten), _median(anfragen), _median(groessen)


def _zeile(name: str, sekunden: float, anfragen: float, groesse: float) -> None:
    print(
        f"  {name:<10} {sekunden:.3f} s"
        f"   Anfragen {int(anfragen)}   Bytes {int(groesse)}"
    )


def _paar(titel: str, electrum, nativ) -> bool:
    print(titel)
    _zeile("Electrum", electrum[1], electrum[2], electrum[3])
    _zeile("nativ", nativ[1], nativ[2], nativ[3])
    links = set(electrum[0])
    rechts = set(nativ[0])
    if links != rechts:
        print(f"  nur Electrum {len(links - rechts)}, nur nativ {len(rechts - links)}")
        return False
    print("  gleich")
    return True


def main() -> int:
    from core.env_bootstrap import _load_dotenv
    from core.fulcrum_wallet import (
        address_has_received_fulcrum,
        fetch_address_utxos_fulcrum,
    )
    from core.libbitcoin_native import sitzung_fuer
    from core.sanctions_pool import make_cached_fulcrum_get_tx

    env = _load_dotenv()
    schluessel, script_type = _wallet(env)
    if not schluessel:
        print("Kein Wallet in der .env.")
        return 2
    client = _verbinde(env)
    if client is None:
        return 2
    try:
        if str(getattr(client, "server_software", "") or "") != "libbitcoin":
            print("Der eigene Indexer meldet sich nicht als libbitcoin. Kein Vergleich.")
            return 2
        sitzung = sitzung_fuer(client)
        if not sitzung.aktiv:
            print(_grund(sitzung.grund))
            return 2
        sitzung.hydrate_aus_cache = False
        sitzung.unterdrueckt = True

        benutzt: list[tuple[int, str]] = []
        hoechster = -1
        for index in range(_SCAN):
            adresse = _adresse(schluessel, script_type, 0, index)
            if not adresse:
                print("Adressen lassen sich aus dem Wallet nicht ableiten.")
                return 2
            if address_has_received_fulcrum(client, adresse):
                benutzt.append((index, adresse))
                hoechster = index
        if not benutzt:
            print("Keine benutzte Adresse in den ersten Indizes. Kein Vergleich.")
            return 2
        luecke = []
        for index in range(hoechster + 1, hoechster + 1 + _LUECKE):
            adresse = _adresse(schluessel, script_type, 0, index)
            if not adresse:
                print("Adressen lassen sich aus dem Wallet nicht ableiten.")
                return 2
            luecke.append((index, adresse))

        start_txid = ""
        for _index, adresse in benutzt:
            for utxo in fetch_address_utxos_fulcrum(client, adresse):
                if not start_txid:
                    start_txid = str(utxo.get("txid") or "")
            if sitzung.hash_bestaetigt:
                break
        if not sitzung.hash_bestaetigt or not sitzung.aktiv:
            print(_grund(sitzung.grund or "hash"))
            return 2

        eigene: set[str] = set()
        for index in range(0, hoechster + 1 + _LUECKE):
            for change in (0, 1):
                adresse = _adresse(schluessel, script_type, change, index)
                if adresse:
                    eigene.add(adresse)

        original = client.request
        zaehler = _Zaehler(original)
        client.request = zaehler

        def luecke_lauf():
            treffer = set()
            for index, adresse in luecke:
                if address_has_received_fulcrum(client, adresse):
                    treffer.add(index)
            return treffer

        def bestand_lauf():
            menge = set()
            for _index, adresse in benutzt[:_BESTAND]:
                for utxo in fetch_address_utxos_fulcrum(client, adresse):
                    status = utxo.get("status") if isinstance(utxo.get("status"), dict) else {}
                    menge.add((
                        str(utxo.get("txid") or "").lower(),
                        int(utxo.get("vout") or 0),
                        int(utxo.get("value") or 0),
                        status.get("block_height"),
                    ))
            return menge

        def herkunft_lauf():
            wurzel = ROOT / "tmp" / "libbitcoin-profil"
            wurzel.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="lauf-", dir=wurzel) as tmp:
                get_tx = make_cached_fulcrum_get_tx(client, Path(tmp))
                return _kanten(get_tx, start_txid, eigene)

        try:
            paare = [(
                f"Lücke, {_LUECKE} folgende Adressen",
                _messe(sitzung, zaehler, False, luecke_lauf),
                _messe(sitzung, zaehler, True, luecke_lauf),
            ), (
                f"Bestand, bis zu {_BESTAND} benutzte Adressen",
                _messe(sitzung, zaehler, False, bestand_lauf),
                _messe(sitzung, zaehler, True, bestand_lauf),
            )]
            if start_txid:
                paare.append((
                    f"Herkunft, 1 UTXO, Tiefe {_TIEFE}, höchstens {_KANTEN} Kanten",
                    _messe(sitzung, zaehler, False, herkunft_lauf),
                    _messe(sitzung, zaehler, True, herkunft_lauf),
                ))
        except RuntimeError as exc:
            if str(exc) == "zurueckgefallen":
                print("Nativ ist auf Electrum zurückgefallen. Kein Vergleich.")
            else:
                print("Der Electrum-Lauf hat die Abfrage-Schnittstelle benutzt. Kein Vergleich.")
            return 2
        except Exception as exc:
            print("Der Vergleich ist fehlgeschlagen.")
            print(_rede(f"{type(exc).__name__}: {exc}"))
            return 1

        gleich = True
        for titel, electrum, nativ in paare:
            if not _paar(titel, electrum, nativ):
                gleich = False
        if not start_txid:
            print("Herkunft: kein UTXO in den geprüften Adressen.")
        return 0 if gleich else 1
    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
