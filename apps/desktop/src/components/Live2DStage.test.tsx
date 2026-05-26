import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../services/live2dRuntime", () => ({
  createRendererMountContext: vi.fn(() => ({})),
  mountLive2DRendererBoundary: vi.fn(),
}));

import { Live2DStage, getLive2DAssetStatusText } from "./Live2DStage";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "../services/live2dRuntime";

const stage = {
  state: "idle" as const,
  label: "待命陪伴",
  mood: "安静待命",
  message: "我在这里陪你整理记忆。",
  hint: "双击可以开始对话",
};

const asset: Live2DAssetInfo = {
  status: "recognized",
  modelId: "UG",
  modelLabel: "UG",
  modelDirectoryUrl: "/live2d/UG/",
  modelFileName: "ugofficial.model3.json",
  manifestPath: "/live2d/UG/ugofficial.model3.json",
  iconPath: "/live2d/UG/icon.png",
  hasIcon: true,
  version: 3,
  moc: "ugofficial.moc3",
  textureCount: 2,
  expressionCount: 4,
  motionCount: 6,
  defaultMotionGroup: "Idle",
  defaultMotionIndex: 0,
  hasPhysics: true,
  hasDisplayInfo: true,
};

const runtime: Live2DRuntimeBoundary = {
  status: "assets-ready",
  title: "资源已就绪",
  detail: "测试环境不挂载真实 Cubism runtime。",
  mountTargetId: "live2d-runtime-canvas",
  rendererName: "Cubism WebGL",
  canMountRenderer: false,
};

function renderStage(variant: "panel" | "pet" = "panel", petInteractions?: Parameters<typeof Live2DStage>[0]["petInteractions"]) {
  return render(
    <Live2DStage
      stage={stage}
      asset={asset}
      runtime={runtime}
      canvasRef={createRef<HTMLCanvasElement>()}
      variant={variant}
      petInteractions={petInteractions}
    />,
  );
}

describe("Live2DStage", () => {
  it("renders the panel model status without mounting the renderer", () => {
    renderStage();

    expect(screen.getByLabelText("桌宠模型展示区")).toBeInTheDocument();
    expect(screen.getByText("待命陪伴")).toBeInTheDocument();
    expect(screen.getByText("模型资源已识别")).toBeInTheDocument();
    expect(screen.getByLabelText("Live2D runtime 边界状态")).toBeInTheDocument();
    expect(screen.getByLabelText("模型资源状态")).toHaveTextContent("ugofficial.model3.json");
    expect(screen.getByAltText("UG 桌宠模型资源封面")).toBeInTheDocument();
  });

  it("renders the pet shell fallback and forwards pointer interactions", () => {
    const petInteractions = {
      onPointerDown: vi.fn(),
      onPointerMove: vi.fn(),
      onPointerUp: vi.fn(),
      onPointerCancel: vi.fn(),
      onLostPointerCapture: vi.fn(),
      onContextMenu: vi.fn(),
      onDoubleClick: vi.fn(),
    };

    renderStage("pet", petInteractions);

    const hitRegion = screen.getByLabelText("桌宠模型交互区");
    expect(screen.getByLabelText("桌宠模型")).toBeInTheDocument();
    expect(screen.getByLabelText("桌宠模型状态：待命陪伴")).toBeInTheDocument();
    expect(screen.getByLabelText("Live2D runtime canvas 宿主区域")).toBeInTheDocument();
    expect(screen.getByLabelText("Live2D 静态回退封面")).toBeInTheDocument();

    fireEvent.pointerDown(hitRegion);
    fireEvent.pointerMove(hitRegion);
    fireEvent.pointerUp(hitRegion);
    fireEvent.pointerCancel(hitRegion);
    fireEvent.lostPointerCapture(hitRegion);
    fireEvent.contextMenu(hitRegion);
    fireEvent.doubleClick(hitRegion);

    expect(petInteractions.onPointerDown).toHaveBeenCalledTimes(1);
    expect(petInteractions.onPointerMove).toHaveBeenCalledTimes(1);
    expect(petInteractions.onPointerUp).toHaveBeenCalledTimes(1);
    expect(petInteractions.onPointerCancel).toHaveBeenCalledTimes(1);
    expect(petInteractions.onLostPointerCapture).toHaveBeenCalledTimes(1);
    expect(petInteractions.onContextMenu).toHaveBeenCalledTimes(1);
    expect(petInteractions.onDoubleClick).toHaveBeenCalledTimes(1);
  });

  it("describes missing assets with the manifest path", () => {
    expect(
      getLive2DAssetStatusText({
        ...asset,
        status: "missing",
        manifestPath: "/missing/model3.json",
      }).detail,
    ).toContain("/missing/model3.json");
  });
});
