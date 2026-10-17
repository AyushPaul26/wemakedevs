import { useState } from "react";
import { Check, CheckCheck, Circle, UserRound } from "lucide-react";
import type { Action, Source } from "../types";
import { errorMessage } from "../api";
import { Button, SourceButton, Status } from "./ui";
export function ActionCard({
  action,
  onTransition,
  onSource,
  sources,
}: {
  action: Action;
  onTransition: (id: string, action: "approve" | "complete") => Promise<void>;
  onSource: (id: string) => void;
  sources: Source[];
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function transition() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await onTransition(
        action.id,
        action.status === "proposed" ? "approve" : "complete",
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="action-card">
      <div className="action-card-title">
        <span className={`task-indicator ${action.status}`}>
          {action.status === "done" ? (
            <CheckCheck size={18} />
          ) : action.status === "approved" ? (
            <Check size={18} />
          ) : (
            <Circle size={18} />
          )}
        </span>
        <h3>{action.title}</h3>
        <span className={`badge badge-${action.status}`}>
          {action.status === "proposed"
            ? "Needs approval"
            : action.status === "approved"
              ? "Approved"
              : "Complete"}
        </span>
      </div>
      <p>{action.description}</p>
      <div className="action-meta">
        <span>
          <UserRound size={14} />
          {action.owner}
        </span>
        <span>Internal Relay task</span>
      </div>
      {action.source_ids.length > 0 && (
        <div className="source-list">
          {action.source_ids.map((id) => (
            <SourceButton
              key={id}
              id={id}
              sources={sources}
              onSource={onSource}
              compact
            />
          ))}
        </div>
      )}
      {error && <Status error>{error}</Status>}
      {action.status !== "done" && (
        <Button
          busy={busy}
          variant={action.status === "proposed" ? "primary" : "secondary"}
          onClick={transition}
        >
          {action.status === "proposed" ? (
            <>
              <Check size={15} />
              Approve task
            </>
          ) : (
            <>
              <CheckCheck size={15} />
              Mark complete
            </>
          )}
        </Button>
      )}
    </article>
  );
}
