#!/usr/bin/env python3
"""Fügt/ersetzt den Linux-Webgui-Abschnitt in GitHub-Release-Notes."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--body-in", required=True, help="Pfad oder - für stdin")
    p.add_argument("--body-out", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--hash", required=True)
    args = p.parse_args()

    if args.body_in == "-":
        body = sys.stdin.read()
    else:
        body = Path(args.body_in).read_text(encoding="utf-8")

    block = (
        f"### Linux Web-GUI (x86_64)\n"
        f"- `{args.name}` (Onefile, GitHub Actions / ubuntu-latest)\n"
        f"- SHA-256: `{args.hash}`\n"
        f"- **Hinweis: GitHub-Build für Linux, ungetestet.**\n"
        f"- Lauscht lokal unter `127.0.0.1:8730`. `.env` und Caches neben das Binary legen.\n"
    )

    pat = re.compile(r"### Linux Web-GUI.*?(?=\n### |\n## |\Z)", re.S)
    if pat.search(body):
        body = pat.sub(block.rstrip() + "\n\n", body, count=1)
    else:
        inserted = False
        for marker in (
            "### macOS Web-GUI (Apple Silicon)",
            "### macOS Web-GUI",
            "### Windows Web-GUI",
        ):
            idx = body.find(marker)
            if idx < 0:
                continue
            rest = body[idx + 1 :]
            m = re.search(r"\n### |\n## ", rest)
            if m:
                end = idx + 1 + m.start()
                body = (
                    body[:end].rstrip()
                    + "\n\n"
                    + block.rstrip()
                    + "\n\n"
                    + body[end:].lstrip("\n")
                )
            else:
                body = body.rstrip() + "\n\n" + block
            inserted = True
            break
        if not inserted:
            body = body.rstrip() + "\n\n" + block

    eng = (
        "Windows onefile GUI, macOS Apple Silicon onefile GUI, "
        "and StartOS"
    )
    eng_new = (
        "Windows onefile GUI, macOS Apple Silicon onefile GUI, "
        "Linux x86_64 onefile GUI (untested GitHub build), and StartOS"
    )
    if eng in body and "Linux x86_64 onefile GUI" not in body:
        body = body.replace(eng, eng_new, 1)
    elif (
        "public binaries:" in body
        and "Linux x86_64" not in body
        and "and StartOS x86_64 sideload package." in body
    ):
        body = body.replace(
            "and StartOS x86_64 sideload package.",
            "Linux x86_64 onefile GUI (untested GitHub build), "
            "and StartOS x86_64 sideload package.",
            1,
        )

    if not body.endswith("\n"):
        body += "\n"
    Path(args.body_out).write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
