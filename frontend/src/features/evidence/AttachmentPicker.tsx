import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../../api";
import { Button, Status } from "../../components/ui";
import type { SourceRef, SourceSummary } from "./types";
export const refKey = (ref: SourceRef) =>
  `${ref.source_id}\u0000${ref.version_id}`;
export function AttachmentPicker({
  label,
  value,
  onChange,
  multiple = false,
  limit = 5,
  exclude = [],
}: {
  label: string;
  value: SourceRef[];
  onChange: (refs: SourceRef[]) => void;
  multiple?: boolean;
  limit?: number;
  exclude?: SourceRef[];
}) {
  const [items, setItems] = useState<SourceSummary[]>([]);
  const requests = useRef(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const [composing, setComposing] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState<string | null>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const request = ++requests.current;
    if (composing) return;
    const controller = new AbortController();
    const timer = setTimeout(
      () => {
        setBusy(true);
        setError("");
        void api
          .sources(query, undefined, controller.signal)
          .then((page) => {
            if (controller.signal.aborted || request !== requests.current)
              return;
            setItems(page.items);
            setCursor(page.next_cursor);
          })
          .catch((err) => {
            if (!controller.signal.aborted) setError(errorMessage(err));
          })
          .finally(() => {
            if (!controller.signal.aborted) setBusy(false);
          });
      },
      query ? 300 : 0,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, retry, composing]);
  return (
    <fieldset className="attachment-picker">
      <legend>{label}</legend>
      <div className="search-field">
        <input
          ref={searchRef}
          onCompositionStart={() => setComposing(true)}
          onCompositionEnd={() => setComposing(false)}
          type="search"
          aria-label={`Search ${label.toLowerCase()}`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Find an uploaded source"
        />
        {query && (
          <Button
            variant="ghost"
            aria-label={`Clear ${label.toLowerCase()} search`}
            onClick={() => {
              setQuery("");
              setComposing(false);
              searchRef.current?.focus();
            }}
          >
            Clear
          </Button>
        )}
      </div>
      <div className="attachment-options">
        {items.map((item) => {
          const ref = {
            source_id: item.id,
            version_id: item.current_version_id || "",
          };
          const selected = value.some((entry) => refKey(entry) === refKey(ref));
          const blocked =
            !ref.version_id ||
            exclude.some((entry) => refKey(entry) === refKey(ref)) ||
            (!selected && multiple && value.length >= limit);
          return (
            <label key={item.id} className="attachment-option">
              <input
                type={multiple ? "checkbox" : "radio"}
                name={label}
                checked={selected}
                disabled={blocked}
                onChange={() =>
                  onChange(
                    multiple
                      ? selected
                        ? value.filter((entry) => refKey(entry) !== refKey(ref))
                        : [...value, ref]
                      : [ref],
                  )
                }
              />
              <span>
                <strong>{item.title}</strong>
                <small>
                  {item.classification || "general"} ·{" "}
                  {item.processing_status || "available"} · version{" "}
                  {item.current_version_id || "not recorded"}
                </small>
              </span>
            </label>
          );
        })}
      </div>
      {busy && <Status>Loading sources…</Status>}
      {!busy && !items.length && !error && (
        <p>No sources found. Upload a file in Knowledge.</p>
      )}
      {error && (
        <>
          <Status error>{error}</Status>
          <Button onClick={() => setRetry((value) => value + 1)}>
            Retry sources
          </Button>
        </>
      )}
      {cursor && (
        <Button
          busy={busy}
          onClick={async () => {
            const request = ++requests.current;
            setBusy(true);
            try {
              const page = await api.sources(query, cursor);
              if (request !== requests.current) return;
              setItems((current) => [...current, ...page.items]);
              setCursor(page.next_cursor);
            } catch (err) {
              if (request === requests.current) setError(errorMessage(err));
            } finally {
              if (request === requests.current) setBusy(false);
            }
          }}
        >
          Load more sources
        </Button>
      )}
      {value.length > 0 && (
        <div className="attachment-chips">
          {value.map((ref) => (
            <span className="badge" key={refKey(ref)}>
              {items.find((item) => item.id === ref.source_id)?.title ||
                ref.source_id}{" "}
              · {ref.version_id}
              <button
                type="button"
                aria-label={`Remove ${ref.source_id}`}
                onClick={() =>
                  onChange(value.filter((item) => refKey(item) !== refKey(ref)))
                }
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </fieldset>
  );
}
