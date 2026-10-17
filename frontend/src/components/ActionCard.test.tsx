import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ActionCard } from "./ActionCard";
import type { Action } from "../types";
const action: Action = {
  id: "task-1",
  title: "Verify backup provider",
  description: "Run the recovery check.",
  owner: "Maya Chen",
  status: "proposed",
  investigation_id: "i1",
  source_ids: [],
  created_at: "2026-10-17T00:00:00Z",
};
describe("Action approval", () => {
  it("offers approval before completion and sends the correct transition", async () => {
    const transition = vi.fn().mockResolvedValue(undefined);
    render(
      <ActionCard
        action={action}
        onTransition={transition}
        onSource={vi.fn()}
        sources={[]}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Mark complete" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve task" }));
    expect(transition).toHaveBeenCalledWith("task-1", "approve");
  });
  it("keeps a recoverable inline error when approval fails", async () => {
    const transition = vi
      .fn()
      .mockRejectedValue(new Error("Graph unavailable. Retry approval."));
    render(
      <ActionCard
        action={action}
        onTransition={transition}
        onSource={vi.fn()}
        sources={[]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Approve task" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Graph unavailable"),
    );
    expect(screen.getByRole("button", { name: "Approve task" })).toBeEnabled();
  });
  it("only offers completion for an approved task", async () => {
    const transition = vi.fn().mockResolvedValue(undefined);
    render(
      <ActionCard
        action={{ ...action, status: "approved" }}
        onTransition={transition}
        onSource={vi.fn()}
        sources={[]}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Mark complete" }),
    );
    expect(transition).toHaveBeenCalledWith("task-1", "complete");
  });
});
