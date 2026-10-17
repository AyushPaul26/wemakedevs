import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginPage } from "../auth/LoginPage";
import { RunComposer } from "./workflows/RunComposer";
import { ApprovalInbox } from "./workflows/ApprovalInbox";
import { AuthProvider } from "../auth/AuthProvider";
async function fillField(
  user: ReturnType<typeof userEvent.setup>,
  field: HTMLElement,
  value: string,
) {
  await user.click(field);
  await user.paste(value);
}
// Real input interactions share CPU with browser/backend checks during integration.
vi.setConfig({ testTimeout: 15000 });
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("workflow interactions", () => {
  it("retains username and explains failed login", async () => {
    const login = vi.fn().mockRejectedValue(new Error("Invalid credentials"));
    render(<LoginPage onLogin={login} />);
    const user = userEvent.setup();
    await fillField(user, screen.getByLabelText("Username"), "operator");
    await fillField(user, screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Invalid credentials")).toBeVisible();
    expect(screen.getByLabelText("Username")).toHaveValue("operator");
  });
  it("requires separate invoice and order before sending work", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }))),
    );
    render(
      <RunComposer
        projects={[{ id: "p", label: "Atlas" }]}
        onCreated={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    expect(
      await screen.findByText(/Choose an invoice and a purchase order/),
    ).toBeVisible();
  });
  it("refreshes a stale approval while preserving decision reason", async () => {
    let inbox = 0;
    const approval = {
      id: "a",
      run_id: "r",
      status: "pending",
      scope_hash: "scope",
      revision: 1,
      reviewer_id: "m",
      gate_kind: "finance_access",
      can_decide: true,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        if (input.includes("/auth/session"))
          return new Response(
            JSON.stringify({
              member: {
                id: "m",
                display_name: "Auditor",
                role: "finance_auditor",
                department_ids: ["finance"],
              },
              csrf_token: "c",
              expires_at: "2099-01-01",
            }),
          );
        if (input.includes("/decision"))
          return new Response(JSON.stringify({ detail: "Scope changed" }), {
            status: 409,
          });
        inbox++;
        return new Response(
          JSON.stringify({
            items: [
              { ...approval, revision: inbox, scope_hash: `scope-${inbox}` },
            ],
          }),
        );
      }),
    );
    render(
      <AuthProvider>
        <ApprovalInbox />
      </AuthProvider>,
    );
    const user = userEvent.setup();
    await fillField(
      user,
      await screen.findByLabelText("Decision reason"),
      "Please correct the invoice",
    );
    await user.click(screen.getByRole("button", { name: "Request changes" }));
    expect(await screen.findByText(/Scope changed/)).toBeVisible();
    expect(screen.getByLabelText("Decision reason")).toHaveValue(
      "Please correct the invoice",
    );
    await waitFor(() => expect(inbox).toBeGreaterThan(1));
  });
});

describe("authorized source search", () => {
  it("does not render a superseded metadata search response", async () => {
    const { KnowledgePage } = await import("./evidence/KnowledgePage");
    let finishOld!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        if (input.includes("query=old"))
          return new Promise<Response>((resolve) => {
            finishOld = resolve;
          });
        return new Response(
          JSON.stringify({
            items: [
              {
                id: "new",
                title: input.includes("query=new")
                  ? "Current source"
                  : "Initial source",
                type: "document",
                author: "Member",
                updated_at: "2026-10-17",
                current_version_id: "v2",
                processing_status: "waiting_approval",
              },
            ],
          }),
        );
      }),
    );
    render(<KnowledgePage onSource={() => {}} onAddNote={() => {}} />);
    const user = userEvent.setup();
    const input = screen.getByLabelText("Search knowledge");
    await fillField(user, input, "old");
    await waitFor(() => expect(finishOld).toBeTypeOf("function"));
    await user.clear(input);
    await fillField(user, input, "new");
    expect(
      await screen.findByText("Current source", {}, { timeout: 5000 }),
    ).toBeVisible();
    finishOld(
      new Response(
        JSON.stringify({ items: [{ id: "old", title: "Old source" }] }),
      ),
    );
    await waitFor(() =>
      expect(screen.queryByText("Old source")).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/waiting_approval/)).toBeVisible();
  });
});

describe("explicit finance composition", () => {
  it("submits exact file versions once while a start request is pending", async () => {
    const calls: { url: string; body?: string }[] = [];
    let finish!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, options: RequestInit) => {
        if (input === "/api/workflow-runs") {
          calls.push({ url: input, body: options.body as string });
          return new Promise<Response>((resolve) => {
            finish = resolve;
          });
        }
        return new Response(
          JSON.stringify({
            items: [
              {
                id: "invoice",
                title: "Invoice CSV",
                current_version_id: "invoice-v1",
                classification: "finance",
                processing_status: "waiting_approval",
              },
              {
                id: "order",
                title: "Order CSV",
                current_version_id: "order-v1",
                classification: "finance",
                processing_status: "waiting_approval",
              },
            ],
          }),
        );
      }),
    );
    const created = vi.fn();
    render(
      <RunComposer
        projects={[{ id: "p", label: "Atlas" }]}
        onCreated={created}
      />,
    );
    const user = userEvent.setup();
    const { within, fireEvent } = await import("@testing-library/react");
    await user.click(
      await within(screen.getByRole("group", { name: "Invoice" })).findByRole(
        "radio",
        { name: /Invoice CSV/ },
      ),
    );
    await user.click(
      within(screen.getByRole("group", { name: "Purchase order" })).getByRole(
        "radio",
        { name: /Order CSV/ },
      ),
    );
    await fillField(
      user,
      screen.getByLabelText("Output audience member IDs"),
      "operator",
    );
    const button = screen.getByRole("button", { name: "Start review" });
    fireEvent.submit(button.closest("form")!);
    fireEvent.submit(button.closest("form")!);
    expect(calls).toHaveLength(1);
    expect(JSON.parse(calls[0].body!)).toMatchObject({
      invoice: { source_id: "invoice", version_id: "invoice-v1" },
      purchase_order: { source_id: "order", version_id: "order-v1" },
      template: "invoice_review",
      project_id: "p",
    });
    expect(created).not.toHaveBeenCalled();
    finish(new Response(JSON.stringify({ id: "r" })));
    await waitFor(() => expect(created).toHaveBeenCalledOnce());
  });
});

describe("execution truthfulness", () => {
  it("does not call an ordinary stored result an execution receipt", async () => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    const { WorkflowGraph } = await import("./workflows/WorkflowGraph");
    render(
      <WorkflowGraph
        steps={[
          {
            id: "s",
            logical_key: "company_context",
            status: "completed",
            result: { summary: "Context found" },
          },
        ]}
      />,
    );
    expect(
      screen.queryByText("Stored result and receipt"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Stored result")).toBeVisible();
  });
});

describe("replacement selection", () => {
  it("allows a single selected attachment to be replaced directly", async () => {
    const { AttachmentPicker } = await import("./evidence/AttachmentPicker");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            items: [
              { id: "a", title: "First file", current_version_id: "v1" },
              { id: "b", title: "Replacement file", current_version_id: "v2" },
            ],
          }),
        ),
      ),
    );
    render(
      <AttachmentPicker
        label="Invoice"
        value={[{ source_id: "a", version_id: "v1" }]}
        onChange={() => {}}
        limit={1}
      />,
    );
    expect(
      await screen.findByRole("radio", { name: /Replacement file/ }),
    ).not.toBeDisabled();
  });
});

describe("approval preview presentation", () => {
  it("keeps meaningful proposed changes visible while technical payload stays closed", async () => {
    const { ApprovalCard } = await import("./workflows/ApprovalInbox");
    render(
      <ApprovalCard
        approval={{
          id: "summary",
          run_id: "run",
          gate_kind: "report_write",
          status: "pending",
          scope_hash: "scope",
          scope: {
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
        }}
        onRefresh={() => {}}
      />,
    );
    expect(
      screen.getByText("Exact proposed output changes").closest("details"),
    ).not.toHaveAttribute("open");
    expect(screen.getByText("Invoice total")).toBeVisible();
    expect(screen.getByText("USD 220.00")).toBeVisible();
    expect(screen.getByText("USD 20.00")).toBeVisible();
    expect(screen.getByText(/unit price mismatch/)).toBeVisible();
  });
});
