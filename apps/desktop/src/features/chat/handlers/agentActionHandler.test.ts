import { describe, expect, it, vi } from "vitest";

import { agentActionHandler } from "./agentActionHandler";

describe("agentActionHandler", () => {
  it("uses localized automatic-organization copy in pet bubbles", () => {
    const showBubble = vi.fn();
    const appendChatEvent = vi.fn();
    const setMessages = vi.fn();
    const upsertAgentAction = vi.fn();

    agentActionHandler({
      messageId: "assistant-1",
      sseEvent: { event: "agent_action", data: "" },
      payload: {
        action_id: "action-1",
        action_type: "chat.auto_memory.skip",
        decision: "auto",
        status: "skipped",
        title: "Skipped automatic organization",
        summary:
          "Skipped because automatic diary, structured memory, long-term memory, and Wiki organization are disabled; no local asset was written.",
        metadata: { skipped_reason: "automation_disabled" },
      },
      context: {
        petChat: {
          replyStartedRef: { current: false },
          showBubble,
        },
        appendChatEvent,
        setMessages,
        upsertAgentAction,
      },
    } as never);

    const bubbleMessage = showBubble.mock.calls[0][0].message;
    const eventDetail = appendChatEvent.mock.calls[0][1].detail;

    expect(bubbleMessage).not.toContain("Skipped because");
    expect(bubbleMessage).not.toContain("automatic diary");
    expect(eventDetail).not.toContain("Skipped because");
    expect(eventDetail).not.toContain("automatic diary");
  });
});
