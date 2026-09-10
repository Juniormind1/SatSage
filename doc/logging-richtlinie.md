# Log-Richtlinie (Web-GUI + gespiegelter Strom)

**Stand:** 2026-09-10  
**Verankert in:** [`AGENTS.md`](../AGENTS.md) (UI-Konventionen)

## Zweck

Das Log baut **Vertrauen** und hilft bei der **Fehlersuche** — es ist kein Debug-Dump und keine Forensik-Konsole.

- **Erstnutzer:** genug sichtbare Erfolge (Tor startet, erste Peers, Header fertig), bevor sie XPUBs anvertrauen.
- **Alltag:** ruhig, wenn alles steht und das Tool arbeitsbereit ist.
- **Störung:** wieder gesprächig — klar, rechtzeitig, handlungsrelevant.

## Betriebsmodi

| Zustand | Log-Verhalten |
|---------|----------------|
| **Hochfahren / noch nicht bereit** | Gesprächig: nächsten Schritt **ankündigen**, bevor er startet (Tor, Peer-Suche, Header). Erste Erfolge melden. |
| **Arbeitsbereit** (eigene Quellen ok bzw. ≥ **3** Compact-Filter-Peers, Tip aktuell, keine kritische Privatsphäre-Verschlechterung) | **Sparsam:** keine Peer-Feier je neuem Host, kein wiederholtes „Header fertig“, kein Peer-Takt-Ritual. |
| **Problem** | Wieder gesprächig: Abbruch, Timeout, unter kritische Peer-Zahl, Auth/Bind-Thema, Fehler mit Ursache. |
| **Privatsphäre ändert sich** | Immer melden (z. B. Wechsel auf öffentliche Electrum, Opt-in, Verlust der privaten Quelle). |

## Kritische Schwellen (Orientierung)

- **Compact-Filter-Peers:** unter **3** → Log darf/ soll leben (Suche, Tor-Ankündigung, `Verbunden. Compact-Filter-Peer …`); ab **3** → Stille bei weiteren Peers, solange Tip und Betrieb ok.
- **Eigener Node (Electrs/Core):** Ausfall oder „konfiguriert, aber unerreichbar“ → sofort sichtbar.
- **Header-Tip:** unverändert → still; echter Nachzug → eine klare Zeile.

## Form

1. **Ankündigung vor der Arbeit** — nicht danach. Beispiel: *Clearnet ohne Treffer — versuche über Tor…* **bevor** SOCKS-Probe/Binary-Start.
2. **Ergebnis danach** — `Verbunden.…` / Fehler; nicht dieselbe Arbeitszeile wiederholen.
3. **„Moment noch“** nur nach ~10 s ohne neue Zeile (global), kein Job-Namen-Spam.
4. **Wallet-Aktionen:** Name nach der Uhrzeit.
5. **Ein Strom** (`on_log` / NDJSON) — nicht erst im fertigen JSON-Block.
6. **Terminal** bei offener GUI: Fortschritt primär in der Web-GUI; stdout nicht verdoppeln (Prozess-Steuerung / harte Fehler reichen).

## Nicht ins Log

- Erfolgreiche Wiederhol-Probes ohne Zustandsänderung  
- Jeder weitere Peer ab dem 4., wenn bereits ≥3 und Tip steht  
- Roh-i18n-Keys, Stacktraces für Normalnutzer (Detail nur wo nötig)  
- Secrets, XPUBs, Tokens, Seed-Hinweise  

## Für Assistenten / Reviews

Bei Änderungen an Verbindung, Peer-Takt, Header-Vorab, Tor, Quellen-Pillen: diese Richtlinie einhalten. Konkrete Merge-Härte zu Leaks/Seed: [`merge-dealbreakers.md`](merge-dealbreakers.md).
