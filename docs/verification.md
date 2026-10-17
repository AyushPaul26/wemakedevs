# Verification record

Environment: Codex cloud, Python 3.12.14, Node 24.19.0, Docker 28.4.0, Compose 2.40.3, system Chromium. This record describes the running instance, not an independently restored task or public deployment.

## Executed checks

| Command or workflow | Result |
| --- | --- |
| `./scripts/start-db.sh` | Real FalkorDB PING and Cypher write/read passed; unique temporary graph deleted |
| Database restart | A temporary fact survived a container restart; the test graph was then deleted |
| `./scripts/dev.sh` startup, shutdown, restart | API and Vite proxy health passed; supervisor stopped both child servers and released their ports |
| `./scripts/check.sh` | 54 backend tests, the initial 7 frontend tests, TypeScript, and production build passed |
| Final frontend checks | 16 tests across 4 files, TypeScript, and production build passed; includes stale action responses and evidence-correct recovery highlights |
| Frozen cloud install script | `uv sync --frozen`, `npm ci`, database readiness, and production build passed; app restart then passed API/proxy health |
| `.venv/bin/ruff check backend` | Passed |
| `UV_CACHE_DIR=/workspace/.cache/uv uv sync --frozen` | Passed |
| Real Graphify HTTPX export import and repeat import | 144 nodes / 330 edges stored in a disposable FalkorDB graph, provenance retained, no duplicates |
| `node scripts/record-demo.mjs` | Captured a 32-second silent video of real Guided demo interactions; ffprobe confirmed a valid MP4 |

Backend coverage includes directed impact paths, alternate dependency routes, backups exposed to the same outage, idempotent approval, completion ordering, persisted sources/memory, unavailable-database recovery, durable LangGraph checkpoints, and model failures. Provider unit tests use HTTP mocks. A real Groq investigation was subsequently verified with openai/gpt-oss-20b: HTTP 200, live mode, two valid citations, three agent steps, and persistence in FalkorDB memory.

## Browser checks

The project-owned runner is `node scripts/browser-check.mjs`. It uses the installed frontend Playwright dependencies and `/usr/bin/chromium` (override with `RELAY_BROWSER_EXECUTABLE`). Start the application first. It adds sample investigations, internal actions, and source notes to the current sample workspace.

All **12 browser workflows passed**, with no uncaught browser exceptions: graph rendering, 3→1 backup exposure, rejection of stale scenario responses, keyboard node evidence, dialog focus restoration, cited investigations and three handoffs, approval/completion, memory after reload, note validation/draft persistence/storage/search, visible investigation failure followed by successful retry, desktop accessibility/layout, mobile dialog/reduced motion, and bootstrap recovery.

Desktop and mobile-dialog axe checks reported **zero violations** for WCAG 2 A/AA and 2.1 AA tags. One impact-label contrast issue found in the first run was corrected with a dedicated text color and verified in the final run. Final results are recorded in `.data/screenshots/browser-results.json`. Generated screenshots and axe reports remain local under `.data/screenshots/`.

A final focused browser check verified the rendered recovery highlight after its guard was tightened: Payment gateway's supported Backup provider is green, while Identity service has no unsupported recovery highlight. Six unit regressions also cover unhealthy backups, backups exposed to the same outage, consumers that remain exposed, incorrect edge directions, and unchanged exposure counts.

The premium UI static audit also passed in strict mode with zero findings. The maintained UI contract documents native scenario selection, modal focus ownership, source-note drafts, and action state transitions. Full deletion is intentionally outside the product scope; note creation/read and task approval/completion are the implemented lifecycle operations.

`DESIGN.md` lint reported zero errors and warnings. Groq defaults, the secure key requirement, the tested installation script, and startup instructions were saved in the cloud environment draft. Saving is confirmed; publication and restoration in a new task have not been tested.

## Limits

- Live Groq access is configured for this cloud checkout using a private, Git-ignored local environment file authorized by the user. The secret value is not stored in source or in the configuration draft. Proxy-secret binding and environment publication are separate from the verified current application. Groq account quota still applies; ChatGPT Pro does not supply API credits.
- The browser runs Chromium only. Automated accessibility checks and keyboard flows do not establish complete screen-reader or cross-browser certification.
- GraphRAG-SDK is an optional dependency, not a completed or verified semantic ingestion integration.
- The production frontend builds, with a bundle-size advisory from Vite. A separate password-protected test deployment entry point is included; multi-tenant production authorization is not implemented.
- No public deployment or environment publication has been verified. The Render setup link is not a live app URL.

## Live Groq connection

Authenticated model discovery confirmed that the previous llama-3.3-70b-versatile model was unavailable on this account. The default was updated to the available openai/gpt-oss-20b model. A real end-to-end investigation through the frontend proxy returned Devon Park as the payment owner, validated both citations, completed all three agent steps, and saved the live result in memory. The 15 focused agent tests and Ruff also passed after the default change.

## Public test deployment preparation

The separate `relay.hosting` entry point adds browser Basic authentication and serves the built frontend. All 64 backend tests passed, including 10 deployment-boundary tests covering unauthorized requests, malformed credentials, static traversal, actual graph health failures, and response headers. The deployment files received an independent code review.

The Docker image built with the frozen Python/npm dependencies and normal TLS verification. Its first run found unreadable copied source files under the non-root runtime user; explicit read/traverse permissions fixed this and the rebuilt image passed. A real container limited to 512 MiB served health, blocked anonymous app requests, rendered the graph in authenticated Chromium without page errors, returned Ripple exposure 3→1, and persisted a cited investigation in its embedded FalkorDB. Observed memory was approximately 89 MiB; this is a small sample workload, not a load test. Missing access-password configuration stopped the container before starting services. The image contains neither the local `.env` nor Git metadata or frontend dependency caches.

The hosted-container tests used Guided demo mode. Live Groq was separately verified in the development application; no Groq key was copied into the image. Render account/API access is still required to create and verify a public service URL. The Blueprint selects the free plan and temporary storage, and its fields were checked against Render-maintained documentation sources. Render's API was blocked by the current proxy policy and no hosting credential was configured; a `RENDER_API_KEY` requirement and `api.render.com` destination were saved in the cloud draft for review.
