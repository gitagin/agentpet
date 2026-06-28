import { lazy, Suspense, useState } from "react";
import type { ComponentProps, FormEvent, ReactNode, RefObject } from "react";
import { CircleAlert, HeartPulse, Loader2, MessageSquareText, RefreshCw, Send, ShieldCheck, X } from "lucide-react";
import { Live2DStage } from "../../components/Live2DStage";
import type { Live2DStageView } from "../../components/Live2DStage";
import { EmptyState, Panel } from "../../components/layout";
import type {
  ContinuityStateResponse,
  DesktopSidecarStatus,
  HealthResponse,
} from "../../types";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "../../services/live2dRuntime";
import type { DesktopApi } from "../../services/desktopApi";
import { ConnectionStatusStrip } from "../connection/HealthStatus";
import { VisibleContinuityPanel } from "../continuity";
import { ChatMessageList } from "../chat/ChatMessageList";
import { TaskPanel } from "../tasks/TaskPanel";
import type { AdvancedManagementToolsProps } from "./AdvancedManagementTools";

const AdvancedManagementTools = lazy(() =>
  import("./AdvancedManagementTools").then((module) => ({ default: module.AdvancedManagementTools })),
);

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type AsyncStatus = "idle" | "loading" | "success" | "empty" | "error";

export type ControlWorkflowItem = {
  label: string;
  status: "done" | "active" | "blocked";
  detail: string;
  targetId?: string;
};

type ControlDashboardProps = {
  sidecarStatus: DesktopSidecarStatus | null;
  health: HealthResponse | null;
  notice: Notice | null;
  live2dStage: Live2DStageView;
  live2dAsset: Live2DAssetInfo;
  live2dRuntime: Live2DRuntimeBoundary;
  live2dCanvasRef: RefObject<HTMLCanvasElement>;
  ttsActive: boolean;
  live2dActionKeyOverride: string | null;
  live2dActionTriggerKey: string | null;
  api: DesktopApi;
  firstUseOnboardingPanel: ReactNode;
  controlInput: string;
  hasConnection: boolean;
  streaming: boolean;
  onControlInputChange: (value: string) => void;
  onSubmitControlChat: (event: FormEvent) => void;
  onStopStreaming: () => void;
  pendingManualActivityCount: number;
  agentActionsStatus: AsyncStatus;
  hasAgentActivity: boolean;
  recentAgentActivityCount: number;
  loadingProposals: boolean;
  loadingContinuity: boolean;
  agentActionsError: string;
  activityItems: ReactNode[];
  onRefreshActivity: () => void;
  chatMessageListProps: ComponentProps<typeof ChatMessageList>;
  workflowItems: ControlWorkflowItem[];
  taskPanelProps: ComponentProps<typeof TaskPanel>;
  continuityState: ContinuityStateResponse | null;
  pendingContinuityCount: number;
  onLoadContinuity: () => void;
  onLocateWorkflowTarget: (targetId?: string) => void;
  advancedTools: AdvancedManagementToolsProps;
};

export function ControlDashboard({
  sidecarStatus,
  health,
  notice,
  live2dStage,
  live2dAsset,
  live2dRuntime,
  live2dCanvasRef,
  ttsActive,
  live2dActionKeyOverride,
  live2dActionTriggerKey,
  api,
  firstUseOnboardingPanel,
  controlInput,
  hasConnection,
  streaming,
  onControlInputChange,
  onSubmitControlChat,
  onStopStreaming,
  pendingManualActivityCount,
  agentActionsStatus,
  hasAgentActivity,
  recentAgentActivityCount,
  loadingProposals,
  loadingContinuity,
  agentActionsError,
  activityItems,
  onRefreshActivity,
  chatMessageListProps,
  workflowItems,
  taskPanelProps,
  continuityState,
  pendingContinuityCount,
  onLoadContinuity,
  onLocateWorkflowTarget,
  advancedTools,
}: ControlDashboardProps) {
  const [secondaryToolsOpen, setSecondaryToolsOpen] = useState(false);
  const [supportToolsOpen, setSupportToolsOpen] = useState(false);
  const activityLoading = agentActionsStatus === "loading" || loadingProposals || loadingContinuity;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">陪伴优先</p>
          <h1>先和我说一句话</h1>
        </div>
        <ConnectionStatusStrip sidecarStatus={sidecarStatus} health={health} />
      </header>

      {notice ? (
        <div className={`notice ${notice.tone}`} role="status">
          {notice.tone === "error" ? <CircleAlert size={18} /> : <ShieldCheck size={18} />}
          <span>{notice.message}</span>
        </div>
      ) : null}

      <section className="dashboard-grid">
        <section className="control-pet-stage" aria-label="桌宠陪伴区">
          <Live2DStage
            key={`panel-${live2dAsset.modelId}`}
            stage={live2dStage}
            asset={live2dAsset}
            runtime={live2dRuntime}
            canvasRef={live2dCanvasRef}
            speaking={ttsActive}
            actionKeyOverride={live2dActionKeyOverride}
            actionTriggerKey={live2dActionTriggerKey}
          />
        </section>

        <Panel id="agent-workspace-panel" icon={<MessageSquareText size={18} />} title="今天要跟进的事" className="chat-panel">
          <section className="stack companion-first-panel" aria-label="聊天和最近整理">
            {firstUseOnboardingPanel}
            <div className="section-heading">
              <strong>直接告诉我现在发生了什么</strong>
              <span>我会先陪你聊，之后把值得留下的记忆和整理动作放在下面给你看。</span>
            </div>
            <form className="chat-form" onSubmit={onSubmitControlChat}>
              <input
                value={controlInput}
                onChange={(event) => onControlInputChange(event.target.value)}
                placeholder={hasConnection ? "说一句要跟进的事、要记住的偏好，或让我安排一个提醒..." : "正在等待本地助手连接..."}
                disabled={streaming}
              />
              {streaming ? (
                <button type="button" className="danger" onClick={onStopStreaming}>
                  <X size={16} />
                  停止
                </button>
              ) : (
                <button type="submit" disabled={!controlInput.trim() || !hasConnection}>
                  <Send size={16} />
                  发送
                </button>
              )}
            </form>
            <section id="agent-activity-log" className="stack" aria-label="最近自动整理活动">
              <div className="section-heading">
                <strong>最近自动整理活动</strong>
                <span>
                  {pendingManualActivityCount > 0
                    ? `${pendingManualActivityCount} 个高风险项需要确认；普通自动整理只保留为活动记录。`
                    : agentActionsStatus === "loading"
                      ? "正在刷新活动记录。"
                      : hasAgentActivity
                        ? `最近 ${recentAgentActivityCount} 条活动；可逆动作会提供撤回入口。`
                        : "还没有自动整理活动。"}
                </span>
              </div>
              <div className="button-row">
                <button
                  type="button"
                  className="secondary"
                  onClick={onRefreshActivity}
                  disabled={activityLoading}
                >
                  {activityLoading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                  刷新活动
                </button>
              </div>
              {agentActionsError ? <p className="field-note error">{agentActionsError}</p> : null}
              <div className="proposal-list agent-activity-log-list">
                {activityItems.length > 0 ? (
                  activityItems
                ) : activityLoading ? (
                  <EmptyState text="正在加载最近自动整理活动。" />
                ) : (
                  <EmptyState text="普通自动整理完成后会出现在这里；高风险写入会在这里显示确认入口。" />
                )}
              </div>
            </section>
            <ChatMessageList {...chatMessageListProps} />
          </section>
        </Panel>

        <Panel id="continuity-panel" icon={<HeartPulse size={18} />} title="下次接着聊">
          <section className="stack" aria-label="下次接着聊">
            <div className="section-heading">
              <strong>它只该提醒你真正有用的线索</strong>
              <span>需要你确认的连续话题会在这里露出，不把内部状态表当成首屏内容。</span>
            </div>
            <div className="button-row">
              <button type="button" className="secondary" onClick={onLoadContinuity} disabled={loadingContinuity}>
                {loadingContinuity ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                刷新
              </button>
              {pendingContinuityCount > 0 ? (
                <button type="button" className="secondary" onClick={() => onLocateWorkflowTarget("agent-activity-log")}>
                  <MessageSquareText size={16} />
                  去确认
                </button>
              ) : null}
            </div>
            <dl className="details continuity-state-grid">
              <div>
                <dt>身份特质</dt>
                <dd>{continuityState?.identity_traits || "未确认"}</dd>
              </div>
              <div>
                <dt>关系摘要</dt>
                <dd>{continuityState?.relationship_summary || "未确认"}</dd>
              </div>
              <div>
                <dt>当前情绪</dt>
                <dd>{continuityState?.current_mood || "未确认"}</dd>
              </div>
              <div>
                <dt>情绪惯性</dt>
                <dd>{continuityState?.mood_momentum || "未确认"}</dd>
              </div>
              <div>
                <dt>能量水平</dt>
                <dd>{continuityState?.energy_level || "未确认"}</dd>
              </div>
              <div>
                <dt>下次可接着聊</dt>
                <dd>{continuityState?.unresolved_threads || "无"}</dd>
              </div>
            </dl>
            {pendingContinuityCount > 0 ? (
              <p className="field-note">
                有 {pendingContinuityCount} 个话题等你决定是否下次继续聊；点“去确认”会跳到对应卡片。
              </p>
            ) : (
              <p className="field-note">当前没有待确认的下次接着聊话题。</p>
            )}
          </section>
        </Panel>

        <details
          className="control-support-nav"
          open={supportToolsOpen}
        >
          <summary
            onClick={(event) => {
              event.preventDefault();
              setSupportToolsOpen((open) => !open);
            }}
          >
            <strong>支撑工作台</strong>
            <span>提醒、任务、工作流状态和定位工具收在这里，不抢聊天入口。</span>
          </summary>
          {supportToolsOpen ? (
            <div className="control-support-grid">
              <div className="workflow-grid" aria-label="助手整理状态">
                {workflowItems.map((item) => (
                  <article key={item.label} className={`workflow-card ${item.status}`}>
                    <span className="workflow-state">{formatWorkflowStatus(item.status)}</span>
                    <strong>{item.label}</strong>
                    <p>{item.detail}</p>
                    {item.targetId ? (
                      <button type="button" className="secondary" onClick={() => onLocateWorkflowTarget(item.targetId)}>
                        定位
                      </button>
                    ) : null}
                  </article>
                ))}
              </div>
              <TaskPanel {...taskPanelProps} />
              <VisibleContinuityPanel api={api} className="control-continuity-panel" />
            </div>
          ) : null}
        </details>

        <details
          className="control-secondary-nav"
          open={secondaryToolsOpen}
        >
          <summary
            onClick={(event) => {
              event.preventDefault();
              setSecondaryToolsOpen((open) => !open);
            }}
          >
            <strong>高级管理与诊断</strong>
            <span>连接、模型、知识整理、设置和角色资源还在，但默认不参与首分钟体验。</span>
          </summary>
          {secondaryToolsOpen ? (
            <Suspense fallback={null}>
              <AdvancedManagementTools {...advancedTools} />
            </Suspense>
          ) : null}
        </details>
      </section>
    </main>
  );
}

function formatWorkflowStatus(status: ControlWorkflowItem["status"]): string {
  const labels: Record<ControlWorkflowItem["status"], string> = {
    done: "已就绪",
    active: "进行中",
    blocked: "待处理",
  };
  return labels[status];
}
