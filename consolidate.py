"""Experimentell: Dust-UTXO-Konsolidierung und PSBT-Erzeugung."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path

from embit.bip32 import HDKey
from embit.psbt import PSBT, DerivationPath
from embit.transaction import Transaction, TransactionInput, TransactionOutput
from embit.script import address_to_scriptpubkey, p2wpkh

DUST_SATS = 5_000
MIN_DUST_UTXOS = 3  # mehr als 2
DEFAULT_FEE_RATE_SAT_VB = 2
DEST_HINT = "kann nur am eigenen Node (Fulcrum/electrs) generiert werden"


@dataclass
class DustConsolidationProposal:
    xpub: str
    wallet_label: str
    dust_utxos: list[dict]
    dest_address: str | None
    total_in_sats: int
    fee_sats: int
    output_sats: int
    dest_index: int | None = None


def _main():
    import main
    return main


def _txid_bytes(txid: str) -> bytes:
    return bytes.fromhex(txid)[::-1]


def resolve_address_derivation(
    xpub: str,
    address: str,
    max_index: int | None = None,
) -> tuple[int, int, HDKey, object] | None:
    """Liefert (change, index, child_hdkey, address_script) für eine XPUB-Adresse."""
    m = _main()
    if max_index is None:
        max_index = m.MAX_TRACE_ADDRESS_SEARCH

    try:
        hd = HDKey.from_string(xpub)
    except Exception:
        return None

    for encoder in m._encoders_for_xpub(xpub):
        for change in (0, 1):
            for i in range(max_index):
                try:
                    child = hd.derive([change, i])
                    sc = encoder(child.key)
                    if sc.address() == address:
                        return change, i, child, sc
                except Exception:
                    break
    return None


def first_receive_address(xpub: str) -> tuple[str, int, HDKey, object] | None:
    """Erste Empfangsadresse (change=0, index=0) des XPUBs."""
    try:
        hd = HDKey.from_string(xpub)
    except Exception:
        return None

    m = _main()
    for encoder in m._encoders_for_xpub(xpub):
        try:
            child = hd.derive([0, 0])
            sc = encoder(child.key)
            return sc.address(), 0, child, sc
        except Exception:
            continue
    return None


def estimate_fee_sats(
    n_inputs: int,
    n_outputs: int = 1,
    fee_rate: int = DEFAULT_FEE_RATE_SAT_VB,
) -> int:
    """Grober vByte-Schätzer für P2WPKH."""
    vbytes = 10 + 68 * n_inputs + 31 * n_outputs
    return vbytes * fee_rate


def find_dust_consolidation_proposals(
    utxos: list[dict],
    wallet,
    dust_max: int = DUST_SATS,
    fee_rate: int = DEFAULT_FEE_RATE_SAT_VB,
    cache_source: str | None = None,
    fulcrum=None,
) -> list[DustConsolidationProposal]:
    """Gruppiert Dust-UTXOs pro XPUB; schlägt Konsolidierung vor wenn >2 Stück."""
    by_xpub: dict[str, list[dict]] = {}

    for utxo in utxos:
        if utxo.get("value", 0) >= dust_max:
            continue
        address = utxo.get("address")
        if not address or address == "?":
            continue
        if wallet:
            wallet.resolve_address(address)
            xpub = wallet.xpub_for_address(address)
        else:
            xpub = None
        if not xpub:
            continue
        by_xpub.setdefault(xpub, []).append(utxo)

    proposals: list[DustConsolidationProposal] = []
    for xpub, dust_list in by_xpub.items():
        if len(dust_list) <= 2:
            continue

        dest_address: str | None = None
        dest_index: int | None = None
        label = wallet.xpub_label(xpub) if wallet else xpub[:20] + "..."

        if cache_source == "fulcrum" and fulcrum is not None:
            m = _main()
            try:
                dest = m.next_unused_receive_address_fulcrum(fulcrum, xpub, wallet=wallet)
            except RuntimeError as exc:
                print(f"  ⚠️  {exc}", flush=True)
                continue
            if not dest:
                print(
                    f"  ⚠️  Keine freie Empfangsadresse im Suchraum für {label}.",
                    flush=True,
                )
                continue
            dest_address, dest_index, _, _ = dest

        dust_sorted = sorted(dust_list, key=lambda u: u["value"])
        total_in = sum(u["value"] for u in dust_sorted)
        fee = estimate_fee_sats(len(dust_sorted), 1, fee_rate)
        if total_in <= fee:
            continue

        proposals.append(
            DustConsolidationProposal(
                xpub=xpub,
                wallet_label=label,
                dust_utxos=dust_sorted,
                dest_address=dest_address,
                total_in_sats=total_in,
                fee_sats=fee,
                output_sats=total_in - fee,
                dest_index=dest_index,
            )
        )

    return proposals


def build_consolidation_psbt(proposal: DustConsolidationProposal) -> PSBT:
    """Erzeugt ein unsigniertes PSBT für Wallet-interne Dust-Konsolidierung."""
    account = HDKey.from_string(proposal.xpub)
    account_fp = account.my_fingerprint

    vins = [
        TransactionInput(_txid_bytes(u["txid"]), u["vout"])
        for u in proposal.dust_utxos
    ]
    if not proposal.dest_address:
        raise ValueError("Keine Zieladresse — PSBT nur mit eigenem Node (RPC)")
    dest_script = address_to_scriptpubkey(proposal.dest_address)
    vouts = [TransactionOutput(proposal.output_sats, dest_script)]
    tx = Transaction(version=2, vin=vins, vout=vouts, locktime=0)
    psbt = PSBT(tx)
    psbt.xpubs[account] = DerivationPath(account_fp, [])

    dest_deriv = resolve_address_derivation(proposal.xpub, proposal.dest_address)
    if dest_deriv:
        _, dest_index, dest_child, dest_sc = dest_deriv
        dest_pubkey = dest_child.key
        psbt.outputs[0].bip32_derivations[dest_pubkey] = DerivationPath(
            account_fp, [0, dest_index]
        )
        if dest_sc.script_type() == "p2sh":
            psbt.outputs[0].redeem_script = p2wpkh(dest_pubkey)

    for index, utxo in enumerate(proposal.dust_utxos):
        address = utxo["address"]
        derived = resolve_address_derivation(proposal.xpub, address)
        if not derived:
            raise ValueError(f"Keine Ableitung für Adresse {address}")
        change, addr_index, child, addr_sc = derived
        pubkey = child.key
        value = utxo["value"]
        script_pubkey = address_to_scriptpubkey(address)

        inp = psbt.inputs[index]
        inp.witness_utxo = TransactionOutput(value, script_pubkey)
        inp.bip32_derivations[pubkey] = DerivationPath(
            account_fp, [change, addr_index]
        )
        if addr_sc.script_type() == "p2sh":
            inp.redeem_script = p2wpkh(pubkey)

    return psbt


def _safe_filename(label: str) -> str:
    slug = re.sub(r"[^\w\-+]+", "_", label, flags=re.UNICODE).strip("_")
    return slug or "wallet"


def print_dust_consolidation_hints(
    proposals: list[DustConsolidationProposal],
    dust_max: int = DUST_SATS,
) -> None:
    print(f"\n{'='*85}")
    print("🧪 Experimentell: Dust-Konsolidierung")
    print(
        f"   Schwellwert: < {dust_max:,} sats | "
        f"mindestens {MIN_DUST_UTXOS} UTXOs pro Wallet"
    )
    print(f"{'='*85}")

    for proposal in proposals:
        print(f"\nWallet: {proposal.wallet_label}")
        print(
            f"   {len(proposal.dust_utxos)} Dust-UTXOs, "
            f"{proposal.total_in_sats:,} sats gesamt"
        )
        if proposal.dest_address:
            dest_label = (
                f"{proposal.dest_address} (Empfangs-Index #{proposal.dest_index})"
            )
        else:
            dest_label = DEST_HINT
        print(
            f"   Vorschlag: in eine Ausgabe auf {dest_label} "
            f"({proposal.output_sats:,} sats nach ~{proposal.fee_sats:,} sats Gebühr)"
        )
        for utxo in proposal.dust_utxos:
            print(
                f"      • {utxo['value']:,} sats  "
                f"{utxo['txid'][:16]}…:{utxo['vout']}  {utxo.get('address', '?')}"
            )




def write_consolidation_psbts(
    proposals: list[DustConsolidationProposal],
    output_dir: Path | None = None,
) -> list[Path]:
    """Schreibt Konsolidierungs-PSBTs auf Platte; gibt Pfade zurück."""
    out_dir = output_dir or Path(__file__).resolve().parent / "psbt_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    written: list[Path] = []

    for proposal in proposals:
        if not proposal.dest_address:
            print(
                f"⚠️  PSBT für {proposal.wallet_label} übersprungen: "
                f"{DEST_HINT}",
                flush=True,
            )
            continue
        try:
            psbt = build_consolidation_psbt(proposal)
        except Exception as exc:
            print(
                f"⚠️  PSBT für {proposal.wallet_label} fehlgeschlagen: {exc}",
                flush=True,
            )
            continue

        fname = f"consolidate_{_safe_filename(proposal.wallet_label)}_{stamp}.psbt"
        path = out_dir / fname
        path.write_text(psbt.to_base64(), encoding="utf-8")
        written.append(path)
        print(f"✅ PSBT gespeichert: {path.resolve()}")
        print(f"   Base64-Länge: {len(psbt.to_base64())} Zeichen")

    return written


def run_dust_consolidation_prompt(
    utxos: list[dict],
    wallet,
    dust_max: int,
    output_dir: Path | None = None,
    cache_source: str | None = None,
    fulcrum=None,
) -> None:
    """Schlägt Konsolidierung mit dust_max vor und erzeugt optional PSBT(s)."""
    proposals = find_dust_consolidation_proposals(
        utxos,
        wallet,
        dust_max=dust_max,
        cache_source=cache_source,
        fulcrum=fulcrum,
    )
    if not proposals:
        print(
            f"Keine Konsolidierung möglich: "
            f"pro Wallet >2 UTXOs unter {dust_max:,} sats erforderlich.\n"
        )
        return

    print_dust_consolidation_hints(proposals, dust_max=dust_max)

    psbt_ready = [p for p in proposals if p.dest_address]
    if not psbt_ready:
        print(
            f"\nPSBT-Erzeugung: {DEST_HINT}\n"
        )
        return

    from interact import prompt_yes_no

    print(
        "\nKonsolidierungs-PSBT(s) erzeugen? [j/N]: ",
        end="",
        flush=True,
    )
    if not prompt_yes_no(default_yes=False):
        print("Keine PSBTs erzeugt.\n")
        return

    write_consolidation_psbts(psbt_ready, output_dir)
    print()

def offer_dust_consolidation(
    utxos: list[dict],
    wallet,
    output_dir: Path | None = None,
    dust_max: int = DUST_SATS,
    cache_source: str | None = None,
    fulcrum=None,
) -> None:
    """Zeigt Dust-Konsolidierungsvorschläge und erzeugt optional PSBT-Dateien."""
    run_dust_consolidation_prompt(
        utxos, wallet, dust_max, output_dir, cache_source, fulcrum
    )