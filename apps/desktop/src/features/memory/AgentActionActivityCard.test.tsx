import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentAction } from "../../types";
import type { AgentActivityLogEntry } from "../../services/agentActivity";
import { AgentActionActivityCard } from "./AgentActionActivityCard";

function action(overrides: Partial<AgentAction> = {}): AgentAction {
  return {
    action_id: "action-1",
    action_type: "wiki.answer_summary.write",
    risk_tier: "low",
    decision: "auto",
    status: "completed",
    title: "Saved summary",
    summary: "Saved to Wiki/Summary.md",
    target_paths: ["Wiki/Summary.md"],
    reversible: false,
    source: {},
    diff_summary: "",
    metadata: {},
    created_at: "2026-06-02T00:00:00.000Z",
    updated_at: "2026-06-02T00:00:00.000Z",
    completed_at: "2026-06-02T00:00:00.000Z",
    ...overrides,
  };
}

function entry(agentAction = action()): Extract<AgentActivityLogEntry, { kind: "agent_action" }> {
  return {
    kind: "agent_action",
    id: `agent-action-${agentAction.action_id}`,
    sortAt: agentAction.updated_at,
    sortKey: Date.parse(agentAction.updated_at),
    action: agentAction,
  };
}

describe("AgentActionActivityCard", () => {
  it("routes target file commands through the provided Vault reveal callback", () => {
    const onRevealTarget = vi.fn();

    render(
      <AgentActionActivityCard
        entry={entry()}
        reverting={false}
        onRevert={vi.fn()}
        onRevealTarget={onRevealTarget}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "打开 Markdown" }));
    fireEvent.click(screen.getByRole("button", { name: "显示位置" }));

    expect(onRevealTarget).toHaveBeenCalledWith("Wiki/Summary.md", "open");
    expect(onRevealTarget).toHaveBeenCalledWith("Wiki/Summary.md", "show");
  });

  it("does not offer local file controls for non-Markdown targets", () => {
    render(
      <AgentActionActivityCard
        entry={entry(action({ target_paths: ["Wiki/image.png"] }))}
        reverting={false}
        onRevert={vi.fn()}
        onRevealTarget={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "打开 Markdown" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "显示位置" })).not.toBeInTheDocument();
  });

  it("uses human-readable skipped automation copy without exposing legacy English details", () => {
    render(
      <AgentActionActivityCard
        entry={entry(
          action({
            action_type: "chat.auto_memory.skip",
            status: "skipped",
            decision: "notify",
            title: "Skipped automatic organization",
            summary:
              "Skipped because automatic diary, structured memory, long-term memory, and Wiki organization are disabled; no local asset was written.",
            target_paths: [],
            metadata: { skipped_reason: "automation_disabled" },
          }),
        )}
        reverting={false}
        onRevert={vi.fn()}
      />,
    );

    expect(screen.getByText("已跳过自动整理")).toBeInTheDocument();
    expect(screen.getByText(/自动整理策略当前关闭/)).toBeInTheDocument();
    expect(screen.queryByText(/Skipped automatic organization/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Skipped because/)).not.toBeInTheDocument();
    expect(screen.queryByText(/automation_disabled/)).not.toBeInTheDocument();
  });
});
