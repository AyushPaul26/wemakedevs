# Relay UX contract

## Product context

Relay helps teammates investigate Meridian's Atlas launch, inspect supporting sources, compare a recovery assumption, and approve internal follow-up tasks. The workspace is visibly sample company data. English is the current UI language; timestamps and counts use the browser locale and timezone with a Gregorian calendar. Target WCAG 2.2 AA. The product specification establishes no Japan-specific market or content requirements.

## Business-context sources

| Domain / scope | Authoritative source | Source type | Reviewed date |
|---|---|---|---|
| Permissions and external actions | `docs/relay-product-spec.md` — Scope and truthfulness | Product policy | 2026-10-17 |
| Graph, investigation, memory and task lifecycle | `docs/relay-product-spec.md` — Public API contract | API contract | 2026-10-17 |
| Deletion and retention | `docs/relay-product-spec.md` — Scope; no deletion flow is specified | Product scope | 2026-10-17 |
| Payment references | `docs/relay-product-spec.md` — Product; fictional outage scenario, no billing workflow | Product scope | 2026-10-17 |
| Legal and regulatory copy | `docs/relay-product-spec.md` — Scope; sample local workspace, no legal claims | Product scope | 2026-10-17 |
| Audience, content and demo disclosure | `docs/relay-product-spec.md` — Product and Scope | Product brief | 2026-10-17 |

This contract records UI consequences; the linked specification remains authoritative for domain rules.

## Visual contract

[DESIGN.md](DESIGN.md) owns visual intent. Model B makes `frontend/src/styles.css` the sole runtime token source, with the documented mapping mirrored in DESIGN.md. Shared controls live in `frontend/src/components/ui.tsx`. There is one light-content theme with a dark sidebar. Update the canonical stylesheet and document together, lint DESIGN.md, and check rendered styles when changing shared tokens.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Table Selection | Not applicable: no selectable table or bulk operation | Product scope | None | Confirm no bulk controls appear |
| Select/Listbox | Native scenario select in the Ripple workflow | This contract | Native; OS popup geometry accepted | Keyboard selection and narrow-screen open popup |
| Date | Native text formatting through Intl; no date input | API UTC timestamps and this contract | Display only | Locale and timestamp display |
| Form | SourceNoteForm.tsx and Assistant.tsx with shared Button and Status | API input contract and Validation below | Investigation and source-note creation | Invalid input, pending, error and successful submit |
| Scrollbar | Global baseline in frontend/src/styles.css | DESIGN.md | Component geometry only | Computed styles and visible keyboard scrolling |
| Toast | Status in frontend/src/components/ui.tsx and the single App.tsx toast live region | This contract | Info, success and error status | Live-region and persistent error checks |
| CRUD | App.tsx workflow state and api.ts requests, with shared Modal and Button | Public API contract | Create note, investigate, approve, complete | Full-flow browser check and service tests |

`Button`, `Modal`, `Status`, and `SourceButton` are the shared interaction owners. React Flow owns graph pan/zoom and node interaction, with a textual Ripple result as the non-spatial alternative. Equivalent action approval and source viewing behave the same from investigation results, saved memory, and Actions.

## Dataset navigation

This sample workspace is a bounded graph and a set of short lists, not an unbounded admin table. Memory returns the backend's bounded newest-first history. Knowledge search filters the loaded sample locally, immediately, and includes an explicit clear button. Empty lists explain what will populate them; a query with no match provides a clear/reset action. Any future large dataset needs explicit paging or Load more before introduction.

Navigation uses URL hashes and Knowledge search uses the q query parameter. Selected service and action filters remain transient application state in this single sample workspace. Never put questions, uploaded source content, credentials, or private investigation context in the URL. Navigation does not discard a pending operation or an unfinished source-note draft without an explicit recovery path.

## Flow ledger

| Operation | Trigger | Pending | Success destination | Success feedback | Failure recovery | Focus outcome | Source ref |
|---|---|---|---|---|---|---|---|
| Investigate | Ask a question | Disable duplicate submit; show agent activity | Current investigation | Source-backed answer and saved memory | Preserve question; show error and retry | Keep composer usable; announce answer | Public API: POST /investigate |
| Compare Ripple | Select service or toggle backup | Visible calculation state | Current Ripple panel | Updated path, exposure and assumptions | Show error; retry current scenario | Preserve scenario control focus | Public API: POST /ripple |
| Open source | Citation or knowledge item | Source loading status | Source Modal | Full source, author and date | Inline error with retry/close | Modal title/content; restore trigger on close | Public API: GET /sources/{id} |
| Add note | Save source note | Disable repeated save | Knowledge | Stored note with provenance | Preserve title/content and show error | Invalid field or updated knowledge context | Public API: POST /sources |
| Approve task | Explicit approval control | Disable repeated approval | Current action context | Approved status | Retain task and retry safely | Preserve action context | Public API: POST /actions/{id}/approve |
| Complete task | Complete an approved task | Disable repeated completion | Current action context | Done status | Retain approved task and error | Preserve action context | Public API: POST /actions/{id}/complete |
| Browse memory | Memory navigation | Loading status | Memory list | Persisted investigations | Visible reload/retry | Navigation remains available | Public API: GET /memory |

No delete, bulk mutation, external send, payment, or production operation is available. A hypothetical recovery comparison updates only the comparison presentation. Task approval remains explicit and internal; proposed tasks are never described as executed.

## Navigation and responsive behavior

Overview, Knowledge, Memory, and Actions share one navigation shell and operation vocabulary. Current navigation is visibly and programmatically identified. At narrow widths the shell and panels stack without hiding actions. Source excerpts, questions, owners, and titles wrap; long evidence can scroll inside its bounded viewer. Keep focused controls visible and preserve the modal trigger for focus restoration. Graph controls have accessible names; keyboard and textual alternatives must provide access to the same evidence.

## Overlays and feedback

The shared `Modal` wraps Radix Dialog. It has an accessible title, appropriate description, focus containment, Escape dismissal, background isolation, scroll locking, and focus return. Its content fits the visual viewport and long content scrolls without losing close/action controls. Approval identifies the task and clearly states that it creates an internal Relay follow-up. Routine local navigation and investigation do not require confirmation.

Shared `Status` presents inline progress and recoverable errors with appropriate live-region semantics. A single App.tsx toast live region acknowledges confirmed source and task writes, remains dismissible, and expires after five seconds; persisted item status provides the durable record. Critical errors stay with the affected operation; they are not temporary toast-only messages. Browser `alert`, `confirm`, and `prompt` are not used. A source-note draft must survive a failed save; closing or navigating away from a dirty draft requires preservation or an app-owned discard decision.

## Async and resilience

Mutations are pessimistic: report success only after the API confirms it. Disable repeat submits while pending and rely on the server's idempotent task transitions for retries. Repeated Ripple requests are stale-safe; a slower previous scenario cannot replace the user's current selection. Loading states remain visible and bounded in layout.

An unavailable graph or model produces a visible recoverable error. Do not silently replace failed live-model work with a demo answer. Display Guided demo when the API reports demo mode. No offline writes, background synchronization, or autosave are promised. Preserve safe input on request failure and offer a deliberate retry. No account/session-expiry UX is claimed for the single local sample workspace.

## Validation and accessibility

Product forms use `noValidate` and app-owned validation. Investigation requires a nonempty trimmed question of at most 2,000 characters; source-note content is bounded to the API's 30,000-character limit. Keep visible labels, associate help/errors with fields, expose invalid state, and focus the first invalid field. Errors state what to correct without discarding the entered text. Textareas use `resize: none` and sufficient visible space or scrolling.

Use native buttons for actions, meaningful headings, accessible icon names, clear focus outlines, and text alongside semantic color. Avoid hover-only evidence or controls. Clear search immediately, restore input focus, and do not trigger unintended submissions during IME composition. There are no secret-entry, clipboard-export, drag-only, role-management, or date-picker workflows in this release.

## Verification

Run every command in `premium-ui.json`, the strict premium static auditor, and the repository backend checks. Static audit is not evidence of browser accessibility or working API flows. Compare Overview and Actions for approval, feedback and source-view consistency.

Browser coverage must include desktop and narrow viewports; keyboard focus and modal focus return; open native scenario selection; real investigation and citations; Ripple mitigation; approval and completion; memory after reload; source-note validation; loading, empty/no-results, and recoverable errors; long content and reduced motion. Record actual results and unresolved limitations in the project verification report. Full screen-reader, assistive-technology, and cross-browser certification are not implied by a passing static check.
