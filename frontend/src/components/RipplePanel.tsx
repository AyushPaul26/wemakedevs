import {
  ArrowRight,
  ArrowUpRight,
  Check,
  GitBranch,
  Waves,
} from "lucide-react";
import type { GraphNode, Ripple, Source } from "../types";
import { Button, SourceButton, Status } from "./ui";
export function RipplePanel({
  nodes,
  origin,
  mitigation,
  result,
  loading,
  error,
  sources,
  onOrigin,
  onMitigation,
  onSource,
  onRetry,
  onActions,
}: {
  nodes: GraphNode[];
  origin: string;
  mitigation: boolean;
  result: Ripple | null;
  loading: boolean;
  error: string;
  sources: Source[];
  onOrigin: (id: string) => void;
  onMitigation: (active: boolean) => void;
  onSource: (id: string) => void;
  onRetry: () => void;
  onActions: () => void;
}) {
  return (
    <section className="ripple-card" aria-labelledby="ripple-title">
      <div className="ripple-heading">
        <div className="ripple-brand">
          <span className="ripple-icon">
            <Waves size={22} />
          </span>
          <div>
            <h2 id="ripple-title">
              Ripple<span>WHAT-IF ANALYSIS</span>
            </h2>
            <p>One change. See the chain reaction.</p>
          </div>
        </div>
        <span className="badge badge-hypothetical">Hypothetical</span>
      </div>
      <div className="ripple-controls">
        <div className="scenario-select">
          <label htmlFor="scenario">Start with a disruption</label>
          <select
            id="scenario"
            value={origin}
            onChange={(event) => onOrigin(event.target.value)}
          >
            {nodes
              .filter((node) => node.kind === "service")
              .map((node) => (
                <option key={node.id} value={node.id}>
                  {node.label} outage
                </option>
              ))}
          </select>
        </div>
        <label className="mitigation-control">
          <span>
            <strong>Assume backup is ready</strong>
            <small>Compare the supported recovery path</small>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={mitigation}
            onChange={(event) => onMitigation(event.target.checked)}
          />
          <span className="switch-track" aria-hidden="true">
            <span>{mitigation && <Check size={11} />}</span>
          </span>
        </label>
      </div>
      <div className="ripple-result" aria-live="polite">
        {loading ? (
          <Status>Tracing dependencies through the company graph…</Status>
        ) : error ? (
          <>
            <Status error>{error}</Status>
            <Button onClick={onRetry}>Retry simulation</Button>
          </>
        ) : (
          result && (
            <>
              <div
                className={`ripple-impact ${result.mitigation && result.risk_after < result.risk_before ? "mitigated" : ""}`}
              >
                <div className="impact-count">
                  {result.mitigation ? (
                    <>
                      <span className="before-count">{result.risk_before}</span>
                      <ArrowRight size={21} />
                      <strong>{result.risk_after}</strong>
                    </>
                  ) : (
                    <strong>{result.risk_after}</strong>
                  )}
                  <span>
                    exposed
                    <br />
                    dependencies
                  </span>
                </div>
                <div>
                  <p>{result.summary}</p>
                  <small>
                    Dependency exposure, not a probability forecast.
                  </small>
                </div>
              </div>
              {result.paths.length > 0 && (
                <div className="impact-paths">
                  {result.paths.slice(0, 3).map((path, index) => (
                    <div key={index}>
                      <GitBranch size={13} />
                      {path.map((id, i) => (
                        <span key={`${id}-${i}`}>
                          {i > 0 && <ArrowRight size={12} />}
                          <span>
                            {nodes.find((node) => node.id === id)?.label || id}
                          </span>
                        </span>
                      ))}
                    </div>
                  ))}
                </div>
              )}
              <div className="ripple-evidence">
                <div className="source-list">
                  {result.source_ids.slice(0, 2).map((id) => (
                    <SourceButton
                      key={id}
                      id={id}
                      sources={sources}
                      onSource={onSource}
                      compact
                    />
                  ))}
                </div>
                {result.actions.length > 0 && (
                  <button className="text-link" onClick={onActions}>
                    Review {result.actions.length} follow-ups
                    <ArrowUpRight size={14} />
                  </button>
                )}
              </div>
              {result.assumptions.length > 0 && (
                <details className="scenario-assumptions">
                  <summary>Scenario assumptions</summary>
                  <ul>
                    {result.assumptions.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )
        )}
      </div>
    </section>
  );
}
