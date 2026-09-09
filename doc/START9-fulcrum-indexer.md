# Start9 · Electrum-Indexer: Electrs oder Fulcrum

**Stand:** 2026-09-09 · Vorbereitung für Issue „Fulcrum als Electrum-Datenquelle“  
**Bezug:** [`ISSUES.md`](../ISSUES.md), [`START9-packaging.md`](START9-packaging.md), Vorbild [mempool-startos Select Indexer](https://github.com/Start9Labs/mempool-startos)

## Ziel

SatSage auf StartOS soll denselben Electrum-Protokoll-Pfad (`FULCRUM_HOST` / Port, SSL aus auf der Bridge) wahlweise an **electrs** oder **Fulcrum** hängen — nicht nur hart an `electrs-startos`.

## Gewähltes Modell (wie Mempool)

**Explizite Auswahl in der StartOS-GUI**, nicht stilles Auto-Detect:

| Mechanismus | Rolle |
|-------------|--------|
| `store.json` → `indexer`: `"electrs"` \| `"fulcrum"` | Dauerhafte Wahl auf dem Service-Volume |
| Action **Select Indexer** | Formular in StartOS (Fulcrum empfohlen / Electrs) |
| `dependencies.ts` | Nur die gewählte Dep ist `kind: running` |
| `main.ts` / Bridge | `getBridgeAddress` auf `electrs`+`electrum` **oder** `fulcrum`+`main`, Port **50001** plaintext |
| Daemon-Env | `FULCRUM_HOST`/`FULCRUM_PORT`/`FULCRUM_SSL=false`, `SATSAGE_ELECTRUM_INDEXER=<wahl>` |

**Kein „None“:** SatSage braucht einen Indexer (anders als Mempool-Address-Lookup).

### Warum nicht zuerst Auto-Detect?

Beide Indexer können installiert sein; welcher „der richtige“ ist, ist eine Nutzerentscheidung (RAM/Disk: Fulcrum schwerer). Mempool löst das bewusst per Action. Auto-Detect (erster erreichbarer Bridge) bleibt optionale Stufe 2.

## Bridge-Adressen (StartOS-Konvention)

Wie in mempool-startos `utils.ts` (ohne npm-Import der Indexer-Packages):

| Indexer | `packageId` | `hostId` | `internalPort` |
|---------|-------------|---------|----------------|
| electrs | `electrs` | `electrum` | `50001` |
| fulcrum | `fulcrum` | `main` | `50001` |

SatSage spricht das Electrum-Protokoll ohnehin über denselben Client-Stack (`FULCRUM_*`); der Package-Name ist nur die Bridge-Quelle.

## Migrationspfad

- Bestehende Installs ohne `store.indexer`: **Default `electrs`** (heutiges Verhalten, kein Bruch).
- Manifest: beide Deps **optional**; `setupDependencies` aktiviert genau eine.
- npm: `fulcrum-startos` **nicht** nötig, solange Host-IDs literal bleiben (wie Mempool).

## App-Vertrag (`SATSAGE_MANAGED_BY=start9`)

Prozess-Env (vom Daemon, nicht in `.env` persistieren):

```text
SATSAGE_ELECTRUM_INDEXER=electrs|fulcrum
FULCRUM_HOST=<bridge-ip>
FULCRUM_PORT=<bridge-port>
FULCRUM_SSL=false
ELECTRS_HOST=<gleiche Bridge oder leer>   # Kompatibilität; App mappt bei Bedarf
```

UI: `own_fulcrum` / `own_core` bleiben read-only; `managed_hint` nennt den gewählten Indexer.

## Umsetzungsschritte

1. **Vorbereitung (dieser Stand):** Design + Packaging-Code + App-Hinweis/`api_config` + Unit-Tests ohne `.s9pk`-Bau.
2. **Build-Host:** `npm ci` in `packaging/`, `./scripts/build_startos_s9pk`, Sideload, Action „Select Indexer“, Scan gegen Fulcrum.
3. **Optional später:** Task erzwingen, wenn `indexer` fehlt (streng wie Mempool); Auto-Probe beider Bridges.

## Abgrenzung

- Kein zweiter Datenquellen-Editor in der SatSage-UI.
- Clearnet-/Tor-Fulcrum-Onions bleiben Desktop-Thema; Start9-Managed nur lokale Bridge.
- Community-Paket **fulcrum** (Start9Labs/`fulcrum-startos`) muss auf dem Gerät installierbar sein.
