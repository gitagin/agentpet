import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MemoryWindowView from "./MemoryWindowView";
import type { DesktopApi } from "../services/desktopApi";
import type { AgentAction, LocalAssetStatsResponse, MemoryGraphFact, MemoryGraphProjectionResponse, MemoryHygienePreviewResponse, MemoryProfileDetail, MemoryProfileProjectionResponse, MemoryProposalDraft, MemoryReviewResponse, MemorySearchResult, RetrospectiveReportResponse, RetrospectiveResponse } from "../types";

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

const hygienePreview: MemoryHygienePreviewResponse = {
  generated_at: "2026-06-02T00:00:00Z",
  redaction_note: "整理建议不会显示原始证据、内部编号、本地路径、凭据或完整授权信息。",
  suggestions: [
    {
      id: "hyg_safe_1",
      type: "stale_recent_state",
      title: "临时状态已过期",
      summary: "有一条临时状态已经到期，建议归档。",
      impact: "归档后不会再作为当前记忆使用。",
      risk_tier: "low",
      destructive: false,
      requires_confirmation: true,
      action_label: "归档",
    },
  ],
};

const emptyHygienePreview: MemoryHygienePreviewResponse = {
  generated_at: "2026-06-02T00:00:00Z",
  redaction_note: "整理建议不会显示原始证据、内部编号、本地路径、凭据或完整授权信息。",
  suggestions: [],
};

const emptyProfileProjection: MemoryProfileProjectionResponse = {
  generated_at: "2026-06-02T00:00:00Z",
  identity: [],
  preferences: [],
  boundaries: [],
  projects: [],
  relationships: [],
  recent_state: [],
  conflicts: [],
  needs_confirmation: [],
  filtered: [],
  redaction_note: "敏感内容、原始证据、凭据、完整授权信息和本机绝对路径不会显示在画像里。",
};

const profilePreference = {
  id: "profile_safe_item_1",
  category: "preferences",
  summary: "回答保持简洁",
  confidence: 0.91,
  importance: 0.82,
  status_label: "已确认",
  risk_label: "普通",
  source_label: "来自用户明确要求",
  updated_at: "2026-06-02T00:00:00Z",
  permissions_summary: "可用于回答",
  can_revoke: true,
  available_actions: ["撤回", "标记不准确"],
};

const profileWithPreference: MemoryProfileProjectionResponse = {
  ...emptyProfileProjection,
  preferences: [profilePreference],
};

const profilePreferenceDetail: MemoryProfileDetail = {
  id: "profile_safe_item_1",
  summary: "回答保持简洁",
  category_label: "偏好",
  status_label: "已确认",
  confidence_label: "可信度较高",
  importance_label: "比较重要",
  source_label: "来自用户明确要求",
  source_summary: {
    label: "来自多次聊天",
    description: "这条记忆由几次相关对话整理而来。",
    evidence_count_label: "有 2 条安全来源",
    last_seen_label: "最近更新于 2026-06-02",
    safety_note: "来源内容已做安全摘要，未显示原文。",
  },
  permissions: ["可用于回答", "不会主动提及"],
  safety_note: null,
  updated_at: "2026-06-02T00:00:00Z",
  available_actions: [
    { action: "forget", label: "撤回", requires_confirmation: true },
    { action: "mark_inaccurate", label: "标记不准确", requires_confirmation: true },
    { action: "keep", label: "确认记住", requires_confirmation: true },
  ],
};

const memoryGraphProjection: MemoryGraphProjectionResponse = {
  generated_at: "2026-06-02T00:00:00Z",
  nodes: [
    {
      id: "mg_user",
      type: "user",
      label: "我",
      subtitle: "记忆中心",
      status: "active",
      risk_tier: "low",
      size: 1.45,
      confidence_label: "由你掌控",
      source_label: "本机记忆图谱",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
    {
      id: "mg_pref",
      type: "preference",
      label: "回答保持简洁",
      subtitle: "偏好",
      status: "active",
      risk_tier: "low",
      size: 1.12,
      confidence_label: "较确定",
      source_label: "来自用户明确要求",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
    {
      id: "mg_project",
      type: "project",
      label: "Project Atlas 正在推进",
      subtitle: "项目",
      status: "active",
      risk_tier: "low",
      size: 1,
      confidence_label: "基本确定",
      source_label: "来自聊天日记",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
    {
      id: "mg_pending",
      type: "pending",
      label: "也许偏好长篇解释",
      subtitle: "待确认",
      status: "pending",
      risk_tier: "low",
      size: 0.9,
      confidence_label: "需要确认",
      source_label: "来自聊天后的整理",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
    {
      id: "mg_cleanup",
      type: "cleanup",
      label: "临时状态已过期",
      subtitle: "需要整理",
      status: "pending",
      risk_tier: "low",
      size: 0.82,
      confidence_label: "建议检查",
      source_label: "来自本机整理建议",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
    {
      id: "mg_hidden",
      type: "archived",
      label: "有一条已隐藏的记忆",
      subtitle: "已隐藏",
      status: "hidden",
      risk_tier: "hidden",
      size: 0.78,
      confidence_label: "细节已隐藏",
      source_label: "细节已隐藏",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
  ],
  edges: [
    { id: "mge_1", from: "mg_user", to: "mg_pref", type: "related_to", strength: 0.7 },
    { id: "mge_2", from: "mg_user", to: "mg_project", type: "related_to", strength: 0.7 },
  ],
  clusters: [
    { id: "cluster_preferences", label: "偏好", node_ids: ["mg_pref"] },
    { id: "cluster_projects", label: "项目", node_ids: ["mg_project"] },
    { id: "cluster_pending", label: "待确认", node_ids: ["mg_pending"] },
    { id: "cluster_cleanup", label: "需要整理", node_ids: ["mg_cleanup"] },
  ],
  summary: { total_nodes: 6, pending_count: 2, cleanup_count: 1, hidden_count: 1 },
  redaction_note: "敏感内容、原始证据、授权信息和本机路径不会显示。",
};

const emptyMemoryGraphProjection: MemoryGraphProjectionResponse = {
  ...memoryGraphProjection,
  nodes: [memoryGraphProjection.nodes[0]],
  edges: [],
  clusters: [],
  summary: { total_nodes: 1, pending_count: 0, cleanup_count: 0, hidden_count: 0 },
};

function createApi(
  facts: MemoryGraphFact[],
  stats: LocalAssetStatsResponse = localAssetStats,
  profile: MemoryProfileProjectionResponse = emptyProfileProjection,
  hygiene: MemoryHygienePreviewResponse = emptyHygienePreview,
  graph: MemoryGraphProjectionResponse = memoryGraphProjection,
) {
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
    getMemoryProfileProjection: vi.fn().mockResolvedValue(profile),
    getMemoryGraphProjection: vi.fn().mockResolvedValue(graph),
    getMemoryProfileDetail: vi.fn().mockResolvedValue(profilePreferenceDetail),
    submitMemoryProfileAction: vi.fn().mockResolvedValue({
      ok: true,
      message: "已撤回这条记忆，我不会再把它作为当前画像使用。",
      item_id: "profile_safe_item_1",
    }),
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
    getMemoryHygienePreview: vi.fn().mockResolvedValue(hygiene),
    applyMemoryHygieneSuggestion: vi.fn().mockResolvedValue({
      ok: true,
      suggestion_id: "hyg_safe_1",
      type: "stale_recent_state",
      status: "archived",
      action_id: "action-hygiene-1",
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
  return render(
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
  openMemoryWorkspaceTab("数据");
  const advanced = screen.getByText("高级备份与检查").closest("details") as HTMLDetailsElement;
  expect(advanced).toBeInTheDocument();
  expect(advanced).not.toHaveAttribute("open");
  fireEvent.click(within(advanced).getByText("高级备份与检查"));
  expect(advanced).toHaveAttribute("open");
  return advanced;
}

function openMemoryWorkspaceTab(label: string) {
  const tab = screen.getByRole("tab", { name: new RegExp(label), hidden: true });
  fireEvent.click(tab);
  expect(tab).toHaveAttribute("aria-selected", "true");
  return screen.getByRole("tabpanel", { name: new RegExp(`记忆工作台：${label}`) });
}

function openArchiveTab() {
  return openMemoryWorkspaceTab("档案");
}

function openDataTab() {
  return openMemoryWorkspaceTab("数据");
}

function openSearchTab() {
  return openMemoryWorkspaceTab("搜索");
}

function openDecayTab() {
  return openMemoryWorkspaceTab("衰减图");
}

function openDiaryTab() {
  return openMemoryWorkspaceTab("日记");
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

  it("keeps the hidden graph implementation lazy", async () => {
    const api = createApi([memoryFact()]);

    const { container } = renderView(api);
    expect(api.getMemoryGraphProjection).not.toHaveBeenCalled();
    openMemoryWorkspaceTab("图谱");

    const graph = await screen.findByLabelText("我的记忆图谱");
    expect(document.getElementById("memory-workspace-panel-graph")).toHaveClass("memory-workspace-tab-panel-graph");
    expect(api.getMemoryGraphProjection).toHaveBeenCalledTimes(1);
    expect(within(graph).getByText("我的记忆图谱")).toBeInTheDocument();
    expect(within(graph).getByText("偏好、边界、项目、情景和资料会在这里连成一张可理解的记忆地图。")).toBeInTheDocument();
    expect(within(graph).getByText("记忆节点")).toBeInTheDocument();
    expect(within(graph).getByText("6")).toBeInTheDocument();
    expect(within(graph).getByText("回答保持简洁")).toBeInTheDocument();
    expect(within(graph).getByText("Project Atlas 正在推进")).toBeInTheDocument();
    expect(within(graph).getByLabelText("记忆知识图谱画布")).toBeInTheDocument();
    expect(graph.querySelector(".react-flow")).toBeInTheDocument();
    expect(graph.querySelector(".memory-node-center")).toBeInTheDocument();
    fireEvent.click(within(graph).getByLabelText("记忆节点：回答保持简洁"));
    expect(within(graph).getByLabelText("记忆节点详情")).toHaveTextContent("来自用户明确要求");
    expect(container.textContent).not.toMatch(
      /candidate|fact|evidence|source_text|source_excerpt|agent_run_id|message_id|conversation_id|lifecycle_status|Authorization|token|FTS|vector|[A-Za-z]:[\\/]/i,
    );
  });

  it("renders the memory graph empty state from the projection", async () => {
    const api = createApi([memoryFact()], localAssetStats, emptyProfileProjection, emptyHygienePreview, emptyMemoryGraphProjection);

    renderView(api);
    openMemoryWorkspaceTab("图谱");

    const graph = await screen.findByLabelText("我的记忆图谱");
    expect(within(graph).getByText("记忆图谱还是空的")).toBeInTheDocument();
    expect(within(graph).getByText("告诉我一些关于你的事，我会把它们连成一张记忆地图。")).toBeInTheDocument();
    expect(within(graph).getByText("告诉我一个偏好")).toBeInTheDocument();
    expect(within(graph).getByText("告诉我正在做的项目")).toBeInTheDocument();
  });

  it("keeps the material library as an internal memory workspace entry", async () => {
    const api = createApi([memoryFact()]);
    window.location.hash = "#memory";

    renderView(api);
    const importPanel = openMemoryWorkspaceTab("导入");

    expect(within(importPanel).getByLabelText("资料导入入口")).toBeInTheDocument();
    expect(within(importPanel).getAllByText("资料库").length).toBeGreaterThan(0);
    expect(within(importPanel).getByText(/记忆工作台/)).toBeInTheDocument();
    fireEvent.click(within(importPanel).getByRole("button", { name: "打开资料库" }));
    expect(window.location.hash).toBe("#world");
  });

  it("shows a safe graph error if the projection request fails", async () => {
    const api = createApi([memoryFact()]);
    (api.getMemoryGraphProjection as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("source_text Authorization token C:\\secret"),
    );

    const { container } = renderView(api);
    openMemoryWorkspaceTab("图谱");

    const graph = await screen.findByLabelText("我的记忆图谱");
    expect(within(graph).getByRole("alert")).toHaveTextContent("这次没能打开记忆图谱，请稍后重试。");
    expect(container.textContent).not.toMatch(/source_text|Authorization|token|C:\\secret/i);
  });

  it("renders local asset stats from the local dashboard", async () => {
    const api = createApi([memoryFact()]);

    renderView(api);
    openDataTab();

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

  it("renders an empty profile projection without internal terms", async () => {
    const api = createApi([memoryFact()]);

    const { container } = renderView(api);
    openArchiveTab();

    const profile = await screen.findByLabelText("只读记忆概览");
    expect(within(profile).getByText("我现在记得什么")).toBeInTheDocument();
    expect(within(profile).getAllByText("我还没有形成稳定画像，继续聊天后会在你确认下逐步整理。").length).toBeGreaterThan(0);
    expect(api.getMemoryProfileProjection).toHaveBeenCalled();
    expect(container.textContent).not.toMatch(/agent_run_id|memory_candidates|FTS|vector|lifecycle_status|source_text|source_excerpt|Authorization|Bearer/i);
  });

  it("opens a safe profile detail drawer from a profile item", async () => {
    const api = createApi([memoryFact()], localAssetStats, profileWithPreference);

    const { container } = renderView(api);
    openArchiveTab();

    const profile = await screen.findByLabelText("只读记忆概览");
    fireEvent.click(within(profile).getByRole("button", { name: "查看记忆详情：回答保持简洁" }));

    const drawer = await screen.findByRole("dialog", { name: "记忆详情" });
    expect(api.getMemoryProfileDetail).toHaveBeenCalledWith("profile_safe_item_1", undefined);
    expect(within(drawer).getByText("回答保持简洁")).toBeInTheDocument();
    expect(within(drawer).getByText("偏好")).toBeInTheDocument();
    expect(within(drawer).getByText("已确认")).toBeInTheDocument();
    expect(within(drawer).getByText("可信度较高")).toBeInTheDocument();
    expect(within(drawer).getByText("比较重要")).toBeInTheDocument();
    expect(within(drawer).getByText("来自用户明确要求")).toBeInTheDocument();
    expect(within(drawer).getByText("来源说明")).toBeInTheDocument();
    expect(within(drawer).getByText("这条记忆由几次相关对话整理而来。")).toBeInTheDocument();
    expect(within(drawer).getByText("有 2 条安全来源")).toBeInTheDocument();
    expect(within(drawer).getByText("最近更新于 2026-06-02")).toBeInTheDocument();
    expect(within(drawer).getByText("来源内容已做安全摘要，未显示原文。")).toBeInTheDocument();
    expect(within(drawer).getByText("可用于回答")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(
      /agent_run_id|memory_candidates|FTS|vector|lifecycle_status|source_text|source_excerpt|Authorization|token|[A-Za-z]:\\/i,
    );
  });

  it("shows a safe empty state when profile detail has no source summary", async () => {
    const api = createApi([memoryFact()], localAssetStats, profileWithPreference);
    (api.getMemoryProfileDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...profilePreferenceDetail,
      source_summary: null,
    });

    const { container } = renderView(api);
    openArchiveTab();

    const profile = await screen.findByLabelText("只读记忆概览");
    fireEvent.click(within(profile).getByRole("button", { name: "查看记忆详情：回答保持简洁" }));

    const drawer = await screen.findByRole("dialog", { name: "记忆详情" });
    expect(within(drawer).getByText("来源说明")).toBeInTheDocument();
    expect(within(drawer).getByText("暂时没有可安全展示的来源说明。")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(
      /agent_run_id|memory_candidates|FTS|vector|lifecycle_status|source_text|source_excerpt|Authorization|token|[A-Za-z]:\\/i,
    );
  });

  it("filters unsafe source summary text in the profile detail drawer", async () => {
    const api = createApi([memoryFact()], localAssetStats, profileWithPreference);
    (api.getMemoryProfileDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...profilePreferenceDetail,
      source_summary: {
        label: "agent_run_id source_text",
        description: "Authorization C:\\Users\\Alice\\Vault\\Secret.md",
        evidence_count_label: "memory_candidates target_id",
        last_seen_label: "vector lifecycle_status",
        safety_note: "token source_excerpt",
      },
    });

    const { container } = renderView(api);
    openArchiveTab();

    fireEvent.click(await screen.findByRole("button", { name: "查看记忆详情：回答保持简洁" }));

    expect((await screen.findAllByText("敏感细节、原始证据和本机安全信息已隐藏。")).length).toBeGreaterThan(0);
    expect(container.textContent).not.toMatch(
      /agent_run_id|memory_candidates|target_id|FTS|vector|lifecycle_status|source_text|source_excerpt|Authorization|token|C:\\Users\\Alice/i,
    );
  });

  it("requires confirmation before profile drawer actions", async () => {
    const api = createApi([memoryFact()], localAssetStats, profileWithPreference);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);

    renderView(api);
    openArchiveTab();

    fireEvent.click(await screen.findByRole("button", { name: "查看记忆详情：回答保持简洁" }));
    const drawer = await screen.findByRole("dialog", { name: "记忆详情" });
    fireEvent.click(within(drawer).getByRole("button", { name: "撤回" }));

    expect(confirm).toHaveBeenCalledWith("撤回后，我不会再把这条作为当前画像使用。确定继续吗？");
    expect(api.submitMemoryProfileAction).not.toHaveBeenCalled();
  });

  it("submits confirmed profile actions and refreshes the profile", async () => {
    const api = createApi([memoryFact()], localAssetStats, profileWithPreference);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderView(api);
    openArchiveTab();

    fireEvent.click(await screen.findByRole("button", { name: "查看记忆详情：回答保持简洁" }));
    const drawer = await screen.findByRole("dialog", { name: "记忆详情" });
    fireEvent.click(within(drawer).getByRole("button", { name: "标记不准确" }));

    await waitFor(() =>
      expect(api.submitMemoryProfileAction).toHaveBeenCalledWith(
        "profile_safe_item_1",
        expect.objectContaining({ action: "mark_inaccurate", confirmed: true }),
      ),
    );
    await waitFor(() => expect(api.getMemoryProfileProjection).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("已撤回这条记忆，我不会再把它作为当前画像使用。")).toBeInTheDocument();
  });

  it("shows safe errors for profile detail and action failures without optimistic removal", async () => {
    const api = createApi([memoryFact()], localAssetStats, profileWithPreference);
    (api.getMemoryProfileDetail as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("source_text Authorization C:\\secret"));

    renderView(api);
    openArchiveTab();

    fireEvent.click(await screen.findByRole("button", { name: "查看记忆详情：回答保持简洁" }));
    expect(await screen.findByText("这次没能打开详情，请稍后重试。")).toBeInTheDocument();
    expect(screen.queryByText(/source_text|Authorization|C:\\secret/)).not.toBeInTheDocument();

    (api.getMemoryProfileDetail as ReturnType<typeof vi.fn>).mockResolvedValue(profilePreferenceDetail);
    (api.submitMemoryProfileAction as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("target_id memory_candidates"));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(await screen.findByRole("button", { name: "查看记忆详情：回答保持简洁" }));
    const drawer = await screen.findByRole("dialog", { name: "记忆详情" });
    fireEvent.click(within(drawer).getByRole("button", { name: "撤回" }));

    expect(await screen.findByText("这次没有改动记忆，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看记忆详情：回答保持简洁" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/target_id|memory_candidates|source_text|Authorization|C:\\secret/i);
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

    expect(screen.queryByRole("heading", { name: "记忆工作台" })).not.toBeInTheDocument();
    expect(screen.queryByText("档案、图谱、日记和资料都在这里，你可以查看、搜索、整理和改正。")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /档案/ })).toHaveAttribute("aria-selected", "true");
    ["档案", "搜索", "活动账本"].forEach((label) => {
      expect(screen.getByRole("tab", { name: new RegExp(label) })).toBeInTheDocument();
    });
    ["数据", "导入", "图谱", "关联", "热力图", "衰减图", "日记"].forEach((label) => {
      expect(screen.queryByRole("tab", { name: new RegExp(label) })).not.toBeInTheDocument();
    });

    openArchiveTab();
    const control = await screen.findByLabelText("记忆主视图");
    await within(control).findByText("fruit is apple");
    await within(control).findByText("fruit is banana");
    expect(within(control).getByText("我现在记得什么")).toBeInTheDocument();
    expect(within(control).getAllByText("等你确认").length).toBeGreaterThan(0);
    expect(within(control).getByText("随时改正或忘记")).toBeInTheDocument();
    expect(within(control).getByText("fruit is apple")).toBeInTheDocument();
    expect(within(control).getByText("fruit is banana")).toBeInTheDocument();
    expect(within(control).getByText("可撤回记忆记录")).toBeInTheDocument();
    expect(within(control).getByRole("button", { name: "撤回" })).toBeInTheDocument();

    expect(screen.queryByText("高级备份与检查")).not.toBeInTheDocument();

    openAdvancedMemoryTools();
    expect(screen.getByLabelText("高级备份与检查")).toBeInTheDocument();
    expect(screen.getByLabelText("已确认记忆")).toBeInTheDocument();
    expect(screen.queryByLabelText(/chat/i)).not.toBeInTheDocument();
  });

  it("offers guided trials for memory search, saving a preference, and today's review", async () => {
    const api = createApi([memoryFact()]);
    const onMemorySearchQueryChange = vi.fn();
    const onMemoryProposalDraftChange = vi.fn();

    renderView(api, vi.fn(), { onMemorySearchQueryChange, onMemoryProposalDraftChange });
    openSearchTab();

    fireEvent.click(screen.getByRole("button", { name: "搜索记忆" }));
    expect(onMemorySearchQueryChange).toHaveBeenCalledWith("发布清单");

    openArchiveTab();
    fireEvent.click(screen.getByRole("button", { name: "保存一个偏好" }));
    expect(onMemoryProposalDraftChange).toHaveBeenCalledWith({
      type: "preference",
      content: "我偏好简洁的发布清单。",
      target_path: "Inbox/Pending Memories.md",
    });

    openDiaryTab();
    fireEvent.click(within(await screen.findByLabelText("复盘助手")).getByRole("button", { name: "生成今日复盘" }));
    await waitFor(() => expect(api.writeRetrospectiveReport).toHaveBeenCalledWith(1));
  });

  it("runs memory search without opening chat", async () => {
    const api = createApi([memoryFact()]);

    renderView(api, vi.fn(), { memorySearchQuery: "发布清单" });
    openSearchTab();

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
    openArchiveTab();

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
    openDataTab();

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
    const advanced = openAdvancedMemoryTools();

    const confirmed = await screen.findByLabelText("已确认记忆");
    expect(within(confirmed).getByText("fruit is apple")).toBeInTheDocument();
    const candidates = within(advanced).getByLabelText("等你确认");
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
    expect(activeFactCard).toHaveTextContent("来自一次聊天");
    expect(diary).toHaveTextContent("来自聊天日记");
    expect(confirmed.textContent).not.toMatch(/target_id|candidate:|fact:|memory_candidates|source_text|source_excerpt|agent_run_id|lifecycle_status|FTS|vector|Authorization|token|\bactive\b|\bcandidate\b|\bstale\b|\brejected\b|\bforgotten\b|\bsuperseded\b/i);
    expect(diary.textContent).not.toMatch(/chat_diary|target_id|source_text|source_excerpt|lifecycle_status|FTS|vector|Authorization|token/i);

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

    fireEvent.click(await screen.findByRole("button", { name: "下载 Markdown 备份" }));
    await waitFor(() => expect(api.getMemoryGraphExportPreview).toHaveBeenCalledWith("markdown", null, "", 100));
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:memory-export");
    expect(await screen.findByText("已导出 1 条长期记忆为 Markdown。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下载 JSON 备份" }));
    await waitFor(() => expect(api.getMemoryGraphExportPreview).toHaveBeenCalledWith("json", null, "", 100));
    expect(await screen.findByText("已导出 1 条长期记忆为 JSON。")).toBeInTheDocument();
  });

  it("shows review coach cards with source coverage before local assets", async () => {
    const api = createApi([memoryFact()]);

    renderView(api);
    openDiaryTab();

    const coach = await screen.findByLabelText("复盘助手");
    expect(within(coach).getByText("今日复盘")).toBeInTheDocument();
    expect(within(coach).getByText("7 天复盘")).toBeInTheDocument();
    expect(within(coach).getByText("月度复盘")).toBeInTheDocument();

    const todayCard = within(coach).getByText("今日复盘").closest("article");
    expect(todayCard).not.toBeNull();
    expect(within(todayCard as HTMLElement).getByText("聊天日记")).toBeInTheDocument();
    expect(within(todayCard as HTMLElement).getByText("任务")).toBeInTheDocument();
    expect(within(todayCard as HTMLElement).getByText("长期记忆")).toBeInTheDocument();
    expect(within(todayCard as HTMLElement).getByText("资料整理")).toBeInTheDocument();
    expect(within(todayCard as HTMLElement).getByText("使用 1 条日记、1 个任务、1 条长期记忆和 1 次资料整理。")).toBeInTheDocument();
  });

  it("scans and displays hygiene suggestions safely", async () => {
    const api = createApi([memoryFact()], localAssetStats, emptyProfileProjection, hygienePreview);

    const { container } = renderView(api);
    const decayPanel = openDecayTab();
    fireEvent.click(within(decayPanel).getByRole("button", { name: "扫描整理建议" }));

    const panel = await screen.findByLabelText("整理建议");
    expect(api.getMemoryHygienePreview).toHaveBeenCalledTimes(1);
    expect(within(panel).getByText("临时状态已过期")).toBeInTheDocument();
    expect(within(panel).getByText("有一条临时状态已经到期，建议归档。")).toBeInTheDocument();
    expect(within(panel).getByText("归档后不会再作为当前记忆使用。")).toBeInTheDocument();
    expect(within(panel).getByText("低风险")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "归档" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /批量/ })).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/candidate|fact|target_id|evidence|source_text|source_excerpt|agent_run_id|lifecycle_status|Authorization|token|[A-Za-z]:[\\/]|FTS|vector/i);
  });

  it("shows an empty hygiene suggestion state after scanning", async () => {
    const api = createApi([memoryFact()], localAssetStats, emptyProfileProjection, emptyHygienePreview);

    renderView(api);
    const decayPanel = openDecayTab();
    fireEvent.click(within(decayPanel).getByRole("button", { name: "扫描整理建议" }));

    expect(await screen.findByText("暂时没有需要整理的记忆。")).toBeInTheDocument();
  });

  it("requires confirmation before applying a hygiene suggestion", async () => {
    const api = createApi([memoryFact()], localAssetStats, emptyProfileProjection, hygienePreview);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);

    renderView(api);
    const decayPanel = openDecayTab();
    fireEvent.click(within(decayPanel).getByRole("button", { name: "扫描整理建议" }));
    const panel = await screen.findByLabelText("整理建议");
    fireEvent.click(within(panel).getByRole("button", { name: "归档" }));

    expect(confirm).toHaveBeenCalledWith("确定要应用这条整理建议吗？这会更新记忆状态。");
    expect(api.applyMemoryHygieneSuggestion).not.toHaveBeenCalled();
  });

  it("applies one hygiene suggestion with confirmed true and refreshes memory views", async () => {
    const api = createApi([memoryFact()], localAssetStats, profileWithPreference, hygienePreview);
    const onRefresh = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderView(api, onRefresh);
    const decayPanel = openDecayTab();
    fireEvent.click(within(decayPanel).getByRole("button", { name: "扫描整理建议" }));
    const panel = await screen.findByLabelText("整理建议");
    fireEvent.click(within(panel).getByRole("button", { name: "归档" }));

    await waitFor(() => expect(api.applyMemoryHygieneSuggestion).toHaveBeenCalledWith("hyg_safe_1", true));
    await waitFor(() => expect(api.getMemoryHygienePreview).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.getMemoryProfileProjection).toHaveBeenCalledTimes(2));
    expect(api.getWeeklyMemoryReview).toHaveBeenCalledTimes(2);
    expect(api.getLocalAssetStats).toHaveBeenCalledTimes(1);
    expect(onRefresh).toHaveBeenCalled();
  });

  it("keeps hygiene suggestions visible and shows a safe error when apply fails", async () => {
    const api = createApi([memoryFact()], localAssetStats, emptyProfileProjection, hygienePreview);
    (api.applyMemoryHygieneSuggestion as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("source_text Authorization token C:\\secret"),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const { container } = renderView(api);
    const decayPanel = openDecayTab();
    fireEvent.click(within(decayPanel).getByRole("button", { name: "扫描整理建议" }));
    const panel = await screen.findByLabelText("整理建议");
    fireEvent.click(within(panel).getByRole("button", { name: "归档" }));

    expect(await within(panel).findByText("这次没有完成整理，请稍后重试。")).toBeInTheDocument();
    expect(within(panel).getByText("临时状态已过期")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/source_text|Authorization|token|C:\\secret/i);
  });

  it("filters raw-ish hygiene suggestion text before rendering", async () => {
    const rawishPreview: MemoryHygienePreviewResponse = {
      generated_at: "2026-06-02T00:00:00Z",
      redaction_note: "source_text Authorization token C:\\Users\\Ada\\secret.md",
      suggestions: [
        {
          id: "hyg_raw_1",
          type: "sensitive_candidate",
          title: "candidate fact target_id",
          summary: "source_text Authorization Bearer token C:\\Users\\Ada\\secret.md",
          impact: "evidence agent_run_id lifecycle_status FTS vector",
          risk_tier: "low",
          destructive: false,
          requires_confirmation: true,
          action_label: "token=secret",
        },
      ],
    };
    const api = createApi([memoryFact()], localAssetStats, emptyProfileProjection, rawishPreview);

    const { container } = renderView(api);
    const decayPanel = openDecayTab();
    fireEvent.click(within(decayPanel).getByRole("button", { name: "扫描整理建议" }));

    const panel = await screen.findByLabelText("整理建议");
    expect(within(panel).getAllByText("整理建议").length).toBeGreaterThan(0);
    expect(within(panel).getByText("这条建议的安全摘要暂时不可显示。")).toBeInTheDocument();
    expect(within(panel).getByText("应用后会更新记忆状态。")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "应用建议" })).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/candidate|fact|target_id|evidence|source_text|source_excerpt|agent_run_id|lifecycle_status|Authorization|Bearer|token|C:\\Users|FTS|vector/i);
  });

  it("shows a weekly memory review and applies lightweight review actions", async () => {
    const api = createApi([memoryFact()]);
    const onRefresh = vi.fn();

    renderView(api, onRefresh);
    openDecayTab();

    const review = await screen.findByLabelText("本周记忆复核");
    expect(within(review).getAllByText("已保留").length).toBeGreaterThan(0);
    expect(within(review).getByText("临时")).toBeInTheDocument();
    expect(within(review).getAllByText("已忽略").length).toBeGreaterThan(0);
    expect(within(review).getByText("weekly review retained preference")).toBeInTheDocument();
    expect(within(review).getByText("Maybe use weekly planning prompts.")).toBeInTheDocument();
    expect(review.textContent).not.toMatch(/Bearer\s+\S+/i);
    expect(review.textContent).not.toContain("token=");
    expect(review.textContent).not.toMatch(/target_id|candidate:|fact:|memory_candidates|source_text|source_excerpt|agent_run_id|lifecycle_status|FTS|vector|Authorization|expires|\bactive\b|\bcandidate\b|\bstale\b|\brejected\b|\bforgotten\b|\bsuperseded\b/i);
    expect(within(review).getAllByText("使用中").length).toBeGreaterThan(0);
    expect(within(review).getAllByText("等你确认").length).toBeGreaterThan(0);
    expect(review).toHaveTextContent("来自一次聊天");
    expect(review).toHaveTextContent("来自聊天后的整理");

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
    openDiaryTab();

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
      openDiaryTab();

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
    openDiaryTab();

    fireEvent.click(within(screen.getByLabelText("复盘助手")).getByRole("button", { name: "生成月度复盘" }));

    await waitFor(() => expect(api.writeRetrospectivePeriodReport).toHaveBeenCalledWith("monthly"));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
