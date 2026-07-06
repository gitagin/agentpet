import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type {
  AgentAction,
  ChatMessage,
  ChatContinuityProposal,
  MemorySearchResult,
  ChatContinuitySignal,
  Citation,
  ContinuityProposal,
  ContinuityStateResponse,
  DiagnosticsExportResponse,
  DesktopVaultRevealMode,
  SettingsStatusResponse,
} from "./types";
import { describeError } from "./services/apiErrorMessages";
import { useConnection } from "./features/connection/useConnection";
import { useTasks } from "./features/tasks/useTasks";
import { isTtsSettingsSavedMessage, settingsSyncChannelName } from "./features/settings/settingsSync";
import type { LastIndexRun } from "./features/settings/settingsTypes";
import { useSettings } from "./features/settings/useSettings";
import { normalizeMemoryProposalPayload } from "./features/memory/memoryUtils";
import { useMemory } from "./features/memory/useMemory";
import { wikiArchiveCandidateStorageKey } from "./features/wiki/wikiConstants";
import { useWiki } from "./features/wiki/useWiki";
import StageView from "./views/StageView";
import {
  buildPetInputIntentMessage,
  getPetInputModeOption,
  petInputModes,
  type PetInputMode,
} from "./features/chat/petInputModes";
import { applyStreamEvent } from "./features/chat/streamDispatcher";
import { usePetChatBubble } from "./features/chat/usePetChatBubble";
import { useProactiveHabitLoop } from "./features/habitLoop/useProactiveHabitLoop";
import {
  firstUseOnboardingStorageKey,
  useFirstUseOnboarding,
} from "./features/onboarding/useFirstUseOnboarding";
import { useTtsOrchestrator } from "./features/tts/useTtsOrchestrator";
import { resolvePetReplyActionKey } from "./features/pet/petReplyActions";
import { getPetStageView } from "./features/pet/petStageState";
import {
  formatContinuityKind,
  normalizeContinuityProposal,
  normalizeContinuitySignal,
} from "./features/continuity/continuityFormatters";
import { fetchSseStream } from "./services/sse";
import {
  agentActivitySortKey,
  buildAgentActivityEntries,
  isAttentionAgentAction,
  type AgentActivityLogEntry,
} from "./services/agentActivity";
import { writeRendererUiState } from "./services/rendererUiState";
import { petHitboxStyle, petShortcutButtonStyles } from "./features/pet/petHitboxStyles";
import { PetWindow } from "./features/pet/PetWindow";
import {
  petEntryHintStorageKey,
  usePetWindowController,
} from "./features/pet/usePetWindowController";
import { ControlDashboard } from "./features/desktop/ControlDashboard";
import { AgentActivityEntryRenderer } from "./features/desktop/AgentActivityEntryRenderer";
import { DesktopFeatureRoutes } from "./features/desktop/DesktopFeatureRoutes";
import { buildControlWorkflowItems } from "./features/desktop/controlWorkflowItems";
import { useDesktopWindowRouting } from "./features/desktop/useDesktopWindowRouting";
import { ConnectionManagementPanel } from "./features/desktop/ConnectionManagementPanel";
import { SettingsPanel } from "./features/settings/SettingsPanel";
import { WikiManagementPanels } from "./features/desktop/WikiManagementPanels";
import type { HalfbodyPetPortraitHandle } from "./features/halfbody/HalfbodyPetPortrait";
import { buildHalfbodyTtsTimelineFromText } from "./features/halfbody/halfbodyTtsTimeline";

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type AsyncStatus = "idle" | "loading" | "success" | "empty" | "error";
type SendChatTextOptions = {
  displayText?: string;
};

const agentActionMemoryReviewLimit = 200;
const localAgentActionCacheLimit = 200;

function displayTextForInputMode(mode: PetInputMode, rawText: string): string {
  const text = rawText.trim();
  if (mode === "chat") {
    return text;
  }
  const label = getPetInputModeOption(mode).label;
  return text ? `${label}：${text}` : label;
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
  const { desktopHostMode, setWindowMode, windowMode } = useDesktopWindowRouting({
    onControlTargetRequested: scrollToWorkflowTarget,
  });
  const [petInputMode, setPetInputMode] = useState<PetInputMode>("chat");
  const streamAbort = useRef<AbortController | null>(null);
  const activeChatRequestIdRef = useRef<string | null>(null);
  const streamingRef = useRef(false);
  const conversationIdRef = useRef<string | null>(conversationId);
  const petTaskStageRef = useRef<() => void>(() => undefined);
  const petTaskStageTimeoutRef = useRef<number | null>(null);
  const [recentTaskStageActive, setRecentTaskStageActive] = useState(false);
  const petCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const halfbodyPortraitRef = useRef<HalfbodyPetPortraitHandle | null>(null);
  const isElectronRuntime = Boolean(window.agentDesktop);
  const canSelectVaultDirectory = Boolean(window.agentDesktop?.selectKnowledgeBaseFolder);

  const pendingSettingsStatusRef = useRef<SettingsStatusResponse | null>(null);
  const applySettingsStatusRef = useRef<(response: SettingsStatusResponse) => void>((response) => {
    pendingSettingsStatusRef.current = response;
  });

  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);

  useEffect(() => {
    streamingRef.current = streaming;
  }, [streaming]);

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
    clearTtsCache,
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
    saveTtsSettings,
    savingAgentModelIds,
    selectVaultDirectory,
    setLastIndexRun,
    setVaultPath,
    settingsStatus,
    testAgentModelConnection,
    testGlobalModelConnection,
    testingAgentModelIds,
    ttsSettingsDraft,
    ttsSettingsSaveStatus,
    updateAgentModelDraft,
    updateAutomationSettingsDraft,
    updateGlobalModelDraft,
    updateNegotiationSettingsDraft,
    updateTtsSettingsDraft,
    vaultId,
    vaultPath,
    vaultStatus,
  } = useSettings({
    api,
    isElectronRuntime,
    onNotice: setNotice,
  });

  applySettingsStatusRef.current = applySettingsStatus;

  function triggerPetTaskStage() {
    setRecentTaskStageActive(true);
    if (petTaskStageTimeoutRef.current !== null) {
      window.clearTimeout(petTaskStageTimeoutRef.current);
    }
    petTaskStageTimeoutRef.current = window.setTimeout(() => {
      setRecentTaskStageActive(false);
      petTaskStageTimeoutRef.current = null;
    }, 12000);
  }

  petTaskStageRef.current = triggerPetTaskStage;

  useEffect(() => {
    return () => {
      if (petTaskStageTimeoutRef.current !== null) {
        window.clearTimeout(petTaskStageTimeoutRef.current);
      }
    };
  }, []);

  const taskReminderPollingEnabled =
    (desktopHostMode === "pet" && windowMode === "pet") ||
    windowMode === "control" ||
    windowMode === "stage";
  const {
    addTaskFromChat,
    clearTasks,
    lastReminderNotification,
    tasks,
  } = useTasks({
    api,
    pollingEnabled: taskReminderPollingEnabled,
    sidecarReady: sidecarStatus?.state === "ready",
    onNotice: setNotice,
    onTaskStage: () => petTaskStageRef.current(),
  });

  const {
    actOnProposal,
    createProposal,
    lastSearchQuery,
    loadingProposals,
    loadPendingProposals,
    proposalActionIds,
    proposalDraft,
    proposals,
    resetMemoryState,
    runMemorySearch,
    searchQuery,
    searchResults,
    searchStatus,
    setSearchQuery,
    updateProposalDraft,
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

  const tts = useTtsOrchestrator({
    api,
    settings: settingsStatus?.tts_settings,
    windowMode,
    onNotice: setNotice,
  });

  const petChat = usePetChatBubble({
    messages,
    latestContinuitySignal,
    setMessages,
    setNotice,
    abortStream: () => streamAbort.current?.abort(),
    tts: {
      enabled: tts.enabled,
      queue: tts.queue,
      provider: tts.provider,
      voice: tts.voice,
      speed: tts.speed,
      volume: tts.volume,
      cacheEnabled: tts.cacheEnabled,
      playbackState: tts.queue.state,
    },
  });
  tts.bindPetPlaybackHandlers({
    onStart: (item) => {
      tts.waitingCue.stop("assistant_tts_started");
      petChat.handleTtsPlaybackStart?.(item);
      halfbodyPortraitRef.current?.speak(null, buildHalfbodyTtsTimelineFromText(item.text, {
        targetDurationMs: readTtsPlaybackDurationMs(item),
      }));
    },
    onEnd: (item, status) => {
      petChat.handleTtsPlaybackEnd?.(item, status);
      halfbodyPortraitRef.current?.speak(null);
    },
  });

  useEffect(() => {
    if (!tts.speaking) {
      halfbodyPortraitRef.current?.speak(null);
    }
  }, [tts.speaking]);
  const petWindow = usePetWindowController({
    windowMode,
    petChat,
    onPetInputModeChange: setPetInputMode,
  });

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
    if (!("BroadcastChannel" in window)) {
      return;
    }
    const channel = new BroadcastChannel(settingsSyncChannelName);
    channel.onmessage = (event) => {
      if (isTtsSettingsSavedMessage(event.data)) {
        void loadSettingsStatus({ silent: true });
      }
    };
    return () => channel.close();
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

  async function sendChatText(
    rawText: string,
    clearInput: () => void,
    options: SendChatTextOptions = {},
  ): Promise<boolean> {
    const text = rawText.trim();
    if (!text || streamingRef.current) {
      return false;
    }
    tts.waitingCue.stop("new_request");
    streamAbort.current?.abort();
    const requestId = crypto.randomUUID();
    activeChatRequestIdRef.current = requestId;
    const displayText = options.displayText?.trim() || text;
    if (agentActionsStatus !== "loading") {
      void loadAgentActions({ silent: true });
    }

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: displayText,
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
    streamingRef.current = true;
    setStreaming(true);
    setNotice(null);
    petChat.resetStreamState(assistantId);
    const waitingCueMessage = tts.waitingCue.start();
    petChat.showBubble({
      title: "",
      message: waitingCueMessage,
      tone: "thinking",
    });
    petChat.scheduleStreamWatchdog(
      "正在整理",
      "资料多一点，我继续看。",
      14000,
      () => petChat.failStream(assistantId, "没有等到回复", "这次没有等到可显示的回复，本轮已停止。"),
    );

    const abort = new AbortController();
    streamAbort.current = abort;
    const isCurrentRequest = () => activeChatRequestIdRef.current === requestId;

    try {
      const accepted = await api.startChat(
        {
          conversation_id: conversationIdRef.current,
          message: text,
        },
        abort.signal,
      );
      if (!isCurrentRequest()) {
        return false;
      }
      conversationIdRef.current = accepted.conversation_id;
      setConversationId(accepted.conversation_id);
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId ? { ...message, agent_run_id: accepted.agent_run_id } : message,
        ),
      );
      petChat.scheduleStreamWatchdog(
        "正在整理",
        "资料多一点，我继续看。",
        14000,
        () => petChat.failStream(assistantId, "没有等到回复", "这次没有等到可显示的回复，本轮已停止。"),
      );

      await fetchSseStream(
        client,
        accepted.stream_url,
        {
          onOpen: () => {
            petChat.streamOpenedRef.current = true;
            petChat.clearStreamWatchdogTimer();
            if (!petChat.replyStartedRef.current && !petChat.streamReceivedEventRef.current) {
              petChat.scheduleStreamWatchdog(
                "正在整理",
                "资料多一点，我继续看。",
                14000,
                () => petChat.failStream(assistantId, "没有等到回复", "这次没有等到可显示的回复，本轮已停止。"),
              );
            }
          },
          onEvent: (sseEvent) => {
            if (!isCurrentRequest()) {
              return;
            }
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
              upsertChatMemoryProposal: (targetMessageId, proposalId, payload) => {
                const proposal = normalizeMemoryProposalPayload(proposalId, payload);
                setMessages((current) =>
                  current.map((message) => {
                    if (message.id !== targetMessageId) {
                      return message;
                    }
                    const proposalsForMessage = message.memory_proposals || [];
                    return {
                      ...message,
                      memory_proposals: [
                        proposal,
                        ...proposalsForMessage.filter((item) => item.proposal_id !== proposal.proposal_id),
                      ],
                    };
                  }),
                );
              },
              upsertChatWikiProposal,
              addTaskFromChat,
              triggerPetTaskStage,
              onVisibleAssistantReply: () => tts.waitingCue.stop("assistant_visible_reply"),
            });
            if (sseEvent.event === "reply_ready") {
              streamingRef.current = false;
              setStreaming(false);
              void loadAgentActions({ silent: true });
            }
          },
        },
        abort.signal,
      );
      if (!isCurrentRequest()) {
        return false;
      }
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
        petChat.startReplyPaging(assistantId);
      } else {
        petChat.completeStreamWithoutReply(assistantId);
      }
      return !petChat.streamFailedRef.current;
    } catch (error) {
      if (!isCurrentRequest()) {
        return false;
      }
      petChat.clearStreamWatchdogTimer();
      tts.waitingCue.stop("send_failed");
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
      if (activeChatRequestIdRef.current === requestId) {
        petChat.clearStreamWatchdogTimer();
        streamingRef.current = false;
        setStreaming(false);
        streamAbort.current = null;
        activeChatRequestIdRef.current = null;
        petChat.finishStream();
      }
    }
  }

  async function sendPetMessage(event: FormEvent) {
    event.preventDefault();
    await sendChatText(buildPetInputIntentMessage(petInputMode, petChat.input), () => petChat.setInput(""), {
      displayText: displayTextForInputMode(petInputMode, petChat.input),
    });
  }

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
        .slice(0, localAgentActionCacheLimit);
    });
  }

  async function loadAgentActions(options: { silent?: boolean; signal?: AbortSignal } = {}) {
    setAgentActionsStatus("loading");
    setAgentActionsError("");
    if (!options.silent) {
      setNotice(null);
    }
    try {
      const response = await api.listAgentActions(agentActionMemoryReviewLimit, null, options.signal);
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
    const targets = action.target_paths.length > 0 ? `\n\n影响文件：${action.target_paths.join("、")}` : "";
    const confirmed = window.confirm(
      `确认撤回“${action.title}”吗？\n\n撤回会通过本机服务恢复这次整理前的文件快照，并留下新的活动记录。${targets}`,
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
          .slice(0, localAgentActionCacheLimit);
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
      setNotice({
        tone: "success",
        message: `已撤回：${response.action.title}。记忆页会显示新的撤回记录，关联文件已按本机快照同步。`,
      });
      void loadAgentActions({ silent: true });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "撤回自动整理活动失败") });
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
        message: "当前浏览器预览不能打开本地保存文件；请在 Electron 桌面端使用该操作。",
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
        message: `无法打开保存目标：${result.reason || result.status}。`,
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "打开保存目标失败") });
    }
  }

  function openArtifactTarget(mode: "memory" | "world", relativePath?: string) {
    setWindowMode(mode);
    if (relativePath) {
      void revealAgentActionTarget(relativePath, "open");
    }
  }

  function fillKnowledgeSnippetTrial() {
    setWindowMode("world");
    onWikiDraftChange({
      title: "决策记忆",
      content:
        "决策记忆会把项目选择、理由和后续任务放在一起，方便之后复盘时解释为什么选择了某条路径。",
      source_type: "concept",
      source_uri: "trial:decision-memory",
      target_path: "Wiki/Concepts/Decision-Memory.md",
      tags: ["concept", "trial"],
    });
    setWikiTagInput("concept, trial");
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
    return (
      <AgentActivityEntryRenderer
        key={entry.id}
        entry={entry}
        revertingAgentActionIds={revertingAgentActionIds}
        memoryProposalActionIds={proposalActionIds}
        continuityActionIds={continuityActionIds}
        formatIssueSeverity={formatIssueSeverity}
        onRevertAgentAction={(action) => void revertAgentAction(action)}
        onRevealAgentActionTarget={(relativePath, mode) => void revealAgentActionTarget(relativePath, mode)}
        onActOnMemoryProposal={(proposalId, action) => void actOnProposal(proposalId, action)}
        onActOnContinuityProposal={(proposalId, action) => void actOnContinuityProposal(proposalId, action)}
        onConfirmChatWikiProposal={confirmChatWikiProposal}
        onRejectChatWikiProposal={rejectChatWikiProposal}
        onToggleChatWikiProposalTarget={toggleChatWikiProposalTarget}
        onApplyChatWikiProposal={(messageId, proposalId) => void applyChatWikiProposal(messageId, proposalId)}
      />
    );
  }

  function stopStreaming() {
    petChat.clearStreamWatchdogTimer();
    tts.waitingCue.stop("stream_stopped");
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
          message: `陪伴状态已刷新：${state.items.length} 个已确认状态，${proposalsResponse.proposals.length} 个待确认话题。`,
        });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (!options.silent) {
        setNotice({ tone: "error", message: describeError(error, "陪伴状态加载失败") });
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
            ? "已记住，下次可以自然接着聊；只进入本机陪伴状态，未写入本地文件。"
            : "已跳过，这个话题不会进入陪伴提示或角色状态。",
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "下次接着聊操作失败") });
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
      "这会清空本机桌宠的聊天记录、长期记忆、陪伴状态、任务、保存位置绑定、索引缓存、模型配置和本地密钥。不会删除你选择的本地文件。确定要重置为初始化状态吗？",
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

  function scrollToWorkflowTarget(targetId?: string) {
    if (!targetId) {
      return;
    }
    document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const hasConnection = sidecarStatus?.state === "ready" || health?.status === "ok";
  const proactiveHabitLoopBlocked =
    streaming ||
    petChat.inputVisible ||
    petChat.bubble.visible ||
    petWindow.petShortcutsVisible ||
    tts.active;
  useProactiveHabitLoop({
    api,
    enabled: windowMode === "pet" && hasConnection,
    frequency: automationSettingsDraft.proactive_trigger_frequency,
    blocked: proactiveHabitLoopBlocked,
    onTrigger: (response) => {
      const candidate = response.candidate;
      if (!candidate) {
        return;
      }
      petChat.showBubble({
        title: candidate.title,
        message: candidate.message,
        tone: "tool",
        phase: "complete",
      });
      petChat.scheduleHide(11000);
    },
  });
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
  const allAgentActivityEntries = agentActivityEntries;
  const pendingManualActivityCount = agentActivityEntries.filter((entry) => entry.kind !== "agent_action").length;
  const automaticActivityCount = agentActivityEntries.filter(
    (entry) => entry.kind === "agent_action" && !isAttentionAgentAction(entry.action),
  ).length;
  const hasAgentActivity = agentActivityEntries.length > 0;
  const coreWorkflowItems = buildControlWorkflowItems({
    agentModelDrafts,
    agentModelTestResults,
    hasVaultInitialized,
    hasIndexSignal,
    lastIndexRun,
    hasAgentEventSignal,
    streaming,
    latestChatEvent,
    latestCitation,
    latestCitationTargetId,
    pendingManualActivityCount,
    hasAgentActivity,
    hasMemoryConfirmed,
    automaticActivityCount,
    hasContinuityState,
    pendingContinuityCount,
    continuityStateItemCount: continuityState?.items.length ?? 0,
  });
  const petStage = getPetStageView({
    connected: hasConnection,
    streaming,
    searchResultCount: searchResults.length,
    pendingProposalCount,
    taskCount: recentTaskStageActive ? Math.max(tasks.length, 1) : 0,
    diagnosticsReady: hasDiagnosticsExport,
    continuityState,
    continuitySignal: activeContinuitySignal,
  });
  const petReplyActionKey = hasConnection ? resolvePetReplyActionKey(latestAssistantMessage) : null;
  const petReplyActionTriggerKey =
    petReplyActionKey && latestAssistantMessage
      ? [
          latestAssistantMessage.id,
          latestAssistantMessage.status || "",
          (latestAssistantMessage.live2d_action_hints || []).join("|"),
        ].join(":")
      : null;

  const refreshActivity = () => {
    void loadAgentActions();
    void loadPendingProposals({ silent: true });
    void loadContinuity({ silent: true });
  };
  const firstUseOnboardingPanel = useFirstUseOnboarding({
    connected: hasConnection,
    streaming,
    windowMode,
    onNotice: setNotice,
    onSendMessage: (message, options) => sendChatText(message, () => undefined, options),
  });
  const connectionPanel = (
    <ConnectionManagementPanel
      settings={settings}
      onSettingsChange={setSettings}
      onSaveSettings={persistSettings}
      onCheckHealth={() => void checkHealth()}
      checkingHealth={checkingHealth}
      isElectronRuntime={isElectronRuntime}
      health={health}
      businessAuthStatus={businessAuthStatus}
      businessAuthMessage={businessAuthMessage}
      resettingLocalState={resettingLocalState}
      onResetLocalState={() => void resetLocalState()}
    />
  );
  const wikiWorkflowPanel = (
    <WikiManagementPanels
        workflow={{
          draft: wikiDraft,
          tagInput: wikiTagInput,
          linkInput: wikiLinkInput,
          approvedTargetsInput: wikiApprovedTargetsInput,
          reviewForceRefresh: wikiReviewForceRefresh,
          preview: wikiPreview,
          reviewResult: wikiReviewResult,
          applyResult: wikiApplyResult,
          lintResult: wikiLintResult,
          diagnosticsQueue: wikiDiagnosticsQueue,
          schemaStatus: wikiSchemaStatus,
          indexStatus: wikiIndexStatus,
          logStatus: wikiLogStatus,
          coreStatus: wikiCoreStatus,
          coreError: wikiCoreError,
          archiveHistory: wikiArchiveHistory,
          archiveHistoryStatus: wikiArchiveHistoryStatus,
          archiveHistoryError: wikiArchiveHistoryError,
          openedArchive: wikiOpenedArchive,
          openingArchiveId: wikiOpeningArchiveId,
          companionContextReports,
          companionContextReportStatus,
          companionContextReportError,
          lastWikiArchiveId,
          workflowAction: wikiWorkflowAction,
          latestArchiveMessage,
          latestKnowledgeCitationCount,
          archiveHistorySummary: wikiArchiveHistorySummary,
          archiveHistoryLoading: wikiArchiveHistoryLoading,
          lintIssueCount: wikiLintIssueCount,
          formatIssueSeverity,
          onDraftChange: onWikiDraftChange,
          onTagInputChange: setWikiTagInput,
          onLinkInputChange: setWikiLinkInput,
          onApprovedTargetsInputChange: setWikiApprovedTargetsInput,
          onReviewForceRefreshChange: setWikiReviewForceRefresh,
          onPreview: (event) => void previewWikiIngest(event),
          onReview: () => void reviewWikiIngest(),
          onApply: () => void applyWikiIngest(),
          onArchiveLatestQuery: () => void archiveLatestWikiQuery(),
          onSynthesize: () => void synthesizeWiki(),
          onRunLint: () => void runWikiLint(),
          onLoadDiagnosticsQueue: () => void loadWikiDiagnosticsQueue(),
          onLoadArchiveHistory: () => void loadWikiArchiveHistory(),
          onLoadCoreStatus: () => void loadWikiCoreStatus(),
          onUseReviewRecommendedTargets: useWikiReviewRecommendedTargets,
          onOpenArchive: (archiveId) => void openWikiQueryArchive(archiveId),
        }}
        browser={{
          vaultConfigured: hasVaultInitialized,
          indexRequired: hasVaultInitialized && !hasIndexSignal && !wikiIndexStatus,
          schemaStatus: wikiSchemaStatus,
          indexStatus: wikiIndexStatus,
          logStatus: wikiLogStatus,
          lintResult: wikiLintResult,
          diagnosticsQueue: wikiDiagnosticsQueue,
          archiveHistory: wikiArchiveHistory,
          archiveHistoryStatus: wikiArchiveHistoryStatus,
          archiveHistoryError: wikiArchiveHistoryError,
          archiveHistoryLoading: wikiArchiveHistoryLoading,
          coreStatus: wikiCoreStatus,
          coreError: wikiCoreError,
          workflowAction: wikiWorkflowAction,
          openingArchiveId: wikiOpeningArchiveId,
          formatIssueSeverity,
          onLoadCoreStatus: () => void loadWikiCoreStatus(),
          onLoadArchiveHistory: () => void loadWikiArchiveHistory(),
          onLoadDiagnosticsQueue: () => void loadWikiDiagnosticsQueue(),
          onOpenArchive: (archiveId) => void openWikiQueryArchive(archiveId),
          onTryKnowledgeSnippet: fillKnowledgeSnippetTrial,
        }}
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
        ttsSettingsDraft={ttsSettingsDraft}
        ttsSettingsSaveStatus={ttsSettingsSaveStatus}
        ttsSettingsStatus={settingsStatus?.tts_settings}
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
        onUpdateTtsSettingsDraft={updateTtsSettingsDraft}
        onSaveTtsSettings={(apiKey) => void saveTtsSettings(apiKey)}
        onClearTtsCache={() => void clearTtsCache()}
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
  const isStageHostWindow = desktopHostMode === "stage";
  const stageView = (
    <StageView
      connected={hasConnection}
      streaming={streaming}
      bubble={petChat.bubble}
      onSendChat={sendChatText}
      onStopStreaming={stopStreaming}
      onPreviousPage={petChat.retreatPageManually}
      onAdvancePage={petChat.advancePageManually}
      onPausePaging={petChat.pausePaging}
      onResumePaging={petChat.resumePaging}
      ttsSpeaking={tts.speaking}
      active={!isStageHostWindow || windowMode === "stage"}
      api={api}
    />
  );

  if (windowMode !== "pet" && windowMode !== "control" && windowMode !== "stage") {
    return (
      <DesktopFeatureRoutes
        windowMode={windowMode}
        isStageHostWindow={isStageHostWindow}
        stageView={stageView}
        agentWorkspaceProps={{ api }}
        chatWindowProps={{
          input: controlInput,
          messages,
          connected: hasConnection,
          streaming,
          mode: petInputMode,
          modes: petInputModes,
          onInputChange: setControlInput,
          onModeChange: setPetInputMode,
          onSend: (event) => {
            event.preventDefault();
            void sendChatText(buildPetInputIntentMessage(petInputMode, controlInput), () => setControlInput(""), {
              displayText: displayTextForInputMode(petInputMode, controlInput),
            });
          },
          onStopStreaming: stopStreaming,
          revertingActionIds: revertingAgentActionIds,
          onRevertAgentAction: (action) => void revertAgentAction(action),
          onOpenTask: () => setWindowMode("agent"),
          onOpenMemory: () => setWindowMode("memory"),
          onOpenWiki: (path) => openArtifactTarget("world", path),
          onOpenReport: (path) => openArtifactTarget("memory", path),
        }}
        memoryWindowProps={{
          api,
          loading: agentActionsStatus === "loading" || loadingProposals || loadingContinuity,
          error: agentActionsError,
          entries: agentActivityEntries,
          memorySearchQuery: searchQuery,
          memorySearchStatus: searchStatus,
          memorySearchResults: searchResults,
          memoryLastSearchQuery: lastSearchQuery,
          onMemorySearchQueryChange: setSearchQuery,
          onRunMemorySearch: (event) => void runMemorySearch(event),
          memoryProposalDraft: proposalDraft,
          memoryProposals: proposals,
          memoryProposalActionIds: proposalActionIds,
          loadingMemoryProposals: loadingProposals,
          onMemoryProposalDraftChange: updateProposalDraft,
          onCreateMemoryProposal: (event) => void createProposal(event),
          onActOnMemoryProposal: (proposalId, action) => void actOnProposal(proposalId, action),
          onLoadMemoryProposals: () => void loadPendingProposals(),
          onRefresh: refreshActivity,
          renderEntry: renderAgentActivityEntry,
        }}
        growthWindowProps={{ api }}
        connectionPanel={connectionPanel}
        wikiWorkflowPanel={wikiWorkflowPanel}
        settingsPanel={settingsPanel}
      />
    );
  }

  if (windowMode === "pet") {
    return (
      <PetWindow
        shellRef={petWindow.shellRef}
        hitboxStyle={petHitboxStyle}
        shortcutButtonStyles={petShortcutButtonStyles}
        hitboxDebug={petHitboxDebug}
        petChat={petChat}
        petDragging={petWindow.petDragging}
        petDragDirection={petWindow.petDragDirection}
        petStage={petStage}
        petCanvasRef={petCanvasRef}
        ttsSpeaking={tts.speaking}
        actionKeyOverride={petReplyActionKey}
        actionTriggerKey={petReplyActionTriggerKey}
        petInputMode={petInputMode}
        petInputModes={petInputModes}
        connected={hasConnection}
        streaming={streaming}
        petShortcutsVisible={petWindow.petShortcutsVisible}
        petShortcutMotion={petWindow.petShortcutMotion}
        onBeginPetDrag={petWindow.beginPetDrag}
        onMovePetDrag={petWindow.movePetDrag}
        onEndPetDrag={petWindow.endPetDrag}
        onTogglePetShortcuts={petWindow.togglePetShortcuts}
        onCompletePetEntryHint={petWindow.completePetEntryHint}
        onOpenStage={() => {
          const openStage = window.agentDesktop?.openStage?.();
          if (openStage) {
            void openStage.catch(() => undefined);
          }
        }}
        onOpenPetInputMode={petWindow.openPetInputMode}
        onOpenPetShortcutStage={petWindow.openPetShortcutStage}
        onQuitApp={petWindow.quitAppFromShortcut}
        onSendPetMessage={sendPetMessage}
        onStopStreaming={stopStreaming}
        onFinishPetShortcutMotion={petWindow.finishPetShortcutMotion}
      />
    );
  }

  return (
    <ControlDashboard
      sidecarStatus={sidecarStatus}
      health={health}
      notice={notice}
      ttsActive={tts.active}
      api={api}
      halfbodyPortraitRef={halfbodyPortraitRef}
      firstUseOnboardingPanel={firstUseOnboardingPanel}
      controlInput={controlInput}
      hasConnection={hasConnection}
      streaming={streaming}
      onControlInputChange={setControlInput}
      onSubmitControlChat={(event) => {
        event.preventDefault();
        void sendChatText(controlInput, () => setControlInput(""));
      }}
      onStopStreaming={stopStreaming}
      pendingManualActivityCount={pendingManualActivityCount}
      agentActionsStatus={agentActionsStatus}
      hasAgentActivity={hasAgentActivity}
      recentAgentActivityCount={allAgentActivityEntries.length}
      loadingProposals={loadingProposals}
      loadingContinuity={loadingContinuity}
      agentActionsError={agentActionsError}
      activityItems={allAgentActivityEntries.map((entry) => renderAgentActivityEntry(entry))}
      onRefreshActivity={refreshActivity}
      messages={messages}
      agentActivityEntries={agentActivityEntries}
      tasks={tasks}
      chatMessageListProps={{
        messages: recentControlMessages,
        revertingActionIds: revertingAgentActionIds,
        onRevertAgentAction: (action) => void revertAgentAction(action),
        onOpenTask: () => setWindowMode("agent"),
        onOpenMemory: () => setWindowMode("memory"),
        onOpenWiki: (path) => openArtifactTarget("world", path),
        onOpenReport: (path) => openArtifactTarget("memory", path),
      }}
      workflowItems={coreWorkflowItems}
      taskPanelProps={{
        tasks,
        lastReminderNotification,
        onLocateTask: scrollToWorkflowTarget,
      }}
      continuityState={continuityState}
      pendingContinuityCount={pendingContinuityCount}
      onLoadContinuity={() => void loadContinuity()}
      onLocateWorkflowTarget={scrollToWorkflowTarget}
      modelStatusLabel={
        settingsStatus?.model_configured
          ? settingsStatus.chat_model || "已配置"
          : hasConnection
            ? "待配置"
            : "连接中"
      }
      knowledgeStatusLabel={hasVaultInitialized ? (hasIndexSignal ? "已就绪" : "待索引") : "未绑定"}
      advancedTools={{
        connectionPanel,
        wikiWorkflowPanel,
        settingsPanel,
      }}
    />
  );
}


function readTtsPlaybackDurationMs(item: unknown): number | null {
  const record = item && typeof item === "object" ? (item as Record<string, unknown>) : null;
  const synthesis = record?.synthesis && typeof record.synthesis === "object"
    ? (record.synthesis as Record<string, unknown>)
    : null;
  const result = record?.result && typeof record.result === "object" ? (record.result as Record<string, unknown>) : null;

  for (const value of [record?.durationMs, synthesis?.durationMs, result?.durationMs]) {
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
      return value;
    }
  }
  return null;
}



function clearRendererResettableState(): void {
  for (const key of [
    "agent-pet.base-url",
    firstUseOnboardingStorageKey,
    petEntryHintStorageKey,
    wikiArchiveCandidateStorageKey,
  ]) {
    void writeRendererUiState(key, null);
  }
}

function findCitationTargetId(citation: Citation, results: MemorySearchResult[]): string | undefined {
  const matched = results.find((result) =>
    citation.chunk_id
      ? result.chunk_id === citation.chunk_id
      : result.relative_path === citation.relative_path,
  );
  return matched ? `search-result-${matched.chunk_id}` : undefined;
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
    return `没有找到“${query}”的结果。最近已有整理记录，请换一个关键词，或确认目标本地文件已在当前资料文件夹中。`;
  }
  return `没有找到“${query}”的结果。当前页面还没有整理完成记录，请先设置资料文件夹或点击“刷新”后再搜索。`;
}

export default App;
