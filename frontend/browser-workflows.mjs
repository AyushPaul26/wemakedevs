/** Browser interaction checks with explicit API fixtures; no backend execution is claimed. */
import assert from "node:assert/strict";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
const base = process.env.RELAY_BROWSER_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({
  executablePath: "/usr/bin/chromium",
  headless: true,
  args: ["--no-sandbox"],
});
const out = new URL("./browser-results/", import.meta.url);
await mkdir(out, { recursive: true });
const member = {
  id: "operator",
  display_name: "Operator",
  role: "operator",
  department_ids: ["general"],
};
const auth = (who) => ({
  member: who,
  csrf_token: "browser-fixture-csrf",
  expires_at: "2099-01-01T00:00:00Z",
});
const refs = [
  { source_id: "invoice", version_id: "invoice-v1" },
  { source_id: "order", version_id: "order-v1" },
];
const sources = refs.map((ref, index) => ({
  id: ref.source_id,
  current_version_id: ref.version_id,
  title: index ? "Purchase order CSV" : "Invoice CSV",
  type: "csv",
  author: "Operator",
  updated_at: "2026-10-17",
  classification: "finance",
  department_id: "finance",
  processing_status: "waiting_approval",
}));
const bootstrap = {
  workspace: { name: "Meridian", project: "Atlas", is_demo: true },
  nodes: [
    {
      id: "project",
      label: "Atlas",
      kind: "project",
      description: "Atlas project",
      status: "active",
      source_ids: [],
      x: 0,
      y: 0,
    },
  ],
  edges: [],
  sources,
  stats: { entities: 1, relationships: 0, memories: 0, actions: 0 },
  capabilities: { mode: "demo", provider: "fixture", document_ingestion: true },
  recent_memory: [],
  actions: [],
};
const approval = {
  id: "approval",
  run_id: "run",
  gate_kind: "finance_access",
  reviewer_id: "auditor",
  reviewer_name: "Finance auditor",
  requester_id: "operator",
  status: "pending",
  scope_hash: "scope-1",
  expected_revision: 2,
  expires_at: 1893456000,
  scope: {
    invoice: refs[0],
    purchase_order: refs[1],
    tools: [{ tool: "finance_parse" }],
    output_audience: ["operator"],
  },
};
const run = {
  id: "run",
  template: "invoice_review",
  current_plan_id: "plan",
  generation: 1,
  revision: 2,
  status: "waiting_approval",
  steps: [
    {
      id: "company",
      logical_key: "company_context",
      tool: "company_context",
      status: "completed",
      depends_on: [],
    },
    {
      id: "finance",
      logical_key: "finance_parse",
      tool: "finance_parse",
      status: "waiting_approval",
      depends_on: [],
    },
  ],
  approvals: [approval],
  outputs: [],
  cases: [],
  allowed_controls: ["revise", "cancel"],
  created_at: "2026-10-17",
  updated_at: "2026-10-17",
};
const errors = [];
const checks = [];
async function fixture(context, who, { signedIn = false } = {}) {
  let authenticated = signedIn;
  let revision = 2;
  let decisionCount = 0;
  await context.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let status = 200,
      data = {};
    if (path === "/api/auth/session") {
      status = authenticated ? 200 : 401;
      data = authenticated ? auth(who) : { detail: "Authentication required" };
    } else if (path === "/api/auth/login") {
      authenticated = true;
      data = auth(who);
    } else if (path === "/api/auth/logout") {
      authenticated = false;
      status = 204;
    } else if (path === "/api/bootstrap") data = bootstrap;
    else if (path === "/api/sources")
      data = { items: sources, next_cursor: null };
    else if (path.startsWith("/api/sources/"))
      data = {
        ...sources[0],
        provenance: {
          source_revision: 1,
          can_replace: true,
          versions: [{ version_id: "invoice-v1", number: 1 }],
        },
        chunks: [],
      };
    else if (path === "/api/workflow-runs" && request.method() === "POST") {
      const body = request.postDataJSON();
      assert.equal(body.invoice.version_id, "invoice-v1");
      assert.equal(body.purchase_order.version_id, "order-v1");
      data = run;
    } else if (path === "/api/workflow-runs")
      data = { items: [run], next_cursor: null };
    else if (path === "/api/workflow-runs/run/timeline")
      data = {
        items: [
          {
            id: "event",
            kind: "company_context_completed",
            created_at: "2026-10-17",
          },
        ],
      };
    else if (path === "/api/workflow-runs/run") data = { ...run, revision };
    else if (path === "/api/approvals")
      data = {
        items: [
          {
            ...approval,
            expected_revision: revision,
            scope_hash: `scope-${revision}`,
          },
        ],
        next_cursor: null,
      };
    else if (path === "/api/approvals/approval/decision") {
      decisionCount++;
      if (decisionCount === 1) {
        revision++;
        status = 409;
        data = { detail: "Approval scope changed" };
      } else data = { ...run, revision: revision + 1 };
    } else if (path.startsWith("/api/artifacts/")) {
      status = 403;
      data = { detail: "Download denied" };
    } else if (path === "/api/memory" || path === "/api/actions")
      data = { items: [] };
    else {
      status = 404;
      data = { detail: `Unconfigured browser fixture: ${path}` };
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      ...(status === 204 ? {} : { body: JSON.stringify(data) }),
    });
  });
}
async function a11y(page, label) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  await writeFile(
    new URL(`axe-${label}.json`, out),
    JSON.stringify(result, null, 2),
  );
  assert.deepEqual(
    result.violations.map((item) => ({
      id: item.id,
      targets: item.nodes.map((node) => node.target),
    })),
    [],
  );
}
async function completedStateCheck() {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  await fixture(context, member, { signedIn: true });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  const completed = {
    ...run,
    status: "completed",
    revision: 9,
    outputs: [
      {
        id: `artifact:${"a".repeat(64)}`,
        kind: "report_html",
        content_hash: "b".repeat(64),
      },
    ],
    cases: [{ id: `case:run:${"c".repeat(64)}`, status: "resolved" }],
    steps: [
      "company_context",
      "finance_parse",
      "invoice_compare",
      "publish_report",
      "upsert_case",
      "archive_run",
    ].map((key) => ({
      id: key,
      logical_key: key,
      status: "completed",
      depends_on: [],
    })),
    approvals: [
      {
        ...approval,
        status: "approved",
        gate_kind: "report_write",
        scope: {
          ...approval.scope,
          preview: {
            result: {
              comparison: {
                currency: "USD",
                invoice_total: "220.00",
                order_total: "200.00",
                difference: "20.00",
                findings: [
                  {
                    item_id: "widget",
                    kind: "unit_price_mismatch",
                    invoice_row: 2,
                    order_row: 2,
                    expected: "100.00",
                    actual: "110.00",
                  },
                ],
              },
            },
            artifacts: [{ kind: "report_html" }, { kind: "discrepancy_csv" }],
            evidence_refs: [],
            case_revision: null,
          },
        },
      },
    ],
  };
  await page.route("**/api/workflow-runs/run", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(completed),
    }),
  );
  await page.goto(`${base}/#workflows/run`);
  await page.locator(".run-summary .state-completed").waitFor();
  assert.equal(
    await page
      .getByText("Exact proposed output changes")
      .evaluate((node) => node.closest("details").open),
    false,
  );
  await page.getByText("USD 220.00", { exact: true }).waitFor();
  await a11y(page, "workflow-completed");
  await page.screenshot({
    path: new URL("workflow-completed.png", out).pathname,
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth + 1,
    ),
    "Completed report hashes and case identifiers must wrap at390px",
  );
  checks.push(
    "completed workflow and approved badges have accessible contrast and compact previews",
  );
  await context.close();
}
if (process.env.RELAY_BROWSER_COMPLETED_ONLY) {
  try {
    await completedStateCheck();
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ checks, errors }, null, 2));
  } finally {
    await browser.close();
  }
} else {
  try {
    const operator = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
    });
    await fixture(operator, member);
    const page = await operator.newPage();
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`${base}/#workflows`);
    await page.getByRole("heading", { name: "Sign in to Relay" }).waitFor();
    await page.getByLabel("Username", { exact: true }).fill("operator");
    await page.getByLabel("Password", { exact: true }).fill("fixture-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByRole("button", { name: "New invoice review" }).waitFor();
    checks.push("session gate and credential sign-in");
    await page.getByRole("button", { name: "New invoice review" }).click();
    await page
      .getByRole("group", { name: "Invoice", exact: true })
      .getByRole("radio", { name: /Invoice CSV/ })
      .check();
    await page
      .getByRole("group", { name: "Purchase order", exact: true })
      .getByRole("radio", { name: /Purchase order CSV/ })
      .check();
    await page
      .getByRole("button", { name: "Start review", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Persisted workflow state" })
      .waitFor();
    await page
      .getByText(
        "Only the assigned authorized reviewer can decide this request.",
      )
      .waitFor();
    assert.equal(
      await page
        .getByRole("button", { name: "Approve permitted work" })
        .count(),
      0,
    );
    checks.push(
      "exact finance version composer and requester approval restriction",
    );
    await a11y(page, "workflow-desktop");
    await page.screenshot({
      path: new URL("workflow-desktop.png", out).pathname,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Revise inputs and plan" }).click();
    await page.getByRole("dialog").waitFor();
    await page
      .getByLabel("Output audience member IDs")
      .fill("operator, auditor");
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "Revise inputs and plan" }).focus();
    await page.keyboard.press("Enter");
    assert.equal(
      await page.getByLabel("Output audience member IDs").inputValue(),
      "operator, auditor",
    );
    checks.push("unsaved revision draft survives modal close");
    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => {
      const graph = document
        .querySelector(".workflow-graph")
        ?.getBoundingClientRect();
      if (!graph) return false;
      return [
        ...document.querySelectorAll(".workflow-graph .react-flow__node"),
      ].every((node) => {
        const box = node.getBoundingClientRect();
        return (
          box.left >= graph.left - 1 &&
          box.right <= graph.right + 1 &&
          box.top >= graph.top - 1 &&
          box.bottom <= graph.bottom + 1
        );
      });
    });
    await page.screenshot({
      path: new URL("workflow-mobile.png", out).pathname,
      fullPage: true,
    });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
      "390px page must not overflow",
    );
    await a11y(page, "workflow-mobile");
    checks.push("390px layout, modal keyboard, accessibility");
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await page.getByRole("heading", { name: "Sign in to Relay" }).waitFor();
    assert.equal(
      await page
        .getByRole("heading", { name: "Persisted workflow state" })
        .count(),
      0,
    );
    checks.push("logout removes scoped workspace");
    const auditor = await browser.newContext({
      viewport: { width: 1280, height: 900 },
    });
    await fixture(
      auditor,
      {
        id: "auditor",
        display_name: "Finance auditor",
        role: "finance_auditor",
        department_ids: ["finance"],
      },
      { signedIn: true },
    );
    const audit = await auditor.newPage();
    audit.on("pageerror", (error) => errors.push(error.message));
    await audit.goto(`${base}/#approvals`);
    await audit
      .getByLabel("Decision reason")
      .fill("Please verify the replacement invoice");
    await audit
      .getByRole("button", { name: "Request changes", exact: true })
      .click();
    await audit.getByText(/Approval scope changed/).waitFor();
    assert.equal(
      await audit.getByLabel("Decision reason").inputValue(),
      "Please verify the replacement invoice",
    );
    await audit.getByText("scope-3", { exact: true }).waitFor();
    checks.push("assigned auditor conflict refresh preserves reason");
    await a11y(audit, "approval");
    await audit.screenshot({
      path: new URL("approval.png", out).pathname,
      fullPage: true,
    });
    await completedStateCheck();
    assert.deepEqual(errors, []);
    await writeFile(
      new URL("report.json", out),
      JSON.stringify(
        { kind: "mocked-api-browser-interactions", checks, errors },
        null,
        2,
      ),
    );
    console.log(JSON.stringify({ checks, errors }, null, 2));
  } finally {
    await browser.close();
  }
}
