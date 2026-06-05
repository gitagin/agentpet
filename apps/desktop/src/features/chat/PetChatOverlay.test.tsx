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
  ttsActive = false,
  onStopTts = vi.fn(),
}: {
  bubble?: PetBubbleState;
  mode?: PetInputMode;
  input?: string;
  inputVisible?: boolean;
  connected?: boolean;
  streaming?: boolean;
  ttsActive?: boolean;
  onStopTts?: () => void;
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
      onPreviousPage={vi.fn()}
      onAdvancePage={vi.fn()}
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
      ttsActive={ttsActive}
      onStopTts={onStopTts}
    />,
  );

  return { ...view, onModeChange, onSubmit, onStopTts };
}

describe("PetChatOverlay", () => {
  it("renders compact mode tabs and emits mode changes", () => {
    const { onModeChange } = renderOverlay();

    expect(screen.getByRole("tablist", { name: "桌宠输入模式" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "切换到新任务模式" }));

    expect(onModeChange).toHaveBeenCalledWith("task");
  });

  it("uses the active mode placeholder and permits empty today review submission", () => {
    const { onSubmit } = renderOverlay({ mode: "review" });

    expect(screen.getByPlaceholderText("留空可直接复盘今天...")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "发送今日复盘请求" }));

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

  it("keeps compact page metadata for paged reply bubbles", () => {
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
    });

    expect(container.querySelector(".pet-agent-bubble")).toHaveClass("has-pagination");
    expect(screen.getByText("1/3")).toBeInTheDocument();
  });

  it("shows a lightweight stop button while a reply bubble is being read", () => {
    const onStopTts = vi.fn();
    const { container } = renderOverlay({
      bubble: {
        visible: true,
        title: "",
        message: "A reply is being spoken.",
        tone: "reply",
        phase: "complete",
      },
      inputVisible: false,
      ttsActive: true,
      onStopTts,
    });

    expect(container.querySelector(".pet-agent-bubble")).toHaveClass("has-header");
    const stopButton = container.querySelector(".pet-agent-bubble-stop-button");
    expect(stopButton).toBeInTheDocument();
    fireEvent.click(stopButton!);

    expect(onStopTts).toHaveBeenCalledTimes(1);
  });
});
