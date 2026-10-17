export type GraphNode = {
  id: string;
  label: string;
  kind:
    | "project"
    | "service"
    | "person"
    | "team"
    | "document"
    | "decision"
    | "incident";
  description: string;
  status: string;
  owner?: string;
  source_ids: string[];
  x: number;
  y: number;
};
export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
  label: string;
  source_ids: string[];
};
export type Source = {
  id: string;
  title: string;
  type: "document" | "ticket" | "decision" | "incident" | "code";
  excerpt: string;
  updated_at: string;
  author: string;
};
export type Action = {
  id: string;
  title: string;
  description: string;
  owner: string;
  status: "proposed" | "approved" | "done";
  investigation_id: string;
  source_ids: string[];
  created_at: string;
  approved_at?: string;
};
export type AgentStep = {
  agent: string;
  label: string;
  detail: string;
  status: "complete" | "running" | "waiting";
};
export type Investigation = {
  id: string;
  question: string;
  answer: string;
  source_ids: string[];
  node_ids: string[];
  steps: AgentStep[];
  actions: Action[];
  created_at: string;
  mode: "demo" | "live";
};
export type Ripple = {
  scenario_id: string;
  origin_id: string;
  mitigation: boolean;
  affected_ids: string[];
  paths: string[][];
  summary: string;
  source_ids: string[];
  actions: Action[];
  risk_before: number;
  risk_after: number;
  assumptions: string[];
};
export type Bootstrap = {
  workspace: { name: string; project: string; is_demo: boolean };
  nodes: GraphNode[];
  edges: GraphEdge[];
  sources: Source[];
  stats: {
    entities: number;
    relationships: number;
    memories: number;
    actions: number;
  };
  capabilities: {
    mode: "demo" | "live";
    provider: string;
    document_ingestion: boolean;
  };
  recent_memory: Investigation[];
  actions: Action[];
};
