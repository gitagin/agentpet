import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentAction, ChatWikiProposal, MemoryProposal, MemoryReceiptItem, TaskItem } from "../../types";
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
    summary: overrides.summary || "草拟资料页。",
    target_paths: overrides.target_paths || ["Wiki/Decision-Memory.md"],
    recommended_targets: overrides.recommended_targets || [],
    selected_targets: overrides.selected_targets || [],
    findings: overrides.findings || [],
    updated_at: overrides.updated_at || "2026-06-02T00:00:00.000Z",
    ...overrides,
  };
}

function receipt(overrides: Partial<MemoryReceiptItem> = {}): MemoryReceiptItem {
  return {
    id: overrides.id || "receipt-1",
    kind: overrides.kind || "remembered",
    title: overrides.title || "已记住一条偏好",
    detail: overrides.detail || "我会在以后回答时优先保持简洁。",
    safety_note: overrides.safety_note,
    action_label: overrides.action_label,
    related_memory_id: overrides.related_memory_id,
    created_at: overrides.created_at || "2026-06-02T00:00:00.000Z",
  };
}

describe("ChatAgentActionSummary", () => {
  it("explains when a completed turn has no artifacts", () => {
    render(<ChatAgentActionSummary actions={[]} tasks={[]} showEmpty />);

    expect(screen.getByRole("region", { name: "聊天整理结果" })).toBeInTheDocument();
    expect(screen.getByText("这轮没有产生新的记忆、任务或资料整理。")).toBeInTheDocument();
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
    expect(screen.getByText("已记住")).toBeInTheDocument();
    expect(screen.getAllByText("等你确认").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("已生成复盘")).toBeInTheDocument();
    expect(screen.getByText("整理明细")).toBeInTheDocument();
    expect(screen.getByText("3 类后台整理")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查看任务" }));
    fireEvent.click(screen.getAllByRole("button", { name: "查看记忆" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "查看资料页" }));
    fireEvent.click(screen.getByRole("button", { name: "查看报告" }));

    expect(onOpenTask).toHaveBeenCalledWith(expect.objectContaining({ task_id: "task-1" }));
    expect(onOpenMemory).toHaveBeenCalledTimes(1);
    expect(onOpenWiki).toHaveBeenCalledWith("Wiki/Decision-Memory.md");
    expect(onOpenReport).toHaveBeenCalledWith("Wiki/Companion/Reports/2026-06-02-1d-review.md");
  });

  it("shows skipped and failed work as plain receipts without internal terms", () => {
    const { container } = render(
      <ChatAgentActionSummary
        actions={[
          action({
            action_id: "skip",
            action_type: "chat.auto_memory.skip",
            status: "skipped",
            decision: "notify",
            title: "Skipped automatic organization",
            summary:
              "Skipped because automatic diary, structured memory, long-term memory, and Wiki organization are disabled; no local asset was written.",
            metadata: { skipped_reason: "automation_disabled" },
          }),
          action({
            action_id: "failed",
            action_type: "wiki.answer_summary.write",
            status: "failed",
            title: "Saved Wiki summary",
            summary: "Saved Wiki/A.md",
            error: "writer failed for Wiki/A.md",
            target_paths: ["Wiki/A.md"],
          }),
        ]}
        tasks={[task({ task_id: "failed-task", title: "交报告", status: "failed" })]}
      />,
    );

    expect(screen.getByText("这次我做了什么")).toBeInTheDocument();
    expect(screen.getByText("已安全跳过")).toBeInTheDocument();
    expect(screen.getByText("任务未创建")).toBeInTheDocument();
    expect(screen.getByText("这条任务没有创建成功，暂时不会提醒你。")).toBeInTheDocument();
    expect(screen.getByText("资料未保存")).toBeInTheDocument();
    expect(screen.getByText("这次整理没有完成，暂时没有保存新内容。")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/agent_actions|proposal|vault|FTS|sidecar|runtime|Wiki\/A\.md|Skipped|saveable|automation_disabled/i);
  });

  it("renders Chinese memory receipt items before raw action fallback", () => {
    const { container } = render(
      <ChatAgentActionSummary
        receipts={[receipt({ action_label: "查看详情" })]}
        actions={[
          action({
            action_id: "memory-action",
            action_type: "memory.long_term.write",
            title: "memory_candidates internal action",
            summary: "source_text should not render",
          }),
        ]}
      />,
    );

    expect(screen.getByText("已记住一条偏好")).toBeInTheDocument();
    expect(screen.getByText("我会在以后回答时优先保持简洁。")).toBeInTheDocument();
    expect(screen.getByText("本机记忆回执")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/memory_candidates|source_text|agent_run_id|lifecycle_status|vector|Authorization/i);
  });

  it("does not hide failed or pending memory actions when receipts only describe answer usage", () => {
    const { container } = render(
      <ChatAgentActionSummary
        receipts={[
          receipt({
            id: "mr_answer_context",
            kind: "used_for_answer",
            title: "本次回答参考了相关记忆",
            detail: "我只参考了已允许用于回答的记忆摘要。",
            related_memory_id: "mem_opaque",
          }),
        ]}
        actions={[
          action({
            action_id: "failed-memory",
            action_type: "memory.long_term.write",
            status: "failed",
            title: "偏好未保存",
            summary: "偏好未保存",
            error: "保存时遇到问题",
          }),
          action({
            action_id: "pending-memory",
            action_type: "memory.long_term.write",
            decision: "ask",
            status: "pending",
            title: "待确认偏好",
            summary: "等待确认后再保存",
          }),
        ]}
      />,
    );

    expect(screen.getByText("本次回答参考了相关记忆")).toBeInTheDocument();
    expect(screen.getByText("偏好未保存")).toBeInTheDocument();
    expect(screen.getByText("待确认偏好")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(
      /agent_run_id|memory_candidates|FTS|vector|lifecycle_status|source_text|source_excerpt|Authorization|receipt:used:run-secret|[A-Za-z]:\\/i,
    );
  });

  it("sanitizes incomplete receipt text and keeps the action fallback visible", () => {
    const { container } = render(
      <ChatAgentActionSummary
        receipts={[
          receipt({
            id: "receipt:used:run-secret",
            kind: "used_for_answer",
            title: "agent_run_id receipt:used:run-secret",
            detail: "source_text Authorization C:\\Users\\Alice\\Vault\\Secret.md",
            safety_note: "related_memory_id vector",
            related_memory_id: "memory_candidates:raw-id",
          }),
        ]}
        actions={[
          action({
            action_id: "memory-action",
            action_type: "memory.long_term.write",
            title: "正常记忆动作",
            summary: "已完成记忆整理",
          }),
        ]}
      />,
    );

    expect(screen.getByText("正常记忆动作")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(
      /agent_run_id|memory_candidates|FTS|vector|lifecycle_status|source_text|source_excerpt|Authorization|receipt:used:run-secret|C:\\Users\\Alice/i,
    );
  });

  it("falls back to existing action summary when receipts are unavailable", () => {
    render(
      <ChatAgentActionSummary
        actions={[
          action({
            action_id: "memory-action",
            action_type: "memory.long_term.write",
            title: "已保存偏好",
            summary: "已更新长期记忆。",
          }),
        ]}
      />,
    );

    expect(screen.getByText("已保存偏好")).toBeInTheDocument();
  });

  it("keeps pending memory explicit about not writing yet", () => {
    render(
      <ChatAgentActionSummary
        actions={[
          action({
            action_id: "pending-memory",
            action_type: "memory.long_term.write",
            decision: "ask",
            status: "pending",
            title: "Memory/Preferences.md",
            summary: "Write Memory/Preferences.md",
            target_paths: ["Memory/Preferences.md"],
          }),
        ]}
      />,
    );

    expect(screen.getByLabelText("等你确认: 长期记忆")).toBeInTheDocument();
    expect(screen.getByText("需要你确认后才会真正写入。")).toBeInTheDocument();
    expect(screen.getByText("未写入")).toBeInTheDocument();
    expect(screen.queryByText(/Memory\/Preferences\.md/)).not.toBeInTheDocument();
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
    expect(screen.getByText("整理明细")).toBeInTheDocument();
    expect(screen.getByText("任务")).toBeInTheDocument();
    expect(screen.getAllByText("陪伴状态").length).toBeGreaterThanOrEqual(1);
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

    expect(screen.getByText("可撤回")).toBeInTheDocument();
    expect(screen.queryByText("Wiki/A.md")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "撤回" }));

    expect(onRevert).toHaveBeenCalledWith(reversible);
  });
});
