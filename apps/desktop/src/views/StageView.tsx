import { useCallback, useRef, useState } from "react";
import type { CSSProperties, FormEvent, RefObject } from "react";
import {
  BookOpen,
  CalendarCheck,
  FolderKanban,
  HeartPulse,
  MessageSquareText,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { Live2DStage } from "../components/Live2DStage";
import type { Live2DStageView } from "../components/Live2DStage";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "../services/live2dRuntime";
import type { DesktopApi } from "../services/desktopApi";
import type { PetBubbleState } from "../features/chat/chatTypes";
import { PetReplyBubble } from "../features/chat/PetReplyBubble";
import { VisibleContinuityPanel } from "../features/continuity";
import { HalfbodyPetPortrait } from "../features/halfbody/HalfbodyPetPortrait";
import type { HalfbodyPetPortraitHandle } from "../features/halfbody/HalfbodyPetPortrait";
import { productCopy } from "../productCopy";
import { BottomNav } from "./BottomNav";

type StageRoute = "agent" | "chat" | "growth" | "memory" | "settings" | "world";
type StagePortraitRenderer = "halfbody" | "live2d";

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
  live2dActionKeyOverride?: string | null;
  live2dActionTriggerKey?: string | null;
  portraitRenderer?: StagePortraitRenderer;
  active?: boolean;
  api?: DesktopApi;
};

const profile = { name: productCopy.displayName, mood: "本地待命" };
const defaultStagePortraitRenderer: StagePortraitRenderer = "halfbody";

const stageActions: StageAction[] = [
  {
    label: "陪我聊聊",
    detail: "把现在的想法、状态或没说完的话交给我",
    route: "chat",
    icon: MessageSquareText,
  },
  {
    label: "看看记忆",
    detail: "查看来源、理由和可撤回记录",
    route: "memory",
    icon: CalendarCheck,
  },
  {
    label: "设置边界",
    detail: "管理保存规则、模型连接和本地资料",
    route: "settings",
    icon: Settings,
  },
];

const advancedStageActions: StageAction[] = [
  {
    label: "成长记录",
    detail: "查看长期陪伴状态和变化记录",
    route: "growth",
    icon: HeartPulse,
  },
  {
    label: "提醒和待办",
    detail: "管理提醒、待办和执行日志",
    route: "agent",
    icon: FolderKanban,
  },
  {
    label: "资料工具",
    detail: "维护本地资料整理和归档",
    route: "world",
    icon: BookOpen,
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
  live2dActionKeyOverride = null,
  live2dActionTriggerKey = null,
  portraitRenderer = defaultStagePortraitRenderer,
  active = true,
  api,
}: StageViewProps) {
  const [chatInput, setChatInput] = useState("");
  const halfbodyPortraitRef = useRef<HalfbodyPetPortraitHandle>(null);
  const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

  const handleSubmit = useCallback(
    (event: FormEvent) => {
      event.preventDefault();
      void onSendChat(chatInput, () => setChatInput(""));
    },
    [chatInput, onSendChat],
  );
  const handleContinuePrompt = useCallback(
    (prompt: string) => {
      void onSendChat(prompt, () => setChatInput(""));
    },
    [onSendChat],
  );

  const bubbleVisible = Boolean(bubble?.visible);

  return (
    <main className="stage-command-shell" style={S.shell} aria-label="桌宠主舞台">
      <header className="stage-topbar" style={S.topBar}>
        <div className="stage-brand-line" style={S.topLeft}>
          <span style={S.heartIcon} aria-hidden="true" />
          <strong>{profile.name}</strong>
          <span style={S.pill}>{profile.mood}</span>
          <span style={S.dot} />
          <span className="stage-status-label" style={S.statusLabel}>
            {connected ? "在线" : "离线"}
          </span>
        </div>
        <time className="stage-local-time" style={S.time}>
          {now}
        </time>
      </header>

      <section className={`stage-main-view stage-command-layout${api ? " has-outcome" : ""}`} style={S.mainStage} aria-label="主舞台">
        {api ? (
          <section className="stage-outcome-panel" aria-label="首页整理结果">
            <VisibleContinuityPanel
              api={api}
              autoLoad={active}
              className="stage-continuity-panel"
              onContinuePrompt={handleContinuePrompt}
            />
          </section>
        ) : null}

        <section className="stage-command-panel" aria-label="陪伴入口">
          <div className="stage-command-heading">
            <span className="stage-command-kicker">今日入口</span>
            <p>{productCopy.promise}</p>
            <h1>今天想从哪里继续？</h1>
          </div>
          <div className="stage-value-list" style={S.valueList} aria-label="陪伴承诺">
            {productCopy.coreValues.map((item) => (
              <span key={item.title} style={S.valueItem}>
                {item.title}
              </span>
            ))}
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
          <details className="stage-advanced-routes">
            <summary>更多和高级</summary>
            <div className="stage-action-grid compact">
              {advancedStageActions.map((action) => {
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
          </details>
        </section>

        <section className="stage-live2d-zone" aria-label="桌宠形象">
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
            {portraitRenderer === "halfbody" ? (
              <HalfbodyPetPortrait ref={halfbodyPortraitRef} active={active} />
            ) : (
              <Live2DStage
                key={`stage-${live2dAsset.modelId}`}
                stage={live2dStage}
                asset={live2dAsset}
                runtime={live2dRuntime}
                canvasRef={live2dCanvasRef}
                variant="stage"
                speaking={ttsSpeaking}
                actionKeyOverride={live2dActionKeyOverride}
                actionTriggerKey={live2dActionTriggerKey}
                active={active}
              />
            )}
          </div>
        </section>
      </section>

      <footer className="stage-footer" style={S.footer}>
        <form className="stage-chat-form" style={S.chatForm} onSubmit={handleSubmit} aria-label="舞台聊天表单">
          <input
            className="stage-chat-input"
            style={S.chatInput}
            value={chatInput}
            onChange={(event) => setChatInput(event.target.value)}
            placeholder={productCopy.chatPage.inputPlaceholder}
            disabled={streaming}
            aria-label="聊天输入"
          />
          {streaming ? (
            <button className="stage-stop-button" type="button" style={S.stopBtn} onClick={onStopStreaming}>
              停止
            </button>
          ) : (
            <button className="stage-send-button" type="submit" style={S.sendBtn} disabled={!chatInput.trim() || !connected}>
              发送
            </button>
          )}
        </form>

        <BottomNav activeTab="首页" visible={active} />
      </footer>
    </main>
  );
}

const S: Record<string, CSSProperties> = {
  shell: {
    position: "relative",
    minHeight: "100dvh",
    display: "grid",
    gridTemplateRows: "52px minmax(0, 1fr) auto",
    background: "url(/images/home.png) center/cover no-repeat, transparent",
    color: "var(--text, #20292f)",
    fontFamily: "var(--font-sans, 'Segoe UI', 'Microsoft YaHei', system-ui, sans-serif)",
    boxSizing: "border-box",
    overflow: "hidden",
  },
  topBar: {
    minHeight: 52,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    padding: "0 22px",
    background: "rgba(255,255,255,0.58)",
    backdropFilter: "blur(12px)",
    WebkitBackdropFilter: "blur(12px)",
    borderBottom: "1px solid rgba(55,73,82,0.12)",
    zIndex: 20,
    flexShrink: 0,
  },
  topLeft: {
    display: "flex",
    alignItems: "center",
    gap: 9,
    minWidth: 0,
    fontWeight: 700,
    fontSize: 14,
    color: "var(--text, #20292f)",
  },
  heartIcon: {
    width: 10,
    height: 10,
    borderRadius: 999,
    background: "var(--brand, #8f4266)",
    boxShadow: "0 0 0 4px rgba(143,66,102,0.12)",
    flexShrink: 0,
  },
  pill: {
    display: "inline-flex",
    alignItems: "center",
    padding: "3px 9px",
    borderRadius: 999,
    background: "rgba(248,251,250,0.88)",
    border: "1px solid rgba(55,73,82,0.12)",
    fontSize: 11,
    fontWeight: 700,
    color: "var(--muted, #7a6670)",
    whiteSpace: "nowrap",
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
    fontWeight: 700,
    color: "var(--muted, #7a6670)",
    padding: "3px 10px",
    borderRadius: 999,
    background: "rgba(248,251,250,0.88)",
    border: "1px solid rgba(55,73,82,0.12)",
    whiteSpace: "nowrap",
  },
  mainStage: {
    position: "relative",
    minHeight: 0,
    overflow: "visible",
    isolation: "isolate",
  },
  valueList: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 0,
  },
  valueItem: {
    borderRadius: 999,
    border: "1px solid rgba(143,66,102,0.16)",
    background: "rgba(255,255,255,0.72)",
    color: "var(--brand-strong, #663353)",
    fontSize: 11,
    fontWeight: 800,
    lineHeight: 1.2,
    padding: "5px 9px",
  },
  footer: {
    display: "grid",
    justifyItems: "center",
    gap: 6,
    padding: "8px 16px 0",
    zIndex: 20,
    flexShrink: 0,
  },
  chatForm: {
    display: "flex",
    gap: 10,
    width: "min(560px, calc(100vw - 44px))",
    padding: "9px 10px 9px 14px",
    borderRadius: 28,
    background: "rgba(255,255,255,0.74)",
    backdropFilter: "blur(12px)",
    WebkitBackdropFilter: "blur(12px)",
    border: "1px solid rgba(55,73,82,0.14)",
    boxShadow: "0 16px 36px rgba(38,58,67,0.12)",
  },
  chatInput: {
    flex: 1,
    border: "none",
    borderRadius: 999,
    padding: "0 14px",
    minHeight: 42,
    color: "var(--text, #20292f)",
    background: "rgba(248,251,250,0.76)",
    fontFamily: "inherit",
    fontSize: 14,
    outline: "none",
  },
  sendBtn: {
    border: "none",
    borderRadius: 999,
    minHeight: 42,
    padding: "0 18px",
    color: "#fff",
    background: "var(--brand, #8f4266)",
    boxShadow: "0 10px 20px rgba(86,54,70,0.14)",
    cursor: "pointer",
    fontWeight: 800,
    fontSize: 13,
    whiteSpace: "nowrap",
  },
  stopBtn: {
    border: "none",
    borderRadius: 999,
    minHeight: 42,
    padding: "0 16px",
    color: "#fff",
    background: "var(--danger, #b54c5f)",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 13,
    whiteSpace: "nowrap",
  },
};
