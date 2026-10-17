import { describe, expect, it } from "vitest";
import { mergeActions, mergeMemories } from "./state";
import type { Action, Investigation } from "./types";
const task: Action = {
  id: "task-1",
  title: "Review failover",
  description: "",
  owner: "Devon Park",
  status: "proposed",
  investigation_id: "i1",
  source_ids: [],
  created_at: "2026-10-17T00:00:00Z",
};
const memory = (id: string, created_at: string): Investigation => ({
  id,
  question: id,
  answer: "",
  created_at,
  source_ids: [],
  node_ids: [],
  steps: [],
  actions: [],
  mode: "demo",
});
describe("late list responses", () => {
  it("cannot undo a confirmed approval or completion", () => {
    expect(
      mergeActions([{ ...task, status: "approved" }], [task])[0].status,
    ).toBe("approved");
    expect(
      mergeActions(
        [{ ...task, status: "done" }],
        [{ ...task, status: "approved" }],
      )[0].status,
    ).toBe("done");
  });
  it("still accepts forward transitions and retains newly proposed tasks", () => {
    const next = { ...task, id: "task-2" };
    expect(
      mergeActions([task, next], [{ ...task, status: "approved" }]),
    ).toEqual([{ ...task, status: "approved" }, next]);
  });
  it("retains a new investigation when an older memory snapshot arrives", () => {
    const old = memory("old", "2026-10-16T00:00:00Z");
    const latest = memory("latest", "2026-10-17T00:00:00Z");
    expect(mergeMemories([latest], [old])).toEqual([latest, old]);
    expect(mergeMemories([latest], [latest])).toEqual([latest]);
  });
});
