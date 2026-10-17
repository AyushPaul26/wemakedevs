#!/usr/bin/env bash
set -euo pipefail

relay_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$relay_root"
[[ -x .venv/bin/python ]] || { echo 'Run uv sync --frozen first.' >&2; exit 1; }
[[ -d frontend/node_modules ]] || { echo 'Run npm --prefix frontend ci first.' >&2; exit 1; }
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

./scripts/start-db.sh
# Deterministic tests never consume a locally configured provider credential.
RELAY_MODEL_API_KEY= .venv/bin/python -m pytest
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
npm --prefix frontend run build
