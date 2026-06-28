import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PetChatOverlay } from "./PetChatOverlay";
import type { PetBubbleState } from "./chatTypes";
import { petInputModes, type PetInputMode } from "./petInputModes";

const hiddenBubble: PetBubbleState = {
  visible: false,
  title: "",
  message: "",
  tone: "thinking",
  phase: "idle",
};

function renderOverlay({
  bubble = hiddenBubble,
  mode = "chat",
  input = "",
  inputVisible = true,
  connected = true,
  streaming = false,
  onPreviousPage = vi.fn(),
  onAdvancePage = vi.fn(),
}: {
  bubble?: PetBubbleState;
  mode?: PetInputMode;
  input?: string;
  inputVisible?: boolean;
  connected?: boolean;
  streaming?: boolean;
  onPreviousPage?: () => void;
  onAdvancePage?: () => void;
} = {}) {
  const onModeChange = vi.fn();
  const onSubmit = vi.fn();

  const view = render(
    <PetChatOverlay
      bubble={bubble}
      input={input}
      inputVisible={inputVisible}
      inputRef={createRef<HTMLInputElement>()}
      mode={mode}
      modes={petInputModes}
      connected={connected}
      streaming={streaming}
      onPreviousPage={onPreviousPage}
      onAdvancePage={onAdvancePage}
      onPausePaging={vi.fn()}
      onResumePaging={vi.fn()}
      onInputChange={vi.fn()}
      onModeChange={onModeChange}
      onInputClose={vi.fn()}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      onStopStreaming={vi.fn()}
    />,
  );

  return { ...view, onModeChange, onSubmit, onPreviousPage, onAdvancePage };
}

describe("PetChatOverlay", () => {
  it("renders compact mode tabs and emits mode changes", () => {
    const { onModeChange } = renderOverlay();

    expect(screen.getByRole("tablist", { name: "桌宠输入模式" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "切换到提醒" }));

    expect(onModeChange).toHaveBeenCalledWith("task");
  });

  it("uses the active mode placeholder and permits empty today review submission", () => {
    const { onSubmit } = renderOverlay({ mode: "review" });

    expect(screen.getByPlaceholderText("留空也可以直接回顾今天...")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "发送今日回顾请求" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("keeps empty non-review messages disabled", () => {
    renderOverlay({ mode: "task" });

    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
  });

  it("does not reserve an empty header for titleless reply bubbles", () => {
    const { container } = renderOverlay({
      bubble: {
        visible: true,
        title: "",
        message: "A short reply should use the full bubble body.",
        tone: "reply",
        phase: "complete",
      },
      inputVisible: false,
    });

    expect(container.querySelector(".pet-agent-bubble")).toHaveClass("no-header");
    expect(container.querySelector(".pet-agent-bubble-header")).not.toBeInTheDocument();
    expect(screen.getByText("A short reply should use the full bubble body.")).toBeInTheDocument();
  });

  it("keeps paged reply bubbles focused on reply text", () => {
    const onAdvancePage = vi.fn();
    const { container } = renderOverlay({
      bubble: {
        visible: true,
        title: "",
        message: "A paged reply keeps controls compact.",
        tone: "reply",
        phase: "complete",
        continueHint: "1/3",
        canPageBackward: false,
        canPageForward: true,
      },
      inputVisible: false,
      onAdvancePage,
    });

    expect(container.querySelector(".pet-agent-bubble")).toHaveClass("no-header");
    expect(container.querySelector(".pet-agent-bubble-header")).not.toBeInTheDocument();
    expect(screen.queryByText("1/3")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "上一页回复" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下一页回复" })).not.toBeInTheDocument();
    expect(screen.getByText("A paged reply keeps controls compact.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("A paged reply keeps controls compact."));
    expect(onAdvancePage).toHaveBeenCalledTimes(1);
  });

  it("does not render a manual TTS stop control in reply bubbles", () => {
    const { container } = renderOverlay({
      bubble: {
        visible: true,
        title: "",
        message: "A reply is being spoken.",
        tone: "reply",
        phase: "complete",
      },
      inputVisible: false,
    });

    expect(container.querySelector(".pet-agent-bubble")).toHaveClass("no-header");
    expect(container.querySelector(".pet-agent-bubble-stop-button")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "停止朗读" })).not.toBeInTheDocument();
    expect(screen.getByText("A reply is being spoken.")).toBeInTheDocument();
  });
});
