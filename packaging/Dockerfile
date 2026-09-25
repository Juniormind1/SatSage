# SatSage container image for StartOS and Umbrel. Build context is the
# **repo root** (StartOS manifest dockerBuild.workdir); Dockerfile path is
# packaging/Dockerfile.
#
# The platform decides the managed mode at runtime:
#   StartOS -> SATSAGE_MANAGED_BY=start9 (packaging/startos/main.ts)
#   Umbrel  -> SATSAGE_MANAGED_BY=umbrel (docker-compose.yml of the app package)
# Leaving it unset here keeps the image usable as a plain Docker deployment.
FROM python:3.12-slim-bookworm AS wheels
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp/wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=wheels /install /usr/local
WORKDIR /opt/satsage
# Keine Handliste: ein neues Paket neben core/ und httpserver/ kommt mit,
# solange .dockerignore es nicht ausschließt. Der Build bricht ab, wenn
# server.py ein lokales Modul importiert, das nicht im Image liegt.
COPY . .
COPY packaging/docker_entrypoint.sh /usr/local/bin/docker_entrypoint.sh
RUN python3 - <<'PY'
import ast
import sys
from pathlib import Path

root = Path("/opt/satsage")
stdlib = set(sys.stdlib_module_names)
third = {"embit", "chiabip158", "argon2", "cryptography", "PIL", "pyi_splash"}
seen: set[Path] = set()
missing: set[str] = set()

def present(mod: str) -> Path | None:
    parts = mod.split(".")
    file = root.joinpath(*parts).with_suffix(".py")
    pkg = root.joinpath(*parts)
    if file.is_file():
        return file
    init = pkg / "__init__.py"
    if pkg.is_dir():
        return init if init.is_file() else pkg
    top = root / f"{parts[0]}.py"
    if len(parts) > 1 and top.is_file():
        return top
    return None

def walk(path: Path) -> None:
    if path in seen or not path.is_file():
        return
    seen.add(path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.append(node.module)
    for mod in mods:
        top = mod.split(".", 1)[0]
        if top in stdlib or top in third:
            continue
        found = present(mod)
        if found is None:
            missing.add(mod)
            continue
        if found.is_file():
            walk(found)

walk(root / "server.py")
if missing:
    print("Image fehlt lokale Module:", ", ".join(sorted(missing)), file=sys.stderr)
    raise SystemExit(1)
print(f"image import check ok ({len(seen)} files)")
PY
# Umbrel runs the service as 1000:1000; keep /data writable for that case as
# well as for the root default used by StartOS.
RUN chmod a+x /usr/local/bin/docker_entrypoint.sh \
 && mkdir -p /data \
 && chown 1000:1000 /data
ENV PYTHONUNBUFFERED=1 \
    SATSAGE_DATA_DIR=/data
EXPOSE 8730
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker_entrypoint.sh"]
