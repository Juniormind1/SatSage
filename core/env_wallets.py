"""
Wallet-/XPUB-Env-Helfer und Start-Sync-Flags.

Aus main.py ausgelagert (Slice 3 / ADR modular-engine). Verhalten 1:1 —
main re-exportiert die öffentlichen Namen als Fassade.
"""
from __future__ import annotations

from pathlib import Path

from core.env_bootstrap import ENV_FILE


def _indexed_env_values(env: dict[str, str], prefix: str) -> list[str]:
    """Liest fortlaufende PREFIX_0, PREFIX_1, … aus der .env."""
    values: list[str] = []
    for index in range(100):
        raw = env.get(f"{prefix}_{index}", "").strip()
        if not raw:
            break
        values.append(raw)
    return values


#: Hinweis, wenn Multisig-Wallets konfiguriert sind.
#:
#: Sie werden gespeichert und angezeigt, aber noch nicht abgeleitet: Für
#: wsh(sortedmulti(…)) fehlt der Adress-Encoder. Ihre Cosigner dürfen deshalb
#: nicht in den Analyse-Stack — einzeln gescannt wären sie leere Wallets, und
#: das sähe aus wie „kein Guthaben" statt „noch nicht unterstützt".
UNLESBAR_HINWEIS = (
    "Achtung: {anzahl} Wallet(s) lassen sich nicht ableiten — der Deskriptor "
    "ist unlesbar oder nutzt eine nicht unterstützte Form (aggregierte "
    "Taproot-Schlüssel, musig). Für sie werden weder Bestände noch Herkunft "
    "ermittelt."
)
def wallets_aus_env_datei(env_path: Path | None = None):
    """
    Die konfigurierten Wallets — Single-Sig wie Multisig.

    Liegt hier (nicht in core.config), damit CLI und Oberfläche dieselbe
    Quelle nutzen. core.config wird erst hier importiert: Es importiert
    seinerseits env_wallets-Helfer, und auf Modulebene wäre das ein Zirkelbezug.
    """
    import sys

    from core.config import EnvFile, read_wallets

    if env_path is None:
        env_path = ENV_FILE
        main_mod = sys.modules.get("main")
        if main_mod is not None:
            main_env = getattr(main_mod, "ENV_FILE", None)
            if main_env is not None:
                env_path = main_env
    return read_wallets(EnvFile.load(env_path))


def _xpubs_from_env(env: dict[str, str]) -> list[str] | None:
    """
    XPUBs aus XPUBS (whitespace-getrennt) oder XPUB_0, XPUB_1, …

    Nur noch für die alte Schreibweise zuständig; das Blockformat liest
    core.config.read_wallets. Bleibt erhalten, weil es von dort aufgerufen
    wird.
    """
    raw = env.get("XPUBS", "").strip()
    if raw:
        return raw.split()
    indexed = _indexed_env_values(env, "XPUB")
    return indexed or None


def _wallet_names_from_env(env: dict[str, str]) -> list[str] | None:
    """Wallet-Namen aus WALLET_NAMES (pipe-getrennt) oder WALLET_NAME_0, …"""
    raw = env.get("WALLET_NAMES", "").strip()
    if raw:
        return [part.strip() for part in raw.split("|") if part.strip()]
    indexed = _indexed_env_values(env, "WALLET_NAME")
    return indexed or None


def _max_addresses_per_xpub_from_env(env: dict[str, str]) -> list[int] | None:
    """Scan-Tiefe je XPUB aus MAX_ADDRESSES_PER_XPUB (pipe-getrennt)."""
    raw = env.get("MAX_ADDRESSES_PER_XPUB", "").strip()
    if not raw:
        return None
    werte: list[int] = []
    for teil in raw.split("|"):
        try:
            werte.append(int(teil.strip()))
        except ValueError:
            return None
    return werte or None


def _script_types_from_env(env: dict[str, str]) -> list[str] | None:
    """Skripttypen aus SCRIPT_TYPES (pipe-getrennt) oder SCRIPT_TYPE_0, …"""
    raw = env.get("SCRIPT_TYPES", "").strip()
    if raw:
        return [part.strip() for part in raw.split("|")]
    indexed = _indexed_env_values(env, "SCRIPT_TYPE")
    return indexed or None

def resolve_wallets_beim_start_aktualisieren(
    env: dict[str, str],
    default: bool = False,
) -> bool:
    """
    „Wallets immer aktuell halten“ — opt-in, Vorgabe aus.

    Env: ``WALLETS_IMMER_AKTUELL`` oder legacy ``WALLETS_BEIM_START_AKTUALISIEREN``.

    Bei ja: Tip-Nachzug beim Start **und** Dauer-Watch über eigenen Electrs
    (scripthash.subscribe). Kein Fullscan.
    """
    raw = env.get("WALLETS_IMMER_AKTUELL")
    if raw is None or not str(raw).strip():
        raw = env.get("WALLETS_BEIM_START_AKTUALISIEREN")
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "ja", "yes", "on")


def resolve_wallets_nur_bekannte_utxos(
    env: dict[str, str],
    default: bool = False,
) -> bool:
    """
    Unteroption zu „Wallets immer aktuell halten“.

    Env: ``WALLETS_NUR_BEKANNTE_UTXOS``. Bei ja: Tip-Nachzug (Start / Block /
    „Bis Tip“) prüft nur bekannte UTXOs/Adressen — kein Gap-Scan. Neue
    Empfangsadressen nur per manuellem UTXO-Scan. Vorgabe aus.
    """
    raw = env.get("WALLETS_NUR_BEKANNTE_UTXOS")
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "ja", "yes", "on")

