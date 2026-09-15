#!/usr/bin/env bash
# SatSage: commit without AI. Repo-Root = Parent von scripts/.
#
# Maintainer-only (Juniormind1-Rechner / Assistenten-Worktrees):
#   Commit-Identität MUSS Juniormind1 <juniormind@proton.me> sein.
#   Fremde Contributor (tbusch u. a.) committen mit ihrer eigenen ID via
#   normalem git — dieses Skript ist nicht für sie gedacht.
#
# Usage:
#   ./scripts/commit.sh "Commit-Message"
#     Default (auto): getrackte Änderungen + untracked Textdateien;
#     untracked Binärdateien → Nachfrage (ohne TTY: überspringen + Warnung)
#   ./scripts/commit.sh -u "nur getrackte Änderungen"
#   ./scripts/commit.sh -A "alles Untracked inkl. Binär (gitignore gilt)"
#   ./scripts/commit.sh --staged "nur Index, nichts neu stagen"
#   ./scripts/commit.sh --fix-identity "Message"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REQUIRED_NAME="Juniormind1"
REQUIRED_EMAIL="juniormind@proton.me"

ADD_MODE="auto"   # auto | -u | -A | staged
FIX_IDENTITY=0
MSG=""

# Bekannte Binär-Endungen (zusätzlich zu NUL-Heuristik, git-ähnlich).
_BINARY_EXT_RE='^(exe|dll|so|dylib|o|a|png|jpg|jpeg|gif|webp|ico|bmp|pdf|zip|gz|tgz|bz2|xz|7z|rar|bin|s9pk|pyc|pyo|whl|egg|wasm|woff|woff2|ttf|otf|mp3|mp4|mov|avi|sqlite|db|dmg|iso|class|jar|pak|dat|npy|npz|pt|onnx)$'

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \?//'
  exit 2
}

# Exit 0 = binary, 1 = text. Leere Datei = Text.
is_binary_file() {
  local f="$1"
  local base ext
  base="${f##*/}"
  ext="${base##*.}"
  if [[ "$base" == *.* ]]; then
    local el
    el=$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')
    if [[ "$el" =~ $_BINARY_EXT_RE ]]; then
      return 0
    fi
  fi
  if [[ ! -s "$f" ]]; then
    return 1
  fi
  # Exit 0 = Binär, 1 = Text. Unter set -e nur in if/|| nutzen.
  local _py=""
  if command -v python3 >/dev/null 2>&1; then
    _py=python3
  elif command -v py >/dev/null 2>&1; then
    _py=py
  fi
  if [[ -n "$_py" ]]; then
    if "$_py" -c "import sys; p=open(sys.argv[1],'rb').read(8192); sys.exit(0 if b'\\x00' in p else 1)" "$f"; then
      return 0
    fi
    return 1
  fi
  # Fallback ohne Python: NUL in den ersten 8 KiB.
  if head -c 8192 "$f" 2>/dev/null | LC_ALL=C grep -a -q $'\0'; then
    return 0
  fi
  return 1
}

# Untracked (nicht ignoriert): Text auto, Binär nachfragen.
stage_untracked_smart() {
  local f ans
  local -a files=()
  while IFS= read -r -d '' f; do
    files+=("$f")
  done < <(git ls-files -z --others --exclude-standard)

  if [[ ${#files[@]} -eq 0 ]]; then
    return 0
  fi

  echo "=== untracked ==="
  for f in "${files[@]}"; do
    if is_binary_file "$f"; then
      if [[ -t 0 ]]; then
        ans=""
        read -r -p "Binär untracked stagen? $f [j/N] " ans || true
        case "$ans" in
          j|J|y|Y|ja|Ja|yes|Yes)
            git add -- "$f"
            echo "  gestaged (Binär, bestätigt): $f"
            ;;
          *)
            echo "  übersprungen (Binär): $f"
            ;;
        esac
      else
        echo "  WARN: Binär untracked, kein TTY — nicht gestaged: $f" >&2
        echo "        explizit: git add -- \"$f\"   oder   ./scripts/commit.sh -A \"…\"" >&2
      fi
    else
      git add -- "$f"
      echo "  gestaged (Text): $f"
    fi
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    -u) ADD_MODE="-u"; shift ;;
    -A|--all) ADD_MODE="-A"; shift ;;
    --staged) ADD_MODE="staged"; shift ;;
    --fix-identity) FIX_IDENTITY=1; shift ;;
    --) shift; break ;;
    -*)
      echo "Unbekanntes Flag: $1" >&2
      usage
      ;;
    *)
      if [[ -n "$MSG" ]]; then
        echo "Nur eine Commit-Message erlaubt." >&2
        exit 2
      fi
      MSG=$1
      shift
      ;;
  esac
done

if [[ -z "$MSG" ]]; then
  echo "Commit-Message fehlt." >&2
  usage
fi

if [[ "$FIX_IDENTITY" -eq 1 ]]; then
  git config user.name "$REQUIRED_NAME"
  git config user.email "$REQUIRED_EMAIL"
  git config core.hooksPath githooks
  echo "Identität + hooksPath gesetzt."
fi

NAME="$(git config --get user.name || true)"
EMAIL="$(git config --get user.email || true)"
HOOKS="$(git config --get core.hooksPath || true)"

if [[ "$NAME" != "$REQUIRED_NAME" || "$EMAIL" != "$REQUIRED_EMAIL" ]]; then
  echo "ERROR: Maintainer-Commit nur als $REQUIRED_NAME <$REQUIRED_EMAIL>." >&2
  echo "  (Contributor mit eigener ID: normales git commit, nicht dieses Skript.)" >&2
  echo "  ./scripts/commit.sh --fix-identity \"deine Message\"" >&2
  exit 1
fi
if [[ "$HOOKS" != "githooks" ]]; then
  echo "WARN: core.hooksPath ist '$HOOKS' (erwartet: githooks)." >&2
  echo "  git config core.hooksPath githooks" >&2
fi

echo "=== status (vorher) ==="
git status -sb

case "$ADD_MODE" in
  staged) ;;
  -u) git add -u ;;
  -A) git add -A ;;
  auto)
    git add -u
    stage_untracked_smart
    ;;
esac

if git diff --cached --quiet; then
  echo "Nichts gestaged — Abbruch (working tree unverändert oder nur übersprungene Untracked)." >&2
  git status -sb
  exit 1
fi

echo "=== staged ==="
git diff --cached --stat

git commit -m "$MSG"

echo "=== HEAD ==="
git log -1 --format="%h %an <%ae>%n%s"
git status -sb
echo "Push: ./scripts/push.sh"
