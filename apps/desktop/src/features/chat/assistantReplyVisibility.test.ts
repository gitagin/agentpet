import { describe, expect, it } from "vitest";

import { createAssistantReplyTextFilter, filterAssistantReplyText, stripAssistantHiddenReplyText } from "./assistantReplyVisibility";

describe("assistant reply visibility", () => {
  it("strips ASCII and full-width parenthetical hidden text", () => {
    expect(stripAssistantHiddenReplyText("你好（微笑）我在这里 (thinking) 别担心")).toBe("你好我在这里 别担心");
  });

  it("returns hidden text separately without leaking it into visible text", () => {
    expect(filterAssistantReplyText("（抱枕）你好 *smile* 我在")).toEqual({
      visibleText: "你好 我在",
      hiddenTexts: ["抱枕", "smile"],
    });
  });

  it("strips single-star hidden action text", () => {
    expect(stripAssistantHiddenReplyText("Hi *smile* there")).toBe("Hi there");
    expect(stripAssistantHiddenReplyText("Hi ＊smile＊ there")).toBe("Hi there");
  });

  it("keeps double-star emphasis as visible text", () => {
    expect(stripAssistantHiddenReplyText("This is **important** text")).toBe("This is **important** text");
  });

  it("keeps hidden state across streaming chunks", () => {
    const filter = createAssistantReplyTextFilter();

    expect(filter.append("你好（")).toBe("你好");
    expect(filter.append("微笑")).toBe("");
    expect(filter.append("）我在")).toBe("我在");
    expect(filter.takeHiddenTexts()).toEqual(["微笑"]);
  });

  it("hides unmatched parenthetical text until a closing marker arrives", () => {
    const filter = createAssistantReplyTextFilter();

    expect(filter.append("先说一句 (")).toBe("先说一句 ");
    expect(filter.append("还在隐藏中")).toBe("");
    expect(filter.append(") 然后继续")).toBe(" 然后继续");
  });

  it("keeps single-star hidden state across streaming chunks", () => {
    const filter = createAssistantReplyTextFilter();

    expect(filter.append("Hi *")).toBe("Hi ");
    expect(filter.append("smile")).toBe("");
    expect(filter.append("* there")).toBe(" there");
    expect(filter.takeHiddenTexts()).toEqual(["smile"]);
  });
});
