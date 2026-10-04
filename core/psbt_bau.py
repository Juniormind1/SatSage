"""
Unsignierte PSBT (BIP174, Version 0) fürs FIFO-Spend — reine Logik.

Kein Netz, kein HTTP, kein Schlüsselmaterial außer öffentlichen Schlüsseln:
Inputs, Ziel, Wechselgeld-Adresse, Roh-Transaktionen und Blockhöhe kommen
vom Aufrufer (``httpserver/api/psbt.py``), die Coin-Auswahl aus
``core/coin_auswahl.py``.

Festlegungen (Maintainer-Auftrag 2026-10-04, ISSUES „FIFO-Spend (PSBT)“):

- **nSequence** ``0xfffffffd`` an jedem Input: RBF signalisiert (BIP125),
  nLockTime ist wirksam.
- **nLockTime** = aktuelle Blockhöhe (Anti-Fee-Sniping wie Bitcoin Core und
  Electrum): Die Tx ist ab dem nächsten Block gültig, ein Miner kann sie
  nicht in einen Reorg der Spitze ziehen. Ohne bekannte Höhe 0. Keine
  Zufalls-Rückdatierung (Core zieht in 10 % der Fälle bis 100 Blöcke ab) —
  bewusst einfach, im Lab reproduzierbar.
- **Inputs**: ``witness_utxo`` für SegWit (P2WPKH, P2SH-P2WPKH), dazu
  ``non_witness_utxo`` (ganze Vorgänger-Tx) für jeden Input, wenn verfügbar —
  bei Legacy Pflicht; bei SegWit v0 verlangen Hardware-Wallets sie seit der
  Segwit-Gebührenlücke (2020). ``redeem_script`` bei P2SH-P2WPKH.
- **bip32_derivation** (Fingerprint + voller Pfad) an jedem Input und am
  Wechselgeld-Output, dazu ``PSBT_GLOBAL_XPUB``. Fingerprint/Pfad-Präfix
  aus dem Key-Origin eines Deskriptors (``[fp/84h/1h/0h]…``); ohne Origin
  der Fingerprint des XPUB selbst mit Pfad relativ zum XPUB (``m/<change>/<i>``)
  — Electrum prüft genau diesen „Zwischen-Fingerprint“, Core signiert über
  das Skript; Hardware-Wallets brauchen den echten Origin. ``GLOBAL_XPUB``
  nur mit echtem Origin (Tiefe = Pfadlänge, sonst lehnt Electrum ab).
- **Outputs**: Ziel und Wechselgeld in zufälliger Reihenfolge (keine feste
  Wechselgeld-Position); Inputs in der Auswahl-Reihenfolge (älteste zuerst).
- Gebühr = ``ceil(milli · vsize / 1000)`` mit der vsize aus den echten
  Input-/Output-Skripten (Signatur 72 Byte angenommen — die signierte Tx ist
  höchstens so groß, die effektive Rate also ≥ der gewählten).

Multisig (``MultisigPolitik``): ``wsh(sortedmulti|multi(…))`` und
``sh(wsh(…))`` aus ``WALLET_n_DESC`` mit ``/<0;1>/*`` je Cosigner. Je Input
und am Wechselgeld ``witness_script`` (bei ``sh-wsh`` dazu
``redeem_script``), ``bip32_derivation`` für **jeden** Cosigner-Schlüssel
(Fingerprint + voller Pfad aus dem Key-Origin), ``PSBT_GLOBAL_XPUB`` je
Cosigner mit echtem Origin, ``witness_utxo`` + ``non_witness_utxo``.
vsize M-von-N siehe ``multisig_input_vbytes``. Signiert wird je Cosigner,
danach combine → finalize (beim Nutzer, nicht in SatSage).

Taproot (auch ``multi_a``) und Miniscript-Policies: noch nicht.
"""
from __future__ import annotations

import base64
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Iterable

from embit import script as escript
from embit.bip32 import HDKey
from embit.psbt import PSBT, DerivationPath
from embit.transaction import Transaction, TransactionInput, TransactionOutput

#: nSequence: RBF an, nLockTime wirksam (BIP125).
RBF_SEQUENCE = 0xFFFFFFFD

#: Transaktions-Version (BIP68-fähig, wie Core/Electrum).
TX_VERSION = 2

#: Skripttypen (``core.derivation.normalize_script_type``), die gebaut werden.
UNTERSTUETZTE_SKRIPTE = ("segwit", "nested", "legacy")

#: vbytes je Input inkl. 72-Byte-Signatur (obere Grenze).
VBYTES_INPUT_NACH_TYP = {"segwit": 68, "nested": 91, "legacy": 148}

#: BIP32: gehärteter Index.
GEHAERTET = 0x80000000


class PsbtFehler(ValueError):
    """Ein Baustein passt nicht (Skript, Betrag, Roh-Tx) — nichts wird gebaut."""


@dataclass(frozen=True)
class Herkunft:
    """Key-Origin des Konto-XPUB: Fingerprint und Pfad-Präfix."""

    fingerprint: bytes
    pfad: tuple[int, ...]
    #: ``deskriptor`` (Root-Fingerprint aus dem Key-Origin) oder ``xpub``
    #: (Fingerprint des XPUB selbst, Pfad relativ).
    quelle: str

    @property
    def fingerprint_hex(self) -> str:
        return self.fingerprint.hex()

    def pfad_text(self, *rest: int) -> str:
        teile = ["m"]
        for i in (*self.pfad, *rest):
            teile.append(f"{i - GEHAERTET}h" if i >= GEHAERTET else str(i))
        return "/".join(teile)


def herkunft_fuer(xpub: str, descriptor: str = "") -> Herkunft:
    """
    Fingerprint und Pfad-Präfix für die bip32_derivation.

    1. Deskriptor mit Key-Origin ``[fp/…]`` → Root-Fingerprint + voller Pfad.
    2. Sonst: Fingerprint des XPUB (``hash160(pubkey)[:4]``), Präfix leer.
       Ein nackter XPUB trägt nur den Fingerprint seines *Elternschlüssels*
       und die letzte Index-Stufe — der Master-Fingerprint ist daraus nicht
       zu gewinnen.
    """
    if descriptor:
        try:
            from core.derivation import parse_deskriptor

            desc = parse_deskriptor(descriptor)
            schluessel = list(desc.keys) if desc is not None else []
            if len(schluessel) == 1 and getattr(schluessel[0], "origin", None) is not None:
                origin = schluessel[0].origin
                return Herkunft(bytes(origin.fingerprint), tuple(origin.derivation), "deskriptor")
        except Exception:
            pass
    hd = HDKey.from_string(xpub)
    return Herkunft(bytes(hd.my_fingerprint), (), "xpub")


def skript_fuer(pubkey, typ: str):
    """scriptPubKey für einen öffentlichen Schlüssel im Skripttyp *typ*."""
    if typ == "segwit":
        return escript.p2wpkh(pubkey)
    if typ == "nested":
        return escript.p2sh(escript.p2wpkh(pubkey))
    if typ == "legacy":
        return escript.p2pkh(pubkey)
    raise PsbtFehler(f"Skripttyp {typ!r} wird für PSBTs nicht unterstützt.")


def ableiten(hd: HDKey, typ: str, change: int, index: int):
    """(öffentlicher Schlüssel, scriptPubKey) an ``change/index``."""
    kind = hd.derive([change, index])
    return kind.key, skript_fuer(kind.key, typ)


def output_vbytes(spk: bytes) -> int:
    """8 Byte Betrag + Längen-Varint + Skript."""
    n = len(spk)
    return 8 + (1 if n < 253 else 3) + n


def vsize_tx(input_typen: Iterable[str | float], output_spks: Iterable[bytes]) -> int:
    """
    Obere Grenze der vsize (72-Byte-Signaturen).

    *input_typen*: Skripttyp je Input (``segwit``/``nested``/``legacy``) oder
    die vbytes als Zahl (Multisig, ``MultisigPolitik.input_vb``; immer SegWit).
    """
    typen = list(input_typen)
    spks = list(output_spks)
    segwit = any(not isinstance(t, str) or t in ("segwit", "nested") for t in typen)
    roh = 10 + (0.5 if segwit else 0)
    if len(typen) >= 253:
        roh += 2
    roh += sum(VBYTES_INPUT_NACH_TYP[t] if isinstance(t, str) else float(t) for t in typen)
    roh += sum(output_vbytes(s) for s in spks)
    return int(math.ceil(roh))


def gebuehr_fuer(milli: int, vsize: int) -> int:
    return -(-int(milli) * int(vsize) // 1000)


class Pfade:
    """
    Adresse → (change, index) für ein XPUB, lazy bis *max_index* je Kette.

    *hd* ist der Konto-XPUB (Single-Sig, Skript nach *typ*) oder eine
    ``MultisigPolitik`` (Skript aus dem Deskriptor, *typ* wird ignoriert).
    """

    def __init__(self, hd: HDKey, typ: str, netz, max_index: int):
        self.hd = hd
        self.typ = typ
        self.netz = netz
        self.max_index = max(1, int(max_index))
        self._karte: dict[str, tuple[int, int]] = {}
        self._bis = {0: 0, 1: 0}

    def adresse(self, change: int, index: int) -> str:
        if isinstance(self.hd, MultisigPolitik):
            spk = self.hd.ableiten(change, index).spk
        else:
            _, spk = ableiten(self.hd, self.typ, change, index)
        return spk.address(self.netz) if self.netz is not None else spk.address()

    def _bis_index(self, change: int, ende: int) -> None:
        ende = min(ende, self.max_index)
        for i in range(self._bis[change], ende):
            self._karte.setdefault(self.adresse(change, i), (change, i))
        self._bis[change] = max(self._bis[change], ende)

    def finde(self, adresse: str) -> tuple[int, int] | None:
        if adresse in self._karte:
            return self._karte[adresse]
        schritt = 200
        while self._bis[0] < self.max_index or self._bis[1] < self.max_index:
            for change in (0, 1):
                self._bis_index(change, self._bis[change] + schritt)
            if adresse in self._karte:
                return self._karte[adresse]
        return None


def naechster_wechsel_index(
    pfade: Pfade,
    bekannte_adressen: Iterable[str],
    *,
    hat_history: Callable[[str], bool] | None = None,
    gap: int = 20,
    ausser: Iterable[str] = (),
) -> int:
    """
    Nächster unbenutzter interner Index (``/1/*``).

    Schätzung: höchster bekannter Wechsel-Index (UTXO-/Verlaufs-Cache) + 1.
    Mit *hat_history* (eigener Electrum-Server) nur vorwärts prüfen, bis die
    erste Adresse ohne Verlauf kommt — höchstens *gap* + 1 Abfragen.
    *ausser*: Adressen, die nicht in Frage kommen (z. B. das Ziel).
    """
    hoechster = -1
    for adresse in bekannte_adressen or ():
        treffer = pfade.finde(str(adresse))
        if treffer and treffer[0] == 1:
            hoechster = max(hoechster, treffer[1])
    gesperrt = {str(a) for a in ausser or ()}
    start = hoechster + 1
    for i in range(start, min(pfade.max_index, start + gap + 1)):
        adresse = pfade.adresse(1, i)
        if adresse in gesperrt:
            continue
        if hat_history is not None and hat_history(adresse):
            continue
        return i
    raise PsbtFehler("Keine unbenutzte Wechseladresse innerhalb der Scan-Tiefe.")


def pruefe_roh_tx(roh: bytes, txid: str, vout: int, wert: int, spk: bytes) -> Transaction:
    """Vorgänger-Tx passt zu ``txid:vout``, Betrag und Skript — sonst ``PsbtFehler``."""
    try:
        tx = Transaction.parse(roh)
    except Exception as exc:
        raise PsbtFehler(f"Vorgänger-Tx {txid} nicht lesbar: {exc}") from None
    if tx.txid().hex() != txid:
        raise PsbtFehler(f"Vorgänger-Tx {txid}: TxID stimmt nicht.")
    if vout >= len(tx.vout):
        raise PsbtFehler(f"{txid}:{vout} existiert nicht.")
    aus = tx.vout[vout]
    if int(aus.value) != int(wert):
        raise PsbtFehler(f"{txid}:{vout}: Betrag {aus.value} statt {wert}.")
    if aus.script_pubkey.data != spk:
        raise PsbtFehler(f"{txid}:{vout}: Skript gehört nicht zu diesem Wallet.")
    return tx


@dataclass
class Eingang:
    txid: str
    vout: int
    wert: int
    change: int
    index: int
    #: Ganze Vorgänger-Tx (roh); Pflicht bei Legacy.
    roh_tx: bytes | None = None


@dataclass
class Ausgang:
    spk: bytes
    wert: int
    rolle: str  # ziel | wechsel
    #: (change, index) beim Wechselgeld.
    pfad: tuple[int, int] | None = None
    extra: dict = field(default_factory=dict)


def baue_psbt(
    *,
    xpub: str,
    typ: str,
    herkunft: Herkunft,
    eingaenge: list[Eingang],
    ausgaenge: list[Ausgang],
    locktime: int = 0,
    rng: random.Random | None = None,
    multisig: "MultisigPolitik | None" = None,
) -> tuple[PSBT, list[Ausgang]]:
    """
    PSBT v0 bauen. Rückgabe: (PSBT, Ausgänge in Tx-Reihenfolge).

    Prüft jede Vorgänger-Tx gegen Betrag und abgeleitetes Skript; der
    Wechselgeld-Output muss ein eigenes internes Skript sein.

    Mit *multisig* kommen Skripte und Schlüssel aus dem Deskriptor
    (*xpub*, *typ* und *herkunft* werden ignoriert).
    """
    if multisig is not None:
        typ = multisig.typ
        hd = None
    elif typ not in UNTERSTUETZTE_SKRIPTE:
        raise PsbtFehler(f"Skripttyp {typ!r} wird für PSBTs nicht unterstützt.")
    if not eingaenge or not ausgaenge:
        raise PsbtFehler("PSBT ohne Inputs oder Outputs.")
    if multisig is None:
        hd = HDKey.from_string(xpub)
        if hd.is_private:
            raise PsbtFehler("Privater Schlüssel — SatSage baut nur aus öffentlichen.")
    locktime = int(locktime or 0)
    if not 0 <= locktime < 500_000_000:
        raise PsbtFehler("nLockTime muss eine Blockhöhe sein.")

    reihe = list(ausgaenge)
    (rng or random.SystemRandom()).shuffle(reihe)

    vin = []
    infos = []
    for e in eingaenge:
        if multisig is not None:
            pub = multisig.ableiten(e.change, e.index)
            spk = pub.spk
        else:
            pub, spk = ableiten(hd, typ, e.change, e.index)
        vorgaenger = None
        if e.roh_tx is not None:
            vorgaenger = pruefe_roh_tx(e.roh_tx, e.txid, e.vout, e.wert, spk.data)
        elif typ == "legacy":
            raise PsbtFehler(f"{e.txid}:{e.vout}: Legacy-Input braucht die Vorgänger-Tx.")
        # embit erwartet die TxID in Anzeige-Reihenfolge und dreht beim Serialisieren selbst.
        vin.append(TransactionInput(bytes.fromhex(e.txid), e.vout, sequence=RBF_SEQUENCE))
        infos.append((e, pub, spk, vorgaenger))
    vout = [TransactionOutput(a.wert, escript.Script(a.spk)) for a in reihe]
    tx = Transaction(version=TX_VERSION, vin=vin, vout=vout, locktime=locktime)

    psbt = PSBT(tx, unknown={})
    for scope, (e, pub, spk, vorgaenger) in zip(psbt.inputs, infos):
        if typ in ("segwit", "nested", *MULTISIG_SKRIPTE):
            scope.witness_utxo = TransactionOutput(e.wert, spk)
        if vorgaenger is not None:
            scope.non_witness_utxo = vorgaenger
        if multisig is not None:
            pub.in_scope(scope)
            continue
        if typ == "nested":
            scope.redeem_script = escript.p2wpkh(pub)
        scope.bip32_derivations[pub] = DerivationPath(
            herkunft.fingerprint, list(herkunft.pfad) + [e.change, e.index]
        )
    for scope, a in zip(psbt.outputs, reihe):
        if a.rolle != "wechsel":
            continue
        if not a.pfad or a.pfad[0] != 1:
            raise PsbtFehler("Wechselgeld muss an eine interne Adresse (/1/*) gehen.")
        if multisig is not None:
            abl = multisig.ableiten(a.pfad[0], a.pfad[1])
            if abl.spk.data != a.spk:
                raise PsbtFehler("Wechselgeld-Skript passt nicht zum Pfad.")
            abl.in_scope(scope)
            continue
        pub, spk = ableiten(hd, typ, a.pfad[0], a.pfad[1])
        if spk.data != a.spk:
            raise PsbtFehler("Wechselgeld-Skript passt nicht zum Pfad.")
        if typ == "nested":
            scope.redeem_script = escript.p2wpkh(pub)
        scope.bip32_derivations[pub] = DerivationPath(
            herkunft.fingerprint, list(herkunft.pfad) + list(a.pfad)
        )
    if multisig is not None:
        for c in multisig.cosigner:
            if c.global_xpub:
                psbt.xpubs[c.hd] = DerivationPath(c.fingerprint, list(c.pfad))
    elif global_xpub_passt(hd, herkunft):
        psbt.xpubs[hd] = DerivationPath(herkunft.fingerprint, list(herkunft.pfad))
    return psbt, reihe


def global_xpub_passt(hd: HDKey, herkunft: Herkunft) -> bool:
    """
    ``PSBT_GLOBAL_XPUB`` nur mit echtem Key-Origin: Tiefe = Pfadlänge und
    letzter Index = child_number (Electrum lehnt Abweichungen ab). Ohne
    Origin bleibt das Feld weg.
    """
    if herkunft.quelle != "deskriptor" or len(herkunft.pfad) != hd.depth:
        return False
    if hd.depth == 0:
        return True
    return int(hd.child_number) == herkunft.pfad[-1]


def psbt_base64(psbt: PSBT) -> str:
    return base64.b64encode(psbt.serialize()).decode("ascii")


# ---------------------------------------------------------------------------
# Multisig: wsh(sortedmulti|multi(…)) und sh(wsh(…)) aus dem Deskriptor
# ---------------------------------------------------------------------------

#: Multisig-Hüllen (``WalletEntry.script_type``), die gebaut werden.
MULTISIG_SKRIPTE = ("wsh", "sh-wsh")

#: Eine Signatur im Witness: Längenbyte + 72 Byte DER samt Sighash (obere Grenze).
_SIG_WITNESS_BYTES = 1 + 72


def _varint_laenge(n: int) -> int:
    return 1 if n < 253 else (3 if n <= 0xFFFF else 5)


def multisig_witness_script_laenge(n: int) -> int:
    """``OP_m`` + n × (Push 33 + Schlüssel) + ``OP_n`` + ``OP_CHECKMULTISIG``."""
    return 1 + 34 * int(n) + 1 + 1


def multisig_input_vbytes(m: int, n: int, typ: str = "wsh") -> float:
    """
    vbytes eines M-von-N-Inputs (obere Grenze, 72-Byte-Signaturen).

    Nicht-Witness: Outpoint 36 + scriptSig-Länge 1 + Sequence 4 = 41, bei
    P2SH-P2WSH dazu das scriptSig (Push ``0x22`` + 34 Byte P2WSH) = 35.
    Witness (÷ 4): Elementzahl 1 + leeres Dummy-Element 1 (CHECKMULTISIG
    nimmt eins zu viel vom Stapel) + M Signaturen + Witness-Script mit
    Längenpräfix. 2-von-3 P2WSH: 41 + (1 + 1 + 146 + 1 + 105) / 4 = 104,5 vB.
    """
    m, n = int(m), int(n)
    if not 1 <= m <= n <= 16:
        raise PsbtFehler(f"Multisig {m}-von-{n} wird nicht unterstützt (1 ≤ M ≤ N ≤ 16).")
    if typ not in MULTISIG_SKRIPTE:
        raise PsbtFehler(f"Multisig-Hülle {typ!r} wird für PSBTs nicht unterstützt.")
    ws = multisig_witness_script_laenge(n)
    witness = 1 + 1 + m * _SIG_WITNESS_BYTES + _varint_laenge(ws) + ws
    nicht_witness = 41 + (35 if typ == "sh-wsh" else 0)
    return nicht_witness + witness / 4


@dataclass(frozen=True)
class Cosigner:
    """Ein Cosigner-XPUB mit Key-Origin (oder Fallback wie bei Single-Sig)."""

    hd: HDKey
    fingerprint: bytes
    pfad: tuple[int, ...]
    #: ``deskriptor`` (``[fp/…]`` im Deskriptor) oder ``xpub`` (Fingerprint des
    #: XPUB selbst, Pfad relativ, kein GLOBAL_XPUB).
    quelle: str

    @property
    def herkunft(self) -> Herkunft:
        return Herkunft(self.fingerprint, self.pfad, self.quelle)

    @property
    def global_xpub(self) -> bool:
        return global_xpub_passt(self.hd, self.herkunft)


@dataclass(frozen=True)
class MultisigAbleitung:
    """Skripte und Cosigner-Schlüssel an einem ``change/index``."""

    spk: escript.Script
    witness_script: escript.Script
    #: Nur bei ``sh-wsh``: das P2WSH-Programm im P2SH.
    redeem_script: escript.Script | None
    #: (öffentlicher Schlüssel, Fingerprint + voller Pfad) je Cosigner.
    schluessel: tuple

    def in_scope(self, scope) -> None:
        """``witness_script``/``redeem_script`` und alle ``bip32_derivation``."""
        scope.witness_script = self.witness_script
        if self.redeem_script is not None:
            scope.redeem_script = self.redeem_script
        for pub, pfad in self.schluessel:
            scope.bip32_derivations[pub] = pfad


class MultisigPolitik:
    """
    Multisig-Wallet aus dem Deskriptor (``WALLET_n_DESC``) — nur öffentlich.

    Unterstützt: ``wsh(sortedmulti(M,…))``, ``wsh(multi(M,…))`` und dieselben
    in ``sh(…)``; jeder Cosigner ein XPUB mit ``/<0;1>/*`` (Empfang ``/0/*``,
    Wechsel ``/1/*``). Das Skript wird hier gebaut (``sortedmulti``: Schlüssel
    nach BIP67 sortiert) und beim Anlegen gegen die embit-Ableitung des
    Deskriptors geprüft — dieselbe, aus der SatSage die Adressen kennt.
    """

    def __init__(self, descriptor: str):
        from core.derivation import parse_deskriptor

        desc = parse_deskriptor(descriptor or "")
        if desc is None:
            raise PsbtFehler("Multisig-Deskriptor nicht lesbar.")
        if getattr(desc, "taproot", False):
            raise PsbtFehler("Taproot-Multisig (multi_a) wird für PSBTs noch nicht unterstützt.")
        if not getattr(desc, "wsh", False) or getattr(desc, "wpkh", False):
            raise PsbtFehler("Nur wsh(…)- und sh(wsh(…))-Multisig wird für PSBTs unterstützt.")
        from embit.descriptor.miniscript import Multi, Sortedmulti

        ms = desc.miniscript
        if type(ms) not in (Multi, Sortedmulti):
            raise PsbtFehler("Nur multi/sortedmulti — Miniscript-Policies (z. B. Zeitschlösser) noch nicht.")
        schluessel = list(ms.args[1:])
        self.m = int(ms.args[0].num)
        self.n = len(schluessel)
        multisig_input_vbytes(self.m, self.n)  # Bereich prüfen
        self.sortiert = isinstance(ms, Sortedmulti)
        self.typ = "sh-wsh" if getattr(desc, "sh", False) else "wsh"
        cosigner = []
        for k in schluessel:
            hd = getattr(k, "key", None)
            if not isinstance(hd, HDKey) or getattr(k, "is_private", False) or hd.is_private:
                raise PsbtFehler("Jeder Cosigner braucht einen öffentlichen XPUB (kein Einzel- oder privater Schlüssel).")
            erlaubt = getattr(k, "allowed_derivation", None)
            if erlaubt is None or list(erlaubt.indexes) != [[0, 1], None]:
                raise PsbtFehler("Multisig-Deskriptor braucht /<0;1>/* je Cosigner (Empfang und Wechsel).")
            if k.origin is not None:
                cosigner.append(Cosigner(hd, bytes(k.origin.fingerprint),
                                         tuple(k.origin.derivation), "deskriptor"))
            else:
                cosigner.append(Cosigner(hd, bytes(hd.my_fingerprint), (), "xpub"))
        self.cosigner = tuple(cosigner)
        self._ketten: dict[tuple[int, int], HDKey] = {}
        self._cache: dict[tuple[int, int], MultisigAbleitung] = {}
        for change in (0, 1):
            soll = desc.derive(0, branch_index=change).script_pubkey().data
            if self.ableiten(change, 0).spk.data != soll:
                raise PsbtFehler("Multisig-Ableitung passt nicht zum Deskriptor.")

    @property
    def input_vb(self) -> float:
        return multisig_input_vbytes(self.m, self.n, self.typ)

    @property
    def quelle(self) -> str:
        """``deskriptor``, wenn jeder Cosigner einen echten Key-Origin hat."""
        return "deskriptor" if all(c.quelle == "deskriptor" for c in self.cosigner) else "xpub"

    def _kette(self, i: int, change: int) -> HDKey:
        k = (i, change)
        if k not in self._ketten:
            self._ketten[k] = self.cosigner[i].hd.derive([change])
        return self._ketten[k]

    def ableiten(self, change: int, index: int) -> MultisigAbleitung:
        change, index = int(change), int(index)
        if change not in (0, 1) or not 0 <= index < GEHAERTET:
            raise PsbtFehler(f"Multisig-Pfad {change}/{index} ungültig.")
        k = (change, index)
        if k in self._cache:
            return self._cache[k]
        paare = []
        for i, c in enumerate(self.cosigner):
            pub = self._kette(i, change).derive([index]).key
            paare.append((pub, DerivationPath(c.fingerprint, list(c.pfad) + [change, index])))
        pubs = [p for p, _ in paare]
        if self.sortiert:
            pubs = sorted(pubs, key=lambda p: p.sec())
        ws = escript.multisig(self.m, pubs)
        if self.typ == "sh-wsh":
            rs = escript.p2wsh(ws)
            spk = escript.p2sh(rs)
        else:
            rs = None
            spk = escript.p2wsh(ws)
        abl = MultisigAbleitung(spk, ws, rs, tuple(paare))
        if len(self._cache) < 20_000:
            self._cache[k] = abl
        return abl

    def pfad_text(self, *rest: int) -> str:
        """Voller Pfad, wenn alle Cosigner denselben Origin-Pfad haben, sonst ``…/c/i``."""
        pfade = {(c.pfad, c.quelle) for c in self.cosigner}
        if len(pfade) == 1:
            return self.cosigner[0].herkunft.pfad_text(*rest)
        return "/".join(["…", *(str(i) for i in rest)]) if rest else "…"

    def uebersicht(self) -> dict:
        """Für die Antwort: M, N, Hülle, Cosigner (nur Fingerprint und Pfad, kein XPUB)."""
        return {
            "m": self.m, "n": self.n, "skript": self.typ, "sortiert": self.sortiert,
            "fingerprints": [c.fingerprint.hex() for c in self.cosigner],
            "cosigner": [{"fingerprint": c.fingerprint.hex(), "quelle": c.quelle,
                          "pfad": c.herkunft.pfad_text(), "global_xpub": c.global_xpub}
                         for c in self.cosigner],
        }



# ---------------------------------------------------------------------------
# Gesamtablauf: Auswahl (Server-seitig neu) → Wechselgeld → PSBT → Übersicht
# ---------------------------------------------------------------------------

#: Kleinster Zielbetrag (Staubgrenze wie ``coin_auswahl.STAUB_SATS``).
MIN_ZIEL_SATS = 546

#: Gebührenfeld: 0 < milli ≤ 10 000 sat/vB (wie ``fifoFeeZuMilli`` im Web).
MAX_FEE_MILLI = 10_000 * 1000


def fee_text_zu_milli(roh) -> int | None:
    """``"2,5"``/``"2.5"``/``2.5`` → 2500 milli-sat/vB; None bei Unsinn."""
    import re

    if isinstance(roh, bool):
        return None
    if isinstance(roh, int):
        text = str(roh)
    elif isinstance(roh, float):
        text = repr(roh)
    else:
        text = re.sub(r"[\s\u00A0\u202F]+", "", str(roh or ""))
        text = re.sub(r"sat/?vb$", "", text, flags=re.I)
    if not re.fullmatch(r"[0-9]*[.,]?[0-9]*", text) or not re.search(r"[0-9]", text):
        return None
    ganz, _, nach = text.replace(",", ".").partition(".")
    if len(nach) > 3:
        return None
    milli = int(ganz or "0") * 1000 + int((nach or "").ljust(3, "0") or "0")
    return milli if 0 < milli <= MAX_FEE_MILLI else None


def _bestaetigt(u: dict) -> bool:
    status = u.get("status")
    if isinstance(status, dict) and "confirmed" in status:
        return bool(status.get("confirmed"))
    if u.get("receive_pending") or u.get("unconfirmed"):
        return False
    hoehe = u.get("height", u.get("block_height"))
    if hoehe is not None:
        try:
            return int(hoehe) > 0
        except (TypeError, ValueError):
            return False
    return True


def zusammenfuehren(wallet_utxos: Iterable[dict], lot_punkte: Iterable[dict]) -> list[dict]:
    """
    Echter UTXO-Bestand (Cache + Mempool-Abgleich) × Lot-Anteile der
    Steuerauswertung. Nur UTXOs, die es in beiden gibt, mit Betrag aus dem
    Bestand; unbestätigte fallen weg. Kein Wert vom Browser.
    """
    lots: dict[str, dict] = {}
    for e in lot_punkte or ():
        if not isinstance(e, dict) or not e.get("txid"):
            continue
        key = f"{str(e.get('txid')).lower()}:{int(e.get('vout') or 0)}"
        lots[key] = e
    aus: list[dict] = []
    for u in wallet_utxos or ():
        if not isinstance(u, dict) or not u.get("txid"):
            continue
        txid = str(u.get("txid")).lower()
        vout = int(u.get("vout") or 0)
        key = f"{txid}:{vout}"
        lot = lots.get(key)
        wert = int(u.get("value_sats", u.get("value")) or 0)
        if lot is None or wert <= 0:
            continue
        lot_wert = int(lot.get("value_sats") or 0)
        if lot_wert and lot_wert != wert:
            continue  # Auswertung passt nicht zum Bestand — lieber nicht
        aus.append({
            "key": key, "txid": txid, "vout": vout, "value_sats": wert,
            "address": str(u.get("address") or ""),
            "sats_gruen": lot.get("sats_gruen"), "sats_orange": lot.get("sats_orange"),
            "sats_grau": lot.get("sats_grau"), "neuvermoegen": bool(lot.get("neuvermoegen")),
            "time_ts": lot.get("time_ts"),
            "spending_pending": bool(u.get("spending_pending")),
            "bestaetigt": _bestaetigt(u),
        })
    return aus


def erzeuge(
    *,
    xpub: str,
    typ: str,
    herkunft: Herkunft | None,
    netz,
    max_index: int,
    utxos: list[dict],
    pending: Iterable[str],
    modus: str,
    strategie: str,
    betrag: int,
    fee_milli: int,
    ziel_adresse: str,
    ziel_status: str,
    ziel_wallet: str = "",
    bekannte_adressen: Iterable[str] = (),
    hat_history: Callable[[str], bool] | None = None,
    roh_tx_holen: Callable[[str], bytes | None] | None = None,
    hoehe: int | None = None,
    nur_inputs: Iterable[str] | None = None,
    rng: random.Random | None = None,
    multisig: MultisigPolitik | None = None,
    quelle_wallet: str = "",
    nur_max: bool = False,
) -> dict:
    """
    Auswahl neu rechnen und PSBT bauen. *utxos* aus ``zusammenfuehren``.

    ``max_netto_sats``: größter Betrag, der bei dieser Rate und diesem Ziel
    gedeckt ist (grünes Maximum minus Gebühr, ``coin_auswahl.netto_max``).
    *nur_max*: nur die Maxima rechnen (``status`` ``max``), keine PSBT; ohne
    Zieladresse gilt die Größe der eigenen Wechseladresse.

    Lot-Anteile je Output: FIFO je Output (``core.fifo_lots``), dieselbe
    Funktion wie die Herkunftsverfolgung. *quelle_wallet* (Anzeigename):
    ein Ziel im selben Wallet zählt wie Wechselgeld.

    Multisig: *multisig* aus dem Deskriptor; *xpub*, *typ* und *herkunft*
    zählen dann nicht.

    Rückgabe ``status`` ``ok`` mit ``psbt_base64`` und Übersicht — oder ein
    Auswahl-Status (``nicht_gedeckt``, ``keine_kandidaten``, ``unzulaessig``,
    ``ueber_max``) ohne PSBT. Bausteine, die nicht passen: ``PsbtFehler``.
    """
    from embit.script import address_to_scriptpubkey

    from core.coin_auswahl import (
        STAUB_HART_SATS,
        FesteRate,
        Groessen,
        kandidaten,
        netto_max,
        waehle,
    )
    from core import fifo_lots

    if multisig is not None:
        typ = multisig.typ
    elif typ not in UNTERSTUETZTE_SKRIPTE:
        raise PsbtFehler(f"Skripttyp {typ!r} wird für PSBTs noch nicht unterstützt.")
    ohne_ziel = nur_max and not ziel_adresse
    if not ohne_ziel and ziel_status not in ("meine", "fremd", "keine_wallets"):
        raise PsbtFehler("Zieladresse ungültig oder im falschen Netz.")
    if not 0 < int(fee_milli) <= MAX_FEE_MILLI:
        raise PsbtFehler("Gebühr außerhalb des Bereichs.")
    if not nur_max and int(betrag) < MIN_ZIEL_SATS:
        raise PsbtFehler(f"Betrag unter der Staubgrenze ({MIN_ZIEL_SATS} sats).")
    modus = "offensiv" if modus == "offensiv" else "defensiv"
    ziel_spk = None if ohne_ziel else address_to_scriptpubkey(ziel_adresse).data

    if multisig is not None:
        hd = None
        pfade = Pfade(multisig, typ, netz, max_index)
        input_vb = multisig.input_vb
        pfad_text = multisig.pfad_text

        def wechsel_spk_an(i: int):
            return multisig.ableiten(1, i).spk
    else:
        hd = HDKey.from_string(xpub)
        if hd.is_private:
            raise PsbtFehler("Privater Schlüssel — SatSage baut nur aus öffentlichen.")
        if herkunft is None:
            herkunft = herkunft_fuer(xpub)
        pfade = Pfade(hd, typ, netz, max_index)
        input_vb = VBYTES_INPUT_NACH_TYP[typ]
        pfad_text = herkunft.pfad_text

        def wechsel_spk_an(i: int):
            return ableiten(hd, typ, 1, i)[1]
    wechsel_probe = wechsel_spk_an(0).data
    if ziel_spk is None:
        ziel_spk = wechsel_probe

    nutzbar = [u for u in utxos if u.get("bestaetigt", True)]
    kand = kandidaten(nutzbar, modus=modus, pending=pending)
    max_sats = sum(k.beitrag for k in kand)
    groessen = Groessen(
        input_vb=input_vb,
        ziel_vb=output_vbytes(ziel_spk),
        wechsel_vb=output_vbytes(wechsel_probe),
        basis_vb=10 if typ == "legacy" else 10.5,
    )
    netto = netto_max(kand, basis_rate=FesteRate(int(fee_milli)), groessen=groessen)
    basis = {"modus": modus, "strategie": strategie, "betrag_sats": int(betrag),
             "max_sats": max_sats, "max_netto_sats": netto["max_netto_sats"],
             "max_netto_fee_sats": netto["fee_sats"], "max_netto_inputs": netto["inputs"],
             "kandidaten": len(kand)}
    if nur_max:
        return {**basis, "status": "max", "sat_vb": FesteRate(int(fee_milli)).sat_vb,
                "ziel_angenommen": ohne_ziel}
    if nur_inputs is not None:
        zulaessig = {k.key for k in kand}
        fehlt = [str(k).strip().lower() for k in nur_inputs
                 if str(k).strip().lower() not in zulaessig]
        if fehlt or not list(nur_inputs):
            return {**basis, "status": "unzulaessig", "strategie": "coin_control",
                    "unzulaessig": fehlt}
    if int(betrag) > max_sats:
        return {**basis, "status": "ueber_max"}

    auswahl = waehle(kand, betrag=int(betrag), basis_rate=FesteRate(int(fee_milli)),
                     strategie=strategie, groessen=groessen, nur=nur_inputs)
    if auswahl.get("status") != "ok":
        return {**basis, **{k: v for k, v in auswahl.items() if k != "inputs"}}

    nach_key = {u["key"]: u for u in nutzbar}
    gewaehlt = [nach_key[i["key"]] for i in auswahl["inputs"]]
    beitrag = {i["key"]: int(i["sats_gruen"]) for i in auswahl["inputs"]}
    summe = sum(int(u["value_sats"]) for u in gewaehlt)
    summe_gruen = sum(beitrag.values())
    nicht_gruen = summe - summe_gruen

    eingaenge: list[Eingang] = []
    for u in gewaehlt:
        pfad = pfade.finde(u.get("address") or "")
        if pfad is None:
            raise PsbtFehler(f"{u['key']}: Adresse nicht aus diesem "
                             f"{'Deskriptor' if multisig else 'XPUB'} ableitbar.")
        roh = roh_tx_holen(u["txid"]) if roh_tx_holen else None
        eingaenge.append(Eingang(u["txid"], int(u["vout"]), int(u["value_sats"]),
                                 pfad[0], pfad[1], roh))

    mit_wechsel = auswahl["outputs"] == 2
    ausgaenge = [Ausgang(ziel_spk, int(betrag), "ziel")]
    wechsel_index = None
    wechsel_adresse = ""
    if mit_wechsel:
        wechsel_index = naechster_wechsel_index(
            pfade, bekannte_adressen, hat_history=hat_history, ausser=[ziel_adresse])
        wechsel_spk = wechsel_spk_an(wechsel_index)
        wechsel_adresse = pfade.adresse(1, wechsel_index)
        if wechsel_spk.data == ziel_spk:
            raise PsbtFehler("Ziel ist die Wechseladresse.")
        ausgaenge.append(Ausgang(wechsel_spk.data, 0, "wechsel", (1, wechsel_index)))

    vsize = vsize_tx([input_vb if multisig else typ] * len(eingaenge), [a.spk for a in ausgaenge])
    mindest = gebuehr_fuer(fee_milli, vsize)
    if mit_wechsel:
        fee = mindest
        wechsel = summe - int(betrag) - fee
        grenze = STAUB_HART_SATS
        if wechsel < max(grenze, nicht_gruen):
            raise PsbtFehler("Wechselgeld deckt den nicht grünen Anteil nicht.")
        ausgaenge[1].wert = wechsel
    else:
        wechsel = 0
        fee = summe - int(betrag)
        if nicht_gruen:
            raise PsbtFehler("Ohne Wechselgeld ginge nicht grünes Guthaben in die Gebühr.")
        if fee < mindest:
            raise PsbtFehler("Gebühr unter der gewählten Rate.")
    if summe_gruen < int(betrag) + fee:
        raise PsbtFehler("Gebühr wäre nicht aus grünen sats bezahlt.")

    locktime = int(hoehe) if hoehe and int(hoehe) > 0 else 0
    psbt, reihe = baue_psbt(xpub=xpub, typ=typ, herkunft=herkunft, eingaenge=eingaenge,
                            ausgaenge=ausgaenge, locktime=locktime, rng=rng, multisig=multisig)

    # Lot-Anteile je Output: FIFO je Output — dieselbe Verteilung wie die
    # Herkunftsverfolgung nach dem Senden (core.fifo_lots).
    ziel_bleibt = bool(ziel_status == "meine" and quelle_wallet and ziel_wallet == quelle_wallet)
    lose = fifo_lots.klassen_lose(
        (beitrag[u["key"]], e.wert - beitrag[u["key"]], 0) for e, u in zip(eingaenge, gewaehlt)
    )
    verteilt = fifo_lots.verteilen(lose, fifo_lots.verbraucher(
        ((n, a.wert, a.rolle == "wechsel" or ziel_bleibt) for n, a in enumerate(reihe)), fee,
    ))
    outputs = []
    for n, a in enumerate(reihe):
        anteil = fifo_lots.klassen_summen(verteilt.get(fifo_lots.output_schluessel(n), []))
        if a.rolle == "ziel":
            outputs.append({
                "rolle": "ziel", "adresse": ziel_adresse, "value_sats": a.wert,
                "farbe": "gruen" if ziel_status == "meine" else "gelb",
                "wallet": ziel_wallet if ziel_status == "meine" else "",
                "sats_gruen": anteil["sats_gruen"], "sats_gelb": anteil["sats_gelb"],
            })
        else:
            outputs.append({
                "rolle": "wechsel", "adresse": wechsel_adresse, "value_sats": a.wert,
                "farbe": "gruen", "pfad": pfad_text(*a.pfad),
                "sats_gruen": anteil["sats_gruen"], "sats_gelb": anteil["sats_gelb"],
            })
    inputs = []
    for e, u in zip(eingaenge, gewaehlt):
        inputs.append({
            "key": u["key"], "value_sats": e.wert, "sats_gruen": beitrag[u["key"]],
            "sats_gelb": e.wert - beitrag[u["key"]], "pfad": pfad_text(e.change, e.index),
            "time_ts": u.get("time_ts"), "non_witness_utxo": e.roh_tx is not None,
        })
    if multisig is not None:
        herkunft_info = {"fingerprint": ",".join(c.fingerprint.hex() for c in multisig.cosigner),
                         "quelle": multisig.quelle, "pfad": multisig.pfad_text()}
        global_xpub = any(c.global_xpub for c in multisig.cosigner)
    else:
        herkunft_info = {"fingerprint": herkunft.fingerprint_hex, "quelle": herkunft.quelle,
                         "pfad": herkunft.pfad_text()}
        global_xpub = global_xpub_passt(hd, herkunft)
    return {
        **basis,
        "status": "ok",
        "strategie": auswahl.get("strategie", strategie),
        "psbt_base64": psbt_base64(psbt),
        "psbt_version": 0,
        "inputs": inputs,
        "outputs": outputs,
        "fee_sats": fee,
        "vsize": vsize,
        "sat_vb": FesteRate(int(fee_milli)).sat_vb,
        "sat_vb_effektiv": round(fee / vsize, 3),
        "wechselgeld_sats": wechsel,
        "wechsel_index": wechsel_index,
        "ohne_wechselgeld": not mit_wechsel,
        "staub_in_gebuehr_sats": 0 if mit_wechsel else fee - mindest,
        "staub_wechselgeld": bool(auswahl.get("staub_wechselgeld")),
        "summe_inputs_sats": summe,
        "summe_gruen_sats": summe_gruen,
        "wechselgeld_nicht_gruen_sats": nicht_gruen,
        "locktime": locktime,
        "sequence": RBF_SEQUENCE,
        "rbf": True,
        "herkunft": herkunft_info,
        "global_xpub": global_xpub,
        "multisig": multisig.uebersicht() if multisig is not None else None,
    }
