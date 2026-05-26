import { createRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { DesktopSidecarStatus } from "./types";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "./services/live2dRuntime";

vi.mock("./components/Live2DStage", () => ({
  Live2DStage: ({ variant = "panel" }: { variant?: "panel" | "pet" }) => (
    <section aria-label={variant === "pet" ? "mock pet stage" : "mock panel stage"} />
  ),
}));

vi.mock("./features/chat/PetChatOverlay", () => ({
  PetChatOverlay: () => <section aria-label="mock pet chat overlay" />,
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

const sidecarStatus: DesktopSidecarStatus = {
  state: "ready",
  baseUrl: "http://127.0.0.1:8765",
  host: "127.0.0.1",
  port: 8765,
  managed: true,
  pid: 1234,
  updatedAt: "2026-05-24T00:00:00.000Z",
  health: { status: "ok", version: "0.2.0", database: "ok" },
  error: null,
};

const api = {
  getSettingsStatus: vi.fn().mockResolvedValue({ model_configured: false, vault_configured: false }),
  getVaultStatus: vi.fn().mockResolvedValue({ configured: false, active_vault_id: null, root_path: "" }),
  listMemoryProposals: vi.fn().mockResolvedValue({ proposals: [] }),
  listAgentActions: vi.fn().mockResolvedValue({ actions: [] }),
  getContinuityState: vi.fn().mockResolvedValue({ items: [] }),
  listContinuityProposals: vi.fn().mockResolvedValue({ proposals: [] }),
  exportDiagnostics: vi.fn(),
  resetLocalState: vi.fn(),
};

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
    bindVault: vi.fn(),
    indexingVault: false,
    lastIndexRun: null,
    loadingSettingsStatus: false,
    loadSettingsStatus: vi.fn().mockResolvedValue(null),
    loadVaultStatus: vi.fn().mockResolvedValue(null),
    rebuildIndex: vi.fn(),
    resetSettingsState: vi.fn(),
    saveAgentModel: vi.fn(),
    savingAgentModelIds: new Set(),
    selectVaultDirectory: vi.fn(),
    setLastIndexRun: vi.fn(),
    setVaultPath: vi.fn(),
    testAgentModelConnection: vi.fn(),
    testingAgentModelIds: new Set(),
    updateAgentModelDraft: vi.fn(),
    vaultId: null,
    vaultPath: "",
  }),
}));

vi.mock("./features/tasks/useTasks", () => ({
  useTasks: () => ({
    addTaskFromChat: vi.fn(),
    clearTasks: vi.fn(),
    lastReminderNotification: null,
    tasks: [],
  }),
}));

vi.mock("./features/memory/useMemory", () => ({
  useMemory: () => ({
    actOnProposal: vi.fn(),
    lastSearchQuery: "",
    loadingProposals: false,
    loadPendingProposals: vi.fn().mockResolvedValue(null),
    proposalActionIds: new Set(),
    proposals: [],
    resetMemoryState: vi.fn(),
    searchResults: [],
    searchStatus: "idle",
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
  status: "recognized",
  modelId: "UG",
  modelLabel: "UG",
  modelDirectoryUrl: "/live2d/UG/",
  modelFileName: "ugofficial.model3.json",
  manifestPath: "/live2d/UG/ugofficial.model3.json",
  iconPath: "/live2d/UG/icon.png",
  hasIcon: true,
  textureCount: 2,
  expressionCount: 4,
  motionCount: 6,
  hasPhysics: true,
  hasDisplayInfo: true,
};

const live2dRuntime: Live2DRuntimeBoundary = {
  status: "assets-ready",
  title: "资源已就绪",
  detail: "测试 runtime",
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
    selectedModelId: "UG",
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
  usePetChatBubble: () => ({
    assistantReplyRef: { current: "" },
    bubble: { visible: false, title: "", message: "", tone: "thinking", phase: "idle" },
    input: "",
    inputRef: createRef<HTMLInputElement>(),
    inputVisible: false,
    replyCompleteRef: { current: false },
    replyStartedRef: { current: false },
    streamFailedRef: { current: false },
    streamOpenedRef: { current: false },
    streamReceivedEventRef: { current: false },
    clearStreamWatchdogTimer: vi.fn(),
    completeStreamWithoutReply: vi.fn(),
    failStream: vi.fn(),
    finishStream: vi.fn(),
    markStreamEventReceived: vi.fn(),
    resetStreamState: vi.fn(),
    scheduleStreamWatchdog: vi.fn(),
    setInput: vi.fn(),
    setInputVisible: vi.fn(),
    setReplyPagesFromText: vi.fn(),
    showBubble: vi.fn(),
    showContinuityPresenceBubble: vi.fn(),
    showInput: vi.fn(),
    showReaction: vi.fn(),
    showReply: vi.fn(),
    startReplyPaging: vi.fn(),
    advancePageManually: vi.fn(),
    pausePaging: vi.fn(),
    resumePaging: vi.fn(),
    latestContinuitySignalForMessage: vi.fn().mockReturnValue(null),
    latestContinuitySignalRef: { current: null },
  }),
}));

describe("App", () => {
  beforeEach(() => {
    window.location.hash = "";
    delete window.agentDesktop;
    vi.clearAllMocks();
  });

  it("renders the control dashboard when desktop bridge is unavailable", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "桌面记忆助手" })).toBeInTheDocument();
    expect(screen.getByText("记忆陪伴工作区")).toBeInTheDocument();
    expect(screen.getByText("和桌宠对话")).toBeInTheDocument();
    expect(screen.getByLabelText("mock panel stage")).toBeInTheDocument();
    expect(screen.getByLabelText("mock connection panel")).toBeInTheDocument();
  });

  it("renders the pet shell from hash routing", async () => {
    window.location.hash = "#pet";

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText("桌面记忆助手桌宠")).toBeInTheDocument());
    expect(screen.getByLabelText("mock pet stage")).toBeInTheDocument();
    expect(screen.getByLabelText("mock pet chat overlay")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "桌面记忆助手" })).not.toBeInTheDocument();
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
});
