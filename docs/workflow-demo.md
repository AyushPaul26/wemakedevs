# Relay invoice review: reproducible demo and user guide

Use the fictional Meridian workspace and assigned development accounts. This demo creates stored evidence, workflow runs, approvals, reports, cases, and memory. Label your uploaded files `DEMO` so reviewers can recognize them. The operator and Finance auditor must be different accounts. Keep passwords and API keys in secure environment settings; never put them in a recording, chat, or tracked file.

## Start and sign in

Follow the README to start FalkorDB, the backend (including its executor), and the frontend. Open the app in your browser and enter your assigned **Username** and **Password**, then choose **Sign in**. Your account determines which evidence and approval requests you can see. Accounts are provisioned by an administrator; see [member and reviewer provisioning](persistence.md#provision-members-and-the-finance-reviewer). There is no public sign-up.

The **Guided demo** badge means narration is composed deterministically from stored evidence. **Live model** means the configured model supplies narration. File storage, approval decisions, calculations, execution receipts, and memory are real in both modes. A failed live model call leaves work failed and retryable.

## Upload the two Finance files

1. Open **Knowledge**, choose **Upload files**, then select these existing fixtures:
   - `backend/tests/fixtures/invoices/invoice.csv`
   - `backend/tests/fixtures/invoices/purchase-order.csv`
2. Select **Finance · approval required before agent inspection** under **Classification and department**. The optional title can name a single file; leave it blank for the two-file upload so their filenames remain distinct.
3. Choose **Upload files** inside the dialog. Wait for both per-file results, then choose **Close**. The files should say `waiting_approval`. Uploading does not start a workflow or authorize an agent to inspect Finance content.
4. Search Knowledge by filename or metadata. Open a source to inspect its provenance and immutable version. Your account may see only metadata until it has permission to inspect content. **Download original** and version replacement appear only when your account is permitted.

The invoice contains two gateway seats at USD 110 each; the purchase order contains two at USD 100 each. The code calculates USD 220 versus USD 200, a USD 20 difference. The model does not calculate these amounts.

Other supported files are selectable-text PDF, TXT, and Markdown. Upload at most five files and 10 MiB per file. PDFs have a 50-page limit. CSVs must have exactly `item_id,quantity,unit_price,currency`, unique item IDs, valid whole-number quantities, decimal prices with at most two decimal places, and one supported currency matching across both files. A scan-only PDF needs text extraction before upload. Read individual upload results if only some files are accepted.

## Start the branching review

1. Open **Workflows** and choose **New invoice review**.
2. In **Invoice**, search for and select the uploaded invoice. In **Purchase order**, select the other uploaded file. Each choice displays the exact version the plan will use.
3. Optionally select up to three **Optional company context** sources. Choose the Atlas project.
4. For this walkthrough choose **Review proposed report and case changes** under **Output automation**. In **Output audience member IDs**, keep the prefilled operator ID and, if needed, add the assigned auditor's ID supplied by your administrator, separated by a comma. Only members allowed by Finance policy can be added.
5. Choose **Start review**. The page shows stored workflow state, a dependency graph, a readable step list, plan approvals, and a decision/execution timeline.
6. Wait for **Company context** to complete while **Read finance files** remains **waiting approval**. The independent company branch can continue. Finance parsing, comparison, reports, and cases remain blocked by the mandatory gate.

The second automation choice, **Run permitted report and case changes automatically**, removes the separate requester output confirmations. Finance auditor approval still applies.

## Review the exact permission scope

1. In a separate browser profile or private window, sign in as the assigned Finance auditor. Open **Approvals**.
2. Open the request for this run. Read the plan's exact invoice and purchase-order versions, permitted tools, output audience, expiry, and complete permission scope. **Inspect invoice** and **Inspect purchase order** let the authorized auditor inspect the original evidence.
3. Enter a decision reason identifying this as a fictional demo. Choose **Approve permitted work** to permit the displayed scope. This grants inspection for this plan and exact versions only.
4. **Request changes** and **Reject** require a reason. Changes require the requester to revise the plan. A rejection stops the protected branch. Only the assigned authorized reviewer can decide; the operator cannot self-approve Finance access. A missing reviewer keeps work waiting.
5. Return to the operator's **Approvals**. Review the actual report preview and approve its **report write** request. Then review and approve the separate **case write** request. These are required by the review-changes preference.

If another action changes the scope while a decision is in flight, the app refreshes the request and preserves your reason. Review the refreshed scope before trying again. Expired or replaced approvals do not authorize later work.

## Read the result and ask a follow-up

1. Return to the workflow. The six steps are **Company context**, **Read finance files**, **Compare invoice and order**, **Publish report**, **Update exception case**, and **Remember result**.
2. Expand each **Execution receipt**. It identifies the stored tool execution, input hash, approval IDs, and timing. A manual task marked complete in **Actions** is a separate human action and does not create an agent execution receipt.
3. Under **Reports and internal cases**, use each **Download report** button to download the HTML reconciliation and discrepancy CSV. Choose **View case** to inspect the internal exception case and current revision. No payment or external message is sent.
4. Open exact citations in a step or response to see their version and page, row, or paragraph locator. Older investigations that did not record a version explicitly say so; their citation view cannot prove which historic version was read.
5. Choose **Ask about this run**. Ask “What discrepancy did this review find, what did it create, and does it prove a launch blocker?” The workflow chip shows the run used for context. The answer uses permitted stored outputs and decisions; a question never starts a workflow. Open **Memory** to revisit the saved investigation.

A Finance discrepancy is not proof that the Atlas launch is blocked. Company relationships establish context; the app should state uncertainty about an actual launch blocker.

## Correct a source and revise the plan

1. Make a local corrected copy of the invoice with these exact contents:

   ```csv
   item_id,quantity,unit_price,currency
   gateway-seat,2,100.00,USD
   ```

2. In **Knowledge**, open the demo invoice. Under **Replace with a new immutable version**, choose the corrected file and choose **Save new version**. Do this only for your demo invoice. The old version is retained, dependent approvals/results become stale, and the app reports affected workflows. Use **View version** to inspect history when available.
3. Return to the stale run. Choose **Revise inputs and plan**, select the invoice's new current version, keep the purchase order, and review the before/after exact inputs. Choose **Save revised plan**.
4. Observe the new plan generation. Unchanged company context can be marked **reused** with its existing receipt. Dependent Finance and report work requires fresh execution. The old Finance approval cannot authorize the corrected file.
5. Ask the auditor to approve the new exact scope. With review-changes selected, approve the new report and case proposals as the operator; with auto-permitted selected, these permitted effects continue automatically.
6. The corrected comparison has zero difference. The existing exception case gains a resolved revision. Earlier artifacts remain historical and may be marked stale.

## Other controls and recovery

- **Add knowledge** or Knowledge's **Add note** saves an original source note. Empty fields show errors, and closing/reopening preserves the draft. Notes do not automatically extract entities or create authoritative graph links.
- Where **Company links** is available, choose an existing **Company entity** and exact **Supporting evidence**, then **Propose company link**. Review pending proposals with **Confirm link** or **Reject link**. Unconfirmed proposals are not company facts. When extraction is unavailable, the app says so and allows supported manual association.
- **Cancel workflow** stops pending work. **Retry failed work** retries an eligible failure. Controls appear only for states and accounts that allow them. A stale workflow requires revised inputs and renewed approval.
- **Retry sources**, **Retry source**, **Retry workflow**, **Retry workflows**, **Retry timeline**, or **Refresh approvals** recover the relevant view after a temporary error. A repeated error preserves drafts instead of claiming success.
- **Sign out** removes member-scoped evidence, drafts, and run views. Sessions expire after eight hours. Sign in again to continue with current permissions.
- The company map, Ripple backup assumption, cited company questions, legacy **Actions**, and saved **Memory** remain available. See [the original map walkthrough](demo.md).

## Run the actual browser integration

The development services and executor must already be running. Install the frontend dependencies and use system Chromium or set `RELAY_BROWSER_EXECUTABLE`. Supply the development accounts through secure environment variables `RELAY_BROWSER_USERNAME`, `RELAY_BROWSER_PASSWORD`, `RELAY_BROWSER_AUDITOR_USERNAME`, and `RELAY_BROWSER_AUDITOR_PASSWORD`, or set `RELAY_BROWSER_CREDENTIALS_FILE` to an ignored private JSON file with mode `600`. Its shape is `{ "operator": { "username": "…", "password": "…" }, "auditor": { "username": "…", "password": "…" } }`; real values belong only in that private file. `RELAY_BROWSER_URL` selects the app's internal test URL.

```sh
node scripts/browser-check.mjs
node scripts/browser-workflow-live.mjs
node scripts/record-demo.mjs
```

The first script verifies the real legacy map, Ripple, investigations, manual task lifecycle, notes, search, session handling, desktop/mobile layout, and accessibility. The second performs the two-account upload, gate, requester confirmations, six receipts, report downloads, case, follow-up, corrected version, revised plan, fresh approval, reuse, accessibility, and logout flow. It creates new `DEMO` sources and a run each time; do not point it at a production workspace. It writes non-secret evidence under `.data/workflow-browser-live/`. No API responses are mocked. Credentials, cookies, and CSRF tokens are not written to reports, screenshots, or recordings.

The recording command runs the same real workflow and captures only authenticated scenes into `.data/relay-demo.mp4`; system ffmpeg is required. Set `RELAY_RECORD_LEGACY=1` to record the original map/Ripple/manual-task story instead. Neither recording captures the sign-in form.

`node frontend/browser-workflows.mjs` is a separate, explicitly mocked API interaction/accessibility test. Its report is useful for UI error handling and permissions display; it does not prove backend execution. Current verification results are recorded in `.data/sdd/relay-workflows/task-10-browser-report.md` after live execution.
