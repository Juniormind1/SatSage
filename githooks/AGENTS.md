# AGENTS.md — Git, Hooks, Identität

Gilt beim Arbeiten an `githooks/` **und** bei jedem Commit/Push aus diesem Clone. Zusätzlich zur Root-Verfassung ([`../AGENTS.md`](../AGENTS.md)). Bei Konflikt gewinnt Root-HART (Geheimnisse, Doxxing, kein Commit ohne Auftrag).

**Der Benutzer entscheidet selber, wann er git commit und push machen will.**

## Branches

- main — nur **stabiles**, öffentliches Material (Release-tauglich). Merge egal von wem, aber nur nach Prüfung. Vor dem Merge und vor jedem Release (Tag `v*`, Image, Linux-Binary, StartOS-Paket): Unittests grün und Regtest-Labor grün (Workflow `Regtest-Labor`, Core + Electrs, `verify_rpc_allowlist.py`, `verify_tx_classify.py`, `verify_sanctions_hops.py` und `verify_quellen_inventar.py`). Wochenlauf auf `dev-juniormind` nur, wenn der Prüfpfad seit dem letzten grünen Labor geändert wurde.
- dev-juniormind — laufende Entwicklung von Juniormind1; hier committen/pushen für Work-in-Progress.
- Andere Contributor-Branches/PRs: nach Review in main mergen, wenn stabil; nicht ungeprüft aus dev-* übernehmen.

## Commit-Identität (Maintainer / Assistent)

**Von Maintainer-Rechnern und Assistenten-Worktrees** (Juniormind1-Maschinen, Grok/Cursor-Worktrees, `scripts/commit.*` / `scripts/push.*`) gilt hart:

- **Nur** `user.name=Juniormind1` / `user.email=juniormind@proton.me` — das ist Config und Committer
- **Git-Autor:** dieselbe Identität. Auf `dev-juniormind` zusätzlich `busch21 <busch21@tutamail.com>`. Auf `main` und jedem anderen Branch bleibt der Autor Juniormind1
- **Kein** Push/Commit unter anderer Committer-Identität — auch nicht versehentlich (OS-Default, alte Config, Assistent)
- Helfer: `scripts/commit.sh`|`.bat`, `scripts/push.sh`|`.bat` (brechen bei Abweichung ab; `--fix-identity` setzt name/email/hooks). Commit-Default: getrackte + untracked **Text** auto; untracked **Binär** nach Nachfrage (`-A` alles, `-u` nur getrackt)
- **Windows `.bat`:** echte `cmd.exe`-Dateien — **CRLF**-Zeilenenden (LF-only zerlegt CMD in Müll-Befehle), `REM`/`::` statt `#`, kein Bash-Syntax. Nach dem Schreiben Bytes prüfen (`\r\n`, kein UTF-16/NUL). `.sh` bleibt LF/Bash.

Pflicht in **diesen** Clones:

```bash
git config user.name Juniormind1
git config user.email juniormind@proton.me
git config core.hooksPath githooks
```

Hooks in `githooks/` (`pre-commit`, `pre-merge-commit`, `post-commit`, `pre-push`) blockieren abweichende Identitäten und `pre-commit` zusätzlich bekannte Secret-Pfade (**S1**) sowie fehlende Chat-Bestätigung (siehe unten) — **nur wenn** `core.hooksPath=githooks` aktiv ist (Maintainer-Setup). `pre-push` fährt die Unit-Suite nur bei Push nach `main` (inkl. Hart-Tests, `SATSAGE_HARD_TESTS=1`); `dev-juniormind` bleibt ohne Suite. Assistenten müssen vor jedem Commit die **lokale** Repo-Config prüfen und den staged Diff selbst gegen **HART · Geheimnisse und Doxxing** halten. Hooks ersetzen diese Prüfung nicht.

**Fremde Contributor (z. B. tbusch) und PRs:** eigene Autor-/Committer-IDs sind **erlaubt und erwünscht** (übliche OSS-Praxis) — sie nutzen **nicht** das Maintainer-hooksPath-Setup und nicht die Maintainer-commit/push-Skripte als Identitätszwang. CI verlangt nicht „jeder Commit im Repo = Juniormind1“. Merge nach `main` weiter nur nach Prüfung (siehe Branches).

Assistenten sollen:

- Änderungen vorstellen und testen, aber **nicht** automatisch committen oder pushen
- Nicht nach jedem Task „Soll ich committen/pushen?“ fragen
- Auf ausdrückliche Anweisung des Benutzers warten (`commit`, `push`, o. ä.)
- Vor Commit/Push: **HART · Geheimnisse und Doxxing** am staged Diff prüfen; bei Treffer abbrechen
- Vor Commit/Push: lokale `user.name`/`user.email` verifizieren; bei Abweichung abbrechen und korrigieren
- Für Commit/Push ohne Token-Verbrauch die Maintainer-Skripte vorschlagen (`scripts/commit.*`, `scripts/push.*`)
- Bestätigungsdateien `satsage-commit-ok` / `satsage-push-ok` nur nach explizitem OK im Chat anlegen; nie vorsorglich, nie `--no-verify`


## Bestätigung im Chat

Commits und Pushes in diesen Clones brauchen zusätzlich zur Identität und zu S1 ein **explizites OK des Nutzers im Chat**. Die Hooks erzwingen das über eine Datei im gemeinsamen Git-Verzeichnis (`git rev-parse --git-common-dir`, damit Worktrees dieselbe Datei sehen):

- Commit: `<git-common-dir>/satsage-commit-ok`
- Push nach `Juniormind1/SatSage`: `<git-common-dir>/satsage-push-ok`

**Assistenten** legen eine dieser Dateien **nur** an, wenn der Nutzer im Chat ausdrücklich zugestimmt hat (z. B. „OK“, „Ja“, oder die klare Anweisung zu genau diesem Commit bzw. Push). Je OK eine Datei, nie vorsorglich, nie für einen späteren Schritt, nie selbst überschreiben, wenn noch eine gültige Datei liegt. Der Inhalt ist egal; eine Datei älter als zwei Stunden gilt als abgelaufen und wird abgelehnt. Die Hooks löschen die Datei nach erfolgreichem Commit (`post-commit`), nach bestandener Prüfung in `pre-merge-commit` (`git merge` ruft `post-commit` nicht auf) bzw. nach bestandenen pre-push-Prüfungen, unmittelbar vor `exit 0` (Git hat keinen post-push-Hook). Ein OK gilt für genau einen Commit bzw. einen Push-Versuch. Schlägt der Push danach netzseitig fehl, braucht es ein neues OK.

`git commit --no-verify` und `git push --no-verify` umgehen die Hooks, **nicht** diese Regel. `--no-verify` ist für Assistenten verboten. `SATSAGE_SKIP_TESTS=1` überspringt nur die Unit-Suite auf `main`, nicht die Chat-Bestätigung.

Lokale Merges ohne Konflikt rufen `pre-merge-commit` statt `pre-commit` auf. `githooks/pre-merge-commit` startet denselben Prüfer wie `pre-commit` (Identität, S1, Chat-OK). Fehlt der Hook, fällt Git seit 2.24 auf `pre-commit` zurück; der Wrapper macht die Pflicht sichtbar.

Die Maintainer-Skripte `scripts/commit.*` und `scripts/push.*` rufen normales `git commit` / `git push` auf und umgehen die Hooks nicht. Ohne Bestätigungsdatei schlagen sie deshalb ebenfalls fehl. Wer am eigenen Rechner selbst committen oder pushen will, legt die Datei vorher an — der Mensch am eigenen Rechner ist sein eigenes OK — oder bestätigt im Chat, damit ein Assistent sie anlegt.

## Remote-Stand prüfen (Pflicht, multi-machine)

Entwicklung läuft parallel (z. B. MacBook + Windows-Worktree). Pushes auf `dev-juniormind` können von einem anderen Rechner kommen. **Niemals** den Remote-Stand nur aus dem lokalen Tracking-Ref `origin/<branch>` ableiten und als Wahrheit melden.

**Harte Falle in manchen Clones/Worktrees:** `remote.origin.fetch` ist auf nur `main` eingeengt, z. B.

```text
remote.origin.fetch=+refs/heads/main:refs/remotes/origin/main
```

Dann aktualisiert `git fetch` / `git fetch --prune` **`origin/dev-juniormind` nicht**. Der Ref kann tagelang auf einem alten Commit stehen, während GitHub schon weiter ist — und der Assistent meldet fälschlich „Remote = 11.09.“ obwohl gerade gepusht wurde.

**Pflichtablauf bei jeder Frage nach Remote / Sync / „wo steht origin?“ / vor Pull-Empfehlung:**

1. `git config --get remote.origin.fetch` lesen (Refspec-Falle erkennen).
2. **Wahrheit vom Server:** `git ls-remote origin refs/heads/dev-juniormind refs/heads/main` (SHA live von GitHub).
3. Tracking-Ref aktualisieren, explizit und mit Force-Refspec wenn nötig:
   - `git fetch origin +refs/heads/dev-juniormind:refs/remotes/origin/dev-juniormind`
   - analog für andere Branches; nicht darauf vertrauen, dass ein bare `git fetch` alle Heads holt.
4. Erst danach `git log -1` auf `origin/dev-juniormind`, Divergenz `HEAD...origin/dev-juniormind` (`rev-list --left-right --count`), und bei Non-Fast-Forward / Rewrite klar sagen.
5. `FETCH_HEAD` allein oder ein veraltetes `origin/*` ohne Schritt 2–3 **reicht nicht** als Remote-Antwort.

Optional dauerhaft heilen (nur wenn der Nutzer das will, nicht stillschweigend global umbiegen):

```bash
git config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
```

## Secret-Pfade im Hook

`githooks/pre-commit` blockiert bekannte Secret-Pfade (Dealbreaker **S1**). Die Pflicht, den staged Diff selbst zu lesen, steht in der Root-Verfassung und wird vom Hook nicht ersetzt. Git-Commit-Metadaten (Autor/E-Mail) sind bei `push` öffentlich sichtbar.
