import { useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  Activity,
  BookOpen,
  Box,
  Circle,
  FileText,
  GitBranch,
  Network,
  Rocket,
  ShieldCheck,
  UserRound,
  Users,
  Waypoints,
} from "lucide-react";
import type { GraphEdge, GraphNode, Ripple } from "../types";
import { Button } from "./ui";
import { recoveryHighlights } from "../recovery";
const icons = {
  project: Rocket,
  service: Box,
  person: UserRound,
  team: Users,
  document: FileText,
  decision: ShieldCheck,
  incident: Activity,
};
type CompanyNodeData = Record<string, unknown> & {
  entity: GraphNode;
  exposed: boolean;
  origin: boolean;
  mitigated: boolean;
};
function EntityNode({ data }: NodeProps<Node<CompanyNodeData>>) {
  const entity = data.entity;
  const Icon = icons[entity.kind];
  return (
    <div
      className={`company-node node-${entity.kind} ${data.exposed ? "node-exposed" : ""} ${data.origin ? "node-origin" : ""} ${data.mitigated ? "node-mitigated" : ""}`}
    >
      <Handle type="target" position={Position.Left} />
      <div className="node-kind">
        <span className="node-icon">
          <Icon size={16} />
        </span>
        <span>{entity.kind}</span>
        {data.origin ? (
          <span className="node-health blocked" title="Scenario origin" />
        ) : (
          <span
            className={`node-health ${data.exposed ? "at_risk" : data.mitigated ? "healthy" : entity.status}`}
            title={data.exposed ? "Exposed in scenario" : entity.status}
          />
        )}
      </div>
      <strong>{entity.label}</strong>
      <div className="node-caption">
        {data.origin
          ? "Simulated outage"
          : data.exposed
            ? "Exposed dependency"
            : data.mitigated
              ? "Recovery assumption"
              : entity.owner || entity.status.replace("_", " ")}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { entity: EntityNode };
export function CompanyGraph({
  nodes,
  edges,
  ripple,
  onNode,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  ripple: Ripple | null;
  onNode: (node: GraphNode) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const visible = useMemo(
    () =>
      showAll
        ? nodes
        : nodes.filter(
            (node) => node.kind === "project" || node.kind === "service",
          ),
    [nodes, showAll],
  );
  const recovery = useMemo(
    () => recoveryHighlights(nodes, edges, ripple),
    [nodes, edges, ripple],
  );
  const graphNodes = useMemo<Node<CompanyNodeData>[]>(
    () =>
      visible.map((entity) => ({
        id: entity.id,
        type: "entity",
        position: { x: entity.x, y: entity.y },
        data: {
          entity,
          exposed: !!ripple?.affected_ids.includes(entity.id),
          origin: entity.id === ripple?.origin_id,
          mitigated: recovery.nodeIds.has(entity.id),
        },
        ariaLabel: `${entity.label}, ${entity.kind}. Open evidence.`,
        selectable: true,
        draggable: false,
      })),
    [visible, ripple, recovery],
  );
  const graphEdges = useMemo(() => {
    const visibleIds = new Set(visible.map((node) => node.id));
    const impactedPairs = new Set(
      ripple?.paths.flatMap((path) =>
        path.slice(1).map((id, i) => `${path[i]}|${id}`),
      ) ?? [],
    );
    return edges
      .filter(
        (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
      )
      .map((edge) => {
        const impacted =
          edge.relation === "DEPENDS_ON" &&
          (impactedPairs.has(`${edge.source}|${edge.target}`) ||
            impactedPairs.has(`${edge.target}|${edge.source}`));
        const backup = recovery.edgeIds.has(edge.id);
        const color = impacted
          ? "var(--color-impact)"
          : backup
            ? "var(--color-success)"
            : "var(--color-graph-edge)";
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: "smoothstep",
          animated: impacted || backup,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color,
            width: 14,
            height: 14,
          },
          style: {
            stroke: color,
            strokeWidth: impacted || backup ? 2.2 : 1.3,
            strokeDasharray: edge.relation === "DEPENDS_ON" ? undefined : "5 5",
          },
          label: impacted ? "depends on" : backup ? edge.label : undefined,
          labelStyle: { fill: color, fontSize: 10, fontWeight: 600 },
          labelBgStyle: { fill: "var(--color-surface)", fillOpacity: 0.95 },
          focusable: true,
          ariaLabel: `${nodes.find((node) => node.id === edge.source)?.label} ${edge.label} ${nodes.find((node) => node.id === edge.target)?.label}`,
        };
      });
  }, [visible, edges, nodes, ripple, recovery]);
  return (
    <section className="graph-card" aria-label="Company dependency map">
      <div className="graph-heading">
        <div>
          <span className="section-kicker">
            <Network size={13} />
            THE BIG PICTURE
          </span>
          <h2>Everything is connected.</h2>
        </div>
        <div className="graph-view-switch" aria-label="Map view">
          <Button
            variant={!showAll ? "secondary" : "ghost"}
            aria-pressed={!showAll}
            onClick={() => setShowAll(false)}
          >
            Launch map
          </Button>
          <Button
            variant={showAll ? "secondary" : "ghost"}
            aria-pressed={showAll}
            onClick={() => setShowAll(true)}
          >
            All entities
          </Button>
        </div>
      </div>
      <div className="graph-canvas">
        <div className="graph-context">
          <span className="context-dot" />
          Atlas launch<span className="context-separator">/</span>
          {showAll ? "Company network" : "Dependency view"}
        </div>
        <ReactFlow
          key={showAll ? "all" : "launch"}
          nodes={graphNodes}
          edges={graphEdges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.17 }}
          minZoom={0.15}
          maxZoom={1.8}
          nodesDraggable={false}
          nodesConnectable={false}
          onNodeClick={(_, node) => onNode(node.data.entity)}
          onNodeDoubleClick={(_, node) => onNode(node.data.entity)}
          proOptions={{ hideAttribution: true }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={22}
            size={1}
            color="var(--color-graph-dot)"
          />
          <Controls showInteractive={false} />
        </ReactFlow>
        <div className="map-hint">
          <Waypoints size={13} />
          Select a node to see its evidence
        </div>
      </div>
      <div className="graph-footer">
        <div className="graph-legend">
          <span>
            <Circle size={8} fill="currentColor" />
            Connected
          </span>
          <span className="legend-impact">
            <Circle size={8} fill="currentColor" />
            Exposed
          </span>
          <span className="legend-recovery">
            <Circle size={8} fill="currentColor" />
            Recovery
          </span>
        </div>
        <span>
          {visible.length} of {nodes.length} entities
          <GitBranch size={13} />
        </span>
      </div>
      <p className="map-direction">
        Arrows point to prerequisites. Impact travels back through dependents.
      </p>
      <details className="graph-accessible-list">
        <summary>
          <BookOpen size={14} />
          Browse map entities
        </summary>
        <div>
          {visible.map((node) => (
            <button key={node.id} onClick={() => onNode(node)}>
              {node.label}
            </button>
          ))}
        </div>
      </details>
    </section>
  );
}
