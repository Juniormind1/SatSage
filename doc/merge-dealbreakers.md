# Merge-Dealbreaker

Kriterien, die einen Merge nach `main` (und strenge Übernahme auf `dev-*`) verhindern oder zumindest ein klares Maintainer-Nein verlangen.

**Legende**

| Härte | Bedeutung |
|-------|-----------|
| **Hart** | Automatisch oder per Ruleset unterbinden (CI, Hooks, Branch-Protection) |
| **Hart+Review** | Wo möglich CI; sonst Maintainer-Block |
| **Weich** | KI-/Menschen-Review — kein automatischer Riegel |

Dieselbe Liste gilt als Leitplanke für Assistenten (Grok o. Ä.) und optional Copilot-Instructions. **CI-Checks für alle Hart-Punkte sind noch nicht vollständig verdrahtet** — die Suite (`Q1`) und die Identitäts-Hooks (`S2`) sind der Anfang.

Verankert in [`AGENTS.md`](../AGENTS.md) (Git / Sicherheit).

---

## 1 · Malware / Trust / Privatsphäre

| ID | Dealbreaker | Härte |
|----|-------------|--------|
| T1 | **Seed / Mnemonic / xprv / WIF** — jede Eingabe oder Abfrage (UI, API, Dialog, Chat, Locales, „Wiederherstellen“, „Support“) | Hart |
| T2 | **Wallet-Passwort / PIN** anderer Software in SatSage abfragen oder Klartext loggen | Hart |
| T3 | **XPUB / Deskriptor / Adresslisten leaken** an nicht konfigurierte Dritte (Telemetrie, Upload, Crash-Report mit Wallet, Cloud-LLM mit Rohdaten ohne Opt-in) | Hart |
| T4 | **Session-Token / `.env` / RPC-Secrets** auslesen und nach außen senden | Hart |
| T5 | **Bind ≠ Loopback** oder Auth/Token abschalten/umgehen (außer klarer Start9-/Specter-Managed-Pfad) | Hart |
| T6 | **Remote-JS / CDN / `eval` von Netz** in `web/` | Hart |
| T7 | **Download + Ausführen** von Code/Binary zur Laufzeit (URL-pip, Payload nach `tmp` + exec) | Hart |
| T8 | **Obfuscated Netz-/Backdoor-Muster** (sinnlose base64-Exfil, versteckte Hosts) | Hart+Review |
| T9 | **PSBT signieren / Raw-Tx broadcasten** in der Produkt-UI (Analyse-Tool bleibt extern signierend; Lab nur explizit) | Hart+Review |
| T10 | **Clipboard**: sensible Werte systematisch klauen oder remote spiegeln | Hart+Review |
| T11 | **Öffentliche Electrum** oder **Remote-LLM** als stiller Default / ohne Opt-in-Dialog | Hart |
| T12 | **Phishing-UX**: „Wallet gesperrt — Seed eingeben“, Fake-Support, irreführende Fremdlinks zur Seed-Eingabe | Hart+Review |
| T13 | **Lern-URLs / „Kaninchenbau“**: Shitcoin-, Altcoin- oder Eth-Content; „Crypto“-Gemischtwaren; im Zweifel **warnen und blocken**, nicht durchwinken. Nur Bitcoin-only. Lernstoff erklärt **Bitcoin-Mechanismen** für Plebs — keine SatSage-Implementierungsdetails | Hart+Review |

**Präzisierung T3:** Gewollte Abfragen an vom Nutzer konfigurierte Datenquellen (Electrs/Fulcrum, BIP-158-Peers, Sanktions-Clearnet laut Design) sind kein Leak. Verboten ist Weitergabe an **andere** Endpoints / Telemetrie / Cloud ohne Opt-in.

**Präzisierung T13:** Gilt für `web/lernhinweise.json`, Tooltips und Lern-QR. Zulässig: konkrete Artikel/BIPs/Whitepaper zu Bitcoin-Mechanismen. Unzulässig: Altcoin-Portale, Staking-Eth, SatSage-Internals, **Anbieter-Startseiten, Mediathek-Index, Shop/„Buch kaufen“**. Im Review: unklare oder generische URL = Nein bis kuratiert (`status: ok`).

---

## 2 · Secrets & Repo-Integrität

| ID | Dealbreaker | Härte |
|----|-------------|--------|
| S1 | **`.env`**, Cookies, RPC-Passwörter, Klartext-XPUBs/Keys **im Git-Diff/Commit** | Hart |
| S2 | **Maintainer-/Agent-Clones:** nur `Juniormind1 <juniormind@proton.me>`. **Fremde Contributor-Commits/PRs:** eigene Autor-IDs erlaubt. CI prüft nicht „jeder Commit = Juniormind1“. | Hart lokal (Hooks) für Maintainer/Agent |
| S3 | **`githooks/`** oder CI-Workflows sabotieren/entfernen ohne Maintainer-Freigabe | Hart+Review |
| S4 | Merge nach **`main`** ohne Prüfung (Prozess/Ruleset) | Hart (Ruleset/Prozess) |

---

## 3 · Qualität / CI / Scope

| ID | Dealbreaker | Härte |
|----|-------------|--------|
| Q1 | **`tests/`-Suite rot** auf CI (Ubuntu `unittest discover`) | Hart |
| Q2 | Suite „grün“ nur durch **unbegründete skips** / Aushebeln von Checks | Hart+Review |
| Q3 | **Scope-Monster**: UI + Core-Scan + Packaging + Plugin in einem PR ohne Trennung | Weich |
| Q4 | Neue Nutzertexte **nur Englisch / hart in `app.js`** statt Locales | Weich |
| Q5 | Nennenswerte Änderung **ohne Changelog** `[Unveröffentlicht]` | Weich |

---

## 4 · Produkt-Semantik

| ID | Dealbreaker | Härte |
|----|-------------|--------|
| P1 | **Danger Zone / Cache-Löschen** entfernt mit Wallet-Alter oder Header-Cache | Hart+Review |
| P2 | Datenquellen-Kaskade so, dass **öffentliche Server** ohne Bestätigung Vorrang bekommen | Hart |
| P3 | Neue Outbound-Hosts außerhalb der bekannten Kette (Electrum/P2P/Preis/Sanktionslisten-Clearnet) **ohne Opt-in und Doku** | Hart+Review |
| P4 | Assistent darf **Jobs starten / scannen / Secrets anzeigen** (Key im Status o. Ä.) | Hart |

---

## Starter-Set (CI zuerst)

1. T1 — keine Seed/xprv/WIF-Eingabe  
2. T3 — kein XPUB/Deskriptor-Leak an Fremde  
3. T4 / S1 — keine Secrets im Diff oder Exfil  
4. T5 — kein Bind/Auth-Aufweichen  
5. T6 / T7 — kein Remote-Code / Download+Exec  
6. T11 — kein stiller Public-Electrum/Remote-LLM-Default  
7. S2 — Juniormind1 nur für Maintainer/Agent (Hooks)  
8. Q1 — Unittests grün  

---

## Nicht als Dealbreaker

- Geschmack / reine Optik  
- Fehlende Tablet-Mobile-Optik (eigenes Issue)  
- Klare, getrennte Refactors bei grüner Suite  
