# Graphify → Relay

Relay imports code maps from [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) into **FalkorDB**, where they become browsable entities and cited source material. Graphify is an optional upstream producer, not a second runtime database. The importer does not require installing Graphify's Python dependencies.

The adapter was checked against Graphify commit `86c57be8204673c2a1b9849a3292a7dd3ab373d8` (Apache-2.0), including its real `worked/httpx/graph.json` export. Format handling follows the upstream `graphify/paths.py` direction conventions and `graphify/extractors/engine.py` source fields. Relay's adapter is new integration code; the upstream checkout is unchanged.

## Import an existing export

From the Relay repository, after the normal `uv sync --frozen` setup:

```bash
# Validate without contacting the database.
uv run python scripts/import_graphify.py /path/to/graphify-out/graph.json \
  --source-name checkout-service --validate-only

# Start FalkorDB and import into the configured Relay graph.
./scripts/start-db.sh
uv run python scripts/import_graphify.py /path/to/graphify-out/graph.json \
  --source-name checkout-service
```

`--source-name` is a stable name for the repository and scope. Its hash namespaces IDs so imported symbols cannot overwrite Meridian's sample company entities. `--graph custom_graph` overrides `RELAY_FALKORDB_GRAPH`; the default is `relay_demo`. Reload Relay to see imported entities and their Graphify source record.

To produce a new export, use Graphify's documented `/graphify ./your-scope` assistant command. An existing code graph can be refreshed with `graphify update ./your-scope` (AST-only, no model calls). Keep the scope within the importer limits below. Relay does not install Graphify hooks, run upstream commands automatically, or use Graphify Cloud.

## What is preserved

Both `nodes` + `links` and `nodes` + `edges` exports are accepted. Graphify may mark the whole file `directed: false` while retaining real arc directions in `_src` and `_tgt`. Those markers take precedence over wrapper endpoint order, and must identify the same two endpoints. Without markers, source/target order is preserved.

| Export relationship | Relay relationship |
| --- | --- |
| `depends_on` | `DEPENDS_ON` |
| `calls` | `CALLS` |
| `imports` / `imports_from` | `IMPORTS` |
| `contains` | `CONTAINS` |
| Other relationships | `RELATED_TO` |

Case is ignored for these mappings; the original relationship string remains in provenance. Calls, imports and generic proximity do **not** become outage dependencies.

Node types matching Relay's seven company kinds retain that kind. Functions, classes, files, and other code symbols become `document` entities with their original `node_type` retained in provenance. The adapter preserves `source_file` (or `file_path`), `source_location` (or integer `line`), and textual `confidence`, including supported fields nested under `metadata`. All imported nodes and edges cite a `code` source containing the normalized export. Unused export fields, clustering, weights, arbitrary metadata, and hyperedges are not imported. Source paths are labels only: the importer never reads those files or follows remote URLs.

## Limits and verification

- Input must be a local UTF-8 JSON regular file, at most 2 MiB.
- Each import is capped at 500 nodes, 1,000 edges, and 300 KB of normalized JSON. Field lengths are also bounded. Duplicate IDs, dangling endpoints, partial direction markers, duplicate JSON fields, and nonfinite JSON values are rejected.
- Repeating an identical import does not duplicate nodes or edges. This is an upsert importer, **not synchronization**: removed upstream records are not deleted. Use a separate graph for independent snapshots. Parallel relationships sharing the same source, target, and normalized type collapse to one graph edge; their original entries remain in the provenance source.
- This imports supplied structure. It does not extract new company knowledge from documents, infer operational dependencies, run GraphRAG-SDK, or certify the truth of upstream inferred links. Guided demo answers remain limited to the supported Meridian scenarios; arbitrary code questions need the live model connection and relevant retrieved context.

Verification during setup: adapter tests passed; the actual bundled HTTPX export imported **144 nodes and 330 edges** into a disposable FalkorDB graph. File/line provenance was read back, and importing the same file again preserved those counts. The bundled mixed-corpus export validated at **22 nodes and 38 edges**. The temporary verification graph was deleted afterward; these examples were not mixed into the default Meridian workspace.

```bash
uv run pytest backend/tests/test_graphify_adapter.py -q
uv run python scripts/import_graphify.py ../graphify/worked/httpx/graph.json \
  --source-name graphify-httpx-example --validate-only
```
