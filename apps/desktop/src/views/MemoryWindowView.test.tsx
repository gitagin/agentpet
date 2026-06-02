import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MemoryWindowView from "./MemoryWindowView";
import type { DesktopApi } from "../services/desktopApi";
import type { LocalAssetStatsResponse, MemoryGraphFact, RetrospectiveResponse } from "../types";

function memoryFact(overrides: Partial<MemoryGraphFact> = {}): MemoryGraphFact {
  return {
    fact_id: "fact-1",
    category: "preference",
    subject: "fruit",
    predicate: "is",
    object: "apple",
    status: "active",
    confidence: 0.91,
    source_text: "raw evidence is not rendered",
    source_type: "user_message",
    support_count: 2,
    conflicts_with: null,
    memory_type: "preference",
    entity_type: "preference",
    occurred_at: null,
    expires_at: null,
    metadata_json: "{}",
    importance: 0.8,
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

const retrospectives: RetrospectiveResponse = {
  generated_at: "2026-06-02T00:00:00Z",
  windows: [
    {
      days: 7,
      label: "7 天",
      start_at: "2026-05-26T00:00:00Z",
      end_at: "2026-06-02T00:00:00Z",
      summary: { diary_objects: 0, long_term_memories: 0, wiki_updates: 0 },
      topics: [],
      diary_summaries: [],
      long_term_memories: [],
      tasks: { total: 0, completed: 0, pending: 0, cancelled: 0, overdue: 0, sources: [] },
      wiki_updates: [],
      repeated_preferences: [],
      has_data: false,
    },
  ],
};

const localAssetStats: LocalAssetStatsResponse = {
  vault_configured: true,
  vault_id: "vault-1",
  chat_diary_days: 2,
  chat_diary_entries: 3,
  long_term_memory_count: 4,
  wiki_page_count: 5,
  task_count: 6,
  completed_task_count: 3,
  latest_organization_at: "2026-06-02T10:00:00Z",
  reversible_operation_count: 2,
};

function createApi(facts: MemoryGraphFact[], stats: LocalAssetStatsResponse = localAssetStats) {
  return {
    getLocalAssetStats: vi.fn().mockResolvedValue(stats),
    getRetrospectives: vi.fn().mockResolvedValue(retrospectives),
    writeRetrospectiveReport: vi.fn(),
    writeRetrospectivePeriodReport: vi.fn(),
    listMemoryGraphFacts: vi.fn().mockResolvedValue({ facts }),
    markMemoryGraphFactWrong: vi.fn().mockResolvedValue({ fact_id: "fact-1", status: "wrong" }),
    archiveMemoryGraphFact: vi.fn(),
    sensitiveBlockMemoryGraphFact: vi.fn(),
    confirmMemoryGraphFact: vi.fn(),
    getMemoryGraphExportPreview: vi.fn().mockResolvedValue({
      generated_at: "2026-06-02T00:00:00Z",
      format: "markdown",
      item_count: 1,
      items: [{ ...facts[0], metadata: {}, source_text: undefined }],
      json_preview: '[{"fact_id":"fact-1","subject":"fruit"}]',
      markdown_preview: "# Long-term memory export preview\n\n## fruit is apple\n",
      redaction_note: "Raw source evidence is omitted from this preview.",
    }),
  } as unknown as DesktopApi;
}

function renderView(api: DesktopApi, onRefresh = vi.fn()) {
  render(
    <MemoryWindowView
      api={api}
      loading={false}
      error=""
      entries={[]}
      onRefresh={onRefresh}
      renderEntry={() => <article />}
    />,
  );
}

describe("MemoryWindowView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("renders local asset stats from the local dashboard", async () => {
    const api = createApi([memoryFact()]);

    renderView(api);

    const dashboard = await screen.findByLabelText("本地资产仪表盘");
    expect(dashboard).toBeInTheDocument();
    expect(within(dashboard).getByText("聊天日记天数")).toBeInTheDocument();
    expect(within(dashboard).getByText("3 条记录")).toBeInTheDocument();
    expect(within(dashboard).getByText("Wiki 页面")).toBeInTheDocument();
    expect(within(dashboard).getByText("5")).toBeInTheDocument();
    expect(within(dashboard).getByText("任务完成")).toBeInTheDocument();
    expect(within(dashboard).getByText("3/6")).toBeInTheDocument();
    expect(within(dashboard).getByText("可撤销操作")).toBeInTheDocument();
    expect(within(dashboard).getByText("尚未撤销")).toBeInTheDocument();
    expect(api.getLocalAssetStats).toHaveBeenCalled();
  });

  it("shows an empty local asset guide when there is no accumulated data", async () => {
    const api = createApi([], {
      vault_configured: false,
      vault_id: null,
      chat_diary_days: 0,
      chat_diary_entries: 0,
      long_term_memory_count: 0,
      wiki_page_count: 0,
      task_count: 0,
      completed_task_count: 0,
      latest_organization_at: null,
      reversible_operation_count: 0,
    });

    renderView(api);

    expect(await screen.findByText("还没有本地资产。完成一次聊天、记录长期记忆或生成复盘后，这里会显示积累情况。")).toBeInTheDocument();
    expect(screen.getByText("尚未绑定 Vault；先显示本地数据库中的积累。")).toBeInTheDocument();
  });

  it("marks an active long-term memory as inaccurate from the UI", async () => {
    const api = createApi([memoryFact()]);
    const onRefresh = vi.fn();

    renderView(api, onRefresh);

    expect(await screen.findByText("fruit is apple")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "标为不准确" }));

    await waitFor(() => expect(api.markMemoryGraphFactWrong).toHaveBeenCalledWith("fact-1"));
    expect(onRefresh).toHaveBeenCalled();
  });

  it("copies a redacted export preview without rendering source evidence", async () => {
    const api = createApi([memoryFact()]);

    renderView(api);

    await screen.findByText("fruit is apple");
    expect(screen.queryByText("raw evidence is not rendered")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "复制导出预览" }));

    await waitFor(() => expect(api.getMemoryGraphExportPreview).toHaveBeenCalledWith("markdown", null, "", 100));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining("fruit is apple"));
    expect(screen.getByLabelText("长期记忆导出预览")).toBeInTheDocument();
    expect(screen.queryByText("raw evidence is not rendered")).not.toBeInTheDocument();
  });

  it("manually generates weekly and monthly Markdown reports from the retrospective toolbar", async () => {
    const api = createApi([memoryFact()]);
    const onRefresh = vi.fn();

    renderView(api, onRefresh);

    await screen.findByText("fruit is apple");
    fireEvent.click(screen.getByRole("button", { name: "生成周报" }));

    await waitFor(() => expect(api.writeRetrospectivePeriodReport).toHaveBeenCalledWith("weekly"));
    fireEvent.click(screen.getByRole("button", { name: "生成月报" }));

    await waitFor(() => expect(api.writeRetrospectivePeriodReport).toHaveBeenCalledWith("monthly"));
    expect(onRefresh).toHaveBeenCalledTimes(2);
  });
});
