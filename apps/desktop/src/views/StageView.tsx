import { useState, useCallback, useRef } from "react";
import type { CSSProperties, FormEvent, RefObject } from "react";
import { Live2DStage } from "../components/Live2DStage";
import type { Live2DStageView } from "../components/Live2DStage";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "../services/live2dRuntime";
import type { PetBubbleState } from "../features/chat/chatTypes";
import { openPrimaryNavigationTab, primaryNavigationTabs } from "./navigation";

type StageViewProps = {
  live2dStage: Live2DStageView;
  live2dAsset: Live2DAssetInfo;
  live2dRuntime: Live2DRuntimeBoundary;
  live2dCanvasRef: RefObject<HTMLCanvasElement>;
  connected: boolean;
  streaming: boolean;
  bubble?: PetBubbleState | null;
  onSendChat: (text: string, clearInput: () => void) => void | Promise<void>;
  onStopStreaming?: () => void;
  onAdvancePage?: () => void;
  onPausePaging?: () => void;
  onResumePaging?: () => void;
};

const profile = { name: "小艾", mood: "开心 😊" };

function bubbleToneClass(tone: PetBubbleState["tone"]): string {
  if (tone === "error") return "stage-bubble--error";
  if (tone === "tool" || tone === "reminder") return "stage-bubble--info";
  return "";
}

export default function StageView({
  live2dStage,
  live2dAsset,
  live2dRuntime,
  live2dCanvasRef,
  connected,
  streaming,
  bubble,
  onSendChat,
  onStopStreaming,
  onAdvancePage,
  onPausePaging,
  onResumePaging,
}: StageViewProps) {
  const [chatInput, setChatInput] = useState("");
  const bubbleRef = useRef<HTMLDivElement>(null);
  const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

  const handleSubmit = useCallback(
    (event: FormEvent) => {
      event.preventDefault();
      void onSendChat(chatInput, () => setChatInput(""));
    },
    [chatInput, onSendChat],
  );

  const bubbleVisible = Boolean(bubble?.visible);
  const bubbleClass = ["stage-bubble", bubble?.tone ? bubbleToneClass(bubble.tone) : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <main style={S.shell} aria-label="桌面记忆助手主舞台">
      {/* ── Top bar ── */}
      <header style={S.topBar}>
        <div style={S.topLeft}>
          <span style={S.heartIcon}>♡</span>
          <strong>{profile.name}</strong>
          <span style={S.pill}>{profile.mood}</span>
          <span style={S.dot} />
          <span style={S.statusLabel}>{connected ? "在线" : "离线"}</span>
        </div>
        <time style={S.time}>{now}</time>
      </header>

      {/* ── Main stage: Live2D model centered ── */}
      <section style={S.mainStage} aria-label="Live2D 陪伴模型主舞台">
        {bubbleVisible && (
          <div
            ref={bubbleRef}
            className={bubbleClass}
            style={S.bubble}
            role="status"
            aria-live="polite"
            onClick={onAdvancePage}
            onMouseEnter={onPausePaging}
            onMouseLeave={onResumePaging}
          >
            <div style={S.bubbleHeader}>
              <strong>{bubble!.title}</strong>
              {bubble!.continueHint ? <span style={S.bubblePage}>{bubble!.continueHint}</span> : null}
            </div>
            <div style={S.bubbleText}>{bubble!.message}</div>
            {bubble!.continueHint ? <div style={S.bubbleTapHint}>点击翻页</div> : null}
          </div>
        )}

        <Live2DStage
          key={`stage-${live2dAsset.modelId}`}
          stage={live2dStage}
          asset={live2dAsset}
          runtime={live2dRuntime}
          canvasRef={live2dCanvasRef}
          variant="stage"
        />
      </section>

      {/* ── Footer: input + nav ── */}
      <footer style={S.footer}>
        <form style={S.chatForm} onSubmit={handleSubmit}>
          <input
            style={S.chatInput}
            value={chatInput}
            onChange={(event) => setChatInput(event.target.value)}
            placeholder="和小艾说点什么..."
            disabled={streaming}
            aria-label="聊天输入"
          />
          <button type="button" style={S.voiceBtn} disabled>
            语音
          </button>
          {streaming ? (
            <button type="button" style={S.stopBtn} onClick={onStopStreaming}>
              停止
            </button>
          ) : (
            <button type="submit" style={S.sendBtn} disabled={!chatInput.trim() || !connected}>
              发送
            </button>
          )}
        </form>

        <nav style={S.bottomNav} aria-label="主导航">
          {primaryNavigationTabs.map((tab) => {
            const active = tab === "桌宠";
            return (
              <button
                key={tab}
                type="button"
                style={{ ...S.navBtn, ...(active ? S.navBtnActive : {}) }}
                onClick={() => {
                  if (!active) {
                    openPrimaryNavigationTab(tab);
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

/* ── Inline style dictionary ── */
const S: Record<string, CSSProperties> = {
  shell: {
    height: "100vh",
    display: "grid",
    gridTemplateRows: "44px minmax(0, 1fr) auto",
    background:
      "radial-gradient(circle at 50% 30%, rgba(255,220,231,0.55), transparent 40%)," +
      "radial-gradient(circle at 50% 80%, rgba(224,203,255,0.4), transparent 38%)," +
      "linear-gradient(180deg, rgba(255,247,242,0.72) 0%, rgba(255,238,245,0.65) 42%, rgba(242,236,255,0.68) 100%)," +
      "url(/images/home.png) center/cover no-repeat",
    color: "var(--color-text, #2b2931)",
    fontFamily: "Inter, 'Segoe UI', system-ui, sans-serif",
    boxSizing: "border-box",
    overflow: "hidden",
  },

  /* Top bar */
  topBar: {
    height: 44,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 20px",
    background: "rgba(255,255,255,0.42)",
    backdropFilter: "blur(14px)",
    WebkitBackdropFilter: "blur(14px)",
    borderBottom: "1px solid rgba(255,255,255,0.48)",
    zIndex: 20,
    flexShrink: 0,
  },
  topLeft: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    fontWeight: 700,
    fontSize: 15,
    color: "#332333",
  },
  heartIcon: { color: "var(--brand, #c05f87)", fontSize: 16, lineHeight: 1 },
  pill: {
    display: "inline-flex",
    alignItems: "center",
    padding: "2px 10px",
    borderRadius: 999,
    background: "rgba(255,255,255,0.64)",
    border: "1px solid rgba(255,255,255,0.55)",
    fontSize: 11,
    fontWeight: 600,
    color: "var(--muted, #7a6670)",
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    background: "var(--success, #4f9b72)",
    boxShadow: "0 0 0 4px rgba(79,155,114,0.18)",
    flexShrink: 0,
  },
  statusLabel: { fontSize: 12, fontWeight: 600, color: "var(--muted, #7a6670)" },
  time: {
    fontSize: 12,
    fontWeight: 600,
    color: "var(--muted, #7a6670)",
    padding: "2px 10px",
    borderRadius: 999,
    background: "rgba(255,255,255,0.55)",
    border: "1px solid rgba(255,255,255,0.45)",
  },

  /* Main stage */
  mainStage: {
    position: "relative",
    minHeight: 0,
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    overflow: "hidden",
    isolation: "isolate",
  },

  /* Bubble — positioned at top of stage, above model */
  bubble: {
    position: "absolute",
    zIndex: 30,
    top: 12,
    left: "50%",
    transform: "translateX(-50%)",
    width: "min(480px, calc(100% - 48px))",
    padding: "12px 16px",
    borderRadius: 20,
    background: "rgba(255,255,255,0.88)",
    backdropFilter: "blur(18px)",
    WebkitBackdropFilter: "blur(18px)",
    boxShadow: "0 14px 36px rgba(119,77,104,0.15)",
    border: "1px solid rgba(255,255,255,0.6)",
    cursor: "pointer",
    userSelect: "none",
    transition: "opacity 0.22s ease, transform 0.22s ease",
  },
  bubbleHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 10,
    marginBottom: 4,
    fontSize: 12,
    fontWeight: 700,
    color: "#1f3f48",
  },
  bubblePage: { flex: "0 0 auto", color: "rgba(49,83,92,0.45)", fontSize: 10, fontWeight: 500 },
  bubbleText: {
    fontSize: 13.5,
    lineHeight: 1.48,
    color: "#31535c",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    overflowWrap: "anywhere",
    maxHeight: 108,
    overflow: "hidden",
  },
  bubbleTapHint: { marginTop: 6, fontSize: 10, color: "rgba(49,83,92,0.38)", textAlign: "right" },

  /* Footer */
  footer: { display: "grid", gap: 0, padding: "10px 16px 4px", zIndex: 20, flexShrink: 0 },
  chatForm: {
    display: "flex",
    gap: 8,
    padding: "8px 14px",
    borderRadius: 22,
    background: "rgba(255,255,255,0.64)",
    backdropFilter: "blur(14px)",
    WebkitBackdropFilter: "blur(14px)",
    border: "1px solid rgba(255,255,255,0.54)",
    boxShadow: "0 8px 24px rgba(119,77,104,0.08)",
  },
  chatInput: {
    flex: 1,
    border: "none",
    borderRadius: 999,
    padding: "0 16px",
    minHeight: 40,
    color: "var(--color-text, #2b2931)",
    background: "rgba(255,255,255,0.72)",
    fontFamily: "inherit",
    fontSize: 13.5,
    outline: "none",
  },
  voiceBtn: {
    border: "1px solid rgba(172,124,141,0.2)",
    borderRadius: 999,
    padding: "0 14px",
    color: "var(--muted, #7a6670)",
    background: "rgba(255,255,255,0.68)",
    cursor: "default",
    fontSize: 13,
    fontWeight: 600,
    whiteSpace: "nowrap",
  },
  sendBtn: {
    border: "none",
    borderRadius: 999,
    padding: "0 20px",
    color: "#fff",
    background: "linear-gradient(135deg, #e680a7, var(--brand-strong, #8d4f86))",
    boxShadow: "0 8px 18px rgba(157,80,128,0.18)",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 13,
    whiteSpace: "nowrap",
  },
  stopBtn: {
    border: "none",
    borderRadius: 999,
    padding: "0 18px",
    color: "#fff",
    background: "var(--danger, #b54c5f)",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 13,
    whiteSpace: "nowrap",
  },

  /* Bottom nav */
  bottomNav: {
    height: 48,
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    gap: 2,
    padding: "4px 0 6px",
  },
  navBtn: {
    border: "none",
    borderRadius: 999,
    padding: "7px 16px",
    color: "var(--muted, #7a6670)",
    background: "transparent",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
    transition: "background 0.15s ease, color 0.15s ease",
  },
  navBtnActive: {
    color: "var(--brand, #c05f87)",
    background: "rgba(192,95,135,0.1)",
    fontWeight: 700,
  },
};
