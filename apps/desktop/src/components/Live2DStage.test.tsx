import { createRef } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../services/live2dRuntime", () => ({
  createRendererMountContext: vi.fn(() => ({})),
  mountLive2DRendererBoundary: vi.fn(),
}));

import { Live2DStage, getLive2DAssetStatusText } from "./Live2DStage";
import { createRendererMountContext, mountLive2DRendererBoundary } from "../services/live2dRuntime";
import type { Live2DAssetInfo, Live2DRuntimeBoundary, Live2DRuntimeHandle } from "../services/live2dRuntime";

const stage = {
  state: "idle" as const,
  label: "待命陪伴",
  mood: "安静待命",
  message: "我在这里陪你整理记忆。",
  hint: "双击可以开始对话",
};

const asset: Live2DAssetInfo = {
  status: "recognized",
  modelId: "agent_pet_companion",
  modelLabel: "Archivist Companion",
  modelDirectoryUrl: "/live2d/agent_pet_companion/",
  modelFileName: "agent_pet_companion.model3.json",
  manifestPath: "/live2d/agent_pet_companion/agent_pet_companion.model3.json",
  iconPath: "/live2d/agent_pet_companion/preview.svg",
  hasIcon: true,
  version: 3,
  moc: "agent_pet_companion.moc3",
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

const createRendererMountContextMock = vi.mocked(createRendererMountContext);
const mountLive2DRendererBoundaryMock = vi.mocked(mountLive2DRendererBoundary);

function createMountedRuntimeHandle(overrides: Partial<Live2DRuntimeHandle> = {}): Live2DRuntimeHandle {
  return {
    start: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
    setExpression: vi.fn(),
    startMotion: vi.fn(),
    getRenderMode: vi.fn(() => "official"),
    getDiagnostics: vi.fn(() => ({
      renderMode: "official",
      idleMotionEnabled: true,
      eyeBlinkEnabled: true,
      breathEnabled: true,
      physicsEnabled: true,
      motionCount: asset.motionCount,
      expressionCount: asset.expressionCount,
      textureCount: asset.textureCount,
      shaderReady: true,
      currentMotion: null,
      currentExpression: null,
      visiblePixels: true,
    })),
    hasVisiblePixels: vi.fn(() => true),
    isPointOnVisiblePixel: vi.fn(() => true),
    cleanup: vi.fn(),
    destroy: vi.fn(),
    unmount: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  createRendererMountContextMock.mockReset();
  createRendererMountContextMock.mockImplementation((canvas, assetInfo, variant) => {
    if (!canvas || assetInfo.status !== "recognized") {
      return null;
    }
    return { canvas, asset: assetInfo, variant };
  });
  mountLive2DRendererBoundaryMock.mockReset();
  window.devicePixelRatio = 1;
});

function renderStage(
  variant: "panel" | "pet" | "stage" = "panel",
  petInteractions?: Parameters<typeof Live2DStage>[0]["petInteractions"],
  speaking = false,
  actionKeyOverride?: string | null,
) {
  return render(
    <Live2DStage
      stage={stage}
      asset={asset}
      runtime={runtime}
      canvasRef={createRef<HTMLCanvasElement>()}
      variant={variant}
      petInteractions={petInteractions}
      speaking={speaking}
      actionKeyOverride={actionKeyOverride}
    />,
  );
}

describe("Live2DStage", () => {
  it("renders the panel model status without mounting the renderer", () => {
    renderStage();

    expect(screen.getByLabelText("桌宠模型展示区")).toBeInTheDocument();
    expect(screen.getByText("待命陪伴")).toBeInTheDocument();
    expect(screen.getByText("模型资源已识别")).toBeInTheDocument();
    expect(screen.getByLabelText("模型运行时边界状态")).toBeInTheDocument();
    expect(screen.getByLabelText("模型资源状态")).toHaveTextContent("agent_pet_companion.model3.json");
    expect(screen.getByAltText("Archivist Companion 桌宠模型资源封面")).toBeInTheDocument();
  });

  it("renders the pet shell fallback and forwards pointer interactions", () => {
    const petInteractions = {
      onPointerDown: vi.fn(),
      onPointerMove: vi.fn(),
      onPointerUp: vi.fn(),
      onPointerCancel: vi.fn(),
      onLostPointerCapture: vi.fn(),
      onContextMenu: vi.fn(),
      onBubbleContextMenu: vi.fn(),
      onDoubleClick: vi.fn(),
    };

    renderStage("pet", petInteractions);

    const hitRegion = screen.getByLabelText("桌宠模型交互区");
    expect(screen.getByLabelText("桌宠模型")).toBeInTheDocument();
    expect(screen.getByLabelText("桌宠模型状态：待命陪伴")).toBeInTheDocument();
    expect(screen.getByLabelText("桌宠模型运行时画布区域")).toBeInTheDocument();
    expect(screen.getByLabelText("桌宠模型静态回退封面")).toBeInTheDocument();

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

  it("renders the stage model without the control diagnostics lists", () => {
    renderStage("stage");

    expect(screen.getByLabelText("陪伴模型")).toBeInTheDocument();
    expect(screen.getByLabelText("陪伴模型状态：待命陪伴")).toBeInTheDocument();
    expect(screen.getByLabelText("桌宠模型运行时画布区域")).toBeInTheDocument();
    expect(screen.queryByLabelText("模型运行时边界状态")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("模型运行时诊断摘要")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("模型资源状态")).not.toBeInTheDocument();
  });

  it("marks the stage as speaking while TTS playback is active", () => {
    renderStage("stage", undefined, true);

    const shell = screen.getByLabelText("陪伴模型");
    const stageView = screen.getByLabelText("陪伴模型状态：待命陪伴");

    expect(shell).toHaveClass("live2d-speaking");
    expect(shell).toHaveAttribute("data-live2d-speaking", "true");
    expect(shell).toHaveAttribute("data-live2d-action-key", "tts_speaking");
    expect(stageView).toHaveAttribute("data-live2d-speaking", "true");
  });

  it("lets a reply-driven action override the generic speaking action", async () => {
    const mountedRuntime: Live2DRuntimeBoundary = {
      ...runtime,
      canMountRenderer: true,
    };
    const setExpression = vi.fn();
    const startMotion = vi.fn();
    const handle = createMountedRuntimeHandle({ setExpression, startMotion });
    const expressiveAsset: Live2DAssetInfo = {
      ...asset,
      expressions: ["comfort", "mic"],
      motions: [
        { group: "Continuity", index: 1 },
        { group: "Reaction", index: 0 },
      ],
      actionProfile: {
        actions: {
          emotion_comfort: {
            expression: "comfort",
            motion: { group: "Continuity", index: 1 },
            petHint: "comfort",
            controlSummary: "comfort",
          },
          tts_speaking: {
            expression: "mic",
            motion: { group: "Reaction", index: 0 },
            petHint: "speaking",
            controlSummary: "speaking",
          },
        },
      },
    };
    mountLive2DRendererBoundaryMock.mockResolvedValueOnce({
      status: "mounted",
      renderMode: "official",
      message: "mounted",
      diagnostics: handle.getDiagnostics(),
      handle,
    });

    render(
      <Live2DStage
        stage={stage}
        asset={expressiveAsset}
        runtime={mountedRuntime}
        canvasRef={createRef<HTMLCanvasElement>()}
        variant="stage"
        speaking
        actionKeyOverride="emotion_comfort"
      />,
    );

    const shell = document.querySelector(".live2d-panel-stage");
    expect(shell).toBeInTheDocument();
    expect(shell).toHaveAttribute("data-live2d-action-key", "emotion_comfort");
    await waitFor(() => expect(setExpression).toHaveBeenCalledWith("comfort"));
    expect(startMotion).toHaveBeenCalledWith("Continuity", 1);
  });

  it("supersamples the pet runtime canvas without changing the stage canvas scale", async () => {
    const mountedRuntime: Live2DRuntimeBoundary = {
      ...runtime,
      canMountRenderer: true,
    };
    const petResize = vi.fn();
    const petHandle = createMountedRuntimeHandle({ resize: petResize });
    mountLive2DRendererBoundaryMock.mockResolvedValueOnce({
      status: "mounted",
      renderMode: "official",
      message: "mounted",
      diagnostics: petHandle.getDiagnostics(),
      handle: petHandle,
    });

    const petResult = render(
      <Live2DStage
        stage={stage}
        asset={asset}
        runtime={mountedRuntime}
        canvasRef={createRef<HTMLCanvasElement>()}
        variant="pet"
      />,
    );

    await waitFor(() => expect(petResize).toHaveBeenCalled());
    expect(petResize).toHaveBeenLastCalledWith({ width: 640, height: 960, pixelRatio: 2 });
    petResult.unmount();

    const stageResize = vi.fn();
    const stageHandle = createMountedRuntimeHandle({ resize: stageResize });
    mountLive2DRendererBoundaryMock.mockResolvedValueOnce({
      status: "mounted",
      renderMode: "official",
      message: "mounted",
      diagnostics: stageHandle.getDiagnostics(),
      handle: stageHandle,
    });

    const stageResult = render(
      <Live2DStage
        stage={stage}
        asset={asset}
        runtime={mountedRuntime}
        canvasRef={createRef<HTMLCanvasElement>()}
        variant="stage"
      />,
    );

    await waitFor(() => expect(stageResize).toHaveBeenCalled());
    expect(stageResize).toHaveBeenLastCalledWith({ width: 320, height: 480, pixelRatio: 1 });
    stageResult.unmount();
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

  it("shows preview-only project character as a preview instead of a render failure", () => {
    const previewAsset: Live2DAssetInfo = {
      ...asset,
      status: "preview",
      version: undefined,
      moc: undefined,
      textureCount: 0,
      expressionCount: 18,
      motionCount: 28,
      actionCount: 28,
      previewOnly: true,
      designPath: "/live2d/agent_pet_companion/character-design.json",
      hasPhysics: false,
      hasDisplayInfo: false,
    };
    const previewRuntime: Live2DRuntimeBoundary = {
      ...runtime,
      status: "preview-only",
      title: "角色预览",
      detail: "项目角色静态预览已启用；导出 Cubism model3 后会接管为真实 Live2D 渲染。",
      canMountRenderer: false,
    };

    render(
      <Live2DStage
        stage={stage}
        asset={previewAsset}
        runtime={previewRuntime}
        canvasRef={createRef<HTMLCanvasElement>()}
        variant="pet"
      />,
    );

    expect(screen.getByLabelText("桌宠模型")).toHaveClass("live2d-runtime-preview-only");
    expect(screen.getByLabelText("桌宠模型")).toHaveClass("live2d-render-preview");
    expect(screen.getByText("角色静态预览")).toBeInTheDocument();
    expect(screen.getByLabelText("桌宠模型静态回退封面")).toBeInTheDocument();
    expect(screen.queryByText("模型渲染不可用")).not.toBeInTheDocument();
  });
});
