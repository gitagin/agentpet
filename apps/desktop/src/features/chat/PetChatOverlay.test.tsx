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
  mode = "chat",
  input = "",
  connected = true,
}: {
  mode?: PetInputMode;
  input?: string;
  connected?: boolean;
} = {}) {
  const onModeChange = vi.fn();
  const onSubmit = vi.fn();

  render(
    <PetChatOverlay
      bubble={hiddenBubble}
      input={input}
      inputVisible
      inputRef={createRef<HTMLInputElement>()}
      mode={mode}
      modes={petInputModes}
      connected={connected}
      streaming={false}
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
    />,
  );

  return { onModeChange, onSubmit };
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
});
