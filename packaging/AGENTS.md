# AGENTS.md — Packaging (PyInstaller, StartOS, Umbrel)

Gilt für `packaging/` und die Build-Skripte, die diese Specs aufrufen. Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART.

## Standalone-Build (PyInstaller)

Web-GUI als Onefile-Binary:

```bash
./scripts/build_satsage_macos    # oder _linux
scripts\build_satsage_win.bat    # Windows (py / .venv)
```

Spec: `packaging/satsage-webgui.spec`. Die Build-Skripte setzen `SATSAGE_BINARY_NAME`: `dist/satsage-macos`, `dist/satsage-linux`, `dist/satsage-windows.exe`.  
Assets (`web/`, `data/`, `doc/`) über `resource_dir()`; `.env` und Caches neben der Executable (`app_dir()`).

`VERSION` im Repo-Root in `packaging/satsage-webgui.spec` als data bundeln. Bump nur der Maintainer (Root-Verfassung).

## StartOS-Sideload (`.s9pk`)

Wrapper liegt in **`packaging/`** auf Branch `main` — nicht auf `master`, nicht in einem Sibling-Repo. Bau-Anleitung für Bots: [`../doc/START9-packaging.md`](../doc/START9-packaging.md). Kurz: `./scripts/build_startos_s9pk` (x86_64). Vorhandenes Release: Tag `startos-tls11`.

**Nicht neu scaffolding.** App-Härtung nicht im Wrapper duplizieren. Release Notes zum StartOS-Tag: wie `doc/START9-packaging.md` + `publish_startos_release`.

## Umbrel-App (App Store)

Paket liegt in **`packaging/umbrel/`** (Manifest, Compose, `exports.sh`), Quelle der Wahrheit; der Store bekommt nur Kopien. Anleitung: [`../doc/UMBREL-packaging.md`](../doc/UMBREL-packaging.md). Modus `SATSAGE_MANAGED_BY=umbrel`; Image via Workflow `build-docker-image.yml` nach `ghcr.io` (amd64 + arm64).
