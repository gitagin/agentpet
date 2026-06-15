import { describe, expect, it } from "vitest";

import { createAssistantReplyTextFilter, stripAssistantHiddenReplyText } from "./assistantReplyVisibility";

describe("assistant reply visibility", () => {
  it("strips ASCII and full-width parenthetical hidden text", () => {
    expect(stripAssistantHiddenReplyText("你好（微笑）我在这里 (thinking) 别担心")).toBe("你好我在这里 别担心");
  });

  it("keeps hidden state across streaming chunks", () => {
    const filter = createAssistantReplyTextFilter();

    expect(filter.append("你好（")).toBe("你好");
    expect(filter.append("微笑")).toBe("");
    expect(filter.append("）我在")).toBe("我在");
  });

  it("hides unmatched parenthetical text until a closing marker arrives", () => {
    const filter = createAssistantReplyTextFilter();

    expect(filter.append("先说一句 (")).toBe("先说一句 ");
    expect(filter.append("还在隐藏中")).toBe("");
    expect(filter.append(") 然后继续")).toBe(" 然后继续");
  });
});
