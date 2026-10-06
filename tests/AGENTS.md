# AGENTS.md — `tests/`

Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART.

- **Keine echten XPUBs, Seeds, Deskriptoren oder Mainnet-Adressen/TxIDs** in Tests, Fixtures oder Assertions. Erfundene Daten, nachgebaute Verbindungen.
- Die Suite soll ohne Electrs, ohne Bitcoin Core und ohne persönliche `.env` auskommen. Was einen laufenden Node oder eine persönliche `.env` braucht, gehört nicht hierher.
- **Hart-Tests** (`tests/test_dealbreaker_*.py`, Gate `tests/hart.py`): Dealbreaker T1/T6/T9/T13, Auth, CSRF. Ohne Node. Auf `dev-juniormind` Skip, auf `main` Pflicht (`SATSAGE_HARD_TESTS=1`, CI, `pre-push` nach `main`). Skip hier ist begründet, kein Q2.
- `py` statt `python` auf Windows. Bei Netzwerk-Tests `.env` laden via `_load_dotenv()`.
- Wenn ein Symbol das Modul wechselt, zeigen Tests auf das Modul, in dem der Name nachgeschlagen wird. Die Fassade behält die Symbol-Identität (`fulcrum.X is core.fulcrum_*.X`). Siehe Modulgrenzen in [`../core/AGENTS.md`](../core/AGENTS.md).
- Core-RPC-Allowlist (Dealbreaker **T14**): neue Methode braucht Maintainer-Freigabe, Doku und Tests `tests/test_rpc_allowlist*.py`. Der Lauf gegen einen echten Node steht in `lab/regtest/scripts/verify_rpc_allowlist.py` und ist Teil des Regtest-Labors (jeder PR nach `main`). Die HART-Regel steht in der Root-Verfassung.
- Umfangreiche Testsuite: erst den Nutzer das Ziel prüfen lassen (Root-HART), dann nur auf Angebot starten.
