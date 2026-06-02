import {
  Check,
  CircleAlert,
  HeartPulse,
  Loader2,
  MessageSquareText,
  RefreshCw,
  Send,
  Settings,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { AnimationEvent, CSSProperties, FormEvent, PointerEvent } from "react";
import type {
  AgentAction,
  ChatMessage,
  ChatContinuityProposal,
  MemorySearchResult,
  ChatContinuitySignal,
  Citation,
  ContinuityProposal,
  ContinuityProposalKind,
  ContinuityProposalStatus,
  ContinuityStateResponse,
  DiagnosticsExportResponse,
  DesktopFeatureWindowMode,
  DesktopVaultRevealMode,
  SettingsStatusResponse,
} from "./types";
import { describeError } from "./services/apiErrorMessages";
import { ConnectionPanel } from "./features/connection/ConnectionPanel";
import { ConnectionStatusStrip } from "./features/connection/HealthStatus";
import { useConnection } from "./features/connection/useConnection";
import { TaskPanel } from "./features/tasks/TaskPanel";
import { formatTaskStatus } from "./features/tasks/taskReducer";
import { useTasks } from "./features/tasks/useTasks";
import { SettingsPanel } from "./features/settings/SettingsPanel";
import { formatModelTestResult } from "./features/settings/settingsFormatters";
import type { LastIndexRun } from "./features/settings/settingsTypes";
import { useSettings } from "./features/settings/useSettings";
import { AgentActionActivityCard } from "./features/memory/AgentActionActivityCard";
import { MemoryProposalActivityCard } from "./features/memory/MemoryProposalActivityCard";
import { useMemory } from "./features/memory/useMemory";
import { ChatWikiProposalCard } from "./features/wiki/ChatWikiProposalCard";
import { WikiBrowserPanel } from "./features/wiki/WikiBrowserPanel";
import { WikiWorkflowPanel } from "./features/wiki/WikiWorkflowPanel";
import { wikiArchiveCandidateStorageKey } from "./features/wiki/wikiConstants";
import { useWiki } from "./features/wiki/useWiki";
import { Live2DStage } from "./components/Live2DStage";
import StageView from "./views/StageView";
import AgentWorkspaceView from "./views/AgentWorkspaceView";
import ChatWindowView from "./views/ChatWindowView";
import MemoryWindowView from "./views/MemoryWindowView";
import SettingsWindowView from "./views/SettingsWindowView";
import WorldWindowView from "./views/WorldWindowView";
import { EmptyState, Panel } from "./components/layout";
import { ChatMessageList } from "./features/chat/ChatMessageList";
import { PetChatOverlay } from "./features/chat/PetChatOverlay";
import {
  buildPetInputIntentMessage,
  normalizePetInputMode,
  petInputModes,
  type PetInputMode,
} from "./features/chat/petInputModes";
import { applyStreamEvent } from "./features/chat/streamDispatcher";
import { usePetChatBubble } from "./features/chat/usePetChatBubble";
import { pickPayloadString } from "./features/chat/chatStreamUtils";
import { Live2DModelPanel } from "./features/live2d/Live2DModelPanel";
import { live2dModelSelectionStorageKey } from "./features/live2d/live2dConstants";
import { useLive2D } from "./features/live2d/useLive2D";
import { fetchSseStream } from "./services/sse";
import { agentLabel } from "./services/agentModelDrafts";
import {
  agentActivitySortKey,
  buildAgentActivityEntries,
  isAttentionAgentAction,
  type AgentActivityLogEntry,
} from "./services/agentActivity";
import { readRendererUiState, writeRendererUiState } from "./services/rendererUiState";
import petHitboxConfig from "../pet-hitbox.json";

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type DesktopWindowMode = "pet" | "control" | "stage" | "agent" | DesktopFeatureWindowMode;
type AsyncStatus = "idle" | "loading" | "success" | "empty" | "error";
type PetShortcutMotion = "idle" | "opening" | "closing";
type FirstUseOnboardingStatus = "unknown" | "pending" | "completed";

type CoreWorkflowItem = {
  label: string;
  status: "done" | "active" | "blocked";
  detail: string;
  targetId?: string;
};

const petShortcutButtonSize = 38;
const petShortcutButtonGap = 8;
const petShortcutButtonCount = 5;
const petShortcutButtonStyles = buildPetShortcutButtonStyles();
const firstUseOnboardingStorageKey = "agent-pet.first-use-onboarding";
const firstUseOnboardingCompletedValue = "completed:v1";

function detectDesktopWindowMode(): DesktopWindowMode {
  const mode = window.location.hash.replace("#/", "").replace("#", "") || "control";
  if (
    mode === "pet" ||
    mode === "stage" ||
    mode === "agent" ||
    mode === "chat" ||
    mode === "memory" ||
    mode === "world" ||
    mode === "settings"
  ) {
    return mode;
  }
  return "control";
}

function isDesktopWindowMode(mode: unknown): mode is DesktopWindowMode {
  return (
    mode === "pet" ||
    mode === "control" ||
    mode === "stage" ||
    mode === "agent" ||
    mode === "chat" ||
    mode === "memory" ||
    mode === "world" ||
    mode === "settings"
  );
}

const petHitboxStyle = {
  "--pet-model-hit-width": `${petHitboxConfig.hitboxes.model.width}px`,
  "--pet-model-hit-height": `${petHitboxConfig.hitboxes.model.height}px`,
  "--pet-model-hit-bottom": `${petHitboxConfig.hitboxes.model.bottom}px`,
  "--pet-input-dock-hit-width": `${petHitboxConfig.hitboxes.inputDock.width}px`,
  "--pet-input-dock-hit-height": `${petHitboxConfig.hitboxes.inputDock.height}px`,
  "--pet-input-dock-hit-bottom": `${petHitboxConfig.hitboxes.inputDock.bottom}px`,
  "--pet-chat-bubble-hit-width": `${petHitboxConfig.hitboxes.chatBubble.width}px`,
  "--pet-chat-bubble-hit-height": `${petHitboxConfig.hitboxes.chatBubble.height}px`,
  "--pet-chat-bubble-hit-bottom": `${petHitboxConfig.hitboxes.chatBubble.bottom}px`,
  "--pet-shortcut-bar-width": `${petHitboxConfig.hitboxes.shortcutBar.width}px`,
  "--pet-shortcut-bar-height": `${petHitboxConfig.hitboxes.shortcutBar.height}px`,
  "--pet-shortcut-bar-right": `${petHitboxConfig.hitboxes.shortcutBar.right}px`,
  "--pet-shortcut-bar-bottom": `${petHitboxConfig.hitboxes.shortcutBar.bottom}px`,
} as CSSProperties;

function buildPetShortcutButtonStyles(): CSSProperties[] {
  const modelCenter = {
    x: petHitboxConfig.window.width / 2,
    y:
      petHitboxConfig.window.height -
      petHitboxConfig.hitboxes.model.bottom -
      petHitboxConfig.hitboxes.model.height / 2,
  };
  const shortcutBarLeft =
    petHitboxConfig.window.width -
    petHitboxConfig.hitboxes.shortcutBar.right -
    petHitboxConfig.hitboxes.shortcutBar.width;
  const shortcutBarTop =
    petHitboxConfig.window.height -
    petHitboxConfig.hitboxes.shortcutBar.bottom -
    petHitboxConfig.hitboxes.shortcutBar.height;
  const stackHeight =
    petShortcutButtonCount * petShortcutButtonSize +
    (petShortcutButtonCount - 1) * petShortcutButtonGap;
  const stackTop = shortcutBarTop + (petHitboxConfig.hitboxes.shortcutBar.height - stackHeight) / 2;

  return Array.from({ length: petShortcutButtonCount }, (_, index) => {
    const buttonCenter = {
      x: shortcutBarLeft + petHitboxConfig.hitboxes.shortcutBar.width / 2,
      y: stackTop + petShortcutButtonSize / 2 + index * (petShortcutButtonSize + petShortcutButtonGap),
    };
    return {
      "--pet-shortcut-origin-x": `${Math.round(modelCenter.x - buttonCenter.x)}px`,
      "--pet-shortcut-origin-y": `${Math.round(modelCenter.y - buttonCenter.y)}px`,
    } as CSSProperties;
  });
}

type FirstUseOnboardingDraft = {
  currentFocus: string;
  longTermContext: string;
  preferredHelp: string;
};

function buildFirstUseOnboardingMessage(draft: FirstUseOnboardingDraft): string | null {
  const currentFocus = draft.currentFocus.trim();
  const longTermContext = draft.longTermContext.trim();
  const preferredHelp = draft.preferredHelp.trim();
  if (!currentFocus && !longTermContext && !preferredHelp) {
    return null;
  }
  return [
    "这是我的首次使用引导回答。请先按普通聊天回应我，再根据现有自动整理策略判断哪些内容值得沉淀；如果没有可保存内容，请明确说明已跳过以及原因。",
    "",
    `最近主要在忙什么：${currentFocus || "未填写"}`,
    `希望你长期记住的偏好或背景：${longTermContext || "未填写"}`,
    `主要想让你帮我做什么：${preferredHelp || "未填写"}`,
  ].join("\n");
}

function FirstUseOnboardingCard({
  currentFocus,
  longTermContext,
  preferredHelp,
  connected,
  streaming,
  submitting,
  hasVaultInitialized,
  onCurrentFocusChange,
  onLongTermContextChange,
  onPreferredHelpChange,
  onSubmit,
  onSkip,
}: {
  currentFocus: string;
  longTermContext: string;
  preferredHelp: string;
  connected: boolean;
  streaming: boolean;
  submitting: boolean;
  hasVaultInitialized: boolean;
  onCurrentFocusChange: (value: string) => void;
  onLongTermContextChange: (value: string) => void;
  onPreferredHelpChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onSkip: () => void;
}) {
  const hasAnyAnswer = Boolean(currentFocus.trim() || longTermContext.trim() || preferredHelp.trim());
  return (
    <section className="first-use-onboarding" aria-label="首次使用引导">
      <div className="section-heading">
        <strong>先让我了解你</strong>
        <span>
          回答 3 个问题后会直接开始第一次聊天；没有 Vault 也可以先聊，后端只会按当前自动整理策略记录已整理或已跳过的结果。
        </span>
      </div>
      <form className="first-use-onboarding-form" onSubmit={onSubmit}>
        <label>
          <span>最近主要在忙什么？</span>
          <textarea
            rows={2}
            value={currentFocus}
            onChange={(event) => onCurrentFocusChange(event.target.value)}
            placeholder="例如：收尾一个桌面应用、准备考试、整理个人知识库"
            disabled={submitting || streaming}
          />
        </label>
        <label>
          <span>希望我长期记住什么偏好或背景？</span>
          <textarea
            rows={2}
            value={longTermContext}
            onChange={(event) => onLongTermContextChange(event.target.value)}
            placeholder="例如：喜欢简洁结论、工作日晚上复盘、项目资料优先写入 Wiki"
            disabled={submitting || streaming}
          />
        </label>
        <label>
          <span>主要想让我帮你做什么？</span>
          <textarea
            rows={2}
            value={preferredHelp}
            onChange={(event) => onPreferredHelpChange(event.target.value)}
            placeholder="陪聊、日记、任务、知识整理、项目复盘"
            disabled={submitting || streaming}
          />
        </label>
        <div className="button-row">
          <button type="submit" disabled={!connected || streaming || submitting || !hasAnyAnswer}>
            {submitting ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
            {submitting ? "正在开始" : "开始第一次聊天"}
          </button>
          <button type="button" className="secondary" onClick={onSkip} disabled={submitting || streaming}>
            跳过
          </button>
        </div>
        <p className="field-note">
          {hasVaultInitialized
            ? "当前已有 active Vault；低风险内容可按设置进入自动整理，高风险或敏感内容仍需确认或会被跳过。"
            : "当前没有 active Vault；这不会阻止聊天，也不会偷偷绑定真实知识库。"}
        </p>
      </form>
    </section>
  );
}

function App() {
  const [notice, setNotice] = useState<Notice | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [controlInput, setControlInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsExportResponse | null>(null);
  const [pendingSettingsStatusVersion, setPendingSettingsStatusVersion] = useState(0);
  const [agentActions, setAgentActions] = useState<AgentAction[]>([]);
  const [agentActionsStatus, setAgentActionsStatus] = useState<AsyncStatus>("idle");
  const [agentActionsError, setAgentActionsError] = useState("");
  const [revertingAgentActionIds, setRevertingAgentActionIds] = useState<Set<string>>(() => new Set());
  const [continuityState, setContinuityState] = useState<ContinuityStateResponse | null>(null);
  const [continuityProposals, setContinuityProposals] = useState<ContinuityProposal[]>([]);
  const [latestContinuitySignal, setLatestContinuitySignal] = useState<ChatContinuitySignal | null>(null);
  const [loadingContinuity, setLoadingContinuity] = useState(false);
  const [continuityActionIds, setContinuityActionIds] = useState<Set<string>>(() => new Set());
  const [resettingLocalState, setResettingLocalState] = useState(false);
  const [windowMode, setWindowMode] = useState<DesktopWindowMode>(() => detectDesktopWindowMode());
  const [desktopHostMode, setDesktopHostMode] = useState<DesktopWindowMode>(() => detectDesktopWindowMode());
  const [petShortcutsVisible, setPetShortcutsVisible] = useState(false);
  const [petShortcutMotion, setPetShortcutMotion] = useState<PetShortcutMotion>("idle");
  const [petInputMode, setPetInputMode] = useState<PetInputMode>("chat");
  const [firstUseOnboardingStatus, setFirstUseOnboardingStatus] =
    useState<FirstUseOnboardingStatus>("unknown");
  const [firstUseOnboardingDraft, setFirstUseOnboardingDraft] = useState({
    currentFocus: "",
    longTermContext: "",
    preferredHelp: "",
  });
  const [submittingFirstUseOnboarding, setSubmittingFirstUseOnboarding] = useState(false);
  const streamAbort = useRef<AbortController | null>(null);
  const live2dTaskStageRef = useRef<() => void>(() => undefined);
  const petDragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    dragging: boolean;
    target: HTMLElement | null;
  } | null>(null);
  const isElectronRuntime = Boolean(window.agentDesktop);
  const canSelectVaultDirectory = Boolean(window.agentDesktop?.selectKnowledgeBaseFolder);

  const pendingSettingsStatusRef = useRef<SettingsStatusResponse | null>(null);
  const openPetInputModeRef = useRef<(mode: PetInputMode) => void>(() => undefined);
  const applySettingsStatusRef = useRef<(response: SettingsStatusResponse) => void>((response) => {
    pendingSettingsStatusRef.current = response;
  });

  const {
    api,
    businessAuthMessage,
    businessAuthStatus,
    checkHealth,
    checkingHealth,
    client,
    health,
    persistSettings,
    setBusinessAuthReady,
    setSettings,
    settings,
    sidecarStatus,
  } = useConnection({
    onNotice: setNotice,
    onSettingsStatus: (response) => {
      pendingSettingsStatusRef.current = response;
      setPendingSettingsStatusVersion((current) => current + 1);
    },
  });

  const {
    agentModelDrafts,
    agentModelTestResults,
    applySettingsStatus,
    automationSettingsDraft,
    automationSettingsSaveStatus,
    bindVault,
    globalModelDraft,
    globalModelSaveStatus,
    globalModelTestResult,
    globalModelTestStatus,
    indexingVault,
    lastIndexRun,
    loadingSettingsStatus,
    loadSettingsStatus,
    loadVaultStatus,
    negotiationSettingsDraft,
    negotiationSettingsSaveStatus,
    rebuildIndex,
    resetSettingsState,
    saveAgentModel,
    saveAutomationSettings,
    saveGlobalModel,
    saveNegotiationSettings,
    savingAgentModelIds,
    selectVaultDirectory,
    setLastIndexRun,
    setVaultPath,
    testAgentModelConnection,
    testGlobalModelConnection,
    testingAgentModelIds,
    updateAgentModelDraft,
    updateAutomationSettingsDraft,
    updateGlobalModelDraft,
    updateNegotiationSettingsDraft,
    vaultId,
    vaultPath,
    vaultStatus,
  } = useSettings({
    api,
    isElectronRuntime,
    onNotice: setNotice,
  });

  applySettingsStatusRef.current = applySettingsStatus;

  const {
    addTaskFromChat,
    clearTasks,
    lastReminderNotification,
    tasks,
  } = useTasks({
    api,
    sidecarReady: sidecarStatus?.state === "ready",
    onNotice: setNotice,
    onTaskStage: () => live2dTaskStageRef.current(),
  });

  const {
    actOnProposal,
    loadingProposals,
    loadPendingProposals,
    proposalActionIds,
    proposals,
    resetMemoryState,
    searchResults,
    upsertProposalFromPayload,
  } = useMemory({
    api,
    onNotice: setNotice,
    getSearchEmptyNotice: (query) => getSearchEmptyNotice(query, lastIndexRun, diagnostics),
    onAgentActionsRefresh: () => void loadAgentActions({ silent: true }),
  });

  const {
    approvedTargetsInput: wikiApprovedTargetsInput,
    applyChatWikiProposal,
    applyIngest: applyWikiIngest,
    applyResult: wikiApplyResult,
    archiveHistory: wikiArchiveHistory,
    archiveHistoryError: wikiArchiveHistoryError,
    archiveHistoryLoading: wikiArchiveHistoryLoading,
    archiveHistoryStatus: wikiArchiveHistoryStatus,
    archiveHistorySummary: wikiArchiveHistorySummary,
    archiveLatestQuery: archiveLatestWikiQuery,
    companionContextReportError,
    companionContextReportStatus,
    companionContextReports,
    confirmChatWikiProposal,
    coreError: wikiCoreError,
    coreStatus: wikiCoreStatus,
    diagnosticsQueue: wikiDiagnosticsQueue,
    draft: wikiDraft,
    indexStatus: wikiIndexStatus,
    lastWikiArchiveId,
    latestArchiveMessage,
    latestKnowledgeCitationCount,
    lintIssueCount: wikiLintIssueCount,
    lintResult: wikiLintResult,
    linkInput: wikiLinkInput,
    loadArchiveHistory: loadWikiArchiveHistory,
    loadCoreStatus: loadWikiCoreStatus,
    loadDiagnosticsQueue: loadWikiDiagnosticsQueue,
    logStatus: wikiLogStatus,
    onDraftChange: onWikiDraftChange,
    openArchive: openWikiQueryArchive,
    openedArchive: wikiOpenedArchive,
    openingArchiveId: wikiOpeningArchiveId,
    preview: wikiPreview,
    previewIngest: previewWikiIngest,
    rejectChatWikiProposal,
    resetWikiState,
    reviewForceRefresh: wikiReviewForceRefresh,
    reviewIngest: reviewWikiIngest,
    reviewResult: wikiReviewResult,
    runLint: runWikiLint,
    schemaStatus: wikiSchemaStatus,
    setApprovedTargetsInput: setWikiApprovedTargetsInput,
    setLinkInput: setWikiLinkInput,
    setReviewForceRefresh: setWikiReviewForceRefresh,
    setTagInput: setWikiTagInput,
    synthesize: synthesizeWiki,
    tagInput: wikiTagInput,
    toggleChatWikiProposalTarget,
    upsertChatWikiProposal,
    useReviewRecommendedTargets: useWikiReviewRecommendedTargets,
    workflowAction: wikiWorkflowAction,
  } = useWiki({
    api,
    conversationId,
    diagnostics,
    messages,
    setMessages,
    vaultId,
    windowMode,
    onAgentActionsRefresh: () => void loadAgentActions({ silent: true }),
    onLastIndexRun: setLastIndexRun,
    onNotice: setNotice,
  });

  const petChat = usePetChatBubble({
    messages,
    latestContinuitySignal,
    setMessages,
    setNotice,
    abortStream: () => streamAbort.current?.abort(),
  });

  useEffect(() => {
    document.body.dataset.windowMode = windowMode;
    return () => {
      delete document.body.dataset.windowMode;
    };
  }, [windowMode]);

  useEffect(() => {
    const visible = windowMode === "pet" && petShortcutsVisible;
    window.agentDesktop?.setPetShortcutBarVisible?.(visible);
    return () => {
      window.agentDesktop?.setPetShortcutBarVisible?.(false);
    };
  }, [petShortcutsVisible, windowMode]);

  useEffect(() => {
    const visible = windowMode === "pet" && petChat.inputVisible;
    window.agentDesktop?.setPetInputVisible?.(visible);
    return () => {
      window.agentDesktop?.setPetInputVisible?.(false);
    };
  }, [petChat.inputVisible, windowMode]);

  useEffect(() => {
    let cancelled = false;
    void window.agentDesktop?.getWindowMode?.().then((mode) => {
      if (!cancelled && isDesktopWindowMode(mode)) {
        setDesktopHostMode(mode);
      }
      const detectedMode = detectDesktopWindowMode();
      if (!cancelled && detectedMode !== "control") {
        setWindowMode(detectedMode);
        return;
      }
      if (!cancelled && (mode === "pet" || mode === "control")) {
        setWindowMode(mode);
      }
    });
    if (!window.agentDesktop?.getWindowMode) {
      setDesktopHostMode(detectDesktopWindowMode());
    }

    const updateFromHash = () => setWindowMode(detectDesktopWindowMode());
    window.addEventListener("hashchange", updateFromHash);
    return () => {
      cancelled = true;
      window.removeEventListener("hashchange", updateFromHash);
    };
  }, []);

  useEffect(() => {
    if (windowMode !== "control") {
      return;
    }
    const unsubscribe = window.agentDesktop?.onControlTargetRequested?.((targetId) => {
      window.requestAnimationFrame(() => scrollToWorkflowTarget(targetId));
    });
    return unsubscribe;
  }, [windowMode]);

  useEffect(() => {
    if (desktopHostMode !== "stage") {
      return;
    }
    const unsubscribe = window.agentDesktop?.onStageRouteRequested?.((mode) => {
      const nextMode = isDesktopWindowMode(mode) ? mode : "stage";
      const nextHash = `#${nextMode}`;
      if (window.location.hash !== nextHash) {
        window.location.hash = nextMode;
        return;
      }
      setWindowMode(nextMode);
    });
    return unsubscribe;
  }, [desktopHostMode]);

  useEffect(() => {
    if (windowMode !== "pet") {
      return;
    }
    const unsubscribe = window.agentDesktop?.onPetInputModeRequested?.((requestedMode) => {
      const normalizedMode = normalizePetInputMode(requestedMode);
      if (!normalizedMode) {
        return;
      }
      openPetInputModeRef.current(normalizedMode);
    });
    return unsubscribe;
  }, [windowMode]);

  useEffect(() => {
    const saved = readRendererUiState(firstUseOnboardingStorageKey);
    setFirstUseOnboardingStatus(saved === firstUseOnboardingCompletedValue ? "completed" : "pending");
  }, []);

  useEffect(() => {
    const cancelPetDrag = () => {
      const dragState = petDragRef.current;
      try {
        window.agentDesktop?.endPetWindowDrag?.();
        if (dragState?.target?.hasPointerCapture(dragState.pointerId)) {
          dragState.target.releasePointerCapture(dragState.pointerId);
        }
      } catch {
        // 透明桌宠窗口在失焦或系统拖动中可能丢失 pointer capture；本地状态必须照常清理。
      } finally {
        petDragRef.current = null;
      }
    };
    const unsubscribe = window.agentDesktop?.onPetDragCancelled?.(cancelPetDrag);
    window.addEventListener("blur", cancelPetDrag);
    window.addEventListener("pointercancel", cancelPetDrag);
    window.addEventListener("pointerup", cancelPetDrag);
    return () => {
      unsubscribe?.();
      window.removeEventListener("blur", cancelPetDrag);
      window.removeEventListener("pointercancel", cancelPetDrag);
      window.removeEventListener("pointerup", cancelPetDrag);
    };
  }, []);

  useEffect(() => {
    const pending = pendingSettingsStatusRef.current;
    if (!pending) {
      return;
    }
    pendingSettingsStatusRef.current = null;
    applySettingsStatus(pending);
  }, [applySettingsStatus, pendingSettingsStatusVersion]);

  useEffect(() => {
    const abort = new AbortController();
    void loadSettingsStatus({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [loadSettingsStatus]);

  useEffect(() => {
    const abort = new AbortController();
    void loadContinuity({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [api]);

  useEffect(() => {
    const abort = new AbortController();
    void loadPendingProposals({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [loadPendingProposals]);

  useEffect(() => {
    const abort = new AbortController();
    void loadAgentActions({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [api]);

  useEffect(() => {
    if (sidecarStatus?.state !== "ready") {
      return;
    }
    const abort = new AbortController();
    void loadVaultStatus({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [loadVaultStatus, sidecarStatus?.state, sidecarStatus?.updatedAt]);

  async function sendChatText(rawText: string, clearInput: () => void): Promise<boolean> {
    const text = rawText.trim();
    if (!text || streaming) {
      return false;
    }
    if (agentActionsStatus !== "loading") {
      void loadAgentActions({ silent: true });
    }

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      status: "completed",
    };
    const assistantId = crypto.randomUUID();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      status: "partial",
      citations: [],
    };

    setMessages((current) => [...current, userMessage, assistantMessage]);
    clearInput();
    petChat.setInputVisible(false);
    setStreaming(true);
    setNotice(null);
    petChat.resetStreamState();
    petChat.showBubble({
      title: "正在发送",
      message: "我正在把你的话交给后端。",
      tone: "thinking",
    });
    petChat.scheduleStreamWatchdog(
      "请求仍在处理中",
      "后端还没有返回回复流地址，可能正在启动或等待模型服务。",
      8000,
      () => petChat.failStream(assistantId, "请求超时", "后端长时间没有返回回复流地址，本次请求已停止。"),
    );

    const abort = new AbortController();
    streamAbort.current = abort;

    try {
      const accepted = await api.startChat(
        {
          conversation_id: conversationId,
          message: text,
        },
        abort.signal,
      );
      setConversationId(accepted.conversation_id);
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId ? { ...message, agent_run_id: accepted.agent_run_id } : message,
        ),
      );
      petChat.showBubble({
        title: "正在连接回复流",
        message: "后端已接收请求，我正在等待实时回复。",
        tone: "thinking",
      });
      petChat.scheduleStreamWatchdog(
        "回复流连接较慢",
        "后端已创建会话，但回复流还没有打开，请再等一下。",
        8000,
        () => petChat.failStream(assistantId, "回复流超时", "后端已接收请求，但长时间没有打开回复流。"),
      );

      await fetchSseStream(
        client,
        accepted.stream_url,
        {
          onOpen: () => {
            petChat.streamOpenedRef.current = true;
            petChat.clearStreamWatchdogTimer();
            if (!petChat.replyStartedRef.current && !petChat.streamReceivedEventRef.current) {
              petChat.showBubble({
                title: "等待回复",
                message: "回复流已连接，我在等模型返回第一段内容。",
                tone: "thinking",
              });
              petChat.scheduleStreamWatchdog(
                "仍在等待模型",
                "后端连接正常，但模型还没有返回第一段回复。",
                12000,
                () => petChat.failStream(assistantId, "模型回复超时", "回复流已连接，但模型长时间没有返回可显示内容。"),
              );
            }
          },
          onEvent: (sseEvent) =>
            applyStreamEvent(assistantId, sseEvent, {
              petChat,
              setMessages,
              appendChatEvent,
              upsertAgentAction,
              setLatestContinuitySignal,
              upsertChatContinuitySignal,
              normalizeContinuitySignal,
              upsertContinuityProposal,
              upsertChatContinuityProposal,
              normalizeContinuityProposal,
              formatContinuityKind,
              upsertProposalFromPayload,
              upsertChatWikiProposal,
              addTaskFromChat,
              triggerLive2DTaskStage,
            }),
        },
        abort.signal,
      );
      petChat.clearStreamWatchdogTimer();

      if (petChat.streamFailedRef.current) {
        return false;
      }

      if (petChat.replyStartedRef.current) {
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId && message.status === "partial"
              ? { ...message, status: "completed" }
              : message,
            ),
        );
        petChat.startReplyPaging();
        const signal = petChat.latestContinuitySignalForMessage(assistantId);
        if (signal) {
          const delay = Math.min(9000, Math.max(1200, petChat.replyPagesRef.current.length * 2600));
          window.setTimeout(() => petChat.showContinuityPresenceBubble(signal), delay);
        }
      } else {
        petChat.completeStreamWithoutReply(assistantId);
      }
      return !petChat.streamFailedRef.current;
    } catch (error) {
      petChat.clearStreamWatchdogTimer();
      petChat.streamFailedRef.current = true;
      const message = describeError(error, "消息发送失败");
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? { ...message, status: "failed", content: message.content || describeError(error, "消息发送失败") }
            : message,
        ),
      );
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        petChat.showBubble({
          title: "交互失败",
          message,
          tone: "error",
        });
        petChat.scheduleHide(10000);
        setNotice({ tone: "error", message });
      }
      return false;
    } finally {
      petChat.clearStreamWatchdogTimer();
      setStreaming(false);
      streamAbort.current = null;
      petChat.finishStream();
    }
  }

  async function sendPetMessage(event: FormEvent) {
    event.preventDefault();
    await sendChatText(buildPetInputIntentMessage(petInputMode, petChat.input), () => petChat.setInput(""));
  }

  async function submitFirstUseOnboarding(event: FormEvent) {
    event.preventDefault();
    if (submittingFirstUseOnboarding || streaming || !hasConnection) {
      return;
    }
    const message = buildFirstUseOnboardingMessage(firstUseOnboardingDraft);
    if (!message) {
      setNotice({ tone: "error", message: "请至少填写一个首次使用问题，再开始第一次整理。" });
      return;
    }
    setSubmittingFirstUseOnboarding(true);
    const completed = await sendChatText(message, () => undefined);
    setSubmittingFirstUseOnboarding(false);
    if (!completed) {
      return;
    }
    writeRendererUiState(firstUseOnboardingStorageKey, firstUseOnboardingCompletedValue);
    setFirstUseOnboardingStatus("completed");
    setNotice({
      tone: "success",
      message: "首次引导已完成；本轮整理结果会显示在聊天消息和最近自动整理活动中。",
    });
  }

  function skipFirstUseOnboarding() {
    writeRendererUiState(firstUseOnboardingStorageKey, firstUseOnboardingCompletedValue);
    setFirstUseOnboardingStatus("completed");
    setNotice({ tone: "info", message: "已跳过首次引导，可以直接开始聊天。" });
  }

  function openPetInputMode(mode: PetInputMode) {
    setPetInputMode(mode);
    setPetShortcutsVisible(false);
    setPetShortcutMotion("idle");
    petChat.showInput();
  }
  openPetInputModeRef.current = openPetInputMode;

  function appendChatEvent(
    messageId: string,
    event: { label: string; detail: string; tone?: "info" | "success" | "error" },
  ) {
    setMessages((current) =>
      current.map((message) =>
        message.id === messageId
          ? {
              ...message,
              events: [
                ...(message.events || []),
                {
                  id: crypto.randomUUID(),
                  label: event.label,
                  detail: event.detail,
                  tone: event.tone,
                },
              ],
            }
          : message,
      ),
    );
  }

  function upsertAgentAction(action: AgentAction) {
    setAgentActions((current) => {
      const next = [action, ...current.filter((item) => item.action_id !== action.action_id)];
      return next
        .sort((left, right) =>
          agentActivitySortKey(right.updated_at || right.created_at) -
          agentActivitySortKey(left.updated_at || left.created_at),
        )
        .slice(0, 50);
    });
  }

  async function loadAgentActions(options: { silent?: boolean; signal?: AbortSignal } = {}) {
    setAgentActionsStatus("loading");
    setAgentActionsError("");
    if (!options.silent) {
      setNotice(null);
    }
    try {
      const response = await api.listAgentActions(30, null, options.signal);
      setAgentActions(response.actions);
      setAgentActionsStatus(response.actions.length > 0 ? "success" : "empty");
      if (!options.silent) {
        setNotice({ tone: "success", message: `已刷新 ${response.actions.length} 条最近自动整理活动。` });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      const message = describeError(error, "最近自动整理活动加载失败");
      setAgentActionsStatus("error");
      setAgentActionsError(message);
      if (!options.silent) {
        setNotice({ tone: "error", message });
      }
    }
  }

  async function revertAgentAction(action: AgentAction) {
    const confirmed = window.confirm(
      `撤销“${action.title}”会通过后端恢复该活动记录的 Markdown 快照。确定继续吗？`,
    );
    if (!confirmed) {
      return;
    }

    setRevertingAgentActionIds((current) => new Set(current).add(action.action_id));
    setNotice(null);
    try {
      const response = await api.revertAgentAction(action.action_id);
      setAgentActions((current) => {
        const updates = new Map<string, AgentAction>([
          [response.action.action_id, response.action],
          [response.reverted.action_id, response.reverted],
        ]);
        const merged = [...updates.values(), ...current.filter((item) => !updates.has(item.action_id))];
        return merged
          .sort((left, right) =>
            agentActivitySortKey(right.updated_at || right.created_at) -
            agentActivitySortKey(left.updated_at || left.created_at),
          )
          .slice(0, 50);
      });
      setMessages((current) =>
        current.map((message) => {
          const existing = message.agent_actions || [];
          if (!existing.some((item) => item.action_id === response.action.action_id)) {
            return message;
          }
          const updated = existing.map((item) =>
            item.action_id === response.action.action_id ? response.action : item,
          );
          return {
            ...message,
            agent_actions: updated.some((item) => item.action_id === response.reverted.action_id)
              ? updated
              : [...updated, response.reverted],
          };
        }),
      );
      setNotice({ tone: "success", message: `已撤销自动整理活动：${response.action.title}。` });
      void loadAgentActions({ silent: true });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "撤销自动整理活动失败") });
    } finally {
      setRevertingAgentActionIds((current) => {
        const next = new Set(current);
        next.delete(action.action_id);
        return next;
      });
    }
  }

  async function revealAgentActionTarget(relativePath: string, mode: DesktopVaultRevealMode) {
    if (!window.agentDesktop?.revealVaultPath) {
      setNotice({
        tone: "info",
        message: "当前浏览器预览不能打开本地 Vault 文件；请在 Electron 桌面端使用该操作。",
      });
      return;
    }

    try {
      const result = await window.agentDesktop.revealVaultPath(relativePath, mode);
      if (result.status === "opened" || result.status === "shown") {
        setNotice({
          tone: "success",
          message: result.status === "opened" ? `已打开 ${result.relative_path}。` : `已在文件夹中显示 ${result.relative_path}。`,
        });
        return;
      }
      setNotice({
        tone: "error",
        message: `无法打开 Vault 目标：${result.reason || result.status}。`,
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "打开 Vault 目标失败") });
    }
  }

  function upsertContinuityProposal(proposal: ContinuityProposal) {
    setContinuityProposals((current) => {
      const rest = current.filter((item) => item.proposal_id !== proposal.proposal_id);
      return [proposal, ...rest];
    });
  }

  function upsertChatContinuityProposal(messageId: string, proposal: ChatContinuityProposal) {
    setMessages((current) =>
      current.map((message) => {
        if (message.id !== messageId) {
          return message;
        }
        const rest = (message.continuity_proposals || []).filter(
          (item) => item.proposal_id !== proposal.proposal_id,
        );
        return {
          ...message,
          continuity_proposals: [proposal, ...rest],
        };
      }),
    );
  }

  function upsertChatContinuitySignal(messageId: string, signal: ChatContinuitySignal) {
    setMessages((current) =>
      current.map((message) =>
        message.id === messageId ? { ...message, continuity_signal: signal } : message,
      ),
    );
  }

  function renderAgentActivityEntry(entry: AgentActivityLogEntry) {
    if (entry.kind === "agent_action") {
      return (
        <AgentActionActivityCard
          key={entry.id}
          entry={entry}
          reverting={revertingAgentActionIds.has(entry.action.action_id)}
          onRevert={(action) => void revertAgentAction(action)}
          onRevealTarget={(relativePath, mode) => void revealAgentActionTarget(relativePath, mode)}
        />
      );
    }
    if (entry.kind === "memory_proposal") {
      return (
        <MemoryProposalActivityCard
          key={entry.id}
          entry={entry}
          busy={proposalActionIds.has(entry.proposal.proposal_id)}
          onAct={(proposalId, action) => void actOnProposal(proposalId, action)}
        />
      );
    }
    if (entry.kind === "continuity_proposal") {
      return renderContinuityProposalActivity(entry);
    }
    return (
      <ChatWikiProposalCard
        key={entry.id}
        message={entry.message}
        proposal={entry.proposal}
        formatIssueSeverity={formatIssueSeverity}
        onConfirm={confirmChatWikiProposal}
        onReject={rejectChatWikiProposal}
        onToggleTarget={toggleChatWikiProposalTarget}
        onApply={(messageId, proposalId) => void applyChatWikiProposal(messageId, proposalId)}
      />
    );
  }

  function renderContinuityProposalActivity(entry: Extract<AgentActivityLogEntry, { kind: "continuity_proposal" }>) {
    const proposal = entry.proposal;
    const busy = continuityActionIds.has(proposal.proposal_id);
    return (
      <article
        key={entry.id}
        id={`continuity-proposal-${proposal.proposal_id}`}
        className={`proposal continuity-proposal ${proposal.status}`}
      >
        <div className="continuity-proposal-head">
          <div>
            <strong>连续性确认 · {formatContinuityKind(proposal.kind)}</strong>
            <small>高风险确认 / {formatContinuityStatus(proposal.status)} / 置信度 {formatConfidence(proposal.confidence)}</small>
          </div>
          <span>{proposal.proposal_id}</span>
        </div>
        <p>{proposal.summary}</p>
        <small>证据：{proposal.evidence}</small>
        <small>来源：{proposal.source_message_id || "未知"} / {proposal.agent_run_id || "无运行 ID"}</small>
        <div className="button-row">
          <button
            type="button"
            className="secondary"
            disabled={busy || proposal.status !== "pending"}
            onClick={() => void actOnContinuityProposal(proposal.proposal_id, "confirm")}
          >
            {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
            确认
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy || proposal.status !== "pending"}
            onClick={() => void actOnContinuityProposal(proposal.proposal_id, "reject")}
          >
            <X size={16} />
            拒绝
          </button>
        </div>
      </article>
    );
  }

  function stopStreaming() {
    petChat.clearStreamWatchdogTimer();
    petChat.streamFailedRef.current = true;
    streamAbort.current?.abort();
    setStreaming(false);
    petChat.showBubble({
      title: "已停止",
      message: "本次回复已停止生成。",
      tone: "error",
    });
    petChat.scheduleHide(5000);
    setMessages((current) =>
      current.map((message) => (message.status === "partial" ? { ...message, status: "cancelled" } : message)),
    );
  }

  async function loadContinuity(options: { silent?: boolean; signal?: AbortSignal } = {}) {
    setLoadingContinuity(true);
    if (!options.silent) {
      setNotice(null);
    }
    try {
      const [state, proposalsResponse] = await Promise.all([
        api.getContinuityState(options.signal),
        api.listContinuityProposals(options.signal),
      ]);
      setContinuityState(state);
      setContinuityProposals(proposalsResponse.proposals);
      if (!options.silent) {
        setNotice({
          tone: "success",
          message: `连续性状态已刷新：${state.items.length} 个已确认状态，${proposalsResponse.proposals.length} 条待确认整理项。`,
        });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (!options.silent) {
        setNotice({ tone: "error", message: describeError(error, "连续性状态加载失败") });
      }
    } finally {
      setLoadingContinuity(false);
    }
  }

  async function actOnContinuityProposal(proposalId: string, action: "confirm" | "reject") {
    setContinuityActionIds((current) => new Set(current).add(proposalId));
    setNotice(null);
    try {
      const response =
        action === "confirm"
          ? await api.confirmContinuityProposal(proposalId)
          : await api.rejectContinuityProposal(proposalId, "用户在连续性审核面板中拒绝。");
      setContinuityProposals((current) =>
        current.map((proposal) =>
          proposal.proposal_id === proposalId
            ? { ...proposal, status: response.status, updated_at: new Date().toISOString() }
            : proposal,
        ),
      );
      await loadContinuity({ silent: true });
      void loadAgentActions({ silent: true });
      setNotice({
        tone: "success",
        message:
          action === "confirm"
            ? "连续性整理项已确认，已进入运行时连续性状态；未写入 Vault Markdown。"
            : "连续性整理项已拒绝，不会进入提示词或 Live2D 状态。",
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "连续性整理项操作失败") });
    } finally {
      setContinuityActionIds((current) => {
        const next = new Set(current);
        next.delete(proposalId);
        return next;
      });
    }
  }

  async function resetLocalState() {
    const confirmed = window.confirm(
      "这会清空本机桌宠的聊天记录、长期记忆、连续性状态、任务、Vault 绑定、索引缓存、模型配置和本地密钥。不会删除 Vault 里的 Markdown 文件。确定要重置为初始化状态吗？",
    );
    if (!confirmed) {
      return;
    }
    setResettingLocalState(true);
    setNotice(null);
    try {
      const response = await api.resetLocalState("RESET_AGENT_PET");
      clearRendererResettableState();
      setConversationId(null);
      petChat.resetStreamState();
      setMessages([]);
      resetMemoryState();
      setAgentActions([]);
      setAgentActionsStatus("idle");
      setAgentActionsError("");
      setRevertingAgentActionIds(new Set());
      clearTasks();
      setContinuityState(null);
      setContinuityProposals([]);
      setLatestContinuitySignal(null);
      setDiagnostics(null);
      resetSettingsState();
      resetWikiState();
      setBusinessAuthReady("业务接口鉴权可用，本地状态已重置。");
      const clearedRows = Object.values(response.cleared_tables).reduce((total, count) => total + count, 0);
      setNotice({
        tone: "success",
        message: `本机桌宠已重置为初始化状态，清理 ${clearedRows} 条本地状态记录。`,
      });
      await loadSettingsStatus({ silent: true });
      await loadVaultStatus({ silent: true });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "本机状态重置失败") });
    } finally {
      setResettingLocalState(false);
    }
  }

  function beginPetDrag(event: PointerEvent<HTMLElement>) {
    if (windowMode !== "pet" || event.button !== 0) {
      return;
    }
    if (!window.agentDesktop?.beginPetWindowDrag || !window.agentDesktop.activatePetWindowDrag) {
      return;
    }
    event.preventDefault();
    petDragRef.current = {
      pointerId: event.pointerId,
      startX: event.screenX,
      startY: event.screenY,
      dragging: false,
      target: event.currentTarget,
    };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      petDragRef.current = null;
      window.agentDesktop?.endPetWindowDrag?.();
      return;
    }
    window.agentDesktop.beginPetWindowDrag();
  }

  function movePetDrag(event: PointerEvent<HTMLElement>) {
    const dragState = petDragRef.current;
    if (windowMode !== "pet" || !dragState || dragState.pointerId !== event.pointerId) {
      return;
    }

    const movedX = event.screenX - dragState.startX;
    const movedY = event.screenY - dragState.startY;
    if (!dragState.dragging && Math.hypot(movedX, movedY) < 6) {
      return;
    }

    if (!dragState.dragging) {
      dragState.dragging = true;
      window.agentDesktop?.activatePetWindowDrag?.();
    }
  }

  function endPetDrag(event?: PointerEvent<HTMLElement>) {
    try {
      if (event && petDragRef.current?.pointerId === event.pointerId && event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      window.agentDesktop?.endPetWindowDrag?.();
    } catch {
      // 即使释放 pointer capture 或 IPC 失败，也不能让拖动状态残留。
    } finally {
      petDragRef.current = null;
    }
  }

  function togglePetShortcuts() {
    setPetShortcutsVisible((visible) => {
      setPetShortcutMotion(visible ? "closing" : "opening");
      return !visible;
    });
  }

  function finishPetShortcutMotion(event: AnimationEvent<HTMLElement>) {
    if (event.animationName === "pet-shortcut-roll-out" || event.animationName === "pet-shortcut-roll-in") {
      setPetShortcutMotion("idle");
    }
  }

  function scrollToWorkflowTarget(targetId?: string) {
    if (!targetId) {
      return;
    }
    document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const hasConnection = sidecarStatus?.state === "ready" || health?.status === "ok";
  const hasVaultInitialized = Boolean(vaultId || diagnostics?.vault.configured);
  const hasIndexSignal = Boolean(
    lastIndexRun ||
      searchResults.length > 0 ||
      diagnostics?.recent_index_jobs.some((job) =>
        ["completed", "done", "indexed", "success"].includes(job.status.toLowerCase()),
      ),
  );
  const hasMemoryConfirmed = proposals.some((proposal) => proposal.status === "confirmed" || Boolean(proposal.written_path));
  const pendingContinuityCount = continuityProposals.filter((proposal) => proposal.status === "pending").length;
  const hasContinuityState = Boolean(continuityState?.items.length);
  const hasDiagnosticsExport = Boolean(diagnostics);
  const hasAgentEventSignal = messages.some((message) => (message.events || []).length > 0 || (message.citations || []).length > 0);
  const pendingProposalCount = proposals.filter((proposal) => proposal.status === "pending").length;
  const latestAssistantMessage = messages.filter((message) => message.role === "assistant").slice(-1)[0];
  const latestChatEvent = latestAssistantMessage?.events?.slice(-1)[0];
  const activeContinuitySignal = latestAssistantMessage?.continuity_signal || latestContinuitySignal;
  const latestCitation = latestAssistantMessage?.citations?.slice(-1)[0];
  const latestCitationTargetId = latestCitation ? findCitationTargetId(latestCitation, searchResults) : undefined;
  const recentControlMessages = messages.slice(-6);
  const agentActivityEntries = buildAgentActivityEntries(agentActions, proposals, continuityProposals, messages);
  const recentAgentActivityEntries = agentActivityEntries.slice(0, 8);
  const pendingManualActivityCount = agentActivityEntries.filter((entry) => entry.kind !== "agent_action").length;
  const automaticActivityCount = agentActivityEntries.filter(
    (entry) => entry.kind === "agent_action" && !isAttentionAgentAction(entry.action),
  ).length;
  const hasAgentActivity = agentActivityEntries.length > 0;
  const agentWorkflowItems: CoreWorkflowItem[] = agentModelDrafts.map((draft) => {
    const testResult = agentModelTestResults[draft.agent_id];
    const tested = testResult?.status === "ok";
    return {
      label: agentLabel(draft.agent_id),
      status: tested ? "done" : draft.configured ? "active" : "blocked",
      detail: tested && testResult
        ? formatModelTestResult(testResult)
        : draft.configured
          ? `${draft.model} 已保存，${draft.masked || "密钥已配置"}，等待试连。`
          : "等待保存提供方、接口地址、模型和密钥。",
    };
  });
  const coreWorkflowItems: CoreWorkflowItem[] = [
    ...agentWorkflowItems,
    {
      label: "Obsidian Vault / 索引",
      status: hasVaultInitialized && hasIndexSignal ? "done" : hasVaultInitialized ? "active" : "blocked",
      detail: lastIndexRun
        ? `最近索引 ${formatTaskStatus(lastIndexRun.status)}，文件 ${lastIndexRun.filesIndexed ?? 0}/${lastIndexRun.filesSeen ?? 0}`
        : hasVaultInitialized
          ? "Vault 已初始化，下一步运行索引。"
          : "先选择并初始化 Obsidian/Markdown Vault。",
    },
    {
      label: "助手运行事件",
      status: hasAgentEventSignal ? "done" : streaming ? "active" : "blocked",
      detail: latestChatEvent
        ? `${latestChatEvent.label}：${latestChatEvent.detail}`
        : latestCitation
          ? `引用：${latestCitation.relative_path}`
          : streaming
            ? "正在等待 SSE 工具事件。"
            : "向桌宠提问后显示检索、记忆、任务或引用事件。",
      targetId: latestCitationTargetId,
    },
    {
      label: "自动整理活动",
      status: pendingManualActivityCount > 0 ? "active" : hasAgentActivity || hasMemoryConfirmed ? "done" : "blocked",
      detail:
        pendingManualActivityCount > 0
          ? `${pendingManualActivityCount} 个高风险项待确认；普通自动整理只作为活动记录展示。`
          : automaticActivityCount > 0
            ? `${automaticActivityCount} 条普通自动整理已记录，可在活动流中查看或撤销可逆项。`
            : hasMemoryConfirmed
              ? "已有确认写入的记忆整理记录。"
              : "桌宠自动整理会进入最近活动，高风险写入仍需确认。",
      targetId: "agent-activity-log",
    },
    {
      label: "连续性状态",
      status: hasContinuityState ? "done" : pendingContinuityCount > 0 ? "active" : "blocked",
      detail:
        pendingContinuityCount > 0
          ? `${pendingContinuityCount} 条连续性整理需要确认；确认后只进入运行时 SQLite 状态。`
          : hasContinuityState
            ? `已确认 ${continuityState?.items.length ?? 0} 个连续性状态。`
            : "低风险情绪与话题会自动整理；身份、关系或低置信内容才需要确认。",
      targetId: pendingContinuityCount > 0 ? "agent-activity-log" : "continuity-panel",
    },
  ];
  const {
    asset: live2dAsset,
    canvasRef: live2dCanvasRef,
    models: live2dModels,
    runtime: live2dRuntime,
    selectedModelId: selectedLive2dModelId,
    selectModel: selectLive2DModel,
    stage: live2dStage,
    triggerTaskStage: triggerLive2DTaskStage,
  } = useLive2D({
    connected: hasConnection,
    streaming,
    searchResultCount: searchResults.length,
    pendingProposalCount,
    taskCount: tasks.length,
    diagnosticsReady: hasDiagnosticsExport,
    continuityState,
    continuitySignal: activeContinuitySignal,
  });
  live2dTaskStageRef.current = triggerLive2DTaskStage;

  const refreshActivity = () => {
    void loadAgentActions();
    void loadPendingProposals({ silent: true });
    void loadContinuity({ silent: true });
  };
  const showFirstUseOnboarding = firstUseOnboardingStatus === "pending" && (windowMode === "control" || windowMode === "chat");
  const firstUseOnboardingPanel = showFirstUseOnboarding ? (
    <FirstUseOnboardingCard
      currentFocus={firstUseOnboardingDraft.currentFocus}
      longTermContext={firstUseOnboardingDraft.longTermContext}
      preferredHelp={firstUseOnboardingDraft.preferredHelp}
      connected={hasConnection}
      streaming={streaming}
      submitting={submittingFirstUseOnboarding}
      hasVaultInitialized={hasVaultInitialized}
      onCurrentFocusChange={(value) => setFirstUseOnboardingDraft((current) => ({ ...current, currentFocus: value }))}
      onLongTermContextChange={(value) => setFirstUseOnboardingDraft((current) => ({ ...current, longTermContext: value }))}
      onPreferredHelpChange={(value) => setFirstUseOnboardingDraft((current) => ({ ...current, preferredHelp: value }))}
      onSubmit={submitFirstUseOnboarding}
      onSkip={skipFirstUseOnboarding}
    />
  ) : null;
  const connectionPanel = (
    <Panel id="connection-panel" icon={<Settings size={18} />} title="本地连接">
      <ConnectionPanel
        settings={settings}
        onSettingsChange={setSettings}
        onSaveSettings={persistSettings}
        onCheckHealth={() => void checkHealth()}
        checkingHealth={checkingHealth}
        isElectronRuntime={isElectronRuntime}
        health={health}
        businessAuthStatus={businessAuthStatus}
        businessAuthMessage={businessAuthMessage}
      />
      <section className="danger-zone" aria-label="本机状态重置">
        <div className="section-heading">
          <strong>重置桌宠初始化状态</strong>
          <span>清空本机聊天、记忆、任务、Vault 绑定、索引缓存和模型配置，让应用回到首次启动状态。</span>
        </div>
        <div className="button-row">
          <button
            type="button"
            className="danger"
            onClick={() => void resetLocalState()}
            disabled={resettingLocalState}
          >
            {resettingLocalState ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            {resettingLocalState ? "正在重置" : "重置桌宠"}
          </button>
        </div>
        <p className="field-note error">
          仅清理本机应用状态和本地凭据引用，不删除 Vault 目录中的 Markdown 文件。打包发版前可用它确认客户首次启动不会带开发测试记录。
        </p>
      </section>
    </Panel>
  );
  const wikiBrowserPanel = (
    <WikiBrowserPanel
      schemaStatus={wikiSchemaStatus}
      indexStatus={wikiIndexStatus}
      logStatus={wikiLogStatus}
      lintResult={wikiLintResult}
      diagnosticsQueue={wikiDiagnosticsQueue}
      archiveHistory={wikiArchiveHistory}
      archiveHistoryStatus={wikiArchiveHistoryStatus}
      archiveHistoryError={wikiArchiveHistoryError}
      archiveHistoryLoading={wikiArchiveHistoryLoading}
      coreStatus={wikiCoreStatus}
      coreError={wikiCoreError}
      workflowAction={wikiWorkflowAction}
      openingArchiveId={wikiOpeningArchiveId}
      formatIssueSeverity={formatIssueSeverity}
      onLoadCoreStatus={() => void loadWikiCoreStatus()}
      onLoadArchiveHistory={() => void loadWikiArchiveHistory()}
      onLoadDiagnosticsQueue={() => void loadWikiDiagnosticsQueue()}
      onOpenArchive={(archiveId) => void openWikiQueryArchive(archiveId)}
    />
  );
  const wikiWorkflowPanel = (
    <WikiWorkflowPanel
      draft={wikiDraft}
      tagInput={wikiTagInput}
      linkInput={wikiLinkInput}
      approvedTargetsInput={wikiApprovedTargetsInput}
      reviewForceRefresh={wikiReviewForceRefresh}
      preview={wikiPreview}
      reviewResult={wikiReviewResult}
      applyResult={wikiApplyResult}
      lintResult={wikiLintResult}
      diagnosticsQueue={wikiDiagnosticsQueue}
      schemaStatus={wikiSchemaStatus}
      indexStatus={wikiIndexStatus}
      logStatus={wikiLogStatus}
      coreStatus={wikiCoreStatus}
      coreError={wikiCoreError}
      archiveHistory={wikiArchiveHistory}
      archiveHistoryStatus={wikiArchiveHistoryStatus}
      archiveHistoryError={wikiArchiveHistoryError}
      openedArchive={wikiOpenedArchive}
      openingArchiveId={wikiOpeningArchiveId}
      companionContextReports={companionContextReports}
      companionContextReportStatus={companionContextReportStatus}
      companionContextReportError={companionContextReportError}
      lastWikiArchiveId={lastWikiArchiveId}
      workflowAction={wikiWorkflowAction}
      latestArchiveMessage={latestArchiveMessage}
      latestKnowledgeCitationCount={latestKnowledgeCitationCount}
      archiveHistorySummary={wikiArchiveHistorySummary}
      archiveHistoryLoading={wikiArchiveHistoryLoading}
      lintIssueCount={wikiLintIssueCount}
      formatIssueSeverity={formatIssueSeverity}
      onDraftChange={onWikiDraftChange}
      onTagInputChange={setWikiTagInput}
      onLinkInputChange={setWikiLinkInput}
      onApprovedTargetsInputChange={setWikiApprovedTargetsInput}
      onReviewForceRefreshChange={setWikiReviewForceRefresh}
      onPreview={(event) => void previewWikiIngest(event)}
      onReview={() => void reviewWikiIngest()}
      onApply={() => void applyWikiIngest()}
      onArchiveLatestQuery={() => void archiveLatestWikiQuery()}
      onSynthesize={() => void synthesizeWiki()}
      onRunLint={() => void runWikiLint()}
      onLoadDiagnosticsQueue={() => void loadWikiDiagnosticsQueue()}
      onLoadArchiveHistory={() => void loadWikiArchiveHistory()}
      onLoadCoreStatus={() => void loadWikiCoreStatus()}
      onUseReviewRecommendedTargets={useWikiReviewRecommendedTargets}
      onOpenArchive={(archiveId) => void openWikiQueryArchive(archiveId)}
    />
  );
  const settingsPanel = (
    <SettingsPanel
      api={api}
      agentModelDrafts={agentModelDrafts}
      agentModelTestResults={agentModelTestResults}
      globalModelDraft={globalModelDraft}
      globalModelSaveStatus={globalModelSaveStatus}
      globalModelTestResult={globalModelTestResult}
      globalModelTestStatus={globalModelTestStatus}
      automationSettingsDraft={automationSettingsDraft}
      automationSettingsSaveStatus={automationSettingsSaveStatus}
      negotiationSettingsDraft={negotiationSettingsDraft}
      negotiationSettingsSaveStatus={negotiationSettingsSaveStatus}
      savingAgentModelIds={savingAgentModelIds}
      testingAgentModelIds={testingAgentModelIds}
      loadingSettingsStatus={loadingSettingsStatus}
      vaultId={vaultId}
      vaultPath={vaultPath}
      vaultStatus={vaultStatus}
      lastIndexRun={lastIndexRun}
      indexingVault={indexingVault}
      canSelectVaultDirectory={canSelectVaultDirectory}
      onRefreshSettings={() => void loadSettingsStatus()}
      onUpdateGlobalModelDraft={updateGlobalModelDraft}
      onSaveGlobalModel={() => void saveGlobalModel()}
      onTestGlobalModel={() => void testGlobalModelConnection()}
      onUpdateAutomationSettingsDraft={updateAutomationSettingsDraft}
      onSaveAutomationSettings={() => void saveAutomationSettings()}
      onUpdateNegotiationSettingsDraft={updateNegotiationSettingsDraft}
      onSaveNegotiationSettings={() => void saveNegotiationSettings()}
      onUpdateAgentModelDraft={updateAgentModelDraft}
      onSaveAgentModel={(agentId) => void saveAgentModel(agentId)}
      onTestAgentModel={(agentId) => void testAgentModelConnection(agentId)}
      onVaultPathChange={setVaultPath}
      onSelectVaultDirectory={() => void selectVaultDirectory()}
      onBindVault={bindVault}
      onLoadVaultStatus={() => void loadVaultStatus()}
      onRebuildIndex={() => void rebuildIndex()}
    />
  );

  const petHitboxDebug =
    windowMode === "pet" && new URLSearchParams(window.location.search).get("hitbox") === "1";
  const stageView = (
    <StageView
      live2dStage={live2dStage}
      live2dAsset={live2dAsset}
      live2dRuntime={live2dRuntime}
      live2dCanvasRef={live2dCanvasRef}
      connected={hasConnection}
      streaming={streaming}
      bubble={petChat.bubble}
      onSendChat={sendChatText}
      onStopStreaming={stopStreaming}
      onAdvancePage={petChat.advancePageManually}
      onPausePaging={petChat.pausePaging}
      onResumePaging={petChat.resumePaging}
    />
  );
  const isStageHostWindow = desktopHostMode === "stage";

  if (isStageHostWindow && windowMode !== "pet" && windowMode !== "control") {
    const activeRoute =
      windowMode === "agent" ? (
        <AgentWorkspaceView api={api} />
      ) : windowMode === "chat" ? (
        <ChatWindowView
          input={controlInput}
          messages={messages}
          connected={hasConnection}
          streaming={streaming}
          onInputChange={setControlInput}
          onSend={(event) => {
            event.preventDefault();
            void sendChatText(controlInput, () => setControlInput(""));
          }}
          onStopStreaming={stopStreaming}
          revertingActionIds={revertingAgentActionIds}
          onRevertAgentAction={(action) => void revertAgentAction(action)}
          onOpenMemory={() => setWindowMode("memory")}
          onboardingPanel={firstUseOnboardingPanel}
        />
      ) : windowMode === "memory" ? (
        <MemoryWindowView
          api={api}
          loading={agentActionsStatus === "loading" || loadingProposals || loadingContinuity}
          error={agentActionsError}
          entries={agentActivityEntries}
          onRefresh={refreshActivity}
          renderEntry={renderAgentActivityEntry}
        />
      ) : windowMode === "world" ? (
        <WorldWindowView>
          <div className="feature-page-stack">
            {wikiBrowserPanel}
            {wikiWorkflowPanel}
          </div>
        </WorldWindowView>
      ) : windowMode === "settings" ? (
        <SettingsWindowView>
          <div className="feature-page-stack">
            {connectionPanel}
            {settingsPanel}
          </div>
        </SettingsWindowView>
      ) : null;

    return (
      <div className="stage-host-routes" data-active-route={windowMode}>
        <div
          className={`stage-host-route${windowMode === "stage" ? " is-active" : ""}`}
          aria-label="stage persistent route"
          aria-hidden={windowMode !== "stage"}
        >
          {stageView}
        </div>
        {windowMode !== "stage" ? (
          <div className="stage-host-route is-active" aria-label="stage active route">
            {activeRoute}
          </div>
        ) : null}
      </div>
    );
  }

  if (windowMode === "stage") {
    return stageView;
  }

  if (windowMode === "agent") {
    return <AgentWorkspaceView api={api} />;
  }

  if (windowMode === "chat") {
    return (
      <ChatWindowView
        input={controlInput}
        messages={messages}
        connected={hasConnection}
        streaming={streaming}
        onInputChange={setControlInput}
        onSend={(event) => {
          event.preventDefault();
          void sendChatText(controlInput, () => setControlInput(""));
        }}
        onStopStreaming={stopStreaming}
        revertingActionIds={revertingAgentActionIds}
        onRevertAgentAction={(action) => void revertAgentAction(action)}
        onOpenMemory={() => setWindowMode("memory")}
        onboardingPanel={firstUseOnboardingPanel}
      />
    );
  }

  if (windowMode === "memory") {
    return (
      <MemoryWindowView
        api={api}
        loading={agentActionsStatus === "loading" || loadingProposals || loadingContinuity}
        error={agentActionsError}
        entries={agentActivityEntries}
        onRefresh={refreshActivity}
        renderEntry={renderAgentActivityEntry}
      />
    );
  }

  if (windowMode === "world") {
    return (
      <WorldWindowView>
        <div className="feature-page-stack">
          {wikiBrowserPanel}
          {wikiWorkflowPanel}
        </div>
      </WorldWindowView>
    );
  }

  if (windowMode === "settings") {
    return (
      <SettingsWindowView>
        <div className="feature-page-stack">
          {connectionPanel}
          {settingsPanel}
        </div>
      </SettingsWindowView>
    );
  }

  if (windowMode === "pet") {
    return (
      <main
        className={[
          "pet-shell",
          petHitboxDebug ? "pet-debug-hitbox" : "",
          petChat.bubble.visible ? "pet-bubble-visible" : "",
        ].filter(Boolean).join(" ")}
        style={petHitboxStyle}
        aria-label="桌面记忆助手桌宠"
        onDragStart={(event) => event.preventDefault()}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => event.preventDefault()}
      >
        <Live2DStage
          key={`pet-${live2dAsset.modelId}`}
          stage={live2dStage}
          asset={live2dAsset}
          runtime={live2dRuntime}
          canvasRef={live2dCanvasRef}
          variant="pet"
          petInteractions={{
            onPointerDown: beginPetDrag,
            onPointerMove: movePetDrag,
            onPointerUp: endPetDrag,
            onPointerCancel: endPetDrag,
            onLostPointerCapture: endPetDrag,
            onContextMenu: (event) => {
              event.preventDefault();
              endPetDrag();
              togglePetShortcuts();
            },
            onBubbleContextMenu: (event) => {
              event.preventDefault();
              endPetDrag();
            },
            onDoubleClick: () => {
              endPetDrag();
              void window.agentDesktop?.openStage?.();
            },
          }}
        />
        <PetChatOverlay
          bubble={petChat.bubble}
          input={petChat.input}
          inputVisible={petChat.inputVisible}
          inputRef={petChat.inputRef}
          mode={petInputMode}
          modes={petInputModes}
          connected={hasConnection}
          streaming={streaming}
          onAdvancePage={petChat.advancePageManually}
          onPausePaging={petChat.pausePaging}
          onResumePaging={petChat.resumePaging}
          onInputChange={petChat.setInput}
          onModeChange={openPetInputMode}
          onInputClose={() => petChat.setInputVisible(false)}
          onSubmit={sendPetMessage}
          onStopStreaming={stopStreaming}
        />
        <nav
          className={`pet-shortcut-bar${petShortcutsVisible ? " is-visible" : ""}`}
          data-shortcut-motion={petShortcutMotion}
          aria-label="桌宠快捷操作"
          aria-hidden={!petShortcutsVisible}
          onContextMenu={(event) => event.preventDefault()}
          onAnimationEnd={finishPetShortcutMotion}
        >
          <button type="button" className="pet-shortcut-button" style={petShortcutButtonStyles[0]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="打开桌宠主舞台" onClick={() => void window.agentDesktop?.openStage?.()}>
            桌宠
          </button>
          <button type="button" className="pet-shortcut-button" style={petShortcutButtonStyles[1]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="开始聊天" onClick={() => openPetInputMode("chat")}>
            聊天
          </button>
          <button type="button" className="pet-shortcut-button" style={petShortcutButtonStyles[2]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="打开任务工作台" onClick={() => void window.agentDesktop?.openStage?.("agent")}>
            任务
          </button>
          <button type="button" className="pet-shortcut-button" style={petShortcutButtonStyles[3]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="打开配置" onClick={() => void window.agentDesktop?.openStage?.("settings")}>
            配置
          </button>
          <button type="button" className="pet-shortcut-button danger" style={petShortcutButtonStyles[4]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="退出应用" onClick={() => void window.agentDesktop?.quitApp?.()}>
            退出
          </button>
        </nav>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">本地优先 · 透明记忆 · 桌宠陪伴</p>
          <h1>桌面记忆助手</h1>
        </div>
        <ConnectionStatusStrip sidecarStatus={sidecarStatus} health={health} />
      </header>

      {notice ? (
        <div className={`notice ${notice.tone}`} role="status">
          {notice.tone === "error" ? <CircleAlert size={18} /> : <ShieldCheck size={18} />}
          <span>{notice.message}</span>
        </div>
      ) : null}

      <section className="dashboard-grid">
        <Live2DStage
          key={`panel-${live2dAsset.modelId}`}
          stage={live2dStage}
          asset={live2dAsset}
          runtime={live2dRuntime}
          canvasRef={live2dCanvasRef}
        />

        <Panel id="agent-workspace-panel" icon={<MessageSquareText size={18} />} title="记忆陪伴工作区" className="chat-panel">
          <section className="stack" aria-label="聊天和 Obsidian 记忆工作流">
            {firstUseOnboardingPanel}
            <div className="section-heading">
              <strong>和桌宠对话</strong>
              <span>日常聊天会优先引用资料库；自动记忆功能默认关闭，可在设置中开启，高风险写入仍会打断你确认。</span>
            </div>
            <form
              className="chat-form"
              onSubmit={(event) => {
                event.preventDefault();
                void sendChatText(controlInput, () => setControlInput(""));
              }}
            >
              <input
                value={controlInput}
                onChange={(event) => setControlInput(event.target.value)}
                placeholder={hasConnection ? "和桌宠说点什么，或让它引用资料库、整理记忆、创建任务..." : "正在等待本地助手连接..."}
                disabled={streaming}
              />
              {streaming ? (
                <button type="button" className="danger" onClick={stopStreaming}>
                  <X size={16} />
                  停止
                </button>
              ) : (
                <button type="submit" disabled={!controlInput.trim() || !hasConnection}>
                  <Send size={16} />
                  发送
                </button>
              )}
            </form>
            <section id="agent-activity-log" className="stack" aria-label="最近自动整理活动">
              <div className="section-heading">
                <strong>最近自动整理活动</strong>
                <span>
                  {pendingManualActivityCount > 0
                    ? `${pendingManualActivityCount} 个高风险项需要确认；普通自动整理只保留为活动记录。`
                    : agentActionsStatus === "loading"
                      ? "正在刷新活动记录。"
                      : hasAgentActivity
                        ? `最近 ${recentAgentActivityEntries.length} 条活动；可逆动作会提供撤销入口。`
                        : "还没有自动整理活动。"}
                </span>
              </div>
              <div className="button-row">
                <button
                  type="button"
                  className="secondary"
                  onClick={refreshActivity}
                  disabled={agentActionsStatus === "loading" || loadingProposals || loadingContinuity}
                >
                  {agentActionsStatus === "loading" || loadingProposals || loadingContinuity ? (
                    <Loader2 className="spin" size={16} />
                  ) : (
                    <RefreshCw size={16} />
                  )}
                  刷新活动
                </button>
              </div>
              {agentActionsError ? <p className="field-note error">{agentActionsError}</p> : null}
              <div className="proposal-list agent-activity-log-list">
                {recentAgentActivityEntries.length > 0 ? (
                  recentAgentActivityEntries.map((entry) => renderAgentActivityEntry(entry))
                ) : agentActionsStatus === "loading" || loadingProposals || loadingContinuity ? (
                  <EmptyState text="正在加载最近自动整理活动。" />
                ) : (
                  <EmptyState text="普通自动整理完成后会出现在这里；高风险写入会在这里显示确认入口。" />
                )}
              </div>
            </section>
            <ChatMessageList
              messages={recentControlMessages}
              revertingActionIds={revertingAgentActionIds}
              onRevertAgentAction={(action) => void revertAgentAction(action)}
              onOpenMemory={() => setWindowMode("memory")}
            />
            <div className="workflow-grid" aria-label="助手与 Obsidian 工作流状态">
              {coreWorkflowItems.map((item) => (
                <article key={item.label} className={`workflow-card ${item.status}`}>
                  <span className="workflow-state">{formatWorkflowStatus(item.status)}</span>
                  <strong>{item.label}</strong>
                  <p>{item.detail}</p>
                  {item.targetId ? (
                    <button type="button" className="secondary" onClick={() => scrollToWorkflowTarget(item.targetId)}>
                      定位
                    </button>
                  ) : null}
                </article>
              ))}
              <TaskPanel
                tasks={tasks}
                lastReminderNotification={lastReminderNotification}
                onLocateTask={scrollToWorkflowTarget}
              />
            </div>
          </section>
        </Panel>

        <Live2DModelPanel
          models={live2dModels}
          selectedModelId={selectedLive2dModelId}
          asset={live2dAsset}
          onSelectModel={selectLive2DModel}
        />

        {connectionPanel}

        <Panel id="continuity-panel" icon={<HeartPulse size={18} />} title="陪伴状态">
          <section className="stack" aria-label="连续性状态">
            <div className="section-heading">
              <strong>关系与状态连续性</strong>
              <span>确认后只进入 SQLite 运行时状态；不会写入 Vault Markdown。</span>
            </div>
            <div className="button-row">
              <button type="button" className="secondary" onClick={() => void loadContinuity()} disabled={loadingContinuity}>
                {loadingContinuity ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                刷新
              </button>
            </div>
            <dl className="details continuity-state-grid">
              <div>
                <dt>身份特质</dt>
                <dd>{continuityState?.identity_traits || "未确认"}</dd>
              </div>
              <div>
                <dt>关系摘要</dt>
                <dd>{continuityState?.relationship_summary || "未确认"}</dd>
              </div>
              <div>
                <dt>当前情绪</dt>
                <dd>{continuityState?.current_mood || "未确认"}</dd>
              </div>
              <div>
                <dt>情绪惯性</dt>
                <dd>{continuityState?.mood_momentum || "未确认"}</dd>
              </div>
              <div>
                <dt>能量水平</dt>
                <dd>{continuityState?.energy_level || "未确认"}</dd>
              </div>
              <div>
                <dt>未完话题</dt>
                <dd>{continuityState?.unresolved_threads || "无"}</dd>
              </div>
            </dl>
            {pendingContinuityCount > 0 ? (
              <p className="field-note">
                有 {pendingContinuityCount} 条连续性确认项，已合并到“最近自动整理活动”中处理。
              </p>
            ) : (
              <p className="field-note">当前没有待确认的连续性整理项。</p>
            )}
          </section>
        </Panel>

        {wikiWorkflowPanel}

        {settingsPanel}

      </section>
    </main>
  );
}



function clearRendererResettableState(): void {
  for (const key of [
    "agent-pet.base-url",
    firstUseOnboardingStorageKey,
    live2dModelSelectionStorageKey,
    wikiArchiveCandidateStorageKey,
  ]) {
    writeRendererUiState(key, null);
  }
}

function normalizeContinuityProposal(payload: Record<string, unknown> | null): ContinuityProposal | null {
  if (!payload) {
    return null;
  }
  const proposalId = pickPayloadString(payload, ["proposal_id", "id"]);
  const kind = pickPayloadString(payload, ["kind"]);
  const summary = pickPayloadString(payload, ["summary"]);
  const evidence = pickPayloadString(payload, ["evidence"]) || "";
  if (!proposalId || !isContinuityKind(kind) || !summary) {
    return null;
  }
  const confidence =
    typeof payload.confidence === "number"
      ? payload.confidence
      : Number.parseFloat(String(payload.confidence ?? "0"));
  const now = new Date().toISOString();
  return {
    proposal_id: proposalId,
    kind,
    summary,
    evidence,
    confidence: Number.isFinite(confidence) ? confidence : 0,
    source_conversation_id: pickPayloadString(payload, ["source_conversation_id"]),
    source_message_id: pickPayloadString(payload, ["source_message_id"]),
    agent_run_id: pickPayloadString(payload, ["agent_run_id"]),
    status: (pickPayloadString(payload, ["status"]) as ContinuityProposalStatus | null) || "pending",
    rejected_reason: pickPayloadString(payload, ["rejected_reason"]),
    created_at: pickPayloadString(payload, ["created_at"]) || now,
    updated_at: pickPayloadString(payload, ["updated_at"]) || now,
  };
}

function normalizeContinuitySignal(payload: Record<string, unknown> | null): ChatContinuitySignal | null {
  if (!payload) {
    return null;
  }
  const kind = pickPayloadString(payload, ["kind"]) || "relationship";
  const title = pickPayloadString(payload, ["title"]) || "连续性在场";
  const summary = pickPayloadString(payload, ["summary"]);
  if (!summary) {
    return null;
  }
  const intensity = pickPayloadString(payload, ["intensity"]) || "medium";
  const displayHint = pickPayloadString(payload, ["display_hint"]) || "只作为运行时陪伴提示；不会写入 Vault。";
  const keys = Array.isArray(payload.source_state_keys)
    ? payload.source_state_keys.filter((value): value is string => typeof value === "string")
    : [];
  return {
    kind,
    title,
    summary,
    intensity,
    display_hint: displayHint,
    source_state_keys: keys,
  };
}

function isContinuityKind(value: unknown): value is ContinuityProposalKind {
  return (
    value === "identity" ||
    value === "relationship" ||
    value === "mood" ||
    value === "energy" ||
    value === "open_thread"
  );
}

function formatContinuityKind(kind: ContinuityProposalKind | string): string {
  const labels: Record<ContinuityProposalKind, string> = {
    identity: "身份连续性",
    relationship: "关系连续性",
    mood: "情绪状态",
    energy: "能量水平",
    open_thread: "未完话题",
  };
  return isContinuityKind(kind) ? labels[kind] : kind;
}

function formatContinuityStatus(status: ContinuityProposalStatus): string {
  const labels: Record<string, string> = {
    pending: "待确认",
    confirmed: "已确认",
    rejected: "已拒绝",
  };
  return labels[status] || status;
}

function formatConfidence(confidence: number): string {
  if (!Number.isFinite(confidence)) {
    return "未知";
  }
  return `${Math.round(confidence * 100)}%`;
}

function findCitationTargetId(citation: Citation, results: MemorySearchResult[]): string | undefined {
  const matched = results.find((result) =>
    citation.chunk_id
      ? result.chunk_id === citation.chunk_id
      : result.relative_path === citation.relative_path,
  );
  return matched ? `search-result-${matched.chunk_id}` : undefined;
}

function formatWorkflowStatus(status: CoreWorkflowItem["status"]): string {
  const labels: Record<CoreWorkflowItem["status"], string> = {
    done: "已就绪",
    active: "进行中",
    blocked: "待处理",
  };
  return labels[status];
}

function formatIssueSeverity(severity: string): string {
  const labels: Record<string, string> = {
    error: "错误",
    warning: "警告",
    info: "提示",
  };
  return labels[severity] || severity;
}

function getSearchEmptyNotice(
  query: string,
  lastIndexRun: LastIndexRun | null,
  diagnostics: DiagnosticsExportResponse | null,
): string {
  const recentCompletedIndex = diagnostics?.recent_index_jobs.find((job) =>
    ["completed", "done", "indexed", "success"].includes(job.status.toLowerCase()),
  );
  if (lastIndexRun || recentCompletedIndex) {
    return `没有找到“${query}”的结果。最近已有索引记录，请换一个关键词，或确认目标 Markdown 已在当前知识库中。`;
  }
  return `没有找到“${query}”的结果。当前页面还没有索引完成记录，请先初始化知识库或点击“索引”后再搜索。`;
}

export default App;
