# AGENTS.md — Regtest-Lab

Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART.

Die portable Docker-/Linux-Anleitung liegt unter `lab/regtest/README.md`. `.data/` und Lab-Env bleiben lokal und sind nie zu committen.

- **Mainnet nie.** Lab/CI: **Regtest → Signet → Testnet nur Ausnahme**. Lab-Env getrennt von Prod-`.env` (kein eingebauter Multi-Chain-Schalter). Remote-Bot-Regeln: [`../GROK_BOT.md`](../GROK_BOT.md).
- Docker/Regtest-Lab hochfahren ist der Prüfweg auf **macOS, Linux und Grok-Bots**. **Windows:** kein Docker durch den Assistenten hochfahren.
- Vor dem Merge nach `main` und vor jedem Release (Tag `v*`, Image, Linux-Binary, StartOS-Paket): Unittests grün und Regtest-Labor grün (Workflow `Regtest-Labor`, Core + Electrs, `verify_rpc_allowlist.py`, `verify_tx_classify.py` und `verify_sanctions_hops.py`). Wochenlauf auf `dev-juniormind` nur, wenn der Prüfpfad seit dem letzten grünen Labor geändert wurde.
- Umfangreiche Labor-Läufe: erst den Nutzer das Ziel prüfen lassen (Root-HART), dann nur auf Angebot starten.
