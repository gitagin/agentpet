import { useEffect, useRef, useState } from "react";
import type { MouseEvent, PointerEvent, RefObject, ReactNode } from "react";
import type { Live2DAssetInfo, Live2DRendererDiagnostics, Live2DRendererMode, Live2DRuntimeBoundary, Live2DRuntimeHandle } from "../services/live2dRuntime";
import { createRendererMountContext, mountLive2DRendererBoundary } from "../services/live2dRuntime";
import { resolveLive2DActionDirective } from "../services/live2dActions";

export type Live2DStageState =
  | "disconnected"
  | "idle"
  | "presence"
  | "reflective"
  | "thinking"
  | "memory"
  | "confirming"
  | "tasking"
  | "diagnosed";

export type Live2DStageView = {
  state: Live2DStageState;
  label: string;
  mood: string;
  message: string;
  hint: string;
};

export type Live2DStageRuntimeDirective = {
  actionKey: string;
  expression: string;
  motionGroup: string;
  motionIndex: number;
  petHint: string;
  controlSummary: string;
  warnings: string[];
};

const live2DStageActionKeys: Record<Live2DStageState, string> = {
  disconnected: "system_offline",
  idle: "idle",
  presence: "continuity_remember",
  reflective: "emotion_comfort",
  thinking: "chat_think",
  memory: "memory_search",
  confirming: "memory_confirm_needed",
  tasking: "task_create",
  diagnosed: "system_diagnosed",
};

type Live2DRenderLifecycleStatus = "loading" | "mounted" | "preview" | "failed";

const petCanvasSupersampleRatio = 1;
const maxCanvasPixelRatio = 2;
const live2dRenderInspectIntervalMs = 5000;
const live2dLayoutInspectIntervalMs = 5000;

function getLive2DCanvasPixelRatio(variant: "panel" | "pet" | "stage" | undefined): number {
  const devicePixelRatio = window.devicePixelRatio || 1;
  return variant === "pet"
    ? Math.min(devicePixelRatio * petCanvasSupersampleRatio, maxCanvasPixelRatio)
    : devicePixelRatio;
}

function isLive2DWindowFocused(): boolean {
  if (document.visibilityState === "hidden") {
    return false;
  }
  return typeof document.hasFocus === "function" ? document.hasFocus() : true;
}

function getLive2DRenderLifecycleText(status: Live2DRenderLifecycleStatus): string {
  const labels: Record<Live2DRenderLifecycleStatus, string> = {
    loading: "模型渲染启动中",
    mounted: "模型渲染已启动",
    preview: "角色静态预览",
    failed: "模型渲染不可用",
  };
  return labels[status];
}

function getInitialLive2DRenderStatus(
  variant: "panel" | "pet" | "stage" | undefined,
  shouldMountRenderer: boolean,
  runtimeStatus: Live2DRuntimeBoundary["status"],
): Live2DRenderLifecycleStatus {
  if (shouldMountRenderer) {
    return "loading";
  }
  if (runtimeStatus === "preview-only") {
    return "preview";
  }
  return variant === "panel" ? "preview" : "failed";
}

function getInactiveLive2DRenderStatus(
  variant: "panel" | "pet" | "stage" | undefined,
  runtimeStatus: Live2DRuntimeBoundary["status"],
): Live2DRenderLifecycleStatus {
  if (runtimeStatus === "loading-assets") {
    return "loading";
  }
  if (runtimeStatus === "preview-only") {
    return "preview";
  }
  return variant === "panel" ? "preview" : "failed";
}

function getLive2DRenderModeText(mode: Live2DRendererMode): string {
  const labels: Record<Live2DRendererMode, string> = {
    official: "官方渲染器",
    fallback: "基础回退渲染",
    failed: "静态回退显示",
  };
  return labels[mode];
}

function getLive2DStaticPreviewMessage(
  variant: "panel" | "pet" | "stage" | undefined,
  fallback: string,
  runtimeStatus: Live2DRuntimeBoundary["status"],
): string {
  if (runtimeStatus === "preview-only") {
    return fallback || "项目角色静态预览已启用，等待 Cubism 导出后切换为真实 Live2D 渲染。";
  }
  if (variant === "panel") {
    return "控制台使用静态预览；真实模型渲染只在陪伴和桌宠窗口运行。";
  }
  return fallback || "模型资源暂未就绪。";
}

function getLive2DStageRuntimeDirective(
  state: Live2DStageState,
  asset: Live2DAssetInfo,
): Live2DStageRuntimeDirective {
  return getLive2DActionRuntimeDirective(live2DStageActionKeys[state], asset);
}

function getLive2DActionRuntimeDirective(
  actionKey: string,
  asset: Live2DAssetInfo,
): Live2DStageRuntimeDirective {
  return resolveLive2DActionDirective({
    actionKey,
    profile: asset.actionProfile,
    availableExpressions: asset.expressions,
    availableMotions: asset.motions,
    defaultMotionGroup: asset.defaultMotionGroup,
    defaultMotionIndex: asset.defaultMotionIndex,
  });
}

function getLive2DSpeakingRuntimeDirective(
  asset: Live2DAssetInfo,
): Live2DStageRuntimeDirective {
  return getLive2DActionRuntimeDirective("tts_speaking", asset);
}

function getLive2DRuntimeDirective({
  state,
  asset,
  speaking,
  actionKeyOverride,
}: {
  state: Live2DStageState;
  asset: Live2DAssetInfo;
  speaking: boolean;
  actionKeyOverride?: string | null;
}): Live2DStageRuntimeDirective {
  const override = actionKeyOverride?.trim();
  if (override) {
    return getLive2DActionRuntimeDirective(override, asset);
  }
  return speaking ? getLive2DSpeakingRuntimeDirective(asset) : getLive2DStageRuntimeDirective(state, asset);
}

function getLive2DRuntimeDiagnosticRows({
  asset,
  runtime,
  renderLifecycle,
  lifecycleText,
  renderModeText,
  runtimeCommand,
  runtimeDiagnostics,
  resourceCountText,
  layoutWarning,
}: {
  asset: Live2DAssetInfo;
  runtime: Live2DRuntimeBoundary;
  renderLifecycle: { status: Live2DRenderLifecycleStatus; message: string; renderMode?: Live2DRendererMode };
  lifecycleText: string;
  renderModeText: string;
  runtimeCommand: Live2DStageRuntimeDirective;
  runtimeDiagnostics: Live2DRendererDiagnostics | null;
  resourceCountText: string;
  layoutWarning: string | null;
}): Array<{ label: string; value: string }> {
  const motionText = runtimeDiagnostics?.currentMotion ? (runtimeDiagnostics.currentMotion.group || "默认动作") + "[" + runtimeDiagnostics.currentMotion.index + "]" : "未播放";
  const expressionText = runtimeDiagnostics?.currentExpression || "未切换";
  const visibleText = runtimeDiagnostics?.visiblePixels === null || !runtimeDiagnostics ? "未检测" : runtimeDiagnostics.visiblePixels ? "可见" : "未检测到可见内容";
  const renderPathText = runtimeDiagnostics ? getLive2DRenderModeText(runtimeDiagnostics.renderMode) : "等待渲染器";
  const effectText = runtimeDiagnostics ? "动作 " + runtimeDiagnostics.motionCount + " 个，表情 " + runtimeDiagnostics.expressionCount + " 个，眨眼" + (runtimeDiagnostics.eyeBlinkEnabled ? "已启用" : "未启用") + "，呼吸" + (runtimeDiagnostics.breathEnabled ? "已启用" : "未启用") + "，物理摆动" + (runtimeDiagnostics.physicsEnabled ? "已启用" : "未启用") : "等待模型资源";
  const latestIssue = runtimeDiagnostics?.lastOfficialRenderError || runtimeDiagnostics?.lastFallbackRenderError || runtimeDiagnostics?.lastMotionError || runtimeDiagnostics?.lastExpressionError || runtimeDiagnostics?.lastEffectError || "暂无问题";
  const actionProfileText = asset.actionProfileStatus === "loaded"
    ? `${asset.actionProfilePath || "模型动作配置"} 已加载，${asset.actionCount || 0} 个项目动作。`
    : asset.actionProfileStatus === "error"
      ? `${asset.actionProfilePath || "模型动作配置"} 读取失败：${asset.actionProfileError || "未知错误"}。`
      : "未声明模型动作配置，使用内置默认映射。";
  const actionWarnings = runtimeCommand.warnings.length > 0 ? runtimeCommand.warnings.join("；") : "当前动作适配正常。";
  return [
    { label: "渲染状态", value: lifecycleText + " / " + renderModeText },
    { label: "当前指令", value: runtimeCommand.controlSummary + " 当前表情：" + (runtimeCommand.expression || "未指定") + "；当前动作：" + (runtimeCommand.motionIndex >= 0 ? (runtimeCommand.motionGroup || "默认动作组") + "[" + runtimeCommand.motionIndex + "]" : "未指定") },
    { label: "动作适配", value: `${actionProfileText} 当前项目动作：${runtimeCommand.actionKey}。${actionWarnings}` },
    { label: "渲染路径", value: runtimeDiagnostics ? renderPathText + "；当前动作：" + motionText + "；当前表情：" + expressionText + "；画布状态：" + visibleText : "等待桌宠渲染器启动" },
    { label: "动作与效果", value: effectText },
    { label: "最近问题", value: latestIssue },
    { label: "模型资源", value: asset.status === "recognized" ? resourceCountText + "，模型文件：" + (asset.moc || "未识别") : asset.status === "preview" ? resourceCountText + "，设计稿：" + (asset.designPath || "未声明") : asset.status + "，" + (asset.error || runtime.detail) },
    { label: "画布诊断", value: layoutWarning || (renderLifecycle.status === "mounted" ? "画布已挂载，像素检测仅作诊断" : renderLifecycle.message) },
  ];
}

function formatLive2DResourceCount(asset: Live2DAssetInfo): string {
  if (asset.status === "loading") {
    return "识别中";
  }

  if (asset.status === "missing" || asset.status === "error") {
    return "待识别";
  }

  if (asset.status === "preview") {
    return asset.actionCount ? `待导出 Cubism / ${asset.actionCount} 个项目动作已适配` : "待导出 Cubism";
  }

  return `${asset.textureCount} 张贴图 / ${asset.expressionCount} 个表情 / ${asset.motionCount} 个动作`;
}

function getLive2DCoverStatusText(asset: Live2DAssetInfo): string {
  if (asset.status === "loading") {
    return "校验中";
  }

  if (asset.hasIcon) {
    return `已加载：${asset.iconPath}`;
  }

  if (asset.status === "recognized") {
    return "未找到封面，当前显示 CSS 占位";
  }

  if (asset.status === "preview") {
    return "静态预览封面待确认";
  }

  return "待识别";
}

export function getLive2DAssetStatusText(asset: Live2DAssetInfo): { title: string; detail: string } {
  if (asset.status === "recognized") {
    return {
      title: "模型资源已识别",
      detail: `已读取桌宠模型清单，Cubism 运行时会尝试挂载 WebGL 画布；失败时回退到${asset.hasIcon ? "静态封面" : "样式占位"}。`,
    };
  }

  if (asset.status === "missing") {
    return {
      title: "模型资源未识别",
      detail: `未读取到 ${asset.manifestPath}；Cubism 运行时暂不能挂载。`,
    };
  }

  if (asset.status === "preview") {
    return {
      title: "角色预览已启用",
      detail: `正在使用 ${asset.iconPath || "静态角色预览"}；${asset.actionCount || 0} 个项目动作已按设计稿适配，等待 Cubism 导出后切换为真实 Live2D 模型。`,
    };
  }

  if (asset.status === "error") {
    return {
      title: "模型资源读取失败",
      detail: `${asset.error || "读取清单时发生异常"}；Cubism 运行时暂不能挂载。`,
    };
  }

  return {
    title: "正在识别模型资源",
    detail: "正在读取桌宠模型清单；资源就绪后会挂载 Cubism WebGL 渲染器。",
  };
}

export function Live2DStage({
  stage,
  asset,
  runtime,
  canvasRef,
  variant = "panel",
  petInteractions,
  speaking = false,
  actionKeyOverride = null,
  actionTriggerKey = null,
  active = true,
  suppressCanvasLayoutWarning = false,
}: {
  stage: Live2DStageView;
  asset: Live2DAssetInfo;
  runtime: Live2DRuntimeBoundary;
  canvasRef: RefObject<HTMLCanvasElement>;
  variant?: "panel" | "pet" | "stage";
  speaking?: boolean;
  actionKeyOverride?: string | null;
  actionTriggerKey?: string | null;
  active?: boolean;
  suppressCanvasLayoutWarning?: boolean;
  petInteractions?: {
    onPointerDown: (event: PointerEvent<HTMLElement>) => void;
    onPointerMove: (event: PointerEvent<HTMLElement>) => void;
    onPointerUp: (event: PointerEvent<HTMLElement>) => void;
    onPointerCancel: (event: PointerEvent<HTMLElement>) => void;
    onLostPointerCapture: (event: PointerEvent<HTMLElement>) => void;
    onContextMenu: (event: MouseEvent<HTMLElement>) => void;
    onBubbleContextMenu: (event: MouseEvent<HTMLElement>) => void;
    onDoubleClick: () => void;
  };
}) {
  const assetStatusText = getLive2DAssetStatusText(asset);
  const resourceCountText = formatLive2DResourceCount(asset);
  const coverStatusText = getLive2DCoverStatusText(asset);
  const shouldMountRenderer = (variant === "pet" || variant === "stage") && runtime.canMountRenderer;
  const [renderLifecycle, setRenderLifecycle] = useState<{
    status: Live2DRenderLifecycleStatus;
    message: string;
    renderMode?: Live2DRendererMode;
  }>(() => ({
    status: getInitialLive2DRenderStatus(variant, shouldMountRenderer, runtime.status),
    renderMode: "failed",
    message: shouldMountRenderer ? "正在启动桌宠模型渲染。" : getLive2DStaticPreviewMessage(variant, runtime.detail, runtime.status),
  }));
  const [layoutWarning, setLayoutWarning] = useState<string | null>(null);
  const [runtimeCommand, setRuntimeCommand] = useState<Live2DStageRuntimeDirective>(() =>
    getLive2DRuntimeDirective({ state: stage.state, asset, speaking, actionKeyOverride }),
  );
  const [runtimeDiagnostics, setRuntimeDiagnostics] = useState<Live2DRendererDiagnostics | null>(null);
  const [windowFocused, setWindowFocused] = useState(isLive2DWindowFocused);
  const rendererFocused = active && windowFocused;
  const live2dRuntimeHandleRef = useRef<Live2DRuntimeHandle | null>(null);
  const activeRef = useRef(active);
  const rendererFocusedRef = useRef(rendererFocused);

  useEffect(() => {
    activeRef.current = active;
    rendererFocusedRef.current = rendererFocused;
    live2dRuntimeHandleRef.current?.setActive?.(active);
    live2dRuntimeHandleRef.current?.setFocused?.(rendererFocused);
    if (!rendererFocused) {
      setLayoutWarning(null);
    }
  }, [active, rendererFocused]);

  useEffect(() => {
    const updateWindowFocus = () => setWindowFocused(isLive2DWindowFocused());
    window.addEventListener("focus", updateWindowFocus);
    window.addEventListener("blur", updateWindowFocus);
    document.addEventListener("visibilitychange", updateWindowFocus);
    updateWindowFocus();

    return () => {
      window.removeEventListener("focus", updateWindowFocus);
      window.removeEventListener("blur", updateWindowFocus);
      document.removeEventListener("visibilitychange", updateWindowFocus);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const mountVariant = variant === "pet" ? "pet" : "stage";
    const mountContext = createRendererMountContext(canvas, asset, mountVariant);
    let activeHandle: Live2DRuntimeHandle | null = null;
    let disposed = false;
    let retryTimerId: number | null = null;
    let invisibleSampleMissCount = 0;

    if (!shouldMountRenderer || !mountContext) {
      setRenderLifecycle({
        status: getInactiveLive2DRenderStatus(variant, runtime.status),
        renderMode: "failed",
        message: getLive2DStaticPreviewMessage(variant, runtime.detail, runtime.status),
      });
      setRuntimeDiagnostics(null);
      return;
    }

    setRenderLifecycle({ status: "loading", message: "正在启动桌宠模型渲染。" });

    const canvasElement = mountContext.canvas;
    const resizeRuntime = () => {
      const bounds = canvasElement.getBoundingClientRect();
      const pixelRatio = getLive2DCanvasPixelRatio(variant);
      const width = Math.max(1, Math.round(bounds.width * pixelRatio));
      const height = Math.max(1, Math.round(bounds.height * pixelRatio));

      if (canvasElement.width !== width) {
        canvasElement.width = width;
      }
      if (canvasElement.height !== height) {
        canvasElement.height = height;
      }

      activeHandle?.resize?.({ width, height, pixelRatio });
    };

    const resizeObserver = new ResizeObserver(resizeRuntime);
    resizeObserver.observe(canvasElement);
    if (variant !== "pet") {
      window.addEventListener("resize", resizeRuntime);
    }

    const mountRenderer = (retryCount = 0) => {
      resizeRuntime();
      activeHandle?.dispose?.();
      activeHandle = null;
      live2dRuntimeHandleRef.current = null;
      void mountLive2DRendererBoundary(mountContext).then((mountResult) => {
        if (disposed) {
          mountResult.handle?.dispose();
          return;
        }

        if (mountResult.status === "failed" && retryCount < 1) {
          setRenderLifecycle({
            status: "loading",
            renderMode: mountResult.renderMode,
            message: `${mountResult.message} 正在重试一次。`,
          });
          retryTimerId = window.setTimeout(() => {
            retryTimerId = null;
            if (!disposed) {
              mountRenderer(retryCount + 1);
            }
          }, 800);
          return;
        }

        activeHandle = mountResult.handle || null;
        live2dRuntimeHandleRef.current = activeHandle;
        activeHandle?.setActive?.(activeRef.current);
        activeHandle?.setFocused?.(rendererFocusedRef.current);
        resizeRuntime();
        setRuntimeDiagnostics(mountResult.diagnostics || activeHandle?.getDiagnostics?.() || null);
        setRenderLifecycle({
          status: mountResult.status,
          renderMode: mountResult.renderMode,
          message: mountResult.message,
        });
      });
    };

    const handleContextLost = (event: Event) => {
      event.preventDefault();
      activeHandle?.dispose?.();
      activeHandle = null;
      live2dRuntimeHandleRef.current = null;
      setRuntimeDiagnostics(null);
      setRenderLifecycle({
        status: "failed",
        renderMode: "failed",
        message: "WebGL 上下文已丢失，正在等待系统恢复桌宠画布。",
      });
    };

    const handleContextRestored = () => {
      if (disposed) {
        return;
      }
      setRenderLifecycle({
        status: "loading",
        renderMode: "failed",
        message: "WebGL 上下文已恢复，正在重新挂载桌宠模型渲染器。",
      });
      mountRenderer();
    };

    const inspectRenderMode = () => {
      if (!rendererFocusedRef.current || !activeHandle) {
        return;
      }
      const renderMode = activeHandle.getRenderMode?.();
      setRuntimeDiagnostics(activeHandle.getDiagnostics?.() || null);
      if (renderMode) {
        setRenderLifecycle((current) => (
          current.status === "mounted" && current.renderMode !== renderMode
            ? { ...current, renderMode, message: getLive2DRenderModeText(renderMode) }
            : current
        ));
      }
      if (activeHandle.hasVisiblePixels && !activeHandle.hasVisiblePixels()) {
        invisibleSampleMissCount += 1;
        if (invisibleSampleMissCount === 1 || invisibleSampleMissCount % 5 === 0) {
          console.info(
            "[Live2D] 画布像素采样暂未命中可见区域，保留已挂载状态；这通常是透明画布、模型位置或 WebGL 后缓冲采样导致的诊断噪声。",
          );
        }
        setLayoutWarning((current) => (
          current === "模型已挂载，但当前画布没有检测到可见像素。" ? null : current
        ));
        return;
      }
      invisibleSampleMissCount = 0;
      setLayoutWarning((current) => (
        current === "模型已挂载，但当前画布没有检测到可见像素。" ? null : current
      ));
    };

    canvasElement.addEventListener("webglcontextlost", handleContextLost);
    canvasElement.addEventListener("webglcontextrestored", handleContextRestored);
    const renderInspectTimer = window.setInterval(inspectRenderMode, live2dRenderInspectIntervalMs);

    mountRenderer();

    return () => {
      disposed = true;
      if (retryTimerId !== null) {
        window.clearTimeout(retryTimerId);
        retryTimerId = null;
      }
      resizeObserver.disconnect();
      if (variant !== "pet") {
        window.removeEventListener("resize", resizeRuntime);
      }
      canvasElement.removeEventListener("webglcontextlost", handleContextLost);
      canvasElement.removeEventListener("webglcontextrestored", handleContextRestored);
      window.clearInterval(renderInspectTimer);
      activeHandle?.cleanup?.();
      activeHandle?.destroy?.();
      activeHandle?.dispose?.();
      activeHandle?.unmount?.();
      activeHandle = null;
      live2dRuntimeHandleRef.current = null;
      setRuntimeDiagnostics(null);
    };
  }, [asset, canvasRef, runtime.detail, runtime.status, shouldMountRenderer, variant]);

  useEffect(() => {
    const command = getLive2DRuntimeDirective({ state: stage.state, asset, speaking, actionKeyOverride });
    setRuntimeCommand(command);

    const handle = live2dRuntimeHandleRef.current;
    if (!handle || renderLifecycle.status !== "mounted") {
      return;
    }

    try {
      if (command.expression) {
        handle.setExpression(command.expression);
      }
      if (command.motionIndex >= 0) {
        handle.startMotion(command.motionGroup, command.motionIndex);
      }
      setRuntimeDiagnostics(handle.getDiagnostics?.() || null);
    } catch (error) {
      console.warn("[Live2D] 状态指令发送失败。", {
        state: stage.state,
        actionKey: command.actionKey,
        speaking,
        actionKeyOverride,
        actionTriggerKey,
        expression: command.expression,
        motionGroup: command.motionGroup,
        motionIndex: command.motionIndex,
        error,
      });
    }
  }, [actionKeyOverride, actionTriggerKey, asset, renderLifecycle.status, speaking, stage.state]);

  useEffect(() => {
    if (!rendererFocused || renderLifecycle.status !== "mounted" || suppressCanvasLayoutWarning) {
      setLayoutWarning(null);
      return;
    }

    const canvas = canvasRef.current;
    if (!canvas) {
      setLayoutWarning("模型已报告挂载，但未找到画布节点。");
      return;
    }

    const inspectCanvasLayout = () => {
      const bounds = canvas.getBoundingClientRect();
      const styles = window.getComputedStyle(canvas);
      const hostStyles = canvas.parentElement ? window.getComputedStyle(canvas.parentElement) : null;
      const width = Math.round(bounds.width);
      const height = Math.round(bounds.height);
      const opacity = Number.parseFloat(styles.opacity || "1");
      const hidden =
        styles.display === "none" ||
        styles.visibility === "hidden" ||
        (hostStyles ? hostStyles.display === "none" || hostStyles.visibility === "hidden" : false);

      if (hidden) {
        setLayoutWarning("模型已挂载，但画布或宿主节点被样式隐藏。");
        return;
      }

      if (width < 24 || height < 24) {
        setLayoutWarning(`模型已挂载，但画布可视尺寸过小：${width}x${height}px。`);
        return;
      }

      if (opacity < 0.95) {
        setLayoutWarning(`模型已挂载，但画布透明度为 ${styles.opacity}。`);
        return;
      }

      setLayoutWarning(null);
    };

    const frame = window.requestAnimationFrame(inspectCanvasLayout);
    const layoutInspectTimer = window.setInterval(inspectCanvasLayout, live2dLayoutInspectIntervalMs);
    const resizeObserver = new ResizeObserver(inspectCanvasLayout);
    resizeObserver.observe(canvas);
    window.addEventListener("resize", inspectCanvasLayout);

    return () => {
      window.cancelAnimationFrame(frame);
      window.clearInterval(layoutInspectTimer);
      resizeObserver.disconnect();
      window.removeEventListener("resize", inspectCanvasLayout);
    };
  }, [canvasRef, renderLifecycle.status, rendererFocused, suppressCanvasLayoutWarning]);

  const lifecycleText = getLive2DRenderLifecycleText(renderLifecycle.status);
  const renderModeText = getLive2DRenderModeText(renderLifecycle.renderMode || "failed");
  const diagnosticRows = getLive2DRuntimeDiagnosticRows({
    asset,
    runtime,
    renderLifecycle,
    lifecycleText,
    renderModeText,
    runtimeCommand,
    runtimeDiagnostics,
    resourceCountText,
    layoutWarning,
  });
  const isPointerOnPetModel = (clientX: number, clientY: number) => {
    if (renderLifecycle.status !== "mounted") {
      return true;
    }
    return Boolean(live2dRuntimeHandleRef.current?.isPointOnVisiblePixel?.(clientX, clientY));
  };
  const petModelInteractions = petInteractions ? {
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      if (isPointerOnPetModel(event.clientX, event.clientY)) {
        petInteractions.onPointerDown(event);
      }
    },
    onPointerMove: petInteractions.onPointerMove,
    onPointerUp: petInteractions.onPointerUp,
    onPointerCancel: petInteractions.onPointerCancel,
    onLostPointerCapture: petInteractions.onLostPointerCapture,
    onContextMenu: (event: MouseEvent<HTMLElement>) => {
      if (isPointerOnPetModel(event.clientX, event.clientY)) {
        petInteractions.onContextMenu(event);
      }
    },
    onDoubleClick: (event: MouseEvent<HTMLElement>) => {
      if (isPointerOnPetModel(event.clientX, event.clientY)) {
        petInteractions.onDoubleClick();
      }
    },
  } : null;
  const petBubbleInteractions = petInteractions ? {
    onPointerDown: petInteractions.onPointerDown,
    onPointerMove: petInteractions.onPointerMove,
    onPointerUp: petInteractions.onPointerUp,
    onPointerCancel: petInteractions.onPointerCancel,
    onLostPointerCapture: petInteractions.onLostPointerCapture,
    onContextMenu: petInteractions.onBubbleContextMenu,
  } : null;

  if (variant === "pet") {
    const shouldRenderPetFallbackComposition = renderLifecycle.status !== "mounted" || Boolean(layoutWarning);

    return (
      <section
        className={`panel live2d-panel live2d-panel-pet live2d-${stage.state}${speaking ? " live2d-speaking" : ""} live2d-runtime-${runtime.status} live2d-render-${renderLifecycle.status} live2d-render-mode-${renderLifecycle.renderMode || "unknown"}`}
        aria-label="桌宠模型"
        data-live2d-speaking={speaking ? "true" : "false"}
        data-live2d-action-key={runtimeCommand.actionKey}
        data-live2d-action-trigger={actionTriggerKey || ""}
      >
        <div
          className="live2d-pet-stage"
          role="img"
          aria-label={`桌宠模型状态：${stage.label}`}
          data-live2d-render={renderLifecycle.status}
          data-live2d-render-mode={renderLifecycle.renderMode || "unknown"}
          data-live2d-speaking={speaking ? "true" : "false"}
          data-live2d-action-key={runtimeCommand.actionKey}
          data-live2d-action-trigger={actionTriggerKey || ""}
        >
          <div className="live2d-runtime-host" aria-label="桌宠模型运行时画布区域">
            <canvas
              ref={canvasRef}
              id={runtime.mountTargetId}
              className="live2d-runtime-canvas"
              width={300}
              height={390}
            />
          </div>

          {shouldRenderPetFallbackComposition ? (
            <div className="live2d-pet-composition">
              {asset.hasIcon ? (
                <div
                  className="live2d-cover live2d-cover-image"
                  aria-label="桌宠模型静态回退封面"
                  style={{ backgroundImage: `url("${asset.iconPath}")` }}
                />
              ) : (
                <div className="live2d-model" aria-label="样式回退展示壳">
                  <div className="live2d-hair back" />
                  <div className="live2d-head">
                    <div className="live2d-bangs">
                      <span />
                      <span />
                      <span />
                    </div>
                    <div className="live2d-eye left" />
                    <div className="live2d-eye right" />
                    <div className="live2d-blush left" />
                    <div className="live2d-blush right" />
                    <div className="live2d-mouth" />
                  </div>
                  <div className="live2d-neck" />
                  <div className="live2d-body">
                    <div className="live2d-collar" />
                    <div className="live2d-ribbon" />
                  </div>
                  <div className="live2d-arm left" />
                  <div className="live2d-arm right" />
                </div>
              )}

              {renderLifecycle.status !== "mounted" ? (
                <div className="live2d-runtime-placeholder">
                  <strong>{lifecycleText}</strong>
                  <span>{renderLifecycle.message}</span>
                </div>
              ) : null}

              {layoutWarning ? (
                <div className="live2d-layout-warning" role="status" aria-live="polite">
                  <strong>模型布局提示</strong>
                  <span>{layoutWarning}</span>
                </div>
              ) : null}
            </div>
          ) : null}
          {petInteractions ? (
            <>
              <div
                className="pet-hit-region pet-hit-model"
                aria-label="桌宠模型交互区"
                {...petModelInteractions}
              />
              <div
                className="pet-hit-region pet-hit-bubble"
                aria-label="桌宠底部输入交互区"
                {...petBubbleInteractions}
              />
            </>
          ) : null}
        </div>
      </section>
    );
  }

  if (variant === "stage") {
    return (
      <section
        className={`panel live2d-panel live2d-panel-stage live2d-${stage.state}${speaking ? " live2d-speaking" : ""} live2d-runtime-${runtime.status} live2d-render-${renderLifecycle.status} live2d-render-mode-${renderLifecycle.renderMode || "unknown"}`}
        aria-label="陪伴模型"
        data-live2d-speaking={speaking ? "true" : "false"}
        data-live2d-action-key={runtimeCommand.actionKey}
        data-live2d-action-trigger={actionTriggerKey || ""}
      >
        <div
          className="live2d-stage"
          role="img"
          aria-label={`陪伴模型状态：${stage.label}`}
          data-live2d-render={renderLifecycle.status}
          data-live2d-render-mode={renderLifecycle.renderMode || "unknown"}
          data-live2d-speaking={speaking ? "true" : "false"}
          data-live2d-action-key={runtimeCommand.actionKey}
          data-live2d-action-trigger={actionTriggerKey || ""}
        >
          <div className="live2d-runtime-host" aria-label="桌宠模型运行时画布区域">
            <canvas
              ref={canvasRef}
              id={runtime.mountTargetId}
              className="live2d-runtime-canvas"
              width={560}
              height={720}
            />
            {renderLifecycle.status !== "mounted" ? (
              <div className="live2d-runtime-placeholder">
                <strong>{lifecycleText}</strong>
                <span>{renderLifecycle.message}</span>
              </div>
            ) : null}
          </div>
          <div className="live2d-scanline" />
          {asset.hasIcon ? (
            <figure className="live2d-cover">
              <img src={asset.iconPath} alt={`${asset.modelLabel} 桌宠模型资源封面`} />
              <figcaption>{assetStatusText.title}</figcaption>
            </figure>
          ) : (
            <div className="live2d-model" aria-label="样式回退展示壳">
              <div className="live2d-hair back" />
              <div className="live2d-head">
                <div className="live2d-bangs">
                  <span />
                  <span />
                  <span />
                </div>
                <div className="live2d-eye left" />
                <div className="live2d-eye right" />
                <div className="live2d-blush left" />
                <div className="live2d-blush right" />
                <div className="live2d-mouth" />
              </div>
              <div className="live2d-neck" />
              <div className="live2d-body">
                <div className="live2d-collar" />
                <div className="live2d-ribbon" />
              </div>
              <div className="live2d-arm left" />
              <div className="live2d-arm right" />
            </div>
          )}
          <div className="live2d-status-card">
            <strong>{stage.mood}</strong>
            <span>{stage.hint} · {lifecycleText}</span>
          </div>
        </div>
        {layoutWarning ? (
          <div className="live2d-layout-warning" role="status" aria-live="polite">
            <strong>模型布局提示</strong>
            <span>{layoutWarning}</span>
          </div>
        ) : null}
      </section>
    );
  }

  return (
    <section
      className={`panel live2d-panel live2d-panel-${variant} live2d-${stage.state}${speaking ? " live2d-speaking" : ""} live2d-runtime-${runtime.status} live2d-render-${renderLifecycle.status} live2d-render-mode-${renderLifecycle.renderMode || "unknown"}`}
      aria-label="桌宠模型展示区"
      data-live2d-speaking={speaking ? "true" : "false"}
      data-live2d-action-key={runtimeCommand.actionKey}
      data-live2d-action-trigger={actionTriggerKey || ""}
    >
      <div className="live2d-copy">
        <p className="eyebrow">桌宠模型</p>
        <h2>{stage.label}</h2>
        <p>{stage.message}</p>
        <div className={`live2d-resource-summary live2d-resource-${asset.status}`}>
          <strong>{assetStatusText.title}</strong>
          <span>{assetStatusText.detail}</span>
        </div>
        <div className="live2d-status-grid" aria-label="模型资源识别与渲染接入状态">
          <div>
            <span>模型清单地址</span>
            <strong>{asset.manifestPath}</strong>
          </div>
          <div>
            <span>封面加载状态</span>
            <strong>{coverStatusText}</strong>
          </div>
          <div>
            <span>资源计数</span>
            <strong>{resourceCountText}</strong>
          </div>
          <div className="live2d-renderer-pending">
            <span>运行时状态</span>
            <strong>{runtime.title}</strong>
          </div>
        </div>
      </div>
      <div
        className="live2d-stage"
        role="img"
        aria-label={`桌宠模型状态：${stage.label}`}
        data-live2d-render={renderLifecycle.status}
        data-live2d-speaking={speaking ? "true" : "false"}
        data-live2d-action-key={runtimeCommand.actionKey}
      >
        <div className="live2d-runtime-host" aria-label="桌宠模型运行时画布区域">
          <canvas
            ref={canvasRef}
            id={runtime.mountTargetId}
            className="live2d-runtime-canvas"
            width={420}
            height={520}
          />
          <div className="live2d-runtime-placeholder">
            <strong>{lifecycleText}</strong>
            <span>{renderLifecycle.message}</span>
          </div>
        </div>
        <div className="live2d-scanline" />
        <div className="live2d-meter" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        {asset.hasIcon ? (
          <figure className="live2d-cover">
            <img src={asset.iconPath} alt={`${asset.modelLabel} 桌宠模型资源封面`} />
            <figcaption>静态封面，非动态渲染</figcaption>
          </figure>
        ) : (
          <div className="live2d-model" aria-label="样式回退展示壳">
            <div className="live2d-hair back" />
            <div className="live2d-head">
              <div className="live2d-bangs">
                <span />
                <span />
                <span />
              </div>
              <div className="live2d-eye left" />
              <div className="live2d-eye right" />
              <div className="live2d-blush left" />
              <div className="live2d-blush right" />
              <div className="live2d-mouth" />
            </div>
            <div className="live2d-neck" />
            <div className="live2d-body">
              <div className="live2d-collar" />
              <div className="live2d-ribbon" />
            </div>
            <div className="live2d-arm left" />
            <div className="live2d-arm right" />
          </div>
        )}
        <div className="live2d-status-card">
          <strong>{stage.mood}</strong>
          <span>{stage.hint} · {lifecycleText}</span>
        </div>
      </div>
      {layoutWarning ? (
        <div className="live2d-layout-warning" role="status" aria-live="polite">
          <strong>模型布局提示</strong>
          <span>{layoutWarning}</span>
        </div>
      ) : null}
      <div className="live2d-runtime-card" aria-label="模型运行时边界状态">
        <div>
          <span>挂载入口</span>
          <strong>#{runtime.mountTargetId}</strong>
        </div>
        <div>
          <span>挂载条件</span>
          <strong>{runtime.canMountRenderer ? "资源已就绪，等待真实渲染器接管" : "资源未就绪，保持边界预留"}</strong>
        </div>
        <div>
          <span>当前探测</span>
          <strong>{renderLifecycle.message}</strong>
        </div>
      </div>
      <dl className="live2d-diagnostic-summary" aria-label="模型运行时诊断摘要">
        {diagnosticRows.map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      <dl className="live2d-resource-list" aria-label="模型资源状态">
        <div>
          <dt>模型清单</dt>
          <dd>{asset.manifestPath}</dd>
        </div>
        <div>
          <dt>构建产物</dt>
          <dd>运行构建命令后校验桌面端产物目录</dd>
        </div>
        <div>
          <dt>运行时</dt>
          <dd>{runtime.title}：{renderLifecycle.message}</dd>
        </div>
        <div>
          <dt>封面</dt>
          <dd>{coverStatusText}</dd>
        </div>
        <div>
          <dt>模型文件</dt>
          <dd>{asset.moc || "待识别"}</dd>
        </div>
        <div>
          <dt>贴图</dt>
          <dd>{asset.textureCount} 个</dd>
        </div>
        <div>
          <dt>表情</dt>
          <dd>{asset.expressionCount} 个</dd>
        </div>
        <div>
          <dt>动作</dt>
          <dd>{asset.motionCount} 个</dd>
        </div>
        <div>
          <dt>物理/显示</dt>
          <dd>
            {asset.hasPhysics ? "物理已识别" : "无物理"} / {asset.hasDisplayInfo ? "显示信息已识别" : "无显示信息"}
          </dd>
        </div>
      </dl>
    </section>
  );
}

export function Live2DStageOverlay({ children }: { children: ReactNode }) {
  return <div>{children}</div>;
}
