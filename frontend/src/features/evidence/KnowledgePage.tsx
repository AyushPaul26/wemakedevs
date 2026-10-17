import { useEffect, useRef, useState } from "react";
import { FileText, Search } from "lucide-react";
import { api, errorMessage, formatDate } from "../../api";
import { Button, Empty, Status } from "../../components/ui";
import { AttachmentDialog } from "./AttachmentDialog";
import type { SourceSummary } from "./types";
export function KnowledgePage({
  onSource,
  onAddNote,
}: {
  onSource: (id: string) => void;
  onAddNote: () => void;
}) {
  const [query, setQuery] = useState("");
  const [committed, setCommitted] = useState("");
  const [composing, setComposing] = useState(false);
  const [items, setItems] = useState<SourceSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [upload, setUpload] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const request = useRef(0);
  useEffect(() => {
    if (composing) return;
    const timer = setTimeout(() => setCommitted(query), query ? 300 : 0);
    return () => clearTimeout(timer);
  }, [query, composing]);
  useEffect(() => {
    const id = ++request.current;
    const controller = new AbortController();
    setBusy(true);
    setError("");
    void api
      .sources(committed, undefined, controller.signal)
      .then((page) => {
        if (id === request.current) {
          setItems(page.items);
          setCursor(page.next_cursor);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      })
      .finally(() => {
        if (id === request.current && !controller.signal.aborted)
          setBusy(false);
      });
    return () => controller.abort();
  }, [committed, version]);
  return (
    <section>
      <div className="section-toolbar">
        <form
          className="search-field"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!composing) setCommitted(query);
          }}
        >
          <Search size={17} />
          <input
            ref={input}
            type="search"
            aria-label="Search knowledge"
            value={query}
            onCompositionStart={() => setComposing(true)}
            onCompositionEnd={() => setComposing(false)}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search source titles and metadata…"
          />
          {query && (
            <Button
              variant="ghost"
              aria-label="Clear knowledge search"
              onClick={() => {
                setQuery("");
                setCommitted("");
                request.current++;
                setVersion((value) => value + 1);
                input.current?.focus();
              }}
            >
              Clear
            </Button>
          )}
        </form>
        <div className="form-actions">
          <Button onClick={onAddNote}>Add note</Button>
          <Button variant="primary" onClick={() => setUpload(true)}>
            Upload files
          </Button>
        </div>
      </div>
      {busy && <Status>Loading authorized sources…</Status>}
      {error && (
        <>
          <Status error>{error}</Status>
          <Button onClick={() => setVersion((value) => value + 1)}>
            Retry sources
          </Button>
        </>
      )}
      {!busy && !error && !items.length && (
        <Empty
          title={query ? "No matching sources" : "Start with what you know"}
        >
          {query
            ? "Try another term or clear your search."
            : "Upload evidence or add a note to start a shared reference."}
        </Empty>
      )}
      <div className="source-grid">
        {items.map((item) => (
          <article className="source-card" key={item.id}>
            <div className="source-card-type">
              <span>
                <FileText size={19} />
              </span>
              <span className="badge">{item.classification || item.type}</span>
            </div>
            <h2>
              <button onClick={() => onSource(item.id)}>{item.title}</button>
            </h2>
            <p>
              {item.processing_status || "Available"} ·{" "}
              {item.current_version_id
                ? `Version ${item.current_version_id}`
                : "Version not recorded"}
            </p>
            <div>
              <span>{item.author}</span>
              <span>{formatDate(item.updated_at)}</span>
            </div>
          </article>
        ))}
      </div>
      {cursor && (
        <div className="load-more">
          <Button
            busy={busy}
            onClick={async () => {
              const id = ++request.current;
              setBusy(true);
              setError("");
              try {
                const page = await api.sources(committed, cursor);
                if (id === request.current) {
                  setItems((current) => [...current, ...page.items]);
                  setCursor(page.next_cursor);
                }
              } catch (err) {
                if (id === request.current) setError(errorMessage(err));
              } finally {
                if (id === request.current) setBusy(false);
              }
            }}
          >
            Load more sources
          </Button>
        </div>
      )}
      <AttachmentDialog
        open={upload}
        onOpenChange={setUpload}
        onUploaded={() => setVersion((value) => value + 1)}
      />
    </section>
  );
}
