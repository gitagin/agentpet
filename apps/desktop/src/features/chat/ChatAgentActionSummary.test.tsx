import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentAction, ChatWikiProposal, MemoryProposal, TaskItem } from "../../types";
import { ChatAgentActionSummary } from "./ChatAgentActionSummary";

function action(overrides: Partial<AgentAction>): AgentAction {
  return {
    action_id: overrides.action_id || "action-1",
    action_type: overrides.action_type || "chat.daily_archive",
    risk_tier: overrides.risk_tier || "low",
    decision: overrides.decision || "auto",
    status: overrides.status || "completed",
    title: overrides.title || "Saved chat diary",
    summary: overrides.summary || "Wrote Memories/Daily/2026-06-02.md",
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
    title: overrides.title || "Review TASK-02",
    status: overrides.status || "pending",
    remind_at: overrides.remind_at,
    timezone_label: overrides.timezone_label,
    ...overrides,
  };
}

function memoryProposal(overrides: Partial<MemoryProposal> = {}): MemoryProposal {
  return {
    proposal_id: overrides.proposal_id || "memory-1",
    type: overrides.type || "preference",
    content: overrides.content || "偏好简洁的发布清单。",
    target_path: overrides.target_path || "Memory/Preferences.md",
    status: overrides.status || "pending",
    ...overrides,
  };
}

function wikiProposal(overrides: Partial<ChatWikiProposal> = {}): ChatWikiProposal {
  return {
    id: overrides.id || "wiki-1",
    proposal_type: overrides.proposal_type || "synthesize",
    state: overrides.state || "pending",
    title: overrides.title || "决策记忆",
    summary: overrides.summary || "草拟 Wiki 页面。",
    target_paths: overrides.target_paths || ["Wiki/Decision-Memory.md"],
    recommended_targets: overrides.recommended_targets || [],
    selected_targets: overrides.selected_targets || [],
    findings: overrides.findings || [],
    updated_at: overrides.updated_at || "2026-06-02T00:00:00.000Z",
    ...overrides,
  };
}

describe("ChatAgentActionSummary", () => {
  it("explains when a completed turn has no artifacts", () => {
    render(<ChatAgentActionSummary actions={[]} tasks={[]} showEmpty />);

    expect(screen.getByRole("region", { name: "聊天整理结果" })).toBeInTheDocument();
    expect(screen.getByText("本轮没有创建任务、记忆、Wiki 页面或复盘报告。")).toBeInTheDocument();
  });

  it("renders actionable cards for task, memory, Wiki, and review artifacts", () => {
    const onOpenTask = vi.fn();
    const onOpenMemory = vi.fn();
    const onOpenWiki = vi.fn();
    const onOpenReport = vi.fn();

    render(
      <ChatAgentActionSummary
        actions={[
          action({
            action_id: "memory-write",
            action_type: "memory.long_term.write",
            title: "已保存偏好",
            summary: "已更新长期记忆。",
            target_paths: ["Memory/Preferences.md"],
          }),
          action({
            action_id: "review",
            action_type: "wiki.retrospective_report.write",
            title: "已生成今日复盘",
            summary: "已保存复盘报告。",
            target_paths: ["Wiki/Companion/Reports/2026-06-02-1d-review.md"],
          }),
        ]}
        tasks={[task({ remind_at: "2026-06-02T12:00:00Z", timezone_label: "Asia/Shanghai" })]}
        memoryProposals={[memoryProposal()]}
        wikiProposals={[wikiProposal()]}
        onOpenTask={onOpenTask}
        onOpenMemory={onOpenMemory}
        onOpenWiki={onOpenWiki}
        onOpenReport={onOpenReport}
      />,
    );

    expect(screen.getByText("已创建任务")).toBeInTheDocument();
    expect(screen.getByText("已写入记忆")).toBeInTheDocument();
    expect(screen.getByText("记忆待确认")).toBeInTheDocument();
    expect(screen.getByText("Wiki 页面待确认")).toBeInTheDocument();
    expect(screen.getByText("已生成复盘")).toBeInTheDocument();
    expect(screen.getByText("自动整理活动")).toBeInTheDocument();
    expect(screen.getByText("3 个结果支持区域")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "打开任务" }));
    fireEvent.click(screen.getAllByRole("button", { name: "打开记忆" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "打开 Wiki 页面" }));
    fireEvent.click(screen.getByRole("button", { name: "打开报告" }));

    expect(onOpenTask).toHaveBeenCalledWith(expect.objectContaining({ task_id: "task-1" }));
    expect(onOpenMemory).toHaveBeenCalledTimes(1);
    expect(onOpenWiki).toHaveBeenCalledWith("Wiki/Decision-Memory.md");
    expect(onOpenReport).toHaveBeenCalledWith("Wiki/Companion/Reports/2026-06-02-1d-review.md");
  });

  it("maps internal specialists to outcomes without selling agent count", () => {
    const { container } = render(
      <ChatAgentActionSummary
        actions={[
          action({
            action_id: "task-action",
            action_type: "task.create",
            title: "已创建提醒",
          }),
          action({
            action_id: "continuity-action",
            action_type: "continuity.relationship",
            title: "已更新关系信号",
          }),
        ]}
      />,
    );

    const teamActivity = container.querySelector(".ai-team-activity");

    expect(teamActivity).not.toHaveAttribute("open");
    expect(screen.getByText("自动整理活动")).toBeInTheDocument();
    expect(screen.getByText("任务")).toBeInTheDocument();
    expect(screen.getByText("连续性")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/9 agents|9 个智能体|9个智能体/);
  });

  it("keeps reversible markdown writes connected to the backend revert handler", () => {
    const onRevert = vi.fn();
    const reversible = action({
      action_id: "wiki",
      action_type: "wiki.answer_summary.write",
      title: "已保存 Wiki 摘要",
      target_paths: ["Wiki/A.md"],
      reversible: true,
    });

    render(<ChatAgentActionSummary actions={[reversible]} onRevertAgentAction={onRevert} />);

    fireEvent.click(screen.getByRole("button", { name: "撤销" }));

    expect(onRevert).toHaveBeenCalledWith(reversible);
  });
});
