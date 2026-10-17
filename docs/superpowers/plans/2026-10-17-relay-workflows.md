# Relay Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the current Relay application with cited attachments and one branching invoice-review workflow that waits for an authenticated Finance auditor, executes permitted tools, and remembers verifiable results.

**Architecture:** Retain FastAPI, React, the company graph, Ripple, and existing investigations. FalkorDB owns source versions, access policy, workflow steps, approvals, execution receipts, and memory; LangGraph orchestrates bounded steps with SQLite checkpoints. Private files use persistent storage, while one executor resumes graph-backed work and enforces versioned permission at every boundary.

**Tech Stack:** Python 3.12+, FastAPI/Pydantic, FalkorDB v4.22.1 (existing pinned image), existing LangGraph/SQLite, Groq-compatible client, React 19/TypeScript/Vite, React Flow, existing Radix/UI primitives; add lightweight `pypdf`, `python-multipart`, and Argon2 password hashing with locked versions.

**Spec:** [Feature proposal](../../relay-workflows-proposal.md). [Database design and migration](../../relay-workflows-database.md) is the companion data contract.

**Status:** Approved for implementation by the user's “go on” instruction on 2026-10-17. Execution progress and verification are recorded in `.data/sdd/relay-workflows/progress.md`. Existing app code started from GitHub `work` at `c40a08f`. Development database migration is authorized after backup and rehearsal; paid hosting changes remain separate.

## Global Constraints

- Preserve existing source IDs, company dependencies, investigations, and `proposed|approved|done` manual tasks. Never relabel old manual completion as agent execution.
- First executable template: `invoice_review@1`, with a company-context branch, gated finance branch, then report/case/memory steps. No arbitrary workflow builder, generated executable code, payments, or external messages.
- Supported attachments: selectable-text PDF, TXT, Markdown, and narrowly templated CSV. Five files per request; 10 MiB per file; 50 PDF pages; 200,000 extracted characters per file; 2,000 CSV data rows.
- CSV headers are exactly `item_id,quantity,unit_price,currency`. Define quantity as an integer from 1 to 1,000,000; unit price as finite nonnegative decimal with at most two fractional digits, maximum 1,000,000,000; item ID matches `[A-Za-z0-9_.:-]{1,80}`. Currency is one of USD, INR, EUR, GBP and must agree across both files. No currency conversion or inferred schema.
- `item_id` is unique per file. Reject duplicate/missing/extra headers, duplicate IDs, malformed amounts, NaN/infinity, and mixed currencies. Cell length is at most 4,096 characters. Use decimal arithmetic, never model arithmetic.
- Finance approval precedes agent parsing/retrieval/model inspection. Grants bind run, plan, tools, input versions, policy, audience, and expiry; no global document unlock.
- Company policy permits two user preferences: `review_changes` and `auto_permitted`. The latter still obeys mandatory department gates.
- Only initial transport validation/hashing and authorized human source inspection precede the finance gate. Uploaded instructions cannot authorize tools.
- FalkorDB stays primary. Preserve dependency direction (dependent -> prerequisite); distinguish connected company context from proof of an actual launch blocker.
- Keep Live model and Guided demo visibly distinct. A failed live call stays a failed/retryable step. Missing live extraction does not become a fabricated successful extraction.
- Single workspace, one executor, maximum two active steps and one parser process. Session expiry is eight hours; default approval expiry is 24 hours. Step lease is 120 seconds with a 20-second heartbeat.
- Work in `/workspace/wemakedevs`, branch `work`, using the existing isolated checkout. Read relevant frontend skills before UI implementation. No new worktree, paid hosting activation, or deployment change during planning.

## Review Focus

- A delayed response after logout could show another member's evidence: Task 2/9 must invalidate requests and all member-scoped state.
- Approval races with source replacement, policy change, cancellation, or expiry: Task 5/8 must reject the old scope/fence at claim and final commit.
- A crash after file creation but before a graph commit could duplicate or lose an output: Task 6 must reconcile effect keys and immutable files before retry.
- A valid-looking CSV can contain duplicate IDs, exponent/NaN amounts, formula-like identifiers, or conflicting currencies: Task 3/6 must reject these instead of guessing.
- Old citations do not prove which file version was seen; a finance discrepancy does not prove launch failure: Task 1/4/6 must preserve provenance and state uncertainty.

---

## Existing-code map and planned boundaries

| Existing area | Change and new owner |
| --- | --- |
| `backend/relay/graph_store.py` | Keep company/Ripple/manual-task behavior; delegate connection handling to new `database.py`; require access context on user-facing reads/writes. |
| `backend/relay/seed.py`, `api.py` lifespan | Replace unconditional reseeding with schema checks/versioned fixtures. New `migrations.py` owns upgrade phases. |
| `backend/relay/hosting.py` | Replace shared Basic identity with the same session authentication used by development. Public health and login assets remain available. |
| `backend/relay/agents.py`, `llm.py`, `models.py` | Retain research/plan/archive questions; add access context, selected versions, exact evidence refs, and permitted run-memory questions. |
| New `auth.py`, `access.py`, `auth_routes.py` | Accounts/sessions, authorization decisions, login/session/logout API. |
| New `sources.py`, `source_store.py`, `storage.py`, `parsers.py`, `source_routes.py` | Upload/version metadata, private blob access, bounded parsing, chunks, link confirmation, and authorized search/evidence. |
| New `workflow_models.py`, `workflow_store.py`, `workflow_service.py`, `workflow_routes.py` | Shared contracts, persisted state transitions, fixed plan creation/revision, and HTTP boundary. |
| New `workflow_engine.py`, `workflow_tools.py`, `reports.py` | LangGraph orchestration, bounded tool registry, deterministic comparison, report/case effects, restart recovery. |
| `frontend/src/api.ts`, `types.ts`, new `routes.ts` | Method-aware JSON/multipart/download requests, typed contracts, existing hash routes plus Workflows/Approvals. |
| `frontend/src/App.tsx`, `main.tsx` | Session gate and navigation; move the affected Knowledge/source-view logic into feature components rather than enlarging the 900-line shell. |
| New `frontend/src/auth/` | `AuthProvider.tsx`, `LoginPage.tsx`: session lifecycle and credential form. |
| New `frontend/src/features/evidence/` | `types.ts`, `KnowledgePage.tsx`, `AttachmentDialog.tsx`, `AttachmentPicker.tsx`, `EvidenceViewer.tsx`, `LinkReview.tsx`. |
| New `frontend/src/features/workflows/` | `types.ts`, `RunComposer.tsx`, `WorkflowPage.tsx`, `WorkflowGraph.tsx`, `ApprovalInbox.tsx`, `WorkflowTimeline.tsx`, `WorkflowOutputs.tsx`, `useWorkflowRun.ts`. |
| `Assistant.tsx`, `SourceNoteForm.tsx`, `components/ui.tsx` | Attachment chips, run links, readable citations, corrected validation, existing shared focus/status/button patterns. |
| `scripts/serve.sh`, `dev.sh`, `Dockerfile`, `compose.yaml` | Schema readiness, executor lifecycle, data paths, and verified persistent storage preparation. |

Keep small helpers local. Do not introduce another UI library, router, queue, or state-management framework. Existing `state.ts` manual-action merging remains separate from revisioned workflow state.

## Shared contracts and state decisions

Define Pydantic contracts in `backend/relay/workflow_models.py` and equivalent TypeScript feature types. API request models forbid extra fields and use explicit enums/bounds.

- `SourceRef {source_id, version_id}` always selects exact immutable content.
- `EvidenceRef {source_id, version_id, chunk_id, locator:{page?,paragraph?,row_start?,row_end?}, title}` references existing, authorized chunks. Old `source_ids` remain supported without fabricated version refs.
- `SourceSummary {id,title,type,author,updated_at,current_version_id,classification,department_id,processing_status}` contains no full excerpt. `SourceDetail` adds authorized selected-version chunks and provenance.
- `MemberView {id,display_name,role,department_ids}` excludes private account/session fields. `SessionView {member,csrf_token,expires_at}` is available only to the session holder.
- `RunCreate {template:'invoice_review',invoice:SourceRef,purchase_order:SourceRef,context:SourceRef[],project_id,automation:'review_changes'|'auto_permitted',output_audience:string[]}`. Maximum five selected files total. The server derives permitted reviewers and validates audience; IDs do not confer access.
- `RunSnapshot {id,template,current_plan_id,generation,revision,status,steps,approvals,outputs,cases,allowed_controls,created_at,updated_at}`. DTOs filter inaccessible content; steps expose identifiers/state/tool/evidence/results but never worker secrets.
- `ApprovalDecision {decision:'approve'|'reject'|'request_changes',expected_revision,scope_hash,reason?}`. Non-approval decisions require a reason of 1–2,000 characters. Reviewer identity comes from the session.
- Mutations use an `Idempotency-Key` UUID. Same key plus same canonical request returns the existing result; same key plus different content returns 409. Revisioned mutations additionally require `expected_revision`.
- Response states: 401 signed out/expired; 403 disallowed operation on a visible object; 404 missing or inaccessible evidence; 409 stale version/scope/revision; 413 size limit; 422 invalid input; 502 provider failure; 503 unavailable database/maintenance. Return sanitized error text.
- New workflow status never flows through `mergeActions()`. Merge snapshots by `(generation, revision)` and discard responses from old members or superseded requests.

Internal return types referenced by tasks are also explicit contracts: `MigrationReport {current_version,target_version,phase,counts,violations}`, `SourcePage/EventPage {items,next_cursor}`, `VersionResult {ref,source_revision,invalidated_run_ids}`, `StoredBlob {key,sha256,byte_size,mime}`, `ParsedDocument {chunks,table?}`, `ParsedTable {currency,rows:[{item_id,quantity,unit_price,row_number}]}`, `ComparisonResult {currency,invoice_total,order_total,difference,findings:[{item_id,kind,invoice_row?,order_row?,expected?,actual?}]}`, `StepLease {step_id,run_id,plan_id,generation,fence,worker_id,lease_until}`, `StepEffects {effect_key,result,evidence_refs,artifacts,case_revision?}`, `StagedArtifacts {items:[{kind,blob,content_hash}]}`, and `RecoveryReport {requeued,waiting,reconciled,failed}`. Monetary JSON fields are decimal strings. `EvidenceContext` extends existing nodes/edges/sources/prior_memories with chunks and permitted run outputs. `RunRevision {expected_revision,invoice,purchase_order,context,automation,output_audience}` uses the same bounds as `RunCreate`.

Authentication provisioning uses `RELAY_BOOTSTRAP_ADMIN_LOGIN` (default `owner`) with the existing securely configured `RELAY_ACCESS_PASSWORD` only for first-account creation. Password entry for `scripts/manage_members.py` uses a hidden prompt; no demo password is committed. `RELAY_DATA_DIR` defaults to `.data` in development and `/app/.data` in the hosted container. Provision a distinct Finance auditor and explicitly assign the Finance policy before the demo; do not infer that role from a seeded person's name.

Stable assertion examples for the owning tasks (fixtures implement the interfaces above):

```python
# Task 1: migration must not invent execution history.
assert after.legacy_ids == before.legacy_ids
assert after.action_statuses == before.action_statuses
assert after.execution_count == 0

# Task 5/6: blocked financial work must not inspect protected bytes.
assert run.steps["company_context"].status == "completed"
assert run.steps["finance_parse"].status == "waiting_approval"
assert protected_parser_calls == protected_model_calls == 0

# Task 6: code, not the model, determines these fixture results.
assert comparison.invoice_total == "220.00"
assert comparison.order_total == "200.00"
assert comparison.difference == "20.00"
```

### API additions and changed boundaries

| Endpoint | Contract |
| --- | --- |
| `POST /api/auth/login`, `GET /api/auth/session`, `POST /api/auth/logout` | Secure session cookie, member/CSRF view, revocation. Login returns a session view. |
| `GET /api/sources?query=&cursor=` | Authorized source summaries, stable cursor, 20 items/page. |
| `POST /api/attachments` | Multipart files plus bounded department/classification/title metadata; returns per-file refs/status. Document batch failures clearly; never silently lose a successfully stored file on retry. |
| `POST /api/sources/{id}/versions` | Authorized new immutable version; requires source revision; returns source ref and invalidated-run summary. |
| `GET /api/sources/{id}` | Authorized detail; optional version/run context. Existing source URL still works. |
| `GET /api/sources/{id}/versions/{version}`, `.../download` | Version metadata and protected original file download. |
| `GET /api/evidence/{chunk_id}` | Exact authorized text/locator; optional run context checked server-side. |
| `POST /api/sources/{id}/versions/{version}/links/review` | Exact proposal IDs, accept/reject, expected revision; accepted facts keep citations. |
| `POST /api/investigate` | Existing question/session fields plus optional `source_refs` and `run_id`; no automatic execution triggered by a question. |
| `POST /api/workflow-runs`, `GET /api/workflow-runs`, `GET /api/workflow-runs/{id}` | Create (202) or read fixed-template runs; list is cursor-paginated, 20 items/page. |
| `POST /api/workflow-runs/{id}/cancel`, `.../retry`, `.../revise` | Revisioned transitions; revision selects replacement inputs and reuses unaffected work. |
| `GET /api/approvals`, `POST /api/approvals/{id}/decision` | Assigned/visible inbox and server-authorized decision; 20-item pages. |
| `GET /api/workflow-runs/{id}/timeline` | Authorized ordered events, cursor-paginated. |
| `GET /api/artifacts/{id}/download`, `GET /api/cases`, `GET /api/cases/{id}` | Protected outputs and separate typed internal cases. Cases are not legacy Action DTOs. |

Bootstrap returns only authorized company data and source summaries, plus session capabilities; it no longer supplies all source excerpts for browser filtering. Capabilities must describe actual enabled parsers/tools. Preserve existing legacy endpoints with added authentication, ownership checks, and optional evidence fields.

## Task 1: Versioned database foundation and migration

**Files:** create `backend/relay/database.py`, `migrations.py`, `workflow_models.py`, `scripts/migrate.py`, `scripts/backup.py`, `backend/tests/test_migrations.py`, `test_db_capabilities.py`; modify `graph_store.py`, `seed.py`, `api.py`, and existing graph/API tests. Define the shared DTOs here so later tasks extend one contract owner.

**Interfaces:** `GraphDatabase(graph_name: str | None).query(statement: str, params: dict | None = None) -> list`; existing `GraphStore` exposes `.database` and preserves its `.graph`/`.db` test/admin accessors. `MigrationService(database, data_dir).inspect() -> MigrationReport` is read-only; `.apply(backup_manifest: Path) -> MigrationReport` resumes the documented phases. `ensure_schema(database) -> None` checks readiness without implicitly rewriting user data.

- [ ] Add capability tests in a unique `relay_test_*` graph for indexes/constraints, competing conditional claims, mutation rollback, and dependency traversal. Stop if the pinned database cannot enforce the required invariants.
- [ ] Add `test_upgrade_preserves_legacy_data_and_repeats_safely`: create a note, investigation and approved/done tasks; capture IDs/content/statuses; migrate twice; assert originals unchanged and exactly one snapshot version per source. Assert old citations remain unversioned and no `Execution` was fabricated. Add interrupted-batch resume and malformed/duplicate-ID refusal tests.
- [ ] Run `PYTHONPATH=backend .venv/bin/pytest backend/tests/test_migrations.py backend/tests/test_db_capabilities.py -q`; confirm failures exercise missing migration behavior rather than environment failure.
- [ ] Implement the companion schema/migration, private backup manifest, capability-gated indexes, deterministic snapshot/chunk IDs, maintenance barrier, and versioned seeding. Preserve serialized legacy content; user-facing source projections are adapted later. Migration refuses unsupported/newer schema and missing verified backup.
- [ ] Prove backup restoration and interrupted migration in isolated databases. Run migration plus existing graph tests; expected all selected tests pass. Do not migrate the user's real graph yet.
- [ ] Commit only the migration/foundation code and tests after reviewing the diff. Suggested commit: `feat: add versioned FalkorDB workflow migration`.

## Task 2: Member identity and access enforcement before private data

**Files:** create `backend/relay/auth.py`, `access.py`, `auth_routes.py`, `scripts/manage_members.py`, `backend/tests/test_auth.py`, `test_access.py`; modify `api.py`, `hosting.py`, `graph_store.py`, `agents.py`, `pyproject.toml`, `uv.lock`, current API/hosting fixtures. Create `frontend/src/auth/AuthProvider.tsx`, `LoginPage.tsx`, auth tests; modify `main.tsx`, `App.tsx`, `api.ts`.

**Interfaces:** `AccessContext(member_id, workspace_id, purpose, run_id=None, step_id=None)` in `access.py`; `AccessService(database).require(context, operation: str, resource_id: str) -> None`; `AuthService(database).login(username, password) -> SessionCredentials`, `.resolve(raw_token) -> SessionView`, `.logout(raw_token) -> None`. Internal session credentials never become a public DTO. User-facing `GraphStore` reads/writes require access context; seed/migration use a separate administrative path.

- [ ] Add auth/access tests asserting anonymous bootstrap is 401, wrong credentials fail, operator cannot decide Finance approvals, disabled members/session expiry revoke access, missing CSRF rejects a write, and private objects are absent from graph/search/memory/source responses. These must test direct API requests, not only hidden UI buttons.
- [ ] Run `PYTHONPATH=backend .venv/bin/pytest backend/tests/test_auth.py backend/tests/test_access.py -q` and the focused frontend auth test; confirm intended failures.
- [ ] Implement Argon2id hashes, random HttpOnly session cookies (Secure in hosted mode, SameSite=Lax), eight-hour expiry, CSRF validation on writes, and current membership checks. Add bounded failed-login throttling. Provision the first admin from the existing secure access-password setting only when no account exists; never reset credentials on restart. Additional member creation/role changes use the local administrator CLI with hidden password input, not passwords in argv or Git.
- [ ] Replace Basic identity in hosted mode; keep one shared auth boundary in both apps. Update every existing endpoint and investigation context with authorization. Login happens before bootstrap; logout clears chat, source caches, run polling, and pending requests. Reject late responses using a session generation token. Document the transition from username `relay` to the configured admin login.
- [ ] Update existing test fixtures to create/log in real test members; no public test-login bypass. Verify old Ripple/manual-task behavior with those members. Run auth/access/API/hosting tests and frontend auth tests; expected all pass, including delayed-private-response-after-logout.
- [ ] Commit the complete identity/access boundary. Suggested commit: `feat: enforce workspace identity and department access`.

## Task 3: Uploads, immutable source versions, and bounded parsers

**Files:** create `backend/relay/source_store.py`, `sources.py`, `storage.py`, `parsers.py`, `source_routes.py`, `backend/tests/test_sources.py`, `test_parsers.py`, small fixtures under `backend/tests/fixtures/invoices/`; modify `models.py`, `workflow_models.py`, `api.py`, dependency locks, and source routes. Move the existing source handlers into the source router; do not register duplicate routes.

**Interfaces:** `SourceStore(database).create_upload(access, metadata, blob) -> SourceRef`; `.add_version(access, source_id, expected_revision, blob) -> VersionResult`; `.list_sources(access, query, cursor) -> SourcePage`. `SourceService(...).ingest(access, ref: SourceRef) -> SourceDetail` checks purpose/grant before opening bytes. `parse_file(path: Path, mime: str) -> ParsedDocument` returns bounded chunks/locators and optional validated CSV rows; it never calls a model or database. `BlobStore(data_dir).put_stream(...) -> StoredBlob` enforces byte limits and generated keys.

- [ ] Add parser/upload tests for limits, accurate PDF page/text paragraph/CSV row locations, duplicate multipart retry, rejected encrypted/scanned-only PDF, unsupported format, path-like filename, duplicate headers/IDs, NaN/exponent amounts, mixed currency, and private source GET denial. Assert Finance upload stores no chunks and invokes no parser/model before authorization.
- [ ] Run `PYTHONPATH=backend .venv/bin/pytest backend/tests/test_sources.py backend/tests/test_parsers.py -q`; verify meaningful failures.
- [ ] Implement streaming size enforcement, per-file idempotency, private blobs, source versions, processing state/leases, and lightweight parsing in one resource-limited subprocess (30-second wall timeout, bounded memory/output). Add direct locked dependencies for PDF/multipart support. Limit aggregate request bytes as well as individual files.
- [ ] Chunk prose into bounded passages (maximum 2,000 characters), retain page/paragraph identity, and retain original CSV row numbers. Public/workspace parsing uses the same resumable processor; restricted parsing is scheduled only by an authorized workflow step. Partial failed extraction never becomes searchable completed content.
- [ ] Verify invalid uploads preserve retryable form metadata and successful files retain stable IDs. Run parser/source tests plus existing note-storage regression; expected all pass.
- [ ] Commit ingestion independently. Suggested commit: `feat: add versioned attachments with bounded parsing`.

## Task 4: Grounded attachment questions and company links

**Files:** modify `graph_store.py`, `agents.py`, `llm.py`, `models.py`, `source_store.py`, `sources.py`; create `backend/tests/test_attachment_answers.py`, `test_link_review.py`; modify agent fixtures and source/API tests.

**Interfaces:** `GraphStore.retrieve(question: str, access: AccessContext, source_refs: list[SourceRef], run_id: str | None) -> EvidenceContext`; `InvestigationService.investigate(question, session_id=None, *, access, source_refs=(), run_id=None) -> Investigation`. `SourceService.suggest_links(access, ref) -> list[LinkProposal]`; `.review_links(access, ref, decisions, expected_revision) -> SourceDetail`. Expose only existing authorized source/chunk IDs to model validation.

- [ ] Add `test_selected_attachment_is_not_lost_behind_legacy_source_limit`, forged/unauthorized chunk citation rejection, unrelated-run grant denial, historical unversioned citation display, and prompt-like attachment content treated as data. Assert no answer claims an unsupported launch block.
- [ ] Run the new attachment/link tests and confirm the expected failures.
- [ ] Implement authorized chunk retrieval prioritizing selected versions, with a bounded 24,000-character model context and per-source representation before supplementary company context. Label truncation/missing evidence; do not imply an entire oversized document was exhaustively read. Model context/citations use validated `EvidenceRef` values and authorized prior run outputs.
- [ ] Add compact evidence-backed proposals for `DOCUMENTS`, `RELATED_TO`, and `DEPENDS_ON` links between existing company entities, plus source-to-entity evidence association. Accepted links require exact source/chunk support and reviewer authority; rejected/conflicting links remain unresolved. This ingestion path cannot change member roles, approval policy, or access grants. Without a live model, offer manual source-to-entity association and explicit extraction-unavailable status, not fake semantic extraction.
- [ ] Preserve old questions and `source_ids`; clear repeated inline citation IDs in rendering via structured references. Run attachment/link/agent/API tests; expected all pass. Real Groq verification is reserved for the final integration task, outside deterministic tests.
- [ ] Commit grounded attachment retrieval. Suggested commit: `feat: answer from versioned attachment evidence`.

## Task 5: Fixed workflow plans, persisted steps, and approval inbox API

**Files:** create `backend/relay/workflow_store.py`, `workflow_service.py`, `workflow_routes.py`, `backend/tests/test_workflow_plans.py`, `test_approvals.py`; modify `workflow_models.py`, `api.py`, and shared authorization.

**Interfaces:** `WorkflowService.create_run(access, request: RunCreate, idempotency_key: str) -> RunSnapshot`; `.decide(access, approval_id, decision: ApprovalDecision, idempotency_key) -> RunSnapshot`; `.get_run(access, run_id) -> RunSnapshot`; `.cancel(access, run_id, expected_revision) -> RunSnapshot`. `WorkflowStore(database)` owns conditional graph mutations; all list methods accept access context/cursor.

- [ ] Add `test_company_lane_is_runnable_while_finance_waits` and `test_only_assigned_auditor_can_grant_exact_scope`. Assert the plan has two independent branches, finance has no content reads before approval, forged reviewer IDs cannot be supplied, double decisions return one event, and stale/expired/rejected decisions never make a protected step runnable. Validate unsupported templates, cycles, mismatched workspace/project/files, and duplicate idempotency keys with different inputs.
- [ ] Run `PYTHONPATH=backend .venv/bin/pytest backend/tests/test_workflow_plans.py backend/tests/test_approvals.py -q`; confirm expected failures.
- [ ] Implement immutable plans and deterministic step IDs using the database companion. The invoice/PO roles require Finance classification; do not allow a requester to bypass the mandatory gate by choosing a weaker run preference. Route the reviewer through Department/Policy/Member graph relationships; a missing/inactive reviewer produces a visible waiting reason.
- [ ] Implement pending, approved, rejected, changes-requested, expired, revoked, and stale approval handling. Decisions atomically validate current plan/policy/member/source versions and update event/revision. Finance grants authorize only the permitted read/tool/output scope; strict mode creates additional requester gates for exact report/case effects after their previews exist.
- [ ] Expose inbox, run list/detail, allowed controls, and cancellation using filtered DTOs. Private finance arguments/text never appear to an unauthorized observer just because the run is visible. Rejection/cancellation preserves completed context work but prevents unapproved joined publication.
- [ ] Run approval/plan/access/API tests with real FalkorDB, including two-client decision races; expected one accepted decision and no duplicate scope/event. Commit as `feat: add graph-routed workflow approvals`.

## Task 6: Durable branch execution and real invoice-review outputs

**Files:** create `backend/relay/workflow_engine.py`, `workflow_tools.py`, `reports.py`, `backend/tests/test_workflow_execution.py`, `test_invoice_compare.py`, `test_execution_recovery.py`; extend workflow store/service/routes, source service, and API lifespan.

**Interfaces:** `WorkflowEngine(store, sources, tools, checkpoint_path).start()`, `.stop()`, `.wake(run_id)` manage one background dispatcher; `.recover() -> RecoveryReport` reconciles pending/running work. `WorkflowStore.claim_step(step_id, worker_id, now) -> StepLease | None`, `.heartbeat(lease, now) -> bool`, `.commit_effects(lease, effects: StepEffects, now) -> RunSnapshot` enforce fence/generation/scope. `compare_invoice(invoice: ParsedTable, order: ParsedTable) -> ComparisonResult` is pure. `ReportService.stage(result, evidence, context) -> StagedArtifacts` creates immutable private files; the workflow store publishes their references and receipts atomically.

- [ ] Add execution tests asserting company context completes while finance waits; approval resumes without another Run click; exactly one known mismatch appears with correct row citations and decimal totals; a matching invoice has no new exception case. Assert a mismatch without documented launch policy is not called a launch blocker.
- [ ] Add recovery tests at claim, parse, model call, staged-file, and graph-commit boundaries. Race two claimers and double approval; assert one current fence/effect, no duplicate report/case, no visible missing-file artifact, and rejection of a late worker after cancellation. Run the new suites and confirm their expected failures.
- [ ] Implement a persistent dispatcher over graph-ready steps. Use independent LangGraph lane checkpoints (`run/branch/input-hash`) so a Finance interrupt does not suspend the independent company lane. Resume a finance checkpoint only after graph authorization; the join is runnable only after its prerequisite outcomes. Store permission decisions in FalkorDB, never in a trusted client checkpoint field.
- [ ] Implement bounded tools: `company_context`, `finance_parse`, `invoice_compare`, `publish_report`, `upsert_case`, `archive_run`. Tools use `AccessContext(purpose='agent',run_id,step_id)`; completed parsing does not unlock another run. No arbitrary network tool, shell tool, model Cypher, or external send.
- [ ] Implement deterministic decimal comparison and an escaped HTML report plus safe CSV export. Fixture: invoice item `gateway-seat`, quantity 2, price 110.00 USD versus order quantity 2, price 100.00 USD yields totals 220.00/200.00 and difference 20.00, with source row 2 cited. Preserve exact data; model-written explanation is additional grounded prose, not calculation authority.
- [ ] Implement stable artifact/effect IDs, separate execution receipts, and a run-scoped exception case with immutable revisions. Resolve an existing discrepancy via a new case revision when corrected evidence matches; do not fabricate a case when none existed. The owner comes from company relationships, with an explicitly unassigned state if no valid owner exists.
- [ ] Implement `review_changes` gates for each proposed report/case change; `auto_permitted` runs the preapproved output scope. Both stop at mandatory Finance approval. Archive records actual tools/outcomes; guided templates still label their narrative mode honestly. Provider failures are visible, with at most two bounded transient retries and explicit manual retry afterward.
- [ ] Run comparison/execution/recovery suites and authority races on real FalkorDB; expected correct results and one logical effect per step fingerprint. Commit as `feat: execute approved invoice workflows with receipts`.

## Task 7: Upload, evidence, and attachment-question interface

**Files:** create the evidence components/types in the boundary table and their focused tests; modify `App.tsx`, `Assistant.tsx`, `SourceNoteForm.tsx`, `api.ts`, `types.ts`, `components/ui.tsx`, `styles.css`, `DESIGN.md`, `UX-CONTRACT.md`.

**Interfaces:** `AttachmentDialog` returns confirmed `SourceRef[]`; `AttachmentPicker` selects exact authorized versions; `EvidenceViewer` opens `EvidenceRef` or a legacy source ID; `KnowledgePage` reads server-side source pages. `api.request<T>(path, options)` supports method/body/AbortSignal/response kind, same-origin credentials, and CSRF. Multipart requests leave Content-Type to the browser; download requests handle blobs and sanitized errors separately.

- [ ] Add focused tests for multipart headers, CSRF, precise version selection, pending/restricted processing, failed download, stale search responses, corrected note validation, and removing duplicate citation chips. Do not snapshot every component.
- [ ] Run `npm --prefix frontend run test -- --run` with the new focused file paths; confirm failures demonstrate absent behavior.
- [ ] Implement the feature components with the existing Button/Modal/Status patterns. Replace browser filtering over `bootstrap.sources[].excerpt` with authorized server search. Keep sensitive search text out of shared URL history; retain harmless existing Knowledge navigation behavior.
- [ ] Add attachment chips to Ask Relay and readable version/page/row citations. Offer the fixed invoice workflow through an explicit composer entry; mentioning an invoice in a normal question must not silently execute work. Preserve legacy questions, note entry/drafts, and source URLs.
- [ ] Update design/UX contracts for session expiry, uploads, processing states, access errors, evidence versions, and wider answer reading. Verify keyboard focus, screen-reader names, narrow layout, empty/error states, and visible mode labeling.
- [ ] Run frontend tests, `npm --prefix frontend run typecheck`, and `npm --prefix frontend run build`; expected all pass. Commit as `feat: add attachment evidence workspace`.

## Task 8: Version invalidation, selective reruns, and decision memory

**Files:** extend `source_store.py`, `workflow_store.py`, `workflow_service.py`, `workflow_engine.py`, `agents.py`, `llm.py`; create `backend/tests/test_workflow_revision.py`, `test_workflow_memory.py`.

**Interfaces:** `WorkflowService.revise(access, run_id, request: RunRevision, idempotency_key) -> RunSnapshot`; `.retry(access, run_id, expected_revision) -> RunSnapshot`; `WorkflowStore.invalidate_source(source_id, new_version_id) -> list[str]`; `.timeline(access, run_id, cursor) -> EventPage`. `RunRevision` contains replacement refs and expected revision; it cannot mutate an old plan's inputs.

- [ ] Add tests where only the invoice changes: finance/report/case results become stale; company-context step ID/result is reused; old approval cannot authorize the new version; the original report stays historical; corrected comparison updates the same case. Also change the company brief to prove that branch is not incorrectly reused.
- [ ] Add tests racing replacement/policy change/expiry with approval and commit. Assert changed plan generation/fence blocks late effects even before asynchronous invalidation finishes. Add memory tests that answer from the permitted report/decision and cannot retrieve raw private files via a past grant.
- [ ] Run revision/memory tests and confirm expected failures.
- [ ] Implement direct source-user lookup plus reverse step-dependency traversal; version replacement atomically changes current source pointer and revision, while any large downstream invalidation is recoverable. Each claim/final commit independently checks current inputs/policy. Derive the new plan and share only unaffected compatible completed steps.
- [ ] Store ordered events for real human/system actions and link saved investigations to the run/decision/output evidence. Return a paged timeline and grounded follow-up memory. A stale output is clearly historical; a past approval never grants new execution.
- [ ] Run revision/memory/execution/access suites; expected no stale-scope publication, correct step reuse, and no duplicated case. Commit as `feat: retain workflow decisions and rerun affected branches`.

## Task 9: Workflow, approvals, and result interface

**Files:** create workflow components/types from the boundary table and `routes.ts`; modify shell/navigation, `Assistant.tsx`, `api.ts`, `types.ts`, `styles.css`, `DESIGN.md`, `UX-CONTRACT.md`, `premium-ui.json`. Add focused frontend workflow tests and `scripts/browser-workflows.mjs`; update `scripts/browser-check.mjs` for authenticated fixtures.

**Interfaces:** `useWorkflowRun(runId)` polls every two seconds while visible/active, cancels on session/route change, and accepts only newer `(generation, revision)` snapshots. `RunComposer` submits explicit invoice/PO/context refs and automation preference. `ApprovalInbox` posts the displayed revision/scope hash. `WorkflowOutputs` uses protected downloads and distinguishes real cases from legacy manual tasks.

- [ ] Add tests for out-of-order polling, expired login/late response isolation, stale approval conflicts, rejected/request-changes states, repeated submit, failed download, and invalid replacement input. Run focused tests and confirm intended failures.
- [ ] Implement `#workflows`, `#workflows/<id>`, `#approvals`, and `#approvals/<id>` alongside existing routes. Render workflow graph and equivalent readable list from real persisted states; never animate a fabricated execution sequence.
- [ ] Show approval scope, named reviewer, exact versions, permitted outputs/audience, expiry, and decision reason. Show waiting cause when reviewer is missing. Prevent requester approval of Finance gates while retaining allowed requester gates in strict mode.
- [ ] Add timeline, evidence links, receipts, downloads, case details, cancel/retry/revise controls, and version-change explanation. UI success follows server confirmation; stale conflicts refresh the visible scope before retry. Keep legacy Actions/manual completion separately labeled.
- [ ] Run a browser flow with two separate authenticated contexts: operator uploads/starts, company branch completes, auditor approves, finance resumes, output appears, refresh retains it, replacement makes affected work stale, and reapproval produces a new report without a duplicate case.
- [ ] Verify 390-pixel layout, keyboard operation, focus restoration, accessible status announcements, and existing Ripple 3→1/negative-backup/note/memory regressions. Run frontend tests, typecheck/build, both browser suites, and relevant configured UI audits. Commit as `feat: show approval-driven workflow progress and outputs`.

## Task 10: Durable deployment, migration rehearsal, and end-to-end delivery

**Files:** modify `scripts/serve.sh`, `dev.sh`, `check.sh`, `Dockerfile`, `compose.yaml`, `.env.example`, `README.md`, `docs/deployment.md`, `docs/verification.md`, `docs/demo.md`, `docs/relay-product-spec.md`; create a separate `deploy/render-persistent.yaml` and `backend/tests/test_deployment_recovery.py`. Update dependency locks only as required by the preceding tasks.

**Interfaces:** `RELAY_DATA_DIR` owns private files and hosted database/checkpoints; existing `RELAY_CHECKPOINT_PATH` remains an explicit supported override. Startup checks schema before serving API traffic or starting the executor. Migration CLI accepts `--check` or `--apply --backup-manifest <path>`; apply is never inferred from a health check.

- [ ] Add recovery tests that replace a container against the same mounted data: waiting approval, completed report bytes/hash, source versions, and case history survive; restarted executor does not repeat completed effects. Test incomplete migration blocks writes, wrong/newer schema stops startup clearly, and missing storage never silently creates an empty replacement workspace.
- [ ] Run recovery tests on disposable data and confirm intended failures.
- [ ] Implement consistent data paths, non-root volume permissions, orderly executor/API/database shutdown, and startup schema checks. Prepare the persistent Render configuration without changing the active free service or charging the account. Record actual plan/disk cost before activation; a free-service deployment must retain explicit temporary-storage messaging.
- [ ] Rehearse backup, migration, restore, and second-run no-op against an isolated copy. Compare baseline IDs/text/statuses rather than fixed counts. Update old tests for the authenticated/versioned contracts without weakening behavior assertions.
- [ ] Run `./scripts/check.sh`, `.venv/bin/ruff check backend`, both browser suites, configured UI audits, and the Docker recovery check. Record actual counts/results and unresolved limits. Build with the managed cloud proxy/CA instructions; never disable TLS verification.
- [ ] Run one real Groq attachment question and workflow explanation with the existing securely configured provider, checking valid citations and saved memory. A quota/network failure is a reported limitation, not a silent Guided demo replacement. Deterministic tests do not consume provider quota.
- [ ] After implementation approval and successful rehearsal, apply the migration to the authorized development target with a verified backup, then validate the complete workflow. Migrate the hosted target only through the agreed deployment/storage procedure; development success is not proof of hosted durability.
- [ ] Commit reviewed implementation/docs and push `work`; confirm the remote hash. Update deployment only when the hosting configuration/access permits it, and verify the actual running service separately from the GitHub push. Produce a fresh short demo with live answers, the Finance gate, real outputs, and change-aware rerun.

## Task dependencies and review gates

Tasks 1 -> 2 -> 3 -> 4 establish data/access/evidence. Task 5 follows 2 and the Task 3 contracts; Task 6 follows 3–5. Task 7 can proceed after source/API contracts settle, in parallel with backend workflow work. Task 8 follows 5–6. Task 9 uses stable 5–8 APIs. Task 10 follows the integrated application.

Recommended execution: coordinate isolated backend/frontend tasks with explicit file ownership and independent review at the migration, authorization, execution, and final integration boundaries. Keep edits to shared API/types/schema files sequential. The plan does not require the user to manage agents or make low-level library decisions.

Do not expose restricted uploads before the access boundary passes. Do not enable execution before the database claim/commit invariants pass. Do not claim restart/redeploy durability before the replacement-container test passes. These are test gates, not additional feature-scope approval requests.

## Completion criteria

- Existing company map, Ripple, notes, questions, manual actions, and memory still work with authenticated users.
- The operator can upload selected attachments; answers open correct source versions/pages/rows.
- Company work proceeds while Finance waits; a real assigned auditor's scoped approval resumes the protected lane automatically.
- The comparator produces correct totals/findings, reports download successfully, and cases/receipts reflect actual execution.
- Retry/restart/duplicate approval cannot duplicate effects, and replacement evidence cannot reuse stale authorization.
- Follow-up questions and the timeline explain who approved what and what changed, within the viewer's access.
- Database migration preserves old data and is repeatable; deployment persistence is independently demonstrated or clearly reported as pending.

Only planning documents and read-only database inspection were performed while writing this plan. Product code, installed dependencies, the development database, and Render configuration remain unchanged.

