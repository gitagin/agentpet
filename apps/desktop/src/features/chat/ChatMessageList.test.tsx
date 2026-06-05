import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ChatMessage } from "../../types";
import { ChatMessageList } from "./ChatMessageList";

describe("ChatMessageList", () => {
  it("hides system messages and keeps assistant trace details collapsed", () => {
    const messages: ChatMessage[] = [
      {
        id: "system-1",
        role: "system",
        content: "内部系统提示",
        status: "completed",
      },
      {
        id: "assistant-1",
        role: "assistant",
        content: "这是直接回答。",
        status: "completed",
        retrieval_attempted: true,
        citations: [
          {
            relative_path: "Wiki/Test.md",
            snippet: "引用片段",
            source_scope: "knowledge_base",
            retrieval_mode: "fts",
          },
        ],
        events: [{ id: "event-1", label: "智能体状态", detail: "已检索 Wiki", tone: "info" }],
      },
    ];

    const { container } = render(<ChatMessageList messages={messages} />);

    expect(screen.queryByText("内部系统提示")).not.toBeInTheDocument();
    expect(screen.getByText("这是直接回答。")).toBeInTheDocument();
    expect(screen.queryByText("助手")).not.toBeInTheDocument();
    expect(screen.getByText("来源与整理 · 1 条引用")).toBeInTheDocument();
    expect(container.querySelector(".message-trace")).not.toHaveAttribute("open");
  });
});
