# Relay

Relay connects company knowledge, exact document evidence, and approval-controlled agent work in FalkorDB. Ask about the fictional Meridian company's Atlas launch, explore dependency changes with **Ripple**, or run an invoice review: company research continues while Finance waits for its auditor, then approved tools compare rows and produce a report and an internal exception case. LangGraph coordinates execution; the graph remains the authority for permissions, state, receipts, and memory.

## Run locally

Requirements: Docker with Compose v2, Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22.12+ (Node 24 is supported), npm, Bash 4.3+, and curl. Docker must be running. The development services use loopback ports 6379, 8000, and 5173.

From this checkout:

```sh
uv sync --frozen
npm --prefix frontend ci
# Configure a private RELAY_ACCESS_PASSWORD (at least 16 characters) first.
# Copy .env.example to the ignored .env file and edit it privately.
set -a
source .env
set +a
./scripts/start-db.sh
# First installation only, with a new graph and empty private data directory:
.venv/bin/python scripts/startup.py --initialize --quiesced --enable-execution
./scripts/dev.sh
```

The start script starts FalkorDB, checks a real Cypher write/read in a temporary graph, launches the API and frontend, and waits for the API health endpoint through Vite's proxy. The frontend serves on port **5173** and the API on **8000**. Keep the command running while using Relay. Ctrl-C stops the application servers; the database and its data remain available.

Sign in as **owner** with your configured first-account password. It creates the first administrator only; changing the environment variable never resets an existing account. Provision a separate Finance auditor with `scripts/manage_members.py` and explicitly assign the reviewer before using workflows; see [account setup](docs/persistence.md#provision-members-and-the-finance-reviewer) and [the workflow walkthrough](docs/workflow-demo.md).

No model credential is needed for **Guided demo** mode. It uses real graph retrieval, exact file parsing, decimal invoice comparison, reports, and durable tasks. Free-form interpretation and report narrative use Groq when configured; Guided demo labels its deterministic excerpts and explanations. A failed live call remains a visible failure.

Existing databases require an explicit backup and migration while application writers are stopped; use the upgrade procedure instead of the first-install command above. HTTP startup and health checks never seed or migrate a database. Follow [the migration and recovery instructions](docs/persistence.md); preserve the graph, checkpoints, uploads, and reports together.

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
| `RELAY_DATA_DIR` | `.data` | Private uploads, reports, checkpoints, and backups |
| `RELAY_BOOTSTRAP_ADMIN_LOGIN` | `owner` | First administrator login |
| `RELAY_ACCESS_PASSWORD` | unset | Private first-account password; used only when no members exist |
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

The first request validates the backend's real database query. The second also validates the development proxy. See [the workflow walkthrough](docs/workflow-demo.md) for the new features and [the company-map demo](docs/demo.md) for Ripple, questions, and memory.

With Relay running and system Chromium available, `node scripts/browser-check.mjs` checks the existing company features and `node scripts/browser-workflow-live.mjs` checks the full two-member approval workflow against the real API. Supply account credentials through a private mode-0600 file using `RELAY_BROWSER_CREDENTIALS_FILE`; see [the workflow guide](docs/workflow-demo.md). Reports and screenshots stay under ignored `.data/`. Set `RELAY_BROWSER_EXECUTABLE` for a different Chromium path. These checks create labeled fictional records in the sample workspace. `node scripts/record-demo.mjs` additionally uses system ffmpeg to capture the workflow in `.data/relay-demo.mp4`.

Current verification evidence and limitations are in [docs/verification.md](docs/verification.md). **Track 3 — Company Brain** is the recommended lead submission; the demo also shows graph-based actions for Track 1 and persistent memory/agent handoffs for Track 2.

## Database persistence and restarts

The official FalkorDB v4.22.1 image is pinned by manifest digest in `compose.yaml`. Its named volume retains graph data. Append-only persistence is enabled with an every-second fsync. The bundled database browser is disabled; only `127.0.0.1:6379` is published. Both development and hosted APIs require member sessions. This release is a single workspace, with distinct Finance access and output audiences.

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
- Selected PDF text, TXT, Markdown, and templated CSV files provide exact version/page/paragraph/row citations. Uploaded instructions cannot authorize agent tools.
- Finance work waits for a separate authenticated auditor. Optional requester review gates control report and case changes; automatic mode still requires Finance approval.
- Invoice amounts are compared with decimal arithmetic. The sample invoice/order pair produces 220.00/200.00 USD totals, a 20.00 difference, and row-2 evidence.
- Completed tools have graph-backed receipts. Reports download as HTML/CSV, discrepancies create internal cases, and corrected evidence resolves the same case through a new revision.
- Replacing a file makes dependent results historical. Revised plans reuse unaffected completed work. Follow-up questions use permitted completed outputs without reopening raw Finance files.
- Legacy manual tasks remain manual; their old done status never becomes an agent execution receipt. No payment, external message, or external ticket tool is included.
- The workspace uses fictional sample data. GraphRAG-SDK and Graphify remain optional reuse sources; this release does not claim automatic semantic link extraction.

Dependency attribution and license distinctions are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The implementation and reuse boundaries are documented in [the reuse assessment](docs/relay-reuse-plan.md).
