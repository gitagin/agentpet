import type { SetStateAction } from "react";
import { describe, expect, it, vi } from "vitest";

import type { SseEvent } from "../../services/sse";
import type { ChatMessage } from "../../types";
import { createAssistantReplyTextFilter, normalizeVisibleAssistantReplyText, stripAssistantHiddenReplyText } from "./assistantReplyVisibility";
import { applyStreamEvent, type StreamDispatcherContext } from "./streamDispatcher";
import type { PetChatBubbleController } from "./usePetChatBubble";

function createHarness() {
  let messages: ChatMessage[] = [
    {
      id: "assistant-1",
      role: "assistant",
      content: "",
      status: "partial",
    },
  ];
  const filter = createAssistantReplyTextFilter();
  const assistantReplyRef = { current: "" };
  const assistantHiddenReplyTextsRef = { current: [] as string[] };
  const replyStartedRef = { current: false };
  const petChat = {
    assistantReplyRef,
    assistantHiddenReplyTextsRef,
    latestContinuitySignalRef: { current: null },
    replyStartedRef,
    markStreamEventReceived: vi.fn(),
    appendAssistantReplyText: vi.fn((text: string) => {
      const visibleText = filter.append(text);
      const hiddenTexts = filter.takeHiddenTexts();
      if (hiddenTexts.length > 0) {
        assistantHiddenReplyTextsRef.current = [...assistantHiddenReplyTextsRef.current, ...hiddenTexts];
      }
      if (visibleText) {
        assistantReplyRef.current = normalizeVisibleAssistantReplyText(`${assistantReplyRef.current}${visibleText}`);
      }
      return visibleText;
    }),
    setAssistantReplyText: vi.fn((text: string) => {
      filter.reset();
      assistantReplyRef.current = stripAssistantHiddenReplyText(text);
      const finalFilter = createAssistantReplyTextFilter();
      finalFilter.append(text);
      assistantHiddenReplyTextsRef.current = finalFilter.takeHiddenTexts();
      return assistantReplyRef.current;
    }),
    setReplyPagesFromText: vi.fn(),
    showBubble: vi.fn(),
    scheduleStreamWatchdog: vi.fn(),
    failStream: vi.fn(),
    startReplyPaging: vi.fn(),
    showContinuityPresenceBubble: vi.fn(),
  } as unknown as PetChatBubbleController;
  const context = {
    petChat,
    setMessages: (update: SetStateAction<ChatMessage[]>) => {
      messages = typeof update === "function" ? update(messages) : update;
    },
    appendChatEvent: vi.fn(),
    upsertAgentAction: vi.fn(),
    setLatestContinuitySignal: vi.fn(),
    upsertChatContinuitySignal: vi.fn(),
    normalizeContinuitySignal: vi.fn(),
    upsertContinuityProposal: vi.fn(),
    upsertChatContinuityProposal: vi.fn(),
    normalizeContinuityProposal: vi.fn(),
    formatContinuityKind: vi.fn(),
    upsertProposalFromPayload: vi.fn(),
    upsertChatMemoryProposal: vi.fn(),
    upsertChatWikiProposal: vi.fn(),
    addTaskFromChat: vi.fn(),
    triggerLive2DTaskStage: vi.fn(),
    onVisibleAssistantReply: vi.fn(),
  } as unknown as StreamDispatcherContext;

  return {
    context,
    petChat,
    get messages() {
      return messages;
    },
  };
}

function event(name: string, payload: Record<string, unknown>): SseEvent {
  return { event: name, data: JSON.stringify(payload) };
}

describe("applyStreamEvent assistant reply visibility", () => {
  it("filters parenthetical text across streamed token chunks", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("token", { token: "你好（" }), harness.context);
    applyStreamEvent("assistant-1", event("token", { token: "微笑）我在" }), harness.context);

    expect(harness.messages[0].content).toBe("你好我在");
    expect(harness.messages[0].content).not.toContain("微笑");
    expect(harness.messages[0].live2d_action_hints).toEqual(["微笑"]);
    expect(harness.petChat.replyStartedRef.current).toBe(true);
    expect(harness.petChat.setReplyPagesFromText).toHaveBeenLastCalledWith("你好我在", { preserveCurrentPage: true });
  });

  it("notifies once when the first visible streamed reply appears", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("token", { token: "hello" }), harness.context);
    applyStreamEvent("assistant-1", event("token", { token: " again" }), harness.context);

    expect(harness.context.onVisibleAssistantReply).toHaveBeenCalledTimes(1);
  });

  it("reads OpenAI-compatible streamed delta content", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("message", { choices: [{ delta: { content: "你好，我在。" } }] }), harness.context);

    expect(harness.messages[0].content).toBe("你好，我在。");
    expect(harness.petChat.replyStartedRef.current).toBe(true);
    expect(harness.context.onVisibleAssistantReply).toHaveBeenCalledTimes(1);
  });

  it("records continuity proposals without replacing the pending answer bubble", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("continuity_proposal", { summary: "continue later" }), harness.context);

    expect(harness.context.appendChatEvent).toHaveBeenCalled();
    expect(harness.petChat.showBubble).not.toHaveBeenCalled();
    expect(harness.petChat.scheduleStreamWatchdog).not.toHaveBeenCalled();
    expect(harness.petChat.replyStartedRef.current).toBe(false);
  });

  it("records continuity signals without replacing the pending answer bubble", () => {
    const harness = createHarness();
    const signal = {
      kind: "open_thread",
      title: "下次接着聊",
      summary: "我还记着这个未完话题。",
      intensity: "medium",
      display_hint: "只在本机提示，不会写入本地文件。",
      source_state_keys: ["unresolved_threads"],
    };
    vi.mocked(harness.context.normalizeContinuitySignal).mockReturnValue(signal);

    applyStreamEvent("assistant-1", event("continuity_signal", signal), harness.context);

    expect(harness.context.setLatestContinuitySignal).toHaveBeenCalledWith(signal);
    expect(harness.context.upsertChatContinuitySignal).toHaveBeenCalledWith("assistant-1", signal);
    expect(harness.context.appendChatEvent).toHaveBeenCalledWith("assistant-1", expect.objectContaining({ label: "下次接着聊" }));
    expect(harness.petChat.showBubble).not.toHaveBeenCalled();
    expect(harness.petChat.showContinuityPresenceBubble).not.toHaveBeenCalled();
    expect(harness.petChat.scheduleStreamWatchdog).not.toHaveBeenCalled();
    expect(harness.petChat.replyStartedRef.current).toBe(false);
  });

  it("filters single-star action text across streamed token chunks", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("token", { token: "你好*" }), harness.context);
    applyStreamEvent("assistant-1", event("token", { token: "微笑*我在" }), harness.context);

    expect(harness.messages[0].content).toBe("你好我在");
    expect(harness.messages[0].content).not.toContain("微笑");
    expect(harness.messages[0].content).not.toContain("*");
    expect(harness.messages[0].live2d_action_hints).toEqual(["微笑"]);
    expect(harness.petChat.replyStartedRef.current).toBe(true);
    expect(harness.petChat.setReplyPagesFromText).toHaveBeenLastCalledWith("你好我在", { preserveCurrentPage: true });
  });

  it("does not start a visible reply for hidden-only streamed text", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("token", { token: "（微笑）" }), harness.context);

    expect(harness.messages[0].content).toBe("");
    expect(harness.messages[0].live2d_action_hints).toEqual(["微笑"]);
    expect(harness.petChat.replyStartedRef.current).toBe(false);
    expect(harness.petChat.setReplyPagesFromText).not.toHaveBeenCalled();
  });

  it("does not notify visible reply start for ASCII hidden-only streamed text", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("token", { token: "(smile)" }), harness.context);

    expect(harness.context.onVisibleAssistantReply).not.toHaveBeenCalled();
  });

  it("notifies visible reply start for final reply_ready text", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("reply_ready", { text: "(smile)Hello." }), harness.context);

    expect(harness.messages[0]).toMatchObject({ content: "Hello.", status: "completed" });
    expect(harness.context.onVisibleAssistantReply).toHaveBeenCalledTimes(1);
  });

  it("reads OpenAI-compatible final message content", () => {
    const harness = createHarness();

    applyStreamEvent(
      "assistant-1",
      event("reply_ready", { choices: [{ message: { content: "这是最终回复。" } }] }),
      harness.context,
    );

    expect(harness.messages[0]).toMatchObject({ content: "这是最终回复。", status: "completed" });
    expect(harness.context.onVisibleAssistantReply).toHaveBeenCalledTimes(1);
  });

  it("does not let a trailing done event overwrite an already visible reply", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("token", { token: "真正的回答。" }), harness.context);
    applyStreamEvent("assistant-1", event("done", { text: "done" }), harness.context);

    expect(harness.messages[0]).toMatchObject({ content: "真正的回答。", status: "completed" });
    expect(harness.petChat.setAssistantReplyText).not.toHaveBeenCalledWith("done");
  });

  it("still completes from a done event when no visible reply has started", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("done", { text: "最终回答。" }), harness.context);

    expect(harness.messages[0]).toMatchObject({ content: "最终回答。", status: "completed" });
    expect(harness.petChat.setAssistantReplyText).toHaveBeenCalledWith("最终回答。");
  });

  it("filters final reply_ready text before completing the message", () => {
    const harness = createHarness();

    applyStreamEvent("assistant-1", event("reply_ready", { text: "（抱枕）你好，我在。" }), harness.context);

    expect(harness.messages[0]).toMatchObject({ content: "你好，我在。", status: "completed" });
    expect(harness.messages[0].live2d_action_hints).toEqual(["抱枕"]);
    expect(harness.petChat.startReplyPaging).toHaveBeenCalledWith("assistant-1");
  });
});
