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


# ---------------------------------------------------------------------------
# Zieladresse fürs FIFO-Spend (PSBT): Format, Netz, Eigentum
# ---------------------------------------------------------------------------


def aktuelles_adress_netz() -> str:
    """
    Name des Adress-Netzes, in dem SatSage gerade läuft (``main``, ``test``,
    ``regtest``, ``signet``).

    Wird bei jedem Aufruf gelesen — ``main.set_chain_network`` setzt das Netz
    zur Laufzeit (``core.derivation._CHAIN_NETWORK``), nicht beim Import.
    """
    import core.derivation as _derivation
    from embit.networks import NETWORKS

    # ``chain_network()`` ist der Laufzeit-Zugriff; ohne ihn das Modul-Attribut.
    zugriff = getattr(_derivation, "chain_network", None)
    netz = zugriff() if callable(zugriff) else getattr(_derivation, "_CHAIN_NETWORK", None)
    if netz is None:
        return "main"
    for name, werte in NETWORKS.items():
        if werte is netz:
            return name
    for name, werte in NETWORKS.items():
        if werte == netz:
            return name
    return "main"


def adress_merkmale(adresse: str) -> dict | None:
    """
    Kodierung und mögliche Netze einer Adresse, ohne Chain-Lookup.

    ``art`` ist ``bech32`` (SegWit v0), ``bech32m`` (v1+, z. B. Taproot) oder
    ``base58`` (Legacy/Nested). ``netze`` sind die embit-Netznamen, zu denen
    Präfix bzw. Versionsbyte passen (``tb``/``m…``/``2…`` teilen sich Testnet,
    Signet und — bei Base58 — Regtest). None, wenn die Prüfsumme oder die
    Form nicht stimmt (auch bech32 statt bech32m und umgekehrt).
    """
    from embit import base58, bech32
    from embit.networks import NETWORKS

    roh = str(adresse or "").strip()
    if not roh:
        return None
    klein = roh.lower()
    if roh in (klein, roh.upper()) and "1" in klein:
        _, hrp, _ = bech32.bech32_decode(klein)
        if hrp is not None:
            witver, programm = bech32.decode(hrp, klein)
            if witver is None or programm is None:
                return None
            netze = [n for n, w in NETWORKS.items() if w["bech32"] == hrp]
            if not netze:
                return None
            return {
                "art": "bech32" if witver == 0 else "bech32m",
                "witness_version": int(witver),
                "netze": netze,
            }
    try:
        roh_bytes = base58.decode_check(roh)
    except Exception:
        return None
    if len(roh_bytes) != 21:
        return None
    version = roh_bytes[:1]
    netze = [
        n for n, w in NETWORKS.items() if version in (w["p2pkh"], w["p2sh"])
    ]
    if not netze:
        return None
    typ = "p2pkh" if any(NETWORKS[n]["p2pkh"] == version for n in netze) else "p2sh"
    return {"art": "base58", "typ": typ, "netze": netze}


def pruefe_zieladresse(wallet: Any, text: str, netz: str | None = None) -> dict:
    """
    Zieladresse für die PSBT: gültig, im laufenden Netz, eigenes Wallet?

    ``status``:

    - ``ungueltig`` — keine Adresse (Zeichen, Prüfsumme, bech32/bech32m).
    - ``falsches_netz`` — gültig, aber für ein anderes Netz (z. B. ``bc1…``
      im Regtest); ``adress_netze`` nennt die passenden Netze.
    - ``meine`` — gehört zu einem hinterlegten Wallet (Empfang oder Wechsel,
      innerhalb der abgeleiteten Tiefe bzw. Trace-Suchtiefe); ``wallet`` ist
      der Anzeigename.
    - ``fremd`` — gültig im laufenden Netz, aber in keinem Wallet.
    - ``keine_wallets`` — gültig im laufenden Netz, kein Wallet hinterlegt.

    Die Antwort trägt nie xpub, Deskriptor, Pfad oder Index — nur Status,
    Adresse, Kodierung, Netz und Wallet-Namen.
    """
    netz_name = netz or aktuelles_adress_netz()
    adresse = bereinige_bitcoin_adresse(text)
    merkmale = adress_merkmale(adresse) if adresse else None
    if not adresse or not merkmale:
        return {"status": "ungueltig", "netz": netz_name}
    basis = {"address": adresse, "art": merkmale["art"], "netz": netz_name}
    if netz_name not in merkmale["netze"]:
        return {**basis, "status": "falsches_netz", "adress_netze": list(merkmale["netze"])}
    if wallet is None or not getattr(wallet, "xpubs", None):
        return {**basis, "status": "keine_wallets"}
    name = wallet.resolve_address(adresse)
    if name:
        return {**basis, "status": "meine", "wallet": str(name)}
    return {**basis, "status": "fremd"}
