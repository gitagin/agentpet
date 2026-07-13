import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentCheckpointSummary, ChatMessage } from "../types";
import ChatWindowView, { chatTrialPrompts } from "./ChatWindowView";

function renderChatWindow({
  messages = [],
}: {
  messages?: ChatMessage[];
} = {}) {
  return render(
    <ChatWindowView
      input=""
      messages={messages}
      connected
      streaming={false}
      onInputChange={vi.fn()}
      onSend={vi.fn()}
      onStopStreaming={vi.fn()}
    />,
  );
}

function appearsBefore(first: Element, second: Element) {
  return Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe("ChatWindowView", () => {
  it("exposes one natural-language composer and only the two golden demo prompts", () => {
    const onInputChange = vi.fn();
    const onSend = vi.fn((event) => event.preventDefault());
    const { container } = render(
      <ChatWindowView
        input=""
        messages={[]}
        connected
        streaming={false}
        onInputChange={onInputChange}
        onSend={onSend}
        onStopStreaming={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "聊天" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "聊天输入" })).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /查找带来源的记忆|创建提醒并记住偏好/ })).toHaveLength(2);

    chatTrialPrompts.forEach((trial) => {
      fireEvent.click(screen.getByRole("button", { name: trial.label }));
      expect(onInputChange).toHaveBeenCalledWith(trial.text);
    });

    fireEvent.submit(container.querySelector(".chat-form") as HTMLFormElement);

    expect(onSend).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  });

  it("keeps first-use onboarding out of the chat window", () => {
    const { container } = renderChatWindow();

    const form = container.querySelector(".chat-form");

    expect(form).toBeTruthy();
    expect(screen.queryByLabelText("首次使用引导")).not.toBeInTheDocument();
    expect(screen.queryByText("补充首次偏好")).not.toBeInTheDocument();
  });

  it("focuses the composer when the companion chat opens", () => {
    const { container } = renderChatWindow();

    expect(container.querySelector(".chat-form input")).toHaveFocus();
  });

  it("removes supplemental onboarding when chat history exists", () => {
    const messages: ChatMessage[] = [
      {
        id: "message-1",
        role: "user",
        content: "今天先简单打个招呼。",
        status: "completed",
      },
    ];
    const { container } = renderChatWindow({ messages });

    const form = container.querySelector(".chat-form");
    const message = screen.getByText("今天先简单打个招呼。");

    expect(form).toBeTruthy();
    expect(appearsBefore(message, form as Element)).toBe(true);
    expect(screen.queryByLabelText("首次使用引导")).not.toBeInTheDocument();
    expect(screen.queryByText("补充首次偏好")).not.toBeInTheDocument();
  });

  it("keeps a blank chat focused on the transcript and composer", () => {
    const { container } = renderChatWindow();

    const form = container.querySelector(".chat-form");

    expect(form).toBeTruthy();
    expect(screen.queryByLabelText("首次使用引导")).not.toBeInTheDocument();
    expect(screen.queryByText("补充首次偏好")).not.toBeInTheDocument();
    expect(screen.getByText("还没有对话。可以直接和桌宠聊一句，之后这里会显示最近聊天。")).toBeInTheDocument();
  });

  it("shows only safe checkpoint details and emits explicit decisions", () => {
    const onDecideCheckpoint = vi.fn();
    const checkpoint: AgentCheckpointSummary = {
      checkpoint_id: "checkpoint-1",
      thread_id: "thread-1",
      run_id: "run-1",
      node_name: "action_agent",
      status: "pending_confirmation",
      action_proposal_id: "proposal-1",
      public_event_cursor: null,
      created_at: "2026-07-12T00:00:00Z",
      updated_at: "2026-07-12T00:00:00Z",
      expires_at: "2026-07-13T00:00:00Z",
      decision_id: "private-decision-id",
      decision_expires_at: "2026-07-12T00:15:00Z",
      action_label: "markdown.bulk_rewrite",
      safe_target_summary: "Wiki/Plan.md",
      risk_tier: "high",
      reversible: false,
    };

    render(
      <ChatWindowView
        input=""
        messages={[]}
        connected
        streaming={false}
        onInputChange={vi.fn()}
        onSend={vi.fn()}
        onStopStreaming={vi.fn()}
        pendingCheckpoints={[checkpoint]}
        decidingCheckpointIds={new Set()}
        onDecideCheckpoint={onDecideCheckpoint}
      />,
    );

    expect(screen.getByRole("region", { name: "待确认的高风险操作" })).toHaveTextContent("Wiki/Plan.md");
    expect(screen.queryByText("private-decision-id")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "批准" }));
    fireEvent.click(screen.getByRole("button", { name: "拒绝" }));
    expect(onDecideCheckpoint).toHaveBeenNthCalledWith(1, checkpoint, "approved");
    expect(onDecideCheckpoint).toHaveBeenNthCalledWith(2, checkpoint, "rejected");
  });
});
