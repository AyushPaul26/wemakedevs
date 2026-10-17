import { useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type ReactFlowInstance,
} from "@xyflow/react";
import { EvidenceViewer, citationLabel } from "../evidence/EvidenceViewer";
import type { EvidenceRef } from "../evidence/types";
import type { WorkflowStep } from "./types";
const order = [
  "company_context",
  "finance_parse",
  "invoice_compare",
  "publish_report",
  "upsert_case",
  "archive_run",
];
const labels: Record<string, string> = {
  company_context: "Company context",
  finance_parse: "Read finance files",
  invoice_compare: "Compare invoice and order",
  publish_report: "Publish report",
  upsert_case: "Update exception case",
  archive_run: "Remember result",
};
const stepLabel = (step: WorkflowStep) =>
  step.label ||
  step.name ||
  labels[step.logical_key || step.key || step.id] ||
  step.logical_key ||
  step.key ||
  step.id;
export function WorkflowGraph({
  steps,
  runId,
}: {
  steps: WorkflowStep[];
  runId?: string;
}) {
  const graphRef = useRef<HTMLDivElement>(null);
  const [flow, setFlow] = useState<ReactFlowInstance | null>(null);
  useEffect(() => {
    if (!flow || !graphRef.current) return;
    let timer: ReturnType<typeof setTimeout>;
    const fit = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        void flow.fitView({ padding: 0.18, duration: 0 });
      }, 100);
    };
    const observer = new ResizeObserver(fit);
    observer.observe(graphRef.current);
    window.addEventListener("resize", fit);
    fit();
    return () => {
      clearTimeout(timer);
      observer.disconnect();
      window.removeEventListener("resize", fit);
    };
  }, [flow]);
  const [evidence, setEvidence] = useState<EvidenceRef>();
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = steps.map((step) => {
      const key = step.logical_key || step.key || step.id;
      const positionIndex = order.indexOf(key);
      const lane = key === "company_context" ? 0 : 1;
      return {
        id: step.id,
        position: { x: Math.max(0, positionIndex - 1) * 210, y: lane * 120 },
        data: {
          label: (
            <>
              <strong>{stepLabel(step)}</strong>
              <br />
              <span>
                {step.status.replaceAll("_", " ")}
                {step.reused ? " · reused" : ""}
              </span>
            </>
          ),
        },
        className: `workflow-node workflow-node-${step.status}`,
        style: { width: 190 },
      };
    });
    const edges: Edge[] = steps.flatMap((step) =>
      (step.depends_on || []).map((parent) => ({
        id: `${parent}-${step.id}`,
        source:
          steps.find(
            (item) => (item.logical_key || item.key || item.id) === parent,
          )?.id || parent,
        target: step.id,
      })),
    );
    return { nodes, edges };
  }, [steps]);
  return (
    <section>
      <h2>Persisted workflow state</h2>
      <div
        ref={graphRef}
        className="workflow-graph"
        aria-label="Workflow dependency graph"
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          onInit={setFlow}
          nodesDraggable={false}
          nodesConnectable={false}
          minZoom={0.3}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <ol className="workflow-step-list">
        {steps.map((step) => (
          <li key={step.id}>
            <div>
              <strong>{stepLabel(step)}</strong>
              <span className={`badge state-${step.status}`}>
                {step.status.replaceAll("_", " ")}
                {step.reused ? " · reused" : ""}
              </span>
            </div>
            {step.tool && <p>Tool: {step.tool}</p>}
            {step.error && <p role="alert">{step.error}</p>}
            {step.execution && (
              <details className="execution-receipt">
                <summary>Execution receipt · {step.execution.status}</summary>
                <dl className="scope-grid">
                  <div>
                    <dt>Execution ID</dt>
                    <dd>{step.execution.id}</dd>
                  </div>
                  <div>
                    <dt>Tool</dt>
                    <dd>{step.execution.tool}</dd>
                  </div>
                  <div>
                    <dt>Input hash</dt>
                    <dd>{step.execution.input_hash}</dd>
                  </div>
                  <div>
                    <dt>Approval IDs</dt>
                    <dd>
                      {(step.execution.approval_ids || []).join(", ") ||
                        "No approval required"}
                    </dd>
                  </div>
                  <div>
                    <dt>Started</dt>
                    <dd>{step.execution.started_at || "Not recorded"}</dd>
                  </div>
                  <div>
                    <dt>Completed</dt>
                    <dd>{step.execution.completed_at || "Not recorded"}</dd>
                  </div>
                </dl>
              </details>
            )}
            {step.evidence_refs?.length ? (
              <div className="source-list">
                {step.evidence_refs.map((ref) => (
                  <button
                    className="source-link"
                    key={ref.chunk_id}
                    onClick={() => setEvidence(ref)}
                  >
                    {citationLabel(ref)}
                  </button>
                ))}
              </div>
            ) : null}
            {step.result != null && (
              <details>
                <summary>Stored result</summary>
                <pre>{JSON.stringify(step.result, null, 2)}</pre>
              </details>
            )}
          </li>
        ))}
      </ol>
      <EvidenceViewer
        sourceId={evidence?.source_id || null}
        evidence={evidence}
        runId={runId}
        onClose={() => setEvidence(undefined)}
      />
    </section>
  );
}
