import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../../types";
import { resolveLive2DReplyActionKey } from "./live2dReplyActions";

function assistantMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "assistant-1",
    role: "assistant",
    content: "",
    status: "completed",
    ...overrides,
  };
}

describe("live2dReplyActions", () => {
  it("keeps a very short partial reply on the current thinking action", () => {
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "\u597d", status: "partial" }))).toBeNull();
  });

  it("maps a neutral completed reply back to the normal done action", () => {
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "\u6211\u660e\u767d\u4e86\uff0c\u6211\u4eec\u7ee7\u7eed\u3002" }))).toBe("chat_done");
  });

  it("maps reply content to expressive Live2D actions", () => {
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "\u522b\u62c5\u5fc3\uff0c\u6211\u5728\u8fd9\u91cc\u966a\u4f60\u6162\u6162\u6765\u3002" }))).toBe("emotion_comfort");
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "\u592a\u597d\u4e86\uff0c\u8fd9\u4ef6\u4e8b\u5df2\u7ecf\u5b8c\u6210\u3002" }))).toBe("celebrate_small");
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "\u6211\u5df2\u5e2e\u4f60\u5b89\u6392\u4efb\u52a1\u548c\u63d0\u9192\u3002" }))).toBe("task_create");
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "\u8fd9\u6bb5\u8d44\u6599\u5df2\u7ecf\u5f52\u6863\u5230 Wiki\u3002" }))).toBe("wiki_archive");
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "\u6211\u628a\u8fd9\u6bb5\u5df2\u4fdd\u5b58\u5230\u65e5\u8bb0\u91cc\u3002" }))).toBe("memory_save_diary");
  });

  it("uses failure and no-result language for error-like actions", () => {
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "\u62b1\u6b49\uff0c\u8fd9\u6b21\u8fde\u63a5\u5931\u8d25\u4e86\u3002" }))).toBe("system_error");
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "\u6682\u65f6\u6ca1\u6709\u627e\u5230\u76f8\u5173\u8bb0\u5fc6\u3002" }))).toBe("memory_not_found");
    expect(resolveLive2DReplyActionKey(assistantMessage({ status: "failed", content: "" }))).toBe("system_error");
  });

  it("uses structured reply metadata when present", () => {
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "", continuity_signal: {} as ChatMessage["continuity_signal"] }))).toBe("continuity_remember");
    expect(resolveLive2DReplyActionKey(assistantMessage({ content: "\u6839\u636e\u5f15\u7528\u6765\u770b", citations: [{} as NonNullable<ChatMessage["citations"]>[number]] }))).toBe("memory_found");
  });
});
