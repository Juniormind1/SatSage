#!/usr/bin/env bash
# SatSage: push aktuellen Branch zu origin (ohne AI).
#
# Maintainer-only (Juniormind1-Rechner / Assistenten-Worktrees):
#   Config UND Tip-Autor müssen Juniormind1 <juniormind@proton.me> sein.
#   Von diesen Maschinen kein Push unter anderer Identität.
#   Fremde Contributor (tbusch u. a.) pushen mit eigener ID — ohne dieses
#   Skript / ohne Maintainer-hooksPath; das ist gewollt (OSS).
#
# Usage:
#   ./scripts/push.sh
#   ./scripts/push.sh --fix-identity   # setzt name/email/hooks, dann push
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REQUIRED_NAME="Juniormind1"
REQUIRED_EMAIL="juniormind@proton.me"

if [[ "${1:-}" == "--fix-identity" ]]; then
  git config user.name "$REQUIRED_NAME"
  git config user.email "$REQUIRED_EMAIL"
  git config core.hooksPath githooks
  echo "Identität + hooksPath gesetzt."
fi

NAME="$(git config --get user.name || true)"
EMAIL="$(git config --get user.email || true)"
if [[ "$NAME" != "$REQUIRED_NAME" || "$EMAIL" != "$REQUIRED_EMAIL" ]]; then
  echo "ERROR: Maintainer-Push nur als $REQUIRED_NAME <$REQUIRED_EMAIL>." >&2
  echo "  (Contributor mit eigener ID: normales git push, nicht dieses Skript.)" >&2
  echo "  ./scripts/push.sh --fix-identity" >&2
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" == "HEAD" ]]; then
  echo "ERROR: detached HEAD — kein Push." >&2
  exit 1
fi

TIP_NAME="$(git -c log.showSignature=false log -1 --format='%an')"
TIP_EMAIL="$(git -c log.showSignature=false log -1 --format='%ae')"
if [[ "$TIP_NAME" != "$REQUIRED_NAME" || "$TIP_EMAIL" != "$REQUIRED_EMAIL" ]]; then
  echo "ERROR: Tip-Autor ist $TIP_NAME <$TIP_EMAIL> — Maintainer-Push verweigert." >&2
  echo "  Erwartet: $REQUIRED_NAME <$REQUIRED_EMAIL>" >&2
  echo "  z. B. git commit --amend --reset-author --no-edit   (nur wenn Tip noch lokal)" >&2
  exit 1
fi

HOOKS="$(git config --get core.hooksPath || true)"
if [[ "$HOOKS" != "githooks" ]]; then
  echo "WARN: core.hooksPath='$HOOKS' (erwartet githooks) — pre-push-Hook greift ggf. nicht." >&2
fi

echo "=== push $BRANCH → origin (als $REQUIRED_NAME) ==="
git status -sb
# Expliziter Branch-Ref (manche Clones tracken nur main).
git push -u origin "refs/heads/${BRANCH}:refs/heads/${BRANCH}"

echo "=== remote tip ==="
git ls-remote origin "refs/heads/${BRANCH}"
git status -sb
git log -1 --format="%h %an <%ae> %s"
