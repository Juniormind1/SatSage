"""
Coin-Auswahl fürs FIFO-Spend (PSBT-Vorschau): kleinstes Wechselgeld.

Regel (Entscheidung Maintainer 2026-10-04, ISSUES „Wallet · FIFO-Spend (PSBT)“):

**Kandidaten.** Nie: Mempool-Ausgaben (``pending``), Neuvermögen, UTXOs ohne
ausgewertete Herkunft (``sats_gruen`` fehlt), UTXOs ohne grünen Anteil
(rein gelb) und UTXOs mit irgendeinem grauen Anteil (``sats_grau`` > 0) —
in beiden Modi (Entscheidung Maintainer 2026-10-04, wie Testkit
``psbt_report.py --policy``). Ausnahme *eigenes Ziel* (``eigenes_ziel``):
das Ziel ist ein hinterlegtes eigenes Wallet. Dann zählt der bestätigte
Gesamtsaldo; Gelb, Grau, Neuvermögen und UTXOs ohne Herkunft sind Inputs,
Beitrag = ganzer Betrag. Mempool-Ausgaben bleiben draußen.

- *defensiv*: nur ganz grüne UTXOs (kein gelber, kein grauer Anteil); Beitrag
  = ganzer Betrag.
- *offensiv* (Korrektur Maintainer 2026-10-04, Testkit ``--policy
  offensive``): zusätzlich grün/gelb gemischte UTXOs. Sie gehen ganz als
  Input ein, zu Betrag und Gebühr zählt nur ihr grüner Anteil; der ganze
  gelbe Teil geht im Wechselgeld an eine eigene Wechseladresse desselben
  Wallets zurück (Wechselgeld ≥ Summe der nicht grünen Anteile,
  ``wechselgeld_nicht_gruen_sats``).
  Eine Lösung mit gemischtem Input hat deshalb immer einen Wechselgeld-Output.

Inputs, deren Beitrag die eigene Input-Gebühr (68 vB × Rate) nicht deckt,
bleiben draußen (unwirtschaftlich).

**Deckung.** Grüne Beiträge ≥ Betrag + Gebühr — die Gebühr kommt aus grünen
sats. Gebühr = Rate × vsize, vsize = ``ceil(10,5 + 68·Inputs + 31·Outputs)``.
Rate je Lösung nach ``core/fee_vorschlag``: Schätzung + Puffer; läge die
Gebühr über 0,1 % des Betrags, 1 sat/vB; ohne Schätzung 1 sat/vB.

**Staub.** Wäre das Wechselgeld kleiner als 546 sats, entfällt der
Wechselgeld-Output und der Rest geht in die Gebühr — aber nur, wenn die
Gesamtgebühr dann höchstens 0,1 % des Betrags ist (oder nicht über der
Mindestgebühr ohne Staub liegt). Sonst bleibt das (kleine) Wechselgeld
stehen (``staub_wechselgeld``) — mindestens ``STAUB_HART_SATS`` (330),
darunter wäre der Output nicht standardkonform. Geht auch das nicht, ist die
Kombination keine Lösung (die Suche nimmt eine andere).

**Ziel.** Die gültige Kombination mit dem kleinsten Wechselgeld (ohne
Wechselgeld-Output = 0). Gleichstand: weniger Inputs, dann ältere zuerst
(aufsteigend sortierte Anschaffungszeiten ``time_ts`` der Steuerauswertung, lexikografisch), dann ``txid:vout``.

**Suche.** Exaktes Branch-and-Bound wie in Bitcoin Core: Kandidaten nach
Beitrag absteigend, Tiefensuche „mit/ohne“. Eine Kombination, die schon
deckt, wird bewertet und nicht weiter vergrößert (mehr Inputs machen das
Wechselgeld nie kleiner, weil jeder Input mehr beiträgt, als er kostet).
Äste, die mit allen übrigen Kandidaten nicht decken können, entfallen.
Budget: ``BUDGET_KNOTEN`` Knoten. Ist es erschöpft, kommt zusätzlich die
Gier-Lösung ins Rennen (größte Beiträge zuerst, bis gedeckt; danach
überflüssige Inputs vom kleinsten her entfernen) und die bessere der beiden
gewinnt (``budget_erschoepft``).

**Strategien** (``strategie``, Dropdown; Zulässigkeit überall gleich):

- ``wechselgeld`` (Standard): wie oben, kleinstes Wechselgeld.
- ``gebuehr``: größte grüne Beiträge zuerst, bis gedeckt — wenigste Inputs,
  also kleinste vsize und Gebühr. Gleichstand: älter, dann ``txid:vout``.
- ``aelteste``: FIFO — älteste Anschaffung (``time_ts`` nach der Lesart
  der Steuer-Einstellung) zuerst, ohne Zeit zuletzt, dann
  ``txid:vout``, bis gedeckt; nichts wird wieder entfernt.
- ``staub``: Auswahl wie ``wechselgeld``, dazu alle zulässigen UTXOs unter
  ``STAUB_AUFRAEUMEN_SATS`` (0,001 BTC), kleinste zuerst, solange die
  Gesamtgebühr höchstens 0,1 % des Betrags ist und die Rate nicht auf
  1 sat/vB fällt; sie gehen ins Wechselgeld (``aufraeumen_*``).

**Feste Rate (PSBT, ``FesteRate``).** Für die echte PSBT gilt die Rate aus
dem Gebührenfeld (milli-sat/vB, bis 3 Nachkommastellen): Gebühr =
``ceil(milli · vsize / 1000)``. Der 0,1-%-Deckel senkt diese Rate nie — er
bleibt nur die Grenze dafür, ob Staub in die Gebühr gehen darf.
``Groessen`` setzt die vbytes je Input und je Output (Skripttyp des Wallets,
Ziel- und Wechseladresse); ohne Angabe gilt die Schätzformel oben.

Deterministisch, ohne Zufall. Kein Schlüsselmaterial.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import math

from core.fee_vorschlag import MIN_SAT_VB, VBYTES_INPUT

#: Unter dieser Grenze ist Wechselgeld Staub (P2PKH-Staubgrenze, konservativ).
STAUB_SATS = 546

#: Darunter wäre ein Wechselgeld-Output nicht standardkonform (Relay-Staub
#: bei 3 sat/vB ``dustrelayfee``: P2WPKH 294, P2TR 330 — der größere Wert).
STAUB_HART_SATS = 330

#: Knoten-Budget der Branch-and-Bound-Suche (wie Core: 100 000 Versuche).
BUDGET_KNOTEN = 100_000

#: Auswahl-Strategien (Dropdown in der Ziel-Zeile, ``FIFO_STRATEGIE``).
STRATEGIEN = ("wechselgeld", "gebuehr", "aelteste", "staub")
STANDARD_STRATEGIE = "wechselgeld"

#: „Staub aufräumen“: zusätzlich eingesammelt werden zulässige UTXOs unter
#: diesem Betrag (0,001 BTC), solange die Gebühr im 0,1-%-Deckel bleibt.
STAUB_AUFRAEUMEN_SATS = 100_000

#: Ohne Anschaffungszeit zählt ein UTXO als jüngstes.
_ZEIT_UNBEKANNT = 1 << 62


@dataclass(frozen=True)
class Kandidat:
    key: str
    txid: str
    vout: int
    wert: int
    beitrag: int
    zeit: int


def _int(wert: Any) -> int:
    try:
        return max(0, int(wert or 0))
    except (TypeError, ValueError):
        return 0


def kandidaten(
    utxos: Iterable[dict],
    *,
    modus: str,
    pending: Iterable[str] = (),
    eigenes_ziel: bool = False,
) -> list[Kandidat]:
    """Zulässige Inputs samt grünem Beitrag (siehe Modul-Doku)."""
    unterwegs = {str(k or "").strip().lower() for k in pending if k}
    aus: list[Kandidat] = []
    gesehen: set[str] = set()
    for u in utxos or []:
        if not isinstance(u, dict):
            continue
        txid = str(u.get("txid") or "").strip().lower()
        key = str(u.get("key") or "").strip().lower()
        if not key and txid:
            key = f"{txid}:{_int(u.get('vout'))}"
        if not key or ":" not in key or key in gesehen:
            continue
        if not txid:
            txid = key.split(":", 1)[0]
        vout = _int(u.get("vout")) if u.get("vout") is not None else _int(key.rsplit(":", 1)[1])
        if key in unterwegs or u.get("pending") or u.get("spending_pending"):
            continue
        wert = _int(u.get("value_sats"))
        if wert <= 0:
            continue
        if eigenes_ziel:
            # Eigenübertrag: ganzer bestätigter Bestand, Farbe egal.
            beitrag = wert
        else:
            if u.get("neuvermoegen") or u.get("sats_gruen") is None:
                continue
            gruen = min(wert, _int(u.get("sats_gruen")))
            if gruen <= 0 or _int(u.get("sats_grau")) > 0:
                continue  # rein gelb oder mit grauem Anteil: nie Input (beide Modi)
            if modus == "offensiv":
                beitrag = gruen
            else:
                # „Ganz grün“ wie die Kopfzeile: kein gelber, kein grauer Anteil.
                # ``sats_gruen`` kann durch BTC-Rundung 1 sat unter dem Wert liegen.
                if _int(u.get("sats_orange")) > 0:
                    continue
                beitrag = wert
        zeit = _int(u.get("time_ts")) or _ZEIT_UNBEKANNT
        gesehen.add(key)
        aus.append(Kandidat(key=key, txid=txid, vout=vout, wert=wert, beitrag=beitrag, zeit=zeit))
    return aus


@dataclass(frozen=True)
class FesteRate:
    """Vom Nutzer gesetzte Rate in milli-sat/vB (1000 = 1 sat/vB)."""

    milli: int

    def gebuehr(self, vsize: int) -> int:
        return -(-self.milli * vsize // 1000)

    @property
    def sat_vb(self) -> float | int:
        return self.milli // 1000 if self.milli % 1000 == 0 else self.milli / 1000


@dataclass(frozen=True)
class Groessen:
    """vbytes je Input/Output; Vorgabe = ``fee_vorschlag.vsize_schaetzung``."""

    input_vb: float = VBYTES_INPUT
    ziel_vb: int = 31
    wechsel_vb: int = 31
    basis_vb: float = 10.5

    def vsize(self, inputs: int, outputs: int) -> int:
        roh = self.basis_vb + self.input_vb * inputs + self.ziel_vb
        if outputs >= 2:
            roh += self.wechsel_vb
        return int(math.ceil(roh))


@dataclass(frozen=True)
class _Kosten:
    """Rate-Regel (Schätzung mit Deckel oder feste Rate) plus Größen."""

    basis: Any
    groessen: Groessen

    def gebuehr(self, vsize: int, betrag: int) -> tuple[int, float | int, bool]:
        """(Gebühr, sat/vB, Deckel griff) für diese vsize."""
        if isinstance(self.basis, FesteRate):
            return self.basis.gebuehr(vsize), self.basis.sat_vb, False
        r, deckel = _rate(self.basis, vsize, betrag)
        return r * vsize, r, deckel

    def input_kosten(self) -> int:
        """Gebühr eines zusätzlichen Inputs (Wirtschaftlichkeits-Grenze)."""
        vb = int(math.ceil(self.groessen.input_vb))
        if isinstance(self.basis, FesteRate):
            return self.basis.gebuehr(vb)
        return vb * (self.basis or MIN_SAT_VB)

    def min_gebuehr(self, inputs: int) -> int:
        """Untergrenze der Gebühr ohne Wechselgeld (für die Suche)."""
        vs = self.groessen.vsize(inputs, 1)
        if isinstance(self.basis, FesteRate):
            return self.basis.gebuehr(vs)
        return vs * MIN_SAT_VB


def _rate(basis: int | None, vsize: int, betrag: int) -> tuple[int, bool]:
    """Rate für diese vsize nach der Fee-Regel; ``True`` = Deckel griff."""
    if basis is None:
        return MIN_SAT_VB, False
    if basis * vsize * 1000 > betrag:
        return MIN_SAT_VB, basis > MIN_SAT_VB
    return basis, False


def _bewerte(n: int, gruen: int, wert: int, betrag: int, kosten: _Kosten) -> dict | None:
    """Beste Ausprägung (mit/ohne Wechselgeld) für n Inputs, sonst None."""
    if not isinstance(kosten, _Kosten):  # Rate direkt (int/None/FesteRate)
        kosten = _Kosten(kosten, Groessen())
    vs2 = kosten.groessen.vsize(n, 2)
    fee2, r2, deckel2 = kosten.gebuehr(vs2, betrag)
    wechsel = wert - betrag - fee2
    if gruen >= betrag + fee2 and wechsel >= STAUB_SATS:
        return {"wechselgeld": wechsel, "outputs": 2, "vsize": vs2, "sat_vb": r2,
                "fee": fee2, "deckel": deckel2, "staub": False, "staub_in_fee": 0}
    vs1 = kosten.groessen.vsize(n, 1)
    fee1, r1, deckel1 = kosten.gebuehr(vs1, betrag)
    rest = wert - betrag - fee1
    if gruen < betrag + fee1 or rest < 0:
        return None
    gesamt = fee1 + rest
    # Ohne Wechselgeld nur, wenn alle Inputs ganz grün sind — sonst ginge
    # nicht grünes Guthaben (gelb) in die Gebühr statt zurück ans Wallet.
    if wert == gruen and (rest == 0 or gesamt * 1000 <= betrag):
        return {"wechselgeld": 0, "outputs": 1, "vsize": vs1, "sat_vb": r1,
                "fee": gesamt, "deckel": deckel1, "staub": False, "staub_in_fee": rest}
    # Konflikt mit dem 0,1-%-Deckel (oder gemischte Inputs): Wechselgeld bleibt, auch wenn klein —
    # aber nicht unter der Relay-Staubgrenze (sonst nicht standardkonform).
    if gruen >= betrag + fee2 and wechsel >= STAUB_HART_SATS:
        return {"wechselgeld": wechsel, "outputs": 2, "vsize": vs2, "sat_vb": r2,
                "fee": fee2, "deckel": deckel2, "staub": True, "staub_in_fee": 0}
    return None


def _rang(loesung: dict, auswahl: tuple[Kandidat, ...]) -> tuple:
    return (
        loesung["wechselgeld"],
        len(auswahl),
        tuple(sorted(k.zeit for k in auswahl)),
        tuple(sorted(k.key for k in auswahl)),
    )


def _gier(kand: list[Kandidat], betrag: int, kosten: _Kosten):
    gewaehlt: list[Kandidat] = []
    g = w = 0
    loesung = None
    for k in kand:  # schon nach Beitrag absteigend
        gewaehlt.append(k)
        g += k.beitrag
        w += k.wert
        loesung = _bewerte(len(gewaehlt), g, w, betrag, kosten)
        if loesung is not None:
            break
    if loesung is None:
        return None
    # Überflüssige Inputs vom kleinsten Beitrag her entfernen.
    for k in sorted(gewaehlt, key=lambda x: (x.beitrag, -x.zeit, x.key)):
        probe = [x for x in gewaehlt if x is not k]
        if not probe:
            continue
        neu = _bewerte(len(probe), g - k.beitrag, w - k.wert, betrag, kosten)
        if neu is not None and _rang(neu, tuple(probe)) < _rang(loesung, tuple(gewaehlt)):
            gewaehlt, loesung = probe, neu
            g -= k.beitrag
            w -= k.wert
    return loesung, tuple(gewaehlt)


def _bnb(nutzbar: list[Kandidat], betrag: int, kosten: _Kosten, budget: int):
    """Kleinstes Wechselgeld: (Lösung, Auswahl, Meta) — Lösung None = nicht gedeckt."""
    rest_gruen = [0] * (len(nutzbar) + 1)
    for i in range(len(nutzbar) - 1, -1, -1):
        rest_gruen[i] = rest_gruen[i + 1] + nutzbar[i].beitrag

    beste: dict | None = None
    beste_auswahl: tuple[Kandidat, ...] = ()
    beste_rang: tuple | None = None
    knoten = 0
    erschoepft = False
    pfad: list[Kandidat] = []

    def suche(i: int, g: int, w: int) -> None:
        nonlocal beste, beste_auswahl, beste_rang, knoten, erschoepft
        if erschoepft:
            return
        knoten += 1
        if knoten > budget:
            erschoepft = True
            return
        n = len(pfad)
        if n:
            loesung = _bewerte(n, g, w, betrag, kosten)
            if loesung is not None:
                auswahl = tuple(pfad)
                rang = _rang(loesung, auswahl)
                if beste_rang is None or rang < beste_rang:
                    beste, beste_auswahl, beste_rang = loesung, auswahl, rang
                return  # mehr Inputs machen das Wechselgeld nicht kleiner
        if i >= len(nutzbar):
            return
        # Mindestgebühr mit einem weiteren Input (1 sat/vB, ohne Wechselgeld).
        if g + rest_gruen[i] < betrag + kosten.min_gebuehr(n + 1):
            return
        if beste_rang is not None and beste_rang[0] == 0 and n + 1 > beste_rang[1]:
            return  # 0 sats Wechselgeld mit weniger Inputs ist nicht zu schlagen
        k = nutzbar[i]
        pfad.append(k)
        suche(i + 1, g + k.beitrag, w + k.wert)
        pfad.pop()
        suche(i + 1, g, w)

    import sys

    alt = sys.getrecursionlimit()
    sys.setrecursionlimit(max(alt, 2 * len(nutzbar) + 100))
    try:
        suche(0, 0, 0)
    finally:
        sys.setrecursionlimit(alt)

    methode = "bnb"
    if erschoepft:
        gier = _gier(nutzbar, betrag, kosten)
        if gier is not None:
            g_loesung, g_auswahl = gier
            g_rang = _rang(g_loesung, g_auswahl)
            if beste_rang is None or g_rang < beste_rang:
                beste, beste_auswahl, beste_rang = g_loesung, g_auswahl, g_rang
                methode = "greedy"
    meta = {"knoten": min(knoten, budget), "budget_erschoepft": erschoepft, "methode": methode}
    return beste, beste_auswahl, meta


def _reihe(reihenfolge: list[Kandidat], betrag: int, kosten: _Kosten):
    """Der Reihe nach aufnehmen, bis Betrag + Gebühr gedeckt sind (kein Entfernen)."""
    gewaehlt: list[Kandidat] = []
    g = w = 0
    for k in reihenfolge:
        gewaehlt.append(k)
        g += k.beitrag
        w += k.wert
        loesung = _bewerte(len(gewaehlt), g, w, betrag, kosten)
        if loesung is not None:
            return loesung, tuple(gewaehlt)
    return None, ()


def _im_deckel(loesung: dict, betrag: int) -> bool:
    return loesung["fee"] * 1000 <= betrag


def _staub_dazu(nutzbar, basis_auswahl, basis_loesung, betrag, kosten):
    """
    Kleine zulässige UTXOs (< ``STAUB_AUFRAEUMEN_SATS``, wirtschaftlich: Beitrag
    > 68 vB × Rate) zusätzlich einsammeln, kleinste zuerst (dann älter, Key),
    solange die Gesamtgebühr im 0,1-%-Deckel bleibt und die Rate gleich bleibt.
    Sie landen im Wechselgeld. Liegt schon die Grundauswahl über dem Deckel,
    kommt nichts dazu.
    """
    drin = {k.key for k in basis_auswahl}
    klein = sorted(
        (k for k in nutzbar if k.key not in drin and k.wert < STAUB_AUFRAEUMEN_SATS),
        key=lambda k: (k.wert, k.zeit, k.key),
    )
    auswahl = list(basis_auswahl)
    loesung = basis_loesung
    g = sum(k.beitrag for k in auswahl)
    w = sum(k.wert for k in auswahl)
    dazu: list[Kandidat] = []
    begrenzt = False
    if not _im_deckel(basis_loesung, betrag):
        return loesung, tuple(auswahl), [], bool(klein)
    for k in klein:
        neu = _bewerte(len(auswahl) + 1, g + k.beitrag, w + k.wert, betrag, kosten)
        if neu is None:
            continue  # z. B. Wechselgeld unter Relay-Staub — ein größerer kann passen
        if not _im_deckel(neu, betrag) or neu["sat_vb"] < loesung["sat_vb"]:
            # Jeder weitere Input kostet gleich viel: Deckel erreicht, Schluss.
            # Die Rate darf dafür nicht auf 1 sat/vB fallen (Bestätigung ginge vor).
            begrenzt = True
            break
        auswahl.append(k)
        dazu.append(k)
        g += k.beitrag
        w += k.wert
        loesung = neu
    return loesung, tuple(auswahl), dazu, begrenzt


def waehle(
    kand: list[Kandidat],
    *,
    betrag: int,
    basis_rate: Any,
    budget: int = BUDGET_KNOTEN,
    strategie: str = STANDARD_STRATEGIE,
    groessen: Groessen | None = None,
    nur: Iterable[str] | None = None,
) -> dict:
    """
    Wählt Inputs nach *strategie* (siehe ``STRATEGIEN``).

    *basis_rate*: Schätzung + Puffer in sat/vB, None = keine Schätzung, oder
    ``FesteRate`` (Gebührenfeld der PSBT; kein Deckel auf die Rate).
    *groessen*: vbytes je Input/Output (Standard: Schätzformel).
    *nur*: Coin-Control — genau diese Kandidaten (``txid:vout``), keine Suche.
    Nicht zulässige Schlüssel liefern ``status`` ``unzulaessig``.
    """
    strategie = strategie if strategie in STRATEGIEN else STANDARD_STRATEGIE
    betrag = _int(betrag)
    kosten = _Kosten(basis_rate, groessen or Groessen())
    ergebnis: dict[str, Any] = {"betrag_sats": betrag, "kandidaten": len(kand), "strategie": strategie}
    if betrag <= 0:
        return {**ergebnis, "status": "kein_betrag"}
    if nur is not None:
        wunsch = list(dict.fromkeys(str(k or "").strip().lower() for k in nur if k))
        nach_key = {k.key: k for k in kand}
        fehlt = [k for k in wunsch if k not in nach_key]
        ergebnis["strategie"] = "coin_control"
        if not wunsch or fehlt:
            return {**ergebnis, "status": "unzulaessig", "unzulaessig": fehlt}
        auswahl = tuple(nach_key[k] for k in wunsch)
        beste = _bewerte(len(auswahl), sum(k.beitrag for k in auswahl),
                         sum(k.wert for k in auswahl), betrag, kosten)
        ergebnis.update({"methode": "coin_control", "budget_erschoepft": False})
        return _ergebnis(ergebnis, beste, auswahl, auswahl, "coin_control", [], False)
    nutzbar = [k for k in kand if k.beitrag > kosten.input_kosten()]
    if not nutzbar and not isinstance(basis_rate, FesteRate):
        nutzbar = [k for k in kand if k.beitrag > VBYTES_INPUT * MIN_SAT_VB]
    nutzbar.sort(key=lambda k: (-k.beitrag, k.zeit, k.key))
    if not nutzbar:
        return {**ergebnis, "status": "keine_kandidaten"}

    dazu: list[Kandidat] = []
    begrenzt = False
    if strategie == "gebuehr":
        beste, auswahl = _reihe(nutzbar, betrag, kosten)
        ergebnis.update({"methode": "groesste_zuerst", "budget_erschoepft": False})
    elif strategie == "aelteste":
        alt_zuerst = sorted(nutzbar, key=lambda k: (k.zeit, k.key))
        beste, auswahl = _reihe(alt_zuerst, betrag, kosten)
        ergebnis.update({"methode": "aelteste_zuerst", "budget_erschoepft": False})
    else:
        beste, auswahl, meta = _bnb(nutzbar, betrag, kosten, budget)
        ergebnis.update(meta)
        if beste is not None and strategie == "staub":
            beste, auswahl, dazu, begrenzt = _staub_dazu(nutzbar, auswahl, beste, betrag, kosten)
    return _ergebnis(ergebnis, beste, auswahl, nutzbar, strategie, dazu, begrenzt)


def _ergebnis(ergebnis, beste, auswahl, nutzbar, strategie, dazu, begrenzt) -> dict:
    if beste is None:
        return {**ergebnis, "status": "nicht_gedeckt",
                "gruen_verfuegbar_sats": sum(k.beitrag for k in nutzbar)}
    inputs = sorted(auswahl, key=lambda k: (k.zeit, k.key))
    erg = {
        **ergebnis,
        "status": "ok",
        "inputs": [
            {"key": k.key, "txid": k.txid, "vout": k.vout, "value_sats": k.wert,
             "sats_gruen": k.beitrag,
             "time_ts": None if k.zeit == _ZEIT_UNBEKANNT else k.zeit}
            for k in inputs
        ],
        "anzahl_inputs": len(inputs),
        "outputs": beste["outputs"],
        "vsize": beste["vsize"],
        "sat_vb": beste["sat_vb"],
        "fee_sats": beste["fee"],
        "deckel": beste["deckel"],
        "wechselgeld_sats": beste["wechselgeld"],
        "ohne_wechselgeld": beste["outputs"] == 1,
        "staub_wechselgeld": beste["staub"],
        "staub_in_gebuehr_sats": beste["staub_in_fee"],
        "summe_inputs_sats": sum(k.wert for k in inputs),
        "summe_gruen_sats": sum(k.beitrag for k in inputs),
        # Nicht grüner Teil der Inputs (gelb, ggf. 1 sat Rundung): zurück ins Wechselgeld.
        "wechselgeld_nicht_gruen_sats": sum(k.wert - k.beitrag for k in inputs),
        "gemischte_inputs": sum(1 for k in inputs if k.wert > k.beitrag),
    }
    if strategie == "staub":
        erg.update({
            "aufraeumen_grenze_sats": STAUB_AUFRAEUMEN_SATS,
            "aufraeumen_anzahl": len(dazu),
            "aufraeumen_sats": sum(k.wert for k in dazu),
            "aufraeumen_begrenzt": begrenzt,
        })
    return erg


def auswahl_vorschau(
    utxos: Iterable[dict],
    *,
    modus: str,
    betrag: int,
    pending: Iterable[str] = (),
    feerate_btc_kvb: Any = None,
    fehler: str | None = None,
    budget: int = BUDGET_KNOTEN,
    strategie: str = STANDARD_STRATEGIE,
    groessen: "Groessen | None" = None,
    eigenes_ziel: bool = False,
) -> dict:
    """
    Kandidaten filtern, Rate nach der Fee-Regel bestimmen, Auswahl suchen.

    ``quelle`` wie beim Gebührenvorschlag: ``schaetzung``, ``deckel`` oder
    ``fallback`` (keine Schätzung, 1 sat/vB; ``grund`` sagt warum).
    *groessen*: vbytes des Wallets (Multisig), sonst die Schätzformel.
    """
    from core.fee_vorschlag import btc_kvb_zu_sat_vb, rate_mit_puffer

    modus = "offensiv" if modus == "offensiv" else "defensiv"
    schaetzung = btc_kvb_zu_sat_vb(feerate_btc_kvb) if feerate_btc_kvb is not None else None
    basis = rate_mit_puffer(schaetzung)
    kand = kandidaten(utxos, modus=modus, pending=pending, eigenes_ziel=eigenes_ziel)
    erg = waehle(kand, betrag=betrag, basis_rate=basis, budget=budget, strategie=strategie,
                 groessen=groessen)
    if basis is None:
        quelle = "fallback"
    elif erg.get("deckel"):
        quelle = "deckel"
    else:
        quelle = "schaetzung"
    erg.update({
        "modus": modus,
        "conf_target": 1,
        "schaetzung_sat_vb": float(schaetzung) if schaetzung is not None else None,
        "rate_ohne_deckel": basis,
        "quelle": quelle,
    })
    if quelle == "deckel" and erg.get("vsize"):
        erg["fee_ohne_deckel"] = basis * int(erg["vsize"])
    if basis is None:
        erg["grund"] = fehler or "keine Schätzung"
    return erg


def netto_max(
    kand: list[Kandidat],
    *,
    basis_rate: Any,
    groessen: Groessen | None = None,
) -> dict:
    """
    Größter Betrag, den ``waehle`` bei dieser Rate noch deckt — das
    Netto-Maximum (grünes Maximum minus Gebühr). ``max_netto_sats`` + 1 ist
    nie gedeckt.

    Kandidaten wie in ``waehle`` (Beitrag > eigene Input-Gebühr). Geprüft
    werden zwei Mengen: alle nutzbaren und nur die ganz grünen (ohne
    gemischten Input entfällt eventuell der Wechselgeld-Output). Jede
    Teilmenge mit weniger Inputs deckt weniger, weil jeder nutzbare Input mehr
    beiträgt, als er kostet. Je Menge kommen die Randfälle von ``_bewerte``
    in Frage (ohne Wechselgeld, mit Wechselgeld, Staubgrenzen); der größte
    gedeckte gewinnt, danach wird nach oben nachgeprüft.
    """
    kosten = _Kosten(basis_rate, groessen or Groessen())
    nutzbar = [k for k in kand if k.beitrag > kosten.input_kosten()]
    if not nutzbar and not isinstance(basis_rate, FesteRate):
        nutzbar = [k for k in kand if k.beitrag > VBYTES_INPUT * MIN_SAT_VB]
    mengen = [nutzbar, [k for k in nutzbar if k.wert == k.beitrag]]
    beste = {"max_netto_sats": 0, "inputs": 0, "outputs": 0, "vsize": 0, "fee_sats": 0,
             "brutto_sats": sum(k.beitrag for k in nutzbar)}
    gesehen: set[int] = set()
    for menge in mengen:
        if not menge or len(menge) in gesehen:
            continue
        gesehen.add(len(menge))
        n = len(menge)
        g = sum(k.beitrag for k in menge)
        w = sum(k.wert for k in menge)

        def gedeckt(b: int) -> bool:
            return b > 0 and _bewerte(n, g, w, b, kosten) is not None

        fee1 = kosten.gebuehr(kosten.groessen.vsize(n, 1), g)[0]
        fee2 = kosten.gebuehr(kosten.groessen.vsize(n, 2), g)[0]
        kandidat = [b for b in (g - fee1, w - fee1, g - fee2, w - fee2 - STAUB_SATS,
                                w - fee2 - STAUB_HART_SATS) if gedeckt(b)]
        if kandidat:
            b = max(kandidat)
            schritte = 0
            while gedeckt(b + 1) and schritte < 1_000_000:
                b += 1
                schritte += 1
        else:
            lo, hi, b = 1, g, 0
            while lo <= hi:  # Rückfall (Rate mit Deckel): größter gedeckter Betrag
                mitte = (lo + hi) // 2
                if gedeckt(mitte):
                    b, lo = mitte, mitte + 1
                else:
                    hi = mitte - 1
        if b > beste["max_netto_sats"]:
            l = _bewerte(n, g, w, b, kosten)
            beste.update({"max_netto_sats": b, "inputs": n, "outputs": l["outputs"],
                          "vsize": l["vsize"], "fee_sats": l["fee"]})
    return beste
