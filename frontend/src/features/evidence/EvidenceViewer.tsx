import { useEffect, useRef, useState } from "react";
import { api, ApiError, downloadFile, errorMessage } from "../../api";
import { Button, Modal, Status } from "../../components/ui";
import type { EvidenceRef, SourceDetail } from "./types";
import { LinkReview } from "./LinkReview";
export function citationLabel(ref: EvidenceRef) {
  const location = ref.locator.page
    ? `page ${ref.locator.page}`
    : ref.locator.row_start
      ? `rows ${ref.locator.row_start}${ref.locator.row_end && ref.locator.row_end !== ref.locator.row_start ? `–${ref.locator.row_end}` : ""}`
      : ref.locator.paragraph
        ? `paragraph ${ref.locator.paragraph}`
        : "exact excerpt";
  return `${ref.title} · ${ref.version_id} · ${location}`;
}
export function EvidenceViewer({
  sourceId,
  evidence,
  versionId,
  legacyCitation = false,
  runId,
  onClose,
  returnFocusTo,
}: {
  sourceId: string | null;
  evidence?: EvidenceRef;
  versionId?: string;
  legacyCitation?: boolean;
  runId?: string;
  onClose: () => void;
  returnFocusTo?: HTMLElement | null;
}) {
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [notice, setNotice] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    setSelected(evidence?.version_id || versionId || "");
    setNotice("");
  }, [sourceId, evidence?.version_id, versionId]);
  useEffect(() => {
    if (!sourceId) return;
    const controller = new AbortController();
    setDetail(null);
    setError("");
    void api
      .source(sourceId, selected || undefined, runId, controller.signal)
      .then(setDetail)
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      });
    return () => controller.abort();
  }, [sourceId, selected, runId, retry]);
  const version = selected || detail?.current_version_id;
  const versions =
    detail?.versions ||
    (detail?.provenance?.versions as SourceDetail["versions"]) ||
    [];
  return (
    <Modal
      open={!!sourceId}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={detail?.title || evidence?.title || "Original source"}
      description={
        evidence
          ? citationLabel(evidence)
          : "Source provenance and exact stored content."
      }
      wide
      returnFocusTo={returnFocusTo}
    >
      {error && (
        <>
          <Status error>{error}</Status>
          <Button onClick={() => setRetry((value) => value + 1)}>
            Retry source
          </Button>
        </>
      )}
      {!error && !detail && <Status>Loading original source…</Status>}
      {detail && (
        <article className="source-detail">
          {legacyCitation && (
            <p className="muted">
              Citation version not recorded. This view shows the current stored
              source; it does not establish which version the earlier
              investigation used.
            </p>
          )}
          <div className="source-detail-meta">
            <span className="badge">
              {detail.classification || detail.type}
            </span>
            <span>{detail.author}</span>
            <span>{detail.processing_status || "Available"}</span>
          </div>
          <p>
            {version
              ? `${evidence || versionId ? "Exact version" : "Current stored version"}: ${version}`
              : "Version not recorded"}
          </p>
          {versions.length > 1 && (
            <label>
              View version
              <select
                value={version || ""}
                onChange={(event) => setSelected(event.target.value)}
              >
                {versions.map((item) => (
                  <option
                    key={item.version_id || item.id}
                    value={item.version_id || item.id}
                  >
                    {item.number ? `Version ${item.number} · ` : ""}
                    {item.version_id || item.id}
                  </option>
                ))}
              </select>
            </label>
          )}
          {detail.chunks?.length ? (
            detail.chunks.map((chunk, index) => (
              <section
                key={chunk.chunk_id || chunk.id || index}
                className={`evidence-chunk ${evidence?.chunk_id === (chunk.chunk_id || chunk.id) ? "selected-evidence" : ""}`}
              >
                <small>
                  {chunk.locator?.page
                    ? `Page ${chunk.locator.page}`
                    : chunk.locator?.row_start
                      ? `Rows ${chunk.locator.row_start}–${chunk.locator.row_end || chunk.locator.row_start}`
                      : `Paragraph ${chunk.locator?.paragraph || index + 1}`}
                </small>
                <div className="source-original">
                  {chunk.text || chunk.content}
                </div>
              </section>
            ))
          ) : detail.excerpt ? (
            <div className="source-original">{detail.excerpt}</div>
          ) : (
            <p>
              Content is {detail.processing_status || "not available"}. Finance
              inspection remains limited to authorized reviewers.
            </p>
          )}
          <div className="form-actions">
            {version && detail.provenance?.can_download === true && (
              <Button
                busy={busy}
                onClick={async () => {
                  setBusy(true);
                  setNotice("");
                  try {
                    await downloadFile(
                      `/sources/${encodeURIComponent(sourceId!)}/versions/${encodeURIComponent(version)}/download`,
                      detail.title,
                    );
                  } catch (err) {
                    setNotice(errorMessage(err));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Download original
              </Button>
            )}
          </div>
          {detail.provenance?.storage_kind === "legacy_inline" && (
            <p className="muted">
              Migration snapshot · original file unavailable. Stored text is
              retained above.
            </p>
          )}
          <details className="provenance">
            <summary>Provenance</summary>
            <pre>{JSON.stringify(detail.provenance || {}, null, 2)}</pre>
          </details>
          <LinkReview
            source={detail}
            version={version || ""}
            onChanged={() => setRetry((value) => value + 1)}
          />
          {detail.provenance?.can_replace === true && (
            <form
              noValidate
              className="version-replace"
              onSubmit={async (event) => {
                event.preventDefault();
                if (!file) return;
                setBusy(true);
                setNotice("");
                const body = new FormData();
                body.append("file", file);
                body.append(
                  "expected_revision",
                  String(
                    detail.source_revision ??
                      detail.revision ??
                      detail.provenance?.source_revision ??
                      0,
                  ),
                );
                try {
                  const result = await api.request<{
                    ref: { version_id: string };
                    invalidated_run_ids: string[];
                  }>(`/sources/${encodeURIComponent(sourceId!)}/versions`, {
                    method: "POST",
                    body,
                  });
                  setNotice(
                    `New version saved. ${result.invalidated_run_ids.length} affected workflow(s) now require review.`,
                  );
                  setSelected(result.ref.version_id);
                  setFile(null);
                  if (fileInput.current) fileInput.current.value = "";
                  setRetry((value) => value + 1);
                } catch (err) {
                  setNotice(errorMessage(err));
                  if (err instanceof ApiError && err.status === 409)
                    setRetry((value) => value + 1);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <label htmlFor="replacement-file">
                Replace with a new immutable version
              </label>
              <input
                ref={fileInput}
                id="replacement-file"
                type="file"
                accept=".csv,.pdf,.txt,.md,.markdown"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
              <p>
                Dependent approvals and results become stale. Unaffected work
                stays reusable.
              </p>
              <Button type="submit" disabled={!file} busy={busy}>
                Save new version
              </Button>
            </form>
          )}
          {notice && <p role="status">{notice}</p>}
        </article>
      )}
    </Modal>
  );
}
