import { useEffect, useRef, useState } from "react";
import { FilePlus2, Info } from "lucide-react";
import { api, errorMessage } from "../api";
import type { Source } from "../types";
import { Button, Modal, Status } from "./ui";
export function SourceNoteForm({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (source: Source) => void;
}) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [invalid, setInvalid] = useState<"title" | "content" | null>(null);
  const [busy, setBusy] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);
  const contentRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!title && !content) return;
    const protect = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [title, content]);
  return (
    <Modal
      open={open}
      onOpenChange={(value) => {
        if (!busy) onOpenChange(value);
      }}
      title="Add company knowledge"
      description="Save a source note for your team to reference."
    >
      <form
        className="note-form"
        noValidate
        onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          setError("");
          setInvalid(null);
          if (!title.trim()) {
            setInvalid("title");
            setError("Give your source a title.");
            titleRef.current?.focus();
            return;
          }
          if (!content.trim()) {
            setInvalid("content");
            setError("Add some content to this source.");
            contentRef.current?.focus();
            return;
          }
          setBusy(true);
          try {
            const source = await api.addSource(title.trim(), content.trim());
            onSaved(source);
            setTitle("");
            setContent("");
            onOpenChange(false);
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label htmlFor="source-title">Source title</label>
        <input
          id="source-title"
          ref={titleRef}
          value={title}
          maxLength={160}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="e.g. Atlas readiness meeting notes"
          aria-invalid={invalid === "title"}
          aria-describedby={
            invalid === "title" ? "source-form-error" : undefined
          }
          disabled={busy}
        />
        <label htmlFor="source-content">Content</label>
        <textarea
          className="resize-none"
          id="source-content"
          ref={contentRef}
          value={content}
          maxLength={30000}
          onChange={(event) => setContent(event.target.value)}
          placeholder="Paste the original note, decision, or context…"
          rows={9}
          aria-invalid={invalid === "content"}
          aria-describedby={
            invalid === "content" ? "source-form-error" : "note-help"
          }
          disabled={busy}
        />
        <div className="form-hint" id="note-help">
          <Info size={15} />
          <p>
            This saves the original note. Entity extraction and graph linking
            are not enabled for note uploads.
          </p>
        </div>
        {error && (
          <div id="source-form-error">
            <Status error>{error}</Status>
          </div>
        )}
        <div className="form-actions">
          <span>Your draft stays here if you close.</span>
          <Button type="submit" variant="primary" busy={busy}>
            <FilePlus2 size={16} />
            Save source
          </Button>
        </div>
      </form>
    </Modal>
  );
}
