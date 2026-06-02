import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentAction, TaskItem } from "../../types";
import { ChatAgentActionSummary } from "./ChatAgentActionSummary";

function action(overrides: Partial<AgentAction>): AgentAction {
  return {
    action_id: overrides.action_id || "action-1",
    action_type: overrides.action_type || "chat.daily_archive",
    risk_tier: overrides.risk_tier || "low",
    decision: overrides.decision || "auto",
    status: overrides.status || "completed",
    title: overrides.title || "已归档聊天日记",
    summary: overrides.summary || "写入 Memories/Daily/2026-06-02.md",
    target_paths: overrides.target_paths || [],
    reversible: overrides.reversible ?? false,
    source: overrides.source || {},
    diff_summary: overrides.diff_summary || "",
    metadata: overrides.metadata || {},
    created_at: overrides.created_at || "2026-06-02T00:00:00.000Z",
    updated_at: overrides.updated_at || "2026-06-02T00:00:00.000Z",
    completed_at: overrides.completed_at || "2026-06-02T00:00:00.000Z",
    ...overrides,
  };
}

function task(overrides: Partial<TaskItem> = {}): TaskItem {
  return {
    task_id: overrides.task_id || "task-1",
    title: overrides.title || "复盘 TASK-02",
    status: overrides.status || "pending",
    remind_at: overrides.remind_at,
    timezone_label: overrides.timezone_label,
    ...overrides,
  };
}

describe("ChatAgentActionSummary", () => {
  it("explains when a completed turn has no traceable organization events", () => {
    render(<ChatAgentActionSummary actions={[]} tasks={[]} showEmpty />);

    expect(screen.getByText("本轮整理结果")).toBeInTheDocument();
    expect(screen.getByText("未产生可保存内容。本轮没有收到可追踪的自动整理活动或任务事件。")).toBeInTheDocument();
    expect(screen.getByText("本轮没有聊天日记写入事件。")).toBeInTheDocument();
  });

  it("renders per-turn organization buckets from real action and task events", () => {
    render(
      <ChatAgentActionSummary
        actions={[
          action({ action_id: "daily", action_type: "chat.daily_archive", target_paths: ["Memories/Daily/a.md"] }),
          action({ action_id: "structured", action_type: "diary.structured_memory", summary: "识别 1 条" }),
          action({ action_id: "long-term", action_type: "memory.long_term.write", title: "已更新长期记忆" }),
          action({ action_id: "wiki", action_type: "wiki.answer_summary.write", target_paths: ["Wiki/A.md"] }),
          action({
            action_id: "skip",
            action_type: "chat.auto_memory.skip",
            status: "skipped",
            decision: "notify",
            title: "已跳过自动整理",
            summary: "Skipped because automation is disabled.",
            metadata: { skipped_reason: "automation_disabled" },
          }),
        ]}
        tasks={[task({ remind_at: "2026-06-02T12:00:00Z", timezone_label: "Asia/Shanghai" })]}
      />,
    );

    expect(screen.getByText("本轮整理结果")).toBeInTheDocument();
    expect(screen.getByText("写入日记")).toBeInTheDocument();
    expect(screen.getByText("结构化记忆")).toBeInTheDocument();
    expect(screen.getByText("长期记忆")).toBeInTheDocument();
    expect(screen.getByText("Wiki 摘要")).toBeInTheDocument();
    expect(screen.getByText("任务/提醒")).toBeInTheDocument();
    expect(screen.getByText("已跳过")).toBeInTheDocument();
    expect(screen.getByText("原因：automation_disabled")).toBeInTheDocument();
    expect(screen.getByText("复盘 TASK-02")).toBeInTheDocument();
  });

  it("keeps reversible markdown writes connected to the backend revert handler", () => {
    const onRevert = vi.fn();
    const reversible = action({
      action_id: "wiki",
      action_type: "wiki.answer_summary.write",
      title: "已自动总结到资料库",
      target_paths: ["Wiki/A.md"],
      reversible: true,
    });

    render(<ChatAgentActionSummary actions={[reversible]} onRevertAgentAction={onRevert} />);

    fireEvent.click(screen.getByRole("button", { name: "撤销" }));

    expect(onRevert).toHaveBeenCalledWith(reversible);
  });
});
