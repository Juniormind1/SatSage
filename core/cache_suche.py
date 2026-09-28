"""
Gesamten UTXO- und Verlaufs-Cache durchsuchen.

Dieselbe Grammatik wie der Kopf-Filter (``listen_fenster.parse_filter`` /
``Fenster.blatt_ok``): Freitext, Betrag, Datum. Der Suchraum ist der Cache
aller Wallets, Bestand und bereits ausgegeben — nicht die gezeichnete Seite
und nicht ein noch nicht gebauter Herkunftsbaum.
"""
from __future__ import annotations

from typing import Callable

from core import listen_fenster as lf


def suche_cache(
    *,
    eintraege,
    roh: str,
    lang: str,
    lade_bestand: Callable,
    lade_verlauf: Callable,
    anreichere_bestand: Callable[[dict], dict],
    anreichere_verlauf: Callable[[dict], dict],
    nach_ts=None,
    vor_ts=None,
    on_progress: Callable[[str], None] | None = None,
    raise_if_cancelled: Callable[[], None] | None = None,
) -> dict:
    """
    Liefert ``{q, total, bestand, verlauf, treffer}``.

    *eintraege*: Wallets mit ``display_name`` und ``wallet_id()``.
    *lade_*: ``(analyse_schluessel) -> list[dict] | None``.
    """
    filt = lf.parse_filter(roh, nach_ts=nach_ts, vor_ts=vor_ts)
    if filt["leer"]:
        return {"q": "", "total": 0, "bestand": 0, "verlauf": 0, "treffer": []}

    fenster_bestand = lf.Fenster(anreichere_bestand, lang=lang)
    fenster_verlauf = lf.Fenster(anreichere_verlauf, lang=lang)
    treffer: list[dict] = []
    gezaehlt = {"bestand": 0, "verlauf": 0}
    wallets = list(eintraege or [])
    gesamt = max(1, len(wallets))

    def brich():
        if raise_if_cancelled:
            raise_if_cancelled()

    def melde(text: str) -> None:
        if on_progress:
            on_progress(text)

    for nummer, eintrag in enumerate(wallets, start=1):
        brich()
        name = str(getattr(eintrag, "display_name", "") or "")
        melde(f"Durchsuche {name} ({nummer}/{gesamt})…")
        schluessel = eintrag.analyse_schluessel
        wallet_id = eintrag.wallet_id()
        for teil, lade, fenster in (
            ("bestand", lade_bestand, fenster_bestand),
            ("verlauf", lade_verlauf, fenster_verlauf),
        ):
            brich()
            roh_liste = lade(schluessel) or []
            for e in roh_liste:
                if not isinstance(e, dict):
                    continue
                gezaehlt[teil] += 1
                if name and not e.get("_wallet_fallback"):
                    e = dict(e)
                    e["_wallet_fallback"] = name
                if not fenster.blatt_ok(e, filt):
                    continue
                voll = fenster.fertig(e)
                treffer.append(_treffer(voll, teil, wallet_id, name))
            # Langer Cache: Abbruch nicht erst am nächsten Wallet.
            if len(roh_liste) > 200:
                brich()

    treffer.sort(key=lambda t: int(t.get("value_sats") or 0), reverse=True)
    return {
        "q": str(roh or "").strip(),
        "total": len(treffer),
        "bestand": gezaehlt["bestand"],
        "verlauf": gezaehlt["verlauf"],
        "treffer": treffer,
    }


def _treffer(voll: dict, teil: str, wallet_id: str, wallet_name: str) -> dict:
    sats = int(voll.get("value_sats") or 0)
    return {
        "teil": teil,
        "key": str(voll.get("key") or ""),
        "txid": str(voll.get("txid") or ""),
        "vout": int(voll.get("vout") or 0),
        "address": str(voll.get("address") or ""),
        "value_sats": sats,
        "wallet": str(voll.get("wallet") or wallet_name or ""),
        "wallet_id": wallet_id,
        "time_label": str(voll.get("time_label") or ""),
        "spent": bool(voll.get("spent")),
    }
