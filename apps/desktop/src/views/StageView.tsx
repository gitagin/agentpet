import { useState } from "react";
import type { CSSProperties, FormEvent, RefObject } from "react";
import { Live2DStage } from "../components/Live2DStage";
import type { Live2DStageView } from "../components/Live2DStage";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "../services/live2dRuntime";

type StageViewProps = {
  live2dStage: Live2DStageView;
  live2dAsset: Live2DAssetInfo;
  live2dRuntime: Live2DRuntimeBoundary;
  live2dCanvasRef: RefObject<HTMLCanvasElement>;
  connected: boolean;
  streaming: boolean;
  onSendChat: (text: string, clearInput: () => void) => void | Promise<void>;
};

const companionProfile = {
  name: "小艾",
  mood: "开心 😊",
  status: "在线",
}; // TODO: 接真实接口

const companionStats = {
  greeting: "今天也想陪你把重要的小事记下来。",
  energy: 80,
  mood: 90,
  memoryCount: 42,
  interactions: 7,
}; // TODO: 接真实接口

const quickActions = ["查天气", "记录日记", "打开 Agent"] as const; // TODO: 接真实接口
const bottomTabs = ["陪伴", "对话", "记忆", "世界", "Agent", "设置"] as const; // TODO: 接真实接口

const stageStyles: Record<string, CSSProperties> = {
  shell: {
    minHeight: "100vh",
    padding: "var(--space-md)",
    background: "var(--bg-stage)",
    color: "var(--color-text)",
    fontFamily: "var(--font-sans)",
    boxSizing: "border-box",
    display: "grid",
    gridTemplateRows: "44px minmax(0, 1fr) auto",
    gap: "var(--space-md)",
  },
  topBar: {
    height: 44,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 16px",
    background: "rgba(255, 255, 255, 0.4)",
    backdropFilter: "blur(8px)",
    WebkitBackdropFilter: "blur(8px)",
  },
  topBarIdentity: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-sm)",
    fontWeight: 700,
  },
  mainGrid: {
    minHeight: 0,
    display: "grid",
    gridTemplateColumns: "220px minmax(320px, 1fr) 220px",
    gap: "var(--space-md)",
    alignItems: "stretch",
  },
  card: {
    width: 220,
    padding: 20,
    display: "flex",
    flexDirection: "column",
    gap: "var(--space-md)",
    minHeight: 0,
  },
  live2dWrap: {
    minHeight: 0,
    flex: 1,
    display: "flex",
    justifyContent: "center",
    alignItems: "flex-end",
    overflow: "hidden",
  },
  metricGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "var(--space-sm)",
  },
  metric: {
    padding: "var(--space-sm)",
    borderRadius: 14,
    background: "rgba(255, 255, 255, 0.48)",
  },
  quickActionList: {
    display: "grid",
    gap: "var(--space-sm)",
  },
  actionButton: {
    border: "none",
    borderRadius: 14,
    padding: "10px 12px",
    color: "var(--color-text)",
    background: "rgba(255, 255, 255, 0.72)",
    cursor: "pointer",
    textAlign: "left",
  },
  footer: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: "var(--space-md)",
    alignItems: "center",
  },
  chatForm: {
    display: "flex",
    gap: "var(--space-sm)",
    padding: "12px 16px",
    margin: "12px 16px",
    borderRadius: 16,
    background: "rgba(255, 255, 255, 0.7)",
  },
  chatInput: {
    flex: 1,
    border: "none",
    borderRadius: 999,
    padding: "0 16px",
    minHeight: 40,
    color: "var(--color-text)",
    background: "transparent",
    fontFamily: "var(--font-sans)",
    outline: "none",
  },
  primaryButton: {
    border: "none",
    borderRadius: 999,
    padding: "0 18px",
    color: "white",
    background: "var(--color-primary)",
    cursor: "pointer",
    fontWeight: 700,
  },
  disabledButton: {
    border: "none",
    borderRadius: 999,
    padding: "0 14px",
    color: "var(--color-text-soft)",
    background: "rgba(255, 255, 255, 0.55)",
    cursor: "not-allowed",
  },
  bottomNav: {
    height: 56,
    display: "flex",
    justifyContent: "space-around",
    gap: "var(--space-xs)",
    padding: "var(--space-sm)",
    background: "rgba(255, 255, 255, 0.8)",
    backdropFilter: "blur(12px)",
    WebkitBackdropFilter: "blur(12px)",
  },
  navButton: {
    border: "none",
    borderRadius: 999,
    padding: "8px 12px",
    color: "var(--color-text-soft)",
    background: "transparent",
    boxShadow: "none",
    cursor: "pointer",
  },
  activeNavButton: {
    color: "var(--color-primary)",
    background: "transparent",
  },
};

export default function StageView({
  live2dStage,
  live2dAsset,
  live2dRuntime,
  live2dCanvasRef,
  connected,
  streaming,
  onSendChat,
}: StageViewProps) {
  const [chatInput, setChatInput] = useState("");
  const currentTime = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }); // TODO: 接真实接口

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void onSendChat(chatInput, () => setChatInput(""));
  }

  function handleQuickAction(action: string) {
    if (action === "打开 Agent") {
      void window.agentDesktop?.openAgent?.();
      return;
    }
    console.log(`TODO: 接真实接口 - ${action}`);
  }

  return (
    <main style={stageStyles.shell} aria-label="桌面记忆助手主舞台">
      <header className="glass-card" style={stageStyles.topBar}>
        <div style={stageStyles.topBarIdentity}>
          <strong>{companionProfile.name}</strong>
          <span className="glass-pill">{companionProfile.mood}</span>
          <span className="glass-pill">{connected ? companionProfile.status : "离线"}</span>
        </div>
        <time className="glass-pill">{currentTime}</time>
      </header>

      <section style={stageStyles.mainGrid} aria-label="陪伴主区域">
        <aside className="glass-card" style={stageStyles.card}>
          <div>
            <p style={{ margin: 0, color: "var(--color-text-soft)" }}>今日陪伴</p>
            <h2 style={{ margin: "6px 0 0", fontSize: 22 }}>{companionStats.greeting}</h2>
          </div>
          <div style={stageStyles.metricGrid}>
            <div style={stageStyles.metric}>
              <small>能量</small>
              <strong>{companionStats.energy}%</strong>
            </div>
            <div style={stageStyles.metric}>
              <small>心情</small>
              <strong>{companionStats.mood}%</strong>
            </div>
            <div style={stageStyles.metric}>
              <small>记忆</small>
              <strong>{companionStats.memoryCount}</strong>
            </div>
            <div style={stageStyles.metric}>
              <small>互动</small>
              <strong>{companionStats.interactions}</strong>
            </div>
          </div>
        </aside>

        <section className="glass-card" style={stageStyles.live2dWrap} aria-label="Live2D 陪伴体">
          <Live2DStage
            key={`stage-${live2dAsset.modelId}`}
            stage={live2dStage}
            asset={live2dAsset}
            runtime={live2dRuntime}
            canvasRef={live2dCanvasRef}
          />
        </section>

        <aside className="glass-card" style={stageStyles.card}>
          <div>
            <p style={{ margin: 0, color: "var(--color-text-soft)" }}>当前场景</p>
            <h2 style={{ margin: "6px 0 0", fontSize: 22 }}>轻陪伴工作台</h2>
          </div>
          <div style={stageStyles.quickActionList}>
            {quickActions.map((action) => (
              <button
                key={action}
                type="button"
                style={stageStyles.actionButton}
                onClick={() => handleQuickAction(action)}
              >
                {action}
              </button>
            ))}
          </div>
        </aside>
      </section>

      <footer style={stageStyles.footer}>
        <form className="glass-card" style={stageStyles.chatForm} onSubmit={handleSubmit}>
          <input
            style={stageStyles.chatInput}
            value={chatInput}
            onChange={(event) => setChatInput(event.target.value)}
            placeholder="和小艾说点什么..."
            disabled={streaming}
          />
          <button type="button" style={stageStyles.disabledButton} disabled>
            语音
          </button>
          <button type="submit" style={stageStyles.primaryButton} disabled={!chatInput.trim() || streaming || !connected}>
            发送
          </button>
        </form>

        <nav className="glass-card" style={stageStyles.bottomNav} aria-label="主舞台导航">
          {bottomTabs.map((tab) => {
            const active = tab === "陪伴";
            return (
              <button
                key={tab}
                type="button"
                style={{ ...stageStyles.navButton, ...(active ? stageStyles.activeNavButton : null) }}
                onClick={() => {
                  if (!active) {
                    console.log(`TODO: 接真实接口 - 打开${tab}`);
                  }
                }}
              >
                {tab}
              </button>
            );
          })}
        </nav>
      </footer>
    </main>
  );
}
