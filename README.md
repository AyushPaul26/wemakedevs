# Relay

Relay is a company intelligence workspace built on FalkorDB. Investigate the fictional Meridian company's Atlas launch, explore a disruption with **Ripple**, inspect the supporting sources, and approve follow-up tasks. Company relationships, investigation memory, and actions live in FalkorDB; LangGraph's SQLite checkpoints retain workflow progress.

## Run locally

Requirements: Docker with Compose v2, Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22.12+ (Node 24 is supported), npm, Bash 4.3+, and curl. Docker must be running. The development services use loopback ports 6379, 8000, and 5173.

From this checkout:

```sh
uv sync --frozen
npm --prefix frontend ci
./scripts/dev.sh
```

The start script starts FalkorDB, checks a real Cypher write/read in a temporary graph, launches the API and frontend, and waits for the API health endpoint through Vite's proxy. The frontend serves on port **5173** and the API on **8000**. Keep the command running while using Relay. Ctrl-C stops the application servers; the database and its data remain available.

No model credential is needed for **Guided demo** mode. Its deterministic answers are labelled in the application. It still uses the real database for retrieval, Ripple, memory, and approved tasks. It does not call a live model or perform semantic extraction.

## Public test deployment

[Create a Render test deployment](https://dashboard.render.com/blueprint/new?repo=https%3A%2F%2Fgithub.com%2FAyushPaul26%2Fwemakedevs) from branch `work`. The Blueprint selects one free Docker service and generates a browser-access password. This opens Render setup; the running app URL is provided after deployment succeeds. See [deployment instructions](docs/deployment.md) for login, Groq configuration, and temporary-storage limits.

## Optional Groq model

Set `RELAY_MODEL_API_KEY` securely in your shell or cloud environment settings to use Groq's OpenAI-compatible chat API. Defaults are `https://api.groq.com/openai/v1` and `openai/gpt-oss-20b`. A provider error is surfaced to the user; it does not silently become a successful live-model answer.

For local overrides, copy `.env.example` to the ignored `.env` file and edit it locally. Never commit or paste a credential into chat. The scripts treat `.env` as trusted Bash configuration; an already injected model credential takes precedence over its local value. In a managed cloud environment, keep credentials in its secure settings and retain the configured proxy and TLS trust. Groq calls require network access to `api.groq.com` and a valid credential; no paid or free quota is guaranteed by Relay.

| Variable | Default | Purpose |
| --- | --- | --- |
| `RELAY_FALKORDB_HOST` | `127.0.0.1` | API connection to FalkorDB |
| `RELAY_FALKORDB_PORT` | `6379` | Local database port and Compose port mapping |
| `RELAY_FALKORDB_GRAPH` | `relay_demo` | Company graph name |
| `RELAY_CHECKPOINT_PATH` | `.data/checkpoints.sqlite` | LangGraph workflow checkpoints |
| `RELAY_MODEL_API_KEY` | unset | Optional Groq/OpenAI-compatible credential |
| `RELAY_MODEL_BASE_URL` | `https://api.groq.com/openai/v1` | Compatible provider API base |
| `RELAY_MODEL` | `openai/gpt-oss-20b` | Provider model ID |

## Verify the application

```sh
./scripts/check.sh
```

This starts and probes FalkorDB, runs backend tests without a live-provider credential, checks frontend types, runs frontend tests, and builds the production frontend. Database tests use their own disposable graph names. To check the running API directly:

```sh
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:5173/api/health
```

The first request validates the backend's real database query. The second also validates the development proxy. See [the demo walkthrough](docs/demo.md) for the user workflow and [the product specification](docs/relay-product-spec.md) for behavior and limitations.

With Relay running and system Chromium available, `node scripts/browser-check.mjs` runs the browser workflows and accessibility checks. Reports and screenshots are saved under `.data/screenshots`. Set `RELAY_BROWSER_EXECUTABLE` for a different Chromium path. These checks create fictional test records in the sample workspace. `node scripts/record-demo.mjs` additionally uses system ffmpeg to capture a silent walkthrough in `.data/relay-demo.mp4`.

Current verification evidence and limitations are in [docs/verification.md](docs/verification.md). **Track 3 — Company Brain** is the recommended lead submission; the demo also shows graph-based actions for Track 1 and persistent memory/agent handoffs for Track 2.

## Database persistence and restarts

The official FalkorDB v4.22.1 image is pinned by manifest digest in `compose.yaml`. Its named volume `relay_falkordb-data` mounts `/var/lib/falkordb/data`. Append-only persistence is enabled with an every-second fsync. The bundled database browser is disabled; only `127.0.0.1:6379` is published. The application and database are local development services, without production authentication or multi-tenant isolation.

```sh
./scripts/start-db.sh           # Safe to repeat; preserves company data
docker compose logs falkordb    # Inspect database startup
docker compose stop falkordb    # Stop only this project's database
./scripts/dev.sh               # Restart the whole development workflow
```

`docker compose down` preserves the named volume. Do not add `--volumes` unless you deliberately want to delete the stored company graph, investigation memory, and actions. Retain `.data/checkpoints.sqlite` to preserve workflow checkpoints. FalkorDB contains durable company knowledge; the SQLite file is not a substitute for the graph.

In a restored cloud task, files and installed dependencies may be present while processes are stopped. Use the existing checkout and run `./scripts/dev.sh` again; a new Git worktree is not needed. If port 8000 or 5173 is already occupied, the script stops before launching another server and leaves the existing process alone.

When a cloud workspace permits writes only below `/workspace` and `/tmp`, use writable dependency caches before the install commands:

```sh
export UV_CACHE_DIR=/tmp/relay-uv-cache
export npm_config_cache=/tmp/relay-npm-cache
```

## What the demo proves

- Ripple follows directed dependency relationships and keeps hypothetical effects separate from stored company facts. Exposure counts are not probabilities or financial forecasts.
- Investigation results include graph-backed sources and visible agent handoffs. Saved memory and approved actions persist in FalkorDB.
- Approvals create internal Relay tasks. They do not send messages, file external tickets, or change production systems.
- The workspace uses fictional sample data. Provider-backed document extraction remains optional and is not claimed by Guided demo. GraphRAG-SDK is an optional ingestion dependency; Graphify is an optional import source.

Dependency attribution and license distinctions are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The implementation and reuse boundaries are documented in [the reuse assessment](docs/relay-reuse-plan.md).
