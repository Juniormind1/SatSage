# StartOS-Paket bauen (Sideload `.s9pk`)

**FÃ¼r den nÃ¤chsten Bot:** Nicht von vorn anfangen. Das Sideload-Paket wird **in diesem Repo** gebaut, Branch `main`, Verzeichnis **`packaging/`**. Es gibt kein separates Ã¶ffentliches `satsage-startos`-Repo und kein `/workspace/satsage-startos` mehr.

Fertiges x86_64-Beispiel: GitHub-Release-Asset `satsage_x86_64-tls11.s9pk` (siehe Releases dieses Repos).

---

## Was wo liegt

| Pfad | Rolle |
|------|--------|
| `packaging/` | StartOS-**Package-Root** (wie `hello-world-startos/`) |
| `packaging/startos/` | SDK 0.4: Manifest, Daemon, Interfaces, Deps, Backup, Passwort-Action |
| `packaging/Dockerfile` | Python-Image; Build-Kontext ist das **Repo-Root** |
| `packaging/docker_entrypoint.sh` | `server.py` mit Volume `/data` |
| `scripts/build_startos_s9pk` | `make x86` inkl. Tool-Check |
| `scripts/publish_startos_release` | `gh release` mit `.s9pk` + SHA-256 |
| `.github/workflows/build-startos-s9pk.yml` | GHA nur manuell (`workflow_dispatch`); baut Artifact, hängt **nichts** an Releases — Upload mit `publish_startos_release` nach Test |
| `doc/START9-hardening.md` | App-HÃ¤rtung S0â€“S3 (Bind, Auth, Outbound) |
| `doc/START9-backlog.md` | Tickets; S4 = dieses Packaging |

Die Python-App bleibt im Repo-Root. `packaging/startos` importiert `bitcoin-core-startos` und `electrs-startos` (npm, GitHub). Electrum-Indexer zur Laufzeit: **electrs oder Fulcrum** (Action Select Indexer; Bridge-Host-IDs literal wie Mempool — kein npm-Import von `fulcrum-startos` nötig). Design: [`START9-fulcrum-indexer.md`](START9-fulcrum-indexer.md). Nur **x86_64** ist im Manifest deklariert.

`master` hat dieses Packaging **nicht**. Arbeiten und Releases laufen Ã¼ber **`main`**.

---

## Toolchain (einmalig auf der Build-Maschine)

Start9-Doku: [Environment Setup](https://docs.start9.com/packaging/environment-setup.html).

| Werkzeug | WofÃ¼r | Hinweis |
|----------|--------|---------|
| Docker (Daemon lÃ¤uft) | Image | `docker ps` muss klappen |
| Node.js **22+** / npm | SDK, `ncc` | z.â€¯B. `nvm install 22` |
| `make`, `jq` | `s9pk.mk` | |
| `mksquashfs` | Image-Pack | Debian: `squashfs-tools squashfs-tools-ng` |
| `start-cli` | pack/sign | `curl -fsSL https://start9.com/start-cli/install.sh \| sh` |
| `gh` | Release hochladen | optional; `~/.local/bin/gh` reicht |

Ohne sudo: `gh` und oft `start-cli` nach `~/.local/bin`. Node per nvm.

**Workspace:** `start-cli s9pk pack` sucht nach oben nach `.startos/` (Signing-Key). Das Skript legt bei Bedarf `.startos/` im **Repo-Root** an. **Nicht committen** â€” der Key ist geheim. `.gitignore` enthÃ¤lt `.startos/`.

---

## Paket bauen (x86)

Vom Repo-Root, Branch `main`:

```bash
git checkout master-dev-hh
./scripts/build_startos_s9pk
```

Ã„quivalent von Hand:

```bash
# einmal: Workspace (Repo-Root)
start-cli s9pk init-workspace .

cd packaging
npm ci
make x86          # â†’ packaging/satsage_x86_64.s9pk
```

Erstes `make x86` zieht das Python-Image und kann mehrere Minuten dauern. ARM: Manifest hat nur `x86_64`; `make arm` nicht verwenden, bis `arch` und ein ARM-Image existieren.

### Version

StartOS-Version steht in `packaging/startos/versions/current.ts` (`0.1.0:0` = upstream:revision). App-`VERSION` (0.9) ist unabhÃ¤ngig. Vor einem Update-Sideload die Package-Version anheben und alte Versionen in `versions/` behalten, sonst scheitert die Migration auf GerÃ¤ten mit dem vorherigen Paket.

---

## Sideload auf StartOS

1. StartOS im Browser â†’ **Sideload**.
2. `satsage_x86_64.s9pk` wÃ¤hlen.
3. **Bitcoin** und **Electrs** mÃ¼ssen auf dem GerÃ¤t laufen (Pflicht-Deps).
4. SatSage starten â†’ Web UI. Basic-Auth: User `admin`, Passwort aus den Service-Properties (oder Action *Rotate Web UI Password*, nur wenn der Dienst gestoppt ist).

Nicht behaupten, das Paket laufe â€žauf Torâ€œ. Gateways setzt der User in StartOS.

---

## Release schneiden

Voraussetzungen: gebautes `.s9pk`, `gh auth login` (Repo ist privat).

```bash
./scripts/build_startos_s9pk
./scripts/publish_startos_release startos-tls12
```

Ohne Argument wird `startos-YYYYMMDD` verwendet. Das Skript lÃ¤dt `.s9pk`, `.sha256` und eine kurze README hoch. Git-Tag nur mit:

```bash
./scripts/publish_startos_release --tag-head startos-tls12
```

(`--tag-head` forct den Tag auf HEAD und pusht ihn â€” nur nach ausdrÃ¼cklichem Maintainer-OK.)

CI: Workflow „Build StartOS s9pk“ nur manuell (`workflow_dispatch`) — Artifact zum Herunterladen, **kein** Release-Attach. Veröffentlichung nach Test: `./scripts/publish_startos_release`. Secret **`STARTOS_BUILD_KEY`** = Inhalt von `.startos/build.key.pem`. Ohne Secret schlägt `pack` fehl.

---

## Wenn etwas fehlt (typische Grok-Fallen)

| Symptom | Ursache |
|---------|---------|
| Kein `packaging/Dockerfile` / `Makefile` | Falscher Branch (`master` statt `main`) |
| Suche nach `/workspace/satsage-startos` | Veralteter Hinweis in Ã¤lteren Docs; Wrapper ist `packaging/` |
| `make: s9pk.mk not found` | `npm ci` in `packaging/` nicht gelaufen |
| `make` / pack: no workspace / no key | `start-cli s9pk init-workspace .` im Repo-Root |
| Docker permission denied | User in Gruppe `docker`, Daemon lÃ¤uft |
| Healthcheck rot | Bind/Proxy: Daemon setzt `SATSAGE_BIND=0.0.0.0`; Check gegen `127.0.0.1:8730/api/health` |
| App ohne Node | StartOS-Deps `bitcoind` + gewÃ¤hlter Indexer (`electrs` **oder** `fulcrum`) mÃ¼ssen running sein |
| Fulcrum statt Electrs | Action **Select Indexer** in SatSage; Fulcrum-Paket installieren/starten; siehe [`START9-fulcrum-indexer.md`](START9-fulcrum-indexer.md) |
| `gh: not logged in` | `gh auth login`; privates Repo |

App-Start im Container (schon im Entrypoint): `--env /data/.env`, Caches unter `/data`, `SATSAGE_MANAGED_BY=start9`, Cookie `/mnt/bitcoind/.cookie`. Das nicht in `server.py` â€žneu erfindenâ€œ.

---

## Checkliste nach App-Ã„nderung auf `main`

1. Start9-Verhalten (Bind, Auth, Bridges) in `tests/test_start9_phase_s*.py` grÃ¼n.
2. Package-Version nur anheben, wenn ein Update-Sideload gewollt ist.
3. `./scripts/build_startos_s9pk`
4. SHA-256 notieren, lokal sideloaden, Login + ein Wallet-Scan gegen Electrs.
5. `./scripts/publish_startos_release <tag>`
6. `CHANGELOG.md` unter `[UnverÃ¶ffentlicht]` bzw. mit Datum.

Kein automatisches `git commit` / `push` ohne Maintainer-Wortlaut.
