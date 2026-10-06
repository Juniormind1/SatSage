"""Hart-Tests: auf ``main`` Pflicht, auf ``dev-juniormind`` optional.

Dealbreaker-Scans (T1/T6/T9/T13, Auth, CSRF) brauchen keinen Node.
``SATSAGE_HARD_TESTS=1`` erzwingt sie überall, ``=0`` stellt sie überall ab.

CI setzt die Variable (``test.yml``). Lokal gilt der Git-Branch, wenn die
Variable fehlt. ``pre-push`` nach ``main`` setzt ``=1``.
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]

SKIP_TEXT = (
    "Hart-Tests (Dealbreaker T1/T6/T9/T13, Auth, CSRF) sind auf "
    "dev-juniormind optional. Vor Merge nach main sind sie Pflicht. "
    "Lokal: SATSAGE_HARD_TESTS=1 py -m unittest discover -s tests -t ."
)


def _flag() -> str | None:
    roh = os.environ.get("SATSAGE_HARD_TESTS")
    if roh is None:
        return None
    return roh.strip().lower()


def _git_branch() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=WURZEL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.decode("utf-8", "replace").strip()


def hart_pflicht() -> bool:
    """Ob die Hart-Tests rot machen dürfen."""
    flag = _flag()
    if flag in ("1", "true", "yes", "ja", "on"):
        return True
    if flag in ("0", "false", "no", "nein", "off"):
        return False
    base = (os.environ.get("GITHUB_BASE_REF") or "").strip()
    ref = (os.environ.get("GITHUB_REF") or "").strip()
    if base == "main" or ref == "refs/heads/main" or ref.startswith("refs/tags/"):
        return True
    if base == "dev-juniormind" or ref == "refs/heads/dev-juniormind":
        return False
    return _git_branch() == "main"


def skip_wenn_dev():
    """Klassen-Decorator: auf WIP-Branches Skip, auf main Pflicht."""
    return unittest.skipUnless(hart_pflicht(), SKIP_TEXT)
