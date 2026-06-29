import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MemoryWindowView from "./MemoryWindowView";
import type { DesktopApi } from "../services/desktopApi";
import type { AgentAction, LocalAssetStatsResponse, MemoryGraphFact, MemoryProposalDraft, MemoryReviewResponse, MemorySearchResult, RetrospectiveReportResponse, RetrospectiveResponse } from "../types";

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

function searchResult(overrides: Partial<MemorySearchResult> = {}): MemorySearchResult {
  return {
    note_id: "note-1",
    chunk_id: "chunk-1",
    relative_path: "Memories/Preferences.md",
    title: "偏好记忆",
    snippet: "用户偏好发布清单。",
    score: 0.92,
    source_scope: "personal_memory",
    retrieval_mode: "graph",
    ...overrides,
  };
}

function agentAction(overrides: Partial<AgentAction> = {}): AgentAction {
  return {
    action_id: "action-review-1",
    action_type: "wiki.retrospective_report.write",
    risk_tier: "low",
    decision: "auto",
    status: "completed",
    title: "已生成复盘",
    summary: "已保存复盘报告。",
    target_paths: ["Wiki/Companion/Reports/2026-06-02-1d.md"],
    reversible: true,
    source: {},
    diff_summary: "",
    metadata: {},
    created_at: "2026-06-02T00:00:00Z",
    updated_at: "2026-06-02T00:00:00Z",
    completed_at: "2026-06-02T00:00:00Z",
    ...overrides,
  };
}

function reportResponse(relativePath: string, overrides: Partial<RetrospectiveReportResponse> = {}): RetrospectiveReportResponse {
  return {
    page: {
      title: "复盘报告",
      relative_path: relativePath,
      operation: "replace",
      status: "created",
      index_job_id: "index-1",
    },
    action: agentAction({ target_paths: [relativePath] }),
    markdown: "# 复盘报告\n",
    ...overrides,
  };
}

const retrospectives: RetrospectiveResponse = {
  generated_at: "2026-06-02T00:00:00Z",
  windows: [
    {
      days: 1,
      label: "今天",
      start_at: "2026-06-01T00:00:00Z",
      end_at: "2026-06-02T00:00:00Z",
      summary: { diary_objects: 1, long_term_memories: 1, wiki_updates: 1 },
      topics: [
        {
          name: "发布复盘",
          count: 1,
          sources: [{ kind: "diary_memory", id: "diary-1", label: "每日笔记", path: "Memories/Daily/2026-06-01.md" }],
        },
      ],
      diary_summaries: [
        {
          id: "diary-1",
          summary: "复盘了发布计划。",
          topic: "发布复盘",
          source_path: "Memories/Daily/2026-06-01.md",
          occurred_at: "2026-06-01T09:00:00Z",
        },
      ],
      long_term_memories: [
        {
          id: "memory-1",
          summary: "用户偏好简洁的发布清单",
          category: "preference",
          status: "active",
          confidence: 0.91,
          source_path: "Memories/Profile.md",
          created_at: "2026-06-01T10:00:00Z",
        },
      ],
      tasks: {
        total: 1,
        completed: 1,
        pending: 0,
        cancelled: 0,
        overdue: 0,
        sources: [{ kind: "task", id: "task-1", label: "交付 task04", created_at: "2026-06-01T11:00:00Z" }],
      },
      wiki_updates: [
        {
          path: "Wiki/Companion/Summaries/Release.md",
          title: "发布摘要",
          action_type: "wiki.answer_summary.write",
          created_at: "2026-06-01T12:00:00Z",
          action_id: "action-wiki-1",
        },
      ],
      repeated_preferences: [],
      has_data: true,
    },
    {
      days: 7,
      label: "7 天",
      start_at: "2026-05-26T00:00:00Z",
      end_at: "2026-06-02T00:00:00Z",
      summary: { diary_objects: 2, long_term_memories: 2, wiki_updates: 1 },
      topics: [],
      diary_summaries: [],
      long_term_memories: [],
      tasks: { total: 3, completed: 2, pending: 1, cancelled: 0, overdue: 0, sources: [] },
      wiki_updates: [],
      repeated_preferences: [],
      has_data: true,
    },
    {
      days: 30,
      label: "30 天",
      start_at: "2026-05-03T00:00:00Z",
      end_at: "2026-06-02T00:00:00Z",
      summary: { diary_objects: 4, long_term_memories: 3, wiki_updates: 2 },
      topics: [],
      diary_summaries: [],
      long_term_memories: [],
      tasks: { total: 5, completed: 3, pending: 2, cancelled: 0, overdue: 1, sources: [] },
      wiki_updates: [],
      repeated_preferences: [],
      has_data: true,
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

const weeklyMemoryReview: MemoryReviewResponse = {
  generated_at: "2026-06-02T00:00:00Z",
  window_days: 7,
  summary: { kept: 1, temporary: 1, ignored: 1 },
  redaction_note: "Sensitive text, credentials, raw evidence, and full Authorization headers are not included.",
  items: [
    {
      review_id: "fact:fact-1",
      target_type: "fact",
      target_id: "fact-1",
      category: "kept",
      summary: "weekly review retained preference",
      memory_kind: "preference",
      memory_scope: null,
      lifecycle_status: "active",
      risk_tier: null,
      confidence: 0.91,
      importance: 0.8,
      evidence_count: 2,
      expires_at: null,
      updated_at: "2026-06-01T00:00:00Z",
      source: "user_message",
      allowed_actions: ["keep", "edit", "forget", "only_this_week"],
    },
    {
      review_id: "candidate:candidate-1",
      target_type: "candidate",
      target_id: "candidate-1",
      category: "ignored",
      summary: "Maybe use weekly planning prompts.",
      memory_kind: "preference",
      memory_scope: "global",
      lifecycle_status: "candidate",
      risk_tier: "low",
      confidence: 0.72,
      importance: 0.5,
      evidence_count: 1,
      expires_at: null,
      updated_at: "2026-06-01T00:00:00Z",
      source: "slow_consolidation",
      allowed_actions: ["keep", "edit", "forget", "only_this_week"],
    },
  ],
};

function createApi(facts: MemoryGraphFact[], stats: LocalAssetStatsResponse = localAssetStats) {
  const exportPreview = (format: "json" | "markdown" = "markdown") => ({
    generated_at: "2026-06-02T00:00:00Z",
    format,
    item_count: 1,
    items: [{ ...facts[0], metadata: {}, source_text: undefined }],
    json_preview: '[{"fact_id":"fact-1","subject":"fruit"}]',
    markdown_preview: "# 长期记忆导出预览\n\n## fruit is apple\n",
    redaction_note: "原始来源证据已从此预览中省略。",
  });
  return {
    searchMemory: vi.fn().mockResolvedValue({ results: [searchResult()], metadata: { semantic_available: false } }),
    createMemoryProposal: vi.fn().mockResolvedValue({
      proposal_id: "proposal-1",
      status: "pending",
      preview_markdown: "我偏好简洁的发布清单。",
      target_path: "Inbox/Pending Memories.md",
      diff: null,
      target_content_hash: "hash-1",
    }),
    listMemoryProposals: vi.fn().mockResolvedValue({ proposals: [] }),
    confirmMemoryProposal: vi.fn().mockResolvedValue({ proposal_id: "proposal-1", status: "confirmed", written_path: "Memories/Profile.md" }),
    rejectMemoryProposal: vi.fn().mockResolvedValue({ proposal_id: "proposal-1", status: "rejected" }),
    getLocalAssetStats: vi.fn().mockResolvedValue(stats),
    getRetrospectives: vi.fn().mockResolvedValue(retrospectives),
    writeRetrospectiveReport: vi.fn((days: number) => Promise.resolve(reportResponse(`Wiki/Companion/Reports/2026-06-02-${days}d-review.md`))),
    writeRetrospectivePeriodReport: vi.fn((period: string) => Promise.resolve(reportResponse(`Wiki/Companion/Reports/2026-06-02-${period}-review.md`))),
    getWeeklyMemoryReview: vi.fn().mockResolvedValue(weeklyMemoryReview),
    applyWeeklyMemoryReviewAction: vi.fn().mockResolvedValue({
      target_type: "fact",
      target_id: "fact-1",
      operation: "make_temporary",
      status: "active",
      feedback_event_id: "feedback-1",
      action_id: "action-feedback-1",
    }),
    listMemoryGraphFacts: vi.fn().mockResolvedValue({ facts }),
    markMemoryGraphFactWrong: vi.fn().mockResolvedValue({ fact_id: "fact-1", status: "wrong" }),
    archiveMemoryGraphFact: vi.fn(),
    sensitiveBlockMemoryGraphFact: vi.fn(),
    confirmMemoryGraphFact: vi.fn(),
    getMemoryGraphExportPreview: vi.fn((format: "json" | "markdown" = "markdown") =>
      Promise.resolve(exportPreview(format)),
    ),
  } as unknown as DesktopApi;
}

function renderView(
  api: DesktopApi,
  onRefresh = vi.fn(),
  overrides: Partial<{
    memorySearchQuery: string;
    memorySearchResults: MemorySearchResult[];
    memorySearchStatus: "idle" | "loading" | "success" | "empty" | "error";
    memoryProposalDraft: MemoryProposalDraft;
    onMemorySearchQueryChange: (query: string) => void;
    onMemoryProposalDraftChange: (patch: Partial<MemoryProposalDraft>) => void;
    entries: Parameters<typeof MemoryWindowView>[0]["entries"];
    renderEntry: Parameters<typeof MemoryWindowView>[0]["renderEntry"];
  }> = {},
) {
  const proposalDraft = overrides.memoryProposalDraft || {
    type: "fact" as const,
    content: "",
    target_path: "Inbox/Pending Memories.md",
  };
  render(
    <MemoryWindowView
      api={api}
      loading={false}
      error=""
      entries={overrides.entries || []}
      memorySearchQuery={overrides.memorySearchQuery || ""}
      memorySearchStatus={overrides.memorySearchStatus || "idle"}
      memorySearchResults={overrides.memorySearchResults || []}
      memoryLastSearchQuery=""
      onMemorySearchQueryChange={overrides.onMemorySearchQueryChange || vi.fn()}
      onRunMemorySearch={(event) => {
        event.preventDefault();
        void api.searchMemory(overrides.memorySearchQuery || "发布清单");
      }}
      memoryProposalDraft={proposalDraft}
      memoryProposals={[]}
      memoryProposalActionIds={new Set()}
      loadingMemoryProposals={false}
      onMemoryProposalDraftChange={overrides.onMemoryProposalDraftChange || vi.fn()}
      onCreateMemoryProposal={(event) => {
        event.preventDefault();
        void api.createMemoryProposal(proposalDraft);
      }}
      onActOnMemoryProposal={vi.fn()}
      onLoadMemoryProposals={vi.fn()}
      onRefresh={onRefresh}
      renderEntry={overrides.renderEntry || (() => <article />)}
    />,
  );
}

function openAdvancedMemoryTools() {
  const advanced = screen.getByText("更多记忆管理").closest("details") as HTMLDetailsElement;
  expect(advanced).toBeInTheDocument();
  expect(advanced).not.toHaveAttribute("open");
  fireEvent.click(within(advanced).getByText("更多记忆管理"));
  expect(advanced).toHaveAttribute("open");
  return advanced;
}

function openReviewTools() {
  const reviewTools = screen.getByText("回顾和本机整理").closest("details") as HTMLDetailsElement;
  expect(reviewTools).toBeInTheDocument();
  expect(reviewTools).not.toHaveAttribute("open");
  fireEvent.click(within(reviewTools).getByText("回顾和本机整理"));
  expect(reviewTools).toHaveAttribute("open");
  return reviewTools;
}

describe("MemoryWindowView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:memory-export"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  });

  it("renders local asset stats from the local dashboard", async () => {
    const api = createApi([memoryFact()]);

    renderView(api);
    openReviewTools();

    const dashboard = (await screen.findByRole("button", { name: /刷新积累/ })).closest("section") as HTMLElement;
    expect(dashboard).toBeInTheDocument();
    expect(within(dashboard).getByText("聊天日记天数")).toBeInTheDocument();
    expect(within(dashboard).getByText("资料页")).toBeInTheDocument();
    expect(within(dashboard).getByText("5")).toBeInTheDocument();
    expect(within(dashboard).getByText("任务完成")).toBeInTheDocument();
    expect(within(dashboard).getByText("3/6")).toBeInTheDocument();
    expect(within(dashboard).getByText("可撤回操作")).toBeInTheDocument();
    expect(within(dashboard).getByText("尚未撤回")).toBeInTheDocument();
    expect(api.getLocalAssetStats).toHaveBeenCalled();
  });

  it("shows memory control first and keeps direct tools in folded sections", async () => {
    const api = createApi([
      memoryFact(),
      memoryFact({
        fact_id: "fact-2",
        object: "banana",
        status: "candidate",
        confidence: 0.72,
      }),
    ]);
    const entries: Parameters<typeof MemoryWindowView>[0]["entries"] = [
      {
        kind: "agent_action",
        id: "agent-action-memory-1",
        sortAt: "2026-06-02T00:00:00Z",
        sortKey: Date.parse("2026-06-02T00:00:00Z"),
        action: agentAction({
          action_id: "memory-action-1",
          action_type: "memory.long_term.write",
          title: "已更新长期记忆",
          summary: "记住发布清单。",
          target_paths: ["Memories/Profile.md"],
          reversible: true,
        }),
      },
    ];

    renderView(api, vi.fn(), {
      entries,
      memorySearchQuery: "发布清单",
      memorySearchStatus: "success",
      memorySearchResults: [searchResult()],
      renderEntry: (entry) => (
        <article key={entry.id}>
          <strong>可撤回记忆记录</strong>
          <button type="button">撤回</button>
        </article>
      ),
    });

    expect(screen.getByRole("heading", { name: "我的记忆" })).toBeInTheDocument();
    const control = await screen.findByLabelText("我的记忆控制台");
    await within(control).findByText("fruit is apple");
    await within(control).findByText("fruit is banana");
    expect(within(control).getByText("正在使用的记忆")).toBeInTheDocument();
    expect(within(control).getByText("待确认的记忆")).toBeInTheDocument();
    expect(within(control).getByText("最近撤回或跳过的记忆")).toBeInTheDocument();
    expect(within(control).getByText("fruit is apple")).toBeInTheDocument();
    expect(within(control).getByText("fruit is banana")).toBeInTheDocument();
    expect(within(control).getByText("可撤回记忆记录")).toBeInTheDocument();
    expect(within(control).getByRole("button", { name: "撤回" })).toBeInTheDocument();

    const reviewTools = screen.getByText("回顾和本机整理").closest("details") as HTMLDetailsElement;
    const advanced = screen.getByText("更多记忆管理").closest("details") as HTMLDetailsElement;
    expect(control.compareDocumentPosition(reviewTools) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(reviewTools.compareDocumentPosition(advanced) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(reviewTools).not.toHaveAttribute("open");
    expect(advanced).not.toHaveAttribute("open");

    openAdvancedMemoryTools();
    const workbench = screen.getByLabelText("更多记忆工作区");
    expect(advanced).toContainElement(workbench);
    expect(within(workbench).getByLabelText("记忆搜索")).toBeInTheDocument();
    expect(within(workbench).getByPlaceholderText("搜索我记住的事")).toBeInTheDocument();
    expect(within(workbench).getByLabelText("新增记忆表单")).toBeInTheDocument();
    expect(within(workbench).getByText("偏好记忆")).toBeInTheDocument();
    expect(within(workbench).getByText("用户偏好发布清单。")).toBeInTheDocument();
    expect(within(advanced).getByLabelText("已确认记忆")).toBeInTheDocument();
    expect(screen.queryByLabelText(/chat/i)).not.toBeInTheDocument();
  });

  it("offers guided trials for memory search, saving a preference, and today's review", async () => {
    const api = createApi([memoryFact()]);
    const onMemorySearchQueryChange = vi.fn();
    const onMemoryProposalDraftChange = vi.fn();

    renderView(api, vi.fn(), { onMemorySearchQueryChange, onMemoryProposalDraftChange });
    openAdvancedMemoryTools();

    fireEvent.click(screen.getByRole("button", { name: "搜索记忆" }));
    expect(onMemorySearchQueryChange).toHaveBeenCalledWith("发布清单");

    fireEvent.click(screen.getByRole("button", { name: "保存一个偏好" }));
    expect(onMemoryProposalDraftChange).toHaveBeenCalledWith({
      type: "preference",
      content: "我偏好简洁的发布清单。",
      target_path: "Inbox/Pending Memories.md",
    });

    fireEvent.click(within(screen.getByLabelText("复盘快捷操作")).getByRole("button", { name: "生成今日复盘" }));
    await waitFor(() => expect(api.writeRetrospectiveReport).toHaveBeenCalledWith(1));
  });

  it("runs memory search without opening chat", async () => {
    const api = createApi([memoryFact()]);

    renderView(api, vi.fn(), { memorySearchQuery: "发布清单" });
    openAdvancedMemoryTools();

    fireEvent.click(screen.getByRole("button", { name: "搜索" }));

    await waitFor(() => expect(api.searchMemory).toHaveBeenCalledWith("发布清单"));
  });

  it("creates a memory proposal without opening chat", async () => {
    const api = createApi([memoryFact()]);
    const draft: MemoryProposalDraft = {
      type: "preference",
      content: "我偏好简洁的发布清单。",
      target_path: "Inbox/Pending Memories.md",
    };

    renderView(api, vi.fn(), { memoryProposalDraft: draft });
    openAdvancedMemoryTools();

    fireEvent.click(screen.getByRole("button", { name: "新增记忆" }));

    await waitFor(() => expect(api.createMemoryProposal).toHaveBeenCalledWith(draft));
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
    openReviewTools();

    const dashboard = await screen.findByText("聊天日记天数");
    expect(dashboard).toBeInTheDocument();
    expect(screen.getAllByText("0").length).toBeGreaterThan(3);
  });

  it("splits memory facts into review sections and manages them directly", async () => {
    const api = createApi([
      memoryFact({ fact_id: "fact-active", subject: "fruit", object: "apple", status: "active" }),
      memoryFact({ fact_id: "fact-candidate", subject: "drink", object: "tea", status: "candidate" }),
      memoryFact({ fact_id: "fact-diary", subject: "topic", predicate: "mentions", object: "planning", source_type: "chat_diary", memory_type: "diary", status: "active" }),
      memoryFact({ fact_id: "fact-archived", subject: "tool", object: "old", status: "archived" }),
    ]);
    const onRefresh = vi.fn();

    renderView(api, onRefresh);
    openAdvancedMemoryTools();

    const confirmed = await screen.findByLabelText("已确认记忆");
    expect(within(confirmed).getByText("fruit is apple")).toBeInTheDocument();
    const candidates = screen.getByLabelText("待复核候选");
    expect(within(candidates).getByText("drink is tea")).toBeInTheDocument();
    const diary = screen.getByLabelText("日记来源记忆");
    expect(within(diary).getByText("topic mentions planning")).toBeInTheDocument();
    const archived = screen.getByLabelText("已归档或封存事实");
    expect(within(archived).getByText("tool is old")).toBeInTheDocument();
    const activeFactCard = within(confirmed).getByText("fruit is apple").closest("article");
    expect(activeFactCard).not.toBeNull();
    expect(within(activeFactCard as HTMLElement).getByText("风险 普通")).toBeInTheDocument();
    expect(within(activeFactCard as HTMLElement).getByText("来源")).toBeInTheDocument();
    expect(within(activeFactCard as HTMLElement).getByText("记住原因")).toBeInTheDocument();

    fireEvent.click(within(candidates).getByRole("button", { name: "确认" }));
    await waitFor(() => expect(api.confirmMemoryGraphFact).toHaveBeenCalledWith("fact-candidate"));

    fireEvent.click(within(activeFactCard as HTMLElement).getByRole("button", { name: "标为不准确" }));
    await waitFor(() => expect(api.markMemoryGraphFactWrong).toHaveBeenCalledWith("fact-active"));

    fireEvent.click(within(activeFactCard as HTMLElement).getByRole("button", { name: "归档" }));
    await waitFor(() => expect(api.archiveMemoryGraphFact).toHaveBeenCalledWith("fact-active"));

    fireEvent.click(within(activeFactCard as HTMLElement).getByRole("button", { name: "敏感封存" }));
    await waitFor(() => expect(api.sensitiveBlockMemoryGraphFact).toHaveBeenCalledWith("fact-active"));
    expect(onRefresh).toHaveBeenCalled();
  });

  it("marks an active long-term memory as inaccurate from the UI", async () => {
    const api = createApi([memoryFact()]);
    const onRefresh = vi.fn();

    renderView(api, onRefresh);
    openAdvancedMemoryTools();

    const confirmed = await screen.findByLabelText("已确认记忆");
    const factCard = within(confirmed).getByText("fruit is apple").closest("article");
    expect(factCard).not.toBeNull();
    fireEvent.click(within(factCard as HTMLElement).getByRole("button", { name: "标为不准确" }));

    await waitFor(() => expect(api.markMemoryGraphFactWrong).toHaveBeenCalledWith("fact-1"));
    expect(onRefresh).toHaveBeenCalled();
  });

  it("copies a redacted export preview without rendering source evidence", async () => {
    const api = createApi([memoryFact()]);

    renderView(api);
    openAdvancedMemoryTools();

    const confirmed = await screen.findByLabelText("已确认记忆");
    expect(within(confirmed).getByText("fruit is apple")).toBeInTheDocument();
    expect(screen.queryByText("raw evidence is not rendered")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "复制导出预览" }));

    await waitFor(() => expect(api.getMemoryGraphExportPreview).toHaveBeenCalledWith("markdown", null, "", 100));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining("fruit is apple"));
    expect(screen.getByLabelText("长期记忆导出预览")).toBeInTheDocument();
    expect(screen.queryByText("raw evidence is not rendered")).not.toBeInTheDocument();
  });

  it("downloads portable memory exports as Markdown and JSON", async () => {
    const api = createApi([memoryFact()]);

    renderView(api);
    openAdvancedMemoryTools();

    fireEvent.click(await screen.findByRole("button", { name: "下载 Markdown" }));
    await waitFor(() => expect(api.getMemoryGraphExportPreview).toHaveBeenCalledWith("markdown", null, "", 100));
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:memory-export");
    expect(await screen.findByText("已导出 1 条长期记忆为 Markdown。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下载 JSON" }));
    await waitFor(() => expect(api.getMemoryGraphExportPreview).toHaveBeenCalledWith("json", null, "", 100));
    expect(await screen.findByText("已导出 1 条长期记忆为 JSON。")).toBeInTheDocument();
  });

  it("shows review coach cards with source coverage before local assets", async () => {
    const api = createApi([memoryFact()]);

    renderView(api);
    openReviewTools();

    const coach = await screen.findByLabelText("复盘助手");
    const localAssets = (await screen.findByRole("button", { name: /刷新积累/ })).closest("section") as HTMLElement;
    expect(coach.compareDocumentPosition(localAssets) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(coach).getByText("今日复盘")).toBeInTheDocument();
    expect(within(coach).getByText("7 天复盘")).toBeInTheDocument();
    expect(within(coach).getByText("月度复盘")).toBeInTheDocument();

    const todayCard = within(coach).getByText("今日复盘").closest("article");
    expect(todayCard).not.toBeNull();
    expect(within(todayCard as HTMLElement).getByText("聊天日记")).toBeInTheDocument();
    expect(within(todayCard as HTMLElement).getByText("任务")).toBeInTheDocument();
    expect(within(todayCard as HTMLElement).getByText("长期记忆")).toBeInTheDocument();
    expect(within(todayCard as HTMLElement).getByText("资料整理")).toBeInTheDocument();
    expect(within(todayCard as HTMLElement).getByText("使用 1 条日记、1 个任务、1 条记忆事实和 1 次资料整理。")).toBeInTheDocument();
  });

  it("shows a weekly memory review and applies lightweight review actions", async () => {
    const api = createApi([memoryFact()]);
    const onRefresh = vi.fn();

    renderView(api, onRefresh);
    openAdvancedMemoryTools();

    const review = await screen.findByLabelText("本周记忆复核");
    expect(within(review).getAllByText("已保留").length).toBeGreaterThan(0);
    expect(within(review).getByText("临时")).toBeInTheDocument();
    expect(within(review).getAllByText("已忽略").length).toBeGreaterThan(0);
    expect(within(review).getByText("weekly review retained preference")).toBeInTheDocument();
    expect(within(review).getByText("Maybe use weekly planning prompts.")).toBeInTheDocument();
    expect(review.textContent).not.toMatch(/Bearer\s+\S+/i);
    expect(review.textContent).not.toContain("token=");

    const factCard = within(review).getByText("weekly review retained preference").closest("article");
    expect(factCard).not.toBeNull();
    fireEvent.click(within(factCard as HTMLElement).getByRole("button", { name: "只保留本周" }));

    await waitFor(() =>
      expect(api.applyWeeklyMemoryReviewAction).toHaveBeenCalledWith({
        target_type: "fact",
        target_id: "fact-1",
        action: "only_this_week",
        feedback_text: "weekly_memory_review:only_this_week",
        replacement_text: null,
      }),
    );
    expect(onRefresh).toHaveBeenCalled();
  });

  it("generates review reports without chat and exposes report artifacts", async () => {
    const api = createApi([memoryFact()]);

    renderView(api);
    openReviewTools();

    const coach = await screen.findByLabelText("复盘助手");
    fireEvent.click(within(coach).getByRole("button", { name: "生成今日复盘" }));

    await waitFor(() => expect(api.writeRetrospectiveReport).toHaveBeenCalledWith(1));
    expect(screen.getByLabelText("今日复盘报告产物")).toHaveTextContent("Wiki/Companion/Reports/2026-06-02-1d-review.md");

    fireEvent.click(within(coach).getByRole("button", { name: "生成 7 天复盘" }));
    await waitFor(() => expect(api.writeRetrospectiveReport).toHaveBeenCalledWith(7));

    fireEvent.click(within(coach).getByRole("button", { name: "生成月度复盘" }));
    await waitFor(() => expect(api.writeRetrospectivePeriodReport).toHaveBeenCalledWith("monthly"));
  });

  it("routes review report open and locate actions through Vault reveal IPC", async () => {
    const originalAgentDesktop = window.agentDesktop;
    const revealVaultPath = vi.fn().mockResolvedValue({ status: "shown", relative_path: "Wiki/Companion/Reports/2026-06-02-1d-review.md" });
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      revealVaultPath,
    };
    const api = createApi([memoryFact()]);

    try {
      renderView(api);
      openReviewTools();

      const coach = await screen.findByLabelText("复盘助手");
      fireEvent.click(within(coach).getByRole("button", { name: "生成今日复盘" }));
      const artifact = await screen.findByLabelText("今日复盘报告产物");
      fireEvent.click(within(artifact).getByRole("button", { name: "打开报告" }));
      fireEvent.click(within(artifact).getByRole("button", { name: "定位报告" }));

      await waitFor(() =>
        expect(revealVaultPath).toHaveBeenCalledWith("Wiki/Companion/Reports/2026-06-02-1d-review.md", "open"),
      );
      expect(revealVaultPath).toHaveBeenCalledWith("Wiki/Companion/Reports/2026-06-02-1d-review.md", "show");
    } finally {
      window.agentDesktop = originalAgentDesktop;
    }
  });

  it("manually generates a monthly local report from the review coach", async () => {
    const api = createApi([memoryFact()]);
    const onRefresh = vi.fn();

    renderView(api, onRefresh);
    openReviewTools();

    expect(await screen.findByLabelText("我的记忆控制台")).toBeInTheDocument();
    fireEvent.click(within(screen.getByLabelText("复盘助手")).getByRole("button", { name: "生成月度复盘" }));

    await waitFor(() => expect(api.writeRetrospectivePeriodReport).toHaveBeenCalledWith("monthly"));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
