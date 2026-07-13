import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import GrowthWindowView from "./GrowthWindowView";
import type { DesktopApi } from "../services/desktopApi";
import type { GrowthSnapshotResponse } from "../types";

vi.mock("./BottomNav", () => ({
  BottomNav: ({ activeTab }: { activeTab: string }) => <nav aria-label="mock bottom nav">{activeTab}</nav>,
}));

const snapshot: GrowthSnapshotResponse = {
  generated_at: "2026-06-04T10:00:00Z",
  stats: {
    vault_configured: true,
    vault_id: "vault-1",
    chat_diary_days: 2,
    chat_diary_entries: 3,
    long_term_memory_count: 2,
    wiki_page_count: 1,
    task_count: 0,
    completed_task_count: 0,
    latest_organization_at: "2026-06-04T09:00:00Z",
    reversible_operation_count: 1,
  },
  dimensions: [
    {
      key: "memory_depth",
      label: "记忆脉络",
      level: 2,
      level_label: "能接住日常",
      current_value: 5,
      next_threshold: 8,
      progress: 40,
      description: "聊天日记和长期记忆越多，桌宠越能接住连续话题。",
      data_sources: ["daily_chat_memory_entries", "memory_graph_facts"],
      last_changed_at: "2026-06-04T09:00:00Z",
    },
    {
      key: "response_affinity",
      label: "回应默契",
      level: 2,
      level_label: "开始贴合表达",
      current_value: 3,
      next_threshold: 5,
      progress: 33,
      description: "偏好、边界和风格类记忆越明确，回复越贴近你的表达习惯。",
      data_sources: ["memory_graph_facts", "diary_memory_objects"],
      last_changed_at: "2026-06-04T08:00:00Z",
    },
    {
      key: "trust_boundary",
      label: "安心边界",
      level: 3,
      level_label: "边界稳定",
      current_value: 4,
      next_threshold: 9,
      progress: 0,
      description: "撤回、跳过和可撤销记录越清楚，桌宠越能展示边界感。",
      data_sources: ["agent_actions", "memory_feedback_events"],
      last_changed_at: "2026-06-04T07:00:00Z",
    },
  ],
  events: [
    {
      event_id: "growth-action-revert",
      occurred_at: "2026-06-04T08:00:00Z",
      dimension_key: "trust_boundary",
      title: "已撤销：已沉淀回答摘要",
      summary: "恢复 1 个 Markdown 目标。",
      source_action_id: "growth-action-revert",
      source_action_type: "agent_action.revert",
      target_paths: ["Wiki/Companion Growth.md"],
    },
  ],
};

function createApi(response: GrowthSnapshotResponse = snapshot) {
  return {
    getGrowthSnapshot: vi.fn().mockResolvedValue(response),
  } as unknown as DesktopApi & { getGrowthSnapshot: ReturnType<typeof vi.fn> };
}

describe("GrowthWindowView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads growth dimensions and history from the local snapshot", async () => {
    const api = createApi();

    render(<GrowthWindowView api={api} />);

    expect(await screen.findByRole("heading", { name: "成长记录" })).toBeInTheDocument();
    await waitFor(() => expect(api.getGrowthSnapshot).toHaveBeenCalledTimes(1));

    expect(screen.getAllByText("边界稳定").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("聊天日记 3 · 长期记忆 2 · 资料页 1 · 可撤回 1")).toBeInTheDocument();
    expect(screen.getByText("记忆脉络")).toBeInTheDocument();
    expect(screen.getByText("回应默契")).toBeInTheDocument();
    expect(screen.getByText("安心边界")).toBeInTheDocument();

    const history = screen.getByRole("list");
    expect(within(history).getByText("已撤销：已沉淀回答摘要")).toBeInTheDocument();
    expect(within(history).getByText("Wiki/Companion Growth.md")).toBeInTheDocument();
  });

  it("refreshes the growth snapshot on demand", async () => {
    const api = createApi();

    render(<GrowthWindowView api={api} />);
    await waitFor(() => expect(api.getGrowthSnapshot).toHaveBeenCalledTimes(1));

    const refreshButton = await screen.findByRole("button", { name: "刷新" });
    fireEvent.click(refreshButton);

    await waitFor(() => expect(api.getGrowthSnapshot).toHaveBeenCalledTimes(2));
  });

  it("aborts the initial snapshot request on unmount", async () => {
    let observedSignal: AbortSignal | undefined;
    const api = {
      getGrowthSnapshot: vi.fn((signal?: AbortSignal) => {
        observedSignal = signal;
        return new Promise<GrowthSnapshotResponse>((_resolve, reject) => {
          signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        });
      }),
    } as unknown as DesktopApi & { getGrowthSnapshot: ReturnType<typeof vi.fn> };

    const { unmount } = render(<GrowthWindowView api={api} />);
    await waitFor(() => expect(api.getGrowthSnapshot).toHaveBeenCalledTimes(1));

    unmount();
    await Promise.resolve();

    expect(observedSignal?.aborted).toBe(true);
  });
});
