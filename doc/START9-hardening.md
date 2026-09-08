# Start9 Community Package â€” HÃ¤rtung & Netzmodell

**Stand:** 2026-09-06 Â· Ziel: SatSage als Start9-Community-Package, sicher jenseits von `127.0.0.1`.  
**Backlog:** [`START9-backlog.md`](START9-backlog.md) Â· **Einreichung:** siehe Abschnitt â€žCommunity Packageâ€œ.  
**UX-Leitbild Node:** [`design-node-anbindung.md`](design-node-anbindung.md) â€” HÃ¤rte hier darf Desktop-LAN und Bridge-Komfort nicht kollateral zerstÃ¶ren.

SatSage rekonstruiert On-Chain-Herkunft aus XPUBs/Deskriptoren â€” kein Seed, kein Signieren. Trotzdem enthÃ¤lt die GUI Wallet-Metadaten, UTXOs, Verlauf, Steuer und Config-APIs. Loopback-only war das Vertrauensmodell; Start9 Ã¤ndert das.

---

## 1. Ist-Zustand (Desktop / Lab)

| Mechanismus | Heute |
|-------------|--------|
| Bind | fest `127.0.0.1` (`BIND_HOST` in `server.py`) |
| Host-Check | nur `localhost` / `127.0.0.1` / `::1` (`_host_ok`) â€” DNS-Rebinding-Schutz |
| Auth | Session-Token pro Prozess (`secrets.token_urlsafe`); Header `X-Satsage-Token` oder Query `?t=` |
| Static / Handbuch | ohne Token, solange Host passt |
| TLS | keines in der App (fÃ¼r Loopback ok) |
| Rate-Limit / CSRF / Login | nicht vorhanden |
| Outbound | Fulcrum/Mempool/LLM/SMTP konfigurierbar; LLM mit `LLM_REMOTE_OPT_IN` |

**StÃ¤rke:** Fremde Hosts erreichen die Socket nicht.  
**Bruch mit Start9:** Reverse-Proxy liefert LAN/`.local`/Onion-Hosts â†’ `_host_ok` wÃ¼rde 403 liefern; Token-in-URL und fehlendes persistentes Login reichen fÃ¼r Netz-Exposure nicht.

---

## 2. Bedrohungsmodell hinter Start9

StartOS terminiert TLS am Edge, proxyt intern oft HTTP zum Container. Der User entscheidet Gateways (LAN default an, Public-IPv4 default aus, Tor opt-in). Das Package darf **nicht** behaupten, es sei â€žauf Tor/Internetâ€œ.

Angreifer-Klassen nach Exposure:

1. **LAN-Mitbewohner / kompromittiertes GerÃ¤t** â€” UI/API erreichbar
2. **Tor-Beobachter / Link-Leak** â€” wenn Onion aktiv und URL/Token geleakt
3. **Cross-Site / Browser** â€” Token in URL â†’ History, Referer, Screenshots
4. **Authentifizierter Missbrauch** â€” Config-APIs als SSRF in LAN/Tor/Clearnet
5. **DoS** â€” schwere Scans/Jobs ohne Quota

---

## 3. SchwÃ¤chen (priorisiert)

| Prio | ID | SchwÃ¤che | Wirkung |
|------|-----|----------|---------|
| Kritisch | H1 | Token in URL (`?t=`) | Leak Ã¼ber History, Referer, Logs, geteilte Links |
| Kritisch | H2 | Nur ephemeres Token, kein User-Passwort | Kein robustes Login Ã¼ber Restarts / Multi-Device |
| Hoch | H3 | `_host_ok` nur Loopback | Start9-UI unbenutzbar ohne Umbau; falsch erweitert = Rebinding-Risiko |
| Hoch | H4 | Static ohne Auth | UI-Shell Ã¶ffentlich (API weiter gated) |
| Hoch | H5 | Config â†’ Outbound-URLs (Fulcrum, Mempool, LLM, SMTP) | SSRF / Exfil nach Auth |
| Hoch | H6 | Volle Wallet-/Trace-/Steuer-APIs nach Token-Diebstahl | XPUB-Metadaten, Historie, Labels |
| Mittel | H7 | Kein CSRF/Origin jenseits Host | Mit geleaktem Token: Cross-Site-Mutationen |
| Mittel | H8 | Keine Rate-Limits / Job-Quotas | Brute/DoS auf Scans |
| Mittel | H9 | Session-Datei auf Disk | Backups/Shared-Host; in Container anders lÃ¶sen |
| Niedrig | H10 | Path-Traversal Static | weitgehend abgefangen (`is_relative_to`) â€” beibehalten |
| Niedrig | H11 | LLM Remote-Opt-in schon da | Vorbild fÃ¼r andere Outbound-Pfade |
| Hoch | H12 | Core-/Fulcrum-TLS mit `CERT_NONE` / ohne Hostname-Check | MITM trotz â€žSSL anâ€œ |
| Hoch | H13 | ZIP-/Base64-Importe ohne Entpack-Grenzen | ZIP-Bomben / RAM-DoS (tokenpflichtig) |
| Mittel | H14 | 500er mit Exception-Text an Client | Pfad-/Host-Leaks in Fehlern |
| Mittel | H15 | `.env`/`.env.bak`-Modus wird beim Start nicht geprÃ¼ft | zu offene Secrets-Datei bleibt so |
| Mittel | H16 | Host-Parsing per `.split(":")[0]` | IPv6-Hosts falsch; bei Ã¶ffentlichem Bind ist Host sowieso spoofbar |
| Niedrig | H17 | Kein `frame-ancestors` / `X-Frame-Options` | Specter-iframe bewusst; Clickjacking sonst offen |

---

## 4. Fix-Richtung mit Pro/Con vs. Loopback-only

### A. Start9 `addSsl.auth` (Basic oder Bearer) am Proxy

- **Pro:** Plattform-Standard; Creds rotierbar per Action; Requests ohne Auth erreichen den Container nie.
- **Contra:** Basic-UX; speichert Browser-Creds; allein kein Schutz gegen XSS in der App.
- **vs Loopback:** Netz-Pfad existiert, aber Edge-Gate; Loopback bleibt enger.

### B. Persistentes App-Login (Argon2/Passwort) + HttpOnly-Cookie; Token aus URL entfernen

- **Pro:** Kein Referer-Leak; Restart-stabil; CSRF mit SameSite + Origin.
- **Contra:** Mehr Code/UX; Cookie-Diebstahl bei XSS; Reset-Action nÃ¶tig.
- **vs Loopback:** FÃ¼r Remote nÃ¶tig; lokal war URL-Token â€žok genugâ€œ.

### C. Container-Bind `0.0.0.0` + Host-Allowlist fÃ¼r Start9-Adressen / `X-Forwarded-Host`

- **Pro:** Funktioniert hinter Reverse-Proxy; Rebinding weiter begrenzt.
- **Contra:** Allowlist muss mit LAN/`.local`/Onion mithalten; Fehlkonfig = 403 oder Bypass.
- **vs Loopback:** Bewusster Trade Erreichbarkeit â†” strengeres Host-Modell.

### D. Defense-in-Depth: Proxy-Auth **und** App-Session (Empfehlung)

- **Pro:** Gestohlenes Cookie ohne Proxy-Cred nutzlos und umgekehrt.
- **Contra:** Doppelte Reibung; mehr Testmatrix.

### E. Outbound-Allowlists + Start9-Dependencies (`bitcoind` / `electrs`)

- **Pro:** SSRF stark reduziert; Bridge statt freier Host-Tippei; Review-freundlich.
- **Contra:** Weniger â€žbring your own onionâ€œ ohne Opt-in.
- **vs Loopback:** Lokal war SSRF meist gegen dich selbst; remote kritisch.

### F. Rate-Limits, Job-Quotas, keine Secrets in GET

- **Pro:** DoS und Log-Leaks runter.
- **Contra:** Aufwand; False Positives.

### G. Bridge-only fÃ¼r interne Ports; keine Public-/Tor-Behauptungen in Docs

- Entspricht Start9-Interfaces-Doku. User schaltet Gateways.

**Pragmatische Reihenfolge:** C+A â†’ B (Token aus URL) â†’ E+Dependencies â†’ F â†’ optional D festziehen.

### Nuancen aus Code-Review (2026-09-06)

- Die GUI liest `?t=` einmal, legt das Token in `sessionStorage` und entfernt es per `history.replaceState` aus der Adresszeile (`web/app.js`). **Bootstrap-Leak** (History vor Replace, Referer beim ersten Load, Specter-iframe-URL) bleibt relevant.
- `starte_im_hintergrund(..., bind=...)` existiert, CLI hat **kein** `--bind` â€” absichtlich schwer, versehentlich Ã¶ffentlich zu binden.
- Bei **Ã¶ffentlichem** Bind ist `_host_ok` **kein** Zugriffsschutz: Clients kÃ¶nnen `Host: 127.0.0.1` spoofen. Host-Allowlist nur hinter **vertrauenswÃ¼rdigem** Proxy sinnvoll (Proxy setzt/normalisiert Host bzw. App trustet nur `X-Forwarded-*` mit Trust-Flag).
- **Bevorzugtes Start9-Muster:** Container/App weiter auf `127.0.0.1` binden; StartOS-Proxy terminiert TLS und proxied nur lokal. `0.0.0.0` nur wenn das Plattform-Modell es zwingt â€” dann Phase S0+S1 vollstÃ¤ndig.


---

## 5. Start9-Betriebsmodell (Soll)

```
Browser â”€â”€TLSâ”€â”€â–¶ StartOS Proxy (addSsl.auth)
                    â”‚ HTTP intern
                    â–¼
              SatSage Container (:8730, 0.0.0.0)
                    â”‚ Bridge
                    â”œâ”€â”€ electrs.startos / bitcoind.startos (RO cookie)
                    â””â”€â”€ optional LLM nur loopback/lan + Opt-in
```

- Absolute Browser-URLs als `https://` hardcoden (Container sieht intern HTTP).
- Keine â€žlocalhost bypassâ€œ-Logik fÃ¼r Auth behalten.
- Tor nicht vom Package provisionieren; nur dokumentieren, dass der User es anschalten kann â€” App muss dafÃ¼r trotzdem safe sein.

---

## 6. Community Package â€” Einreichung (0.4.x)

Quellen: [Publishing](https://docs.start9.com/packaging/0.4.0.x/publishing.html), [Quick Start](https://docs.start9.com/packaging/0.4.0.x/quick-start.html), [Interfaces](https://docs.start9.com/packaging/0.4.0.x/interfaces.html), [Outbound](https://docs.start9.com/packaging/0.4.0.x/outbound-networking.html), [Web-UI](https://docs.start9.com/packaging/0.4.0.x/recipe-web-ui.html).

1. Ã–ffentliches Wrapper-Repo (`satsage-startos`), SDK 0.4.x, `instructions.md`, LICENSE, Icon â‰¤40â€¯KiB.
2. Lokal `.s9pk` bauen, auf StartOS sideload/install, E2E (Install, UI, Health, Uninstall, Backup).
3. Mail an **submissions@start9.com** mit Repo-Link.
4. Start9 forkt nach **Start9-Community**; Review als PR am Fork.
5. Ab dann PRs nur gegen den Fork â†’ Merge â†’ **community-beta** â†’ Soak â†’ Promotion nach **community**.

**Official vs Community:** Community = technische Aufnahme, **kein** Start9-Support/Empfehlung.

**Vorbilder:** [canary-startos](https://github.com/Start9-Community/canary-startos) (UI+Auth+Electrum-Dep), [electrs-startos](https://github.com/Start9-Community/electrs-startos) (Bridge, Cookie, Sync-Health).

---

## 7. Abgrenzung

- **Kein Mainnet-Bot-Betrieb** laut `GROK_BOT.md` â€” Packaging/HÃ¤rtung ist Code+Doku; Live-Mainnet-Scans bleiben Maintainer/StartOS-User.
- Specter-Plugin und Start9 sind parallele Distributionswege; Specter bleibt Loopback/iframe-Modell (eigener Testplan).

### Implementiert in Phase S0

FÃ¼r Start9 bleibt der sichere Default der Bind auf `127.0.0.1` hinter dem StartOS-Proxy. Ein Container-Bind auf `0.0.0.0` ist nur opt-in Ã¼ber `SATSAGE_BIND` oder `--bind`; bei abweichenden Proxy-Hosts muss `SATSAGE_HOST_ALLOWLIST` (kommagetrennt, etwa `*.local` oder `*.onion`) gesetzt werden. `X-Forwarded-Host` und `X-Forwarded-Proto` werden nur bei `SATSAGE_TRUST_PROXY=1` berÃ¼cksichtigt. `GET /api/health` liefert ohne Token nur Status, Version und Verwaltungsmodus; alle anderen `/api/*`-Routen bleiben tokenpflichtig.

### Implementiert in Phase S1

- Ein Passwort wird als Argon2id-Hash (Dependency `argon2-cffi`) in `.satsage-password` neben der `.env` gespeichert, mit Modus `0600`; Minimalinstallationen nutzen den dokumentierten scrypt-Stdlib-Fallback. Die `.env` enthÃ¤lt kein Klartext-Passwort.
- Ohne Passwort-Datei bleibt das bisherige Token-Modell aktiv. Mit Passwort gilt: Loopback/Specter darf das Prozess-Token weiter nutzen; bei nicht-Loopback-Hosts ist eine Passwort-Session erforderlich. `POST /api/auth/setup` richtet das Passwort erstmals ein, `POST /api/auth/login` meldet an, `POST /api/auth/logout` lÃ¶scht das Cookie, und `POST/PUT /api/auth/password` Ã¤ndert es.
- Der Bootstrap `?t=` setzt ein `HttpOnly; SameSite=Lax`-Cookie und antwortet fÃ¼r GUI/static mit Redirect ohne Token. Die API akzeptiert danach Cookie oder `X-Satsage-Token`; ein Query-Token reicht bei gesetztem Passwort nur von Loopback.
- Mutierende Cookie-Anfragen brauchen `Origin`/`Referer`; ein gÃ¼ltiger `X-Satsage-Token` ist der explizite CSRF-Schutz fÃ¼r Scripts. Login-Fehler sind auf 5 je IP in 15 Minuten begrenzt. `/api/health` bleibt ohne Login datenarm offen.
- FÃ¼r das spÃ¤tere Start9-Wrapper-Repo muss die Web-UI zusÃ¤tzlich mit `addSsl.auth` (Basic oder Bearer) versehen werden; diese Phase Ã¤ndert keinen Wrapper.

### Implementiert in Phase S2 â€” Outbound / SSRF

- Alle konfigurierbaren Fulcrum-, Core-, Mempool-, LLM- und SMTP-Ziele laufen durch eine zentrale Allowlist: Loopback, private Netze und `.onion` sind standardmÃ¤ÃŸig erlaubt; Ã¶ffentliche Clearnet-Ziele brauchen `SATSAGE_OUTBOUND_PUBLIC_OPT_IN=1`. Die PrÃ¼fung erfolgt beim Speichern und direkt vor dem Connect.
- `LLM_REMOTE_OPT_IN=1` bleibt das LLM-spezifische Opt-in und wird von derselben Policy ausgewertet. Ohne Opt-in bleibt der LLM-Default Loopback.
- `SATSAGE_MANAGED_BY=start9` oder `SATSAGE_START9=1` aktiviert den Start9-Modus. `BITCOIND_HOST` und `ELECTRS_HOST` werden als nicht persistierte Bridge-Aliase genutzt; Node-/DatenquellenÃ¤nderungen sind in der API gesperrt und in der UI ausgeblendet. Mempool, LLM und Status-Mail bleiben separat konfigurierbar und unterliegen der Allowlist.
- Core-/Fulcrum-TLS: Ã¶ffentliche Clearnet-Hosts validieren Zertifikate; private/LAN/Loopback/Onion behalten die Desktop-Praxis ohne CA-PrÃ¼fung (Start9-LAN-Self-Signed). Der Sideload setzt `FULCRUM_SSL=false` auf der Bridge. `SATSAGE_TLS_INSECURE=1` ist die Ausnahme fÃ¼r Ã¶ffentliche Self-Signed-Ziele.
- Der Cookie-RO-Mount fÃ¼r den Bitcoin-Core-RPC und die eigentliche StartOS-Bridge bleiben Wrapper-Arbeit in S4; diese Phase verdrahtet nur die App-seitigen Hooks.

### Phase S3 â€” Betrieb / DoS

- Schwere Hintergrundjobs sind Ã¼ber `SATSAGE_MAX_PARALLEL_JOBS` begrenzt (Default 3); bei voller Belegung kommt HTTP 429. Die vorhandene Job-Abbruch-API bleibt der Abbruch-Hook.
- ZIP- und Base64-Importe werden vor dem Lesen auf GesamtgrÃ¶ÃŸe, Dateianzahl und KompressionsverhÃ¤ltnis begrenzt.
- `.env` und `.env.bak` werden beim Start auf Modus `0600` geprÃ¼ft und bei Bedarf korrigiert. Query-Tokens werden nicht in Zugriffslogs geschrieben; interne 500er bleiben serverseitig.

### S4 Wrapper pointer

The StartOS package lives **in this repository**: `packaging/` on `main` (SDK in `packaging/startos/`). There is no sibling `/workspace/satsage-startos`. How to build and publish: [`START9-packaging.md`](START9-packaging.md).
