import { createRef } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  options: { active?: boolean; ttsSpeaking?: boolean } = {},
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
      ttsSpeaking={options.ttsSpeaking}
      active={options.active}
    />,
  );
}

describe("StageView", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("shows five primary feature entries on the main stage", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    });

    const commandCenter = screen.getByLabelText("功能指挥中心");
    expect(commandCenter).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /新建任务/ })).toHaveAttribute("data-stage-route", "agent");
    expect(screen.getByRole("button", { name: /记住这件事/ })).toHaveAttribute("data-stage-route", "memory");
    expect(screen.getByRole("button", { name: /整理知识/ })).toHaveAttribute("data-stage-route", "world");
    expect(screen.getByRole("button", { name: /今日复盘/ })).toHaveAttribute("data-stage-route", "memory");
    expect(screen.getByRole("button", { name: /搜索记忆/ })).toHaveAttribute("data-stage-route", "memory");
    expect(screen.getByLabelText("聊天输入")).toBeInTheDocument();
  });

  it("opens concrete non-chat routes from stage feature entries", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    });

    fireEvent.click(screen.getByRole("button", { name: /新建任务/ }));
    expect(window.location.hash).toBe("#agent");

    fireEvent.click(screen.getByRole("button", { name: /记住这件事/ }));
    expect(window.location.hash).toBe("#memory");

    fireEvent.click(screen.getByRole("button", { name: /整理知识/ }));
    expect(window.location.hash).toBe("#world");
  });

  it("keeps primary workflow entries separate from the chat composer", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    });

    const commandCenter = screen.getByLabelText("功能指挥中心");
    const actionButtons = within(commandCenter).getAllByRole("button");

    expect(actionButtons).toHaveLength(5);
    actionButtons.forEach((button) => {
      expect(button).toHaveAttribute("data-stage-route");
      expect(button).not.toHaveAttribute("data-stage-route", "chat");
    });
    expect(within(commandCenter).queryByLabelText("聊天输入")).not.toBeInTheDocument();
    expect(screen.getByLabelText("舞台聊天表单")).toBeInTheDocument();
  });

  it("uses the shared pet bubble presentation for paged replies", () => {
    const { container } = renderStageView({
      visible: true,
      title: "",
      message: "分页舞台回复",
      tone: "reply",
      phase: "complete",
      continueHint: "1/3",
      canPageBackward: false,
      canPageForward: true,
    });

    const live2dZone = container.querySelector(".stage-live2d-zone");
    const petAnchor = container.querySelector(".stage-pet-anchor");
    const stageBubble = container.querySelector(".stage-agent-bubble");

    expect(stageBubble).toHaveClass("pet-agent-bubble", "no-header");
    expect(live2dZone).toContainElement(stageBubble as HTMLElement);
    expect(petAnchor).toContainElement(stageBubble as HTMLElement);
    expect(container.querySelector(".stage-bubble")).not.toBeInTheDocument();
    expect(screen.queryByText("1/3")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "上一页回复" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下一页回复" })).not.toBeInTheDocument();
    expect(screen.getByText("分页舞台回复")).toBeInTheDocument();
  });

  it("does not render a manual TTS stop control in the stage footer", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    }, { ttsSpeaking: true });

    expect(screen.queryByRole("button", { name: "停止朗读" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "语音未播放" })).not.toBeInTheDocument();
  });

  it("passes active TTS playback state to the Live2D stage", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    }, { ttsSpeaking: true });

    expect(screen.getByLabelText("mock live2d stage")).toHaveAttribute("data-speaking", "true");
  });

  it("does not move the Live2D mouth while TTS is only synthesizing", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    }, { ttsSpeaking: false });

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
