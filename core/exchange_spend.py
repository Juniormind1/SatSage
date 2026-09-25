"""
Börsenanteil einer Ausgabetransaktion.

„Bereits ausgegeben“ zeigt den eigenen Output, der das Wallet verlassen hat.
Davon ist nur der Teil an Kraken/Coinbase/… gegangen, dessen Zieladresse als
Börse bekannt ist. Gebühr, Wechselgeld und unbekannte Gegenparteien zählen
nicht mit. In einem CoinJoin ist eine fremde Börsenadresse kein eigenes Ziel.
"""
from __future__ import annotations

from core.tx_classify import COINJOIN_KINDS, _form_coinjoin_kind, _output_values_sats
from core.utxo_report import _extract_addresses


def _boerse_name(adresse: str) -> str:
    """Klarname aus Report oder Katalog, sonst leer."""
    a = (adresse or "").strip()
    if not a:
        return ""
    try:
        from core import exchange_reports as boerse

        hit = boerse.beschrifte_adresse(a)
        if hit and hit.get("kategorie") == "exchange":
            name = str(hit.get("name") or "").strip()
            if name:
                return name
    except Exception:
        pass
    try:
        import labels

        lab = labels.beschrifte(a)
        if lab and (
            lab.get("kategorie") == "exchange"
            or lab.get("kategorie_label") == "Börse"
        ):
            name = str(lab.get("name") or "").strip()
            if name and lab.get("benannt", True):
                return name
    except Exception:
        pass
    return ""


def ist_coinjoin_tx(tx: dict | None) -> bool:
    """Formheuristik ohne Eigentum — fremde Börsen-Outputs sind dann Rauschen."""
    if not isinstance(tx, dict):
        return False
    try:
        from core.tx_classify import form_coinjoin_kind_from_tx

        kind = form_coinjoin_kind_from_tx(tx)
    except Exception:
        kind = None
    if kind in COINJOIN_KINDS:
        return True
    values = _output_values_sats(tx)
    n_in = len(tx.get("vin") or [])
    n_out = len(tx.get("vout") or [])
    return _form_coinjoin_kind(n_in, n_out, values) in COINJOIN_KINDS


def ziele_aus_outputs(outputs: list[dict] | None) -> list[dict]:
    """
    Wie ``ziele_aus_tx``, aber aus schon gespeicherten ``{address, sats}``.

    Wechselgeld filtert der Aufrufer. Mehrere Adressen je Output gibt es hier
    nicht mehr — der Verlauf hat sie flach abgelegt.
    """
    summen: dict[str, int] = {}
    reihe: list[str] = []
    for eintrag in outputs or []:
        if not isinstance(eintrag, dict):
            continue
        addrs = eintrag.get("addresses")
        if not isinstance(addrs, list) or not addrs:
            einzeln = str(eintrag.get("address") or "")
            addrs = [einzeln] if einzeln else []
        namen = {_boerse_name(str(a or "")) for a in addrs}
        namen.discard("")
        # Multisig: nur wenn jede bekannte Adresse dieselbe Börse ist.
        if len(namen) != 1:
            continue
        name = namen.pop()
        try:
            sats = int(eintrag.get("sats") or 0)
        except (TypeError, ValueError):
            continue
        if sats <= 0:
            continue
        if name not in summen:
            reihe.append(name)
        summen[name] = summen.get(name, 0) + sats
    return [{"name": name, "sats": summen[name]} for name in reihe]


def ziele_aus_tx(tx: dict | None) -> list[dict]:
    """
    Fremde Outputs, deren Adresse als Börse bekannt ist.

    Rückgabe: ``[{"name": "Kraken", "sats": 15000000}, …]``, je Börse eine
    Summe, Reihenfolge des ersten Treffers. CoinJoin → leer (Adress-Treffer
    wäre nicht das eigene Ziel).
    """
    if not isinstance(tx, dict) or ist_coinjoin_tx(tx):
        return []
    summen: dict[str, int] = {}
    reihe: list[str] = []
    for vout in tx.get("vout") or []:
        if not isinstance(vout, dict):
            continue
        addrs = [a for a in _extract_addresses(vout) if a]
        if not addrs:
            continue
        # Ein Output, eine Gegenpartei. Mehrere Adressen (Multisig) nur, wenn
        # alle denselben Börsennamen tragen.
        namen = {_boerse_name(a) for a in addrs}
        namen.discard("")
        if len(namen) != 1:
            continue
        name = namen.pop()
        try:
            from core.utxo_report import _extract_value_sats

            sats = int(_extract_value_sats(vout))
        except (TypeError, ValueError):
            continue
        if sats <= 0:
            continue
        if name not in summen:
            reihe.append(name)
        summen[name] = summen.get(name, 0) + sats
    return [{"name": name, "sats": summen[name]} for name in reihe]


def ziele_aus_txid(txid: str) -> list[dict]:
    """
    Report kennt die Ausgaben-TxID, keine Output-Adresse.

    Ohne Betrag: der Report ersetzt die Output-Summe nicht. CoinJoin-Sonderfall
    entfällt — die TxID ist die eigene Einzahlung.
    """
    tid = (txid or "").strip().lower()
    if not tid:
        return []
    try:
        from core import exchange_reports as boerse

        hit = boerse.beschrifte_txid(tid)
    except Exception:
        return []
    if not hit or hit.get("kategorie") != "exchange":
        return []
    name = str(hit.get("name") or "").strip()
    if not name:
        return []
    return [{"name": name, "sats": None}]


def boerse_ziele(
    tx: dict | None = None,
    *,
    txid: str = "",
) -> list[dict]:
    """Adresse zuerst. TxID aus dem Report nur, wenn keine Output-Adresse trifft."""
    aus_tx = ziele_aus_tx(tx) if tx else []
    if aus_tx:
        return aus_tx
    return ziele_aus_txid(txid)
