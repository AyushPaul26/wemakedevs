import { useEffect, useState } from "react";
import { api, errorMessage, formatDate } from "../../api";
import { Button, Status } from "../../components/ui";
import type { WorkflowEvent } from "./types";
export function WorkflowTimeline({
  runId,
  revision,
}: {
  runId: string;
  revision: number;
}) {
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void api
      .timeline(runId, undefined, controller.signal)
      .then((page) => {
        setEvents(page.items);
        setCursor(page.next_cursor);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      });
    return () => controller.abort();
  }, [runId, revision, retry]);
  return (
    <section className="workflow-timeline">
      <h2>Decision and execution timeline</h2>
      {error && (
        <>
          <Status error>{error}</Status>
          <Button onClick={() => setRetry((value) => value + 1)}>
            Retry timeline
          </Button>
        </>
      )}
      {!events.length && !error && <p>No timeline events are available yet.</p>}
      <ol>
        {events.map((event, index) => (
          <li key={event.id || index}>
            <strong>
              {event.message || event.kind || event.type || "Workflow event"}
            </strong>
            <small>
              {event.created_at ? formatDate(event.created_at) : ""}
              {event.actor_id ? ` · ${event.actor_id}` : ""}
            </small>
            <details>
              <summary>Event details</summary>
              <pre>{JSON.stringify(event, null, 2)}</pre>
            </details>
          </li>
        ))}
      </ol>
      {cursor && (
        <Button
          busy={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const page = await api.timeline(runId, cursor);
              setEvents((current) => [...current, ...page.items]);
              setCursor(page.next_cursor);
            } catch (err) {
              setError(errorMessage(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          Load more events
        </Button>
      )}
    </section>
  );
}
