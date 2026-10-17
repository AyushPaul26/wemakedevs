import type { GraphEdge, GraphNode, Ripple } from "./types";

/** Presentation guards for recovery evidence; the backend remains the scenario authority. */
export function recoveryHighlights(
  nodes: GraphNode[],
  edges: GraphEdge[],
  ripple: Ripple | null,
) {
  const nodeIds = new Set<string>();
  const edgeIds = new Set<string>();
  if (!ripple?.mitigation || ripple.risk_after >= ripple.risk_before)
    return { nodeIds, edgeIds };

  // A backup exposed before mitigation cannot justify breaking its own outage path.
  const dependents = new Map<string, string[]>();
  for (const edge of edges) {
    if (edge.relation !== "DEPENDS_ON") continue;
    const consumers = dependents.get(edge.target) || [];
    consumers.push(edge.source);
    dependents.set(edge.target, consumers);
  }
  const exposedBefore = new Set([ripple.origin_id]);
  const pending = [ripple.origin_id];
  for (let index = 0; index < pending.length; index++) {
    for (const consumer of dependents.get(pending[index]) || []) {
      if (!exposedBefore.has(consumer)) {
        exposedBefore.add(consumer);
        pending.push(consumer);
      }
    }
  }

  const directConsumers = new Set(dependents.get(ripple.origin_id) || []);
  const stillExposed = new Set(ripple.affected_ids);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  for (const fallback of edges) {
    if (
      fallback.relation !== "BACKUP_FOR" ||
      fallback.target !== ripple.origin_id
    )
      continue;
    const backup = byId.get(fallback.source);
    if (
      backup?.status !== "healthy" ||
      exposedBefore.has(backup.id) ||
      stillExposed.has(backup.id)
    )
      continue;
    for (const usable of edges) {
      if (
        usable.relation !== "CAN_USE" ||
        usable.target !== backup.id ||
        !directConsumers.has(usable.source) ||
        stillExposed.has(usable.source) ||
        usable.source === ripple.origin_id
      )
        continue;
      nodeIds.add(backup.id);
      edgeIds.add(fallback.id);
      edgeIds.add(usable.id);
    }
  }
  return { nodeIds, edgeIds };
}
