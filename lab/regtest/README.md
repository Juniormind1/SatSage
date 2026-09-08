# SatSage-Regtest-Labor

Dieses Verzeichnis enthält ein **secrets-freies, portables Regtest-Labor** für SatSage. Es ist kein Mainnet-Node und keine Verbindung zu einem Heim-Node. Bitcoin-Core-Daten, Electrum-Index (Electrs oder Fulcrum), generierte XPUBs und Szenario-Reports bleiben lokal unter `lab/regtest/.data/`; sie werden niemals gepusht. Portable Binaries liegen unter `lab/regtest/.tools/` (ebenfalls gitignore).

Die Arbeitsregeln stehen in [`../../GROK_BOT.md`](../../GROK_BOT.md). Für die Lab-Anbindung: `NETWORK=regtest` in der generierten `.regtest.env` setzt das Adressnetz (`bcrt1…`); SatSage startet mit `py server.py --env lab/regtest/.data/.regtest.env`. Lab-Caches getrennt von Mainnet halten (`--cache-dir` / `--immutable-cache-dir`).

**Assistent (optional):** Die Lab-Env setzt Ollama-Loopback (`LLM_ANBIETER=ollama`, `LLM_MODELL=qwen2.5:0.5b`, `http://127.0.0.1:11434/v1`). Ollama und das Modell müssen auf dem Host laufen (`ollama pull qwen2.5:0.5b`); sonst bleibt die LLM-Pille unerreichbar. Bei `run_scenarios` / `write_env` werden die LLM-Zeilen mitgeschrieben.

## Windows (portable bitcoind + Fulcrum, ohne Admin)

Bevorzugter Weg ohne Docker: Bitcoin Core und Fulcrum als ZIP unter `.tools/`, Daten unter `.data/`. Nur Loopback (RPC `127.0.0.1:18443`, Electrum `127.0.0.1:50001`), kein WAN-Sync.

```powershell
cd lab\regtest
powershell -ExecutionPolicy Bypass -File .\scripts\win\setup_tools.ps1   # einmalig (~130 MB)
# Alles: bitcoind + Fulcrum + Szenarien + GUI + Browser (Edge/Chrome/Firefox)
powershell -ExecutionPolicy Bypass -File .\scripts\win\start_lab.ps1
# Stop:
powershell -ExecutionPolicy Bypass -File .\scripts\win\stop_lab.ps1
```

`start_lab.ps1` öffnet die SatSage-GUI mit **Token-URL** im ersten gefundenen Browser (Edge → Chrome → Firefox → System-Default). Die URL liegt zusätzlich in `.data/gui-url.txt`. Optional Playwright-Verify (`verify_gui.py`, braucht `pip install playwright` + `playwright install chromium`).

Einzelschritte falls nötig: `start.ps1` (nur Chain), `run_scenarios.ps1`, `start_gui.ps1` (GUI±Browser), `status.ps1`.

Endpunkte nur Loopback: RPC `127.0.0.1:18443` (user/pass `bitcoin`/`secret`), Electrum `127.0.0.1:50001` ohne SSL, GUI `127.0.0.1:8730/?t=…`.  
Chain zurücksetzen: `stop_lab.ps1`, dann `lab/regtest/.data/` löschen (`.tools/` kann bleiben), erneut `start_lab.ps1`.

**Scan findet 0 UTXOs:** SatSage teilt `WALLET_n_MAX_ADDRESSES` auf Empfang und Change (`//2`). Lab-Default ist 400 (je 200). Liegen Coins auf höheren Indizes (mehrfaches `run_scenarios` mit altem `getnewaddress`), Limit anheben oder `.data/` neu aufbauen. Szenarien nutzen feste `deriveaddresses`-Indizes und schieben den Keypool nicht mehr.

## macOS (Grok Build)

1. Docker Desktop installieren und starten. Das Repo in Grok Build öffnen.
2. Im Repo-Terminal ausführen:

   ```bash
   cd lab/regtest
   chmod +x scripts/*.sh scripts/generate_scenarios.py
   ./scripts/start.sh
   ./scripts/generate_scenarios.py
   ```

   Docker ist der bevorzugte Mac-Weg. RPC ist nur unter `127.0.0.1:18443` erreichbar, Electrum nur unter `127.0.0.1:50001`.
3. Die generierte Datei `lab/regtest/.data/.regtest.env` kann lokal als SatSage-Lab-Konfiguration verwendet werden. Die Platzhalter-Vorlage ist [`.regtest.env.example`](.regtest.env.example).
4. Status und Logs:

   ```bash
   docker compose -f docker-compose.yml ps
   docker compose -f docker-compose.yml logs -f electrs
   ./scripts/stop.sh
   ```

Die Szenarien erzeugen vier Lab-Wallets sowie Hops, Selbstüberweisung, Konsolidierung, Fan-out und gealterte Coins. Dazu kommen zwei absichtlich strukturelle CoinJoin-ähnliche Transaktionen mit jeweils **24 Inputs und 28 Outputs** (gleichartige Outputs plus Change). Das ist keine Coordinator- oder WabiSabi-Implementierung, sondern reproduzierbares On-Chain-Testmaterial.

## Linux-Bot-Host

Auf einem Linux-Host ist der Docker-Ablauf identisch und ebenfalls empfohlen:

```bash
cd /workspace/xPubQuery/lab/regtest
./scripts/start.sh
./scripts/generate_scenarios.py
```

Wenn Docker fehlt, bleibt das Repository trotzdem nutzbar. Für einen nativen Core-Start kann das vorhandene Muster [`specter_plugin/scripts/run_bitcoind_regtest.sh`](../../specter_plugin/scripts/run_bitcoind_regtest.sh) als Referenz dienen; das Script in diesem Verzeichnis benötigt dann ein erreichbares `bitcoin-cli`:

```bash
SATSAGE_LAB_NATIVE=1 BITCOIN_CLI=/pfad/zu/bitcoin-cli \
  scripts/generate_scenarios.py --native
```

Falls nötig, kann zusätzlich Electrs nativ nach dem Muster des bestehenden Host-Labors (lokaler Regtest-RPC/P2P-Endpunkt, `127.0.0.1:50001`) gestartet werden. Keine Host-Datadir-, `secrets/`-, Seed- oder xprv-Datei wird aus dem Referenzlabor kopiert.

## Dateien und Sicherheit

- `docker-compose.yml`: lokaler bitcoind-Regtest plus Electrs (Mac/Linux).
- `scripts/win/`: portable bitcoind + Fulcrum unter Windows ohne Admin/Docker.
- `.regtest.env.example`: nur Platzhalter und absichtlich harmlose Lab-Defaults (`bitcoin`/`secret`).
- `scripts/generate_scenarios.py`: signiert mit lokalen Core-Testwallets, exportiert nur öffentliche XPUB-Daten; setzt `NETWORK=regtest`.
- `.data/`, `.tools/` und `.regtest.env` sind in `.gitignore`; Chain-Daten und Binaries nie committen.
- `./scripts/stop.sh` bzw. `scripts/win/stop.ps1` beenden nur die Dienste; zum Löschen lokaler Chain-Daten `.data/` ausdrücklich selbst entfernen.
