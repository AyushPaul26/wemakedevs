# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-trixie AS python-base
FROM python-base AS dependencies
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      export PIP_CERT=/run/secrets/proxy_ca SSL_CERT_FILE=/run/secrets/proxy_ca; \
    fi; \
    python -m pip install --no-cache-dir uv==0.12.23 && \
    uv sync --frozen --no-dev --no-install-project --no-managed-python

FROM falkordb/falkordb:v4.22.1@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a AS graph
FROM python-base AS runtime
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      export SSL_CERT_FILE=/run/secrets/proxy_ca; \
      apt_extra='-o Acquire::https::CaInfo=/run/secrets/proxy_ca'; \
    fi; \
    apt-get ${apt_extra:-} update && \
    apt-get ${apt_extra:-} install -y --no-install-recommends libgomp1 libsystemd0 && \
    rm -rf /var/lib/apt/lists/*
COPY --from=graph /usr/local/bin/redis-server /usr/local/bin/redis-server
COPY --from=graph /usr/local/bin/redis-cli /usr/local/bin/redis-cli
COPY --from=graph /var/lib/falkordb/bin/falkordb.so /opt/falkordb/falkordb.so
WORKDIR /app
COPY --from=dependencies /app/.venv /app/.venv
COPY --from=frontend /build/frontend/dist /app/frontend/dist
COPY backend/relay /app/backend/relay
COPY scripts/serve.sh /app/scripts/serve.sh
RUN chmod -R a+rX /app/backend /app/frontend /app/.venv /app/scripts && \
    mkdir -p /app/.data/graph && chown -R 10001:10001 /app/.data && \
    chmod 755 /app/scripts/serve.sh
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RELAY_CHECKPOINT_PATH=/app/.data/checkpoints.sqlite \
    RELAY_STATIC_DIR=/app/frontend/dist \
    PORT=10000
USER 10001:10001
EXPOSE 10000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c 'import os,urllib.request; urllib.request.urlopen("http://127.0.0.1:"+os.environ.get("PORT","10000")+"/api/health", timeout=4)'
ENTRYPOINT ["/bin/bash", "/app/scripts/serve.sh"]
