import { createRef } from "react";
import type { MouseEvent, PointerEvent } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { DesktopSidecarStatus } from "./types";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "./services/live2dRuntime";

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
const mockCreateBackendTtsProvider = vi.hoisted(() =>
  vi.fn(({ providerId = "custom-http" }: { providerId?: string } = {}) => ({ id: providerId })),
);
const live2dStageRenderProps = vi.hoisted(() => [] as Array<{
  variant: "panel" | "pet" | "stage";
  canvasRef: unknown;
  active: boolean;
  petInteractions?: {
    onPointerDown?: (event: PointerEvent<HTMLElement>) => void;
    onPointerMove?: (event: PointerEvent<HTMLElement>) => void;
    onPointerUp?: (event: PointerEvent<HTMLElement>) => void;
  };
}>);

vi.mock("./components/Live2DStage", () => ({
  Live2DStage: ({
    active = true,
    canvasRef,
    variant = "panel",
    petInteractions,
  }: {
    canvasRef?: unknown;
    active?: boolean;
    variant?: "panel" | "pet" | "stage";
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
    live2dStageRenderProps.push({ variant, canvasRef, active, petInteractions });
    return (
      <section
        aria-label={variant === "pet" ? "mock pet stage" : variant === "stage" ? "mock stage stage" : "mock panel stage"}
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
  useTtsPlaybackQueue: () => ({
    state: {
      status: mockTtsQueueStatus.current,
      current: null,
      queue: [],
      error: mockTtsQueueError.current,
      volume: 1,
      updatedAt: null,
    },
    enqueue: vi.fn(),
    prefetch: vi.fn(),
    prefetchMany: vi.fn(),
    play: vi.fn(),
    stop: mockTtsStop,
    cancelMessage: vi.fn(),
    clear: vi.fn(),
    setVolume: vi.fn(),
  }),
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
  ChatMessageList: () => <section aria-label="mock chat message list" />,
}));

vi.mock("./features/live2d/Live2DModelPanel", () => ({
  Live2DModelPanel: () => <section aria-label="mock live2d model panel" />,
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

const live2dAsset: Live2DAssetInfo = {
  status: "preview",
  modelId: "agent_pet_companion",
  modelLabel: "Archivist Companion",
  modelDirectoryUrl: "/live2d/agent_pet_companion/",
  modelFileName: "agent_pet_companion.model3.json",
  manifestPath: "/live2d/agent_pet_companion/agent_pet_companion.model3.json",
  iconPath: "/live2d/agent_pet_companion/preview.svg",
  hasIcon: true,
  textureCount: 0,
  expressionCount: 18,
  motionCount: 28,
  actionCount: 28,
  previewOnly: true,
  designPath: "/live2d/agent_pet_companion/character-design.json",
  hasPhysics: false,
  hasDisplayInfo: false,
};

const live2dRuntime: Live2DRuntimeBoundary = {
  status: "preview-only",
  title: "角色预览",
  detail: "项目角色静态预览已启用；导出 Cubism model3 后会接管为真实 Live2D 渲染。",
  mountTargetId: "live2d-runtime-canvas",
  rendererName: "Cubism WebGL",
  canMountRenderer: false,
};

vi.mock("./features/live2d/useLive2D", () => ({
  useLive2D: () => ({
    asset: live2dAsset,
    canvasRef: createRef<HTMLCanvasElement>(),
    models: [],
    runtime: live2dRuntime,
    selectedModelId: "agent_pet_companion",
    selectModel: vi.fn(),
    stage: {
      state: "idle",
      label: "待命陪伴",
      mood: "安静待命",
      message: "我在这里。",
      hint: "双击聊天",
    },
    triggerTaskStage: vi.fn(),
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
    live2dStageRenderProps.length = 0;
    vi.clearAllMocks();
  });

  it("renders the Today route when desktop bridge is unavailable", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "今天想从哪里继续？" })).toBeInTheDocument();
    const companionEntry = within(screen.getByLabelText("陪伴入口"));
    expect(companionEntry.getByRole("button", { name: /陪我聊聊/ })).toHaveAttribute("data-stage-route", "chat");
    expect(companionEntry.getByRole("button", { name: /看看记忆/ })).toHaveAttribute("data-stage-route", "memory");
    expect(companionEntry.getByRole("button", { name: /设置边界/ })).toHaveAttribute("data-stage-route", "settings");
    expect(companionEntry.getByText("更多和高级").closest("details")).not.toHaveAttribute("open");
    expect(screen.queryByText("高级管理与诊断")).not.toBeInTheDocument();
  });

  it("keeps the control dashboard companion-first while preserving support tools", async () => {
    window.location.hash = "#control";

    render(<App />);

    expect(await screen.findByRole("heading", { name: "先和我说一句话" })).toBeInTheDocument();
    expect(screen.getByLabelText("桌宠陪伴区")).toBeInTheDocument();
    expect(screen.getByText("今天要跟进的事")).toBeInTheDocument();
    expect(screen.getByText("直接告诉我现在发生了什么")).toBeInTheDocument();
    expect(screen.getByLabelText("聊天和最近整理")).toBeInTheDocument();
    expect(screen.getByLabelText("最近自动整理活动")).toBeInTheDocument();
    expect(screen.queryByLabelText("mock visible continuity panel")).not.toBeInTheDocument();
    expect(screen.getByText("今天要跟进的事")).toBeInTheDocument();
    expect(screen.getByLabelText("mock panel stage")).toBeInTheDocument();
    expect(screen.queryByLabelText("mock task panel")).not.toBeInTheDocument();
    const supportNavigation = document.querySelector(".control-support-nav");
    expect(supportNavigation).toBeInTheDocument();
    expect(supportNavigation).not.toHaveAttribute("open");

    fireEvent.click(supportNavigation!.querySelector("summary")!);
    expect(await screen.findByLabelText("mock task panel")).toBeInTheDocument();
    expect(await screen.findByLabelText("mock visible continuity panel")).toBeInTheDocument();

    expect(screen.getByText("高级管理与诊断")).toBeInTheDocument();
    const secondaryNavigation = document.querySelector(".control-secondary-nav");
    expect(secondaryNavigation).toBeInTheDocument();
    expect(secondaryNavigation).not.toHaveAttribute("open");
    expect(screen.queryByLabelText("mock connection panel")).not.toBeInTheDocument();

    fireEvent.click(secondaryNavigation!.querySelector("summary")!);
    expect(await screen.findByLabelText("mock connection panel")).toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: /去确认/ })).toBeInTheDocument();
    expect(screen.getByText("下次可接着聊")).toBeInTheDocument();
    expect(screen.getByText("继续聊水果偏好")).toBeInTheDocument();
    expect(screen.queryByText(/连续性确认/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /记住下次聊/ }));

    await waitFor(() => expect(api.confirmContinuityProposal).toHaveBeenCalledWith("continuity-1"));
    expect(await screen.findByText(/已记住，下次可以自然接着聊/)).toBeInTheDocument();
  });

  it("starts the first-use onboarding as a normal chat and persists completion", async () => {
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
    window.location.hash = "#chat";

    render(<App />);

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

  it("keeps first-use save preference optional instead of requiring a storage path", async () => {
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
    window.location.hash = "#chat";

    render(<App />);

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

    await waitFor(() => expect(screen.getByLabelText("桌面记忆助手桌宠")).toBeInTheDocument());
    expect(screen.getByLabelText("mock pet stage")).toBeInTheDocument();
    expect(screen.getByLabelText("mock pet chat overlay")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "桌面记忆助手" })).not.toBeInTheDocument();
  });

  it("renders stage feature entries from the stage route", async () => {
    window.location.hash = "#stage";

    render(<App />);

    expect(await screen.findByLabelText("陪伴入口")).toBeInTheDocument();
    const companionEntry = within(screen.getByLabelText("陪伴入口"));
    expect(companionEntry.getByRole("button", { name: /陪我聊聊/ })).toHaveAttribute("data-stage-route", "chat");
    expect(companionEntry.getByRole("button", { name: /看看记忆/ })).toHaveAttribute("data-stage-route", "memory");
    expect(companionEntry.getByRole("button", { name: /设置边界/ })).toHaveAttribute("data-stage-route", "settings");
    fireEvent.click(companionEntry.getByText("更多和高级"));
    expect(companionEntry.getByRole("button", { name: /提醒和待办/ })).toHaveAttribute("data-stage-route", "agent");
    expect(companionEntry.getByRole("button", { name: /资料工具/ })).toHaveAttribute("data-stage-route", "world");
  });

  it("renders core product routes as dedicated workspaces instead of chat-only surfaces", async () => {
    const routes = [
      { hash: "#agent", query: () => screen.findByLabelText("提醒和待办区") },
      { hash: "#memory", query: () => screen.findByRole("heading", { name: "我的记忆" }) },
      { hash: "#world", query: () => screen.findByRole("heading", { name: "资料工具" }) },
    ];

    for (const route of routes) {
      window.location.hash = route.hash;
      const { unmount } = render(<App />);

      expect(await route.query()).toBeInTheDocument();
      expect(screen.queryByLabelText("mock chat message list")).not.toBeInTheDocument();

      unmount();
    }
  });

  it("toggles pet shortcut buttons from the Live2D right-click menu gesture", async () => {
    window.location.hash = "#pet";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      openAgent: vi.fn().mockResolvedValue(undefined),
      openFeatureWindow: vi.fn().mockResolvedValue(undefined),
      openStage: vi.fn().mockResolvedValue(undefined),
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
    expect(await screen.findByLabelText("桌宠入口提示")).toHaveTextContent("右键我快速行动");
    expect(screen.getByLabelText("继续聊")).toHaveAttribute("tabindex", "-1");

    const finishShortcutAnimation = (animationName: string) => {
      const event = new Event("animationend", { bubbles: true });
      Object.defineProperty(event, "animationName", { value: animationName });
      fireEvent(shortcutBar, event);
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
    expect(shortcutBar).not.toHaveClass("is-visible");
    expect(screen.queryByLabelText("桌宠入口提示")).not.toBeInTheDocument();
    expect(screen.getByLabelText("继续聊")).toHaveAttribute("tabindex", "-1");
    expect(window.agentDesktop.setPetShortcutBarVisible).toHaveBeenLastCalledWith(false);

    finishShortcutAnimation("pet-shortcut-roll-in");
    expect(shortcutBar).toHaveAttribute("data-shortcut-motion", "idle");

    fireEvent.contextMenu(petStage);
    fireEvent.click(screen.getByLabelText("继续聊"));
    fireEvent.contextMenu(petStage);
    fireEvent.click(screen.getByLabelText("记一条"));
    fireEvent.contextMenu(petStage);
    fireEvent.click(screen.getByLabelText("建提醒"));
    fireEvent.contextMenu(petStage);
    fireEvent.click(screen.getByLabelText("打开记忆"));
    fireEvent.contextMenu(petStage);
    fireEvent.click(screen.getByLabelText("打开设置"));

    expect(window.agentDesktop.openStage).toHaveBeenNthCalledWith(1, "memory");
    expect(window.agentDesktop.openStage).toHaveBeenNthCalledWith(2, "settings");
    expect(window.agentDesktop.openAgent).not.toHaveBeenCalled();
    expect(window.agentDesktop.openFeatureWindow).not.toHaveBeenCalled();
    expect(window.agentDesktop.quitApp).not.toHaveBeenCalled();

    expect(mockPetShowInput).toHaveBeenCalledTimes(3);
    expect(shortcutBar).toHaveAttribute("aria-hidden", "true");
    expect(shortcutBar).not.toHaveClass("is-visible");
  });

  it("offers pause speech from the pet shortcut menu while TTS is active", async () => {
    mockTtsQueueStatus.current = "playing";
    window.location.hash = "#pet";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      openStage: vi.fn().mockResolvedValue(undefined),
      getUiState: vi.fn().mockReturnValue("completed:v1"),
      setUiState: vi.fn(),
      setPetShortcutBarVisible: vi.fn().mockResolvedValue({ enabled: false, reason: "test", changed: false }),
      onPetDragCancelled: vi.fn().mockReturnValue(() => undefined),
    };

    render(<App />);

    fireEvent.contextMenu(await screen.findByLabelText("mock pet stage"));
    fireEvent.click(screen.getByLabelText("暂停朗读"));

    expect(mockTtsStop).toHaveBeenCalledWith("pet_shortcut_stop_tts");
    expect(screen.getByLabelText("桌宠快捷操作")).toHaveAttribute("aria-hidden", "true");
    expect(window.agentDesktop.openStage).not.toHaveBeenCalled();
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
    const petStageProps = live2dStageRenderProps.find((props) => props.variant === "pet");
    const petInteractions = petStageProps?.petInteractions;
    expect(petInteractions).toBeTruthy();
    const canvas = document.createElement("canvas");
    canvas.width = 300;
    canvas.height = 390;
    canvas.toDataURL = vi.fn(() => "data:image/png;base64,pet-drag-frame");
    canvas.getBoundingClientRect = vi.fn(() => ({
      x: 20,
      y: 30,
      left: 20,
      top: 30,
      right: 240,
      bottom: 312,
      width: 220,
      height: 282,
      toJSON: vi.fn(),
    }));
    petShell!.getBoundingClientRect = vi.fn(() => ({
      x: 5,
      y: 10,
      left: 5,
      top: 10,
      right: 305,
      bottom: 400,
      width: 300,
      height: 390,
      toJSON: vi.fn(),
    }));
    (petStageProps?.canvasRef as { current: HTMLCanvasElement | null }).current = canvas;

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
    expect(petShell).toHaveClass("pet-drag-snapshot-ready");
    const snapshot = document.querySelector(".pet-drag-frame-cache");
    expect(snapshot).toHaveAttribute("src", "data:image/png;base64,pet-drag-frame");
    expect(snapshot).toHaveStyle({
      left: "15px",
      top: "20px",
      width: "220px",
      height: "282px",
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
    expect(petShell).toHaveClass("pet-drag-snapshot-ready");

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

    await waitFor(() => expect(screen.getByLabelText("桌面记忆助手桌宠")).toBeInTheDocument());
    expect(window.agentDesktop.getWindowMode).toHaveBeenCalledTimes(1);
  });

  it("uses an isolated Live2D canvas ref for each renderer surface", async () => {
    window.location.hash = "#control";
    render(<App />);
    expect(await screen.findByLabelText("mock panel stage")).toBeInTheDocument();
    const panelRef = live2dStageRenderProps.find((props) => props.variant === "panel")?.canvasRef;

    live2dStageRenderProps.length = 0;
    window.location.hash = "#pet";
    render(<App />);
    expect(await screen.findByLabelText("mock pet stage")).toBeInTheDocument();
    const petRef = live2dStageRenderProps.find((props) => props.variant === "pet")?.canvasRef;

    live2dStageRenderProps.length = 0;
    window.location.hash = "#stage";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      getWindowMode: vi.fn().mockResolvedValue("stage"),
      onStageRouteRequested: vi.fn(() => () => undefined),
    };
    render(<App />);
    expect(await screen.findByLabelText("mock stage stage")).toBeInTheDocument();
    const stageRef = live2dStageRenderProps.find((props) => props.variant === "stage")?.canvasRef;

    expect(panelRef).toBeTruthy();
    expect(petRef).toBeTruthy();
    expect(stageRef).toBeTruthy();
    expect(panelRef).not.toBe(petRef);
    expect(panelRef).not.toBe(stageRef);
    expect(petRef).not.toBe(stageRef);
  });

  it("keeps active TTS playing when the renderer document is hidden", async () => {
    mockTtsQueueStatus.current = "playing";
    const visibilitySpy = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    window.location.hash = "#control";

    try {
      render(<App />);
      expect(await screen.findByLabelText("mock panel stage")).toBeInTheDocument();

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
    expect(await screen.findByLabelText("mock panel stage")).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pagehide"));
    });

    expect(mockTtsStop).toHaveBeenCalledWith("window_hidden");
  });

  it("registers Xiaomi MiMo as a backend TTS provider", async () => {
    window.location.hash = "#control";
    render(<App />);

    expect(await screen.findByLabelText("mock panel stage")).toBeInTheDocument();
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
    expect(await screen.findByLabelText("首页常驻路由")).toHaveAttribute("aria-hidden", "false");

    act(() => {
      window.location.hash = "#chat";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    await waitFor(() => expect(mockTtsStop).toHaveBeenCalledWith("window_mode_changed"));
  });

  it("keeps the stage Live2D route mounted while navigating inside the stage window", async () => {
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

    expect(await screen.findByLabelText("首页常驻路由")).toHaveAttribute("aria-hidden", "false");

    act(() => {
      window.location.hash = "#chat";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    await waitFor(() => expect(screen.getByLabelText("首页常驻路由")).toHaveAttribute("aria-hidden", "true"));
    expect(screen.getByLabelText("首页常驻路由")).toBeInTheDocument();
    expect(live2dStageRenderProps.at(-1)).toMatchObject({ variant: "stage", active: false });

    act(() => {
      requestStageRoute?.("settings");
    });

    await waitFor(() => expect(window.location.hash).toBe("#settings"));
    expect(screen.getByLabelText("首页常驻路由")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByLabelText("首页常驻路由")).toBeInTheDocument();
    expect(live2dStageRenderProps.at(-1)).toMatchObject({ variant: "stage", active: false });

    act(() => {
      window.location.hash = "#stage";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    await waitFor(() => expect(screen.getByLabelText("首页常驻路由")).toHaveAttribute("aria-hidden", "false"));
    expect(screen.getByLabelText("首页常驻路由")).toBeInTheDocument();
    expect(live2dStageRenderProps.at(-1)).toMatchObject({ variant: "stage", active: true });
  });
});
