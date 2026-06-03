import { createRef } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import StageView from "./StageView";
import type { PetBubbleState } from "../features/chat/chatTypes";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "../services/live2dRuntime";
import type { Live2DStageView } from "../components/Live2DStage";

vi.mock("../components/Live2DStage", () => ({
  Live2DStage: () => <section aria-label="mock live2d stage" />,
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

function renderStageView(bubble: PetBubbleState) {
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
    />,
  );
}

describe("StageView", () => {
  it("keeps page metadata but hides the automatic paging implementation hint", () => {
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

    expect(container.querySelector(".stage-bubble")).toHaveClass("stage-bubble--paged");
    expect(screen.getByText("1/3")).toBeInTheDocument();
    expect(screen.getByText(/像说话一样自动翻页/)).not.toBeVisible();
  });
});
