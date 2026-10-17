import type { Action, Investigation } from "./types";
const actionRank: Record<Action["status"], number> = {
  proposed: 0,
  approved: 1,
  done: 2,
};
/** Immutable IDs and the forward-only task lifecycle make late snapshots safe to merge. */
export function mergeActions(current: Action[], incoming: Action[]): Action[] {
  const merged = new Map(current.map((item) => [item.id, item]));
  for (const item of incoming) {
    const existing = merged.get(item.id);
    if (!existing || actionRank[item.status] >= actionRank[existing.status])
      merged.set(item.id, item);
  }
  return [...merged.values()];
}
export function mergeMemories(
  current: Investigation[],
  incoming: Investigation[],
): Investigation[] {
  const merged = new Map(current.map((item) => [item.id, item]));
  for (const item of incoming) merged.set(item.id, item);
  return [...merged.values()]
    .sort(
      (left, right) =>
        Date.parse(right.created_at) - Date.parse(left.created_at),
    )
    .slice(0, 30);
}
