# Umbrel-Paket (App Store)

**Für den nächsten Bot:** Das Umbrel-Paket liegt **in diesem Repo** unter `packaging/umbrel/` und ist die Quelle der Wahrheit. Der offizielle Store (`getumbrel/umbrel-apps`) und ein möglicher Community-Store bekommen jeweils nur Kopien dieser drei Dateien.

Referenz-Skills der Umbrel-Crew: `.claude/skills/umbrel-package-app`, `umbrel-update-app`, `umbrel-test-app` im Repo [`getumbrel/umbrel-apps`](https://github.com/getumbrel/umbrel-apps).

---

## Was wo liegt

| Pfad | Rolle |
|------|--------|
| `packaging/umbrel/umbrel-app.yml` | Manifest: Store-Metadaten, `port: 8732`, `dependencies: [electrs]`, `deterministicPassword` |
| `packaging/umbrel/docker-compose.yml` | `app_proxy` + Dienst `web`; Bridge-Env und Bootstrap-Passwort |
| `packaging/umbrel/exports.sh` | Erkennt die optionale `mempool`-App und setzt `APP_SATSAGE_MEMPOOL_URL` |
| `packaging/umbrel/data/.gitkeep` | Bind-Mount-Quelle `${APP_DATA_DIR}/data` für Erstinstallationen |
| `packaging/Dockerfile` | Gemeinsames Image für StartOS **und** Umbrel; Build-Kontext ist das Repo-Root |
| `.github/workflows/build-docker-image.yml` | Multi-Arch-Build (amd64 + arm64) → `ghcr.io/juniormind1/satsage` |

Das Image ist dasselbe wie für StartOS. Unterschiedlich ist nur die Prozess-Env, die die Plattform setzt.

---

## Laufzeit-Vertrag (`SATSAGE_MANAGED_BY=umbrel`)

Umbrel reicht diese Werte als Compose-Env herein; `AppState.env()` übernimmt sie in `runtime_values`, **ohne** sie in die `.env` des Nutzers zu schreiben:

```text
SATSAGE_MANAGED_BY=umbrel
SATSAGE_BOOTSTRAP_PASSWORD=${APP_PASSWORD}   # Umbrel zeigt den Wert in den App-Details
SATSAGE_HOST_ALLOWLIST=...                   # app_proxy reicht den Original-Host durch
FULCRUM_HOST/PORT/SSL                        # aus der electrs-Dependency
NODE_IP, RPCPORT, RPCUSER, RPCPASSWORD       # transitiv aus bitcoin
MEMPOOL_URL                                  # leer, wenn die mempool-App fehlt
```

Wirkung in der App: `own_fulcrum` und `own_core` sind in der Datenquellen-UI gesperrt (`_datenquellen_config_gesperrt`), `_managed_hint` erklärt warum, und `_seed_managed_password` legt den Passwort-Hash aus dem Bootstrap-Wert an.

**Warum trotz Umbrel-Login ein eigenes Passwort:** Der `app_proxy` schützt nur den Weg über den Browser. Jeder andere Container im `umbrel_main_network` erreicht `satsage_web_1:8730` direkt — und dort liegen XPUBs. `SATSAGE_TRUST_PROXY` wird deshalb **nicht** gesetzt; `_start9_proxy_authenticated` bleibt auf StartOS beschränkt.

**Warum nur `electrs` als Dependency:** Umbrel sourct auch die Exports transitiver Dependencies. `electrs` hängt selbst an `bitcoin`, also sind `APP_BITCOIN_*` verfügbar, ohne dass der Nutzer beim Install zwei Apps auswählen muss. `mempool` ist bewusst keine Dependency, sondern wird in `exports.sh` erkannt.

---

## Dev vs. Store-Release

Auf `dev-juniormind` zeigt `docker-compose.yml` absichtlich auf
`ghcr.io/juniormind1/satsage:latest` **ohne** Digest — floating Pin, kein
Store-Release. Der Image-Workflow taggt bei jedem Lauf zusätzlich `:latest`.
Für Gerätetests vor einem öffentlichen Image: `scripts/umbrel_dev_install`
(baut lokal und schreibt den Compose-Tag um).

Nächster Store-Stand: **0.9.6** beim Merge nach `main` (hier im Dev ist seit
0.9.2 viel passiert; 0.9.3–0.9.5 auf main waren Umbrel-only Pins).

## Ablauf für ein Release

1. `VERSION` und `CHANGELOG.md` hochziehen, Tag `vX.Y.Z` pushen.
2. Workflow **Build container image (multi-arch)** läuft an und schiebt
   `ghcr.io/juniormind1/satsage:X.Y.Z` (und `:latest`). Die Job-Summary nennt
   die fertige `image:`-Zeile inklusive Manifest-List-Digest.
3. Diese Zeile und `version:` in `packaging/umbrel/` eintragen (Digest-Pin,
   kein `:latest` mehr), `releaseNotes:` für bestehende Installationen schreiben.
4. Kopie in den Store bringen — siehe unten.

Wichtig: umbrelOS bietet ein Update nur an, wenn sich `version:` im Manifest ändert, und führt neuen Code nur aus, wenn zusätzlich Tag+Digest im Compose angepasst sind. Beides gehört in denselben Commit.

---

## Prüfen vor jedem Store-PR

```bash
# im Klon von getumbrel/umbrel-apps
rm -rf satsage && cp -r /pfad/zu/satsage/packaging/umbrel/. satsage/
npm install
npm run lint:apps -- satsage --check-images
git diff --check
```

`--check-images` zieht die Manifest-Liste und prüft `linux/amd64` + `linux/arm64`; ohne echten Digest schlägt das erwartungsgemäß fehl.

Laufzeittest gehört auf ein echtes umbrelOS (Skill `umbrel-test-app`): `electrs` installieren, Paket in die Store-Quelle spiegeln, `umbreld client apps.install.mutate --appId satsage`, dann im Browser Login → Wallet → UTXO-Scan → Neustart → Daten noch da.

---

## Store-Wege

| Weg | Merge | Tempo |
|-----|-------|-------|
| Community App Store (eigenes Repo) | selbst | sofort |
| Offizieller Store (`getumbrel/umbrel-apps`) | Umbrel-Team per PR | Review-abhängig |

### Community App Store

Nutzer fügen ihn in umbrelOS unter **App Store → Community App Stores** per Repo-URL hinzu — kein SSH nötig. Struktur laut Vorlage [`getumbrel/umbrel-community-app-store`](https://github.com/getumbrel/umbrel-community-app-store):

```text
umbrel-app-store.yml          # id + name, im Repo-Wurzelverzeichnis
<store-id>-satsage/           # Verzeichnisname = App-ID
  umbrel-app.yml              # `id:` muss exakt dem Verzeichnisnamen entsprechen
  docker-compose.yml
  exports.sh
```

Drei Fallstricke:

- umbrelOS liest nur den **Default-Branch** des Store-Repos. Ein Feature-Branch wird nicht gesehen.
- Die App-ID trägt das Store-Präfix (`juniormind-satsage`). Damit ändern sich auch der injizierte Containername (`APP_HOST`) und das Datenverzeichnis. Eine so installierte App ist eine **andere Identität** als `satsage` aus dem offiziellen Store — ein Wechsel migriert die Daten nicht.
- `icon:` und `gallery:` sind hier vollständige URLs. Offizielle Pakete lassen beides weg, weil Umbrel die Assets selbst hostet.

Den Store-Baum nicht von Hand pflegen, sondern aus `packaging/umbrel/` ableiten:

```bash
./scripts/build_umbrel_community_store juniormind
```

Das Ergebnis landet unter `build/umbrel-community-store/` (gitignored) und wird von dort ins Store-Repo committet.

**Nicht mit `rsync` spiegeln.** Ein Versionswechsel wie `0.9.4` → `0.9.5` und ein Digest-Wechsel sind byte-gleich lang, und `rsync` vergleicht standardmäßig nur Größe und Zeitstempel — es hält die Dateien für identisch und überträgt nichts. Das schlägt still fehl und veröffentlicht einen veralteten Stand. Entweder das Zielverzeichnis vorher löschen und neu kopieren, oder `rsync --checksum` verwenden. Gleiches gilt beim Spiegeln aufs Umbrel-Gerät zum Testen.
