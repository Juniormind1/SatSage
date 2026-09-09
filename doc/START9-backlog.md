# Start9 â€” Hardening- & Packaging-Backlog

**Stand:** 2026-09-06 Â· Ableitung aus [`START9-hardening.md`](START9-hardening.md).  
IDs = Tracking; Reihenfolge = empfohlene Umsetzung. Phase 0 und Phase 1 (S1 Auth) sind umgesetzt; weitere Phasen folgen.

Legende Status: `todo` Â· `doing` Â· `done` Â· `blocked`

---

## Phase 0 â€” Fundament (Blocker fÃ¼r Sideload)

| ID | Status | Aufgabe | Akzeptanz |
|----|--------|---------|-----------|
| S0-1 | done | Bind-Modus: `loopback` (Default) vs `container`/`0.0.0.0` per Env/Flag | Mit `SATSAGE_BIND=0.0.0.0` lauscht Server; Default unverÃ¤ndert 127.0.0.1 |
| S0-2 | done | `_host_ok` erweitern: konfigurierbare Allowlist + Start9-Hostnames (`.local`, LAN-IP, Onion, `X-Forwarded-Host` nur wenn Proxy-Trust-Flag) | Loopback-Hosts weiter ok; fremder Host ohne Allowlist â†’ 403; Start9-UI erreichbar |
| S0-3 | done | Kein â€žlocalhost Auth-Bypassâ€œ wenn Request vom Proxy kommt | Auth immer erforderlich auÃŸer explizitem Health ohne Daten |
| S0-4 | done | Health-Endpoint ohne Wallet-Daten (z. B. `/api/health`) fÃ¼r StartOS Checks | 200 + Version; kein XPUB/UTXO |

## Phase 1 â€” Auth (H1/H2/H4/H7)

| ID | Status | Aufgabe | Akzeptanz |
|----|--------|---------|-----------|
| S1-1 | done | Persistentes Passwort (Argon2id; scrypt-Stdlib-Fallback) in Volume; Setup beim Erststart | Restart behÃ¤lt Login |
| S1-2 | done | Session-Cookie HttpOnly + Secure(+SameSite); **Token aus URL entfernen** | GUI ohne `?t=`; API per Cookie oder `X-Satsage-Token` |
| S1-3 | done | Origin/CSRF-Check fÃ¼r mutierende Methoden | Cross-Site POST ohne Token abgelehnt |
| S1-4 | done | Static/Handbuch hinter Auth, wenn Passwort gesetzt und Host nicht Loopback | Unauth â†’ Redirect Login |
| S1-5 | partial | Start9-Wrapper soll `addSsl.auth` nutzen; Integration bleibt Wrapper-Ticket | Notiz in Hardening-Doku |
| S1-6 | done | In-Memory-Rate-Limit Login (5 / 15 min / IP) | Brute nach N Fehlversuchen gedrosselt |

## Phase 2 â€” Outbound / SSRF (H5)

| ID | Status | Aufgabe | Akzeptanz |
|----|--------|---------|-----------|
| S2-1 | done | Allowlist-Policy fÃ¼r Fulcrum/Mempool/LLM/SMTP (loopback / .onion / private / public+Opt-in) | Public ohne Opt-in abgelehnt |
| S2-2 | partial | Start9-Dependencies: `bitcoind` + `electrs` (oder Fulcrum) per Bridge; Cookie RO-Mount | Kein freier RPC-Host nÃ¶tig im Default-Pfad |
| S2-3 | done | Config-UI: im Start9-Modus Node-Felder read-only / ausgeblendet, Status aus Dependency | User Ã¤ndert Backend nur Ã¼ber StartOS-Deps |
| S2-4 | done | LLM: Default loopback; Remote nur mit Opt-in (bereits teilweise) â€” Tests + Start9-Hinweise | Gleiches Verhalten wie Desktop, dokumentiert |

## Phase 3 â€” Betrieb / DoS (H6/H8/H9)

| ID | Status | Aufgabe | Akzeptanz |
|----|--------|---------|-----------|
| S3-1 | done | Job-Quotas (parallele Scans, Timeout, Abbruch) | DoS durch Massen-Jobs begrenzt |
| S3-2 | done | Keine Secrets in Query-Strings/Logs; Session nur Volume | `?t=` weg; Logs ohne Token |
| S3-3 | done | Backup-Volumes dokumentiert; Wrapper-`instructions.md` bleibt partial | App-Doku done, Wrapper-Ãœbernahme partial |

## Phase 4 â€” Packaging-Wrapper

| ID | Status | Aufgabe | Akzeptanz |
|----|--------|---------|-----------|
| S4-1 | doing | Package-Root `packaging/` in diesem Repo (0.4 SDK + Dockerfile + `make x86`) | `./scripts/build_startos_s9pk` â†’ `satsage_x86_64.s9pk`; Anleitung `doc/START9-packaging.md` |
| S4-2 | done | Dockerfile/Image pin + x86_64 und aarch64 nur wenn gebaut | Manifest stimmt mit Image Ã¼berein |
| S4-3 | done | Interfaces: UI mit `addSsl.auth`; interne Ports bridge-only | Kein Roh-RPC exportiert |
| S4-4 | done | Health: Prozess + optional Electrs-Dependency-Health | StartOS zeigt grÃ¼n wenn nutzbar |
| S4-5 | done | `README.md` + `instructions.md` (kein â€žist auf Torâ€œ) | Review-Checkliste Docs |
| S4-6 | done | E2E auf StartOS: Install, Login, Wallet-Scan gegen Electrs-Dep, Backup/Restore, Uninstall â€” Maintainer-Sideload mit Release **0.9** durchgeklickt (Passwort einmal via StartOS Basic Auth / Proxy-Session; Electrs+Core-Bridge auto; Bridge-Einstellungen gesperrt/ausgeblendet) | Protokoll abgehakt; GerÃ¤tetest 2026-09 |
| S4-7 | todo | Einreichung `submissions@start9.com` â†’ Community-Fork â†’ beta â†’ promote | Package in community-beta |

## Phase 5 â€” Nice-to-have

| ID | Status | Aufgabe | Akzeptanz |
|----|--------|---------|-----------|
| S5-1 | todo | Security.txt / SECURITY.md im Wrapper | Meldeweg klar |
| S5-2 | todo | Automatisierte Auth-/SSRF-Regressionstests | CI grÃ¼n |
| S5-3 | todo | Specter-Modus und Start9-Modus teilen â€žmanaged settingsâ€œ-Flag | Eine Code-Pfad-Abstraktion |

---

## Schnellreferenz PrioritÃ¤t

1. S0-1â€¦S0-6 (Loopback+Proxy bevorzugen; sonst kein sinnvoller Sideload)  
2. S1-1â€¦S1-5 (sonst Token-Leak / offene UI)  
3. S2-1â€¦S2-3 (SSRF + Dependencies)  
4. S4-* parallel sobald S0+S1 greifbar  
5. S3 + S5 nachziehen  

## Abgrenzung

- Kein Push von Prod-Secrets; kein Bot-Mainnet (`GROK_BOT.md`).
- Community Registry â‰  Start9-Support.

## Nachtrag Review (zusÃ¤tzliche Tickets)

| ID | Status | Aufgabe | Akzeptanz |
|----|--------|---------|-----------|
| S1-7 | done | Query-Token nur einmaliger Bootstrap; danach Header/Cookie | Erster Load optional `?t=`; Redirect entfernt Token |
| S2-5 | done | Core-/Fulcrum-TLS: Zertifikate validieren oder dokumentierte Pinning-/CA-Ausnahme | Kein stilles `CERT_NONE` in Prod/Start9-Default |
| S3-4 | done | ZIP-Entpackgrenzen (GesamtgrÃ¶ÃŸe, Dateianzahl, Ratio) fÃ¼r Labels/Sanktionen | Bomben werden abgewiesen |
| S3-5 | done | Generische API-500er nach auÃŸen; Details nur Log | Client sieht keine internen Pfade |
| S3-6 | done | Beim Start `.env`-Modus prÃ¼fen/korrigieren (`0600`); `.env.bak` ebenso | Zu offene Datei â†’ Warnung + chmod |
| S0-5 | done | Start9-Default: App-Bind `127.0.0.1`, Proxy davor; `0.0.0.0` nur Opt-in | Manifest/instructions beschreiben Loopback+Proxy |
| S0-6 | done | Host-Header/IPv6 robust parsen; `X-Forwarded-*` nur mit `SATSAGE_TRUST_PROXY=1` | Spoof ohne Trust-Flag wirkungslos |


### S4 scaffold review (2026-09-07)

- S4-1: wrapper is `packaging/` in this repo on `main` (not a sibling `satsage-startos`). `make x86` still needs Docker, Node 22, `start-cli`, and a `.startos/` workspace key.
- S4-2 through S4-5: Dockerfile/entrypoint, UI+Basic-auth, health, instructions.md; only x86_64 until an ARM image exists.
- S4-6 **done** (2026-09): Maintainer E2E on device with GitHub/App **0.9** sideload — single password gate (StartOS `addSsl` Basic Auth + `X-Forwarded-User` → SatSage session), bitcoind/electrs bridges from StartOS deps, UI/API locks for `own_fulcrum`/`own_core`. S4-7 remains todo (Community submission not started).
