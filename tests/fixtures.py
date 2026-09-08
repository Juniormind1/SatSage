"""
Synthetische Testdaten.

Bewusst *nicht* aus immutable_cache/ kopiert: der Cache enthält Transaktionen
echter Wallets, und als Testdatei würde er die Wallet-Zuordnung dauerhaft
festschreiben. Alle Transaktionen hier sind erfunden; die XPUBs stammen aus
öffentlichen BIP-Spezifikationen.
"""
from embit.bip32 import HDKey

# --- Öffentliche Testvektoren --------------------------------------------

# BIP-84, Account 0 (Mnemonic "abandon … about") aus der Spezifikation.
BIP84_ZPUB = (
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtf"
    "SdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
)
BIP84_RECEIVE_0 = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
BIP84_RECEIVE_1 = "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g"
BIP84_CHANGE_0 = "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el"

# SLIP-132-Versionsbytes für die Prefix-Umwandlung
VERSION_XPUB = b"\x04\x88\xb2\x1e"
VERSION_YPUB = b"\x04\x9d\x7c\xb2"
VERSION_ZPUB = b"\x04\xb2\x47\x46"


def reencode_xpub(key: str, version: bytes) -> str:
    """Tauscht das SLIP-132-Versionsbyte — gleiches Schlüsselmaterial, anderer Prefix."""
    return HDKey.from_string(key).to_string(version=version)


#: Derselbe Schlüssel wie BIP84_ZPUB, exportiert mit generischem xpub-Prefix —
#: so verhalten sich Wallets, die SLIP-132 nicht umsetzen (z. B. Ledger Desktop).
#: Achtung: leitet dieselben Adressen ab wie BIP84_ZPUB und darf deshalb nicht
#: gleichzeitig mit diesem als zweites Wallet konfiguriert werden.
BIP84_AS_XPUB = reencode_xpub(BIP84_ZPUB, VERSION_XPUB)

#: Ein tatsächlich anderer Schlüssel (Kindschlüssel des Testvektors) — für
#: Tests, die zwei unterscheidbare Wallets brauchen.
ZWEITER_ZPUB = reencode_xpub(
    HDKey.from_string(BIP84_ZPUB).derive([9]).to_string(), VERSION_ZPUB
)
ZWEITER_ALS_XPUB = reencode_xpub(ZWEITER_ZPUB, VERSION_XPUB)


# --- Transaktionen --------------------------------------------------------

def txid(marker: str) -> str:
    """Erzeugt eine erkennbare, formal gültige TxID aus einem kurzen Kürzel."""
    return (marker * 64)[:64]


TXID_COINBASE = txid("c0")
TXID_EXTERN = txid("e1")
TXID_WALLET_IN = txid("a1")
TXID_SPEND = txid("b2")


def core_tx(
    tx_id: str,
    vin: list[dict],
    vout: list[dict],
    *,
    blocktime: int = 1_700_000_000,
    confirmations: int = 100,
) -> dict:
    """Transaktion im Bitcoin-Core-RPC-Format (Beträge als float BTC)."""
    return {
        "txid": tx_id,
        "hash": tx_id,
        "version": 2,
        "locktime": 0,
        "blockhash": txid("bb"),
        "blocktime": blocktime,
        "time": blocktime,
        "confirmations": confirmations,
        "vin": vin,
        "vout": vout,
    }


def core_vin(prev_txid: str, prev_vout: int) -> dict:
    return {
        "txid": prev_txid,
        "vout": prev_vout,
        "scriptSig": {"asm": "", "hex": ""},
        "txinwitness": ["00" * 32],
        "sequence": 4294967293,
    }


def core_vout(n: int, address: str, btc: float) -> dict:
    return {
        "n": n,
        "value": btc,
        "scriptPubKey": {
            "address": address,
            "asm": "",
            "hex": "",
            "desc": "",
            "type": "witness_v0_keyhash",
        },
    }


def esplora_tx(
    tx_id: str,
    vin: list[dict],
    vout: list[dict],
    *,
    block_height: int = 800_000,
    block_time: int = 1_700_000_000,
) -> dict:
    """Transaktion im Esplora-Format (Beträge als int Satoshis)."""
    return {
        "txid": tx_id,
        "version": 2,
        "locktime": 0,
        "vin": vin,
        "vout": vout,
        "status": {
            "confirmed": True,
            "block_height": block_height,
            "block_time": block_time,
        },
    }


def esplora_vin(prev_txid: str, prev_vout: int, address: str, sats: int) -> dict:
    return {
        "txid": prev_txid,
        "vout": prev_vout,
        "is_coinbase": False,
        "prevout": {"scriptpubkey_address": address, "value": sats},
    }


def esplora_vout(address: str, sats: int) -> dict:
    return {"scriptpubkey_address": address, "value": sats}


# --- Fertige Ketten -------------------------------------------------------

#: Adressen, die keinem der Testvektor-Wallets gehören.
EXTERN_A = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
EXTERN_B = "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3"


def simple_chain() -> dict[str, dict]:
    """
    Externer Zufluss → Wallet-Adresse → Ausgabe.

        TXID_EXTERN (extern)  →  TXID_WALLET_IN:0 (BIP84_RECEIVE_0)  →  TXID_SPEND
    """
    t_extern = core_tx(
        TXID_EXTERN,
        [core_vin(TXID_COINBASE, 0)],
        [core_vout(0, EXTERN_A, 1.0)],
        blocktime=1_690_000_000,
    )
    t_in = core_tx(
        TXID_WALLET_IN,
        [core_vin(TXID_EXTERN, 0)],
        [core_vout(0, BIP84_RECEIVE_0, 0.6), core_vout(1, EXTERN_B, 0.39)],
        blocktime=1_700_000_000,
    )
    t_spend = core_tx(
        TXID_SPEND,
        [core_vin(TXID_WALLET_IN, 0)],
        [core_vout(0, EXTERN_A, 0.59)],
        blocktime=1_710_000_000,
    )
    return {t["txid"]: t for t in (t_extern, t_in, t_spend)}


def cyclic_chain() -> dict[str, dict]:
    """Zwei Transaktionen, die sich gegenseitig als Vorgänger nennen."""
    a, b = txid("aa"), txid("bc")
    return {
        a: core_tx(a, [core_vin(b, 0)], [core_vout(0, BIP84_RECEIVE_0, 0.5)]),
        b: core_tx(b, [core_vin(a, 0)], [core_vout(0, EXTERN_A, 0.5)]),
    }


def make_get_tx(chain: dict[str, dict], *, counter: list | None = None):
    """Baut ein get_tx aus einer Kette; unbekannte TxIDs lösen KeyError aus."""

    def get_tx(tx_id: str) -> dict:
        if counter is not None:
            counter.append(tx_id)
        if tx_id not in chain:
            raise KeyError(f"Unbekannte Tx in der Testkette: {tx_id}")
        return chain[tx_id]

    return get_tx
