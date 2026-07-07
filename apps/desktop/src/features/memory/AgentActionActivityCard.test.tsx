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
    summary: "Saved to Knowledge/Summary.md",
    target_paths: ["Knowledge/Summary.md"],
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
  it("routes target file commands through the provided local reveal callback", () => {
    const onRevealTarget = vi.fn();

    render(
      <AgentActionActivityCard
        entry={entry()}
        reverting={false}
        onRevert={vi.fn()}
        onRevealTarget={onRevealTarget}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "打开文件" }));
    fireEvent.click(screen.getByRole("button", { name: "显示位置" }));

    expect(onRevealTarget).toHaveBeenCalledWith("Knowledge/Summary.md", "open");
    expect(onRevealTarget).toHaveBeenCalledWith("Knowledge/Summary.md", "show");
  });

  it("does not offer local file controls for non-md targets", () => {
    render(
      <AgentActionActivityCard
        entry={entry(action({ target_paths: ["Knowledge/image.png"] }))}
        reverting={false}
        onRevert={vi.fn()}
        onRevealTarget={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "打开文件" })).not.toBeInTheDocument();
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
              "Skipped because automatic diary, structured memory, long-term memory, and knowledge organization are disabled; no local asset was written.",
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

  it("explains reversible activity rollback before calling the revert handler", () => {
    const onRevert = vi.fn();
    const reversible = action({
      action_type: "memory.long_term.write",
      title: "已更新长期记忆",
      summary: "记住发布清单。",
      target_paths: ["Memories/Profile.md"],
      reversible: true,
    });

    render(
      <AgentActionActivityCard
        entry={entry(reversible)}
        reverting={false}
        onRevert={onRevert}
      />,
    );

    expect(screen.getByText(/撤回前会再次确认/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "撤回" }));

    expect(onRevert).toHaveBeenCalledWith(reversible);
  });

  it("sanitizes raw ids and internal fields in activity details", () => {
    const { container } = render(
      <AgentActionActivityCard
        entry={entry(
          action({
            action_id: "activity-raw",
            action_type: "memory.profile.action",
            title: "target_id candidate:raw-candidate fact:raw-fact",
            summary: "source_text source_excerpt agent_run_id lifecycle_status Authorization token C:\\Users\\Alice\\Vault\\Secret.md",
            target_paths: ["C:\\Users\\Alice\\Vault\\Secret.md"],
            error: "memory_candidates target_id source_text Authorization",
            diff_summary: "fact:raw-fact source_excerpt",
            metadata: { skipped_reason: "automation_disabled target_id" },
            reverted_by: "action-raw-revert",
            reverts_action_id: "action-raw-source",
          }),
        )}
        reverting={false}
        onRevert={vi.fn()}
        onRevealTarget={vi.fn()}
      />,
    );

    expect(screen.getAllByText(/细节已隐藏/).length).toBeGreaterThan(0);
    expect(screen.getByText("这次整理没有完成，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByText("已撤回，并留下新的活动记录。")).toBeInTheDocument();
    expect(screen.getByText("这是撤回记录，来源活动细节已隐藏。")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(
      /target_id|candidate:|fact:|memory_candidates|source_text|source_excerpt|agent_run_id|lifecycle_status|Authorization|token|action-raw|C:\\Users\\Alice/i,
    );
  });

  it("shows a clear state after an activity has been reverted", () => {
    render(
      <AgentActionActivityCard
        entry={entry(action({ status: "reverted", reverted_by: "action-revert-1", reversible: true }))}
        reverting={false}
        onRevert={vi.fn()}
      />,
    );

    expect(screen.getByText(/已撤回，并留下新的活动记录/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "撤回" })).not.toBeInTheDocument();
  });
});
