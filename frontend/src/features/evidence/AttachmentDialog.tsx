import { useRef, useState } from "react";
import { api, errorMessage } from "../../api";
import { Button, Modal, Status } from "../../components/ui";
import { useSessionDraft } from "../../components/SessionDrafts";
import type { SourceRef } from "./types";
export function AttachmentDialog({
  open,
  onOpenChange,
  onUploaded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUploaded: (refs: SourceRef[]) => void;
}) {
  const [files, setFiles] = useSessionDraft<File[]>("upload:files", []);
  const [classification, setClassification] = useSessionDraft(
    "upload:classification",
    "general",
  );
  const [title, setTitle] = useSessionDraft("upload:title", "");
  const [savedKey, setSavedKey] = useSessionDraft("upload:key", "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState<
    { filename?: string; status?: string; error?: string }[]
  >([]);
  const key = useRef(crypto.randomUUID());
  const active = useRef(false);
  return (
    <Modal
      open={open}
      onOpenChange={busy ? () => {} : onOpenChange}
      title="Upload evidence"
      description="PDF, TXT, Markdown, or invoice CSV. Up to five files, 10 MiB each."
    >
      <form
        className="workflow-form"
        noValidate
        onSubmit={async (event) => {
          event.preventDefault();
          if (active.current) return;
          if (
            !files.length ||
            files.length > 5 ||
            files.some(
              (file) =>
                file.size > 10 * 1024 * 1024 ||
                !/\.(pdf|txt|md|markdown|csv)$/i.test(file.name),
            )
          ) {
            setError(
              "Choose one to five PDF, TXT, Markdown, or CSV files, up to 10 MiB each.",
            );
            return;
          }
          active.current = true;
          setBusy(true);
          setError("");
          try {
            const body = new FormData();
            files.forEach((file) => body.append("files", file));
            body.append("classification", classification);
            body.append("department_id", classification);
            if (title.trim()) body.append("title", title.trim());
            const requestKey = savedKey || key.current;
            setSavedKey(requestKey);
            const result = await api.upload(body, requestKey);
            const refs: SourceRef[] = [];
            setResults(
              result.items.map((item) => {
                const ref =
                  item.ref ||
                  item.source_ref ||
                  (item.source_id && item.version_id
                    ? { source_id: item.source_id, version_id: item.version_id }
                    : undefined);
                if (ref) refs.push(ref);
                return {
                  filename: item.filename,
                  status: item.processing_status || item.status,
                  error: item.error,
                };
              }),
            );
            if (refs.length) onUploaded(refs);
            if (result.items.every((item) => !item.error)) {
              setFiles([]);
              key.current = crypto.randomUUID();
              setSavedKey(key.current);
            } else
              setError(
                "Some files could not be stored. Review each result before uploading again.",
              );
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
            active.current = false;
          }
        }}
      >
        <label htmlFor="attachment-files">Files</label>
        <input
          id="attachment-files"
          type="file"
          multiple
          accept=".pdf,.txt,.md,.markdown,.csv"
          disabled={busy}
          onChange={(event) => {
            setFiles(Array.from(event.target.files || []));
            setResults([]);
            key.current = crypto.randomUUID();
            setSavedKey(key.current);
          }}
        />
        <label htmlFor="attachment-title">Title (optional)</label>
        <input
          id="attachment-title"
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
            key.current = crypto.randomUUID();
            setSavedKey(key.current);
          }}
          maxLength={300}
        />
        <label htmlFor="attachment-classification">
          Classification and department
        </label>
        <select
          id="attachment-classification"
          value={classification}
          onChange={(event) => {
            setClassification(event.target.value);
            key.current = crypto.randomUUID();
            setSavedKey(key.current);
          }}
        >
          <option value="general">General · company context</option>
          <option value="finance">
            Finance · approval required before agent inspection
          </option>
        </select>
        <p className="muted">
          Finance files remain protected. Uploading a file does not authorize
          agent inspection or run a workflow.
        </p>
        {files.length > 0 && (
          <ul>
            {files.map((file) => (
              <li key={file.name}>
                {file.name} · {(file.size / 1024).toFixed(0)} KiB
              </li>
            ))}
          </ul>
        )}
        {results.map((result, index) => (
          <p role="status" key={index}>
            {result.filename || `File ${index + 1}`}:{" "}
            {result.error || result.status || "Stored"}
          </p>
        ))}
        {error && <Status error>{error}</Status>}
        <div className="form-actions">
          <Button onClick={() => onOpenChange(false)} disabled={busy}>
            Close
          </Button>
          <Button
            variant="primary"
            type="submit"
            busy={busy}
            disabled={!files.length}
          >
            Upload files
          </Button>
        </div>
      </form>
    </Modal>
  );
}
