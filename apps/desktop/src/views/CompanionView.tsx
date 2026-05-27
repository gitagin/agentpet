import type { CSSProperties, RefObject } from "react";
import { Live2DStage } from "../components/Live2DStage";
import type { Live2DStageView } from "../components/Live2DStage";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "../services/live2dRuntime";

type CompanionStyle = CSSProperties & { WebkitAppRegion?: "drag" | "no-drag" };

type CompanionViewProps = {
  live2dStage: Live2DStageView;
  live2dAsset: Live2DAssetInfo;
  live2dRuntime: Live2DRuntimeBoundary;
  live2dCanvasRef: RefObject<HTMLCanvasElement>;
  message?: string;
};

const companionStyles: Record<string, CompanionStyle> = {
  shell: {
    position: "relative",
    width: 200,
    height: 320,
    margin: 0,
    padding: 0,
    border: "none",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
    background: "transparent",
    color: "var(--color-text)",
    fontFamily: "var(--font-sans)",
    WebkitAppRegion: "drag",
  },
  live2dArea: {
    minHeight: 0,
    flex: 1,
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "center",
    overflow: "hidden",
    background: "transparent",
  },
  bubble: {
    position: "absolute",
    top: 12,
    right: 8,
    maxWidth: 140,
    padding: "8px 10px",
    fontSize: 12,
    lineHeight: 1.4,
    WebkitAppRegion: "no-drag",
  },
  shortcutBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 10,
    display: "flex",
    justifyContent: "center",
    gap: 8,
    WebkitAppRegion: "no-drag",
  },
  shortcutButton: {
    width: 34,
    height: 34,
    border: "none",
    borderRadius: 999,
    display: "grid",
    placeItems: "center",
    color: "var(--color-text)",
    background: "rgba(255, 255, 255, 0.78)",
    boxShadow: "0 10px 28px rgba(111, 91, 255, 0.18)",
    cursor: "pointer",
    fontSize: 16,
    WebkitAppRegion: "no-drag",
  },
};

export default function CompanionView({
  live2dStage,
  live2dAsset,
  live2dRuntime,
  live2dCanvasRef,
  message = "",
}: CompanionViewProps) {
  const bubbleMessage = message.trim(); // TODO: 接陪伴状态聚合接口。

  function handleInteraction() {
    // TODO: 接陪伴互动接口。
    console.log("互动");
  }

  function handleMore() {
    // TODO: 接更多操作面板。
    console.log("更多");
  }

  return (
    <main style={companionStyles.shell} aria-label="透明桌面陪伴体">
      <section style={companionStyles.live2dArea} aria-label="Live2D 角色">
        {/* TODO: Live2DStage 当前未暴露 fps/quality 轻量配置，后续由组件接口统一支持后再传入。 */}
        <Live2DStage
          key={`companion-${live2dAsset.modelId}`}
          stage={live2dStage}
          asset={live2dAsset}
          runtime={live2dRuntime}
          canvasRef={live2dCanvasRef}
          variant="pet"
        />
      </section>

      {bubbleMessage ? (
        <p className="glass-pill" style={companionStyles.bubble}>
          {bubbleMessage}
        </p>
      ) : null}

      <nav style={companionStyles.shortcutBar} aria-label="陪伴体快捷操作">
        <button type="button" style={companionStyles.shortcutButton} aria-label="打开主舞台" onClick={() => void window.agentDesktop?.openStage?.()}>
          🏠
        </button>
        <button type="button" style={companionStyles.shortcutButton} aria-label="互动" onClick={handleInteraction}>
          ❤️
        </button>
        <button type="button" style={companionStyles.shortcutButton} aria-label="打开 Agent 工作空间" onClick={() => void window.agentDesktop?.openAgent?.()}>
          🤖
        </button>
        <button type="button" style={companionStyles.shortcutButton} aria-label="更多" onClick={handleMore}>
          ⋯
        </button>
      </nav>
    </main>
  );
}
