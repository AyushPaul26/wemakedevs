import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  FileText,
  GitBranch,
  LayoutDashboard,
  ListTodo,
  Network,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Waves,
  X,
} from "lucide-react";
import type {
  Action,
  Bootstrap,
  GraphNode,
  Investigation,
  Ripple,
} from "./types";
import { api, errorMessage, formatDate } from "./api";
import { mergeActions, mergeMemories } from "./state";
import { ActionCard } from "./components/ActionCard";
import { Assistant } from "./components/Assistant";
import { CompanyGraph } from "./components/CompanyGraph";
import { RipplePanel } from "./components/RipplePanel";
import { SourceNoteForm } from "./components/SourceNoteForm";
import {
  Button,
  Empty,
  Modal,
  SourceButton,
  Status,
  dialogReturnTarget,
} from "./components/ui";
import { readRoute, type View } from "./routes";
import { useAuth } from "./auth/AuthProvider";
import { LoginPage } from "./auth/LoginPage";
import { KnowledgePage } from "./features/evidence/KnowledgePage";
import { EvidenceViewer } from "./features/evidence/EvidenceViewer";
import { WorkflowPage } from "./features/workflows/WorkflowPage";
import { SessionDraftProvider } from "./components/SessionDrafts";
import { ApprovalInbox } from "./features/workflows/ApprovalInbox";
const navigation = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "knowledge", label: "Knowledge", icon: BookOpen },
  { id: "memory", label: "Memory", icon: Clock3 },
  { id: "actions", label: "Actions", icon: ListTodo },
  { id: "workflows", label: "Workflows", icon: GitBranch },
  { id: "approvals", label: "Approvals", icon: Check },
] as const;
const getView = (): View => readRoute().view;
function App() {
  const { session, loading, error, login, refresh, epoch } = useAuth();
  if (loading)
    return (
      <main className="login-page">
        <Status>Checking your session…</Status>
      </main>
    );
  if (!session)
    return (
      <>
        {error && (
          <div className="session-error">
            <Status error>{error}</Status>
            <Button onClick={refresh}>Retry connection</Button>
          </div>
        )}
        <LoginPage onLogin={login} />
      </>
    );
  return (
    <SessionDraftProvider key={`${session.member.id}-${epoch}`}>
      <Workspace />
    </SessionDraftProvider>
  );
}
function Workspace() {
  const { session, logout } = useAuth();
  const [logoutError, setLogoutError] = useState("");
  const [assistantRunId, setAssistantRunId] = useState<string>();
  const [routeId, setRouteId] = useState(readRoute().id);
  const [data, setData] = useState<Bootstrap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>(getView);
  const [origin, setOrigin] = useState("");
  const [mitigation, setMitigation] = useState(false);
  const [ripple, setRipple] = useState<Ripple | null>(null);
  const [rippleLoading, setRippleLoading] = useState(false);
  const [rippleError, setRippleError] = useState("");
  const [rippleVersion, setRippleVersion] = useState(0);
  const [memories, setMemories] = useState<Investigation[]>([]);
  const [actions, setActions] = useState<Action[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedMemory, setSelectedMemory] = useState<Investigation | null>(
    null,
  );
  const [legacySource, setLegacySource] = useState(true);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [actionFilter, setActionFilter] = useState<"all" | Action["status"]>(
    "all",
  );
  const sourceOpener = useRef<HTMLElement | null>(null);
  const listRequest = useRef(0);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await api.bootstrap();
      setData(result);
      setMemories((current) => mergeMemories(current, result.recent_memory));
      setActions((current) => mergeActions(current, result.actions));
      setOrigin(
        result.nodes.find((node) => node.id === "payment-gateway")?.id ||
          result.nodes.find((node) => node.kind === "service")?.id ||
          "",
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const change = () => {
      setView(getView());
      setRouteId(readRoute().id);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    document.title = `${navigation.find((item) => item.id === view)?.label} · Relay`;
  }, [view]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (!origin) return;
    let current = true;
    setRippleLoading(true);
    setRippleError("");
    setRipple(null);
    api
      .ripple(origin, mitigation)
      .then((result) => {
        if (!current) return;
        setRipple(result);
        setActions((items) => mergeActions(items, result.actions));
      })
      .catch((err) => {
        if (current) setRippleError(errorMessage(err));
      })
      .finally(() => {
        if (current) setRippleLoading(false);
      });
    return () => {
      current = false;
    };
  }, [origin, mitigation, rippleVersion]);
  const refreshList = useCallback(async (currentView: View) => {
    if (currentView !== "memory" && currentView !== "actions") return;
    const request = ++listRequest.current;
    setListLoading(true);
    setListError("");
    try {
      if (currentView === "memory") {
        const result = await api.memory();
        if (request === listRequest.current)
          setMemories((current) => mergeMemories(current, result.items));
      } else {
        const result = await api.actions();
        if (request === listRequest.current)
          setActions((current) => mergeActions(current, result.items));
      }
    } catch (err) {
      if (request === listRequest.current) setListError(errorMessage(err));
    } finally {
      if (request === listRequest.current) setListLoading(false);
    }
  }, []);
  useEffect(() => {
    if (data) void refreshList(view);
  }, [view, !!data, refreshList]);
  function goTo(next: View) {
    window.location.hash = next;
    setView(next);
  }
  function openSource(id: string, legacy = true) {
    setLegacySource(legacy);
    sourceOpener.current = dialogReturnTarget(
      document.activeElement as HTMLElement,
    );
    setSelectedNode(null);
    setSelectedMemory(null);
    setSourceId(id);
  }
  function investigated(result: Investigation) {
    setMemories((items) => mergeMemories(items, [result]));
    setActions((items) => mergeActions(items, result.actions));
  }
  async function transition(id: string, action: "approve" | "complete") {
    const updated = await api.transition(id, action);
    setActions((items) => mergeActions(items, [updated]));
    setNotice(
      action === "approve"
        ? "Task approved. It is ready for your team."
        : "Task marked complete.",
    );
  }
  const sources = data?.sources || [];
  const filteredActions = actions.filter(
    (item) => actionFilter === "all" || item.status === actionFilter,
  );
  const proposedCount = actions.filter(
    (item) => item.status === "proposed",
  ).length;
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        Skip to main content
      </a>
      <aside className="sidebar">
        <a className="brand" href="#overview" aria-label="Relay overview">
          <span className="brand-mark">
            <GitBranch size={24} />
          </span>
          <span>
            relay<span className="brand-period">.</span>
          </span>
        </a>
        <div className="mobile-session">
          <span>{session?.member.display_name}</span>
          <Button variant="ghost" onClick={logout}>
            Sign out
          </Button>
        </div>
        <div className="workspace-card">
          <span className="workspace-avatar">M</span>
          <div>
            <strong>{data?.workspace.name || "Meridian"}</strong>
            <span>Company workspace</span>
          </div>
          <span className="workspace-indicator" />
        </div>
        <span className="sidebar-label">WORKSPACE</span>
        <nav aria-label="Main navigation">
          {navigation.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              aria-label={item.label}
              className={view === item.id ? "active" : ""}
              aria-current={view === item.id ? "page" : undefined}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
              {item.id === "actions" && proposedCount > 0 && (
                <span className="nav-count">{proposedCount}</span>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-launch">
          <span className="sidebar-label">IN FOCUS</span>
          <button
            onClick={() => {
              goTo("overview");
              if (data)
                setSelectedNode(
                  data.nodes.find((node) => node.kind === "project") || null,
                );
            }}
          >
            <span className="launch-dot" />
            <span>{data?.workspace.project || "Atlas launch"}</span>
            <ArrowUpRight size={14} />
          </button>
        </div>
        <div className="sidebar-bottom">
          <div className="workspace-note">
            <Network size={19} />
            <strong>Context is a superpower.</strong>
            <p>
              Knowledge, people, and decisions.
              <br />
              Better together.
            </p>
          </div>
          <div className="connection-status">
            <span className={`connection-dot ${data ? "connected" : ""}`} />
            <span>
              {data
                ? "FalkorDB connected"
                : loading
                  ? "Connecting to graph…"
                  : "Graph unavailable"}
            </span>
          </div>
          <div className="sample-badge">
            <Database size={12} />
            Fictional sample company
          </div>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>
              {navigation.find((item) => item.id === view)?.label}
            </strong>
          </div>
          <div className="topbar-actions">
            <span className="demo-chip">
              <Sparkles size={12} />
              {data?.capabilities.mode === "live"
                ? "Live model"
                : data
                  ? "Guided demo"
                  : "Connecting"}
            </span>
            <Button
              variant="ghost"
              className="topbar-search"
              onClick={() => {
                goTo("knowledge");
                setTimeout(
                  () =>
                    document
                      .querySelector<HTMLInputElement>(
                        '[aria-label="Search knowledge"]',
                      )
                      ?.focus(),
                  0,
                );
              }}
            >
              <Search size={17} />
              <span>Find knowledge</span>
            </Button>
            <span className="member-name">{session?.member.display_name}</span>
            <Button
              variant="ghost"
              onClick={async () => {
                setLogoutError("");
                try {
                  await logout();
                } catch (err) {
                  setLogoutError(errorMessage(err));
                }
              }}
            >
              Sign out
            </Button>
          </div>
        </header>
        <div className="content-layout">
          <main id="main-content" tabIndex={-1} className="main-content">
            <div className="page-heading">
              <div>
                <span className="eyebrow">
                  {view === "overview"
                    ? "MERIDIAN WORKSPACE · SAMPLE DATA"
                    : "SAMPLE COMPANY CONTEXT"}
                </span>
                <h1>
                  {view === "overview"
                    ? "Your company, connected."
                    : view === "knowledge"
                      ? "Knowledge with a source."
                      : view === "memory"
                        ? "A little wiser, every time."
                        : view === "workflows"
                          ? "Work, with a clear path."
                          : view === "approvals"
                            ? "Your approval, in context."
                            : "From insight to action."}
                </h1>
                <p>
                  {view === "overview"
                    ? "See the relationships. Understand the impact. Move forward with context."
                    : view === "knowledge"
                      ? "The original context behind every answer and connection."
                      : view === "memory"
                        ? "Past investigations, remembered. Evidence you can return to."
                        : view === "workflows"
                          ? "Follow evidence, approvals, and recorded results."
                          : view === "approvals"
                            ? "Review the exact scope before permitted work resumes."
                            : "Review internal manual tasks and record team completion."}
                </p>
              </div>
              <Button
                variant="primary"
                onClick={() => setNoteOpen(true)}
                disabled={!data}
              >
                <Plus size={16} />
                <span>Add knowledge</span>
              </Button>
            </div>
            {logoutError && <Status error>{logoutError}</Status>}
            {loading && (
              <div className="page-state">
                <Status>Connecting to the Meridian company graph…</Status>
              </div>
            )}
            {error && (
              <div className="page-state">
                <Status error>{error}</Status>
                <Button onClick={load}>
                  <RefreshCw size={15} />
                  Reconnect
                </Button>
              </div>
            )}
            {data && !loading && (
              <>
                {view === "overview" && (
                  <>
                    <div className="overview-stats">
                      <div>
                        <span className="stat-icon">
                          <Network size={18} />
                        </span>
                        <strong>{data.stats.entities}</strong>
                        <span>connected entities</span>
                      </div>
                      <div>
                        <span className="stat-icon">
                          <GitBranch size={18} />
                        </span>
                        <strong>{data.stats.relationships}</strong>
                        <span>relationships</span>
                      </div>
                      <div>
                        <span className="stat-icon">
                          <BookOpen size={18} />
                        </span>
                        <strong>{sources.length}</strong>
                        <span>source documents</span>
                      </div>
                    </div>
                    <CompanyGraph
                      nodes={data.nodes}
                      edges={data.edges}
                      ripple={ripple}
                      onNode={setSelectedNode}
                    />
                    <RipplePanel
                      nodes={data.nodes}
                      origin={origin}
                      mitigation={mitigation}
                      result={ripple}
                      loading={rippleLoading}
                      error={rippleError}
                      sources={sources}
                      onOrigin={setOrigin}
                      onMitigation={setMitigation}
                      onSource={openSource}
                      onRetry={() => setRippleVersion((version) => version + 1)}
                      onActions={() => goTo("actions")}
                    />
                    <section className="recent-section">
                      <div className="section-heading">
                        <div>
                          <Clock3 size={17} />
                          <h2>Recently remembered</h2>
                        </div>
                        <button
                          className="text-link"
                          onClick={() => goTo("memory")}
                        >
                          View memory
                          <ArrowRight size={14} />
                        </button>
                      </div>
                      {memories.length ? (
                        <div className="recent-memory-list">
                          {memories.slice(0, 2).map((item) => (
                            <button
                              key={item.id}
                              onClick={() => setSelectedMemory(item)}
                            >
                              <span className="memory-small-icon">
                                <Sparkles size={16} />
                              </span>
                              <div>
                                <strong>{item.question}</strong>
                                <span>
                                  {item.source_ids.length} sources ·{" "}
                                  {formatDate(item.created_at)}
                                </span>
                              </div>
                              <ArrowUpRight size={16} />
                            </button>
                          ))}
                        </div>
                      ) : (
                        <div className="memory-empty-inline">
                          <Sparkles size={18} />
                          <p>
                            Your next investigation becomes company memory.
                            <br />
                            <span>
                              Ask Relay a question to start connecting the dots.
                            </span>
                          </p>
                        </div>
                      )}
                    </section>
                  </>
                )}
                {view === "knowledge" && (
                  <KnowledgePage
                    onSource={(id) => openSource(id, false)}
                    onAddNote={() => setNoteOpen(true)}
                  />
                )}
                {view === "workflows" && (
                  <WorkflowPage
                    runId={routeId}
                    projects={data.nodes.filter(
                      (node) => node.kind === "project",
                    )}
                    mode={data.capabilities.mode}
                    onAskRun={(id) => {
                      setAssistantRunId(id);
                      setTimeout(() => {
                        const composer =
                          document.querySelector<HTMLTextAreaElement>(
                            '[aria-label="Ask Relay a question"]',
                          );
                        composer?.focus();
                        composer?.scrollIntoView({ block: "center" });
                      }, 0);
                    }}
                  />
                )}
                {view === "approvals" && <ApprovalInbox approvalId={routeId} />}
                {view === "memory" && (
                  <section>
                    <div className="section-toolbar">
                      <span>{memories.length} saved investigations</span>
                      <Button
                        busy={listLoading}
                        onClick={() => refreshList("memory")}
                      >
                        <RefreshCw size={15} />
                        Refresh
                      </Button>
                    </div>
                    {listError && <Status error>{listError}</Status>}
                    {listLoading && (
                      <Status>Loading saved investigations…</Status>
                    )}
                    {!listLoading && !memories.length && (
                      <Empty title="Every good question leaves a trace">
                        Ask Relay about a launch or an owner. Your source-backed
                        investigation will be saved here.
                      </Empty>
                    )}
                    <div className="memory-list">
                      {memories.map((item) => (
                        <article className="memory-card" key={item.id}>
                          <div className="memory-card-top">
                            <span className="memory-small-icon">
                              <Sparkles size={17} />
                            </span>
                            <span>{formatDate(item.created_at)}</span>
                            <span className="badge">
                              {item.mode === "demo"
                                ? "Guided demo"
                                : "Live model"}
                            </span>
                          </div>
                          <h2>
                            <button onClick={() => setSelectedMemory(item)}>
                              {item.question}
                              <ArrowUpRight size={16} />
                            </button>
                          </h2>
                          <p>{item.answer}</p>
                          <div className="memory-card-bottom">
                            <span>
                              <FileText size={13} />
                              {item.source_ids.length} sources
                            </span>
                            <span>
                              <GitBranch size={13} />
                              {item.steps.length} agent steps
                            </span>
                            <button
                              className="text-link"
                              onClick={() => setSelectedMemory(item)}
                            >
                              Open investigation
                              <ArrowRight size={13} />
                            </button>
                          </div>
                        </article>
                      ))}
                    </div>
                  </section>
                )}
                {view === "actions" && (
                  <section>
                    <div className="section-toolbar">
                      <div className="filter-pills" aria-label="Filter tasks">
                        {(["all", "proposed", "approved", "done"] as const).map(
                          (status) => (
                            <button
                              key={status}
                              aria-pressed={actionFilter === status}
                              onClick={() => setActionFilter(status)}
                            >
                              {status === "all"
                                ? "All tasks"
                                : status === "proposed"
                                  ? "Needs approval"
                                  : status === "done"
                                    ? "Complete"
                                    : "Approved"}
                            </button>
                          ),
                        )}
                      </div>
                      <Button
                        busy={listLoading}
                        onClick={() => refreshList("actions")}
                        aria-label="Refresh tasks"
                      >
                        <RefreshCw size={15} />
                      </Button>
                    </div>
                    <div className="action-scope-note">
                      <CircleDot size={15} />
                      Tasks stay inside Relay. Approval does not send messages
                      or change live systems.
                    </div>
                    {listError && <Status error>{listError}</Status>}
                    {listLoading && <Status>Loading tasks…</Status>}
                    {!listLoading && !filteredActions.length && (
                      <Empty title="Nothing waiting here">
                        Investigate a company question or try a Ripple scenario
                        to prepare next steps.
                      </Empty>
                    )}
                    <div className="actions-list">
                      {filteredActions.map((action) => (
                        <ActionCard
                          key={action.id}
                          action={action}
                          sources={sources}
                          onSource={openSource}
                          onTransition={transition}
                        />
                      ))}
                    </div>
                  </section>
                )}
              </>
            )}
          </main>
          {data && (
            <Assistant
              sources={sources}
              mode={data.capabilities.mode}
              onSource={openSource}
              onResult={investigated}
              onActions={() => goTo("actions")}
              runId={assistantRunId}
              onClearRun={() => setAssistantRunId(undefined)}
            />
          )}
        </div>
      </div>
      <Modal
        open={!!selectedNode}
        onOpenChange={(open) => {
          if (!open) setSelectedNode(null);
        }}
        title={selectedNode?.label || "Company entity"}
        description="The context and evidence behind this connection."
      >
        {selectedNode && (
          <div className="entity-detail">
            <span className="badge">{selectedNode.kind}</span>
            <p>{selectedNode.description}</p>
            <div className="entity-facts">
              <div>
                <span>Owner</span>
                <strong>{selectedNode.owner || "See source evidence"}</strong>
              </div>
              <div>
                <span>Recorded status</span>
                <strong>{selectedNode.status.replace("_", " ")}</strong>
              </div>
            </div>
            {ripple?.affected_ids.includes(selectedNode.id) && (
              <p className="entity-impact">
                <Waves size={16} />
                Exposed in the current hypothetical scenario.
              </p>
            )}
            <h3>Source evidence</h3>
            <div className="detail-source-list">
              {selectedNode.source_ids.map((id) => (
                <SourceButton
                  key={id}
                  id={id}
                  sources={sources}
                  onSource={openSource}
                />
              ))}
            </div>
            <h3>Connections</h3>
            <div className="entity-connections">
              {data?.edges
                .filter(
                  (edge) =>
                    edge.source === selectedNode.id ||
                    edge.target === selectedNode.id,
                )
                .map((edge) => (
                  <div key={edge.id}>
                    <span>
                      {
                        data.nodes.find((node) => node.id === edge.source)
                          ?.label
                      }
                    </span>
                    <small>{edge.label}</small>
                    <span>
                      {
                        data.nodes.find((node) => node.id === edge.target)
                          ?.label
                      }
                    </span>
                  </div>
                ))}
            </div>
          </div>
        )}
      </Modal>
      <EvidenceViewer
        sourceId={sourceId}
        legacyCitation={legacySource}
        onClose={() => setSourceId(null)}
        returnFocusTo={sourceOpener.current}
      />
      <Modal
        open={!!selectedMemory}
        onOpenChange={(open) => {
          if (!open) setSelectedMemory(null);
        }}
        title={selectedMemory?.question || "Saved investigation"}
        description="A saved, source-backed investigation."
        wide
      >
        {selectedMemory && (
          <article className="investigation-detail">
            <div className="source-detail-meta">
              <span className="badge">
                {selectedMemory.mode === "demo" ? "Guided demo" : "Live model"}
              </span>
              <span>{formatDate(selectedMemory.created_at)}</span>
            </div>
            <p>{selectedMemory.answer}</p>
            <h3>Source evidence</h3>
            <div className="detail-source-list">
              {selectedMemory.source_ids.map((id) => (
                <SourceButton
                  key={id}
                  id={id}
                  sources={sources}
                  onSource={openSource}
                />
              ))}
            </div>
            <h3>Agent handoffs</h3>
            <ol className="memory-agent-steps">
              {selectedMemory.steps.map((step, i) => (
                <li key={i}>
                  <Check size={16} />
                  <div>
                    <strong>{step.label}</strong>
                    <p>{step.detail}</p>
                    <small>
                      {step.agent} · {step.status}
                    </small>
                  </div>
                </li>
              ))}
            </ol>
            {selectedMemory.actions.length > 0 && (
              <Button
                onClick={() => {
                  setSelectedMemory(null);
                  goTo("actions");
                }}
              >
                Review proposed tasks
                <ArrowRight size={15} />
              </Button>
            )}
          </article>
        )}
      </Modal>
      <SourceNoteForm
        open={noteOpen}
        onOpenChange={setNoteOpen}
        onSaved={(newSource) => {
          setData((current) =>
            current
              ? { ...current, sources: [newSource, ...current.sources] }
              : current,
          );
          setNotice(
            "Source saved. Original content is available in Knowledge.",
          );
          goTo("knowledge");
        }}
      />
      {notice && (
        <div className="toast" role="status">
          <Check size={17} />
          <span>{notice}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setNotice("")}
          >
            <X size={15} />
          </button>
        </div>
      )}
    </div>
  );
}
export default App;
