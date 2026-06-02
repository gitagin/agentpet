import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../../types";
import { ChatCitationSummary } from "./ChatCitationSummary";

function assistantMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "message-1",
    role: "assistant",
    content: "我翻到了相关记录。",
    status: "completed",
    ...overrides,
  };
}

describe("ChatCitationSummary", () => {
  it("shows searched scopes, local source paths, snippets, and retrieval mode for citations", () => {
    render(
      <ChatCitationSummary
        message={assistantMessage({
          retrieval_attempted: true,
          retrieval_scopes: ["personal_memory", "knowledge_base"],
          retrieval_context_budget: {
            strategy: "deterministic_v1",
            candidate_count: 3,
            selected_count: 2,
            item_budget: 5,
            per_scope_limit: 2,
            char_budget: 1200,
            used_chars: 240,
            source_counts: { personal_memory: 1, knowledge_base: 2 },
            selected_scopes: ["personal_memory", "knowledge_base"],
          },
          citations: [
            {
              note_id: "note-1",
              chunk_id: "chunk-1",
              relative_path: "Memories/LongTerm/Profile.md",
              title: "Profile",
              heading: "偏好",
              snippet: "用户偏好简洁的状态更新。",
              score: 0.88,
              source_scope: "personal_memory",
              retrieval_mode: "fts",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("检索范围")).toBeInTheDocument();
    expect(screen.getByText("长期记忆 / Wiki/知识库")).toBeInTheDocument();
    expect(screen.getByText(/候选 3 条，采用 2 条/)).toBeInTheDocument();
    expect(screen.getByText(/长期记忆 1/)).toBeInTheDocument();
    expect(screen.getByText("Memories/LongTerm/Profile.md")).toBeInTheDocument();
    expect(screen.getByText("来源：长期记忆")).toBeInTheDocument();
    expect(screen.getByText("检索方式：全文搜索")).toBeInTheDocument();
    expect(screen.getByText("用户偏好简洁的状态更新。")).toBeInTheDocument();
    expect(screen.queryByText("0.88")).not.toBeInTheDocument();
  });

  it("explains when retrieval ran but no local citation was found", () => {
    render(
      <ChatCitationSummary
        message={assistantMessage({
          retrieval_attempted: true,
          retrieval_scopes: ["personal_memory", "daily_chat"],
          citations: [],
        })}
      />,
    );

    expect(screen.getByText("长期记忆 / 每日聊天日记")).toBeInTheDocument();
    expect(
      screen.getByText("本轮已检索 长期记忆 / 每日聊天日记，没有找到可引用的本地记忆或知识，回答里没有附带本地来源。"),
    ).toBeInTheDocument();
  });
});
