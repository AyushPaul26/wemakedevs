#!/usr/bin/env bash
# Single-container test deployment. Only the web port is externally exposed.
set -euo pipefail
cd /app

relay_password="${RELAY_ACCESS_PASSWORD:-}"
if [[ ${#relay_password} -lt 16 ]]; then
  echo 'Set RELAY_ACCESS_PASSWORD to at least 16 characters before starting.' >&2
  exit 1
fi
unset relay_password
export RELAY_FALKORDB_HOST=127.0.0.1
export RELAY_FALKORDB_PORT=6379
export RELAY_DATA_DIR="${RELAY_DATA_DIR:-/app/.data}"
umask 077
mkdir -p "$RELAY_DATA_DIR/graph"

relay_db_pid=''
relay_web_pid=''
cleanup() {
  trap - EXIT INT TERM
  [[ -z "$relay_web_pid" ]] || kill "$relay_web_pid" 2>/dev/null || true
  [[ -z "$relay_web_pid" ]] || wait "$relay_web_pid" 2>/dev/null || true
  [[ -z "$relay_db_pid" ]] || kill "$relay_db_pid" 2>/dev/null || true
  [[ -z "$relay_db_pid" ]] || wait "$relay_db_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

redis-server --bind 127.0.0.1 --port 6379 --protected-mode yes \
  --dir "$RELAY_DATA_DIR/graph" --save '' --appendonly yes --appendfsync everysec \
  --maxmemory 192mb --maxmemory-policy noeviction \
  --loadmodule /opt/falkordb/falkordb.so THREAD_COUNT 2 OMP_THREAD_COUNT 1 &
relay_db_pid=$!
relay_db_ready=false
for _ in {1..60}; do
  kill -0 "$relay_db_pid" 2>/dev/null || { echo 'FalkorDB exited during startup.' >&2; exit 1; }
  if redis-cli -e PING >/dev/null 2>&1; then
    relay_db_ready=true
    break
  fi
  sleep 1
done
[[ "$relay_db_ready" == true ]] || { echo 'FalkorDB did not become ready.' >&2; exit 1; }

# Only an explicit first-install flag can initialize empty persistent storage.
# Upgrades/adoption remain offline operator commands, never a health side effect.
if [[ "${RELAY_UPGRADE_DATA:-0}" == 1 ]]; then
  python scripts/startup.py --upgrade --quiesced
elif [[ "${RELAY_INITIALIZE_DATA:-0}" == 1 || "${RELAY_STORAGE_MODE:-ephemeral}" == ephemeral ]]; then
  python scripts/startup.py --initialize --quiesced
else
  python scripts/startup.py --check
fi

uvicorn relay.hosting:create_hosted_app --factory --app-dir backend \
  --host 0.0.0.0 --port "${PORT:-10000}" --no-access-log &
relay_web_pid=$!
set +e
wait -n "$relay_db_pid" "$relay_web_pid"
relay_exit=$?
set -e
echo 'A Relay service exited; stopping the container.' >&2
[[ "$relay_exit" -ne 0 ]] || relay_exit=1
exit "$relay_exit"
