import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, errorMessage, formatDate } from "../../api";
import { useAuth } from "../../auth/AuthProvider";
import { Button, Empty, Status } from "../../components/ui";
import type { Approval } from "./types";
import { EvidenceViewer, citationLabel } from "../evidence/EvidenceViewer";
import { useSessionDraft } from "../../components/SessionDrafts";
import { uniqueEvidenceRefs } from "./state";
import type { SourceRef, EvidenceRef } from "../evidence/types";
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const valueText = (value: unknown) =>
  typeof value === "string" || typeof value === "number"
    ? String(value)
    : "Not recorded";
export function ComparisonSummary({ value }: { value: unknown }) {
  const comparison = record(value);
  if (!Object.keys(comparison).length) return null;
  const currency =
    typeof comparison.currency === "string" ? comparison.currency : "";
  const findings = Array.isArray(comparison.findings)
    ? comparison.findings
    : undefined;
  return (
    <section className="comparison-summary" aria-label="Invoice comparison">
      <dl className="comparison-totals">
        {[
          ["Invoice total", "invoice_total"],
          ["Purchase order total", "order_total"],
          ["Difference", "difference"],
        ].map(([label, key]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              {currency} {valueText(comparison[key])}
            </dd>
          </div>
        ))}
      </dl>
      {findings && (
        <>
          <p>
            <strong>
              {findings.length
                ? `${findings.length} discrepancy finding${findings.length === 1 ? "" : "s"}`
                : "No discrepancies found."}
            </strong>
          </p>
          {findings.length > 0 && (
            <ul
              className="preview-findings"
              tabIndex={0}
              aria-label="Comparison findings"
            >
              {findings.map((entry, index) => {
                const finding = record(entry);
                return (
                  <li key={index}>
                    <strong>
                      {valueText(finding.item_id)} ·{" "}
                      {valueText(finding.kind).replaceAll("_", " ")}
                    </strong>
                    {finding.expected != null || finding.actual != null ? (
                      <p>
                        Purchase order: {valueText(finding.expected)} · Invoice:{" "}
                        {valueText(finding.actual)}
                      </p>
                    ) : (
                      <p>
                        {finding.kind === "missing_in_order"
                          ? "Item is present in the invoice and missing from the purchase order."
                          : finding.kind === "missing_in_invoice"
                            ? "Item is present in the purchase order and missing from the invoice."
                            : "Review the cited rows for this finding."}
                      </p>
                    )}
                    <small>
                      {finding.invoice_row != null
                        ? `Invoice row ${valueText(finding.invoice_row)}`
                        : ""}
                      {finding.invoice_row != null && finding.order_row != null
                        ? " · "
                        : ""}
                      {finding.order_row != null
                        ? `Purchase order row ${valueText(finding.order_row)}`
                        : ""}
                    </small>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
function OutputPreview({
  value,
  status,
  onEvidence,
}: {
  value: unknown;
  status: string;
  onEvidence: (ref: EvidenceRef) => void;
}) {
  const preview = record(value);
  const result = record(preview.result);
  const proposedCase = record(preview.case_revision);
  const artifacts = Array.isArray(preview.artifacts) ? preview.artifacts : [];
  const evidence = Array.isArray(preview.evidence_refs)
    ? uniqueEvidenceRefs(preview.evidence_refs as EvidenceRef[])
    : [];
  return (
    <section
      className="approval-preview-summary"
      aria-label="Proposed output summary"
    >
      <h4>{status === "pending" ? "Proposed changes" : "Reviewed changes"}</h4>
      {artifacts.length > 0 && (
        <p>
          <strong>
            Publish {artifacts.length} report file
            {artifacts.length === 1 ? "" : "s"}:
          </strong>{" "}
          {artifacts
            .map((item) => {
              const kind = record(item).kind;
              return kind === "report_html"
                ? "HTML comparison report"
                : kind === "discrepancy_csv"
                  ? "discrepancy CSV"
                  : valueText(kind).replaceAll("_", " ");
            })
            .join(" and ")}
          .
        </p>
      )}
      {Object.keys(proposedCase).length > 0 && (
        <p>
          <strong>
            {proposedCase.status === "resolved"
              ? "Resolve the existing internal exception case."
              : "Create or update the internal exception case with these discrepancies."}
          </strong>
          {proposedCase.owner_entity_id
            ? ` Owner: ${valueText(proposedCase.owner_entity_id)}.`
            : " Owner is unassigned."}
          {typeof proposedCase.decision === "string"
            ? ` ${proposedCase.decision}.`
            : ""}
        </p>
      )}
      <ComparisonSummary value={result.comparison || proposedCase.comparison} />
      {evidence.length > 0 && (
        <>
          <h4>Supporting evidence</h4>
          <div
            className="preview-evidence"
            tabIndex={0}
            role="region"
            aria-label="Supporting evidence"
          >
            {evidence.map((ref) => (
              <button
                className="source-link"
                key={ref.chunk_id}
                onClick={() => onEvidence(ref)}
              >
                {citationLabel(ref)}
              </button>
            ))}
          </div>
        </>
      )}
      {typeof result.narrative === "string" && (
        <details>
          <summary>
            Report explanation
            {result.narrative_mode === "live"
              ? " · Live model"
              : result.narrative_mode === "guided"
                ? " · Guided demo"
                : ""}
          </summary>
          <p>{result.narrative}</p>
        </details>
      )}
      <details>
        <summary>Exact proposed output changes</summary>
        <pre>{JSON.stringify(value, null, 2)}</pre>
      </details>
    </section>
  );
}
export function ApprovalCard({
  approval,
  onRefresh,
}: {
  approval: Approval;
  onRefresh: () => Promise<void> | void;
}) {
  const { session } = useAuth();
  const [inspect, setInspect] = useState<SourceRef>();
  const [inspectEvidence, setInspectEvidence] = useState<EvidenceRef>();
  const [reason, setReason] = useSessionDraft(
    `approval:${approval.id}:reason`,
    "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const active = useRef(false);
  const key = useRef(crypto.randomUUID());
  const expiry = approval.expires_at
    ? new Date(
        typeof approval.expires_at === "number"
          ? approval.expires_at * 1000
          : approval.expires_at,
      )
    : null;
  const assigned = approval.reviewer_id === session?.member.id;
  const isFinance = approval.gate_kind === "finance_access";
  const canDecide =
    approval.status === "pending" &&
    assigned &&
    (!isFinance || session?.member.role === "finance_auditor") &&
    approval.can_decide !== false;
  async function decide(decision: "approve" | "reject" | "request_changes") {
    if (active.current) return;
    if (decision !== "approve" && !reason.trim()) {
      setError("Enter a reason before rejecting or requesting changes.");
      return;
    }
    active.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.decide(
        approval.id,
        {
          decision,
          expected_revision:
            approval.expected_revision ?? approval.revision ?? 0,
          scope_hash: approval.scope_hash,
          ...(reason.trim() ? { reason: reason.trim() } : {}),
        },
        key.current,
      );
      setNotice(
        decision === "approve"
          ? "Approval recorded. Permitted work can resume."
          : decision === "reject"
            ? "Rejected. The protected branch remains stopped."
            : "Changes requested. The requester must revise the plan.",
      );
      await onRefresh();
      key.current = crypto.randomUUID();
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.status === 409) {
        await onRefresh();
        setError(
          `${errorMessage(err)} Review the refreshed scope before trying again. Your reason is preserved.`,
        );
        key.current = crypto.randomUUID();
      }
    } finally {
      setBusy(false);
      active.current = false;
    }
  }
  return (
    <article className="approval-card">
      <div className="section-heading">
        <h2>
          {approval.gate_kind?.replaceAll("_", " ") || "Workflow approval"}
        </h2>
        <span className={`badge state-${approval.status}`}>
          {approval.status.replaceAll("_", " ")}
        </span>
      </div>
      <dl className="scope-grid">
        <div>
          <dt>Workflow</dt>
          <dd>
            <a href={`#workflows/${encodeURIComponent(approval.run_id)}`}>
              {approval.run_id}
            </a>
          </dd>
        </div>
        <div>
          <dt>Assigned reviewer</dt>
          <dd>
            {approval.reviewer_name ||
              approval.reviewer_id ||
              "No reviewer assigned · waiting"}
          </dd>
        </div>
        <div>
          <dt>Requester</dt>
          <dd>{approval.requester_id || "Not provided"}</dd>
        </div>
        <div>
          <dt>Expires</dt>
          <dd>
            {approval.expires_at
              ? `${formatDate(expiry!.toISOString())} · ${expiry!.toLocaleTimeString()}`
              : "Not provided"}
          </dd>
        </div>
        <div>
          <dt>Scope</dt>
          <dd>{approval.scope_hash}</dd>
        </div>
        <div>
          <dt>Revision</dt>
          <dd>
            {approval.expected_revision ?? approval.revision ?? "Not provided"}
          </dd>
        </div>
      </dl>
      <h3>Exact permitted scope</h3>
      <p>
        Approval applies only to this plan, its file versions, tools, outputs,
        audience, and expiry.
      </p>
      {approval.scope && (
        <div className="approval-scope">
          <h3>Selected file versions</h3>
          {(["invoice", "purchase_order"] as const).map((key) => {
            const ref = approval.scope?.[key] as SourceRef | undefined;
            return (
              ref && (
                <div className="scope-file" key={key}>
                  <strong>
                    {key === "invoice" ? "Invoice" : "Purchase order"}
                  </strong>
                  <span>
                    {ref.source_id} · version {ref.version_id}
                  </span>
                  <Button
                    onClick={() => {
                      setInspect(ref);
                      setInspectEvidence(undefined);
                    }}
                  >
                    Inspect {key === "invoice" ? "invoice" : "purchase order"}
                  </Button>
                </div>
              )
            );
          })}
          <h3>Permitted tools</h3>
          <ul>
            {(
              (approval.scope.tools || []) as {
                tool: string;
                tool_version?: string;
              }[]
            ).map((tool, index) => (
              <li key={index}>
                {tool.tool.replaceAll("_", " ")}
                {tool.tool_version ? ` · version ${tool.tool_version}` : ""}
              </li>
            ))}
          </ul>
          <h3>Output audience</h3>
          <p>
            {(
              (approval.scope.output_audience ||
                approval.output_audience ||
                []) as string[]
            ).join(", ") || "Not provided"}
          </p>
          <h3>Planned outputs</h3>
          <p>
            Protected invoice comparison report and an internal exception case
            when a discrepancy is found. No payment or external message.
          </p>
          {approval.scope.preview != null && (
            <OutputPreview
              value={approval.scope.preview}
              status={approval.status}
              onEvidence={(ref) => {
                setInspect(ref);
                setInspectEvidence(ref);
              }}
            />
          )}
        </div>
      )}
      <details>
        <summary>Complete permission scope</summary>
        <pre>
          {JSON.stringify(
            approval.scope || {
              source_refs:
                approval.source_refs || approval.input_versions || [],
              tools: approval.tools || [],
              output_audience: approval.output_audience || [],
            },
            null,
            2,
          )}
        </pre>
      </details>
      <EvidenceViewer
        sourceId={inspect?.source_id || null}
        versionId={inspect?.version_id}
        evidence={inspectEvidence}
        runId={approval.run_id}
        onClose={() => setInspect(undefined)}
      />
      {approval.reason && <p>Recorded reason: {approval.reason}</p>}
      {canDecide ? (
        <>
          <label htmlFor={`reason-${approval.id}`}>Decision reason</label>
          <textarea
            className="resize-none"
            id={`reason-${approval.id}`}
            aria-label="Decision reason"
            value={reason}
            maxLength={2000}
            onChange={(event) => {
              setReason(event.target.value);
              key.current = crypto.randomUUID();
            }}
            rows={3}
          />
          <div className="form-actions">
            <Button
              variant="primary"
              busy={busy}
              onClick={() => decide("approve")}
            >
              Approve permitted work
            </Button>
            <Button busy={busy} onClick={() => decide("request_changes")}>
              Request changes
            </Button>
            <Button busy={busy} onClick={() => decide("reject")}>
              Reject
            </Button>
          </div>
        </>
      ) : (
        approval.status === "pending" && (
          <p>
            {approval.reviewer_id
              ? "Only the assigned authorized reviewer can decide this request."
              : "Waiting for a Finance reviewer to be assigned. Work cannot proceed without approval."}
          </p>
        )
      )}
      {error && <Status error>{error}</Status>}
      {notice && <p role="status">{notice}</p>}
    </article>
  );
}
export function ApprovalInbox({ approvalId }: { approvalId?: string }) {
  const { epoch } = useAuth();
  const [items, setItems] = useState<Approval[]>([]);
  const [cursor, setCursor] = useState<string | null>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setError("");
    try {
      let page = await api.approvals(undefined, current.signal);
      const loaded = [...page.items];
      while (
        approvalId &&
        !loaded.some((item) => item.id === approvalId) &&
        page.next_cursor &&
        !current.signal.aborted
      ) {
        page = await api.approvals(page.next_cursor, current.signal);
        loaded.push(...page.items);
      }
      if (!current.signal.aborted) {
        setItems(loaded);
        setCursor(page.next_cursor);
      }
    } catch (err) {
      if (!current.signal.aborted) setError(errorMessage(err));
    } finally {
      if (!current.signal.aborted) setBusy(false);
    }
  }, [epoch, approvalId]);
  useEffect(() => {
    void load();
    return () => controller.current?.abort();
  }, [load]);
  const visible = approvalId
    ? items.filter((item) => item.id === approvalId)
    : items;
  return (
    <section>
      <div className="section-toolbar">
        <p>
          Assigned requests and visible decisions. Finance approval always
          precedes agent inspection.
        </p>
        <Button busy={busy} onClick={load}>
          Refresh approvals
        </Button>
      </div>
      {busy && !items.length && <Status>Loading approvals…</Status>}
      {error && <Status error>{error}</Status>}
      {!busy && !visible.length && !error && (
        <Empty title="No visible approval requests">
          Requests assigned to you will appear here. A missing reviewer leaves
          the workflow waiting.
        </Empty>
      )}
      {visible.map((approval) => (
        <ApprovalCard key={approval.id} approval={approval} onRefresh={load} />
      ))}
      {cursor && (
        <Button
          busy={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const page = await api.approvals(cursor);
              setItems((current) => [...current, ...page.items]);
              setCursor(page.next_cursor);
            } catch (err) {
              setError(errorMessage(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          Load more approvals
        </Button>
      )}
    </section>
  );
}
