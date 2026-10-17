import { useEffect, useState } from "react";
import { api, ApiError, errorMessage, formatDate } from "../../api";
import { Button, Empty, Modal, Status } from "../../components/ui";
import { RunComposer, type RunDraft } from "./RunComposer";
import { useWorkflowRun } from "./useWorkflowRun";
import { WorkflowGraph } from "./WorkflowGraph";
import { WorkflowTimeline } from "./WorkflowTimeline";
import { WorkflowOutputs } from "./WorkflowOutputs";
import { ApprovalCard } from "./ApprovalInbox";
import type { RunSnapshot } from "./types";
export function WorkflowPage({
  runId,
  projects,
  mode,
  onAskRun,
}: {
  runId?: string;
  projects: { id: string; label: string }[];
  mode: "demo" | "live";
  onAskRun?: (id: string) => void;
}) {
  const { run, loading, error, refresh, accept } = useWorkflowRun(runId);
  const [items, setItems] = useState<RunSnapshot[]>([]);
  const [cursor, setCursor] = useState<string | null>();
  const [listBusy, setListBusy] = useState(false);
  const [listError, setListError] = useState("");
  const [version, setVersion] = useState(0);
  const [composeDraft, setComposeDraft] = useState<RunDraft>();
  const [reviseDraft, setReviseDraft] = useState<RunDraft>();
  const [compose, setCompose] = useState(false);
  const [revise, setRevise] = useState(false);
  const [control, setControl] = useState("");
  const [controlError, setControlError] = useState("");
  useEffect(() => {
    setControlError("");
    setRevise(false);
    setReviseDraft(undefined);
  }, [runId]);
  useEffect(() => {
    if (runId) return;
    const controller = new AbortController();
    setListBusy(true);
    setListError("");
    void api
      .runs(undefined, controller.signal)
      .then((page) => {
        setItems(page.items);
        setCursor(page.next_cursor);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setListError(errorMessage(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setListBusy(false);
      });
    return () => controller.abort();
  }, [runId, version]);
  const created = (result: RunSnapshot) => {
    setCompose(false);
    setComposeDraft(undefined);
    setReviseDraft(undefined);
    setRevise(false);
    accept(result);
    window.location.hash = `workflows/${encodeURIComponent(result.id)}`;
  };
  return (
    <section className="workflow-page">
      <div className="section-toolbar">
        <p>
          <span className="badge">
            {mode === "demo" ? "Guided demo narration" : "Live model narration"}
          </span>{" "}
          Workflow states, approvals, and receipts come from stored execution.
        </p>
        <div className="form-actions">
          {runId && (
            <Button
              onClick={() => {
                window.location.hash = "workflows";
              }}
            >
              All workflows
            </Button>
          )}
          <Button variant="primary" onClick={() => setCompose(true)}>
            New invoice review
          </Button>
        </div>
      </div>
      {runId ? (
        <>
          {loading && !run && <Status>Loading workflow…</Status>}
          {error && (
            <>
              <Status error>{error}</Status>
              <Button onClick={refresh}>Retry workflow</Button>
            </>
          )}
          {run && (
            <>
              <div className="run-summary">
                <h2>
                  Invoice review{" "}
                  <span className={`badge state-${run.status}`}>
                    {run.status.replaceAll("_", " ")}
                  </span>
                </h2>
                <p>
                  {run.id} · generation {run.generation} · revision{" "}
                  {run.revision}
                </p>
                <p>Plan {run.current_plan_id}</p>
                <div className="form-actions">
                  <Button onClick={() => onAskRun?.(run.id)}>
                    Ask about this run
                  </Button>
                  {(["cancel", "retry"] as const)
                    .filter((name) => run.allowed_controls.includes(name))
                    .map((name) => (
                      <Button
                        key={name}
                        busy={control === name}
                        disabled={!!control}
                        onClick={async () => {
                          setControl(name);
                          setControlError("");
                          try {
                            accept(
                              await api.runControl(run.id, name, run.revision),
                            );
                          } catch (err) {
                            setControlError(errorMessage(err));
                            if (err instanceof ApiError && err.status === 409)
                              refresh();
                          } finally {
                            setControl("");
                          }
                        }}
                      >
                        {name === "cancel"
                          ? "Cancel workflow"
                          : "Retry failed work"}
                      </Button>
                    ))}
                  {run.allowed_controls.includes("revise") && (
                    <Button onClick={() => setRevise(true)}>
                      Revise inputs and plan
                    </Button>
                  )}
                </div>
                {controlError && <Status error>{controlError}</Status>}
                {run.status === "stale" && (
                  <p role="status">
                    A selected version or approval changed. Dependent work is
                    stale; revise inputs and obtain new approval. Unaffected
                    completed work can be reused.
                  </p>
                )}
              </div>
              <WorkflowGraph steps={run.steps} runId={run.id} />
              {run.approvals.length > 0 && (
                <section>
                  <h2>Plan approvals</h2>
                  {run.approvals.map((approval) => (
                    <ApprovalCard
                      key={approval.id}
                      approval={approval}
                      onRefresh={async () => {
                        accept(await api.run(run.id));
                      }}
                    />
                  ))}
                </section>
              )}
              <WorkflowOutputs run={run} />
              <WorkflowTimeline runId={run.id} revision={run.revision} />
              <Modal
                open={revise}
                onOpenChange={setRevise}
                title="Revise workflow inputs"
                wide
              >
                <RunComposer
                  projects={projects}
                  existing={run}
                  draft={reviseDraft}
                  onDraftChange={setReviseDraft}
                  onCreated={created}
                  onConflict={refresh}
                />
              </Modal>
            </>
          )}
        </>
      ) : (
        <>
          {listBusy && <Status>Loading workflows…</Status>}
          {listError && (
            <>
              <Status error>{listError}</Status>
              <Button onClick={() => setVersion((value) => value + 1)}>
                Retry workflows
              </Button>
            </>
          )}
          {!listBusy && !items.length && !listError && (
            <Empty title="Start a review with exact evidence">
              Upload an invoice and purchase order in Knowledge, then create an
              invoice review.
            </Empty>
          )}
          <div className="workflow-list">
            {items.map((item) => (
              <article key={item.id} className="workflow-output">
                <div>
                  <h2>
                    <a href={`#workflows/${encodeURIComponent(item.id)}`}>
                      Invoice review · {item.id}
                    </a>
                  </h2>
                  <p>
                    {formatDate(item.updated_at)} · generation {item.generation}{" "}
                    · revision {item.revision}
                  </p>
                </div>
                <span className={`badge state-${item.status}`}>
                  {item.status.replaceAll("_", " ")}
                </span>
              </article>
            ))}
          </div>
          {cursor && (
            <Button
              busy={listBusy}
              onClick={async () => {
                setListBusy(true);
                try {
                  const page = await api.runs(cursor);
                  setItems((current) => [...current, ...page.items]);
                  setCursor(page.next_cursor);
                } catch (err) {
                  setListError(errorMessage(err));
                } finally {
                  setListBusy(false);
                }
              }}
            >
              Load more workflows
            </Button>
          )}
        </>
      )}
      <Modal
        open={compose}
        onOpenChange={setCompose}
        title="New invoice review"
        wide
      >
        <RunComposer
          projects={projects}
          onCreated={created}
          draft={composeDraft}
          onDraftChange={setComposeDraft}
        />
      </Modal>
    </section>
  );
}
