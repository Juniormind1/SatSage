# SatSage for StartOS. Build context is the **repo root** (see manifest
# dockerBuild.workdir). Dockerfile path is packaging/Dockerfile.
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
COPY analyze.py bip158_scanner.py check_fulcrum_tor.py consolidate.py \
     diagnose.py display.py fulcrum.py interact.py labels.py main.py menu.py \
     outbound_policy.py sanctioned.py server.py trace_engine.py \
     requirements.txt VERSION LICENSE NOTICE ./
COPY core ./core
COPY web ./web
COPY doc ./doc
COPY data ./data
COPY packaging/docker_entrypoint.sh /usr/local/bin/docker_entrypoint.sh
RUN chmod a+x /usr/local/bin/docker_entrypoint.sh \
 && mkdir -p /data
ENV PYTHONUNBUFFERED=1 \
    SATSAGE_MANAGED_BY=start9 \
    SATSAGE_DATA_DIR=/data
EXPOSE 8730
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker_entrypoint.sh"]
