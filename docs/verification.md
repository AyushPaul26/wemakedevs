# Verification record

Relay Workflows was verified in the cloud checkout on 2026-10-17 with real
FalkorDB, authenticated members, the background executor and Chromium. The
existing free Render app remains on the earlier `c40a08f` baseline, verified live
by the user; this release has not been deployed there.

## Results

| Check | Result |
| --- | --- |
| Backend tests | Latest full run: **302 passed, 1 parser-timeout failure** in 431.85s; unchanged isolated rerun: **1 passed** in 8.45s. All 303 tests have passing evidence across those runs |
| Backend Ruff | Passed |
| Frontend tests | **31 passed across 6 files** in 25.95s |
| TypeScript and production build | Passed; Vite bundle-size advisory only |
| Actual workflow browser and recording | **11/11 passed**, no browser errors; completed desktop and 390px mobile axe reported zero violations, no overflow, logout passed |
| Actual legacy browser | **10/10 passed** without mocked routes; desktop/mobile-dialog axe reported zero violations |
| Mocked UI checks and audits | 6 browser checks passed; 3 axe scans reported zero violations; strict UI audit and design lint passed. Later focused completed/mobile regressions also passed |
| Development migration | Schema 1, verified backup/restore, legacy data and checkpoint preserved, repeat apply a no-op; execution explicitly enabled after verification |
| Candidate container replacement | Passed under 512 MiB, UID/GID 10001:10001; waiting approval, downloads, versions, case history and SQLite survived, with zero repeated effects |
| Final image build and hosted smoke | **Passed** after the code freeze, with frozen dependencies and TLS verification; local sign-in/static/readiness/session checks passed under 512 MiB |
| Shell and Compose | Bash syntax and `docker compose config --quiet` passed |
| Current-release live Groq / hosted update | Not verified: Groq is blocked by the current cloud network policy; no Render deployment or paid activation occurred |

The backend full run's one failure retained
`ParseError('Attachment processing timed out.')` in its LangGraph checkpoint
while Docker was building concurrently. With Docker stopped, the unchanged HTTP
test passed in 8.45s. The deliberate 30-second parser limit and assertions were
not relaxed. This is passing evidence for all 303 cases across runs, not a claim
of one pristine 303-test run.

## Workflow, migration and recovery

The actual browser flow uploaded protected Finance files, completed company work
while Finance waited, obtained distinct auditor and exact report/case approvals,
and automatically completed all six steps. Two downloads and an internal case
were verified, followed by cited output Q&A and saved memory. Replacing the
invoice created a new plan and fresh approval, reused company work, produced a
zero discrepancy and resolved the same case. These runs used Guided demo mode.

The authorized development migration preserved the original 24 entities,
12 sources, 9 investigations, 10 manual actions and 3 scenarios, including their
legacy data/status comparison. The checkpoint was unchanged, isolated restore
passed, repeated apply was a no-op and migration fabricated no execution
receipts. Execution was subsequently enabled explicitly for the verified demo.
The private record is `.data/sdd/relay-workflows/development-migration.json`.

Full replacement recovery was tested on the earlier candidate image
`sha256:9edcb4f13b7b401ca2e2ea20f0541c73f89f3dee49d656fbfc11a64c88e09fac`,
which predates the final lease-renewal, Ripple privacy and UI fixes. A new
container against the same unique volume, with initialization disabled,
preserved the waiting gate, 12 source versions, two authenticated download
hashes, one case revision and SQLite integrity. Seven receipts remained
unchanged; completed effects repeated zero times. Disposable resources were
removed. The final image receives a separate short hosted-session/static smoke;
the earlier full replacement result is not relabeled as a final-image rerun.

Final image:
`sha256:e820014e34f24628b5dc852419e857cdaa9ee0382d0007535f4fb2a6a60d75dd`.
Its separate 512 MiB smoke verified health, public sign-in HTML and compiled
JavaScript (200), anonymous bootstrap (401), same-origin owner login (200),
cross-origin login rejection (403), `Secure; HttpOnly; SameSite=Lax` cookies, and
authenticated session/bootstrap (200). Execution remained disabled on this fresh
workspace. It ran as UID 10001 with a unique disposable graph/volume and no
published host ports; the container and volume were removed. This is local
container evidence, not validation of Render's TLS ingress.

## Recording and evidence

The fresh recording is `.data/relay-demo.mp4`: H.264, 1440×1080, 44.000s,
1,391,647 bytes. `ffprobe` verified it and a complete ffmpeg decode exited 0.
It records the actual workflow; no API routes were mocked or feature assertions
removed to obtain the passing result.

Private evidence includes:

- `.data/workflow-browser-live/report.json`: 11 checks and 11 scenes, with screenshots, desktop/mobile axe reports and verified downloads alongside it.
- `.data/screenshots/browser-results.json`: 10 actual legacy checks and its desktop/mobile-dialog axe reports.
- `.data/sdd/relay-workflows/task-10-browser-report.md`, `record-demo-output.txt` and `legacy-browser-output.txt`.
- `.data/sdd/relay-workflows/task-10-persistence-report.md`, `task-10-container-recovery.txt` and its replayable harness.
- `.data/sdd/relay-workflows/final-http-rerun.txt` and `final-frontend-tests.txt` for the final focused retry and frontend run; `frontend/premium-audit.json` and `frontend/browser-results/` for UI audit/regression evidence.
- `.data/sdd/relay-workflows/task-10-final-container-smoke.txt` and its replayable harness for the final image smoke.

## Limits

- One workspace, one executor and the fixed invoice-review template are supported. Case creation is internal record keeping; it sends no external messages, makes no payments and modifies no external systems.
- Guided demo and live model results remain distinct. Current tests do not establish live Groq attachment/workflow behavior. Historical live Groq results from the earlier baseline do not verify this release.
- The free Render baseline has temporary storage. The separate paid persistent Blueprint is review-only; current pricing, disk ownership, verified ingress proxy ranges and real HTTPS same-origin sign-in must be checked before hosted readiness. No wildcard proxy trust is assumed. See [deployment.md](deployment.md).
- Backup snapshots cover the approved data-root checkpoint. External `RELAY_CHECKPOINT_PATH` works for runtime/adoption, but initialization/upgrade refuses incomplete backup coverage. Keep verified backups off disk as well; see [persistence.md](persistence.md).
- Chromium and automated axe checks do not establish complete cross-browser or screen-reader certification. Optional GraphRAG-SDK ingestion is not a completed semantic integration. Cloud environment publication/restoration in a new task was not verified here.
