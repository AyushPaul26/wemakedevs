import { useEffect, useState } from "react";
import { api, ApiError, errorMessage } from "../../api";
import { Button, Status } from "../../components/ui";
import type { SourceDetail } from "./types";
type Proposal = {
  id: string;
  source_entity_id?: string;
  target_entity_id?: string;
  relation: string;
  status: string;
};
type Links = {
  proposals: Proposal[];
  extraction_status: string;
  manual_association: boolean;
  entity_options: { id: string; name: string }[];
};
export function LinkReview({
  source,
  version,
  onChanged,
}: {
  source: SourceDetail;
  version: string;
  onChanged: () => void;
}) {
  const [data, setData] = useState<Links | null>(null);
  const [target, setTarget] = useState("");
  const [chunk, setChunk] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const base = `/sources/${encodeURIComponent(source.id)}/versions/${encodeURIComponent(version)}/links`;
  useEffect(() => {
    if (!version || source.provenance?.can_review_links !== true) return;
    const controller = new AbortController();
    void api
      .request<Links>(base, { signal: controller.signal })
      .then(setData)
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      });
    return () => controller.abort();
  }, [base, version, source.provenance?.can_review_links, revision]);
  if (source.provenance?.can_review_links !== true) return null;
  return (
    <section className="link-review">
      <h3>Company links</h3>
      {data?.extraction_status === "unavailable" && (
        <p>
          Automatic link extraction is unavailable. Associate an existing
          company entity using an exact evidence chunk.
        </p>
      )}
      {data?.proposals.map((proposal) => (
        <article key={proposal.id}>
          <p>
            {proposal.source_entity_id || source.title} → {proposal.relation} →{" "}
            {proposal.target_entity_id} · {proposal.status}
          </p>
          {proposal.status === "pending" && (
            <div className="form-actions">
              {(["accept", "reject"] as const).map((decision) => (
                <Button
                  key={decision}
                  busy={busy}
                  onClick={async () => {
                    setBusy(true);
                    setError("");
                    try {
                      await api.request(`${base}/review`, {
                        method: "POST",
                        body: {
                          expected_revision:
                            source.source_revision ??
                            source.revision ??
                            source.provenance?.source_revision ??
                            0,
                          decisions: [{ proposal_id: proposal.id, decision }],
                        },
                      });
                      setRevision((value) => value + 1);
                      onChanged();
                    } catch (err) {
                      setError(errorMessage(err));
                      if (err instanceof ApiError && err.status === 409)
                        onChanged();
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {decision === "accept" ? "Confirm link" : "Reject link"}
                </Button>
              ))}
            </div>
          )}
        </article>
      ))}
      {data?.manual_association && (
        <form
          className="workflow-form"
          noValidate
          onSubmit={async (event) => {
            event.preventDefault();
            if (!target || !chunk) {
              setError(
                "Choose a company entity and a supporting evidence chunk.",
              );
              return;
            }
            setBusy(true);
            setError("");
            try {
              await api.request(`${base}/proposals`, {
                method: "POST",
                body: {
                  target_entity_id: target,
                  relation: "DOCUMENTS",
                  evidence_chunk_ids: [chunk],
                },
              });
              setRevision((value) => value + 1);
            } catch (err) {
              setError(errorMessage(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          <label htmlFor="link-target">Company entity</label>
          <select
            id="link-target"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          >
            <option value="">Choose an existing entity</option>
            {data.entity_options.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <label htmlFor="link-evidence">Supporting evidence</label>
          <select
            id="link-evidence"
            value={chunk}
            onChange={(event) => setChunk(event.target.value)}
          >
            <option value="">Choose an exact excerpt</option>
            {source.chunks?.map((item, index) => (
              <option
                key={item.id || item.chunk_id || index}
                value={item.id || item.chunk_id}
              >{`Excerpt ${index + 1}: ${(item.text || item.content || "").slice(0, 100)}`}</option>
            ))}
          </select>
          <Button busy={busy} type="submit">
            Propose company link
          </Button>
        </form>
      )}
      {error && <Status error>{error}</Status>}
    </section>
  );
}
