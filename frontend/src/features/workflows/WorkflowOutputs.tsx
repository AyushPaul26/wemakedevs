import { useState } from "react";
import { api, downloadFile, errorMessage } from "../../api";
import { Button, Modal, Status } from "../../components/ui";
import { ComparisonSummary } from "./ApprovalInbox";
import type { RunSnapshot, WorkflowCase } from "./types";
export function WorkflowOutputs({ run }: { run: RunSnapshot }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<WorkflowCase | null>(null);
  return (
    <section>
      <h2>Reports and internal cases</h2>
      {!run.outputs.length && !run.cases.length && (
        <p>Outputs appear here after permitted execution completes.</p>
      )}
      {run.outputs.map((output) => (
        <article key={output.id} className="workflow-output">
          <div>
            <strong>
              {output.title || output.kind || "Workflow artifact"}
            </strong>
            <p>
              {output.stale
                ? "Stale · input or approval changed"
                : "Stored output"}
              {output.content_hash ? ` · ${output.content_hash}` : ""}
            </p>
          </div>
          <Button
            busy={busy === output.id}
            onClick={async () => {
              setBusy(output.id);
              setError("");
              try {
                await downloadFile(
                  `/artifacts/${encodeURIComponent(output.id)}/download`,
                  `${output.id}.${output.kind?.includes("csv") ? "csv" : "html"}`,
                );
              } catch (err) {
                setError(errorMessage(err));
              } finally {
                setBusy("");
              }
            }}
          >
            Download report
          </Button>
        </article>
      ))}
      {run.cases.map((item) => (
        <article key={item.id} className="workflow-output">
          <div>
            <strong>{item.title || `Exception case ${item.id}`}</strong>
            <p>
              Internal case · {item.stale ? "Stale · " : ""}
              {item.status || "recorded"} · separate from manual Actions
            </p>
          </div>
          <Button
            busy={busy === item.id}
            onClick={async () => {
              setBusy(item.id);
              setError("");
              try {
                setSelected(
                  await api.request<WorkflowCase>(
                    `/cases/${encodeURIComponent(item.id)}`,
                  ),
                );
              } catch (err) {
                setError(errorMessage(err));
              } finally {
                setBusy("");
              }
            }}
          >
            View case
          </Button>
        </article>
      ))}
      {error && <Status error>{error}</Status>}
      <Modal
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected?.title || "Internal exception case"}
      >
        <p>{selected?.description}</p>
        {selected?.stale && (
          <p role="status">
            This case includes results made stale by an input or approval
            change.
          </p>
        )}
        {selected?.owner_entity_id && <p>Owner: {selected.owner_entity_id}</p>}
        {selected?.current_revision && (
          <>
            <h3>Current case revision</h3>
            <p>
              Status:{" "}
              {String(
                selected.current_revision.status ||
                  selected.status ||
                  "Not recorded",
              )}
            </p>
            {typeof selected.current_revision.decision === "string" && (
              <p>{selected.current_revision.decision}</p>
            )}
            <ComparisonSummary value={selected.current_revision.comparison} />
          </>
        )}
        <details>
          <summary>Technical case details</summary>
          <pre>{JSON.stringify(selected, null, 2)}</pre>
        </details>
      </Modal>
    </section>
  );
}
