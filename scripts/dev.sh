#!/usr/bin/env bash
set -euo pipefail

if (( BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 3) )); then
  echo 'Relay requires Bash 4.3 or newer (for process supervision).' >&2
  exit 1
fi

relay_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$relay_root"

if [[ -f .env ]]; then
  # .env is local, trusted shell configuration; never enable shell tracing here.
  relay_existing_model_key="${RELAY_MODEL_API_KEY:-}"
  set -a
  source .env
  set +a
  # A copied example's empty key must not shadow injected cloud credentials.
  if [[ -n "$relay_existing_model_key" ]]; then
    export RELAY_MODEL_API_KEY="$relay_existing_model_key"
  fi
  unset relay_existing_model_key
fi

[[ -x .venv/bin/uvicorn ]] || { echo 'Run uv sync --frozen first.' >&2; exit 1; }
[[ -d frontend/node_modules ]] || { echo 'Run npm --prefix frontend ci first.' >&2; exit 1; }
command -v curl >/dev/null || { echo 'curl is required for readiness checks.' >&2; exit 1; }

# Fail before starting anything if a previous server owns either app port.
.venv/bin/python - <<'PY'
import socket
for port in (8000, 5173):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise SystemExit(f'Port {port} is unavailable; stop the existing server first: {exc}')
PY

./scripts/start-db.sh
mkdir -p .data
export RELAY_DATA_DIR="${RELAY_DATA_DIR:-$relay_root/.data}"
# A missing marker or old schema must be handled offline before any API writer.
if [[ "${RELAY_INITIALIZE_DATA:-0}" == 1 ]]; then
  .venv/bin/python scripts/startup.py --initialize --quiesced
else
  .venv/bin/python scripts/startup.py --check
fi
relay_api_pid=''
relay_frontend_pid=''
cleanup() {
  trap - EXIT INT TERM
  [[ -z "$relay_frontend_pid" ]] || kill "$relay_frontend_pid" 2>/dev/null || true
  [[ -z "$relay_api_pid" ]] || kill "$relay_api_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

.venv/bin/uvicorn relay.api:app --app-dir backend --host 127.0.0.1 --port 8000 &
relay_api_pid=$!
relay_api_ready=false
for _ in {1..60}; do
  kill -0 "$relay_api_pid" 2>/dev/null || { echo 'Relay API exited during startup.' >&2; exit 1; }
  if curl --silent --fail --max-time 2 http://127.0.0.1:8000/api/health >/dev/null; then
    relay_api_ready=true
    break
  fi
  sleep 1
done
[[ "$relay_api_ready" == true ]] || { echo 'Relay API did not become healthy within 60 seconds.' >&2; exit 1; }

# Invoke Vite directly so this supervisor owns its process and can stop it cleanly.
(
  cd frontend
  exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort
) &
relay_frontend_pid=$!
relay_frontend_ready=false
for _ in {1..30}; do
  kill -0 "$relay_frontend_pid" 2>/dev/null || { echo 'Relay frontend exited during startup.' >&2; exit 1; }
  if curl --silent --fail --max-time 2 http://127.0.0.1:5173/api/health >/dev/null; then
    relay_frontend_ready=true
    break
  fi
  sleep 1
done
[[ "$relay_frontend_ready" == true ]] || { echo 'Relay frontend proxy did not become healthy within 30 seconds.' >&2; exit 1; }

echo 'Relay ready: frontend port 5173, API port 8000. Ctrl-C stops both; FalkorDB data is retained.'
set +e
wait -n "$relay_api_pid" "$relay_frontend_pid"
relay_exit=$?
set -e
echo 'A Relay server exited; stopping its companion.' >&2
exit "$relay_exit"
