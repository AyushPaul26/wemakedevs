# Relay product specification

This is the original company-map baseline specification. The later approved
[workflow proposal](relay-workflows-proposal.md), [database design](relay-workflows-database.md),
and [current walkthrough](workflow-demo.md) extend it with member sessions,
private attachments, approvals, real execution, and versioned outputs. The API
shapes and implementation-turn authorization below describe that earlier baseline.

The user approved starting implementation after reviewing Relay, Ripple, the repository shortlist, and the Graph Hacks requirements. Build a working end-to-end hackathon application in the existing isolated cloud checkout.

## Product

Relay is an evidence-backed company assistant. Its signature interaction is Ripple: select a service outage or delay, trace the affected launch through a real FalkorDB dependency graph, compare a recovery assumption, and prepare follow-up tasks for approval. The fictional company is **Meridian**, preparing its **Atlas launch**. Clearly label the workspace as sample company data.

The default workspace opens into a polished company intelligence screen with an interactive dependency map, an investigation panel, a small recent-activity/memory section, and navigation to Knowledge, Memory, and Actions. The default selected scenario is Payment gateway outage. Core proof: payment-gateway -> checkout -> atlas-launch, with owners, source citations, mitigation by backup-provider, and an earlier incident recording that mitigation.

## Scope and truthfulness

- FalkorDB is the primary graph. All company relationship retrieval, Ripple calculations, durable investigation memory, and action writes execute against it.
- Python/FastAPI backend; React/TypeScript/Vite frontend. React Flow renders graph results. LangGraph coordinates researcher, planner, and archivist nodes. File-backed SQLite is allowed only for workflow checkpoints.
- Use assistant-ui chat primitives/custom runtime where useful, with the backend owning messages and persistence.
- Keep model integration configurable. With no API key, show **Guided demo** prominently and produce deterministic source-backed responses to supported questions; never label those responses live AI. Live OpenAI-compatible calls use RELAY_MODEL_API_KEY, RELAY_MODEL_BASE_URL, RELAY_MODEL and a bounded timeout. Failure yields a visible recoverable error, not silent replacement with a fabricated live answer.
- Document semantic extraction through GraphRAG-SDK is optional until provider/model access exists; do not pretend it ran. Graphify imports must retain provenance and map into FalkorDB. Core demo requires no paid account.
- Hypothetical scenarios do not modify authoritative facts. Dependency traversal follows typed DEPENDS_ON direction; undirected graph proximity is not causal evidence.
- Task creation is explicit approval, idempotent, and internal to Relay. No external messages, real tickets, or production changes are authorized.
- Single sample workspace, loopback development service; do not claim multi-tenant production authorization or deployed hosting.

## Public API contract

All endpoints use `/api`. All IDs are stable strings. JSON errors contain `detail` with a helpful message. Dates are ISO UTC; the UI formats to the user's locale. Unknown node/action IDs return 404, invalid requests 422, unavailable graph 503. CORS is limited to local dev origins; Vite proxies `/api`.

### Common shapes

- GraphNode: `{id,label,kind,description,status,owner?,source_ids:string[],x:number,y:number}`. Kinds: `project|service|person|team|document|decision|incident`. Status: `healthy|at_risk|blocked|active|resolved`.
- GraphEdge: `{id,source,target,relation,label,source_ids:string[]}`. A DEPENDS_ON edge points from the dependent to its prerequisite. Display can visually animate reversed impact paths, but source/target semantics must stay consistent.
- Source: `{id,title,type,excerpt,updated_at,author}`. Type `document|ticket|decision|incident|code`. Full fictional sample source text can be stored as excerpt.
- Action: `{id,title,description,owner,status,investigation_id,source_ids,created_at,approved_at?}`. Status `proposed|approved|done`. Approving twice returns the existing action; never duplicate tasks.
- AgentStep: `{agent,label,detail,status}`; status `complete|running|waiting`.
- Investigation: `{id,question,answer,source_ids,node_ids,steps:AgentStep[],actions:Action[],created_at,mode}`. Mode `demo|live`.
- Ripple: `{scenario_id,origin_id,mitigation,affected_ids:string[],paths:string[][],summary,source_ids:string[],actions:Action[],risk_before:number,risk_after:number,assumptions:string[]}`. Risk values are explicitly dependency exposure counts, not probability or financial forecasts.

### Endpoints

- `GET /health`: `{status:'ok',graph:'connected',mode:'demo'|'live'}` after a real DB query.
- `GET /bootstrap`: `{workspace:{name:'Meridian',project:'Atlas launch',is_demo:true},nodes:GraphNode[],edges:GraphEdge[],sources:Source[],stats:{entities,relationships,memories,actions},capabilities:{mode,provider,document_ingestion:boolean},recent_memory:Investigation[],actions:Action[]}`.
- `POST /investigate` body `{question:string,session_id?:string}` -> Investigation. Nonempty trimmed question, max 2000 chars. A fresh session UUID is allowed; reusing one resumes checkpoint history. Handle company/launch/owner/payment/previous incident questions; unsupported demo queries explain the demo boundary with suggested questions. Cite only existing source IDs.
- `POST /ripple` body `{origin_id:string,mitigation:boolean=false}` -> Ripple. Valid origins are service nodes. Recompute from DB on each call; enabling backup mitigation removes only the dependency exposure supported by the backup relationship.
- `GET /memory` -> `{items:Investigation[]}` newest first. Investigations persist across process restart.
- `GET /actions` -> `{items:Action[]}`.
- `POST /actions/{id}/approve` -> Action, idempotent.
- `POST /actions/{id}/complete` -> Action; only approved actions may complete (409 otherwise), repeats are idempotent.
- `GET /sources/{id}` -> Source.
- `POST /sources` body `{title:string,content:string,type?:'document'}` -> Source. Store the uploaded note in FalkorDB with provenance; a response never claims entities were semantically extracted unless an enabled importer actually performed it. Input max 30000 chars.

## Backend service interface

`GraphStore` in `backend/relay/graph_store.py` reads RELAY_FALKORDB_HOST (127.0.0.1), PORT (6379), GRAPH (relay_demo). It accepts optional `graph_name` for isolated tests. Methods return JSON-compatible dicts/lists:

- `health() -> bool`, `seed() -> None` (idempotent and preserves user notes/memory/tasks)
- `get_graph() -> {nodes,edges,sources}`, `stats() -> dict`
- `get_source(source_id) -> dict|None`, `add_source(title,content) -> dict`
- `retrieve(question) -> {nodes,edges,sources,prior_memories}` (bounded relevant context; graph queries, no model)
- `simulate(origin_id,mitigation=False) -> Ripple` (raises ValueError for invalid service)
- `save_investigation(investigation:dict) -> dict`, `list_memories(limit=30) -> list[dict]`
- `save_actions(actions:list[dict]) -> None`, `list_actions() -> list[dict]`, `transition_action(action_id,target_status) -> dict` (KeyError missing; ValueError disallowed)
- `import_graphify(data:dict,source_name:str) -> {nodes:int,edges:int}` (validate and whitelist label/relation values; retain imported provenance; no arbitrary query interpolation)

## Verification

Meaningful tests must exercise actual FalkorDB: directed multi-hop impact, mitigation reducing only justified impact, scenario isolation, no duplicate seed/action approvals, persistence through a new GraphStore instance, and source citations. API tests cover errors, approval and completion ordering, and unsupported demo questions. Browser checks cover real investigation, graph interaction, mitigation toggle, approved actions, reloaded memory, keyboard focus, visible error/empty states, and narrow screens. Run typecheck and production build.

## Submission

Lead with Track 3 Company Brain. Track 1 proof is real graph-based investigation plus approved actions. Track 2 proof is LangGraph handoffs, persistent state, and saved company memory. Record honest demo and setup instructions. No commit, GitHub push, or public deployment is requested in this implementation turn.
