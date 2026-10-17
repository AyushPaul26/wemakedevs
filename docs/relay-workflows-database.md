# Relay workflows: database design and migration

Status: implemented; schema version 1 applied to the cloud development graph on 2026-10-17 after a verified backup and isolated restore rehearsal. That development migration did not change the Render database. Later hosted deployments are recorded in [verification.md](verification.md); the free service uses temporary storage, and those deployments do not establish migration or preservation of its previous records. This document accompanies [the implementation plan](superpowers/plans/2026-10-17-relay-workflows.md) and [feature proposal](relay-workflows-proposal.md).

## Verified starting point

On 2026-10-17, read-only `GRAPH.RO_QUERY` calls against the **cloud development** graph `relay_demo` found 24 `Entity`, 12 `Source`, 9 `Investigation`, 10 `Action`, and 3 `Scenario` nodes. Tasks were 6 proposed, 2 approved, and 2 done. These are development counts, not a measurement of the Render deployment, and must not be hardcoded as migration expectations.

Before the upgrade, records used JSON `payload` for API display fields. `Action.status` and `approved_at` were authoritative scalar fields overlaid on that payload. Company edges connected `Entity` nodes. `Source.payload.excerpt` and `Source.search` contained source text. Startup called `seed()` without schema/version tracking. The upgrade preserves these legacy records and replaces startup seeding with explicit offline preparation.

Preserve all existing IDs, company dependency directions, investigation text, action states, and source links. Existing completed tasks remain **manual tasks**; no execution receipt or named reviewer may be invented for them. Old citations did not record a source version and remain labeled **Version not recorded**.

## Data ownership and storage

- FalkorDB remains the primary database for company knowledge, access rules, source metadata/chunks, workflow state, approvals, outputs, and memory.
- SQLite remains LangGraph checkpoint storage, not an alternative business database. It never overrides a rejected/stale approval in FalkorDB.
- Original files and generated downloads live under a private `RELAY_DATA_DIR` outside frontend assets. FalkorDB stores generated storage keys and content hashes, never user-supplied filesystem paths.
- Runtime identity, status, access classification, versions, and leases use explicit scalar properties. JSON payloads are display data, not authorization decisions.
- Use the explicit workspace ID `meridian`. This release is one workspace, not a claim of multi-tenant isolation.

## Schema version 1

Every new record has a generated or deterministic `id`, `workspace_id` where applicable, and UTC timestamps. Hashes use SHA-256 over canonical serialized inputs; passwords use Argon2id, not SHA-256. Tokens and password hashes are never included in public DTOs or logs.

| Label | Important properties | Purpose |
| --- | --- | --- |
| `SchemaMigration` | `id`, `version`, `status`, `phase`, `last_id`, `checksum`, `backup_manifest` | Tracks migration completion and restart progress. |
| `Workspace` | `id`, `schema_version`, `seed_version`, `maintenance` | Gates startup/writes and records seed/schema versions. |
| `Member` | `id`, `login`, `display_name`, `password_hash`, `role`, `active`, `auth_revision` | Identifies actual users. Initial roles: `admin`, `operator`, `finance_auditor`. |
| `Session` | `id` = opaque-token digest, `member_id`, `auth_revision`, `expires_at`, `revoked_at`, private CSRF value | Server session; never stores the raw bearer token. |
| `Department` | `id`, `name`, `current_policy_id` | Initially General and Finance. |
| `Policy` | `id`, `department_id`, `version`, `reviewer_id`, `allowed_tools`, `approval_ttl_seconds` | Immutable department policy; default approval lifetime 86,400 seconds. |
| `Source` (extend) | existing ID/title/type; `workspace_id`, `current_version_id`, `department_id`, `classification`, `uploader_id`, `revision` | Stable document identity. New restricted sources have metadata-only payload/search. |
| `SourceVersion` | `source_id`, `number`, `content_hash`, `mime`, `storage_kind`, `blob_key`, `byte_size`, `classification`, `department_id`, `uploader_id`, `processing_status`, processing lease fields | Immutable bytes and provenance; separate mutable processing state. Legacy versions can use `legacy_inline` storage. |
| `SourceChunk` | `version_id`, `ordinal`, `text`, `locator_json`, `content_hash` | Bounded extract with page, paragraph, or CSV row location. |
| `LinkProposal` | `version_id`, source/target entity IDs, allowlisted relation, evidence chunk IDs, status, reviewer, revision | Small ingestion confirmation flow; unresolved suggestions are not company facts. |
| `WorkflowRun` | `requester_id`, `template`, `template_version`, `current_plan_id`, `generation`, `revision`, `status`, `cancelled_at` | Durable user request and current state. |
| `WorkflowPlan` | `run_id`, `number`, `scope_hash`, `automation`, selected version IDs, `output_audience`, `policy_id` | Immutable proposal for a run generation. |
| `WorkflowStep` | `run_id`, `logical_key`, `tool`, `tool_version`, `arguments_json`, `input_hash`, `status`, `attempt`, `fence`, `lease_owner`, `lease_until`, `result_id` | Persisted execution unit. Stable ID derives from run, logical key, and input fingerprint. |
| `Approval` | `run_id`, `plan_id`, `scope_hash`, `gate_kind`, `requester_id`, `reviewer_id`, `policy_id`, `status`, `expires_at`, `decision_at`, `reason`, `output_audience`, `revision` | Exact permission and human decision. Gate kinds: `finance_access`, `report_write`, `case_write`. |
| `Execution` | `step_id`, `effect_key`, `attempt`, `fence`, `tool`, `input_hash`, `approval_ids`, `status`, start/end times | Receipt for actual tool work. |
| `Artifact` | `execution_id`, `effect_key`, `kind`, `blob_key`, `content_hash`, `classification`, audience, `stale` | Stored HTML report or CSV discrepancy download. |
| `ExceptionCase` | `run_id`, `owner_entity_id`, optional `assignee_member_id`, `current_revision_id`, `status` | Stable internal follow-up; never pretends an external notification was delivered. |
| `CaseRevision` | `case_id`, `execution_id`, findings, evidence references, decision/status | Immutable case history, including corrected evidence. |
| `RunEvent` | `run_id`, `sequence`, event kind, actor ID, resource IDs, timestamp | Ordered decision/execution timeline. Human and system actors are distinct. |

Do not make workflow, session, or financial row records `Entity` nodes. This preserves the company map and Ripple's `Entity`-to-`Entity` meaning. Supplier entities may add `kind='supplier'` with UI support. An actual account maps to a company person only through an explicit administrator assignment; seeded names never become login accounts automatically.

Existing `Entity`, `Investigation`, `Action`, and `Scenario` gain workspace/access metadata as needed. Old `Action` records gain `record_kind='legacy_manual'` and retain their scalar status. New investigations may include `evidence_refs` and `run_id`; old JSON remains readable without those optional fields.

## Relationships

| Relationship | Meaning |
| --- | --- |
| `Member -MEMBER_OF-> Department`, `Member -REPRESENTS-> Entity` | Membership and explicit company identity mapping. |
| `Department -GOVERNED_BY-> Policy` | Policy versions; `current_policy_id` selects the active one. |
| `Source -HAS_VERSION-> SourceVersion -HAS_CHUNK-> SourceChunk` | Document versions and exact evidence. |
| `LinkProposal -USES_SOURCE-> SourceVersion`, `-SUPPORTED_BY-> SourceChunk` | Evidence behind a suggested company link. |
| `WorkflowRun -REQUESTED_BY-> Member`, `-HAS_PLAN-> WorkflowPlan` | Requester and immutable proposals. |
| `WorkflowPlan -HAS_STEP-> WorkflowStep` | Explicit plan membership; unchanged steps may belong to successive plans. |
| `WorkflowStep -DEPENDS_ON-> WorkflowStep` | Dependent to prerequisite, matching existing dependency direction. |
| `WorkflowStep -USES_SOURCE-> SourceVersion`, `-ABOUT-> Entity` | Source versions and company context used. |
| `WorkflowStep -REQUIRES_APPROVAL-> Approval` | Gate before a step is runnable. |
| `Approval -ASSIGNED_TO/DECIDED_BY-> Member` | Requested reviewer and actual deciding identity. |
| `Approval -AUTHORIZES-> WorkflowStep`, `-PERMITS_SOURCE-> SourceVersion` | Exact action/read scope. |
| `WorkflowStep -EXECUTED_AS-> Execution -PRODUCED-> Artifact` | Verifiable execution and outputs. |
| `Execution -REVISED-> CaseRevision -VERSION_OF-> ExceptionCase` | Idempotent case evolution. |
| `Artifact/CaseRevision/Investigation -CITES_VERSION-> SourceVersion`, `-CITES_CHUNK-> SourceChunk` | Precise new citations; preserve legacy `CITES->Source` links separately. |
| `WorkflowRun -HAS_EVENT-> RunEvent`, `Investigation -ABOUT_RUN-> WorkflowRun` | Replay timeline and follow-up memory. |

Company entities keep existing `DEPENDS_ON`, `OWNED_BY`, and evidence relationships. Workflow impact traversals must anchor their node labels, not mix company and execution graphs just because relation names match.

## Access and approval invariants

1. Authentication is required before bootstrap in development and hosted apps. Public endpoints are limited to health, login, and static login assets.
2. `AccessContext` is constructed by the server from the current session: member, workspace, purpose (`human` or `agent`), and optional run/step. A request cannot set its own role or approval state.
3. Finance uploads may be hashed and stored before approval. Authorized uploaders/auditors can inspect originals as humans; that permission does not let an agent parse, retrieve, or send them to Groq.
4. The run grant includes plan, steps, tools/versions, canonical arguments, exact file versions, policy version, audience, and expiry. Validate it before processing and again when publishing effects.
5. No `unlocked` flag exists on a document. Cached extracted chunks remain restricted, even after one approved run finishes. Unrelated questions/runs need their own authorization; authorized questions about a completed report can use its permitted output, not automatically its protected raw files.
6. Default finance policy grants report visibility to the named requester and assigned auditor only, in addition to authorized administrative access. It does not globally grant the requester access to other finance documents.
7. Search, bootstrap, source/graph APIs, memory, evidence, artifact downloads, and statistics are filtered server-side. Hide inaccessible objects with 404; reject an unauthorized operation on a visible run with 403. No full private excerpts are sent for client-side filtering.
8. Before any restricted record is enabled, replace current unscoped `get_graph`, `retrieve`, and `list_memories` calls with access-aware services. Old memory JSON can contain quoted source text and must also be permission-checked.

## Workflow state and reliable effects

Template `invoice_review@1` has an independent `company_context` step and a finance lane (`finance_parse` -> `invoice_compare`). `publish_report` depends on company context and comparison. `upsert_case` depends on comparison and report and records a skipped outcome for matching invoices with no prior exception. `archive_run` joins report/case outcomes. Finance processing has a gate before parsing. Strict-review mode adds requester approval of the exact report/case changes; auto-run mode uses the already approved bounded output scope.

Run/step states: `queued`, `running`, `waiting_approval`, `completed`, `failed`, `rejected`, `cancelled`, `stale`. A step can also be `skipped`, an explicit successful no-op prerequisite outcome. Approval states: `pending`, `approved`, `rejected`, `changes_requested`, `expired`, `stale`, `revoked`.

Use one executor initially, maximum two active tool steps, one parser subprocess, 120-second step leases with 20-second heartbeats. Claim, heartbeat, cancellation, decision, and completion use conditional database writes with expected revision/fence. A single process lock is insufficient across restart or independent clients.

Before claim/commit, check current plan membership, run cancellation/generation, prerequisites, current policy and source versions, and approval scope/expiry. Increment the fencing token on each new claim. A late worker with an old token cannot publish after cancellation, invalidation, expiry, or lease recovery.

Each effect has a stable key derived from run, logical step, input fingerprint, and output kind. Store receipt, graph artifact/case changes, final step state, run revision, and event together in one validated graph mutation. On an uncertain connection result, inspect the receipt before retrying. Prove actual atomic behavior on the pinned server before depending on it.

Write downloads to private temporary files, flush, then publish immutable content-addressed blobs before referencing them in the graph. A crash can leave an unreferenced blob, but must not produce a completed artifact pointing to a missing file. Never overwrite a previous version's file.

New source versions increment source revision and make matching approvals/steps stale. Follow reverse `WorkflowStep.DEPENDS_ON` to invalidate downstream outputs. A revised plan reuses unchanged step IDs and creates fresh affected steps and approvals. Every claim/commit also compares approved input versions with current source pointers, so a delayed invalidation worker cannot grant stale work. Past receipts stay immutable; case corrections add a revision to the existing run's case.

An invoice discrepancy is not proof of a blocked launch. Require explicit policy evidence plus the correct directed company dependencies before making that claim.

## Indexes and capability checks

Use scalar indexes for every label's ID; unique IDs where supported, unique normalized `Member.login`, and unique execution/artifact effect keys. Additional lookup indexes: source workspace/department, source-version source ID, chunk version ID, run requester/status, step run/status/lease deadline, approval reviewer/status/run, and case run ID. No vector index is needed for this bounded release.

Task 1 must probe exact supported syntax/readiness for indexes and uniqueness constraints on the pinned FalkorDB v4.22.1, and test concurrent conditional writes, multi-record mutation failure, and reverse dependency traversal on a disposable graph. Do not assume Neo4j locking syntax, arbitrary multi-statement transactions, or atomicity based only on syntax acceptance. If the required behavior cannot be proved, keep execution disabled and revise the persistence design before enabling it.

## Migration procedure

1. **Preflight:** inspect current schema, server capabilities, ID uniqueness, mandatory payload validity, available storage, and per-label ID/status fingerprints. `--check` is read-only. Do not call `seed()` first.
2. **Quiesce:** stop API writes and the executor. On deployment, start the database in maintenance before serving application traffic; avoid old/new writers running simultaneously.
3. **Backup:** create a consistent FalkorDB snapshot plus the checkpoint database and private data directory, with a private manifest/checksums. Restore the backup in an isolated database/container and verify IDs/statuses before upgrading the real target. Backups stay ignored and are never committed.
4. **Mark:** create migration `001_workflows` with checksum, phase, cursor, and backup reference. API writes remain disabled while it is incomplete.
5. **Backfill in batches:** preserve all existing payloads and IDs; add workspace/classification metadata; create deterministic version-1 snapshots and chunks from current legacy excerpts; mark source versions as migration snapshots; label old tasks manual. Retain old citation links and their unversioned meaning.
6. **Adapt source access:** keep original legacy payloads intact while the new adapter returns authorized metadata/detail views from version/chunk storage. New sources use metadata-only payloads. Do not duplicate protected text into a global search field or use old unscoped search paths. Reclassifying an already shared legacy source is outside this migration; a restricted attachment is a separate protected record.
7. **Policies/indexes:** create the verified indexes/constraints; add General/Finance department policy records. Provision actual accounts separately. Missing Finance reviewer leaves the gate waiting.
8. **Validate:** compare preflight IDs, original text/status fingerprints, source-version integrity, action hydration, company dependency directions, and new access rules. Run a second migration invocation to prove it is a no-op.
9. **Finish:** set expected schema/seed versions and migration complete, then enable the new API and executor. Unknown newer schemas fail startup clearly.
10. **Failure/restart:** stay in maintenance and resume the last verified phase. Deterministic IDs and cursor updates after successful batches make retries safe. Never clear or reseed the whole graph to repair migration. Restore a backup only through an explicit recovery operation, with a consistent code/data version.

Replace unconditional seeding with a versioned seed manifest: unchanged sample data produces no new versions; intentional seed updates are explicit and do not overwrite user changes. Migration itself does not add new company graph entities; the separate demo-fixture seed adds Finance/supplier context without manufacturing human approval.

## Deployment layout and verification

`RELAY_DATA_DIR` contains `graph/`, `checkpoints.sqlite`, `uploads/`, `artifacts/`, and private `backups/`. Development Compose continues to retain its database volume; hosted startup uses the same configurable root for its embedded database and files.

The existing Render free service has no persistent disk. Prepare a separate persistent-disk Blueprint/configuration without silently changing the active free service or activating paid resources. A replacement-container test using the same mounted data must preserve a waiting approval and completed download. A restore test must verify graph, file hashes, and checkpoint consistency. Snapshot recovery revokes restored sessions and expired grants before traffic resumes.

## Development migration result

The upgrade preserved all 24 company entities, 12 sources, 9 investigations, 10 manual actions, and 3 scenarios present immediately before migration. Exact legacy IDs, payloads, statuses, company edges, and citation links matched before and after. The existing SQLite checkpoint file was unchanged and passed its integrity check. Twelve legacy source snapshots were added; no execution receipt was invented for historical tasks. Repeating the migration was a no-op.

The graph/file backup and restore verification evidence remain private under `.data/backups/`; the migration report is `.data/sdd/relay-workflows/development-migration.json`. Storage adoption passed readiness checks. Execution was left disabled until explicit opt-in for the separately provisioned demo accounts and browser verification. Later labeled demo records are verification data, not part of the original migration counts. The paid Render configuration remains unactivated.
