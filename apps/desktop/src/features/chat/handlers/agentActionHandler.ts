import {
  formatAgentActionRiskTier,
  formatAgentActionStatus,
  formatAgentActionType,
  normalizeAgentAction,
} from "../../../services/agentActivity";
import type { StreamHandlerInput } from "../streamDispatcher";

export function agentActionHandler({ messageId, payload, context }: StreamHandlerInput) {
  const { petChat, appendChatEvent, upsertAgentAction } = context;
  const action = normalizeAgentAction(payload);
  if (action) {
    upsertAgentAction(action);
  }
  const detail = action
    ? `${formatAgentActionType(action.action_type)}：${action.summary || action.title} / ${formatAgentActionRiskTier(action.risk_tier)} / ${formatAgentActionStatus(action.status)}`
    : "收到一条自动整理活动。";
  appendChatEvent(messageId, {
    label: "自动整理活动",
    detail,
    tone: action?.status === "failed" ? "error" : action?.decision === "auto" ? "success" : "info",
  });
  if (!petChat.replyStartedRef.current && action) {
    petChat.showBubble({
      title: action.decision === "ask" ? "需要确认" : "自动整理",
      message: action.summary || action.title,
      tone: action.status === "failed" ? "error" : "tool",
    });
  }
}
