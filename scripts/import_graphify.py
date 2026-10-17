#!/usr/bin/env python3
"""Import a local Graphify node-link export into Relay's FalkorDB graph."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from relay.graphify_adapter import load_graphify_file  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="Local graph.json from Graphify")
    parser.add_argument("--source-name", required=True,
                        help="Stable repository/scope name; controls the import namespace")
    parser.add_argument("--graph", help="FalkorDB graph override; otherwise RELAY_FALKORDB_GRAPH")
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate and count without connecting to FalkorDB")
    args = parser.parse_args()
    if not args.source_name.strip() or len(args.source_name) > 200:
        parser.error("--source-name must contain 1–200 characters")
    try:
        graph = load_graphify_file(args.export)
    except ValueError as exc:
        parser.error(str(exc))
    if args.validate_only:
        print(json.dumps({"validated": True, "nodes": len(graph["nodes"]),
                          "edges": len(graph["edges"])}))
        return 0
    from relay.graph_store import GraphStore
    from redis.exceptions import RedisError

    try:
        store = GraphStore(graph_name=args.graph)
        result = store.import_graphify(graph, source_name=args.source_name.strip())
    except ValueError as exc:
        parser.error(str(exc))
    except RedisError:
        parser.exit(1, "FalkorDB import failed. Check the database and RELAY_FALKORDB settings.\n")
    print(json.dumps({"imported": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
