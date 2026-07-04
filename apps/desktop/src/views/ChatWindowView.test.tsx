import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "../types";
import ChatWindowView, { demoMemoryTrialPrompt } from "./ChatWindowView";

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
  it("exposes focused actions and allows an empty daily review", () => {
    const onModeChange = vi.fn();
    const onInputChange = vi.fn();
    const onSend = vi.fn((event) => event.preventDefault());
    const { container, rerender } = render(
      <ChatWindowView
        input=""
        messages={[]}
        connected
        streaming={false}
        mode="chat"
        onModeChange={onModeChange}
        onInputChange={onInputChange}
        onSend={onSend}
        onStopStreaming={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "聊天" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "切换到陪伴" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "切换到记住" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "切换到提醒" })).toHaveClass("secondary");
    expect(screen.getByRole("tab", { name: "切换到整理资料" })).toHaveClass("secondary");

    fireEvent.click(screen.getByRole("button", { name: demoMemoryTrialPrompt.label }));
    expect(onModeChange).toHaveBeenCalledWith("note");
    expect(onInputChange).toHaveBeenCalledWith(demoMemoryTrialPrompt.text);

    fireEvent.click(screen.getByRole("button", { name: "明天提醒我继续这件事" }));
    expect(onModeChange).toHaveBeenCalledWith("task");
    expect(onInputChange).toHaveBeenCalledWith("明天提醒我继续这件事");

    fireEvent.click(screen.getByRole("button", { name: "记住我最近在准备一件重要的事" }));
    expect(onModeChange).toHaveBeenCalledWith("note");
    expect(onInputChange).toHaveBeenCalledWith("记住我最近在准备一件重要的事");

    fireEvent.click(screen.getByRole("tab", { name: "切换到回顾今天" }));
    expect(onModeChange).toHaveBeenCalledWith("review");

    rerender(
      <ChatWindowView
        input=""
        messages={[]}
        connected
        streaming={false}
        mode="review"
        onModeChange={onModeChange}
        onInputChange={vi.fn()}
        onSend={onSend}
        onStopStreaming={vi.fn()}
      />,
    );

    fireEvent.submit(container.querySelector(".chat-form") as HTMLFormElement);

    expect(onSend).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "回顾" })).not.toBeDisabled();
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
});
