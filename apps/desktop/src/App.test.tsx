import { createRef } from "react";
import type { MouseEvent, PointerEvent } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { AgentAction, DesktopSidecarStatus } from "./types";
import { navigationHashForTab, primaryNavigationTabs } from "./views/navigation";

const mockPetShowInput = vi.hoisted(() => vi.fn());
const mockTtsStop = vi.hoisted(() => vi.fn());
const mockTtsWaitingCueStart = vi.hoisted(() => vi.fn(() => "我想一下。"));
const mockTtsWaitingCueStop = vi.hoisted(() => vi.fn());
const mockTtsQueueStatus = vi.hoisted(() => ({ current: "idle" }));
const mockTtsQueueError = vi.hoisted(() => ({
  current: null as null | {
    code: string;
    message: string;
    provider?: string;
    itemId?: string;
    recoverable: boolean;
  },
}));
const mockTtsPlaybackQueueOptions = vi.hoisted(() => ({
  current: null as null | {
    onPlaybackStart?: (item: any) => void;
    onPlaybackEnd?: (item: any, status: any) => void;
  },
}));
const mockCreateBackendTtsProvider = vi.hoisted(() =>
  vi.fn(({ providerId = "custom-http" }: { providerId?: string } = {}) => ({ id: providerId })),
);
const spritePetStageRenderProps = vi.hoisted(() => [] as Array<{
  canvasRef: unknown;
  dragging?: boolean;
  dragDirection?: string;
  petInteractions?: {
    onPointerDown?: (event: PointerEvent<HTMLElement>) => void;
    onPointerMove?: (event: PointerEvent<HTMLElement>) => void;
    onPointerUp?: (event: PointerEvent<HTMLElement>) => void;
  };
}>);

vi.mock("./features/pet/SpritePetStage", () => ({
  SpritePetStage: ({
    canvasRef,
    dragging,
    dragDirection,
    petInteractions,
  }: {
    canvasRef?: unknown;
    dragging?: boolean;
    dragDirection?: string;
    petInteractions?: {
      onPointerDown?: (event: PointerEvent<HTMLElement>) => void;
      onPointerMove?: (event: PointerEvent<HTMLElement>) => void;
      onPointerUp?: (event: PointerEvent<HTMLElement>) => void;
      onPointerCancel?: (event: PointerEvent<HTMLElement>) => void;
      onLostPointerCapture?: (event: PointerEvent<HTMLElement>) => void;
      onContextMenu?: (event: MouseEvent<HTMLElement>) => void;
      onDoubleClick?: (event: MouseEvent<HTMLElement>) => void;
    };
  }) => {
    spritePetStageRenderProps.push({ canvasRef, dragging, dragDirection, petInteractions });
    return (
      <section
        aria-label="mock pet stage"
        onPointerDown={petInteractions?.onPointerDown}
        onPointerMove={petInteractions?.onPointerMove}
        onPointerUp={petInteractions?.onPointerUp}
        onPointerCancel={petInteractions?.onPointerCancel}
        onLostPointerCapture={petInteractions?.onLostPointerCapture}
        onContextMenu={petInteractions?.onContextMenu}
        onDoubleClick={petInteractions?.onDoubleClick}
      />
    );
  },
}));

vi.mock("./features/chat/PetChatOverlay", () => ({
  PetChatOverlay: () => <section aria-label="mock pet chat overlay" />,
}));

vi.mock("./features/tts", () => ({
  createBackendTtsProvider: mockCreateBackendTtsProvider,
  createMockTtsProvider: vi.fn(() => ({ id: "mock" })),
  createSystemTtsProvider: vi.fn(() => ({ id: "system" })),
  useTtsWaitingCue: () => ({
    start: mockTtsWaitingCueStart,
    stop: mockTtsWaitingCueStop,
    prefetch: vi.fn(),
  }),
  useTtsPlaybackQueue: (options: { onPlaybackStart?: (item: any) => void; onPlaybackEnd?: (item: any, status: any) => void }) => {
    mockTtsPlaybackQueueOptions.current = options;
    return {
      state: {
        status: mockTtsQueueStatus.current,
        currentItem: null,
        queue: [],
        error: mockTtsQueueError.current,
        volume: 1,
        updatedAt: "2026-07-04T00:00:00.000Z",
      },
      enqueue: vi.fn(),
      prefetch: vi.fn(),
      prefetchMany: vi.fn(),
      play: vi.fn(),
      stop: mockTtsStop,
      cancelMessage: vi.fn(),
      clear: vi.fn(),
      setVolume: vi.fn(),
    };
  },
}));

vi.mock("./features/connection/ConnectionPanel", () => ({
  ConnectionPanel: () => <section aria-label="mock connection panel" />,
}));

vi.mock("./features/connection/HealthStatus", () => ({
  ConnectionStatusStrip: () => <section aria-label="mock connection status" />,
}));

vi.mock("./features/tasks/TaskPanel", () => ({
  TaskPanel: () => <section aria-label="mock task panel" />,
}));

vi.mock("./features/settings/SettingsPanel", () => ({
  SettingsPanel: () => <section aria-label="mock settings panel" />,
}));

vi.mock("./features/memory/MemoryProposalActivityCard", () => ({
  MemoryProposalActivityCard: () => <section aria-label="mock memory proposal card" />,
}));

vi.mock("./features/wiki/ChatWikiProposalCard", () => ({
  ChatWikiProposalCard: () => <section aria-label="mock wiki proposal card" />,
}));

vi.mock("./features/wiki/WikiWorkflowPanel", () => ({
  WikiWorkflowPanel: () => <section aria-label="mock wiki workflow panel" />,
}));

vi.mock("./features/chat/ChatMessageList", () => ({
  ChatMessageList: ({ messages = [] }: { messages?: Array<{ id: string; content: string }> }) => (
    <section aria-label="mock chat message list">
      {messages.map((message) => (
        <p key={message.id}>{message.content}</p>
      ))}
    </section>
  ),
}));

vi.mock("./features/continuity", () => ({
  VisibleContinuityPanel: () => (
    <section id="visible-continuity-panel" aria-label="mock visible continuity panel">
      Visible continuity outcomes
    </section>
  ),
}));

const sidecarStatus: DesktopSidecarStatus = {
  state: "ready",
  baseUrl: "http://127.0.0.1:8765",
  host: "127.0.0.1",
  port: 8765,
  logPath: "C:\\logs\\agent-pet-sidecar.log",
  managed: true,
  pid: 1234,
  updatedAt: "2026-05-24T00:00:00.000Z",
  health: { status: "ok", version: "0.0.1-alpha", database: "ok" },
  error: null,
};

const api = {
  startChat: vi.fn().mockResolvedValue({
    conversation_id: "conversation-1",
    message_id: "message-1",
    agent_run_id: "run-1",
    stream_url: "/api/chat/runs/run-1/events",
  }),
  getDailyChatHistory: vi.fn().mockResolvedValue({
    date: "2026-07-09",
    timezone: "Asia/Shanghai",
    conversation_id: null,
    messages: [],
    has_more: false,
  }),
  getSettingsStatus: vi.fn().mockResolvedValue({ model_configured: false, vault_configured: false }),
  getVaultStatus: vi.fn().mockResolvedValue({
    configured: false,
    active_vault_id: null,
    root_path: "",
    root_path_label: null,
    latest_indexed_at: null,
    markdown_count: 0,
    wiki_page_count: 0,
    diary_page_count: 0,
  }),
  listMemoryProposals: vi.fn().mockResolvedValue({ proposals: [] }),
  listAgentActions: vi.fn().mockResolvedValue({ actions: [] }),
  getContinuityState: vi.fn().mockResolvedValue({ items: [] }),
  listContinuityProposals: vi.fn().mockResolvedValue({ proposals: [] }),
  confirmContinuityProposal: vi.fn().mockResolvedValue({ proposal_id: "continuity-1", status: "confirmed" }),
  rejectContinuityProposal: vi.fn().mockResolvedValue({ proposal_id: "continuity-1", status: "rejected" }),
  getVisibleContinuitySnapshot: vi.fn(),
  triggerHabitLoop: vi.fn().mockResolvedValue({ should_trigger: false, candidate: null }),
  revertAgentAction: vi.fn(),
  exportDiagnostics: vi.fn(),
  resetLocalState: vi.fn(),
};

function agentActionForTest(index: number): AgentAction {
  const day = String(index).padStart(2, "0");
  return {
    action_id: `action-${index}`,
    source_agent_run_id: `run-${index}`,
    source_conversation_id: `conversation-${index}`,
    source_message_id: `message-${index}`,
    action_type: "chat.daily_archive",
    risk_tier: "low",
    decision: "auto",
    status: "completed",
    title: `测试自动整理 ${index}`,
    summary: `这是第 ${index} 条完整记忆记录`,
    target_paths: [`Daily/2026-07-${day}.md`],
    reversible: false,
    reverted_by: null,
    reverts_action_id: null,
    error: null,
    source: {},
    diff_summary: "",
    metadata: {},
    created_at: `2026-07-${day}T10:00:00.000Z`,
    updated_at: `2026-07-${day}T10:00:00.000Z`,
    completed_at: `2026-07-${day}T10:00:00.000Z`,
  };
}

vi.mock("./services/sse", () => ({
  fetchSseStream: vi.fn().mockImplementation(async (_client, _url, handlers) => {
    handlers.onOpen?.();
    handlers.onEvent({ event: "token", data: JSON.stringify({ text: "已收到你的首次引导。" }) });
    handlers.onEvent({ event: "done", data: JSON.stringify({ text: "已收到你的首次引导。" }) });
  }),
}));

vi.mock("./features/connection/useConnection", () => ({
  useConnection: () => ({
    api,
    businessAuthMessage: "业务接口鉴权可用。",
    businessAuthStatus: "ready",
    checkHealth: vi.fn(),
    checkingHealth: false,
    client: {},
    health: sidecarStatus.health,
    persistSettings: vi.fn(),
    setBusinessAuthReady: vi.fn(),
    setSettings: vi.fn(),
    settings: { baseUrl: sidecarStatus.baseUrl },
    sidecarStatus,
  }),
}));

vi.mock("./features/settings/useSettings", () => ({
  useSettings: () => ({
    agentModelDrafts: [],
    agentModelTestResults: {},
    applyDiagnosticsStatus: vi.fn(),
    applySettingsStatus: vi.fn(),
    automationSettingsDraft: {
      auto_chat_diary: false,
      auto_structured_memory: false,
      auto_long_term_memory: false,
      auto_wiki_organize: false,
      local_privacy_mode: false,
      proactive_trigger_frequency: "low",
      use_negotiation: true,
      max_rounds: 5,
      high_risk_confirmation_required: true,
      updated_at: null,
    },
    automationSettingsSaveStatus: "idle",
    bindVault: vi.fn(),
    clearTtsCache: vi.fn(),
    globalModelDraft: {
      provider: "openai-compatible",
      base_url: "",
      model: "",
      api_key: "",
      saved_provider: "openai-compatible",
      saved_base_url: "",
      saved_model: "",
      configured: false,
    },
    globalModelSaveStatus: "idle",
    globalModelTestResult: undefined,
    globalModelTestStatus: "idle",
    indexingVault: false,
    lastIndexRun: null,
    loadingSettingsStatus: false,
    loadSettingsStatus: vi.fn().mockResolvedValue(null),
    loadVaultStatus: vi.fn().mockResolvedValue(null),
    negotiationSettingsDraft: {
      use_negotiation: true,
      max_rounds: 5,
    },
    negotiationSettingsSaveStatus: "idle",
    rebuildIndex: vi.fn(),
    resetSettingsState: vi.fn(),
    saveAgentModel: vi.fn(),
    saveAutomationSettings: vi.fn(),
    saveGlobalModel: vi.fn(),
    saveNegotiationSettings: vi.fn(),
    saveTtsSettings: vi.fn(),
    savingAgentModelIds: new Set(),
    selectVaultDirectory: vi.fn(),
    setLastIndexRun: vi.fn(),
    setVaultPath: vi.fn(),
    settingsStatus: null,
    testAgentModelConnection: vi.fn(),
    testGlobalModelConnection: vi.fn(),
    testingAgentModelIds: new Set(),
    ttsSettingsDraft: {
      enabled: false,
      auto_play_assistant_reply: false,
      auto_play_reminders: false,
      provider: "system",
      base_url: null,
      model: null,
      voice: null,
      speed: 1,
      volume: 1,
      response_format: "mp3",
      requires_api_key: false,
      api_style: "generic",
      auth_header_name: null,
      request_template: null,
      audio_json_path: null,
      audio_encoding: "base64",
      mime_type: null,
      cache_enabled: false,
      night_quiet_mode: true,
    },
    ttsSettingsSaveStatus: "idle",
    updateAgentModelDraft: vi.fn(),
    updateAutomationSettingsDraft: vi.fn(),
    updateGlobalModelDraft: vi.fn(),
    updateNegotiationSettingsDraft: vi.fn(),
    updateTtsSettingsDraft: vi.fn(),
    vaultId: null,
    vaultPath: "",
    vaultStatus: null,
  }),
}));

vi.mock("./features/tasks/useTasks", () => ({
  useTasks: () => ({
    actOnTask: vi.fn(),
    addTaskFromChat: vi.fn(),
    clearTasks: vi.fn(),
    createTask: vi.fn(),
    lastReminderNotification: null,
    loadingTasks: false,
    loadTasks: vi.fn().mockResolvedValue(null),
    taskActionIds: new Set(),
    taskDraft: {
      title: "",
      description: "",
      due_at: "",
      remind_at: "",
      timezone: "Asia/Shanghai",
    },
    tasks: [],
    updateTaskDraft: vi.fn(),
  }),
}));

vi.mock("./features/memory/useMemory", () => ({
  useMemory: () => ({
    actOnProposal: vi.fn(),
    createProposal: vi.fn(),
    lastSearchQuery: "",
    loadingProposals: false,
    loadPendingProposals: vi.fn().mockResolvedValue(null),
    proposalActionIds: new Set(),
    proposalDraft: {
      type: "fact",
      content: "",
      target_path: "Inbox/Pending Memories.md",
    },
    proposals: [],
    resetMemoryState: vi.fn(),
    runMemorySearch: vi.fn(),
    searchQuery: "",
    searchResults: [],
    searchStatus: "idle",
    setSearchQuery: vi.fn(),
    updateProposalDraft: vi.fn(),
    upsertProposalFromPayload: vi.fn(),
  }),
}));

vi.mock("./features/wiki/useWiki", () => ({
  useWiki: () => ({
    approvedTargetsInput: "",
    applyChatWikiProposal: vi.fn(),
    applyIngest: vi.fn(),
    applyResult: null,
    archiveHistory: [],
    archiveHistoryError: "",
    archiveHistoryLoading: false,
    archiveHistoryStatus: "idle",
    archiveHistorySummary: "暂无归档",
    archiveLatestQuery: vi.fn(),
    companionContextReportError: "",
    companionContextReportStatus: "idle",
    companionContextReports: [],
    confirmChatWikiProposal: vi.fn(),
    coreError: "",
    coreStatus: "idle",
    diagnosticsQueue: null,
    draft: { title: "", content: "", source_type: "manual", source_uri: "", max_pages: 15, target_path: "", section: "", tags: [], links: [], write_report: true, allow_mixed_sources: false },
    indexStatus: null,
    lastWikiArchiveId: null,
    latestArchiveMessage: "",
    latestKnowledgeCitationCount: 0,
    lintIssueCount: 0,
    lintResult: null,
    linkInput: "",
    loadArchiveHistory: vi.fn(),
    loadCoreStatus: vi.fn(),
    loadDiagnosticsQueue: vi.fn(),
    logStatus: null,
    onDraftChange: vi.fn(),
    openArchive: vi.fn(),
    openedArchive: null,
    openingArchiveId: null,
    preview: null,
    previewIngest: vi.fn(),
    rejectChatWikiProposal: vi.fn(),
    resetWikiState: vi.fn(),
    reviewForceRefresh: false,
    reviewIngest: vi.fn(),
    reviewResult: null,
    runLint: vi.fn(),
    schemaStatus: null,
    setApprovedTargetsInput: vi.fn(),
    setLinkInput: vi.fn(),
    setReviewForceRefresh: vi.fn(),
    setTagInput: vi.fn(),
    synthesize: vi.fn(),
    tagInput: "",
    toggleChatWikiProposalTarget: vi.fn(),
    upsertChatWikiProposal: vi.fn(),
    useReviewRecommendedTargets: vi.fn(),
    workflowAction: null,
  }),
}));

vi.mock("./features/chat/usePetChatBubble", () => ({
  usePetChatBubble: () => {
    const assistantReplyRef = { current: "" };
    const assistantHiddenReplyTextsRef = { current: [] };
    return {
      assistantReplyRef,
      assistantHiddenReplyTextsRef,
      bubble: { visible: false, title: "", message: "", tone: "thinking", phase: "idle" },
      input: "",
      inputRef: createRef<HTMLInputElement>(),
      inputVisible: false,
      replyCompleteRef: { current: false },
      replyStartedRef: { current: false },
      streamFailedRef: { current: false },
      streamOpenedRef: { current: false },
      streamReceivedEventRef: { current: false },
      appendAssistantReplyText: vi.fn((text: string) => {
        assistantReplyRef.current += text;
        return text;
      }),
      clearStreamWatchdogTimer: vi.fn(),
      completeStreamWithoutReply: vi.fn(),
      failStream: vi.fn(),
      finishStream: vi.fn(),
      markStreamEventReceived: vi.fn(),
      resetStreamState: vi.fn(),
      scheduleHide: vi.fn(),
      scheduleStreamWatchdog: vi.fn(),
      setAssistantReplyText: vi.fn((text: string) => {
        assistantReplyRef.current = text;
        return text;
      }),
      setInput: vi.fn(),
      setInputVisible: vi.fn(),
      setReplyPagesFromText: vi.fn(),
      showBubble: vi.fn(),
      showContinuityPresenceBubble: vi.fn(),
      showInput: mockPetShowInput,
      showReaction: vi.fn(),
      showReply: vi.fn(),
      startReplyPaging: vi.fn(),
      advancePageManually: vi.fn(),
      pausePaging: vi.fn(),
      resumePaging: vi.fn(),
      latestContinuitySignalForMessage: vi.fn().mockReturnValue(null),
      latestContinuitySignalRef: { current: null },
    };
  },
}));

describe("App", () => {
  beforeEach(() => {
    window.location.hash = "";
    delete window.agentDesktop;
    sessionStorage.clear();
    mockTtsQueueStatus.current = "idle";
    mockTtsQueueError.current = null;
    mockTtsPlaybackQueueOptions.current = null;
    spritePetStageRenderProps.length = 0;
    vi.clearAllMocks();
    api.getDailyChatHistory.mockResolvedValue({
      date: "2026-07-09",
      timezone: "Asia/Shanghai",
      conversation_id: null,
      messages: [],
      has_more: false,
    });
  });

  it("renders the homeboard route when desktop bridge is unavailable", async () => {
    render(<App />);

    expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();
    expect(screen.getByLabelText("今日随行")).toBeInTheDocument();
    expect(screen.getByLabelText("Agent Pet 首页舞台")).toBeInTheDocument();
    expect(screen.getByLabelText("记忆回顾")).toBeInTheDocument();
    expect(document.querySelector(".control-stage-background")?.getAttribute("src")).toMatch(
      /^\/images\/home\.png\?v=\d+$/,
    );
    expect(document.querySelector(".halfbody-pet-portrait-base")?.getAttribute("src")).toMatch(
      /^\/sprite-pet\/halfbody\/base\.png\?v=\d+$/,
    );
    expect(document.querySelector(".bottom-nav-center-avatar img")?.getAttribute("src")).toMatch(
      /^\/images\/character\.png\?v=\d+$/,
    );
    expect(screen.queryByLabelText("陪伴入口")).not.toBeInTheDocument();
  });

  it("loads enough agent actions for the memory review to include older dates", async () => {
    render(<App />);

    await waitFor(() => expect(api.listAgentActions).toHaveBeenCalled());
    expect(api.listAgentActions.mock.calls[0][0]).toBe(200);
    expect(api.listAgentActions.mock.calls[0][1]).toBeNull();
    expect(api.listAgentActions.mock.calls[0][2]).toBeInstanceOf(AbortSignal);
  });

  it("shows the complete loaded memory list from the view-all memory drawer", async () => {
    api.listAgentActions.mockResolvedValueOnce({
      actions: Array.from({ length: 9 }, (_, index) => agentActionForTest(index + 1)),
    });

    render(<App />);

    await waitFor(() => expect(api.listAgentActions).toHaveBeenCalled());
    expect(await screen.findByText("测试自动整理 1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查看全部记忆" }));

    const activityLog = document.querySelector("#agent-activity-log");
    expect(activityLog).toBeTruthy();
    expect(within(activityLog as HTMLElement).getByText("测试自动整理 9")).toBeInTheDocument();
  });

  it("returns the homeboard date selector directly to today", async () => {
    render(<App />);

    expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();
    const previousDay = screen.getByRole("button", { name: "查看前一天" });
    const today = screen.getByRole("button", { name: "回到今天" });

    expect(today).toBeDisabled();

    fireEvent.click(previousDay);
    fireEvent.click(previousDay);
    expect(today).not.toBeDisabled();

    fireEvent.click(today);
    expect(today).toBeDisabled();
  });

  it("keeps the control homeboard companion-first while preserving support tools", async () => {
    window.location.hash = "#control";

    render(<App />);

    expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();
    expect(screen.getByLabelText("今日随行")).toBeInTheDocument();
    expect(screen.getByLabelText("Agent Pet 首页舞台")).toBeInTheDocument();
    expect(screen.getByLabelText("记忆回顾")).toBeInTheDocument();
    expect(screen.queryByLabelText("mock visible continuity panel")).not.toBeInTheDocument();
    expect(screen.getByText("今日目标")).toBeInTheDocument();
    expect(document.querySelector(".halfbody-pet-portrait")).toBeInTheDocument();
    expect(screen.queryByLabelText("mock task panel")).not.toBeInTheDocument();
    const drawers = Array.from(document.querySelectorAll(".control-detail-drawer"));
    const supportNavigation = drawers.find((drawer) => drawer.textContent?.includes("计划与连续性"));
    expect(supportNavigation).toBeInTheDocument();
    expect(supportNavigation).not.toHaveAttribute("open");

    fireEvent.click(supportNavigation!.querySelector("summary")!);
    expect(await screen.findByLabelText("mock task panel")).toBeInTheDocument();
    expect(await screen.findByLabelText("mock visible continuity panel")).toBeInTheDocument();

    const secondaryNavigation = drawers.find((drawer) => drawer.textContent?.includes("连接与数据"));
    expect(secondaryNavigation).toBeInTheDocument();
    expect(secondaryNavigation).not.toHaveAttribute("open");
    expect(screen.queryByLabelText("mock connection panel")).not.toBeInTheDocument();

    fireEvent.click(secondaryNavigation!.querySelector("summary")!);
    expect(await screen.findByLabelText("mock connection panel")).toBeInTheDocument();
  });

  it("drives the home halfbody mouth from TTS playback lifecycle", async () => {
    window.location.hash = "#control";
    render(<App />);

    const visemeLayer = () => document.querySelector(".halfbody-pet-portrait-viseme") as HTMLImageElement | null;
    await waitFor(() => expect(visemeLayer()).toBeInTheDocument());
    expect(visemeLayer()?.getAttribute("src")).toContain("closed.png");

    const item = {
      id: "tts:assistant-1:0",
      messageId: "assistant-1",
      pageIndex: 0,
      pageCount: 1,
      text: "a哦。",
      synthesis: {
        requestId: "tts:assistant-1:0",
        text: "a哦。",
        provider: "mock",
        voice: null,
        speed: 1,
        volume: 1,
        cacheEnabled: true,
      },
    };

    act(() => {
      mockTtsPlaybackQueueOptions.current?.onPlaybackStart?.(item);
    });

    expect(mockTtsWaitingCueStop).toHaveBeenCalledWith("assistant_tts_started");
    await waitFor(() => expect(visemeLayer()?.getAttribute("src")).toContain("AI.png"));

    act(() => {
      mockTtsPlaybackQueueOptions.current?.onPlaybackEnd?.(item, "played");
    });

    await waitFor(() => expect(visemeLayer()?.getAttribute("src")).toContain("closed.png"));
  });

  it("presents open-thread continuity as a clear next-time chat decision", async () => {
    window.location.hash = "#control";
    api.getContinuityState.mockResolvedValueOnce({
      items: [
        {
          state_key: "unresolved_threads",
          value: "继续聊水果偏好",
          confidence: 0.8,
          updated_at: "2026-05-24T00:00:00.000Z",
        },
      ],
      unresolved_threads: "继续聊水果偏好",
    });
    api.listContinuityProposals.mockResolvedValueOnce({
      proposals: [
        {
          proposal_id: "continuity-1",
          kind: "open_thread",
          summary: "之前聊到苹果但还没确认喜好。",
          evidence: "用户提到喜欢水果，后续没有收尾。",
          confidence: 0.72,
          source_conversation_id: "conversation-1",
          source_message_id: "message-1",
          agent_run_id: "run-1",
          status: "pending",
          rejected_reason: null,
          created_at: "2026-05-24T00:00:00.000Z",
          updated_at: "2026-05-24T00:00:00.000Z",
        },
      ],
    });

    render(<App />);

    expect((await screen.findAllByText("下次接着聊")).length).toBeGreaterThan(0);
    expect(screen.getByText("要让我下次记得继续这个话题吗？之前聊到苹果但还没确认喜好。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /记住下次聊/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /不用记/ })).toBeInTheDocument();
    expect(screen.queryByText(/连续性确认/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /记住下次聊/ }));

    await waitFor(() => expect(api.confirmContinuityProposal).toHaveBeenCalledWith("continuity-1"));
    expect(await screen.findByText(/已记住，下次可以自然接着聊/)).toBeInTheDocument();
  });

  it("starts the first-use onboarding from advanced management and persists completion", async () => {
    const uiState = new Map<string, string>();
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      getUiState: vi.fn((key: string) => uiState.get(key) ?? null),
      setUiState: vi.fn((key: string, value: string | null) => {
        if (value === null) {
          uiState.delete(key);
        } else {
          uiState.set(key, value);
        }
      }),
    };
    window.location.hash = "#stage";

    render(<App />);

    fireEvent.click(screen.getByText("连接与数据"));
    const onboarding = await screen.findByLabelText("首次使用引导");
    expect(onboarding).toBeInTheDocument();
    const submitButton = screen.getByRole("button", { name: "开始第一次聊天" });
    expect(submitButton).toBeDisabled();
    expect(
      within(onboarding)
        .getAllByRole("textbox")
        .filter((field) => field.hasAttribute("required")),
    ).toHaveLength(1);

    fireEvent.change(screen.getByLabelText("今天想让我从哪里陪你继续？"), {
      target: { value: "我今天有点累，想把昨天没说完的事接上" },
    });

    expect(submitButton).not.toBeDisabled();
    expect(screen.getByText("可选补充").closest("details")).not.toHaveAttribute("open");
    expect(
      within(onboarding)
        .getAllByRole("textbox")
        .filter((field) => field.hasAttribute("required")),
    ).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "开始第一次聊天" }));

    await waitFor(() => expect(api.startChat).toHaveBeenCalledTimes(1));
    expect(mockTtsWaitingCueStart).toHaveBeenCalledTimes(1);
    const request = api.startChat.mock.calls[0][0];
    expect(request.message).toContain("今天想让我从哪里陪你继续：我今天有点累，想把昨天没说完的事接上");
    expect(request.message).toContain("只沉淀高价值、非敏感、可复用的长期记忆");
    expect(request.message).toContain("低置信、敏感或关系身份类内容必须等待用户确认或跳过");
    expect(request.message).toContain("希望我怎么称呼你：未填写");
    expect(request.message).toContain("记忆保存偏好：未填写");
    expect(request.message).not.toContain("Markdown");
    await waitFor(() =>
      expect(window.agentDesktop?.setUiState).toHaveBeenCalledWith(
        "agent-pet.first-use-onboarding",
        "completed:v1",
      ),
    );
    expect(screen.queryByLabelText("首次使用引导")).not.toBeInTheDocument();
  });

  it("keeps first-use save preference optional inside advanced management", async () => {
    const uiState = new Map<string, string>();
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      getUiState: vi.fn((key: string) => uiState.get(key) ?? null),
      setUiState: vi.fn((key: string, value: string | null) => {
        if (value === null) {
          uiState.delete(key);
        } else {
          uiState.set(key, value);
        }
      }),
    };
    window.location.hash = "#stage";

    render(<App />);

    fireEvent.click(screen.getByText("连接与数据"));
    expect(await screen.findByLabelText("首次使用引导")).toBeInTheDocument();
    expect(screen.queryByText("保存位置")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("保存位置")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("今天想让我从哪里陪你继续？"), {
      target: { value: "先陪我接住今天这件事" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始第一次聊天" }));

    await waitFor(() => expect(api.startChat).toHaveBeenCalledTimes(1));
    const request = api.startChat.mock.calls[0][0];
    expect(request.message).toContain("今天想让我从哪里陪你继续：先陪我接住今天这件事");
    expect(request.message).toContain("记忆保存偏好：未填写");
    expect(request.message).not.toContain("保存位置");
  });

  it("does not show first-use onboarding inside the chat route", async () => {
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      getUiState: vi.fn(() => null),
      setUiState: vi.fn(),
    };
    window.location.hash = "#chat";

    render(<App />);

    expect(await screen.findByRole("heading", { name: "聊天" })).toBeInTheDocument();
    expect(screen.queryByLabelText("首次使用引导")).not.toBeInTheDocument();
    expect(screen.queryByText("今天想让我从哪里陪你继续？")).not.toBeInTheDocument();
  });

  it("restores today's chat history and continues the latest daily conversation", async () => {
    api.getDailyChatHistory.mockResolvedValueOnce({
      date: "2026-07-09",
      timezone: "Asia/Shanghai",
      conversation_id: "daily-conversation",
      messages: [
        {
          id: "daily-user-1",
          conversation_id: "daily-conversation",
          role: "user",
          content: "TODAY_USER_MESSAGE",
          status: "completed",
          created_at: "2026-07-09T01:00:00Z",
          updated_at: "2026-07-09T01:00:00Z",
          agent_run_id: null,
        },
        {
          id: "daily-assistant-1",
          conversation_id: "daily-conversation",
          role: "assistant",
          content: "TODAY_ASSISTANT_REPLY",
          status: "completed",
          created_at: "2026-07-09T01:00:02Z",
          updated_at: "2026-07-09T01:00:02Z",
          agent_run_id: "daily-run-1",
        },
      ],
      has_more: false,
    });
    window.location.hash = "#chat";

    render(<App />);

    expect(await screen.findByText("TODAY_USER_MESSAGE")).toBeInTheDocument();
    expect(screen.getByText("TODAY_ASSISTANT_REPLY")).toBeInTheDocument();

    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "CONTINUE_TODAY" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => expect(api.startChat).toHaveBeenCalledTimes(1));
    expect(api.startChat.mock.calls[0][0]).toMatchObject({
      conversation_id: "daily-conversation",
      message: "CONTINUE_TODAY",
    });
  });

  it("does not show first-use onboarding after completion is stored in Electron UI state", async () => {
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      getUiState: vi.fn((key: string) =>
        key === "agent-pet.first-use-onboarding" ? "completed:v1" : null,
      ),
      setUiState: vi.fn(),
    };

    render(<App />);

    await waitFor(() => expect(window.agentDesktop?.getUiState).toHaveBeenCalledWith("agent-pet.first-use-onboarding"));
    expect(screen.queryByLabelText("首次使用引导")).not.toBeInTheDocument();
  });

  it("renders the pet shell from hash routing", async () => {
    window.location.hash = "#pet";

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText("Agent Pet 桌宠")).toBeInTheDocument());
    expect(screen.getByLabelText("mock pet stage")).toBeInTheDocument();
    expect(screen.getByLabelText("mock pet chat overlay")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Agent Pet" })).not.toBeInTheDocument();
  });

  it("renders the homeboard from the stage home route", async () => {
    window.location.hash = "#stage";

    render(<App />);

    expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();
    expect(screen.getByLabelText("今日随行")).toBeInTheDocument();
    expect(screen.getByLabelText("Agent Pet 首页舞台")).toBeInTheDocument();
    expect(screen.getByLabelText("记忆回顾")).toBeInTheDocument();
  });

  it("keeps the bottom navigation active state synchronized on every primary route", async () => {
    for (const tab of primaryNavigationTabs) {
      window.location.hash = `#${navigationHashForTab(tab)}`;
      const { container, unmount } = render(<App />);

      await waitFor(() => {
        const activeButtons = Array.from(container.querySelectorAll<HTMLButtonElement>(".bottom-nav-button.active"))
          .filter((button) => !button.closest("[hidden]"));

        expect(activeButtons).toHaveLength(1);
        expect(activeButtons[0]).toHaveTextContent(tab);
        expect(activeButtons[0]).toHaveAttribute("aria-current", "page");
      });

      const activeNav = Array.from(container.querySelectorAll<HTMLElement>(".bottom-nav"))
        .find((nav) => !nav.closest("[hidden]"));
      expect(activeNav).toBeTruthy();

      fireEvent.click(within(activeNav!).getByRole("button", { name: primaryNavigationTabs[0] }));
      expect(window.location.hash).toBe(`#${navigationHashForTab(primaryNavigationTabs[0])}`);

      unmount();
    }
  });

  it("renders core product routes as dedicated workspaces instead of chat-only surfaces", async () => {
    const routes = [
      { hash: "#agent", query: () => screen.findByLabelText("提醒和待办区") },
      { hash: "#memory", query: () => screen.findByLabelText("记忆工作台入口") },
      { hash: "#world", query: () => screen.findByRole("heading", { name: "资料库" }) },
    ];

    for (const route of routes) {
      window.location.hash = route.hash;
      const { unmount } = render(<App />);

      expect(await route.query()).toBeInTheDocument();
      expect(screen.queryByLabelText("mock chat message list")).not.toBeInTheDocument();

      unmount();
    }
  });

  it("toggles pet shortcut buttons from the sprite pet right-click menu gesture", async () => {
    window.location.hash = "#pet";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      openAgent: vi.fn().mockResolvedValue(undefined),
      openFeatureWindow: vi.fn().mockResolvedValue(undefined),
      openStage: vi.fn().mockResolvedValue(undefined),
      hidePetWindow: vi.fn().mockResolvedValue(undefined),
      quitApp: vi.fn().mockResolvedValue(undefined),
      getUiState: vi.fn().mockReturnValue(null),
      setUiState: vi.fn(),
      setPetShortcutBarVisible: vi.fn().mockResolvedValue({ enabled: false, reason: "test", changed: false }),
      onPetDragCancelled: vi.fn().mockReturnValue(() => undefined),
    };

    render(<App />);

    const petStage = await screen.findByLabelText("mock pet stage");
    const shortcutBar = screen.getByLabelText("桌宠快捷操作");
    expect(shortcutBar).toHaveAttribute("aria-hidden", "true");
    expect(shortcutBar).toHaveAttribute("data-shortcut-motion", "idle");
    expect(shortcutBar).not.toHaveClass("is-visible");
    expect(screen.queryByLabelText("桌宠入口提示")).not.toBeInTheDocument();
    expect(screen.getByLabelText("继续聊")).toHaveAttribute("tabindex", "-1");

    const finishShortcutAnimation = (animationName: string) => {
      const event = new Event("animationend", { bubbles: true });
      Object.defineProperty(event, "animationName", { value: animationName });
      fireEvent(screen.getByLabelText("退出 Agent Pet"), event);
    };

    fireEvent.contextMenu(petStage);

    expect(shortcutBar).toHaveAttribute("aria-hidden", "false");
    expect(shortcutBar).toHaveAttribute("data-shortcut-motion", "opening");
    expect(shortcutBar).toHaveClass("is-visible");
    expect(screen.queryByLabelText("桌宠入口提示")).not.toBeInTheDocument();
    expect(screen.getByLabelText("继续聊")).toHaveAttribute("tabindex", "0");
    expect(window.agentDesktop.setPetShortcutBarVisible).toHaveBeenLastCalledWith(true);
    expect(window.agentDesktop.setUiState).toHaveBeenCalledWith("agent-pet.pet-entry-hint", "completed:v1");

    finishShortcutAnimation("pet-shortcut-roll-out");
    expect(shortcutBar).toHaveAttribute("data-shortcut-motion", "idle");

    fireEvent.contextMenu(petStage);

    expect(shortcutBar).toHaveAttribute("aria-hidden", "true");
    expect(shortcutBar).toHaveAttribute("data-shortcut-motion", "closing");
    expect(shortcutBar).toHaveClass("is-visible");
    expect(screen.queryByLabelText("桌宠入口提示")).not.toBeInTheDocument();
    expect(screen.getByLabelText("继续聊")).toHaveAttribute("tabindex", "-1");
    expect(window.agentDesktop.setPetShortcutBarVisible).toHaveBeenLastCalledWith(true);

    finishShortcutAnimation("pet-shortcut-roll-in");
    expect(shortcutBar).toHaveAttribute("data-shortcut-motion", "idle");
    expect(shortcutBar).toHaveAttribute("aria-hidden", "true");
    expect(shortcutBar).not.toHaveClass("is-visible");
    expect(window.agentDesktop.setPetShortcutBarVisible).toHaveBeenLastCalledWith(false);

    fireEvent.contextMenu(petStage);
    fireEvent.click(screen.getByLabelText("继续聊"));
    fireEvent.contextMenu(petStage);
    fireEvent.click(screen.getByLabelText("建提醒"));
    fireEvent.contextMenu(petStage);
    fireEvent.click(screen.getByLabelText("打开记忆"));
    fireEvent.contextMenu(petStage);
    fireEvent.click(screen.getByLabelText("打开设置"));
    fireEvent.contextMenu(petStage);
    fireEvent.click(screen.getByLabelText("退出 Agent Pet"));

    expect(window.agentDesktop.openStage).toHaveBeenNthCalledWith(1, "memory");
    expect(window.agentDesktop.openStage).toHaveBeenNthCalledWith(2, "settings");
    expect(window.agentDesktop.openAgent).not.toHaveBeenCalled();
    expect(window.agentDesktop.openFeatureWindow).not.toHaveBeenCalled();
    expect(window.agentDesktop.hidePetWindow).not.toHaveBeenCalled();
    expect(window.agentDesktop.quitApp).toHaveBeenCalledTimes(1);

    expect(mockPetShowInput).toHaveBeenCalledTimes(2);
    expect(shortcutBar).toHaveAttribute("aria-hidden", "true");
    expect(shortcutBar).not.toHaveClass("is-visible");
  });

  it("keeps the fixed pet shortcut menu order while TTS is active", async () => {
    mockTtsQueueStatus.current = "playing";
    window.location.hash = "#pet";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      openStage: vi.fn().mockResolvedValue(undefined),
      quitApp: vi.fn().mockResolvedValue(undefined),
      getUiState: vi.fn().mockReturnValue("completed:v1"),
      setUiState: vi.fn(),
      setPetShortcutBarVisible: vi.fn().mockResolvedValue({ enabled: false, reason: "test", changed: false }),
      onPetDragCancelled: vi.fn().mockReturnValue(() => undefined),
    };

    render(<App />);

    fireEvent.contextMenu(await screen.findByLabelText("mock pet stage"));
    expect(screen.queryByLabelText("暂停朗读")).not.toBeInTheDocument();
    expect(screen.getByLabelText("退出 Agent Pet")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("打开设置"));

    expect(mockTtsStop).not.toHaveBeenCalledWith("pet_shortcut_stop_tts");
    expect(screen.getByLabelText("桌宠快捷操作")).toHaveAttribute("aria-hidden", "true");
    expect(window.agentDesktop.openStage).toHaveBeenCalledWith("settings");
    expect(window.agentDesktop.quitApp).not.toHaveBeenCalled();
  });

  it("opens the stage window instead of the inline input when double-clicking the pet", async () => {
    window.location.hash = "#pet";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      openStage: vi.fn().mockResolvedValue(undefined),
      onPetDragCancelled: vi.fn().mockReturnValue(() => undefined),
    };

    render(<App />);

    const petStage = await screen.findByLabelText("mock pet stage");
    fireEvent.doubleClick(petStage);

    expect(window.agentDesktop.openStage).toHaveBeenCalledTimes(1);
    expect(mockPetShowInput).not.toHaveBeenCalled();
  });

  it("marks the pet shell while the desktop pet is being dragged", async () => {
    window.location.hash = "#pet";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      beginPetWindowDrag: vi.fn(),
      activatePetWindowDrag: vi.fn(),
      endPetWindowDrag: vi.fn(),
      onPetDragCancelled: vi.fn().mockReturnValue(() => undefined),
    };

    render(<App />);

    const petStage = await screen.findByLabelText("mock pet stage");
    const petShell = petStage.closest(".pet-shell");
    expect(petShell).toBeTruthy();
    const pointerTarget = {
      setPointerCapture: vi.fn(),
      releasePointerCapture: vi.fn(),
      hasPointerCapture: vi.fn(() => true),
    } as unknown as HTMLElement;
    const petStageProps = spritePetStageRenderProps[spritePetStageRenderProps.length - 1];
    const petInteractions = petStageProps?.petInteractions;
    expect(petInteractions).toBeTruthy();

    act(() => {
      petInteractions?.onPointerDown?.({
        button: 0,
        pointerId: 7,
        screenX: 100,
        screenY: 100,
        currentTarget: pointerTarget,
        preventDefault: vi.fn(),
      } as unknown as PointerEvent<HTMLElement>);
    });
    expect(window.agentDesktop.beginPetWindowDrag).toHaveBeenCalledTimes(1);
    expect(window.agentDesktop.activatePetWindowDrag).not.toHaveBeenCalled();
    expect(petShell).toHaveClass("pet-dragging");
    expect(petShell).not.toHaveClass("pet-drag-snapshot-ready");
    expect(document.querySelector(".pet-drag-frame-cache")).not.toBeInTheDocument();
    expect(spritePetStageRenderProps[spritePetStageRenderProps.length - 1]).toMatchObject({
      dragging: true,
      dragDirection: "none",
    });

    act(() => {
      petInteractions?.onPointerMove?.({
        pointerId: 7,
        screenX: 109,
        screenY: 100,
      } as unknown as PointerEvent<HTMLElement>);
    });

    expect(window.agentDesktop.activatePetWindowDrag).toHaveBeenCalledTimes(1);
    expect(petShell).toHaveClass("pet-dragging");
    expect(petShell).not.toHaveClass("pet-drag-snapshot-ready");
    expect(document.querySelector(".pet-drag-frame-cache")).not.toBeInTheDocument();
    expect(spritePetStageRenderProps[spritePetStageRenderProps.length - 1]).toMatchObject({
      dragging: true,
      dragDirection: "right",
    });

    act(() => {
      petInteractions?.onPointerUp?.({
        pointerId: 7,
        currentTarget: pointerTarget,
      } as unknown as PointerEvent<HTMLElement>);
    });

    expect(window.agentDesktop.endPetWindowDrag).toHaveBeenCalled();
    expect(petShell).not.toHaveClass("pet-dragging");
    expect(document.querySelector(".pet-drag-frame-cache")).not.toBeInTheDocument();
  });

  it("uses the desktop bridge window mode when available", async () => {
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      getWindowMode: vi.fn().mockResolvedValue("pet"),
      onPetDragCancelled: vi.fn().mockReturnValue(() => undefined),
    };

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText("Agent Pet 桌宠")).toBeInTheDocument());
    expect(window.agentDesktop.getWindowMode).toHaveBeenCalledTimes(1);
  });

  it("uses the static home character on home routes and keeps the pet sprite isolated", async () => {
    window.location.hash = "#control";
    render(<App />);
    expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();
    expect(document.querySelector(".control-stage-background")?.getAttribute("src")).toMatch(
      /^\/images\/home\.png\?v=\d+$/,
    );
    expect(document.querySelector(".halfbody-pet-portrait-base")?.getAttribute("src")).toMatch(
      /^\/sprite-pet\/halfbody\/base\.png\?v=\d+$/,
    );

    spritePetStageRenderProps.length = 0;
    window.location.hash = "#pet";
    render(<App />);
    expect(await screen.findByLabelText("mock pet stage")).toBeInTheDocument();
    const petRef = spritePetStageRenderProps[spritePetStageRenderProps.length - 1]?.canvasRef;

    spritePetStageRenderProps.length = 0;
    window.location.hash = "#stage";
    render(<App />);
    expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();
    expect(document.querySelector(".control-stage-background")?.getAttribute("src")).toMatch(
      /^\/images\/home\.png\?v=\d+$/,
    );
    expect(document.querySelector(".halfbody-pet-portrait-base")?.getAttribute("src")).toMatch(
      /^\/sprite-pet\/halfbody\/base\.png\?v=\d+$/,
    );

    expect(petRef).toBeTruthy();
  });

  it("keeps active TTS playing when the renderer document is hidden", async () => {
    mockTtsQueueStatus.current = "playing";
    const visibilitySpy = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    window.location.hash = "#control";

    try {
      render(<App />);
      expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();

      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });

      expect(mockTtsStop).not.toHaveBeenCalledWith("window_hidden");
    } finally {
      visibilitySpy.mockRestore();
    }
  });

  it("stops active TTS when the renderer page is unloaded", async () => {
    mockTtsQueueStatus.current = "playing";
    window.location.hash = "#control";

    render(<App />);
    expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pagehide"));
    });

    expect(mockTtsStop).toHaveBeenCalledWith("window_hidden");
  });

  it("registers Xiaomi MiMo as a backend TTS provider", async () => {
    window.location.hash = "#control";
    render(<App />);

    expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();
    expect(mockCreateBackendTtsProvider).toHaveBeenCalledWith(expect.objectContaining({ api }));
    expect(mockCreateBackendTtsProvider).toHaveBeenCalledWith(expect.objectContaining({ api, providerId: "xiaomi-mimo" }));
  });

  it("surfaces TTS playback errors instead of failing silently", async () => {
    mockTtsQueueError.current = {
      code: "playback_blocked",
      message: "TTS 音频播放被阻止。",
      provider: "xiaomi-mimo",
      itemId: "tts:assistant-1:0",
      recoverable: true,
    };
    window.location.hash = "#control";

    render(<App />);

    expect(await screen.findByText("语音播放失败：TTS 音频播放被阻止。")).toBeInTheDocument();
  });

  it("explains Xiaomi MiMo TTS authentication failures with a settings fix", async () => {
    mockTtsQueueError.current = {
      code: "authentication_failed",
      message: "TTS 服务鉴权失败，请检查 API Key。",
      provider: "xiaomi-mimo",
      itemId: "tts:assistant-1:0",
      recoverable: true,
    };
    window.location.hash = "#control";

    render(<App />);

    expect(await screen.findByText(/小米 MiMo API Key 无效/)).toBeInTheDocument();
    expect(screen.getByText(/重新保存语音服务密钥/)).toBeInTheDocument();
  });

  it("stops active TTS when the stage window route changes", async () => {
    mockTtsQueueStatus.current = "playing";
    window.location.hash = "#stage";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      getWindowMode: vi.fn().mockResolvedValue("stage"),
      onStageRouteRequested: vi.fn(() => () => undefined),
    };

    render(<App />);
    expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();

    act(() => {
      window.location.hash = "#chat";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    await waitFor(() => expect(mockTtsStop).toHaveBeenCalledWith("window_mode_changed"));
  });

  it("navigates stage-window routes away from and back to the homeboard", async () => {
    window.location.hash = "#stage";
    let requestStageRoute: ((mode: "stage" | "agent" | "chat" | "memory" | "world" | "settings") => void) | null = null;
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      getWindowMode: vi.fn().mockResolvedValue("stage"),
      onStageRouteRequested: vi.fn((callback) => {
        requestStageRoute = callback;
        return () => undefined;
      }),
    };

    render(<App />);

    expect(await screen.findByLabelText("Agent Pet 首页")).toBeInTheDocument();

    act(() => {
      window.location.hash = "#chat";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    await waitFor(() => expect(screen.getByLabelText("当前活动路由")).toBeInTheDocument());

    act(() => {
      requestStageRoute?.("settings");
    });

    await waitFor(() => expect(window.location.hash).toBe("#settings"));
    expect(screen.getByLabelText("当前活动路由")).toBeInTheDocument();

    act(() => {
      window.location.hash = "#stage";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    await waitFor(() => expect(screen.getByLabelText("Agent Pet 首页")).toBeInTheDocument());
  });
});
