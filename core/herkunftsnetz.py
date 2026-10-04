"""
Herkunftsnetz als Overlay im Steuerjahr-Zeitstrahl (ISSUES: Steuerjahr ·
Herkunftsnetz als Overlay, Schritt 1).

Aus dem **einen** gespeicherten Herkunftsbaum eines UTXO wird ein flaches
Netz für die Oberfläche: eigene Vorfahren als Knoten, Kanten mit dem
Sat-Anteil am gewählten Output. Der Baum selbst geht nicht an den Browser
(Lazy-Tree-Invariante); ``zeitstrahl()`` und seine ``events[]`` bleiben
unberührt — das Netz ist ein ephemerer Zusatz.

X der Knoten ist die **Output-Zeit** des Hops (Blockzeit aus der Höhe über
den ``block_header``-Cache, sonst die im Baum abgelegte Blockzeit) — auf
derselben 0..100-Skala wie ``core.tax.zeitstrahl``. Y ist dieselbe
log1p-Skala auf ``anteil_sats``: dem Stück des gewählten Outputs, das durch
diesen Knoten läuft. 100 % liegen auf der Höhe des Fokus. ``value_sats``
bleibt der volle Nennwert für den Tooltip. X wird nicht geklemmt: Vorfahren
dürfen älter als der Achsenbeginn sein; die Oberfläche setzt sie an den Rand.

Anteile: FIFO je Output (``core.fifo_lots``, Entscheidung Maintainer
2026-10-04). An jedem eigenen Hop werden die Lose aller Eingänge nach
Anschaffungszeit geordnet; was das Wallet verlässt (fremde Outputs, andere
eigene Wallets, Gebühr) nimmt die ältesten, das Wechselgeld behält den Rest.
Hops mit fremden oder ungeklärten Eingängen, ohne Tx im Cache oder ohne
Wallet-Kontext verteilen wie bisher anteilig (pro rata). So summieren sich
die Kanten in einen Knoten zu dessen Anteil am gewählten Output.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from core import fifo_lots
from core.tax import _minus_monate, _y_log_prozent
from core.trace import FULL_RESOLUTION_INPUT_LIMIT
from core.tx_classify import COINJOIN_KINDS

#: Obergrenze eindeutiger Knoten — darüber werden weitere Eingänge zu je
#: einem Bündel „n Eingänge“ (kein Haarnetz, auch bei tiefen Bäumen).
MAX_KNOTEN = 600

TYP_EIGEN = "eigen"
TYP_HORIZONT = "horizont"
TYP_FREMD = "fremd"
TYP_COINBASE = "coinbase"
TYP_BUENDEL = "buendel"
TYP_LUECKE = "luecke"

_BLOCK_RE = re.compile(r"Block\s+([\d.,]+)")
_DATUM_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?")


@dataclass(frozen=True)
class Skala:
    """Dieselbe X/Y-Abbildung wie ``core.tax.zeitstrahl``."""

    von: datetime
    bis: datetime
    hoechst: int

    def pos(self, zeitpunkt: datetime) -> float:
        """X in % — ungeklemmt (vor dem Achsenbeginn negativ)."""
        spanne = (self.bis - self.von).total_seconds()
        return round((zeitpunkt - self.von).total_seconds() / spanne * 100, 3)

    def y(self, sats: int) -> float:
        return _y_log_prozent(int(sats), self.hoechst)


def y_aus_beitrag(skala: Skala, anteil_sats: float) -> float:
    """Höhe = Anteil dieses Knotens am gewählten Output, in sats."""
    return skala.y(max(0, int(round(float(anteil_sats or 0)))))


def skala_aus_auswertung(auswertung: dict) -> Skala | None:
    """
    Rekonstruiert die Zeitstrahl-Skala aus einer Steuer-Auswertung.

    Wie ``zeitstrahl()``: Beginn 6 Monate vor dem ältesten Eingang, Ende
    beim jüngsten Eingang oder dem Bezugstag (``bezug_ts``), was später
    liegt; Y-Ende ist ``max_sats``. Ohne Zeitstrahl: ``None``.
    """
    strahl = auswertung.get("zeitstrahl") or {}
    events = strahl.get("events") or []
    if not strahl.get("vorhanden") or not events:
        return None
    zeiten = [
        datetime.fromtimestamp(int(e["time_ts"]))
        for e in events if e.get("time_ts") is not None
    ]
    if not zeiten:
        return None
    von = _minus_monate(min(zeiten), 6)
    bis = max(zeiten)
    bezug = auswertung.get("bezug_ts")
    if bezug is not None:
        bis = max(bis, datetime.fromtimestamp(float(bezug)))
    if (bis - von).total_seconds() <= 0:
        bis = von + timedelta(days=180)
    return Skala(von=von, bis=bis, hoechst=int(strahl.get("max_sats") or 1))


def output_zeit(
    knoten: dict, block_zeit: Callable[[int], int | None] | None = None,
) -> datetime | None:
    """
    Output-Zeit eines Baumknotens.

    Reihenfolge: Blockhöhe (Feld oder „Block N“ im Label) → ``block_header``-
    Cache; sonst ``block_time``/``time_ts`` des Knotens; sonst das Datum im
    ``time_label``. Ohne jede Zeit: ``None``.
    """
    label = str(knoten.get("time_label") or "")
    hoehe = knoten.get("block_height")
    if not hoehe:
        treffer = _BLOCK_RE.search(label)
        if treffer:
            try:
                hoehe = int(re.sub(r"[.,]", "", treffer.group(1)))
            except ValueError:
                hoehe = None
    if hoehe and block_zeit is not None:
        try:
            ts = block_zeit(int(hoehe))
        except Exception:
            ts = None
        if ts:
            return datetime.fromtimestamp(int(ts))
    for feld in ("block_time", "time_ts"):
        wert = knoten.get(feld)
        if wert:
            try:
                return datetime.fromtimestamp(int(wert))
            except (TypeError, ValueError, OverflowError, OSError):
                pass
    treffer = _DATUM_RE.search(label)
    if treffer:
        t, m, j, hh, mm, ss = treffer.groups()
        try:
            return datetime(
                int(j), int(m), int(t), int(hh or 0), int(mm or 0), int(ss or 0),
            )
        except ValueError:
            return None
    return None


def _pos(wert) -> float | None:
    try:
        pos = float(wert)
    except (TypeError, ValueError):
        return None
    if pos != pos or pos in (float("inf"), float("-inf")):
        return None
    return pos


def _obergrenze_ts(
    key: str,
    nach: dict[str, list[str]],
    zeiten: dict[str, int],
) -> int | None:
    """Früheste datierte Nachfolger-Zeit. Der Eingang kann nicht jünger sein."""
    beste: int | None = None
    schlange = list(nach.get(key) or [])
    gesehen: set[str] = set()
    while schlange:
        nxt = schlange.pop()
        if not nxt or nxt in gesehen:
            continue
        gesehen.add(nxt)
        ts = zeiten.get(nxt) or 0
        if ts > 0 and (beste is None or ts < beste):
            beste = ts
        schlange.extend(nach.get(nxt) or [])
    return beste


def _sicher_ausserhalb(
    time_ts: int | None,
    *,
    bezug: datetime | None,
    jahre: int,
    stichtag: date | None,
) -> bool:
    """
    Obergrenze liegt außerhalb der Haltefrist und, falls gesetzt, nicht
    nach dem Stichtag. Dann ist der undatierte Eingang ebenfalls sicher.
    """
    if not time_ts or bezug is None:
        return False
    try:
        anschaffung = datetime.fromtimestamp(int(time_ts))
    except (TypeError, ValueError, OSError, OverflowError):
        return False
    from core.tax import haltefrist_entscheidung

    _ende, erfuellt, neu = haltefrist_entscheidung(
        anschaffung, bezug, int(jahre or 0), stichtag,
    )
    return bool(erfuellt) and not neu


def lot_mischung(
    vorfahren: list[dict] | None,
    frist_pos,
    fokus_key: str = "",
    *,
    kanten: list[dict] | None = None,
    bezug: datetime | None = None,
    jahre: int = 1,
    stichtag: date | None = None,
) -> dict | None:
    """
    Lose des Fokus aus den Endknoten, gewichtet mit ``anteil_sats``.

    Dieselbe Regel wie ``herkunftsnetzLotMischung`` in
    ``web/views/herkunftsnetz.js``: Grün, wenn ein fremdes oder
    Coinbase-Ende oder ein datiertes Bündel links der Fristgrenze liegt
    (``pos_output < frist_pos``). Orange, wenn es darauf oder rechts liegt.
    Das Bündeldatum ist die jüngste bekannte Output-Zeit seiner Eingänge.
    Grau ohne Datum, ohne Fristposition, oder bei Lücke und Horizont.
    Ein undatiertes Ende zählt trotzdem grün, wenn ein Nachfolger schon
    außerhalb der Haltefrist und nicht nach dem Stichtag liegt — der
    Eingang kann nicht jünger sein als diese Ausgabe.
    Eigene Zwischenhops und der Fokus zählen nicht.
    ``sats_ohne_datum`` bleibt der undatierte Anteil, auch wenn er als
    Grün gezählt wird.
    ``lot_von_ts``/``lot_bis_ts``: ältestes/jüngstes Los (Unix) — nur, wenn
    jedes Ende mit Anteil ein datiertes Fremd- oder Coinbase-Ende ist,
    sonst fehlen beide.
    """
    acc = {"sats_gruen": 0.0, "sats_orange": 0.0, "sats_grau": 0.0}
    ohne_datum = 0.0
    los_zeiten: list[int] = []
    los_datiert = True
    frist = _pos(frist_pos)
    nach: dict[str, list[str]] = {}
    zeiten: dict[str, int] = {}
    for kante in kanten or []:
        if not isinstance(kante, dict):
            continue
        von = str(kante.get("von") or "")
        ziel = str(kante.get("nach") or "")
        if von and ziel:
            nach.setdefault(von, []).append(ziel)
    for v in vorfahren or []:
        if not isinstance(v, dict):
            continue
        try:
            ts = int(v.get("time_ts") or 0)
        except (TypeError, ValueError):
            ts = 0
        if v.get("key") and ts > 0:
            zeiten[str(v["key"])] = ts
    for v in vorfahren or []:
        if not isinstance(v, dict) or not v.get("ende"):
            continue
        if fokus_key and v.get("key") == fokus_key:
            continue
        try:
            gewicht = float(v.get("anteil_sats") or 0)
        except (TypeError, ValueError):
            continue
        if gewicht <= 0:
            continue
        try:
            los_ts = int(v.get("time_ts") or 0)
        except (TypeError, ValueError):
            los_ts = 0
        if v.get("typ") in (TYP_FREMD, TYP_COINBASE) and los_ts > 0:
            los_zeiten.append(los_ts)
        else:
            los_datiert = False
        farbe = "sats_grau"
        pos = _pos(v.get("pos_output"))
        if (
            v.get("typ") in (TYP_FREMD, TYP_COINBASE, TYP_BUENDEL)
            and pos is not None
            and frist is not None
        ):
            farbe = "sats_gruen" if pos < frist else "sats_orange"
        elif pos is None and _sicher_ausserhalb(
            _obergrenze_ts(str(v.get("key") or ""), nach, zeiten),
            bezug=bezug, jahre=jahre, stichtag=stichtag,
        ):
            farbe = "sats_gruen"
        if pos is None:
            ohne_datum += gewicht
        acc[farbe] += gewicht
    if acc["sats_gruen"] + acc["sats_orange"] + acc["sats_grau"] <= 0:
        return None
    aus = {name: int(round(wert)) for name, wert in acc.items()}
    aus["sats_ohne_datum"] = int(round(ohne_datum))
    if los_datiert and los_zeiten:
        aus["lot_von_ts"] = min(los_zeiten)
        aus["lot_bis_ts"] = max(los_zeiten)
    return aus


def lot_ring(
    baum: dict,
    fokus_key: str,
    *,
    fifo: "FifoKontext | None" = None,
    block_zeit: Callable[[int], int | None] | None = None,
    jahre: int = 1,
    stichtag: date | None = None,
    jetzt: datetime | None = None,
) -> dict | None:
    """
    Lot-Ring eines UTXO ohne Steuer-Auswertung (Herkunft, Wallet-Liste).

    Dieselbe Rechnung wie der Ring im Steuerjahr — ``flach`` (FIFO je
    Output mit *fifo*) und ``lot_mischung`` —, nur mit einer eigenen Achse
    vom Genesis-Block bis *jetzt* und der Fristgrenze *jetzt* − *jahre*.
    Liefert ``sats_gruen``/``sats_orange``/``sats_grau`` (+ ``anteilig``).
    """
    from core.tax import plus_jahre

    if not isinstance(baum, dict) or not baum.get("found") or not baum.get("root"):
        return None
    jetzt = jetzt or datetime.now()
    skala = Skala(von=datetime(2009, 1, 3), bis=jetzt, hoechst=1)
    if int(jahre or 0) > 0:
        frist_pos = skala.pos(plus_jahre(jetzt, -int(jahre)))
    else:
        frist_pos = skala.pos(jetzt) + 1.0  # ohne Frist: alles Datierte grün
    netz = flach(baum, fokus_key, skala, block_zeit=block_zeit, fifo=fifo)
    seg = lot_mischung(
        netz.get("vorfahren"), frist_pos, fokus_key,
        kanten=netz.get("kanten"), bezug=jetzt, jahre=int(jahre or 0), stichtag=stichtag,
    )
    if not seg:
        return None
    return {
        "sats_gruen": seg["sats_gruen"],
        "sats_orange": seg["sats_orange"],
        "sats_grau": seg["sats_grau"],
        "anteilig": bool(netz.get("anteilig")),
    }


def _typ(knoten: dict) -> str:
    typ = knoten.get("type")
    if typ == "internal":
        return TYP_HORIZONT if knoten.get("tax_horizon") else TYP_EIGEN
    if typ == "tax_horizon":
        return TYP_HORIZONT
    if typ == "external":
        return TYP_FREMD
    if typ == "coinbase":
        return TYP_COINBASE
    return TYP_LUECKE


def _schluessel(knoten: dict, typ: str, eltern: str, nummer: int) -> str:
    herkunft = str(knoten.get("from_utxo") or "").strip()
    if typ in (TYP_EIGEN, TYP_HORIZONT) and herkunft:
        return herkunft
    if typ == TYP_FREMD:
        return herkunft or f"fremd:{eltern}:{nummer}"
    if typ == TYP_COINBASE:
        return f"coinbase:{eltern}"
    return f"{knoten.get('type') or 'luecke'}:{herkunft or eltern}"


def _buendeln(eltern: dict, kinder: list[dict]) -> bool:
    """CoinJoin, Sammel-Tx über dem Auflöse-Limit oder abgebrochene Auflösung."""
    if str(eltern.get("tx_class") or "") in COINJOIN_KINDS:
        return True
    if len(kinder) > FULL_RESOLUTION_INPUT_LIMIT:
        return True
    return any(k.get("type") == "external_unresolved" for k in kinder)


def _coinjoin_eigen(
    eltern: dict,
    kinder: list[dict],
    eltern_key: str,
    fifo: "FifoKontext | None",
) -> bool:
    """
    CoinJoin, der nicht gebündelt wird: Seine Eingänge im Baum sind alle
    eigen und aufgelöst (die Verfolgung hinter einem CoinJoin folgt nur den
    eigenen Eingängen), und sie decken die eigenen Outputs der Tx.

    Dann finanzieren die eigenen Eingänge die eigenen Outputs (die fremden
    Teilnehmer ihre eigenen); die Herkunft läuft durch den CoinJoin weiter
    zu den Losen der eigenen Eingänge (``_fifo_coinjoin_hop``), statt an
    deren Output-Zeit als Bündel zu enden. Ohne Tx im Cache zählt der
    Fokus-Output selbst als „eigene Outputs“.
    """
    if str(eltern.get("tx_class") or "") not in COINJOIN_KINDS:
        return False
    if not kinder or len(kinder) > FULL_RESOLUTION_INPUT_LIMIT:
        return False
    for kind in kinder:
        if kind.get("type") == "external_unresolved":
            return False
        if _typ(kind) not in (TYP_EIGEN, TYP_HORIZONT):
            return False
        if not str(kind.get("from_utxo") or "").strip():
            return False
    summe_ein = sum(int(k.get("amount_sats") or 0) for k in kinder)
    eigen_aus = int(eltern.get("amount_sats") or 0)
    outpoint = _schluessel_outpoint(eltern_key)
    tx = fifo.tx(outpoint[0]) if fifo is not None and outpoint else None
    if isinstance(tx, dict):
        index = _vin_index(tx)
        if any(str(k.get("from_utxo")).strip().lower() not in index for k in kinder):
            return False
        eigen_aus = sum(
            wert for _n, wert, adresse in _tx_ausgaenge(tx) if fifo.wallet(adresse)
        )
    return eigen_aus > 0 and summe_ein >= eigen_aus


@dataclass(frozen=True)
class FifoKontext:
    """
    Woher ``flach`` die Erzeuger-Txs und die Wallet-Zuordnung nimmt.

    *tx*: Tx aus dem Cache (RPC- oder Esplora-Form) oder None.
    *wallet*: Anzeigename des eigenen Wallets einer Adresse oder None — nur
    bekannter Bestand (``WalletContext.own_label``), keine XPUB-Suche.
    """

    tx: Callable[[str], dict | None]
    wallet: Callable[[str], str | None]

    @classmethod
    def aus_cache(cls, cache, wallet_ctx) -> "FifoKontext | None":
        """Tx-Flatfile-Cache plus ``WalletContext`` — ohne Wallet-Kontext None."""
        if wallet_ctx is None:
            return None
        from core import xpub_cache

        label = getattr(wallet_ctx, "own_label", None)
        zuordnung = getattr(wallet_ctx, "address_to_wallet", None)

        def wallet(adresse: str) -> str | None:
            if not adresse:
                return None
            if callable(label):
                treffer = label(adresse)
                if treffer:
                    return treffer
            if isinstance(zuordnung, dict):
                return zuordnung.get(adresse)
            return None

        def tx(txid: str) -> dict | None:
            try:
                return xpub_cache.load_cached_tx(txid, cache)
            except Exception:
                return None

        return cls(tx=tx, wallet=wallet)


def _schluessel_outpoint(key: str) -> tuple[str, int] | None:
    txid, _, vout = str(key or "").rpartition(":")
    if len(txid) != 64:
        return None
    try:
        return txid.lower(), int(vout)
    except ValueError:
        return None


def _tx_ausgaenge(tx: dict) -> list[tuple[int, int, str]]:
    from core.utxo_report import _extract_addresses, _extract_value_sats

    aus = []
    for pos, v in enumerate(tx.get("vout") or []):
        if not isinstance(v, dict):
            return []
        try:
            n = int(v.get("n", pos))
            wert = int(_extract_value_sats(v))
        except (TypeError, ValueError):
            return []
        adressen = _extract_addresses(v) or [""]
        aus.append((n, wert, str(adressen[0] or "")))
    return aus


def _vin_index(tx: dict) -> dict[str, int]:
    aus: dict[str, int] = {}
    for pos, vin in enumerate(tx.get("vin") or []):
        if isinstance(vin, dict) and vin.get("txid") is not None:
            aus[f"{str(vin['txid']).lower()}:{int(vin.get('vout') or 0)}"] = pos
    return aus


def _fifo_hop(
    fifo: FifoKontext | None,
    key: str,
    sats: int,
    kinder: list[tuple[dict, str, str]],
    eingang: list[list[fifo_lots.Los]],
) -> list[fifo_lots.Los] | None:
    """
    Lose, die der Output *key* aus seiner Erzeuger-Tx bekommt (FIFO je
    Output, ``core.fifo_lots``). None = Fallback anteilig: kein Kontext, Tx
    nicht im Cache, fremde/ungeklärte Eingänge, Eingänge nicht vollständig
    aufgelöst oder Beträge passen nicht zusammen.
    """
    if fifo is None:
        return None
    outpoint = _schluessel_outpoint(key)
    if outpoint is None:
        return None
    if any(typ not in (TYP_EIGEN, TYP_HORIZONT) for _k, _s, typ in kinder):
        return None
    tx = fifo.tx(outpoint[0])
    if not isinstance(tx, dict):
        return None
    vins = tx.get("vin") or []
    if len(vins) != len(kinder):
        return None
    ausgaenge = _tx_ausgaenge(tx)
    eigener = [a for a in ausgaenge if a[0] == outpoint[1]]
    if not eigener or eigener[0][1] != int(sats):
        return None
    index = _vin_index(tx)
    sender: set[str] = set()
    summe_ein = 0
    lose: list[fifo_lots.Los] = []
    for pos, ((kind, ckey, _typ), kind_lose) in enumerate(zip(kinder, eingang)):
        wallet = fifo.wallet(str(kind.get("address") or ""))
        if wallet:
            sender.add(wallet)
        summe_ein += int(kind.get("amount_sats") or 0)
        vin_pos = index.get(str(ckey).lower(), pos)
        lose.extend(
            fifo_lots.Los(sats=l.sats, zeit=l.zeit, rang=(vin_pos,) + l.rang, marke=l.marke)
            for l in kind_lose
        )
    if not sender:
        return None
    gebuehr = summe_ein - sum(a[1] for a in ausgaenge)
    if gebuehr < 0:
        return None
    verteilt = fifo_lots.je_output(
        lose,
        ((n, wert, fifo.wallet(adresse) in sender) for n, wert, adresse in ausgaenge),
        gebuehr,
    )
    return verteilt.get(fifo_lots.output_schluessel(outpoint[1]), [])


def _fifo_coinjoin_hop(
    fifo: FifoKontext | None,
    key: str,
    sats: int,
    kinder: list[tuple[dict, str, str]],
    eingang: list[list[fifo_lots.Los]],
) -> list[fifo_lots.Los] | None:
    """
    Lose eines eigenen CoinJoin-Outputs (Whirlpool-Mix, WabiSabi, …).

    Die eigenen Eingänge (*kinder*) finanzieren nur die eigenen Outputs; die
    fremden Ein- und Ausgänge gehören den anderen Teilnehmern und bleiben
    außen vor. Die Lose der eigenen Eingänge laufen FIFO (älteste zuerst)
    durch dieselbe Verbraucher-Regel wie jeder Hop (``fifo_lots``): eigene
    Outputs an ein anderes eigenes Wallet nach vout, dann der Abfluss
    (eigene Eingänge − eigene Outputs = Koordinator- und Mining-Gebühr,
    verlässt das Wallet), dann die Outputs zurück an ein Wallet der Eingänge
    nach vout. Mehrere Rückflüsse (WabiSabi mit mehreren eigenen Outputs):
    defensiv das jüngste verbliebene Los für jeden (``fifo_lots.je_output``).
    None = Fallback anteilig über die eigenen Eingänge.
    """
    if fifo is None:
        return None
    outpoint = _schluessel_outpoint(key)
    if outpoint is None:
        return None
    tx = fifo.tx(outpoint[0])
    if not isinstance(tx, dict):
        return None
    ausgaenge = _tx_ausgaenge(tx)
    eigener = [a for a in ausgaenge if a[0] == outpoint[1]]
    if not eigener or eigener[0][1] != int(sats):
        return None
    index = _vin_index(tx)
    sender: set[str] = set()
    summe_ein = 0
    lose: list[fifo_lots.Los] = []
    for pos, ((kind, ckey, _typ), kind_lose) in enumerate(zip(kinder, eingang)):
        vin_pos = index.get(str(ckey).lower())
        if vin_pos is None:
            return None
        wallet = fifo.wallet(str(kind.get("address") or ""))
        if wallet:
            sender.add(wallet)
        summe_ein += int(kind.get("amount_sats") or 0)
        lose.extend(
            fifo_lots.Los(sats=l.sats, zeit=l.zeit, rang=(vin_pos,) + l.rang, marke=l.marke)
            for l in kind_lose
        )
    if not sender:
        return None
    eigene = []
    for n, wert, adresse in ausgaenge:
        wallet = fifo.wallet(adresse)
        if wallet:
            eigene.append((n, wert, wallet in sender))
    if outpoint[1] not in {n for n, _w, _z in eigene}:
        return None
    abfluss = summe_ein - sum(w for _n, w, _z in eigene)
    if abfluss < 0:
        return None
    verteilt = fifo_lots.je_output(lose, eigene, abfluss)
    return verteilt.get(fifo_lots.output_schluessel(outpoint[1]), [])


def _skaliere(lose: list[fifo_lots.Los], ziel: float) -> list[fifo_lots.Los]:
    """Anteilig auf *ziel* sats (Fallback ohne FIFO)."""
    gesamt = sum(l.sats for l in lose)
    if gesamt > 0:
        f = ziel / gesamt
        return [fifo_lots.Los(l.sats * f, l.zeit, l.rang, l.marke) for l in lose]
    if not lose:
        return []
    je = ziel / len(lose)
    return [fifo_lots.Los(je, l.zeit, l.rang, l.marke) for l in lose]


def flach(
    baum: dict,
    fokus_key: str,
    skala: Skala,
    *,
    block_zeit: Callable[[int], int | None] | None = None,
    max_knoten: int = MAX_KNOTEN,
    fifo: FifoKontext | None = None,
) -> dict:
    """
    Flaches Herkunftsnetz des Fokus-UTXO aus dem gespeicherten UI-Baum.

    ``vorfahren`` enthält den Fokus selbst (``tiefe`` 0, Layer B an seiner
    Output-Zeit) und alle Vorfahren mit Anteil; ``kanten`` laufen vom Eingang
    (``von``) zum Output, den er mitfinanziert (``nach``). ``sats`` ist der
    Anteil am Fokus-Output. Fremd/Coinbase/Bündel/Horizont sind Endknoten
    (``ende``).

    Anteile: mit *fifo* FIFO je Output (``core.fifo_lots``) an jedem Hop,
    dessen Eingänge alle eigen und aufgelöst sind und dessen Tx im Cache
    liegt; sonst anteilig (pro rata). Ein CoinJoin, dessen Eingänge im Baum
    alle eigen sind und die eigenen Outputs decken, wird nicht gebündelt:
    Die Herkunft läuft zu den Losen der eigenen Eingänge weiter
    (``_coinjoin_eigen``, ``_fifo_coinjoin_hop``). Vorfahren ohne Anteil am Fokus fallen
    weg. ``anteilig`` sagt, ob ein anteiliger Hop (mit Losen verschiedener
    Zeit) oder ein Bündel zum Fokus beiträgt.
    """
    import sys

    wurzel = dict(baum.get("root") or {})
    wurzel["children"] = baum.get("children") or []
    fokus_sats = int(wurzel.get("amount_sats") or 0)

    knoten: dict[str, dict] = {}
    reihenfolge: list[str] = []
    eigen_kante: dict[tuple[str, str], bool] = {}
    #: id(Instanz) → (Schlüssel, Plan); Plan None = Ende,
    #: ("buendel", key) oder ("kinder", [(kind, key, typ, marker)], coinjoin).
    instanz: dict[int, tuple[str, tuple | None]] = {}
    #: Hops, die anteilig verteilt haben und dabei Lose verschiedener Zeit
    #: mischten, und Bündel — dort ist kein Los-Datum belastbar.
    anteilig_keys: set[str] = set()

    def zeitfelder(zeit: datetime | None) -> dict:
        if zeit is None:
            return {"pos_output": None, "zeit": "", "time_ts": None}
        return {
            "pos_output": skala.pos(zeit),
            "zeit": zeit.strftime("%d.%m.%Y %H:%M"),
            "time_ts": int(zeit.timestamp()),
        }

    def neu(key: str, eintrag: dict, _anteil: float = 0.0) -> None:
        if key in knoten:
            alt = knoten[key]
            alt["tiefe"] = min(alt["tiefe"], eintrag["tiefe"])
            return
        eintrag["anteil_sats"] = 0.0
        knoten[key] = eintrag
        reihenfolge.append(key)

    def kante(von: str, nach: str, _sats: float, eigen: bool) -> None:
        schluessel = (von, nach)
        eigen_kante[schluessel] = eigen_kante.get(schluessel, True) and eigen

    zeit0 = output_zeit(wurzel, block_zeit)
    neu(fokus_key, {
        "key": fokus_key,
        "typ": TYP_EIGEN,
        "value_sats": fokus_sats,
        "y": skala.y(fokus_sats),
        "wallet": wurzel.get("wallet") or "",
        "eigen": True,
        "ende": not wurzel["children"],
        "tiefe": 0,
        "n": 0,
        **zeitfelder(zeit0),
    })
    instanz[id(wurzel)] = (fokus_key, None)

    # 1) Struktur: Knoten, Kanten, Bündel — Breitensuche wie bisher.
    gekappt = False
    schlange: deque = deque([(wurzel, fokus_key, 0)])
    while schlange:
        eltern, eltern_key, tiefe = schlange.popleft()
        kinder = [k for k in (eltern.get("children") or []) if isinstance(k, dict)]
        if not kinder:
            continue
        voll = len(knoten) >= max_knoten
        coinjoin = _coinjoin_eigen(eltern, kinder, eltern_key, fifo)
        buendeln = _buendeln(eltern, kinder) and not coinjoin
        gekappt = gekappt or (voll and not buendeln)
        if voll or buendeln:
            bkey = _buendel(
                kinder, eltern_key, 0.0, tiefe + 1, fokus_sats,
                neu=neu, kante=kante, zeitfelder=zeitfelder, skala=skala,
                block_zeit=block_zeit,
            )
            instanz[id(eltern)] = (eltern_key, ("buendel", bkey))
            continue
        plan: list[tuple[dict, str, str, bool]] = []
        for nummer, kind in enumerate(kinder):
            typ = _typ(kind)
            key = _schluessel(kind, typ, eltern_key, nummer)
            if key == eltern_key:
                # Marker-Blatt am Hop selbst (Steuer-Horizont, Zyklus, …):
                # kein eigener Knoten, der Hop endet hier.
                knoten[key]["ende"] = True
                knoten[key]["abbruch"] = typ
                plan.append((kind, key, typ, True))
                continue
            sats = int(kind.get("amount_sats") or 0)
            eigen = typ in (TYP_EIGEN, TYP_HORIZONT)
            enkel = kind.get("children") or []
            ende = typ != TYP_EIGEN or not enkel
            neu(key, {
                "key": key,
                "typ": typ,
                "value_sats": sats,
                "y": 0.0,
                "wallet": kind.get("wallet") or "",
                "eigen": eigen,
                "ende": ende,
                "tiefe": tiefe + 1,
                "n": 0,
                **zeitfelder(output_zeit(kind, block_zeit)),
            })
            kante(key, eltern_key, 0.0, eigen)
            instanz[id(kind)] = (key, None)
            plan.append((kind, key, typ, False))
            if typ == TYP_EIGEN and enkel:
                schlange.append((kind, key, tiefe + 1))
        instanz[id(eltern)] = (eltern_key, ("kinder", plan, coinjoin))

    # 2) Lose von unten: jeder Hop gibt seinem Output FIFO (oder anteilig)
    #    Lose seiner Eingänge weiter. ``marke`` = Pfad der Schlüssel.
    def lose(inst: dict, sats: float) -> list[fifo_lots.Los]:
        key, plan = instanz[id(inst)]
        zeit_hop = knoten[key].get("time_ts")
        if plan is None:
            return [fifo_lots.Los(sats, zeit_hop, (), (key,))]
        if plan[0] == "buendel":
            bkey = plan[1]
            anteilig_keys.add(bkey)
            return [fifo_lots.Los(sats, knoten[bkey].get("time_ts"), (), (bkey, key))]
        echte = [(k, ck, typ) for k, ck, typ, marker in plan[1] if not marker]
        if not echte:
            return [fifo_lots.Los(sats, zeit_hop, (), (key,))]
        eingang = []
        for kind, _ck, _typ in echte:
            kind_lose = lose(kind, int(kind.get("amount_sats") or 0))
            # Ohne eigene Zeit: frühestens so alt wie dieser Hop (Obergrenze).
            eingang.append([
                l if l.zeit is not None else fifo_lots.Los(l.sats, zeit_hop, l.rang, l.marke)
                for l in kind_lose
            ])
        hop = _fifo_coinjoin_hop if plan[2] else _fifo_hop
        ergebnis = hop(fifo, key, int(sats), echte, eingang)
        if ergebnis is None:
            if len({l.zeit for kl in eingang for l in kl}) > 1:
                anteilig_keys.add(key)
            alle = [k for k, *_r in plan[1]]
            summe = sum(int(k.get("amount_sats") or 0) for k in alle)
            ergebnis = []
            for pos, ((kind, _ck, _typ), kind_lose) in enumerate(zip(echte, eingang)):
                c = int(kind.get("amount_sats") or 0)
                ziel = sats * c / summe if summe > 0 else sats / len(alle)
                ergebnis.extend(
                    fifo_lots.Los(l.sats, l.zeit, (pos,) + l.rang, l.marke)
                    for l in _skaliere(kind_lose, ziel)
                )
        return [fifo_lots.Los(l.sats, l.zeit, l.rang, l.marke + (key,)) for l in ergebnis]

    alt = sys.getrecursionlimit()
    sys.setrecursionlimit(max(alt, 4 * len(knoten) + 200))
    try:
        fokus_lose = lose(wurzel, float(fokus_sats))
    finally:
        sys.setrecursionlimit(alt)

    # 3) Anteile und Kanten aus den Pfaden der Lose.
    kanten: dict[tuple[str, str], float] = {}
    for l in fokus_lose:
        pfad = l.marke
        for k in set(pfad):
            knoten[k]["anteil_sats"] += l.sats
        for von, nach in zip(pfad, pfad[1:]):
            kanten[(von, nach)] = kanten.get((von, nach), 0.0) + l.sats
    knoten[fokus_key]["anteil_sats"] = float(fokus_sats)

    vorfahren = []
    for key in reihenfolge:
        eintrag = knoten[key]
        if key != fokus_key and eintrag["anteil_sats"] <= 0:
            continue
        if key != fokus_key:
            eintrag["y"] = y_aus_beitrag(skala, eintrag["anteil_sats"])
        eintrag["anteil_sats"] = int(round(eintrag["anteil_sats"]))
        vorfahren.append(eintrag)
    return {
        "fokus_key": fokus_key,
        "fokus_sats": fokus_sats,
        "vorfahren": vorfahren,
        "kanten": [
            {
                "von": von,
                "nach": nach,
                "sats": int(round(sats)),
                "eigen": bool(eigen_kante.get((von, nach))),
            }
            for (von, nach), sats in kanten.items()
        ],
        "gekappt": gekappt,
        # True: ein Hop mit Anteil am Fokus hat anteilig (pro rata) Lose
        # verschiedener Zeit gemischt oder ein Bündel trägt bei — die
        # Los-Daten des Fokus sind dann nicht FIFO-genau.
        "anteilig": any(
            knoten[k]["anteil_sats"] > 0 for k in anteilig_keys if k in knoten
        ),
    }


def _buendel(
    kinder, eltern_key, anteil, tiefe, fokus_sats, *,
    neu, kante, zeitfelder, skala, block_zeit,
) -> str:
    """Alle Eingänge eines Hops als ein Endknoten „n Eingänge“.

    Das Lot nimmt die jüngste bekannte Eingangszeit. Fehlt jede Zeit, bleibt
    der Knoten ohne Position und damit grau. Liefert den Bündel-Schlüssel.
    """
    anzahl = 0
    sats = 0
    eigen = False
    zeiten: list[datetime] = []
    for kind in kinder:
        if kind.get("type") == "external_unresolved":
            anzahl += int(kind.get("input_count") or 0)
            continue
        anzahl += 1
        sats += int(kind.get("amount_sats") or 0)
        eigen = eigen or _typ(kind) in (TYP_EIGEN, TYP_HORIZONT)
        zeit = output_zeit(kind, block_zeit)
        if zeit is not None:
            zeiten.append(zeit)
    key = f"buendel:{eltern_key}"
    # X: jüngste bekannte Output-Zeit im Bündel (die defensiv maßgebliche).
    felder = zeitfelder(max(zeiten) if zeiten else None)
    if zeiten:
        felder["zeit_von"] = min(zeiten).strftime("%d.%m.%Y %H:%M")
    neu(key, {
        "key": key,
        "typ": TYP_BUENDEL,
        "value_sats": sats,
        "y": y_aus_beitrag(skala, anteil),
        "wallet": "",
        "eigen": eigen,
        "ende": True,
        "tiefe": tiefe,
        "n": anzahl,
        **felder,
    }, anteil)
    kante(key, eltern_key, anteil, eigen)
    return key
