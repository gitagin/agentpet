import { describe, expect, it } from "vitest";
import {
  getPetBubbleGraphemeCount,
  getPetBubbleGraphemeWeight,
  getPetBubblePageDelay,
  getPetBubbleVisualWeight,
  normalizePetBubbleText,
  paginatePetBubbleReply,
} from "./petBubblePagination";

describe("petBubblePagination", () => {
  it("normalizes whitespace before pagination", () => {
    expect(normalizePetBubbleText("  你好\t小猫\r\n\r\n今天好吗  ")).toBe("你好 小猫\n今天好吗");
  });

  it("uses visual weights for mixed text", () => {
    expect(getPetBubbleGraphemeWeight("你")).toBe(1);
    expect(getPetBubbleGraphemeWeight("a")).toBe(0.55);
    expect(getPetBubbleGraphemeWeight("!")).toBe(0.35);
    expect(getPetBubbleVisualWeight("你好a!")).toBeCloseTo(2.9);
    expect(getPetBubbleGraphemeCount("你好a!")).toBe(4);
  });

  it("splits long replies into bounded readable pages", () => {
    const pages = paginatePetBubbleReply(
      "今天先整理长期记忆和 Wiki 提案，确认后再写入 Vault。然后检查 Live2D 资源边界，避免把 release 产物提交进仓库。最后运行桌面端质量检查。",
    );

    expect(pages.length).toBeGreaterThan(1);
    expect(pages.join("")).toBe("今天先整理长期记忆和 Wiki 提案，确认后再写入 Vault。然后检查 Live2D 资源边界，避免把 release 产物提交进仓库。最后运行桌面端质量检查。");
    expect(pages.every((page) => getPetBubbleVisualWeight(page) <= 36)).toBe(true);
  });

  it("calculates bounded page delay from visual weight", () => {
    expect(getPetBubblePageDelay("短句")).toBe(3600);
    expect(getPetBubblePageDelay("这是一段需要停留更久的较长桌宠气泡文本，用来确认阅读时间不会无限增长。".repeat(4))).toBe(7600);
  });
});
