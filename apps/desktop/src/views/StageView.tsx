import { useCallback, useState } from "react";
import type { CSSProperties, FormEvent, RefObject } from "react";
import {
  BookOpen,
  CalendarCheck,
  ListPlus,
  Search,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { Live2DStage } from "../components/Live2DStage";
import type { Live2DStageView } from "../components/Live2DStage";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "../services/live2dRuntime";
import type { PetBubbleState } from "../features/chat/chatTypes";
import { PetReplyBubble } from "../features/chat/PetReplyBubble";
import { BottomNav } from "./BottomNav";

type StageRoute = "agent" | "memory" | "world";

type StageAction = {
  label: string;
  detail: string;
  route: StageRoute;
  icon: LucideIcon;
};

type StageViewProps = {
  live2dStage: Live2DStageView;
  live2dAsset: Live2DAssetInfo;
  live2dRuntime: Live2DRuntimeBoundary;
  live2dCanvasRef: RefObject<HTMLCanvasElement>;
  connected: boolean;
  streaming: boolean;
  bubble?: PetBubbleState | null;
  onSendChat: (text: string, clearInput: () => void) => void | Promise<void | boolean>;
  onStopStreaming?: () => void;
  onPreviousPage?: () => void;
  onAdvancePage?: () => void;
  onPausePaging?: () => void;
  onResumePaging?: () => void;
  ttsSpeaking?: boolean;
  active?: boolean;
};

const profile = { name: "桌面记忆助手", mood: "待命" };

const stageActions: StageAction[] = [
  {
    label: "新建任务",
    detail: "提醒、截止时间、步骤、日志",
    route: "agent",
    icon: ListPlus,
  },
  {
    label: "记住这件事",
    detail: "保存为长期记忆",
    route: "memory",
    icon: Sparkles,
  },
  {
    label: "整理知识",
    detail: "草拟或更新 Wiki 页面",
    route: "world",
    icon: BookOpen,
  },
  {
    label: "今日复盘",
    detail: "今天、周报、月报",
    route: "memory",
    icon: CalendarCheck,
  },
  {
    label: "搜索记忆",
    detail: "事实、日记、Wiki 上下文",
    route: "memory",
    icon: Search,
  },
];

function openStageRoute(route: StageRoute) {
  window.location.hash = `#${route}`;
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
  onPreviousPage,
  onAdvancePage,
  onPausePaging,
  onResumePaging,
  ttsSpeaking = false,
  active = true,
}: StageViewProps) {
  const [chatInput, setChatInput] = useState("");
  const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

  const handleSubmit = useCallback(
    (event: FormEvent) => {
      event.preventDefault();
      void onSendChat(chatInput, () => setChatInput(""));
    },
    [chatInput, onSendChat],
  );

  const bubbleVisible = Boolean(bubble?.visible);

  return (
    <main className="stage-command-shell" style={S.shell} aria-label="桌宠主舞台">
      <header style={S.topBar}>
        <div style={S.topLeft}>
          <span style={S.heartIcon}>*</span>
          <strong>{profile.name}</strong>
          <span style={S.pill}>{profile.mood}</span>
          <span style={S.dot} />
          <span style={S.statusLabel}>{connected ? "在线" : "离线"}</span>
        </div>
        <time style={S.time}>{now}</time>
      </header>

      <section className="stage-main-view stage-command-layout" style={S.mainStage} aria-label="主舞台">
        <section className="stage-command-panel" aria-label="功能指挥中心">
          <div className="stage-command-heading">
            <p>从真实工作流开始</p>
            <h1>首页</h1>
          </div>
          <div className="stage-action-grid">
            {stageActions.map((action) => {
              const Icon = action.icon;
              return (
                <button
                  key={action.label}
                  type="button"
                  className="stage-action-card"
                  data-stage-route={action.route}
                  onClick={() => openStageRoute(action.route)}
                >
                  <Icon aria-hidden="true" size={20} />
                  <span>
                    <strong>{action.label}</strong>
                    <small>{action.detail}</small>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="stage-live2d-zone" aria-label="Live2D 桌宠">
          <div className="stage-pet-anchor">
            {bubbleVisible ? (
              <PetReplyBubble
                bubble={bubble!}
                className="stage-agent-bubble"
                onPreviousPage={() => onPreviousPage?.()}
                onAdvancePage={() => onAdvancePage?.()}
                onPausePaging={() => onPausePaging?.()}
                onResumePaging={() => onResumePaging?.()}
              />
            ) : null}
            <Live2DStage
              key={`stage-${live2dAsset.modelId}`}
              stage={live2dStage}
              asset={live2dAsset}
              runtime={live2dRuntime}
              canvasRef={live2dCanvasRef}
              variant="stage"
              speaking={ttsSpeaking}
              active={active}
            />
          </div>
        </section>
      </section>

      <footer style={S.footer}>
        <form style={S.chatForm} onSubmit={handleSubmit} aria-label="舞台聊天表单">
          <input
            style={S.chatInput}
            value={chatInput}
            onChange={(event) => setChatInput(event.target.value)}
            placeholder="直接提问，或从上方工作流开始..."
            disabled={streaming}
            aria-label="聊天输入"
          />
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

        <BottomNav activeTab="首页" />
      </footer>
    </main>
  );
}

const S: Record<string, CSSProperties> = {
  shell: {
    position: "relative",
    height: "100vh",
    display: "grid",
    gridTemplateRows: "44px minmax(0, 1fr) auto",
    background: "url(/images/home.png) center/cover no-repeat",
    color: "var(--color-text, #2b2931)",
    fontFamily: "Inter, 'Segoe UI', system-ui, sans-serif",
    boxSizing: "border-box",
    overflow: "hidden",
  },
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
  mainStage: {
    position: "relative",
    minHeight: 0,
    overflow: "visible",
    isolation: "isolate",
  },
  footer: {
    display: "grid",
    justifyItems: "center",
    gap: 0,
    padding: "10px 16px 4px",
    zIndex: 20,
    flexShrink: 0,
  },
  chatForm: {
    display: "flex",
    gap: 8,
    width: "min(420px, calc(100vw - 44px))",
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
};
