import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentAction, ChatMessage, ChatNegotiationStep } from "../../types";
import { ChatMessageList } from "./ChatMessageList";

function action(overrides: Partial<AgentAction>): AgentAction {
  return {
    action_id: overrides.action_id || "action-1",
    action_type: overrides.action_type || "wiki.answer_summary.write",
    risk_tier: overrides.risk_tier || "low",
    decision: overrides.decision || "auto",
    status: overrides.status || "completed",
    title: overrides.title || "Saved Wiki summary",
    summary: overrides.summary || "Saved Wiki/A.md",
    target_paths: overrides.target_paths || ["Wiki/A.md"],
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

describe("ChatMessageList", () => {
  it("marks the list state so short chats can sit at the bottom", () => {
    const { container, rerender } = render(<ChatMessageList messages={[]} />);

    expect(container.querySelector(".message-list")).toHaveClass("is-empty");

    rerender(
      <ChatMessageList
        messages={[
          {
            id: "user-1",
            role: "user",
            content: "hello",
            status: "completed",
          },
        ]}
      />,
    );

    expect(container.querySelector(".message-list")).toHaveClass("has-messages");
  });

  it("renders messages as chat rows with left and right bubbles", () => {
    const messages: ChatMessage[] = [
      {
        id: "user-1",
        role: "user",
        content: "今天有点累。",
        status: "completed",
      },
      {
        id: "assistant-1",
        role: "assistant",
        content: "先缓一下，我在。",
        status: "completed",
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} />);

    expect(container.querySelector("#message-user-1")).toBeInTheDocument();
    expect(container.querySelector("#message-assistant-1")).toBeInTheDocument();
    expect(container.querySelector(".message-row.user .message-bubble.user")).toHaveTextContent("今天有点累。");
    expect(container.querySelector(".message-row.assistant .message-bubble.assistant")).toHaveTextContent("先缓一下，我在。");
  });

  it("renders assistant Markdown as readable semantic structure", () => {
    const messages: ChatMessage[] = [
      {
        id: "assistant-markdown",
        role: "assistant",
        content: [
          "## 8 月 5 日",
          "",
          "* **旅行**：聊了夏季目的地",
          "  * *偏好*：更喜欢慢旅行",
          "* **称呼**：你希望我叫你测试员",
          "",
          "```ts",
          "const plan = {",
          '  city: "威海",',
          "};",
          "```",
          "",
          "[查看资料](https://example.com/memory_(daily))",
        ].join("\n"),
        status: "completed",
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} />);

    expect(screen.getByRole("heading", { level: 2, name: "8 月 5 日" })).toBeInTheDocument();
    expect(screen.getAllByRole("list")).toHaveLength(2);
    expect(screen.getByText("旅行").tagName).toBe("STRONG");
    expect(screen.getByText("偏好").tagName).toBe("EM");
    expect(screen.getByRole("link", { name: "查看资料" })).toHaveAttribute("target", "_blank");
    expect(container.querySelector("pre code")?.textContent).toContain('  city: "威海",');
    expect(container.querySelector(".message-content")).toBeInTheDocument();
  });

  it("does not interpret assistant raw HTML", () => {
    const messages: ChatMessage[] = [
      {
        id: "assistant-html",
        role: "assistant",
        content: "正常内容<script>window.alert('unsafe')</script>",
        status: "completed",
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} />);

    expect(container.querySelector("script")).not.toBeInTheDocument();
    expect(container.querySelector(".message-content")).toHaveTextContent("正常内容window.alert");
  });

  it("hides system messages and keeps assistant trace details collapsed", () => {
    const messages: ChatMessage[] = [
      {
        id: "system-1",
        role: "system",
        content: "内部系统提示",
        status: "completed",
      },
      {
        id: "assistant-1",
        role: "assistant",
        content: "这是直接回答。",
        status: "completed",
        retrieval_attempted: true,
        citations: [
          {
            relative_path: "Wiki/Test.md",
            snippet: "引用片段",
            source_scope: "knowledge_base",
            retrieval_mode: "fts",
          },
        ],
        events: [{ id: "event-1", label: "智能体状态", detail: "已检索 Wiki", tone: "info" }],
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} />);

    expect(screen.queryByText("内部系统提示")).not.toBeInTheDocument();
    expect(screen.getByText("这是直接回答。")).toBeInTheDocument();
    expect(screen.queryByText("助手")).not.toBeInTheDocument();
    expect(screen.getByText("来源与整理 · 1 条引用 / 1 条工具事件")).toBeInTheDocument();
    expect(container.querySelector(".message-trace")).not.toHaveAttribute("open");
  });

  it("renders generated artifact cards outside the collapsed trace", () => {
    const onOpenTask = vi.fn();
    const messages: ChatMessage[] = [
      {
        id: "assistant-1",
        role: "assistant",
        content: "完成。",
        status: "completed",
        retrieval_attempted: true,
        events: [{ id: "event-1", label: "工具轨迹", detail: "已创建任务", tone: "success" }],
        task_actions: [{ task_id: "task-1", title: "支付发票", status: "pending" }],
        agent_actions: [
          action({
            action_id: "review",
            action_type: "wiki.retrospective_report.write",
            title: "已生成复盘",
            target_paths: ["Wiki/Companion/Reports/2026-06-02-1d-review.md"],
          }),
        ],
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} onOpenTask={onOpenTask} />);
    const artifactSection = screen.getByRole("region", { name: "聊天整理结果" });
    const trace = container.querySelector(".message-trace");

    expect(within(artifactSection).getByLabelText("已创建任务: 支付发票")).toBeInTheDocument();
    expect(within(artifactSection).getByLabelText("已生成复盘: 已生成复盘")).toBeInTheDocument();
    expect(trace).not.toHaveAttribute("open");
    expect(trace).not.toContainElement(artifactSection);
  });

  it("shows concise progress cards while waiting for the first answer text", () => {
    const messages: ChatMessage[] = [
      {
        id: "assistant-1",
        role: "assistant",
        content: "",
        status: "partial",
        progress_stage: "verifying",
        retrieval_attempted: true,
        retrieval_scopes: ["personal_memory", "knowledge_base"],
        events: [{ id: "event-1", label: "智能体状态", detail: "retrieving memory", tone: "info" }],
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} />);
    const progress = screen.getByRole("region", { name: "聊天进度" });

    expect(screen.getByText("正在整理回答...")).toBeInTheDocument();
    expect(within(progress).getByText("理解问题")).toBeInTheDocument();
    expect(within(progress).getByText("查找本地记忆")).toBeInTheDocument();
    expect(within(progress).getByText("核验来源")).toBeInTheDocument();
    expect(within(progress).getByText("完成")).toBeInTheDocument();
    expect(within(progress).getByText("核验来源").closest(".message-agent-action-bucket")).toHaveClass("pending");
    expect(container.querySelector(".message-trace")).not.toHaveAttribute("open");
  });

  it("does not expose internal retrieval scope names in progress cards", () => {
    const messages: ChatMessage[] = [
      {
        id: "assistant-1",
        role: "assistant",
        content: "",
        status: "partial",
        retrieval_attempted: true,
        retrieval_scopes: ["vector", "FTS", "agent_run_id"],
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} />);

    expect(screen.getByText(/本地资料/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/vector|FTS|agent_run_id/i);
  });

  it("renders only allowlisted safe trace details even when legacy fields are present", () => {
    const traceStep = {
      contract_version: "agent-trace.v1",
      run_id: "run-safe-1",
      branch_id: "foreground",
      stage_id: "negotiation",
      agent_id: "retrieval_agent",
      phase: "invoking",
      status: "running",
      round: 1,
      sequence: 1,
      duration_ms: 0,
      reason_code: "additional_context_required",
      safe_summary: "需要补充本地证据，正在进行有界检索。",
      counts: { agents_invoked: 0, citations: 0, rounds: 0 },
      source_scope: "personal_memory",
      reasoning: "private-reasoning-output",
      message: "private-message-output",
      raw_prompt: "private-prompt-output",
      tool_arguments: "private-tool-output",
    } as unknown as ChatNegotiationStep;
    const messages: ChatMessage[] = [
      {
        id: "assistant-trace-safe",
        role: "assistant",
        content: "这是安全回答。",
        status: "completed",
        negotiation_steps: [traceStep],
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} />);

    expect(screen.getByText("需要补充本地证据，正在进行有界检索。")).toBeInTheDocument();
    expect(container.querySelector(".message-negotiation")).not.toHaveAttribute("open");
    expect(container.textContent).not.toMatch(
      /private-reasoning-output|private-message-output|private-prompt-output|private-tool-output/,
    );
  });

  it("keeps streamed answer text before progress details once tokens arrive", () => {
    const messages: ChatMessage[] = [
      {
        id: "assistant-1",
        role: "assistant",
        content: "先给你结论。",
        status: "partial",
        retrieval_attempted: true,
        retrieval_scopes: ["daily_chat"],
      },
    ];

    render(<ChatMessageList messages={messages} />);

    expect(screen.getByText("先给你结论。")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "聊天进度" })).not.toBeInTheDocument();
  });

  it("keeps ordinary parentheses in assistant Markdown", () => {
    const messages: ChatMessage[] = [
      {
        id: "assistant-1",
        role: "assistant",
        content: "这是一条说明（仅供参考）。",
        status: "completed",
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} />);

    expect(container.querySelector(".message-content")).toHaveTextContent("这是一条说明（仅供参考）。");
  });

  it("renders single-star Markdown emphasis", () => {
    const messages: ChatMessage[] = [
      {
        id: "assistant-1",
        role: "assistant",
        content: "这是 *斜体内容*，不应被动作过滤器删除。",
        status: "completed",
      },
    ];

    render(<ChatMessageList messages={messages} />);

    expect(screen.getByText("斜体内容").tagName).toBe("EM");
  });

  it("hides recognized pet action directives without changing surrounding Markdown", () => {
    const messages: ChatMessage[] = [
      {
        id: "assistant-1",
        role: "assistant",
        content: "(smile)你好（抱枕），这是 *斜体内容*。*smile*",
        status: "completed",
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} />);

    expect(container.querySelector(".message-content")).toHaveTextContent("你好，这是 斜体内容。");
    expect(screen.getByText("斜体内容").tagName).toBe("EM");
    expect(container.textContent).not.toMatch(/smile|抱枕/);
  });
});
