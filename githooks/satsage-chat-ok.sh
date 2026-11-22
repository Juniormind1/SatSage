#!/bin/sh
# Gemeinsame Prüfung der Chat-Bestätigungsdatei.
# Wird von pre-commit und pre-push per `.` eingebunden, ist selbst kein Hook.
# Datei: $(git rev-parse --git-common-dir)/satsage-<commit|push>-ok
# Inhalt egal; älter als 120 Minuten gilt als abgelaufen.
# find -mmin ist nicht POSIX-find, läuft aber auf macOS, Linux und Git-Bash.

# satsage_require_ok commit
# satsage_require_ok push
satsage_require_ok() {
  _kind="$1"
  case "$_kind" in
    commit|push) ;;
    *)
      echo "ERROR: satsage_require_ok: unbekannte Art '$_kind'." >&2
      exit 1
      ;;
  esac
  _gitdir="$(git rev-parse --git-common-dir)"
  _okfile="$_gitdir/satsage-${_kind}-ok"
  if [ ! -f "$_okfile" ]; then
    if [ "$_kind" = "commit" ]; then
      echo "ERROR: Kein Commit ohne explizites OK im Chat." >&2
    else
      echo "ERROR: Kein Push ohne explizites OK im Chat." >&2
    fi
    echo "Die Bestätigungsdatei fehlt:" >&2
    echo "  $_okfile" >&2
    echo "Diese Datei wird erst angelegt, wenn der Nutzer im Chat ausdrücklich zugestimmt hat (z. B. \"OK\", \"Ja\")." >&2
    echo "Assistenten dürfen die Datei nicht selbst vorsorglich erzeugen." >&2
    exit 1
  fi
  if [ -n "$(find "$_okfile" -mmin +120 -print)" ]; then
    echo "ERROR: Die Chat-Bestätigung ist abgelaufen (älter als 2 Stunden):" >&2
    echo "  $_okfile" >&2
    echo "Bitte erneut im Chat bestätigen; die Datei wird danach neu angelegt." >&2
    exit 1
  fi
}
