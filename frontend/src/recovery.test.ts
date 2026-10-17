import { describe, expect, it } from "vitest";
import { recoveryHighlights } from "./recovery";
import type { GraphNode, GraphEdge, Ripple } from "./types";
const node = (id: string, status = "healthy"): GraphNode => ({
  id,
  label: id,
  kind: "service",
  description: "",
  status,
  source_ids: [],
  x: 0,
  y: 0,
});
const edge = (source: string, relation: string, target: string): GraphEdge => ({
  id: `${source}-${relation}-${target}`,
  source,
  target,
  relation,
  label: relation,
  source_ids: [],
});
const nodes = ["origin", "consumer", "backup", "billing", "other"].map((id) =>
  node(id),
);
const edges = [
  edge("consumer", "DEPENDS_ON", "origin"),
  edge("billing", "DEPENDS_ON", "origin"),
  edge("consumer", "CAN_USE", "backup"),
  edge("backup", "BACKUP_FOR", "origin"),
];
const result: Ripple = {
  scenario_id: "scenario",
  origin_id: "origin",
  mitigation: true,
  affected_ids: ["billing"],
  paths: [["origin", "billing"]],
  summary: "",
  source_ids: [],
  actions: [],
  risk_before: 2,
  risk_after: 1,
  assumptions: [],
};
function expectNoRecovery(
  graphNodes = nodes,
  graphEdges = edges,
  ripple: Ripple = result,
) {
  const highlighted = recoveryHighlights(graphNodes, graphEdges, ripple);
  expect([...highlighted.nodeIds]).toEqual([]);
  expect([...highlighted.edgeIds]).toEqual([]);
}
describe("source-backed recovery highlights", () => {
  it("highlights the supported healthy backup and exactly its two evidence relationships", () => {
    const highlighted = recoveryHighlights(
      nodes,
      [...edges, edge("other", "CAN_USE", "backup")],
      result,
    );
    expect([...highlighted.nodeIds]).toEqual(["backup"]);
    expect([...highlighted.edgeIds].sort()).toEqual(
      [edges[2].id, edges[3].id].sort(),
    );
  });
  it("does not color an unhealthy backup when another backup really caused recovery", () => {
    const otherEdges = [
      ...edges,
      edge("consumer", "CAN_USE", "other"),
      edge("other", "BACKUP_FOR", "origin"),
    ];
    const highlighted = recoveryHighlights(
      nodes.map((item) =>
        item.id === "backup" ? { ...item, status: "blocked" } : item,
      ),
      otherEdges,
      result,
    );
    expect([...highlighted.nodeIds]).toEqual(["other"]);
    expect(highlighted.edgeIds.has(edges[2].id)).toBe(false);
    expect(highlighted.edgeIds.has(edges[3].id)).toBe(false);
  });
  it("rejects a backup transitively exposed to the original outage", () => {
    expectNoRecovery(nodes, [
      ...edges,
      edge("backup", "DEPENDS_ON", "other"),
      edge("other", "DEPENDS_ON", "origin"),
    ]);
  });
  it("does not imply recovery when the consumer remains exposed through another path", () => {
    expectNoRecovery(nodes, edges, { ...result, affected_ids: ["consumer"] });
  });
  it("requires the matching consumer direct dependency and directed CAN_USE relationship", () => {
    expectNoRecovery(
      nodes,
      edges.filter((item) => item.id !== edges[0].id),
    );
    expectNoRecovery(nodes, [
      ...edges.filter((item) => item.id !== edges[2].id),
      edge("backup", "CAN_USE", "consumer"),
    ]);
  });
  it("requires an enabled assumption and a backend-confirmed exposure reduction", () => {
    expectNoRecovery(nodes, edges, { ...result, mitigation: false });
    expectNoRecovery(nodes, edges, {
      ...result,
      risk_after: result.risk_before,
    });
  });
});
