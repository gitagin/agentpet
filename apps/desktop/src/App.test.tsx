import { createRef } from "react";
import type { MouseEvent } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { DesktopSidecarStatus } from "./types";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "./services/live2dRuntime";

const mockPetShowInput = vi.hoisted(() => vi.fn());

vi.mock("./components/Live2DStage", () => ({
  Live2DStage: ({
    variant = "panel",
    petInteractions,
  }: {
    variant?: "panel" | "pet" | "stage";
    petInteractions?: {
      onContextMenu?: (event: MouseEvent<HTMLElement>) => void;
      onDoubleClick?: (event: MouseEvent<HTMLElement>) => void;
    };
  }) => (
    <section
      aria-label={variant === "pet" ? "mock pet stage" : variant === "stage" ? "mock stage stage" : "mock panel stage"}
      onContextMenu={petInteractions?.onContextMenu}
      onDoubleClick={petInteractions?.onDoubleClick}
    />
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
    showInput: mockPetShowInput,
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
    sessionStorage.clear();
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

    render(<App />);

    expect(await screen.findByLabelText("首次使用引导")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("最近主要在忙什么？"), {
      target: { value: "准备产品加固任务" },
    });
    fireEvent.change(screen.getByLabelText("希望我长期记住什么偏好或背景？"), {
      target: { value: "偏好简洁可追踪的结果" },
    });
    fireEvent.change(screen.getByLabelText("主要想让我帮你做什么？"), {
      target: { value: "日记、任务、知识整理、项目复盘" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始第一次聊天" }));

    await waitFor(() => expect(api.startChat).toHaveBeenCalledTimes(1));
    const request = api.startChat.mock.calls[0][0];
    expect(request.message).toContain("准备产品加固任务");
    expect(request.message).toContain("偏好简洁可追踪的结果");
    expect(request.message).toContain("日记、任务、知识整理、项目复盘");
    await waitFor(() =>
      expect(window.agentDesktop?.setUiState).toHaveBeenCalledWith(
        "agent-pet.first-use-onboarding",
        "completed:v1",
      ),
    );
    expect(screen.queryByLabelText("首次使用引导")).not.toBeInTheDocument();
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

  it("toggles pet shortcut buttons from the Live2D right-click menu gesture", async () => {
    window.location.hash = "#pet";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      openAgent: vi.fn().mockResolvedValue(undefined),
      openFeatureWindow: vi.fn().mockResolvedValue(undefined),
      openStage: vi.fn().mockResolvedValue(undefined),
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
    expect(await screen.findByLabelText("桌宠入口提示")).toHaveTextContent("右键我打开功能");
    expect(screen.getByLabelText("打开桌宠主舞台")).toHaveAttribute("tabindex", "-1");

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
    expect(screen.getByLabelText("打开桌宠主舞台")).toHaveAttribute("tabindex", "0");
    expect(window.agentDesktop.setPetShortcutBarVisible).toHaveBeenLastCalledWith(true);
    expect(window.agentDesktop.setUiState).toHaveBeenCalledWith("agent-pet.pet-entry-hint", "completed:v1");

    fireEvent.click(screen.getByLabelText("打开任务工作台"));
    fireEvent.click(screen.getByLabelText("打开配置"));

    expect(window.agentDesktop.openStage).toHaveBeenCalledWith("agent");
    expect(window.agentDesktop.openStage).toHaveBeenCalledWith("settings");
    expect(window.agentDesktop.openAgent).not.toHaveBeenCalled();
    expect(window.agentDesktop.openFeatureWindow).not.toHaveBeenCalled();

    finishShortcutAnimation("pet-shortcut-roll-out");
    expect(shortcutBar).toHaveAttribute("data-shortcut-motion", "idle");

    fireEvent.contextMenu(petStage);

    expect(shortcutBar).toHaveAttribute("aria-hidden", "true");
    expect(shortcutBar).toHaveAttribute("data-shortcut-motion", "closing");
    expect(shortcutBar).not.toHaveClass("is-visible");
    expect(screen.queryByLabelText("桌宠入口提示")).not.toBeInTheDocument();
    expect(screen.getByLabelText("打开桌宠主舞台")).toHaveAttribute("tabindex", "-1");
    expect(window.agentDesktop.setPetShortcutBarVisible).toHaveBeenLastCalledWith(false);

    finishShortcutAnimation("pet-shortcut-roll-in");
    expect(shortcutBar).toHaveAttribute("data-shortcut-motion", "idle");
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

    expect(await screen.findByLabelText("stage persistent route")).toHaveAttribute("aria-hidden", "false");

    act(() => {
      window.location.hash = "#chat";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    await waitFor(() => expect(screen.getByLabelText("stage persistent route")).toHaveAttribute("aria-hidden", "true"));
    expect(screen.getByLabelText("stage persistent route")).toBeInTheDocument();

    act(() => {
      requestStageRoute?.("settings");
    });

    await waitFor(() => expect(window.location.hash).toBe("#settings"));
    expect(screen.getByLabelText("stage persistent route")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByLabelText("stage persistent route")).toBeInTheDocument();

    act(() => {
      window.location.hash = "#stage";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    await waitFor(() => expect(screen.getByLabelText("stage persistent route")).toHaveAttribute("aria-hidden", "false"));
    expect(screen.getByLabelText("stage persistent route")).toBeInTheDocument();
  });
});
