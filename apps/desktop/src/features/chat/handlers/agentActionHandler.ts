import {
  getAgentActionDisplayFields,
  normalizeAgentAction,
} from "../../../services/agentActivity";
import type { StreamHandlerInput } from "../streamDispatcher";

export function agentActionHandler({ messageId, payload, context }: StreamHandlerInput) {
  const { petChat, appendChatEvent, setMessages, upsertAgentAction } = context;
  const action = normalizeAgentAction(payload);
  if (action) {
    upsertAgentAction(action);
    setMessages((current) =>
      current.map((message) => {
        if (message.id !== messageId) {
          return message;
        }
        const existing = message.agent_actions || [];
        return {
          ...message,
          agent_actions: [...existing.filter((item) => item.action_id !== action.action_id), action],
        };
      }),
    );
  }

  const display = action ? getAgentActionDisplayFields(action) : null;
  appendChatEvent(messageId, {
    label: "自动整理活动",
    detail: display
      ? `${display.actionName}：${display.summary} / ${display.riskTierLabel} / ${display.statusLabel}`
      : "收到一条自动整理活动。",
    tone: action?.status === "failed" ? "error" : action?.decision === "auto" ? "success" : "info",
  });

  if (!petChat.replyStartedRef.current && action) {
    petChat.showBubble({
      title: action.decision === "ask" ? "需要确认" : "自动整理",
      message: display?.summary || action.summary || action.title,
      tone: action.status === "failed" ? "error" : "tool",
    });
  }
}
