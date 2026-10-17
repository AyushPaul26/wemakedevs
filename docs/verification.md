# Verification record

## Hosted deployment and live workflow — 18 October 2026

The existing free service is live at
<https://relay-company-brain.onrender.com>. No paid plan or disk was activated,
and no demo video was published. Runtime commit
`04070c83242cdb2035276c47ff1959346701a144`, deployment
`dep-db9t3teq1p3s739get00`, became live at `2026-10-17T19:58:29.650914Z`.
The full direct HTTPS workflow passed **12/12 checks**, with no retry or fallback
in that final run.

Direct HTTPS checks verified the public application and assets, protected API
access, three separate member roles, secure cookies, origin rejection, CSRF
checks, and an enabled executor. A real workflow uploaded uniquely labelled
fictional Finance files, completed independent company work while Finance
remained blocked, rejected requester self-approval, accepted the assigned
auditor's exact scope, and waited for separate report and case confirmations.
It produced six execution receipts, USD 220 versus USD 200 totals, two private
downloads matching their stored hashes, and an internal exception case. The
company answer and report narrative used live Groq.

The original natural-language run follow-up returned HTTP 200 in live mode,
cited both actual reports, and saved its answer to memory. The answer correctly
identified unit prices of USD 110 versus USD 100, the internal case, and that the
discrepancy alone does not prove a launch blocker. All three sessions signed out
and lost protected access. The test deliberately paused 65 seconds before the
final model request because an earlier attempt encountered a confirmed HTTP 429
provider rate limit. This is paced test evidence, not a guarantee of unlimited
provider quota or a hidden application fallback.

The first hosted run follow-up failed with a provider HTTP error. Safe server
diagnostics were added without logging provider bodies, generated text or
credentials. The model's run context was then reduced from 18,942 to 1,585
serialized characters by removing repeated graphs, recursive archives and raw
Finance reference metadata. Exact calculated totals, permitted report IDs,
current/stale flags and omission counts remain. This measurement covers the run
section, not the whole request. Subsequent provider-rate-limit failures were
reported as failures. On commit `226d57d35904d7fe562d3fb9ff09ed4972ae9fff`,
a structured follow-up returned HTTP 200 in live mode, cited both actual reports,
and saved memory.

A natural-language follow-up also failed citation validation. The final
release separates source citations from explicitly declared, authorized report
citations; it does not grant access to raw Finance files or accept invented
report IDs. It also records only allowlisted validation subtypes in server logs.
The final hosted natural-language check passed as described above; earlier
failures were never presented as successful answers or saved memory.

Regression checks passed in focused groups: 107 compact-context/workflow tests,
121 citation/model tests, and 51 API/diagnostic tests. These groups overlap;
their counts are not added together or described as a fresh complete backend
suite. The earlier complete backend result is recorded separately below.

The browser rerun against the final hosted commit passed **7/7 checks**, with
21 real upstream requests, zero page errors and zero failed requests, through a
per-process verified HTTPS forwarding path. Native Chromium's direct hosted
connection was blocked in this environment. This establishes the tested
application flow through that forwarding path, not native Chromium TLS
validation against Render. The direct HTTPS API checks are separate evidence.

The service retains free-tier temporary storage. These checks establish the
tested workflow behavior, not persistence across container replacement or
redeployment. Added originals, reports, approval history and memory can be lost
when the free container is replaced. Verification evidence remains private
under `.data/sdd/relay-deploy/`; the final 12-check result is
`live-smoke-a91a17604706/summary.json` with its workflow, timeline and verified
downloads alongside it. No credentials, private evidence or video files are
included in Git.

## Local container verification before hosted deployment — 18 October 2026

The complete backend suite passed: **360 passed in 129.55s**, with no retries.
This includes explicit hosted executor opt-in, offline demo member provisioning,
and exact HTTPS-origin login behind an internal HTTP proxy. Backend/scripts Ruff,
Bash syntax, Compose configuration, and whitespace checks passed. No frontend
source changed in this follow-up.

The final container image
`sha256:107cdb800b9fa5f6dbe1505da2a50cfcbc5605c7157eea1ec4e06c03c17c2e91`
built with frozen dependencies and verified TLS. A disposable container ran under
512 MiB as UID 10001 with no published host ports. Before and after restarting
that container, owner/operator/Finance-auditor sign-ins succeeded, the executor
was enabled, compiled frontend assets loaded, authenticated APIs worked, unrelated
origins and missing CSRF tokens were rejected, and cookies retained
`Secure; HttpOnly; SameSite=Lax`. The member-management CLI was present and usable.
The disposable container was removed. This tests a container restart, not durable
storage across free-host replacement.

Before the hosted deployment, the public Render service's health endpoint
returned 200 with a connected graph in Guided demo mode. Its root returned the
earlier Basic Auth challenge (401), confirming the upgraded session UI was not
serving at that earlier check. At that point no Render deployment or paid
activation had occurred, and the running Codex environment had no Render API
credential binding or process variable. The later authorized deployments and
live checks above supersede that status.

Private evidence is in `.data/sdd/relay-deploy/`: `backend-tests.txt`,
`container-build.txt`, `container-smoke.txt`, and the replayable
`free-container-smoke.py`. No demo video or credentials are included in this
follow-up's Git changes. The following sections retain the earlier workflow
release's detailed browser, migration and replacement-recovery evidence.

## Earlier workflow release

Relay Workflows was verified in the cloud checkout on 2026-10-17 with real
FalkorDB, authenticated members, the background executor and Chromium. The
free Render app was then still on the earlier `c40a08f` baseline, verified live
by the user. The hosted deployments above supersede that earlier status.

## Earlier workflow release results

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
| Hosted update at that earlier checkpoint | Not verified then: the cloud network policy blocked Groq; no Render deployment or paid activation had occurred at that point |

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
- Guided demo and live model results remain distinct. Live company answers, report narration, and the natural-language report follow-up passed on the final hosted code release. The paced run does not establish unrestricted Groq quota, general document extraction, or arbitrary task execution.
- The free Render service has temporary storage. Direct HTTPS sign-in and session controls have passed; browser forwarding evidence has the limitation described above. The separate paid persistent Blueprint remains review-only; any future paid disk requires its own pricing, ownership and recovery verification. No wildcard proxy trust is assumed. See [deployment.md](deployment.md).
- Backup snapshots cover the approved data-root checkpoint. External `RELAY_CHECKPOINT_PATH` works for runtime/adoption, but initialization/upgrade refuses incomplete backup coverage. Keep verified backups off disk as well; see [persistence.md](persistence.md).
- Chromium and automated axe checks do not establish complete cross-browser or screen-reader certification. Optional GraphRAG-SDK ingestion is not a completed semantic integration. Cloud environment publication/restoration in a new task was not verified here.
