# SatSage StartOS package

This directory is the **StartOS package root** (`satsage-startos`).
The Python app lives in the repository root; this folder wraps it as an
`.s9pk` for StartOS 0.4 (x86_64).

**How to build, sideload, and cut a release:**
[`doc/START9-packaging.md`](../doc/START9-packaging.md)

Quick path (on a machine with Docker, Node 22, `start-cli`):

```bash
# repo root must sit inside a Start9 packaging workspace
./scripts/build_startos_s9pk
```

That produces `packaging/satsage_x86_64.s9pk`. Sideload it in the StartOS
web UI, or publish with `./scripts/publish_startos_release`.
