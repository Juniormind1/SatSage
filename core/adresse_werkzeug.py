"""Prüft, ob eine Bitcoin-Adresse zu einem konfigurierten Wallet gehört.

Ableitung aus den hinterlegten Schlüsseln — nicht der UTXO-Bestand und nicht
der Verlauf. Eine Adresse zählt auch, wenn noch nie sats darauf lagen.
"""
from __future__ import annotations

from typing import Any

from embit.script import address_to_scriptpubkey


_BECH32_ANFAENGE = ("bc1", "tb1", "bcrt1")


def bereinige_bitcoin_adresse(text: str) -> str | None:
    """
    Leerzeichen weg, ``bitcoin:``-URI abstreifen, Bech32 kleinschreiben.

    None, wenn der Text keine Adresse ist, die embit liest (Legacy, Nested,
    SegWit, Taproot).
    """
    roh = "".join(str(text or "").split())
    if not roh:
        return None
    if roh.lower().startswith("bitcoin:"):
        roh = roh.split(":", 1)[1]
        roh = roh.split("?", 1)[0].split("&", 1)[0]
        roh = "".join(roh.split())
    if not roh:
        return None
    if roh.lower().startswith(_BECH32_ANFAENGE):
        roh = roh.lower()
    try:
        address_to_scriptpubkey(roh)
    except Exception:
        return None
    return roh


def pruefe_eigene_adresse(wallet: Any, text: str) -> dict:
    """
    Ordnet eine Adresse einem Wallet zu — oder stellt fest, dass sie fremd ist.

    ``status`` ist ``ungueltig``, ``keine_wallets``, ``meine`` oder ``fremd``.
    Bei ``meine`` steht der Anzeigename in ``wallet``. Die Suche ist dieselbe
    wie überall sonst (``WalletContext.resolve_address``): vorabgeleitete
    Adressen der konfigurierten Tiefe, darüber die Trace-Suchtiefe. Kein
    Chain-Lookup.
    """
    adresse = bereinige_bitcoin_adresse(text)
    if not adresse:
        return {"status": "ungueltig"}
    if wallet is None or not getattr(wallet, "xpubs", None):
        return {"status": "keine_wallets", "address": adresse}
    name = wallet.resolve_address(adresse)
    if name:
        return {"status": "meine", "wallet": name, "address": adresse}
    return {"status": "fremd", "address": adresse}
