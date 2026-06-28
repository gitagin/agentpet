import type { ChatToolEvent, Citation, ModelTestResponse } from "../../types";
import type { LastIndexRun } from "../settings/settingsTypes";
import { formatTaskStatus } from "../tasks/taskReducer";
import { agentLabel, type AgentModelDraft } from "../../services/agentModelDrafts";
import { formatModelTestResult } from "../settings/settingsFormatters";
import type { ControlWorkflowItem } from "./ControlDashboard";

type BuildControlWorkflowItemsInput = {
  agentModelDrafts: AgentModelDraft[];
  agentModelTestResults: Record<string, ModelTestResponse | undefined>;
  hasVaultInitialized: boolean;
  hasIndexSignal: boolean;
  lastIndexRun: LastIndexRun | null;
  hasAgentEventSignal: boolean;
  streaming: boolean;
  latestChatEvent?: ChatToolEvent;
  latestCitation?: Citation;
  latestCitationTargetId?: string;
  pendingManualActivityCount: number;
  hasAgentActivity: boolean;
  hasMemoryConfirmed: boolean;
  automaticActivityCount: number;
  hasContinuityState: boolean;
  pendingContinuityCount: number;
  continuityStateItemCount: number;
};

export function buildControlWorkflowItems({
  agentModelDrafts,
  agentModelTestResults,
  hasVaultInitialized,
  hasIndexSignal,
  lastIndexRun,
  hasAgentEventSignal,
  streaming,
  latestChatEvent,
  latestCitation,
  latestCitationTargetId,
  pendingManualActivityCount,
  hasAgentActivity,
  hasMemoryConfirmed,
  automaticActivityCount,
  hasContinuityState,
  pendingContinuityCount,
  continuityStateItemCount,
}: BuildControlWorkflowItemsInput): ControlWorkflowItem[] {
  const agentWorkflowItems = agentModelDrafts.map((draft) => {
    const testResult = agentModelTestResults[draft.agent_id];
    const tested = testResult?.status === "ok";
    return {
      label: agentLabel(draft.agent_id),
      status: tested ? "done" : draft.configured ? "active" : "blocked",
      detail: tested && testResult
        ? formatModelTestResult(testResult)
        : draft.configured
          ? `${draft.model} 已保存，${draft.masked || "密钥已配置"}，等待试连。`
          : "等待保存提供方、接口地址、模型和密钥。",
    } satisfies ControlWorkflowItem;
  });

  return [
    ...agentWorkflowItems,
    {
      label: "保存与导出",
      status: hasVaultInitialized && hasIndexSignal ? "done" : hasVaultInitialized ? "active" : "blocked",
      detail: lastIndexRun
        ? `最近索引 ${formatTaskStatus(lastIndexRun.status)}，文件 ${lastIndexRun.filesIndexed ?? 0}/${lastIndexRun.filesSeen ?? 0}`
        : hasVaultInitialized
          ? "保存位置已设置，下一步刷新本地索引。"
          : "可选：设置本地导出文件夹，方便之后备份和复盘。",
    },
    {
      label: "助手运行事件",
      status: hasAgentEventSignal ? "done" : streaming ? "active" : "blocked",
      detail: latestChatEvent
        ? `${latestChatEvent.label}：${latestChatEvent.detail}`
        : latestCitation
          ? `引用：${latestCitation.relative_path}`
          : streaming
            ? "正在等待 SSE 工具事件。"
            : "向桌宠提问后显示检索、记忆、任务或引用事件。",
      targetId: latestCitationTargetId,
    },
    {
      label: "自动整理活动",
      status: pendingManualActivityCount > 0 ? "active" : hasAgentActivity || hasMemoryConfirmed ? "done" : "blocked",
      detail:
        pendingManualActivityCount > 0
          ? `${pendingManualActivityCount} 个高风险项待确认；普通自动整理只作为活动记录展示。`
          : automaticActivityCount > 0
            ? `${automaticActivityCount} 条普通自动整理已记录，可在活动流中查看或撤回可逆项。`
            : hasMemoryConfirmed
              ? "已有确认写入的记忆整理记录。"
              : "桌宠自动整理会进入最近活动，高风险写入仍需确认。",
      targetId: "agent-activity-log",
    },
    {
      label: "下次接着聊",
      status: hasContinuityState ? "done" : pendingContinuityCount > 0 ? "active" : "blocked",
      detail:
        pendingContinuityCount > 0
          ? `${pendingContinuityCount} 个话题等你决定是否下次继续聊。`
          : hasContinuityState
            ? `已记住 ${continuityStateItemCount} 条陪伴状态。`
            : "当话题值得下次继续，桌宠会先问你要不要记住。",
      targetId: pendingContinuityCount > 0 ? "agent-activity-log" : "continuity-panel",
    },
  ];
}
