# Mitmachen

SatSage ist ein Analysewerkzeug: woher Sats kamen und wie lange sie on-chain lagen. Es signiert nicht und sendet keine Transaktionen. Neue Logik landet in der passenden Domäne, nicht in den Root-Fassaden. Die Grenzen stehen in [`AGENTS.md`](AGENTS.md) unter **Modulgrenzen**.

## Nichts Sensibles schicken

In Issues, Pull Requests, Logs und Screenshots gehören keine Seeds, xprv, WIF, XPUBs, Deskriptoren, Wallet-Namen, echten Adressen, TxIDs aus dem eigenen Bestand, `.env` oder Passwörter. Ein Fehler lässt sich mit Testdaten aus `.env.example` oder mit `lab/regtest/` beschreiben.

## Einrichten

```bash
git clone https://github.com/Juniormind1/SatSage.git
cd SatSage
python -m venv .venv
```

Windows: `.venv\Scripts\activate` und `py -m pip install -r requirements.txt`.  
Linux und macOS: `source .venv/bin/activate` und `pip install -r requirements.txt`.

`.env.example` nach `.env` kopieren, wenn du die Oberfläche lokal startest. Die Datei bleibt lokal.

## Tests ohne Node

Die Prüfungen unter `tests/` sollen ohne Electrs, ohne Bitcoin Core und ohne echte `.env` auskommen: erfundene Daten, nachgebaute Verbindungen. Was noch einen laufenden Node oder eine persönliche `.env` braucht, gehört nicht in diese Suite.

```bash
python -m unittest discover -s tests -t .
```

Windows: `py -m unittest discover -s tests -t .`

GitHub startet dieselbe Suite bei jedem Push und jedem Pull Request nach `dev-juniormind` und nach `main`. Grün heißt: der Lauf kam ohne Node und ohne persönliche `.env` durch. Der Browser-Klicklauf (`scripts/webgui_userflow.py`) bleibt lokal. Er braucht eine Oberfläche und ist nicht Teil dieser Suite.

## Regtest vor `main`

Ein Merge nach `main` setzt zusätzlich das Regtest-Labor voraus. GitHub startet dafür den Workflow `Regtest-Labor`: Bitcoin Core und Electrs in Docker, Lab-Szenarien, dann `verify_tx_classify.py` und `verify_sanctions_hops.py`. Der Lauf dauert deutlich länger als die Unittests. Er startet bei einem Pull Request nach `main` und bei einem Push nach `main`, nicht bei jedem Push nach `dev-juniormind`.

Lokal derselbe Kern, ohne den Mempool-Explorer:

```bash
cd lab/regtest
SATSAGE_LAB_SKIP_MEMPOOL=1 ./scripts/start.sh
python3 scripts/generate_scenarios.py
python3 scripts/generate_sanctions_scenarios.py
python3 scripts/verify_tx_classify.py
python3 scripts/verify_sanctions_hops.py
```

Windows bleibt bei `scripts/win/start_lab.ps1` (siehe [`lab/regtest/README.md`](lab/regtest/README.md)).

Regtest mit Docker steht in [`lab/regtest/README.md`](lab/regtest/README.md). Das ist extra und nicht die Voraussetzung für einen Pull Request.

## Branches und Pull Requests

`main` ist der stabile Stand. Laufende Arbeit geht nach `dev-juniormind` oder in einen eigenen Branch mit einem Pull Request dorthin.

Ein Pull Request ist der Vorschlag auf GitHub, Commits von deinem Branch zu übernehmen. GitHub zeigt den Unterschied und das Testergebnis. Merge erst, wenn die Suite grün ist.

Contributor committen unter dem eigenen Namen. Die Identität `Juniormind1` und die Hooks unter `githooks/` gelten nur für Maintainer-Rechner, nicht für Pull Requests.

## Was nicht hinein soll

- Seed, xprv oder eine Signatur in der Oberfläche
- Öffentliche Electrum-Server oder ein fernes Sprachmodell als stiller Standard
- Die Web-Oberfläche an eine andere Adresse als localhost binden, oder das Sitzungs-Token abschalten
- Skripte oder Schrift von einem fremden Server in `web/`
- Geheimnisse oder persönliche Wallet-Daten im Commit
