#!/usr/bin/env bash
set -euo pipefail

relay_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$relay_root"

command -v docker >/dev/null || { echo 'Docker is required.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Python 3 is required for the readiness check.' >&2; exit 1; }
docker compose version >/dev/null
docker compose up -d --wait --wait-timeout 90 falkordb

relay_ping="$(docker compose exec -T falkordb redis-cli --raw PING)"
[[ "$relay_ping" == PONG ]] || { echo 'FalkorDB PING failed.' >&2; exit 1; }

# Verify that the graph module can write and read, not merely accept a connection.
# This graph is unique to this invocation and never touches application data.
relay_probe_graph="relay_readiness_$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
cleanup() {
  docker compose exec -T falkordb redis-cli GRAPH.DELETE "$relay_probe_graph" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker compose exec -T falkordb redis-cli --json GRAPH.QUERY "$relay_probe_graph" \
  "CREATE (n:Readiness {value: 'relay-runtime-ready'}) RETURN n.value" \
  | python3 -c 'import json,sys; result=json.load(sys.stdin); assert result[1] == [["relay-runtime-ready"]], result'
docker compose exec -T falkordb redis-cli --json GRAPH.RO_QUERY "$relay_probe_graph" \
  'MATCH (n:Readiness) RETURN n.value' \
  | python3 -c 'import json,sys; result=json.load(sys.stdin); assert result[1] == [["relay-runtime-ready"]], result'
docker compose exec -T falkordb redis-cli --json GRAPH.DELETE "$relay_probe_graph" \
  | python3 -c 'import json,sys; result=json.load(sys.stdin); assert result == "OK" or (isinstance(result,str) and result.startswith("Graph removed")), result'
trap - EXIT
echo 'FalkorDB ready: PING and Cypher write/read passed; temporary graph removed.'
