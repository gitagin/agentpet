import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import StageView from "./StageView";
import type { PetBubbleState } from "../features/chat/chatTypes";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "../services/live2dRuntime";
import type { Live2DStageView } from "../components/Live2DStage";

vi.mock("../components/Live2DStage", () => ({
  Live2DStage: ({ active = true, speaking = false }: { active?: boolean; speaking?: boolean }) => (
    <section
      aria-label="mock live2d stage"
      data-active={active ? "true" : "false"}
      data-speaking={speaking ? "true" : "false"}
    />
  ),
}));

vi.mock("./BottomNav", () => ({
  BottomNav: () => <nav aria-label="mock bottom nav" />,
}));

const live2dStage: Live2DStageView = {
  state: "idle",
  label: "idle",
  mood: "calm",
  message: "ready",
  hint: "ready",
};

const live2dRuntime: Live2DRuntimeBoundary = {
  status: "assets-ready",
  title: "ready",
  detail: "ready",
  mountTargetId: "test-live2d-canvas",
  rendererName: "test",
  canMountRenderer: false,
};

const live2dAsset: Live2DAssetInfo = {
  status: "recognized",
  modelId: "test-model",
  modelLabel: "Test Model",
  modelDirectoryUrl: "/live2d/test/",
  modelFileName: "test.model3.json",
  manifestPath: "/live2d/test/test.model3.json",
  iconPath: "/live2d/test/icon.png",
  hasIcon: false,
  textureCount: 0,
  expressionCount: 0,
  motionCount: 0,
  hasPhysics: false,
  hasDisplayInfo: false,
};

function renderStageView(
  bubble: PetBubbleState,
  options: { active?: boolean; ttsActive?: boolean; ttsSpeaking?: boolean; onStopTts?: () => void } = {},
) {
  return render(
    <StageView
      live2dStage={live2dStage}
      live2dAsset={live2dAsset}
      live2dRuntime={live2dRuntime}
      live2dCanvasRef={createRef<HTMLCanvasElement>()}
      connected
      streaming={false}
      bubble={bubble}
      onSendChat={vi.fn()}
      onPreviousPage={vi.fn()}
      onAdvancePage={vi.fn()}
      onPausePaging={vi.fn()}
      onResumePaging={vi.fn()}
      ttsActive={options.ttsActive}
      ttsSpeaking={options.ttsSpeaking}
      onStopTts={options.onStopTts}
      active={options.active}
    />,
  );
}

describe("StageView", () => {
  it("uses the shared pet bubble presentation for paged replies", () => {
    const { container } = renderStageView({
      visible: true,
      title: "",
      message: "Paged stage reply",
      tone: "reply",
      phase: "complete",
      continueHint: "1/3",
      canPageBackward: false,
      canPageForward: true,
    });

    expect(container.querySelector(".stage-agent-bubble")).toHaveClass("pet-agent-bubble", "has-pagination");
    expect(container.querySelector(".stage-bubble")).not.toBeInTheDocument();
    expect(screen.getByText("1/3")).toBeInTheDocument();
  });

  it("lets users stop active TTS playback from the stage footer", () => {
    const onStopTts = vi.fn();
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    }, { ttsActive: true, onStopTts });

    fireEvent.click(screen.getByRole("button", { name: "停止朗读" }));

    expect(onStopTts).toHaveBeenCalledTimes(1);
  });

  it("passes active TTS playback state to the Live2D stage", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    }, { ttsActive: true, ttsSpeaking: true });

    expect(screen.getByLabelText("mock live2d stage")).toHaveAttribute("data-speaking", "true");
  });

  it("does not move the Live2D mouth while TTS is only synthesizing", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    }, { ttsActive: true, ttsSpeaking: false });

    expect(screen.getByLabelText("mock live2d stage")).toHaveAttribute("data-speaking", "false");
  });

  it("passes inactive route state down to the Live2D stage", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    }, { active: false });

    expect(screen.getByLabelText("mock live2d stage")).toHaveAttribute("data-active", "false");
  });
});
