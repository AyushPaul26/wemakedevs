import { useEffect, useRef, useState } from "react";
import { api, ApiError, errorMessage } from "../../api";
import { useAuth } from "../../auth/AuthProvider";
import { Button, Status } from "../../components/ui";
import { AttachmentPicker } from "../evidence/AttachmentPicker";
import { useSessionDraft } from "../../components/SessionDrafts";
import type { SourceRef } from "../evidence/types";
import type { RunInputs, RunSnapshot } from "./types";
export type RunDraft = {
  invoice: SourceRef[];
  order: SourceRef[];
  context: SourceRef[];
  project: string;
  automation: RunInputs["automation"];
  audience: string;
};
export function RunComposer({
  projects,
  onCreated,
  existing,
  onConflict,
  draft,
  onDraftChange,
}: {
  projects: { id: string; label: string }[];
  onCreated: (run: RunSnapshot) => void;
  existing?: RunSnapshot;
  onConflict?: () => void;
  draft?: RunDraft;
  onDraftChange?: (draft: RunDraft) => void;
}) {
  const { session } = useAuth();
  const [storedDraft, setStoredDraft] = useSessionDraft<RunDraft | undefined>(
    `run:${existing?.id || "new"}`,
    undefined,
  );
  draft = draft || storedDraft;
  const approvalScope = existing?.approvals.find(
    (approval) => approval.scope?.invoice,
  )?.scope;
  const initial =
    existing?.inputs ||
    (approvalScope?.invoice && approvalScope?.purchase_order
      ? {
          invoice: approvalScope.invoice as SourceRef,
          purchase_order: approvalScope.purchase_order as SourceRef,
          context: (approvalScope.context || []) as SourceRef[],
          automation: (approvalScope.automation ||
            "review_changes") as RunInputs["automation"],
          output_audience: (approvalScope.output_audience || []) as string[],
        }
      : undefined);
  const [invoice, setInvoice] = useState<SourceRef[]>(
    draft?.invoice || (initial ? [initial.invoice] : []),
  );
  const [order, setOrder] = useState<SourceRef[]>(
    draft?.order || (initial ? [initial.purchase_order] : []),
  );
  const [context, setContext] = useState<SourceRef[]>(
    draft?.context || initial?.context || [],
  );
  const [project, setProject] = useState(
    draft?.project || existing?.project_id || projects[0]?.id || "",
  );
  const [automation, setAutomation] = useState<RunInputs["automation"]>(
    draft?.automation || initial?.automation || "review_changes",
  );
  const [audience, setAudience] = useState(
    draft?.audience ??
      initial?.output_audience.join(", ") ??
      session?.member.id ??
      "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(false);
  const mounted = useRef(true);
  const [savedKey, setSavedKey] = useSessionDraft(
    `run-key:${existing?.id || "new"}`,
    "",
  );
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const key = useRef(crypto.randomUUID());
  useEffect(() => {
    const snapshot = { invoice, order, context, project, automation, audience };
    onDraftChange?.(snapshot);
    setStoredDraft(snapshot);
  }, [
    invoice,
    order,
    context,
    project,
    automation,
    audience,
    onDraftChange,
    setStoredDraft,
  ]);
  useEffect(() => {
    const protect = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    if (draft) window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [draft]);
  function changed() {
    key.current = crypto.randomUUID();
    setSavedKey(key.current);
  }
  return (
    <form
      noValidate
      className="workflow-form"
      onChange={changed}
      onSubmit={async (event) => {
        event.preventDefault();
        if (active.current) return;
        if (!invoice[0] || !order[0]) {
          setError(
            "Choose an invoice and a purchase order before starting a review.",
          );
          return;
        }
        if (invoice[0].source_id === order[0].source_id) {
          setError(
            "Choose different sources for the invoice and purchase order.",
          );
          return;
        }
        const output_audience = [
          ...new Set(
            audience
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean),
          ),
        ];
        if (!output_audience.length || (!existing && !project)) {
          setError("Choose a project and at least one output audience member.");
          return;
        }
        active.current = true;
        setBusy(true);
        setError("");
        const inputs: RunInputs = {
          invoice: invoice[0],
          purchase_order: order[0],
          context,
          automation,
          output_audience,
        };
        const requestKey = savedKey || key.current;
        setSavedKey(requestKey);
        try {
          const result = existing
            ? await api.reviseRun(
                existing.id,
                { ...inputs, expected_revision: existing.revision },
                requestKey,
              )
            : await api.createRun(
                { template: "invoice_review", project_id: project, ...inputs },
                requestKey,
              );
          setStoredDraft(undefined);
          setSavedKey("");
          if (mounted.current) onCreated(result);
        } catch (err) {
          setError(errorMessage(err));
          if (err instanceof ApiError && err.status === 409) onConflict?.();
        } finally {
          active.current = false;
          setBusy(false);
        }
      }}
    >
      <div className="workflow-intro">
        <h2>{existing ? "Revise the review plan" : "Review an invoice"}</h2>
        <p>
          Compare two finance CSV files, connect the result to company context,
          then publish a report and an internal exception case when needed.
          Finance inspection waits for the assigned auditor.
        </p>
      </div>
      <div className="workflow-inputs">
        <AttachmentPicker
          label="Invoice"
          value={invoice}
          onChange={(value) => {
            setInvoice(value);
            changed();
          }}
          exclude={order}
          limit={1}
        />
        <AttachmentPicker
          label="Purchase order"
          value={order}
          onChange={(value) => {
            setOrder(value);
            changed();
          }}
          exclude={invoice}
          limit={1}
        />
      </div>
      <AttachmentPicker
        label="Optional company context"
        multiple
        value={context}
        onChange={(value) => {
          setContext(value);
          changed();
        }}
        limit={3}
        exclude={[...invoice, ...order]}
      />
      {!existing && (
        <>
          <label htmlFor="run-project">Project</label>
          <select
            id="run-project"
            value={project}
            onChange={(event) => setProject(event.target.value)}
          >
            <option value="">Choose a project</option>
            {projects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </>
      )}
      <label htmlFor="run-automation">Output automation</label>
      <select
        id="run-automation"
        value={automation}
        onChange={(event) =>
          setAutomation(event.target.value as RunInputs["automation"])
        }
      >
        <option value="review_changes">
          Review proposed report and case changes
        </option>
        <option value="auto_permitted">
          Run permitted report and case changes automatically
        </option>
      </select>
      <p className="muted">
        Both choices preserve mandatory department approval. No payment or
        external message is sent.
      </p>
      <label htmlFor="run-audience">Output audience member IDs</label>
      <input
        id="run-audience"
        value={audience}
        onChange={(event) => setAudience(event.target.value)}
        placeholder="Member IDs, separated by commas"
      />
      <p className="muted">
        Only permitted members can be added. The server verifies the audience.
      </p>
      {existing && (
        <section className="revision-preview">
          <h3>Revision preview</h3>
          <p>
            Current plan {existing.current_plan_id}, generation{" "}
            {existing.generation}, revision {existing.revision}. Changed input
            versions invalidate dependent finance and report work. Unaffected
            completed company context may be reused.
          </p>
          <div className="workflow-inputs">
            <div>
              <strong>Current exact inputs</strong>
              <pre>
                {JSON.stringify(
                  initial || {
                    status:
                      "Current inputs unavailable; select all replacement inputs explicitly.",
                  },
                  null,
                  2,
                )}
              </pre>
            </div>
            <div>
              <strong>Proposed exact inputs</strong>
              <pre>
                {JSON.stringify(
                  { invoice: invoice[0], purchase_order: order[0], context },
                  null,
                  2,
                )}
              </pre>
            </div>
          </div>
        </section>
      )}
      {error && <Status error>{error}</Status>}
      <div className="form-actions">
        <Button type="submit" variant="primary" busy={busy}>
          {existing ? "Save revised plan" : "Start review"}
        </Button>
      </div>
    </form>
  );
}
