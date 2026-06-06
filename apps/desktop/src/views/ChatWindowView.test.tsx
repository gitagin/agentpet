import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "../types";
import ChatWindowView from "./ChatWindowView";

const onboardingPanel = (
  <section aria-label="首次使用引导">
    <p>首次引导表单</p>
  </section>
);

function renderChatWindow({
  messages = [],
  hasVaultInitialized = false,
}: {
  messages?: ChatMessage[];
  hasVaultInitialized?: boolean;
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
      onboardingPanel={onboardingPanel}
      hasVaultInitialized={hasVaultInitialized}
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

    expect(screen.getByRole("tab", { name: "切换到新任务模式" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "创建明天的提醒" }));
    expect(onModeChange).toHaveBeenCalledWith("task");
    expect(onInputChange).toHaveBeenCalledWith("请在明天上午 9:00 提醒我检查发布清单。");

    fireEvent.click(screen.getByRole("button", { name: "保存一个偏好" }));
    expect(onModeChange).toHaveBeenCalledWith("note");
    expect(onInputChange).toHaveBeenCalledWith("请记住我偏好简洁的发布清单。");

    fireEvent.click(screen.getByRole("tab", { name: "切换到今日复盘模式" }));
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
    expect(screen.getByRole("button", { name: "复盘" })).not.toBeDisabled();
  });

  it("keeps first-use onboarding first for a blank uninitialized chat", () => {
    const { container } = renderChatWindow();

    const onboarding = screen.getByLabelText("首次使用引导");
    const form = container.querySelector(".chat-form");

    expect(form).toBeTruthy();
    expect(appearsBefore(onboarding, form as Element)).toBe(true);
    expect(screen.queryByText("补充首次偏好")).not.toBeInTheDocument();
  });

  it("moves onboarding behind the recent conversation when chat history exists", () => {
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
    const onboarding = screen.getByLabelText("首次使用引导");
    const drawer = screen.getByText("补充首次偏好").closest("details");

    expect(form).toBeTruthy();
    expect(drawer).toBeTruthy();
    expect(drawer).not.toHaveAttribute("open");
    expect(appearsBefore(form as Element, message)).toBe(true);
    expect(appearsBefore(message, onboarding)).toBe(true);
  });

  it("deemphasizes onboarding when an active vault already exists", () => {
    const { container } = renderChatWindow({ hasVaultInitialized: true });

    const form = container.querySelector(".chat-form");
    const onboarding = screen.getByLabelText("首次使用引导");

    expect(form).toBeTruthy();
    expect(appearsBefore(form as Element, onboarding)).toBe(true);
    expect(screen.getByText("补充首次偏好")).toBeInTheDocument();
    expect(screen.getByText("还没有对话。可以直接和桌宠聊一句，之后这里会显示最近聊天。")).toBeInTheDocument();
    expect(screen.queryByText(/先绑定 Obsidian\/Markdown 资料库/)).not.toBeInTheDocument();
  });
});
