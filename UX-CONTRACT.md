# Relay UX contract

## Product context

Relay helps teammates investigate Meridian's Atlas launch, inspect supporting sources, compare a recovery assumption, and approve internal follow-up tasks, and run a fixed invoice review with authenticated department approvals. The workspace is visibly sample company data. English is the current UI language; timestamps and counts use the browser locale and timezone with a Gregorian calendar. Target WCAG 2.2 AA. The product specification establishes no Japan-specific market or content requirements.

## Business-context sources

| Domain / scope                                             | Authoritative source                                                                   | Source type                    | Reviewed date |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------ | ------------- |
| Attachments, department permissions and workflow execution | `docs/relay-workflows-proposal.md` and `docs/relay-workflows-database.md`              | Approved feature/data contract | 2026-10-17    |
| Permissions and external actions                           | `docs/relay-product-spec.md` — Scope and truthfulness                                  | Product policy                 | 2026-10-17    |
| Graph, investigation, memory and task lifecycle            | `docs/relay-product-spec.md` — Public API contract                                     | API contract                   | 2026-10-17    |
| Deletion and retention                                     | `docs/relay-product-spec.md` — Scope; no deletion flow is specified                    | Product scope                  | 2026-10-17    |
| Payment references                                         | `docs/relay-product-spec.md` — Product; fictional outage scenario, no billing workflow | Product scope                  | 2026-10-17    |
| Legal and regulatory copy                                  | `docs/relay-product-spec.md` — Scope; sample local workspace, no legal claims          | Product scope                  | 2026-10-17    |
| Audience, content and demo disclosure                      | `docs/relay-product-spec.md` — Product and Scope                                       | Product brief                  | 2026-10-17    |

This contract records UI consequences; the linked specification remains authoritative for domain rules.

## Visual contract

[DESIGN.md](DESIGN.md) owns visual intent. Model B makes `frontend/src/styles.css` the sole runtime token source, with the documented mapping mirrored in DESIGN.md. Shared controls live in `frontend/src/components/ui.tsx`. There is one light-content theme with a dark sidebar. Update the canonical stylesheet and document together, lint DESIGN.md, and check rendered styles when changing shared tokens.

## Canonical UI Map

| Capability      | Canonical owner                                                                                                                             | Source of truth                         | Allowed variants                            | Verification                                        |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- | ------------------------------------------- | --------------------------------------------------- |
| Table Selection | Not applicable: no selectable table or bulk operation                                                                                       | Product scope                           | None                                        | Confirm no bulk controls appear                     |
| Select/Listbox  | Native selects in Ripple, evidence versions, company links and workflow composition                                                         | This contract                           | Native; OS popup geometry accepted          | Keyboard selection and narrow-screen open popup     |
| Date            | Native text formatting through Intl; no date input                                                                                          | API UTC timestamps and this contract    | Display only                                | Locale and timestamp display                        |
| Form            | SourceNoteForm.tsx, Assistant.tsx, LoginPage.tsx, AttachmentDialog.tsx, RunComposer.tsx and ApprovalInbox.tsx with shared Button and Status | API input contract and Validation below | Investigation and source-note creation      | Invalid input, pending, error and successful submit |
| Scrollbar       | Global baseline in frontend/src/styles.css                                                                                                  | DESIGN.md                               | Component geometry only                     | Computed styles and visible keyboard scrolling      |
| Toast           | Status in frontend/src/components/ui.tsx and the single App.tsx toast live region                                                           | This contract                           | Info, success and error status              | Live-region and persistent error checks             |
| CRUD            | App.tsx legacy state, feature-owned revision state and api.ts session transport with shared Modal and Button                                | Public API contract                     | Create note, investigate, approve, complete | Full-flow browser check and service tests           |

`Button`, `Modal`, `Status`, and `SourceButton` are the shared interaction owners. React Flow owns graph pan/zoom and node interaction, with a textual Ripple result as the non-spatial alternative. Equivalent action approval and source viewing behave the same from investigation results, saved memory, and Actions.

## Dataset navigation

The company graph remains bounded. Knowledge uses authorized server metadata search with 300 ms debounce, IME protection, stale-response rejection, an immediate clear control, and cursor paging. Sensitive source queries remain in memory rather than URL history. Workflows, approvals and timelines use server cursor pages with explicit Load more controls. Source content is loaded only for an authorized selected immutable version. Empty, loading, no-results and failed states provide a useful next action.

Navigation uses URL hashes: `#overview`, `#knowledge`, `#memory`, `#actions`, `#workflows[/id]`, and `#approvals[/id]`. Questions, file contents, credentials and private queries never enter URLs or persistent browser storage. Source-note drafts and workflow/upload/decision drafts are retained in the session-owned `SessionDrafts.tsx` memory provider through transient failures, modal dismissal and internal navigation. Logout deliberately clears every member-scoped draft and view. Unload protection applies to unsaved forms; drafts are not promised after a reload.

## Flow ledger

| Operation      | Trigger                         | Pending                                       | Success destination    | Success feedback                       | Failure recovery                        | Focus outcome                                 | Source ref                              |
| -------------- | ------------------------------- | --------------------------------------------- | ---------------------- | -------------------------------------- | --------------------------------------- | --------------------------------------------- | --------------------------------------- |
| Investigate    | Ask a question                  | Disable duplicate submit; show agent activity | Current investigation  | Source-backed answer and saved memory  | Preserve question; show error and retry | Keep composer usable; announce answer         | Public API: POST /investigate           |
| Compare Ripple | Select service or toggle backup | Visible calculation state                     | Current Ripple panel   | Updated path, exposure and assumptions | Show error; retry current scenario      | Preserve scenario control focus               | Public API: POST /ripple                |
| Open source    | Citation or knowledge item      | Source loading status                         | Source Modal           | Full source, author and date           | Inline error with retry/close           | Modal title/content; restore trigger on close | Public API: GET /sources/{id}           |
| Add note       | Save source note                | Disable repeated save                         | Knowledge              | Stored note with provenance            | Preserve title/content and show error   | Invalid field or updated knowledge context    | Public API: POST /sources               |
| Approve task   | Explicit approval control       | Disable repeated approval                     | Current action context | Approved status                        | Retain task and retry safely            | Preserve action context                       | Public API: POST /actions/{id}/approve  |
| Complete task  | Complete an approved task       | Disable repeated completion                   | Current action context | Done status                            | Retain approved task and error          | Preserve action context                       | Public API: POST /actions/{id}/complete |
| Browse memory  | Memory navigation               | Loading status                                | Memory list            | Persisted investigations               | Visible reload/retry                    | Navigation remains available                  | Public API: GET /memory                 |

No delete, bulk mutation, external send, payment, or production operation is available. Invoice workflows may write protected reports and internal exception cases only after the required scoped approvals. A hypothetical recovery comparison updates only the comparison presentation. Task approval remains explicit and internal; proposed tasks are never described as executed.

## Navigation and responsive behavior

Overview, Knowledge, Memory, Actions, Workflows, and Approvals share one navigation shell and operation vocabulary. Current navigation is visibly and programmatically identified. At narrow widths the shell and panels stack without hiding actions. Source excerpts, questions, owners, and titles wrap; long evidence can scroll inside its bounded viewer. Keep focused controls visible and preserve the modal trigger for focus restoration. Graph controls have accessible names; keyboard and textual alternatives must provide access to the same evidence.

## Overlays and feedback

The shared `Modal` wraps Radix Dialog. It has an accessible title, appropriate description, focus containment, Escape dismissal, background isolation, scroll locking, and focus return. Its content fits the visual viewport and long content scrolls without losing close/action controls. Approval identifies the task and clearly states that it creates an internal Relay follow-up. Routine local navigation and investigation do not require confirmation.

Shared `Status` presents inline progress and recoverable errors with appropriate live-region semantics. A single App.tsx toast live region acknowledges confirmed source and task writes, remains dismissible, and expires after five seconds; persisted item status provides the durable record. Critical errors stay with the affected operation; they are not temporary toast-only messages. Browser `alert`, `confirm`, and `prompt` are not used. A source-note draft must survive a failed save; closing or navigating away from a dirty draft requires preservation or an app-owned discard decision.

## Async and resilience

Mutations are pessimistic: report success only after the API confirms it. Disable repeat submits while pending and rely on the server's idempotent task transitions for retries. Repeated Ripple requests are stale-safe; a slower previous scenario cannot replace the user's current selection. Loading states remain visible and bounded in layout.

An unavailable graph or model produces a visible recoverable error. Do not silently replace failed live-model work with a demo answer. Display Guided demo when the API reports demo mode. No offline writes, background synchronization, or autosave are promised. Preserve safe input on request failure and offer a deliberate retry. The session gate checks the server before rendering company data. Expiry or 401 aborts every in-flight member request, invalidates late results through a global epoch, and unmounts the entire workspace including Assistant chat and drafts. No credentials, CSRF token or member data are written to persistent browser storage. Sign-out immediately clears local data after the server response; if server revocation cannot be confirmed, sign-in displays that limitation.

## Validation and accessibility

Product forms use `noValidate` and app-owned validation. Investigation requires a nonempty trimmed question of at most 2,000 characters; source-note content is bounded to the API's 30,000-character limit. Keep visible labels, associate help/errors with fields, expose invalid state, and focus the first invalid field. Errors state what to correct without discarding the entered text. Textareas use `resize: none` and sufficient visible space or scrolling.

Use native buttons for actions, meaningful headings, accessible icon names, clear focus outlines, and text alongside semantic color. Avoid hover-only evidence or controls. Clear search immediately, restore input focus, and do not trigger unintended submissions during IME composition. Sign-in allows password managers, paste and native autocomplete. There are no clipboard-export, drag-only, role-management or date-picker workflows.

## Verification

Run every command in `premium-ui.json`, the strict premium static auditor, and the repository backend checks. Static audit is not evidence of browser accessibility or working API flows. Compare Overview and Actions for approval, feedback and source-view consistency.

Browser coverage must include desktop and narrow viewports; keyboard focus and modal focus return; open native scenario selection; real investigation and citations; Ripple mitigation; approval and completion; memory after reload; source-note validation; loading, empty/no-results, and recoverable errors; long content and reduced motion. Record actual results and unresolved limitations in the project verification report. Full screen-reader, assistive-technology, and cross-browser certification are not implied by a passing static check.

## Evidence and workflow contract

`features/evidence/` owns metadata search, exact-version attachment selection, upload, human link confirmation and evidence viewing. An attachment is `{source_id, version_id}`; exact citations add chunk ID and page/paragraph/row locator. Legacy source citations remain labeled **Version not recorded**. Duplicate exact attachment chips collapse; replacing a version never silently retargets an earlier citation. Protected original downloads use authenticated blob transport, check errors before creating a file and show a recoverable error on failure. Source details show version history and authorized version replacement controls from server provenance. A confirmed replacement announces invalidated workflow IDs/count; stale approvals/results remain explicitly stale.

Uploads accept PDF, TXT, Markdown and narrowly templated CSV, five files per request and 10 MiB each. Finance file storage is separate from agent inspection: pending or restricted status never claims extraction success. Per-file batch outcomes remain visible and a retry must not conceal previously stored files. General company link proposals use exact existing chunks and authorized entities; confirmation explicitly accepts or rejects a proposal. Unavailable extraction is labeled as unavailable with a manual association option when authorized.

`features/workflows/` owns the fixed `invoice_review` composer, paged list/detail, persisted graph and readable steps, scope approvals, timeline, reports and separate exception cases. Composition requires two different exact finance source refs, up to three optional context refs, a project, automation choice and explicit audience. Both automation choices preserve mandatory Finance gates. A question mentioning an invoice never starts execution. An explicit **Ask about this run** control scopes Assistant to the named run's permitted stored outputs and decisions; no protected raw finance source is inferred.

Workflow snapshots merge only when `(generation, revision)` increases. Active visible runs poll every two seconds; route/member change cancels requests. Mutations suppress duplicate submission, use a UUID idempotency key and submit the displayed expected revision. A 409 refreshes current scope while retaining safe form values and decision reasons; the user reviews the new scope before resubmitting. A failed provider/API call remains failed and retryable. Guided demo narration and Live model narration remain visibly distinct from stored execution state.

Approval UI shows the assigned reviewer, requester, exact versions, tools, intended outputs, audience, expiry and current scope hash. Only the assigned reviewer has decision controls; a Finance requester cannot self-approve. Reject and Request changes require a reason. Missing reviewers remain waiting; elapsed time never grants consent. Controls are derived from server `allowed_controls` and scope, and the server remains the authority. Revision preview compares current and proposed inputs and explains selective stale/reuse behavior. Manual Actions preserve their legacy proposed/approved/done meaning and are never relabeled as agent execution.

## Canonical resolution and drift (workflow extension)

| Rule                                | Evidence                                                       | Verdict                  | Action                                                          |
| ----------------------------------- | -------------------------------------------------------------- | ------------------------ | --------------------------------------------------------------- |
| Purple, Sora headings, DM Sans body | Existing runtime tokens consumed by all new surfaces           | Match                    | No token change                                                 |
| Shared Modal/Button/Status          | New auth/evidence/workflow features import `components/ui.tsx` | Match                    | Retain shared owner                                             |
| Local source excerpt filtering      | Removed from App; KnowledgePage calls server metadata search   | Approved behavior change | Update paging/search contract above                             |
| Four-item mobile navigation         | Six destinations exceeded 390px width in browser verification  | Drift repaired           | Canonical responsive navigation uses three-column wrapping grid |
| Sessionless sample                  | Replaced by shared auth provider and global transport epoch    | Approved behavior change | Session contract above                                          |

Frontend interaction/browser evidence is in `frontend/src/features/interactions.test.tsx`, `frontend/src/workflows.test.ts`, and `frontend/browser-workflows.mjs`. The latter uses explicit mocked API fixtures and does not establish real backend execution. Full authenticated multi-member and legacy Ripple browser verification is owned by the integration suite.
