"""
Selbstanzeige-Report: markierte Börsen-Einzahlungen mit walletbezogenem FiFo.

Keine Steuerberatung. V1: Veräußerungszeit = Chain-Zeit der Einzahlung;
Personendaten sind Platzhalter (Donald Duck), später über Einstellungen.
On-Chain ergänzt Börsenhistorien und Kaufbelege, ersetzt sie nicht.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

import main
from core import tax as tax_mod

#: Platzhalter bis Einstellungen existieren.
STEUER_PERSON = {
    "name": "Donald Duck",
    "steuernummer": "0/8/15",
    "anschrift": "Entenhausen",
}

HINWEIS_SELBSTANZEIGE = (
    "Diese Unterlage dient der Vorbereitung einer Selbstanzeige bzw. "
    "Nachmeldung. Sie ist keine Steuerberatung. Eine wirksame Selbstanzeige "
    "setzt Vollständigkeit für den betroffenen Zeitraum und die betroffenen "
    "Einkünfte voraus — fehlende Veräußerungen gefährden sie."
)

HINWEIS_FIFO = (
    "Verwendungsreihenfolge: walletbezogenes FiFo (älteste Anschaffungslose "
    "zuerst), vereinfachend aus dem lokalen Verlauf. Markierte Vorgänge "
    "werden in zeitlicher Reihenfolge verbraucht; nicht markierte Abgänge "
    "gelten hier nicht als Veräußerung und verbrauchen keine Lose."
)

HINWEIS_VERAEUSSERUNGSZEIT = (
    "Als Veräußerungszeitpunkt gilt in dieser Fassung die Blockzeit der "
    "on-chain-Einzahlung an die Börse. Ein späterer Trade auf der Börse "
    "kann der wirtschaftlich maßgebliche Zeitpunkt sein — ggf. belegen."
)

HINWEIS_HYPOTHESE = (
    "Hypothese „Was wäre wenn“: markierte offene UTXOs werden fiktiv zum "
    "Stichtag (Jahresende des Steuerjahres, bzw. heute wenn das Jahr noch "
    "läuft) als veräußert angenommen. Das ist keine tatsächliche Ausgabe — "
    "nur eine Durchrechnung der Haltedauer."
)


def hypothese_stichtag(jahr: int, *, jetzt: datetime | None = None) -> datetime:
    """Fiktive Veräußerungszeit für offene UTXOs."""
    jetzt = jetzt or datetime.now()
    if jahr < jetzt.year:
        return datetime(jahr, 12, 31, 23, 59, 59)
    if jahr > jetzt.year:
        return datetime(jahr, 12, 31, 23, 59, 59)
    return jetzt


def _utxo_schluessel(txid: str, vout: int) -> str:
    return f"utxo:{_norm_txid(txid)}:{int(vout)}"


def _parse_utxo_schluessel(wert: str) -> tuple[str, int] | None:
    text = (wert or "").strip()
    if text.startswith("utxo:"):
        text = text[5:]
    if ":" not in text:
        return None
    txid, _, rest = text.partition(":")
    try:
        return _norm_txid(txid), int(rest)
    except (TypeError, ValueError):
        return None


def _norm_txid(txid: str) -> str:
    text = (txid or "").strip()
    if not text:
        return ""
    return main._normalize_txid(text)


def _wallet_name(utxo: dict, wallet) -> str:
    adresse = utxo.get("address") or ""
    if wallet:
        name = wallet.resolve_address(adresse)
        if name:
            return name
    return "unbekannt"


def _anschaffung_los(
    utxo: dict,
    immutable_cache_dir: Path | None,
    *,
    anschaffung: str = tax_mod.STANDARD_ANSCHAFFUNG,
) -> tuple[datetime | None, str, bool, str]:
    """(zeit, grundlage, untergrenze, externe_adresse_oder_leer)."""
    ingress = None
    if immutable_cache_dir:
        ingress = main.load_utxo_ingress_cache(
            utxo.get("txid", ""), int(utxo.get("vout", 0)), immutable_cache_dir
        )
    zeit, grundlage, untergrenze, _fb = tax_mod._anschaffung(
        utxo, ingress, anschaffung=anschaffung,
    )
    ext_addr = ""
    if ingress:
        if tax_mod.parse_anschaffung(anschaffung) == tax_mod.ANSCHAFFUNG_AELTESTE:
            ext_addr = str(
                ingress.get("external_oldest_address")
                or ingress.get("external_address")
                or ""
            )
        else:
            ext_addr = str(ingress.get("external_address") or "")
    return zeit, grundlage, untergrenze, ext_addr


def _baue_lose(
    utxos: list[dict],
    wallet,
    immutable_cache_dir: Path | None,
    *,
    anschaffung: str = tax_mod.STANDARD_ANSCHAFFUNG,
) -> dict[str, list[dict]]:
    """
    Anschaffungslose je Wallet, FiFo-bereit (älteste zuerst).

    Jeder Verlaufs-/UTXO-Eintrag ist ein Empfang = ein Los zur Anschaffungszeit.
    """
    lose: dict[str, list[dict]] = {}
    for utxo in utxos:
        zeit, grundlage, untergrenze, ext_addr = _anschaffung_los(
            utxo, immutable_cache_dir, anschaffung=anschaffung,
        )
        if zeit is None:
            continue
        name = _wallet_name(utxo, wallet)
        sats = int(utxo.get("value", 0))
        if sats <= 0:
            continue
        lose.setdefault(name, []).append({
            "wallet": name,
            "txid": _norm_txid(utxo.get("txid", "")),
            "vout": int(utxo.get("vout", 0)),
            "address": utxo.get("address") or "",
            "external_address": ext_addr,
            "anschaffung": zeit,
            "sats": sats,
            "rest": sats,
            "grundlage": grundlage,
            "untergrenze": untergrenze,
        })
    for name in lose:
        lose[name].sort(key=lambda L: (L["anschaffung"], L["txid"], L["vout"]))
    return lose


def _netto_und_eigen(
    utxos: list[dict],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    netto, zurueck = tax_mod._abgang_je_transaktion(utxos)
    eingesetzt: dict[str, int] = {}
    for utxo in utxos:
        spender = utxo.get("spent_txid")
        if utxo.get("spent") and spender:
            eingesetzt[spender] = eingesetzt.get(spender, 0) + int(
                utxo.get("value", 0)
            )
    return netto, zurueck, eingesetzt


def _inputs_fuer_txid(utxos: list[dict], txid: str, wallet) -> list[dict]:
    ziel = _norm_txid(txid)
    inputs = []
    for utxo in utxos:
        if not utxo.get("spent"):
            continue
        if _norm_txid(utxo.get("spent_txid", "")) != ziel:
            continue
        inputs.append({
            "txid": _norm_txid(utxo.get("txid", "")),
            "vout": int(utxo.get("vout", 0)),
            "address": utxo.get("address") or "",
            "wallet": _wallet_name(utxo, wallet),
            "value_sats": int(utxo.get("value", 0)),
            "spent_time_ts": utxo.get("spent_time_ts"),
        })
    inputs.sort(key=lambda i: (i["wallet"], i["txid"], i["vout"]))
    return inputs


def _abfluss_zeit(utxos: list[dict], spender: str) -> datetime | None:
    stempel = None
    ziel = _norm_txid(spender)
    for utxo in utxos:
        if _norm_txid(utxo.get("spent_txid", "")) != ziel:
            continue
        ts = utxo.get("spent_time_ts")
        if ts and (stempel is None or int(ts) < stempel):
            stempel = int(ts)
    if stempel is None:
        return None
    try:
        return datetime.fromtimestamp(stempel)
    except (ValueError, OSError, OverflowError):
        return None


def _wallet_anteile(
    utxos: list[dict], spender: str, wallet
) -> dict[str, int]:
    """Einsatz je Wallet in der ausgebenden Tx."""
    ziel = _norm_txid(spender)
    anteile: dict[str, int] = {}
    for utxo in utxos:
        if _norm_txid(utxo.get("spent_txid", "")) != ziel:
            continue
        name = _wallet_name(utxo, wallet)
        anteile[name] = anteile.get(name, 0) + int(utxo.get("value", 0))
    return anteile


def _offene_utxos(utxos: list[dict]) -> list[dict]:
    """Unspent Einträge — für Hypothese „Was wäre wenn ich die ausgebe“."""
    offen = []
    gesehen: set[str] = set()
    for utxo in utxos:
        if utxo.get("spent"):
            continue
        sats = int(utxo.get("value", 0) or 0)
        if sats <= 0:
            continue
        txid = _norm_txid(utxo.get("txid", ""))
        if not txid:
            continue
        vout = int(utxo.get("vout", 0))
        key = f"{txid}:{vout}"
        if key in gesehen:
            continue
        gesehen.add(key)
        offen.append(utxo)
    return offen


def _hypothese_utxo_kandidaten(
    utxos: list[dict],
    jahr: int,
    *,
    wallet=None,
    immutable_cache_dir: Path | None = None,
) -> list[dict]:
    stichtag = hypothese_stichtag(jahr)
    liste = []
    for utxo in _offene_utxos(utxos):
        zeit, grundlage, untergrenze, ext_addr = _anschaffung_los(
            utxo, immutable_cache_dir
        )
        txid = _norm_txid(utxo.get("txid", ""))
        vout = int(utxo.get("vout", 0))
        name = _wallet_name(utxo, wallet)
        sats = int(utxo.get("value", 0))
        anschaffung = ""
        if zeit is not None:
            anschaffung = zeit.strftime("%d.%m.%Y")
        liste.append({
            "id": _utxo_schluessel(txid, vout),
            "txid": txid,
            "vout": vout,
            "address": utxo.get("address") or "",
            "wallet": name,
            "value_sats": sats,
            "anschaffung_datum": anschaffung,
            "external_address": ext_addr,
            "grundlage": tax_mod._grundlage_label(grundlage, untergrenze)
            if zeit is not None else "unbekannt",
            "stichtag": stichtag.strftime("%d.%m.%Y"),
            "stichtag_ts": int(stichtag.timestamp()),
            "hypothese": True,
            "ausgewaehlt": False,
        })
    liste.sort(key=lambda k: (
        -(k["value_sats"] or 0), k["wallet"], k["txid"], k["vout"],
    ))
    return liste


def _verlauf_ueberblick(utxos: list[dict], jahr: int) -> dict:
    """Kurzstatistik, ob/wieviel Verlaufsdaten im Jahr stecken."""
    jahresbeginn = datetime(jahr, 1, 1)
    jahresende = datetime(jahr, 12, 31, 23, 59, 59)
    empfang = 0
    abgang = 0
    hat_spent = False
    for utxo in utxos:
        if utxo.get("spent"):
            hat_spent = True
            wann = None
            ts = utxo.get("spent_time_ts")
            if ts:
                try:
                    wann = datetime.fromtimestamp(int(ts))
                except (ValueError, OSError, OverflowError):
                    wann = None
            if wann and jahresbeginn <= wann <= jahresende:
                abgang += 1
        status = utxo.get("status") or {}
        ts = status.get("block_time") or utxo.get("block_time")
        if ts:
            try:
                wann = datetime.fromtimestamp(int(ts))
            except (ValueError, OSError, OverflowError, TypeError):
                continue
            if jahresbeginn <= wann <= jahresende and not utxo.get("spent"):
                empfang += 1
            elif jahresbeginn <= wann <= jahresende:
                empfang += 1
    return {
        "vorhanden": hat_spent or any(
            not u.get("spent") and (u.get("status") or {}).get("block_time")
            for u in utxos
        ),
        "hat_ausgaben": hat_spent,
        "empfaenge_im_jahr": empfang,
        "abgaenge_im_jahr": abgang,
        "offen_utxos": len(_offene_utxos(utxos)),
    }


def kandidaten(
    utxos: list[dict],
    jahr: int,
    *,
    wallet=None,
    immutable_cache_dir: Path | None = None,
    txid: str | None = None,
) -> dict:
    """
    Auswahl für den Selbstanzeige-Report.

    *abfluesse*: Netto-Abgänge des Jahres (Verlauf).
    *utxos*: offene UTXOs als Hypothese „Was wäre wenn“.
    *verlauf*: Kurzüberblick, ob Verlaufsdaten da sind.
    """
    netto, zurueck, eingesetzt = _netto_und_eigen(utxos)
    jahresbeginn = datetime(jahr, 1, 1)
    jahresende = datetime(jahr, 12, 31, 23, 59, 59)
    hinweis_txid = _norm_txid(txid) if txid else ""

    liste = []
    for spender, betrag in sorted(netto.items(), key=lambda kv: kv[0]):
        wann = _abfluss_zeit(utxos, spender)
        if wann is None or not (jahresbeginn <= wann <= jahresende):
            continue
        eigen = tax_mod._ist_eigenuebertrag(
            eingesetzt.get(spender, 0), betrag, zurueck.get(spender, 0),
        )
        if betrag <= 0 and not eigen:
            continue
        inputs = _inputs_fuer_txid(utxos, spender, wallet)
        wallets = sorted({i["wallet"] for i in inputs})
        ausgewaehlt = bool(hinweis_txid and spender == hinweis_txid)
        liste.append({
            "id": spender,
            "txid": spender,
            "abgang_datum": wann.strftime("%d.%m.%Y"),
            "abgang_zeit": wann.strftime("%H:%M:%S"),
            "abgang_ts": int(wann.timestamp()),
            "netto_sats": max(0, betrag),
            "eigenuebertrag": eigen,
            "wallets": wallets,
            "input_count": len(inputs),
            "inputs": inputs if ausgewaehlt or hinweis_txid == spender else [],
            "ausgewaehlt": ausgewaehlt,
            "hypothese": False,
        })

    liste.sort(key=lambda k: k["abgang_ts"])
    hypothese = _hypothese_utxo_kandidaten(
        utxos, jahr, wallet=wallet, immutable_cache_dir=immutable_cache_dir,
    )
    return {
        "jahr": jahr,
        "txid_hinweis": hinweis_txid,
        "kandidaten": liste,
        "abfluesse": liste,
        "utxos": hypothese,
        "verlauf": _verlauf_ueberblick(utxos, jahr),
        "stichtag_hypothese": hypothese_stichtag(jahr).strftime("%d.%m.%Y"),
        "hinweise": [
            HINWEIS_SELBSTANZEIGE,
            tax_mod.HINWEIS_ONCHAIN,
            "Keine Vorauswahl: nur markierte Abflüsse bzw. Hypothese-UTXOs "
            "gehen in den Report.",
            HINWEIS_HYPOTHESE,
        ],
        "person": dict(STEUER_PERSON),
    }


def _fifo_verbrauch(
    lose_wallet: list[dict],
    menge: int,
    veraeusserung: datetime,
    haltefrist_jahre: int,
) -> tuple[list[dict], int]:
    """Verbraucht *menge* sats FiFo. Liefert (lose_zeilen, ungedeckt)."""
    rest = menge
    zeilen = []
    for los in lose_wallet:
        if rest <= 0:
            break
        if los["rest"] <= 0:
            continue
        if los["anschaffung"] > veraeusserung:
            continue
        nehmen = min(los["rest"], rest)
        los["rest"] -= nehmen
        rest -= nehmen
        frist_ende, erfuellt, _neu = tax_mod.haltefrist_entscheidung(
            los["anschaffung"], veraeusserung, haltefrist_jahre, None,
        )
        zeilen.append({
            "wallet": los["wallet"],
            "anschaffung_datum": los["anschaffung"].strftime("%d.%m.%Y"),
            "anschaffung_zeit": los["anschaffung"].strftime("%H:%M:%S"),
            "anschaffung_ts": int(los["anschaffung"].timestamp()),
            "sats": nehmen,
            "address": los["address"],
            "external_address": los["external_address"],
            "lot_txid": los["txid"],
            "lot_vout": los["vout"],
            "grundlage": tax_mod._grundlage_label(
                los["grundlage"], los["untergrenze"],
            ),
            "haltedauer_tage": max(
                0, (veraeusserung - los["anschaffung"]).days
            ),
            "frist_erfuellt": erfuellt,
            "frist_ende": (
                frist_ende.strftime("%d.%m.%Y") if frist_ende else ""
            ),
        })
    return zeilen, rest


def _vorgang_aus_abfluss(
    *,
    wann: datetime,
    spender: str,
    betrag: int,
    eigen: bool,
    utxos: list[dict],
    lose: dict[str, list[dict]],
    wallet,
    haltefrist_jahre: int,
    luecken: list[str],
) -> dict:
    anteile = _wallet_anteile(utxos, spender, wallet)
    einsatz_summe = sum(anteile.values()) or 1
    alle_lose: list[dict] = []
    ungedeckt = 0
    verteilt = 0
    items = sorted(anteile.items(), key=lambda kv: -kv[1])
    for i, (wname, einsatz) in enumerate(items):
        if i < len(items) - 1:
            teil = int(betrag * einsatz / einsatz_summe)
        else:
            teil = betrag - verteilt
        verteilt += teil
        if teil <= 0:
            continue
        zeilen, rest = _fifo_verbrauch(
            lose.get(wname, []), teil, wann, haltefrist_jahre,
        )
        alle_lose.extend(zeilen)
        ungedeckt += rest
        if rest:
            luecken.append(
                f"Wallet {wname}: {rest} sats der Tx {_norm_txid(spender)} "
                f"ohne FiFo-Los (Verlauf/Herkunft unvollständig)."
            )
    if eigen:
        luecken.append(
            f"Tx {_norm_txid(spender)} wirkt wie Eigenübertrag "
            f"(Netto {betrag} sats) — bitte Auswahl prüfen."
        )
    juengstes = (
        max(alle_lose, key=lambda z: z["anschaffung_ts"]) if alle_lose else None
    )
    return {
        "txid": _norm_txid(spender),
        "hypothese": False,
        "abgang_datum": wann.strftime("%d.%m.%Y"),
        "abgang_zeit": wann.strftime("%H:%M:%S"),
        "netto_sats": betrag,
        "eigenuebertrag": eigen,
        "wallets": sorted(anteile.keys()),
        "inputs": _inputs_fuer_txid(utxos, spender, wallet),
        "lose": alle_lose,
        "ungedeckt_sats": ungedeckt,
        "summe_juengstes_anschaffung_datum": (
            juengstes["anschaffung_datum"] if juengstes else ""
        ),
        "summe_juengstes_anschaffung_zeit": (
            juengstes["anschaffung_zeit"] if juengstes else ""
        ),
        "summe_juengstes_quelle": (
            (juengstes.get("external_address") or juengstes.get("address") or "")
            if juengstes else ""
        ),
        "summe_alle_lose_frist_erfuellt": (
            all(z["frist_erfuellt"] for z in alle_lose) if alle_lose else False
        ),
    }


def _vorgang_aus_hypothese_utxo(
    utxo: dict,
    *,
    stichtag: datetime,
    wallet,
    immutable_cache_dir: Path | None,
    haltefrist_jahre: int,
    anschaffung: str = tax_mod.STANDARD_ANSCHAFFUNG,
) -> dict:
    """Ein offener UTXO als fiktive Veräußerung zum Stichtag (eigene Anschaffung)."""
    zeit, grundlage, untergrenze, ext_addr = _anschaffung_los(
        utxo, immutable_cache_dir, anschaffung=anschaffung,
    )
    sats = int(utxo.get("value", 0))
    name = _wallet_name(utxo, wallet)
    txid = _norm_txid(utxo.get("txid", ""))
    vout = int(utxo.get("vout", 0))
    alle_lose: list[dict] = []
    ungedeckt = sats
    if zeit is not None and zeit <= stichtag:
        frist_ende, erfuellt, _neu = tax_mod.haltefrist_entscheidung(
            zeit, stichtag, haltefrist_jahre, None,
        )
        alle_lose.append({
            "wallet": name,
            "anschaffung_datum": zeit.strftime("%d.%m.%Y"),
            "anschaffung_zeit": zeit.strftime("%H:%M:%S"),
            "anschaffung_ts": int(zeit.timestamp()),
            "sats": sats,
            "address": utxo.get("address") or "",
            "external_address": ext_addr,
            "lot_txid": txid,
            "lot_vout": vout,
            "grundlage": tax_mod._grundlage_label(grundlage, untergrenze),
            "haltedauer_tage": max(0, (stichtag - zeit).days),
            "frist_erfuellt": erfuellt,
            "frist_ende": frist_ende.strftime("%d.%m.%Y") if frist_ende else "",
        })
        ungedeckt = 0
    juengstes = alle_lose[0] if alle_lose else None
    return {
        "txid": _utxo_schluessel(txid, vout),
        "hypothese": True,
        "abgang_datum": stichtag.strftime("%d.%m.%Y"),
        "abgang_zeit": stichtag.strftime("%H:%M:%S"),
        "netto_sats": sats,
        "eigenuebertrag": False,
        "wallets": [name],
        "inputs": [{
            "txid": txid,
            "vout": vout,
            "address": utxo.get("address") or "",
            "wallet": name,
            "value_sats": sats,
            "spent_time_ts": int(stichtag.timestamp()),
        }],
        "lose": alle_lose,
        "ungedeckt_sats": ungedeckt,
        "summe_juengstes_anschaffung_datum": (
            juengstes["anschaffung_datum"] if juengstes else ""
        ),
        "summe_juengstes_anschaffung_zeit": (
            juengstes["anschaffung_zeit"] if juengstes else ""
        ),
        "summe_juengstes_quelle": (
            (juengstes.get("external_address") or juengstes.get("address") or "")
            if juengstes else ""
        ),
        "summe_alle_lose_frist_erfuellt": (
            all(z["frist_erfuellt"] for z in alle_lose) if alle_lose else False
        ),
    }


def auswerten(
    utxos: list[dict],
    jahr: int,
    txids: list[str],
    *,
    haltefrist_jahre: int = 1,
    anschaffung: str = tax_mod.STANDARD_ANSCHAFFUNG,
    wallet=None,
    immutable_cache_dir: Path | None = None,
    utxo_keys: list[str] | None = None,
) -> dict:
    """
    Report für markierte Abfluss-TxIDs und/oder Hypothese-UTXOs.

    *utxo_keys*: ``txid:vout`` oder ``utxo:txid:vout`` — offene UTXOs,
    fiktiv zum Jahresende (bzw. heute) veräußert.

    *anschaffung*: wie ``tax.auswerten`` — ``juengste`` oder ``aelteste``.
    """
    modus = tax_mod.parse_anschaffung(anschaffung)
    gewaehlt = {_norm_txid(t) for t in txids if t and not str(t).startswith("utxo:")}
    # Auch irrtümlich in txids gelandete utxo:-Keys mitnehmen.
    roh_keys = list(utxo_keys or [])
    for t in txids or []:
        if str(t).startswith("utxo:"):
            roh_keys.append(str(t))
    hypothese_keys: list[tuple[str, int]] = []
    gesehen_h: set[str] = set()
    for roh in roh_keys:
        geparst = _parse_utxo_schluessel(roh)
        if not geparst:
            continue
        marke = f"{geparst[0]}:{geparst[1]}"
        if marke in gesehen_h:
            continue
        gesehen_h.add(marke)
        hypothese_keys.append(geparst)

    if not gewaehlt and not hypothese_keys:
        return {
            "jahr": jahr,
            "vorgaenge": [],
            "hinweise": [
                HINWEIS_SELBSTANZEIGE,
                tax_mod.HINWEIS_ONCHAIN,
                "Keine Transaktion und kein UTXO ausgewählt.",
            ],
            "person": dict(STEUER_PERSON),
            "erstellt": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "haltefrist_jahre": haltefrist_jahre,
            "methode": "FiFo (walletbezogen)",
        }

    netto, zurueck, eingesetzt = _netto_und_eigen(utxos)
    lose = _baue_lose(
        utxos, wallet, immutable_cache_dir, anschaffung=modus,
    )
    stichtag = hypothese_stichtag(jahr)

    vorgang_meta = []
    for spender in gewaehlt:
        wann = _abfluss_zeit(utxos, spender)
        if wann is None:
            continue
        betrag = netto.get(spender, 0)
        eigen = tax_mod._ist_eigenuebertrag(
            eingesetzt.get(spender, 0), betrag, zurueck.get(spender, 0),
        )
        vorgang_meta.append((wann, spender, max(0, betrag), eigen))
    vorgang_meta.sort(key=lambda x: x[0])

    vorgaenge = []
    hinweise = [
        HINWEIS_SELBSTANZEIGE,
        tax_mod.HINWEIS_ONCHAIN,
        HINWEIS_FIFO,
        HINWEIS_VERAEUSSERUNGSZEIT,
    ]
    if hypothese_keys:
        hinweise.append(HINWEIS_HYPOTHESE)
    luecken: list[str] = []

    for wann, spender, betrag, eigen in vorgang_meta:
        vorgaenge.append(_vorgang_aus_abfluss(
            wann=wann,
            spender=spender,
            betrag=betrag,
            eigen=eigen,
            utxos=utxos,
            lose=lose,
            wallet=wallet,
            haltefrist_jahre=haltefrist_jahre,
            luecken=luecken,
        ))

    index = {
        f"{_norm_txid(u.get('txid', ''))}:{int(u.get('vout', 0))}": u
        for u in _offene_utxos(utxos)
    }
    for txid, vout in sorted(hypothese_keys, key=lambda kv: kv):
        utxo = index.get(f"{txid}:{vout}")
        if utxo is None:
            luecken.append(
                f"Hypothese-UTXO {txid}:{vout} nicht (mehr) als offen gefunden."
            )
            continue
        vorgaenge.append(_vorgang_aus_hypothese_utxo(
            utxo,
            stichtag=stichtag,
            wallet=wallet,
            immutable_cache_dir=immutable_cache_dir,
            haltefrist_jahre=haltefrist_jahre,
            anschaffung=modus,
        ))

    if luecken:
        hinweise.extend(luecken)

    methode = "FiFo (walletbezogen)"
    if hypothese_keys and gewaehlt:
        methode = "FiFo (Abflüsse) + Hypothese offene UTXOs"
    elif hypothese_keys:
        methode = "Hypothese: offene UTXOs zum Stichtag"

    return {
        "jahr": jahr,
        "vorgaenge": vorgaenge,
        "hinweise": hinweise,
        "person": dict(STEUER_PERSON),
        "erstellt": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "haltefrist_jahre": haltefrist_jahre,
        "methode": methode,
        "ausgewaehlte_txids": sorted(gewaehlt),
        "ausgewaehlte_utxos": [
            f"{t}:{v}" for t, v in sorted(hypothese_keys)
        ],
        "stichtag_hypothese": stichtag.strftime("%d.%m.%Y"),
    }


def _btc(sats: int) -> str:
    return f"{sats / 1e8:.8f}".replace(".", ",")


def als_csv(report: dict) -> bytes:
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=";", quoting=csv.QUOTE_MINIMAL,
                   lineterminator="\r\n")
    person = report["person"]
    w.writerow(["Selbstanzeige-Report (Vorbereitung)"])
    w.writerow(["Name", person["name"]])
    w.writerow(["Steuernummer", person["steuernummer"]])
    w.writerow(["Anschrift", person["anschrift"]])
    w.writerow(["Steuerjahr", report["jahr"]])
    w.writerow(["Methode", report["methode"]])
    w.writerow(["Haltefrist Jahre", report["haltefrist_jahre"]])
    w.writerow(["Erstellt am", report["erstellt"]])
    w.writerow(["Quelle", "SatSage, lokale Blockchain-/Cache-Auswertung"])
    w.writerow([])
    for h in report["hinweise"]:
        w.writerow(["Hinweis", h])
    w.writerow([])

    for vg in report["vorgaenge"]:
        w.writerow([
            (
                "Vorgang Hypothese-UTXO"
                if vg.get("hypothese")
                else "Vorgang Einzahl-/Veräußerungs-Tx"
            ),
            vg["txid"],
        ])
        w.writerow([
            "Stichtag" if vg.get("hypothese") else "Einzahlung/Abgang Datum",
            vg["abgang_datum"],
            "Uhrzeit", vg["abgang_zeit"],
            "Netto sats", vg["netto_sats"],
            "Netto BTC", _btc(vg["netto_sats"]),
        ])
        w.writerow([
            "Summenzeile: jüngstes FiFo-Anschaffungsdatum der verbrauchten Lose",
            vg["summe_juengstes_anschaffung_datum"],
            vg["summe_juengstes_anschaffung_zeit"],
            "Quelle/Adresse",
            vg["summe_juengstes_quelle"],
            "Alle Lose außerhalb Haltefrist",
            "ja" if vg["summe_alle_lose_frist_erfuellt"] else "nein",
        ])
        w.writerow([
            "FiFo-Los Anschaffung", "Uhrzeit", "Wallet", "Adresse Empfang",
            "Externe Quelle", "Betrag BTC", "Betrag sats", "Haltedauer Tage",
            "Frist erfüllt", "Grundlage", "Los-TxID", "Los-Output",
        ])
        for los in vg["lose"]:
            w.writerow([
                los["anschaffung_datum"], los["anschaffung_zeit"],
                los["wallet"], los["address"], los["external_address"],
                _btc(los["sats"]), los["sats"], los["haltedauer_tage"],
                "ja" if los["frist_erfuellt"] else "nein",
                los["grundlage"], los["lot_txid"], los["lot_vout"],
            ])
        if vg["inputs"]:
            w.writerow([
                "On-Chain-Inputs der Einzahl-Tx", "Wallet", "Adresse",
                "Betrag sats", "Input-TxID", "Output",
            ])
            for inp in vg["inputs"]:
                w.writerow([
                    "",
                    inp["wallet"], inp["address"], inp["value_sats"],
                    inp["txid"], inp["vout"],
                ])
        w.writerow([])

    return b"\xef\xbb\xbf" + puffer.getvalue().encode("utf-8")


def als_html(report: dict) -> bytes:
    person = report["person"]
    esc = tax_mod._html_escape
    vorgang_html = []
    for vg in report["vorgaenge"]:
        los_zeilen = "".join(
            "<tr>"
            f"<td>{esc(los['anschaffung_datum'])} {esc(los['anschaffung_zeit'])}</td>"
            f"<td>{esc(los['wallet'])}</td>"
            f"<td class='mono voll'>{esc(los['address'])}</td>"
            f"<td class='mono voll'>{esc(los['external_address'] or '—')}</td>"
            f"<td class='r mono'>{_btc(los['sats'])}</td>"
            f"<td class='r'>{los['haltedauer_tage']}</td>"
            f"<td>{'ja' if los['frist_erfuellt'] else '<b>nein</b>'}</td>"
            f"<td class='klein'>{esc(los['grundlage'])}</td>"
            f"<td class='mono voll'>{esc(los['lot_txid'])}:{los['lot_vout']}</td>"
            "</tr>"
            for los in vg["lose"]
        )
        input_zeilen = "".join(
            "<tr>"
            f"<td>{esc(i['wallet'])}</td>"
            f"<td class='mono voll'>{esc(i['address'])}</td>"
            f"<td class='r'>{i['value_sats']}</td>"
            f"<td class='mono voll'>{esc(i['txid'])}:{i['vout']}</td>"
            "</tr>"
            for i in vg["inputs"]
        )
        titel = (
            "Hypothese: offener UTXO (fiktive Veräußerung)"
            if vg.get("hypothese")
            else "Einzahl-/Veräußerungs-Transaktion"
        )
        vorgang_html.append(f"""
<section class="vorgang">
  <h2>{esc(titel)}</h2>
  <p class="mono voll">{esc(vg['txid'])}</p>
  <p>
    {"Stichtag" if vg.get("hypothese") else "Abgang"}
    {esc(vg['abgang_datum'])} {esc(vg['abgang_zeit'])} ·
    Netto {_btc(vg['netto_sats'])} BTC ({vg['netto_sats']} sats) ·
    Wallets: {esc(', '.join(vg['wallets']) or '—')}
  </p>
  <p class="summe">
    <strong>Summenzeile (FiFo):</strong>
    Jüngstes Anschaffungsdatum der verbrauchten Lose:
    <strong>{esc(vg['summe_juengstes_anschaffung_datum'] or '—')}
    {esc(vg['summe_juengstes_anschaffung_zeit'])}</strong>
    · Quelle/Adresse:
    <span class="mono voll">{esc(vg['summe_juengstes_quelle'] or '—')}</span>
    · Alle Lose außerhalb Haltefrist:
    <strong>{'ja' if vg['summe_alle_lose_frist_erfuellt'] else 'nein'}</strong>
  </p>
  <h3>FiFo-Lose (Anschaffung → dieser Abgang)</h3>
  <table>
    <thead><tr>
      <th>Anschaffung</th><th>Wallet</th><th>Adresse Empfang</th>
      <th>Externe Quelle</th><th class="r">BTC</th><th class="r">Tage</th>
      <th>Frist</th><th>Grundlage</th><th>Los (Tx:vout)</th>
    </tr></thead>
    <tbody>{los_zeilen or '<tr><td colspan="9">Keine Lose zugeordnet.</td></tr>'}</tbody>
  </table>
  <h3>On-Chain-Inputs dieser Einzahl-Tx</h3>
  <table>
    <thead><tr>
      <th>Wallet</th><th>Adresse</th><th class="r">sats</th><th>Outpoint</th>
    </tr></thead>
    <tbody>{input_zeilen or '<tr><td colspan="4">Keine Inputs im Cache.</td></tr>'}</tbody>
  </table>
</section>
""")

    hinweise = "".join(f"<li>{esc(h)}</li>" for h in report["hinweise"])
    kopf_text = (
        f"{person['name']} · Steuernummer {person['steuernummer']} · "
        f"{person['anschrift']}"
    )
    fuss_text = (
        f"{person['name']} · {person['steuernummer']} · "
        f"Selbstanzeige-Report {report['jahr']}"
    )

    html = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<title>Selbstanzeige-Report {report['jahr']} — {esc(person['name'])}</title>
<style>
  body {{ font-family: Georgia, "Times New Roman", serif; color: #1a1a1a;
         max-width: 22cm; margin: 1.5cm auto; line-height: 1.45; }}
  h1 {{ font-size: 18pt; margin: 0 0 6pt; }}
  h2 {{ font-size: 13pt; margin: 22pt 0 6pt; }}
  h3 {{ font-size: 11pt; margin: 14pt 0 4pt; }}
  .unter, .klein {{ color: #444; font-size: 9pt; }}
  .summe {{ background: #f4f4f0; padding: 8pt 10pt; border-left: 3px solid #333; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 8.5pt; margin: 6pt 0 12pt; }}
  th {{ text-align: left; border-bottom: 1.5px solid #333; padding: 3pt 5pt 3pt 0;
        font-size: 7.5pt; text-transform: uppercase; letter-spacing: .04em; }}
  td {{ border-bottom: 1px solid #ddd; padding: 3pt 5pt 3pt 0; vertical-align: top; }}
  .r {{ text-align: right; }}
  .mono {{ font-family: "Courier New", Courier, monospace; }}
  .voll {{ word-break: break-all; overflow-wrap: anywhere; }}
  .stammdaten {{ margin: 0 0 16pt; font-size: 10pt; }}
  .stammdaten dt {{ font-weight: bold; float: left; width: 9em; clear: left; }}
  .stammdaten dd {{ margin: 0 0 2pt 9em; }}
  .hinweise {{ margin-top: 20pt; padding-top: 10pt; border-top: 1px solid #333;
               font-size: 8.5pt; color: #333; }}
  .bildschirm-kopf {{
    font-size: 9pt; color: #333; border-bottom: 1px solid #ccc;
    padding-bottom: 6pt; margin-bottom: 12pt;
  }}
  @media print {{
    body {{ margin: 0; max-width: none; }}
    .vorgang {{ page-break-inside: avoid; }}
    .bildschirm-kopf {{ display: none; }}
    @page {{
      margin: 2cm 1.5cm 2.2cm 1.5cm;
      @top-center {{
        content: "{esc(kopf_text)} · {esc(report['erstellt'])}";
        font-size: 8pt; color: #333;
      }}
      @bottom-center {{
        content: "{esc(fuss_text)} · Seite " counter(page);
        font-size: 8pt; color: #333;
      }}
    }}
  }}
</style></head><body>

<div class="bildschirm-kopf">{esc(kopf_text)} · erstellt {esc(report['erstellt'])}</div>

<h1>Selbstanzeige-Report (Vorbereitung)</h1>
<p class="unter">Steuerjahr {report['jahr']} · {esc(report['methode'])} ·
Haltefrist {report['haltefrist_jahre']} Jahr(e) · erstellt {esc(report['erstellt'])}</p>

<dl class="stammdaten">
  <dt>Name</dt><dd>{esc(person['name'])}</dd>
  <dt>Steuernummer</dt><dd>{esc(person['steuernummer'])}</dd>
  <dt>Anschrift</dt><dd>{esc(person['anschrift'])}</dd>
</dl>

{''.join(vorgang_html) if vorgang_html else '<p>Keine Vorgänge ausgewählt.</p>'}

<div class="hinweise"><ul>{hinweise}</ul>
<p>Erzeugt mit SatSage aus lokal vorliegenden Wallet-/Cache-Daten.
TxIDs und Adressen sind vollständig angegeben. PDF: Im Browser
„Drucken → Als PDF sichern“ (Kopf-/Fußzeile mit Seitenzahl erscheinen im Druck).</p></div>

</body></html>
"""
    return html.encode("utf-8")
