import {
  Bell,
  Bot,
  Check,
  CircleAlert,
  Database,
  FileDown,
  FolderOpen,
  HeartPulse,
  KeyRound,
  ListChecks,
  Loader2,
  MemoryStick,
  MessageSquareText,
  RefreshCw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent, PointerEvent, ReactNode, RefObject } from "react";
import type {
  AgentModelId,
  ChatMessage,
  ChatContinuityProposal,
  ChatContinuitySignal,
  ChatWikiProposal,
  ChatWikiProposalState,
  Citation,
  ConnectionSettings,
  ContinuityProposal,
  ContinuityProposalKind,
  ContinuityProposalStatus,
  ContinuityStateResponse,
  DesktopSidecarStatus,
  DiagnosticsExportResponse,
  HealthResponse,
  MemoryProposal,
  MemoryProposalDraft,
  MemoryProposalType,
  MemorySearchResult,
  ModelTestResponse,
  SettingsStatusResponse,
  TaskDraft,
  TaskItem,
  WikiIngestApplyResponse,
  WikiIngestPreviewResponse,
  WikiIngestRequest,
  WikiIngestReviewResponse,
  WikiIndexResponse,
  WikiLintRunResponse,
  WikiLogResponse,
  WikiQueryArchiveDetailResponse,
  WikiQueryArchiveHistoryItem,
  WikiQueryArchiveResponse,
  WikiSchemaStatus,
  WikiSynthesizeResponse,
  WikiPageResponse,
} from "./types";
import { ApiClient, ApiError, loadConnectionSettings, saveConnectionSettings } from "./services/apiClient";
import { DesktopApi } from "./services/desktopApi";
import {
  createInitialLive2DAssetInfo,
  createLive2DAssetInfo,
  createLive2DRuntimeBoundary,
  createRendererMountContext,
  defaultLive2DModelOption,
  initialLive2DAssetInfo,
  live2DIconPath,
  live2DManifestPath,
  live2dModelCatalogPath,
  mountLive2DRendererBoundary,
} from "./services/live2dRuntime";
import type {
  Live2DAssetInfo,
  Live2DModelCatalog,
  Live2DModelManifest,
  Live2DModelOption,
  Live2DRendererDiagnostics,
  Live2DRendererMode,
  Live2DRuntimeBoundary,
  Live2DRuntimeHandle,
} from "./services/live2dRuntime";
import { fetchSseStream } from "./services/sse";
import type { SseEvent } from "./services/sse";
import { getPetBubblePageDelay, paginatePetBubbleReply } from "./services/petBubblePagination";
import {
  agentLabel,
  agentModelCountLabel,
  agentModelDefinitions,
  defaultAgentModelDrafts,
  hasUnsavedAgentModelDraft,
  isSupportedProviderDraft,
  mergeAgentModelStatus,
  normalizeProviderDraft,
} from "./services/agentModelDrafts";
import type { AgentModelDraft } from "./services/agentModelDrafts";
import petHitboxConfig from "../pet-hitbox.json";

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type Live2DStageState =
  | "disconnected"
  | "idle"
  | "presence"
  | "reflective"
  | "thinking"
  | "memory"
  | "confirming"
  | "tasking"
  | "diagnosed";

type Live2DStageView = {
  state: Live2DStageState;
  label: string;
  mood: string;
  message: string;
  hint: string;
};

type Live2DRenderLifecycleStatus = "loading" | "mounted" | "preview" | "failed";
type DesktopWindowMode = "pet" | "control";
type AsyncStatus = "idle" | "loading" | "success" | "empty" | "error";

type LastIndexRun = {
  vaultId: string;
  jobId: string;
  status: string;
  filesSeen?: number;
  filesIndexed?: number;
};

type WikiWorkflowAction = "preview" | "review" | "apply" | "archive" | "synthesize" | "lint";
type ChatWikiApplyResponse = WikiIngestApplyResponse | WikiQueryArchiveResponse | WikiSynthesizeResponse | WikiLintRunResponse;

type WikiArchiveCandidate = {
  conversation_id: string | null;
  message: ChatMessage;
  question?: string | null;
  updated_at: string;
};

type WikiWorkflowDraft = WikiIngestRequest & {
  target_path?: string | null;
  section?: string | null;
  write_report: boolean;
  allow_mixed_sources: boolean;
  archive_id?: string | null;
  archive_question?: string | null;
  archive_answer?: string | null;
  archive_citations?: MemorySearchResult[];
};

type ReminderNotificationSummary = {
  status: "idle" | "shown" | "duplicate" | "unsupported" | "failed";
  detail: string;
};

type PetBubbleTone = "thinking" | "reply" | "tool" | "error" | "reminder";
type PetBubblePhase = "idle" | "thinking" | "speaking" | "complete" | "fading";
const petStreamFinalTimeoutMs = 45000;
const petStreamFinalWatchdogDelayMs = 18000;

type PetBubbleState = {
  visible: boolean;
  title: string;
  message: string;
  tone: PetBubbleTone;
  phase: PetBubblePhase;
  continueHint?: string;
};

type CoreWorkflowItem = {
  label: string;
  status: "done" | "active" | "blocked";
  detail: string;
  targetId?: string;
};

type PetQuickAction = {
  id: string;
  label: string;
  targetId: string;
  icon: ReactNode;
};

type Live2DStageRuntimeDirective = {
  expression: string;
  motionGroup: string;
  motionIndex: number;
  petHint: string;
  controlSummary: string;
};

const memoryTypes: MemoryProposalType[] = ["preference", "fact", "event", "goal", "rule"];
const defaultMemoryTargetPath = "Inbox/Pending Memories.md";
const defaultWikiArchiveTargetPath = "Wiki/Reports/Query-Archive.md";
const wikiArchiveCandidateStorageKey = "agent-pet.wiki-archive-candidate";
const wikiArchiveCandidateChannelName = "agent-pet.wiki-archive-candidate";
const live2dModelSelectionStorageKey = "agent-pet.live2d-model-id";
const live2dModelSelectionChannelName = "agent-pet.live2d-model-selection";
const memoryTypeLabels: Record<MemoryProposalType, string> = {
  preference: "偏好",
  fact: "事实",
  event: "事件",
  goal: "目标",
  rule: "规则",
};

function detectDesktopWindowMode(): DesktopWindowMode {
  return window.location.hash.replace("#", "") === "pet" ? "pet" : "control";
}

function formatAgentStage(stage: unknown): string | null {
  if (typeof stage !== "string" || !stage) {
    return null;
  }
  const labels: Record<string, string> = {
    route: "路由",
    semantic_analysis: "语义分析",
    personal_memory_retrieval: "翻记忆本",
    daily_chat_retrieval: "查聊天日记",
    daily_chat_fallback: "补查聊天日记",
    knowledge_base_retrieval: "查资料库",
    multi_source_retrieval: "查记忆和资料",
    chat_generation: "生成回复",
    background_memory: "后台保存记忆",
  };
  return labels[stage] || stage;
}

function isWikiProposalStreamEvent(eventName: string): boolean {
  const normalized = eventName.toLowerCase();
  return normalized.includes("wiki") && normalized.includes("proposal");
}

function pickPayloadString(payload: Record<string, unknown> | null, keys: string[]): string | null {
  if (!payload) {
    return null;
  }
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function truncateEventDetail(value: string, maxLength = 360): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized;
}

function isSensitivePayloadKey(key: string): boolean {
  const normalized = key.toLowerCase();
  return (
    normalized.includes("authorization") ||
    normalized.includes("token") ||
    normalized.includes("api_key") ||
    normalized.includes("password") ||
    normalized.includes("secret")
  );
}

function redactStreamPayload(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.slice(0, 5).map(redactStreamPayload);
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, entry]) => [
      key,
      isSensitivePayloadKey(key) ? "[redacted]" : redactStreamPayload(entry),
    ]),
  );
}

function formatStreamPayloadPreview(payload: Record<string, unknown> | null, rawData: string): string {
  if (payload) {
    try {
      return truncateEventDetail(JSON.stringify(redactStreamPayload(payload)));
    } catch {
      return "payload 无法序列化";
    }
  }
  return truncateEventDetail(rawData);
}

function formatWikiProposalEventDetail(
  eventName: string,
  payload: Record<string, unknown> | null,
  rawData: string,
): string {
  const summary = pickPayloadString(payload, ["summary", "message", "description"]);
  const proposalId = pickPayloadString(payload, ["proposal_id", "id", "run_id"]);
  const title = pickPayloadString(payload, ["title", "page_title"]);
  const target = pickPayloadString(payload, ["target_path", "relative_path", "path"]);
  const operation = pickPayloadString(payload, ["operation", "action"]);
  const status = pickPayloadString(payload, ["status"]);
  const pagePlanCount = Array.isArray(payload?.page_plans) ? payload.page_plans.length : null;
  const parts = [
    summary,
    title ? `标题 ${title}` : null,
    target ? `目标 ${target}` : null,
    operation ? `操作 ${operation}` : null,
    status ? `状态 ${formatTaskStatus(status)}` : null,
    proposalId ? `ID ${proposalId}` : null,
    pagePlanCount !== null ? `${pagePlanCount} 个页面计划` : null,
  ].filter(Boolean);

  if (parts.length > 0) {
    return truncateEventDetail(`${parts.join("；")}；需确认后才会写入 Vault。`);
  }

  const payloadPreview = formatStreamPayloadPreview(payload, rawData);
  return payloadPreview
    ? `收到 ${eventName}：${payloadPreview}；需确认后才会写入 Vault。`
    : `收到 ${eventName} 事件；需确认后才会写入 Vault。`;
}

function pickPayloadStringArray(payload: Record<string, unknown> | null, key: string): string[] {
  const value = payload?.[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return uniqueCompactList(value.map((item) => (typeof item === "string" ? item : null)));
}

function normalizeWikiProposalFindings(value: unknown): ChatWikiProposal["findings"] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    .map((item) => ({
      severity: typeof item.severity === "string" ? item.severity : "info",
      code: typeof item.code === "string" && item.code.trim() ? item.code.trim() : "wiki_review_finding",
      message: typeof item.message === "string" ? item.message : "",
      target_path: typeof item.target_path === "string" ? item.target_path : null,
    }));
}

function normalizeChatWikiProposal(payload: Record<string, unknown> | null): ChatWikiProposal | null {
  if (!payload) {
    return null;
  }
  const runId = pickPayloadString(payload, ["run_id"]);
  const reviewId = pickPayloadString(payload, ["review_id"]);
  const sourceId = pickPayloadString(payload, ["source_id"]);
  const sourceHash = pickPayloadString(payload, ["source_hash"]);
  const targetPaths = pickPayloadStringArray(payload, "target_paths");
  const recommendedTargets = pickPayloadStringArray(payload, "recommended_targets");
  const selectedTargets = recommendedTargets.length > 0 ? recommendedTargets : targetPaths;
  const proposalType = pickPayloadString(payload, ["proposal_type"]) || "ingest";
  const title = pickPayloadString(payload, ["title", "page_title"]) || "Vault proposal";
  const id = reviewId || runId || sourceId || sourceHash || crypto.randomUUID();

  return {
    id,
    proposal_type: proposalType,
    state: "pending",
    backend_status: pickPayloadString(payload, ["status"]),
    title,
    run_id: runId,
    agent_run_id: pickPayloadString(payload, ["agent_run_id"]),
    source_id: sourceId,
    source_hash: sourceHash,
    review_id: reviewId,
    review_status: pickPayloadString(payload, ["review_status"]),
    summary: pickPayloadString(payload, ["summary"]) || "",
    review_summary: pickPayloadString(payload, ["review_summary"]) || "",
    target_paths: targetPaths,
    recommended_targets: recommendedTargets,
    selected_targets: selectedTargets,
    findings: normalizeWikiProposalFindings(payload.findings),
    markdown_preview: pickPayloadString(payload, ["markdown_preview"]) || "",
    source_message_id: pickPayloadString(payload, ["source_message_id"]),
    write_report: typeof payload.write_report === "boolean" ? payload.write_report : null,
    lint_summary:
      payload.lint_summary && typeof payload.lint_summary === "object" && !Array.isArray(payload.lint_summary)
        ? (payload.lint_summary as Record<string, unknown>)
        : undefined,
    error: null,
    apply_result: null,
    updated_at: new Date().toISOString(),
  };
}

function mergeChatWikiProposal(
  existing: ChatWikiProposal | undefined,
  incoming: ChatWikiProposal,
): ChatWikiProposal {
  if (!existing) {
    return incoming;
  }
  return {
    ...existing,
    ...incoming,
    state: existing.state === "pending" ? incoming.state : existing.state,
    selected_targets: existing.selected_targets,
    error: existing.error,
    apply_result: existing.apply_result,
  };
}

function getWikiProposalTargetOptions(proposal: ChatWikiProposal): string[] {
  return uniqueCompactList([
    ...proposal.recommended_targets,
    ...proposal.target_paths,
    ...proposal.selected_targets,
  ]);
}

function isSupportedChatWikiProposalType(proposalType: string): proposalType is "ingest" | "query_archive" | "synthesize" | "lint" {
  return proposalType === "ingest" || proposalType === "query_archive" || proposalType === "synthesize" || proposalType === "lint";
}

function formatChatWikiProposalState(state: ChatWikiProposalState): string {
  const labels: Record<ChatWikiProposalState, string> = {
    pending: "待确认",
    confirmed: "已确认",
    rejected: "已拒绝",
    applying: "正在应用",
    applied: "已应用",
    failed: "应用失败",
  };
  return labels[state] || state;
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
} as CSSProperties;

function App() {
  const [settings, setSettings] = useState<ConnectionSettings>(() => loadConnectionSettings());
  const [sidecarStatus, setSidecarStatus] = useState<DesktopSidecarStatus | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [checkingHealth, setCheckingHealth] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [petInput, setPetInput] = useState("");
  const [controlInput, setControlInput] = useState("");
  const [petInputVisible, setPetInputVisible] = useState(false);
  const [petBubble, setPetBubble] = useState<PetBubbleState>({
    visible: false,
    title: "",
    message: "",
    tone: "thinking",
    phase: "idle",
  });
  const [petReplyText, setPetReplyText] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MemorySearchResult[]>([]);
  const [searchStatus, setSearchStatus] = useState<AsyncStatus>("idle");
  const [lastSearchQuery, setLastSearchQuery] = useState("");
  const [proposalDraft, setProposalDraft] = useState<MemoryProposalDraft>({
    type: "fact",
    content: "",
    target_path: defaultMemoryTargetPath,
  });
  const [proposals, setProposals] = useState<MemoryProposal[]>([]);
  const [taskDraft, setTaskDraft] = useState<TaskDraft>({
    title: "",
    description: "",
    due_at: "",
    remind_at: "",
    timezone: formatTimezoneForUser(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"),
  });
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsExportResponse | null>(null);
  const [vaultId, setVaultId] = useState<string | null>(null);
  const [vaultPath, setVaultPath] = useState("");
  const [lastIndexRun, setLastIndexRun] = useState<LastIndexRun | null>(null);
  const [wikiDraft, setWikiDraft] = useState<WikiWorkflowDraft>({
    title: "",
    content: "",
    source_type: "manual",
    source_uri: "",
    max_pages: 15,
    target_path: "",
    section: "",
    tags: [],
    links: [],
    write_report: true,
    allow_mixed_sources: false,
    archive_id: null,
    archive_question: null,
    archive_answer: null,
    archive_citations: [],
  });
  const [wikiTagInput, setWikiTagInput] = useState("desktop,wiki");
  const [wikiLinkInput, setWikiLinkInput] = useState("");
  const [wikiApprovedTargetsInput, setWikiApprovedTargetsInput] = useState("");
  const [wikiReviewForceRefresh, setWikiReviewForceRefresh] = useState(false);
  const [wikiPreview, setWikiPreview] = useState<WikiIngestPreviewResponse | null>(null);
  const [wikiReviewResult, setWikiReviewResult] = useState<WikiIngestReviewResponse | null>(null);
  const [wikiApplyResult, setWikiApplyResult] = useState<WikiIngestApplyResponse | WikiQueryArchiveResponse | WikiSynthesizeResponse | null>(null);
  const [wikiLintResult, setWikiLintResult] = useState<WikiLintRunResponse | null>(null);
  const [wikiSchemaStatus, setWikiSchemaStatus] = useState<WikiSchemaStatus | null>(null);
  const [wikiIndexStatus, setWikiIndexStatus] = useState<WikiIndexResponse | null>(null);
  const [wikiLogStatus, setWikiLogStatus] = useState<WikiLogResponse | null>(null);
  const [wikiCoreStatus, setWikiCoreStatus] = useState<AsyncStatus>("idle");
  const [wikiCoreError, setWikiCoreError] = useState("");
  const [wikiArchiveHistory, setWikiArchiveHistory] = useState<WikiQueryArchiveHistoryItem[]>([]);
  const [wikiArchiveHistoryStatus, setWikiArchiveHistoryStatus] = useState<AsyncStatus>("idle");
  const [wikiArchiveHistoryError, setWikiArchiveHistoryError] = useState("");
  const [wikiOpenedArchive, setWikiOpenedArchive] = useState<WikiQueryArchiveDetailResponse | null>(null);
  const [wikiOpeningArchiveId, setWikiOpeningArchiveId] = useState<string | null>(null);
  const [lastWikiArchiveId, setLastWikiArchiveId] = useState<string | null>(null);
  const [wikiWorkflowAction, setWikiWorkflowAction] = useState<WikiWorkflowAction | null>(null);
  const [wikiArchiveCandidate, setWikiArchiveCandidate] = useState<WikiArchiveCandidate | null>(() =>
    loadWikiArchiveCandidate(),
  );
  const [agentModelDrafts, setAgentModelDrafts] = useState<AgentModelDraft[]>(() => defaultAgentModelDrafts());
  const [agentModelTestResults, setAgentModelTestResults] = useState<Record<string, ModelTestResponse | undefined>>({});
  const [savingAgentModelIds, setSavingAgentModelIds] = useState<Set<string>>(() => new Set());
  const [testingAgentModelIds, setTestingAgentModelIds] = useState<Set<string>>(() => new Set());
  const [settingsStatus, setSettingsStatus] = useState<SettingsStatusResponse | null>(null);
  const [loadingSettingsStatus, setLoadingSettingsStatus] = useState(false);
  const [businessAuthStatus, setBusinessAuthStatus] = useState<"unknown" | "checking" | "ready" | "unauthorized" | "error">("unknown");
  const [businessAuthMessage, setBusinessAuthMessage] = useState("尚未检查业务接口鉴权。");
  const [loadingProposals, setLoadingProposals] = useState(false);
  const [proposalActionIds, setProposalActionIds] = useState<Set<string>>(() => new Set());
  const [continuityState, setContinuityState] = useState<ContinuityStateResponse | null>(null);
  const [continuityProposals, setContinuityProposals] = useState<ContinuityProposal[]>([]);
  const [latestContinuitySignal, setLatestContinuitySignal] = useState<ChatContinuitySignal | null>(null);
  const [loadingContinuity, setLoadingContinuity] = useState(false);
  const [continuityActionIds, setContinuityActionIds] = useState<Set<string>>(() => new Set());
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [taskActionIds, setTaskActionIds] = useState<Set<string>>(() => new Set());
  const [lastReminderNotification, setLastReminderNotification] = useState<ReminderNotificationSummary>({
    status: "idle",
    detail: "等待到期提醒触发。",
  });
  const [exportingDiagnostics, setExportingDiagnostics] = useState(false);
  const [resettingLocalState, setResettingLocalState] = useState(false);
  const [indexingVault, setIndexingVault] = useState(false);
  const [live2dModels, setLive2dModels] = useState<Live2DModelOption[]>([defaultLive2DModelOption]);
  const [selectedLive2dModelId, setSelectedLive2dModelId] = useState<string>(() => loadLive2DModelSelection());
  const [live2dAsset, setLive2dAsset] = useState<Live2DAssetInfo>(initialLive2DAssetInfo);
  const [recentTaskStageActive, setRecentTaskStageActive] = useState(false);
  const [windowMode, setWindowMode] = useState<DesktopWindowMode>(() => detectDesktopWindowMode());
  const live2dCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const petInputRef = useRef<HTMLInputElement | null>(null);
  const petReplyScrollRef = useRef<HTMLDivElement | null>(null);
  const petAssistantReplyRef = useRef("");
  const petReplyStartedRef = useRef(false);
  const petReplyCompleteRef = useRef(false);
  const petReplyAutoFollowRef = useRef(true);
  const petUserIsReadingRef = useRef(false);
  const streamAbort = useRef<AbortController | null>(null);
  const triggeredReminderNotificationIds = useRef<Set<string>>(new Set());
  const readyHealthRefreshKey = useRef<string | null>(null);
  const live2dTaskStageTimeoutRef = useRef<number | null>(null);
  const petBubbleHideTimerRef = useRef<number | null>(null);
  const petBubblePageTimerRef = useRef<number | null>(null);
  const petStreamWatchdogTimerRef = useRef<number | null>(null);
  const petReplyPagesRef = useRef<string[]>([]);
  const petReplyPageIndexRef = useRef(0);
  const petReplyPagingStartedRef = useRef(false);
  const latestContinuitySignalRef = useRef<ChatContinuitySignal | null>(null);
  const petBubblePausedRef = useRef(false);
  const petStreamOpenedRef = useRef(false);
  const petStreamReceivedEventRef = useRef(false);
  const petStreamFailedRef = useRef(false);
  const petStreamStartedAtRef = useRef<number | null>(null);
  const petDragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    dragging: boolean;
    target: HTMLElement | null;
  } | null>(null);
  const isElectronRuntime = Boolean(window.agentDesktop);
  const canSelectVaultDirectory = Boolean(window.agentDesktop?.selectKnowledgeBaseFolder);

  const client = useMemo(() => new ApiClient(settings), [settings]);
  const api = useMemo(() => new DesktopApi(client), [client]);

  function triggerLive2DTaskStage() {
    setRecentTaskStageActive(true);
    if (live2dTaskStageTimeoutRef.current !== null) {
      window.clearTimeout(live2dTaskStageTimeoutRef.current);
    }
    live2dTaskStageTimeoutRef.current = window.setTimeout(() => {
      setRecentTaskStageActive(false);
      live2dTaskStageTimeoutRef.current = null;
    }, 12000);
  }

  function clearPetBubbleHideTimer() {
    if (petBubbleHideTimerRef.current !== null) {
      window.clearTimeout(petBubbleHideTimerRef.current);
      petBubbleHideTimerRef.current = null;
    }
  }

  function clearPetBubblePageTimer() {
    if (petBubblePageTimerRef.current !== null) {
      window.clearTimeout(petBubblePageTimerRef.current);
      petBubblePageTimerRef.current = null;
    }
  }

  function clearPetStreamWatchdogTimer() {
    if (petStreamWatchdogTimerRef.current !== null) {
      window.clearTimeout(petStreamWatchdogTimerRef.current);
      petStreamWatchdogTimerRef.current = null;
    }
  }

  function hasPetStreamTerminalState() {
    return petReplyStartedRef.current || petReplyCompleteRef.current || petStreamFailedRef.current;
  }

  function schedulePetStreamWatchdog(
    title: string,
    message: string,
    delayMs = 10000,
    onFinalTimeout?: () => void,
  ) {
    clearPetStreamWatchdogTimer();
    if (onFinalTimeout && !hasPetStreamTerminalState()) {
      const elapsedMs = petStreamStartedAtRef.current === null ? 0 : Date.now() - petStreamStartedAtRef.current;
      if (elapsedMs >= petStreamFinalTimeoutMs) {
        onFinalTimeout();
        return;
      }
    }
    petStreamWatchdogTimerRef.current = window.setTimeout(() => {
      petStreamWatchdogTimerRef.current = null;
      if (hasPetStreamTerminalState()) {
        return;
      }
      showPetBubble({
        title,
        message,
        tone: "thinking",
      });
      if (!onFinalTimeout) {
        return;
      }

      const elapsedMs = petStreamStartedAtRef.current === null ? 0 : Date.now() - petStreamStartedAtRef.current;
      const remainingFinalMs = Math.max(0, petStreamFinalTimeoutMs - elapsedMs);
      const finalDelayMs = Math.min(petStreamFinalWatchdogDelayMs, remainingFinalMs);
      petStreamWatchdogTimerRef.current = window.setTimeout(() => {
        petStreamWatchdogTimerRef.current = null;
        if (hasPetStreamTerminalState()) {
          return;
        }
        onFinalTimeout();
      }, finalDelayMs);
    }, delayMs);
  }

  function markPetStreamEventReceived() {
    petStreamReceivedEventRef.current = true;
    clearPetStreamWatchdogTimer();
  }

  function isReplyScrolledToBottom(element: HTMLDivElement) {
    return element.scrollHeight - element.scrollTop - element.clientHeight <= 8;
  }

  function followReplyToBottom() {
    const element = petReplyScrollRef.current;
    if (!element || !petReplyAutoFollowRef.current || petUserIsReadingRef.current) {
      return;
    }
    window.requestAnimationFrame(() => {
      const nextElement = petReplyScrollRef.current;
      if (!nextElement || !petReplyAutoFollowRef.current || petUserIsReadingRef.current) {
        return;
      }
      nextElement.scrollTop = nextElement.scrollHeight;
    });
  }

  function showPetBubble(next: Omit<PetBubbleState, "visible" | "phase"> & { phase?: PetBubblePhase }) {
    clearPetBubbleHideTimer();
    const phase = next.phase || (next.tone === "reply" ? "speaking" : "thinking");
    setPetBubble({ ...next, phase, visible: true });
  }

  function showPetReaction(message: string, tone: Exclude<PetBubbleTone, "reply"> = "thinking", title = "") {
    if (petReplyStartedRef.current) {
      return;
    }
    showPetBubble({ title, message, tone, phase: tone === "error" ? "complete" : "thinking" });
  }

  function showPetReply(text: string, phase: Extract<PetBubblePhase, "speaking" | "complete"> = "speaking") {
    clearPetBubbleHideTimer();
    setPetReplyText(text);
    setPetBubble({ visible: true, title: "", message: text, tone: "reply", phase });
    followReplyToBottom();
  }

  function latestContinuitySignalForMessage(messageId: string): ChatContinuitySignal | null {
    return (
      messages.find((message) => message.id === messageId)?.continuity_signal ||
      latestContinuitySignalRef.current ||
      latestContinuitySignal
    );
  }

  function showContinuityPresenceBubble(signal: ChatContinuitySignal) {
    if (petBubblePausedRef.current) {
      return;
    }
    showPetBubble({
      title: signal.title || "连续性在场",
      message: signal.display_hint ? `${signal.summary} ${signal.display_hint}` : signal.summary,
      tone: "tool",
      phase: "complete",
    });
    schedulePetBubbleHide(signal.intensity === "high" ? 9000 : 7000);
  }

  function formatPetBubbleContinueHint(pageIndex: number, pageCount: number) {
    if (pageCount <= 1) {
      return undefined;
    }
    return `${pageIndex + 1}/${pageCount}`;
  }

  function renderPetBubblePage(pageIndex: number, phase: Extract<PetBubblePhase, "speaking" | "complete"> = "speaking") {
    const pages = petReplyPagesRef.current;
    if (pages.length === 0) {
      return false;
    }
    const safeIndex = Math.max(0, Math.min(pageIndex, pages.length - 1));
    petReplyPageIndexRef.current = safeIndex;
    clearPetBubbleHideTimer();
    setPetBubble({
      visible: true,
      title: "",
      message: pages[safeIndex],
      tone: "reply",
      phase,
      continueHint: formatPetBubbleContinueHint(safeIndex, pages.length),
    });
    return true;
  }

  function setPetReplyPagesFromText(
    text: string,
    options: { preserveCurrentPage?: boolean; phase?: Extract<PetBubblePhase, "speaking" | "complete"> } = {},
  ) {
    const pages = paginatePetBubbleReply(text);
    petReplyPagesRef.current = pages;
    setPetReplyText(text);
    clearPetBubbleHideTimer();
    if (pages.length === 0) {
      setPetBubble({ visible: false, title: "", message: "", tone: "reply", phase: "idle" });
      return;
    }

    const nextIndex =
      options.preserveCurrentPage
        ? Math.min(petReplyPageIndexRef.current, pages.length - 1)
        : 0;
    renderPetBubblePage(nextIndex, options.phase || "speaking");
  }

  function scheduleNextPetBubblePage() {
    clearPetBubblePageTimer();
    const pages = petReplyPagesRef.current;
    if (pages.length === 0 || petBubblePausedRef.current) {
      return;
    }
    const currentIndex = petReplyPageIndexRef.current;
    if (currentIndex >= pages.length - 1) {
      schedulePetBubbleHide(9000);
      return;
    }
    petBubblePageTimerRef.current = window.setTimeout(() => {
      if (petBubblePausedRef.current) {
        petBubblePageTimerRef.current = null;
        return;
      }
      renderPetBubblePage(currentIndex + 1, petReplyCompleteRef.current ? "complete" : "speaking");
      scheduleNextPetBubblePage();
    }, getPetBubblePageDelay(pages[currentIndex]));
  }

  function startPetReplyPaging() {
    if (petReplyPagingStartedRef.current) {
      return;
    }
    clearPetStreamWatchdogTimer();
    clearPetBubblePageTimer();
    petReplyPagingStartedRef.current = true;
    petReplyCompleteRef.current = true;
    const text = petAssistantReplyRef.current;
    const pages = paginatePetBubbleReply(text);
    petReplyPagesRef.current = pages;
    setPetReplyText(text);

    if (pages.length === 0) {
      showPetBubble({
        title: "",
        message: "我这次没有生成可显示的回复。",
        tone: "reply",
        phase: "complete",
      });
      schedulePetBubbleHide(6000);
      return;
    }

    const safeIndex = Math.min(petReplyPageIndexRef.current, pages.length - 1);
    renderPetBubblePage(safeIndex, "complete");
    scheduleNextPetBubblePage();
  }

  function failPetStream(messageId: string, title: string, message: string) {
    if (hasPetStreamTerminalState()) {
      return;
    }

    petStreamFailedRef.current = true;
    petReplyCompleteRef.current = true;
    clearPetStreamWatchdogTimer();
    clearPetBubblePageTimer();
    petReplyPagesRef.current = [];
    setPetReplyText("");
    showPetBubble({
      title,
      message,
      tone: "error",
      phase: "complete",
    });
    schedulePetBubbleHide(10000);
    setMessages((current) =>
      current.map((chatMessage) =>
        chatMessage.id === messageId && chatMessage.status === "partial"
          ? { ...chatMessage, status: "failed", content: chatMessage.content || message }
          : chatMessage,
      ),
    );
    setNotice({ tone: "error", message });
    streamAbort.current?.abort();
  }

  function completePetStreamWithoutReply(messageId: string) {
    if (hasPetStreamTerminalState()) {
      return;
    }

    const message = petStreamReceivedEventRef.current
      ? "回复流已经结束，但没有收到可显示的模型回复。"
      : "回复流已经结束，但没有收到任何事件。";
    failPetStream(messageId, "没有收到回复", message);
  }

  function advancePetBubblePageManually() {
    const pages = petReplyPagesRef.current;
    if (pages.length <= 1 || petBubble.tone !== "reply") {
      return;
    }
    clearPetBubblePageTimer();
    const nextIndex = Math.min(petReplyPageIndexRef.current + 1, pages.length - 1);
    renderPetBubblePage(nextIndex, petReplyCompleteRef.current ? "complete" : "speaking");
    if (nextIndex >= pages.length - 1) {
      if (petReplyCompleteRef.current && !petBubblePausedRef.current) {
        schedulePetBubbleHide(9000);
      }
      return;
    }
    if (petReplyPagingStartedRef.current && !petBubblePausedRef.current) {
      scheduleNextPetBubblePage();
    }
  }

  function pausePetBubblePaging() {
    petBubblePausedRef.current = true;
    petUserIsReadingRef.current = true;
    clearPetBubblePageTimer();
    clearPetBubbleHideTimer();
  }

  function resumePetBubblePaging() {
    petBubblePausedRef.current = false;
    petUserIsReadingRef.current = false;
    if (petReplyPagingStartedRef.current && petBubble.tone === "reply") {
      scheduleNextPetBubblePage();
    }
  }

  function schedulePetBubbleHide(delayMs = 8000) {
    clearPetBubbleHideTimer();
    petBubbleHideTimerRef.current = window.setTimeout(() => {
      if (petUserIsReadingRef.current || petBubblePausedRef.current) {
        petBubbleHideTimerRef.current = null;
        return;
      }
      setPetBubble((current) => ({ ...current, phase: "fading", visible: false }));
      petBubbleHideTimerRef.current = null;
    }, delayMs);
  }


  function showPetInput() {
    setPetInputVisible(true);
    window.requestAnimationFrame(() => petInputRef.current?.focus());
  }

  function selectLive2DModel(modelId: string) {
    setSelectedLive2dModelId(modelId);
    saveLive2DModelSelection(modelId);
    if ("BroadcastChannel" in window) {
      const channel = new BroadcastChannel(live2dModelSelectionChannelName);
      channel.postMessage({ modelId });
      channel.close();
    }
  }

  useEffect(() => {
    const candidateMessage = findLatestArchivableAssistantMessage(messages);
    if (!candidateMessage) {
      return;
    }
    const candidate: WikiArchiveCandidate = {
      conversation_id: conversationId,
      message: candidateMessage,
      question: findQuestionForAssistantMessage(messages, candidateMessage.id),
      updated_at: new Date().toISOString(),
    };
    setWikiArchiveCandidate(candidate);
    saveWikiArchiveCandidate(candidate);
  }, [conversationId, messages]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key !== wikiArchiveCandidateStorageKey) {
        return;
      }
      setWikiArchiveCandidate(loadWikiArchiveCandidate());
    };
    window.addEventListener("storage", handleStorage);

    let channel: BroadcastChannel | null = null;
    if ("BroadcastChannel" in window) {
      channel = new BroadcastChannel(wikiArchiveCandidateChannelName);
      channel.onmessage = (event) => {
        const candidate = normalizeWikiArchiveCandidate(event.data);
        if (candidate) {
          setWikiArchiveCandidate(candidate);
        }
      };
    }

    return () => {
      window.removeEventListener("storage", handleStorage);
      channel?.close();
    };
  }, []);

  useEffect(() => {
    if (windowMode !== "control") {
      return;
    }
    void loadWikiArchiveHistory({ silent: true });
    void loadWikiCoreStatus({ silent: true });
  }, [api, windowMode]);

  useEffect(() => {
    document.body.dataset.windowMode = windowMode;
    return () => {
      delete document.body.dataset.windowMode;
    };
  }, [windowMode]);

  useEffect(() => {
    return () => {
      if (live2dTaskStageTimeoutRef.current !== null) {
        window.clearTimeout(live2dTaskStageTimeoutRef.current);
      }
      if (petBubbleHideTimerRef.current !== null) {
        window.clearTimeout(petBubbleHideTimerRef.current);
      }
      clearPetBubblePageTimer();
      clearPetStreamWatchdogTimer();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void window.agentDesktop?.getWindowMode?.().then((mode) => {
      if (!cancelled && (mode === "pet" || mode === "control")) {
        setWindowMode(mode);
      }
    });

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
    let cancelled = false;
    void window.agentDesktop?.getSidecarStatus?.().then((status) => {
      if (!cancelled) {
        setSidecarStatus(status);
      }
    });
    const unsubscribe = window.agentDesktop?.onSidecarStatusChanged?.((status) => {
      setSidecarStatus(status);
    });
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, []);

  useEffect(() => {
    if (!sidecarStatus?.error) {
      return;
    }

    setNotice({
      tone: sidecarStatus.state === "ready" ? "info" : "error",
      message: getSidecarActionMessage(sidecarStatus),
    });
  }, [sidecarStatus?.state, sidecarStatus?.error?.code, sidecarStatus?.error?.message]);

  useEffect(() => {
    const abort = new AbortController();
    void loadSettingsStatus({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [api]);

  useEffect(() => {
    const abort = new AbortController();
    void loadContinuity({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [api]);

  useEffect(() => {
    if (sidecarStatus?.state !== "ready") {
      return;
    }
    const abort = new AbortController();
    void loadVaultStatus({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [api, sidecarStatus?.state, sidecarStatus?.updatedAt]);

  useEffect(() => {
    if (!window.agentDesktop?.showReminderNotification || sidecarStatus?.state !== "ready") {
      return;
    }

    const intervalId = window.setInterval(() => {
      void loadTasksSilently();
    }, 15000);
    return () => window.clearInterval(intervalId);
  }, [api, sidecarStatus?.state]);

  useEffect(() => {
    const abort = new AbortController();
    let cancelled = false;

    async function loadLive2DModels() {
      try {
        const response = await fetch(live2dModelCatalogPath, { signal: abort.signal });
        if (!response.ok) {
          return;
        }
        const catalog = (await response.json()) as Live2DModelCatalog;
        const models = normalizeLive2DModelCatalog(catalog);
        if (!cancelled && models.length > 0) {
          setLive2dModels(models);
          setSelectedLive2dModelId((current) => (
            models.some((model) => model.id === current) ? current : models[0].id
          ));
        }
      } catch (error) {
        if (!abort.signal.aborted) {
          console.warn("[Live2D] 模型列表读取失败，使用默认 UG 模型。", error);
        }
      }
    }

    void loadLive2DModels();

    return () => {
      cancelled = true;
      abort.abort();
    };
  }, []);

  useEffect(() => {
    saveLive2DModelSelection(selectedLive2dModelId);
  }, [selectedLive2dModelId]);

  useEffect(() => {
    const applySelection = (modelId: string | null) => {
      if (!modelId) {
        return;
      }
      setSelectedLive2dModelId((current) => (
        current === modelId ? current : modelId
      ));
    };

    const handleStorage = (event: StorageEvent) => {
      if (event.key === live2dModelSelectionStorageKey) {
        applySelection(event.newValue);
      }
    };
    window.addEventListener("storage", handleStorage);
    const pollSelectionTimer = window.setInterval(() => {
      applySelection(loadLive2DModelSelection());
    }, 1000);

    let channel: BroadcastChannel | null = null;
    if ("BroadcastChannel" in window) {
      channel = new BroadcastChannel(live2dModelSelectionChannelName);
      channel.onmessage = (event) => {
        const modelId = typeof event.data?.modelId === "string" ? event.data.modelId : null;
        applySelection(modelId);
      };
    }

    return () => {
      window.removeEventListener("storage", handleStorage);
      window.clearInterval(pollSelectionTimer);
      channel?.close();
    };
  }, [live2dModels]);

  useEffect(() => {
    const abort = new AbortController();
    let cancelled = false;

    async function loadLive2DAsset() {
      const selectedModel = live2dModels.find((model) => model.id === selectedLive2dModelId) || live2dModels[0] || defaultLive2DModelOption;
      const initialAsset = createInitialLive2DAssetInfo(selectedModel);
      setLive2dAsset(initialAsset);
      try {
        const [manifestResponse, hasIcon] = await Promise.all([
          fetch(live2DManifestPath(selectedModel), { signal: abort.signal }),
          selectedModel.icon ? checkImageExists(live2DIconPath(selectedModel)) : Promise.resolve(false),
        ]);

        if (!manifestResponse.ok) {
          if (!cancelled) {
            setLive2dAsset({
              ...initialAsset,
              status: "missing",
              hasIcon,
              error: `HTTP ${manifestResponse.status}`,
            });
          }
          return;
        }

        const manifest = (await manifestResponse.json()) as Live2DModelManifest;

        if (!cancelled) {
          setLive2dAsset(createLive2DAssetInfo(manifest, hasIcon, selectedModel));
        }
      } catch (error) {
        if (abort.signal.aborted || cancelled) {
          return;
        }

        setLive2dAsset({
          ...initialAsset,
          status: "error",
          error: describeError(error, "模型资源清单读取失败"),
        });
      }
    }

    void loadLive2DAsset();

    return () => {
      cancelled = true;
      abort.abort();
    };
  }, [live2dModels, selectedLive2dModelId]);

  useEffect(() => {
    if (sidecarStatus?.health) {
      setHealth(sidecarStatus.health);
    }

    if (sidecarStatus?.state !== "ready") {
      return;
    }

    const refreshKey = sidecarStatus.updatedAt || `${sidecarStatus.baseUrl}:${sidecarStatus.port}`;
    if (readyHealthRefreshKey.current === refreshKey) {
      return;
    }

    readyHealthRefreshKey.current = refreshKey;
    if (sidecarStatus.baseUrl && sidecarStatus.baseUrl !== settings.baseUrl) {
      const next = { ...settings, baseUrl: sidecarStatus.baseUrl };
      saveConnectionSettings(next);
      setSettings(next);
    }
    void checkHealth({ silent: true });
  }, [sidecarStatus]);

  function persistSettings(next: ConnectionSettings) {
    const trimmed = {
      baseUrl: next.baseUrl,
      sessionToken: next.sessionToken,
    };
    saveConnectionSettings(trimmed);
    setSettings(trimmed);
    setNotice({ tone: "success", message: "本次应用会话的连接设置已保存。" });
  }

  async function checkHealth(options: { silent?: boolean } = {}) {
    setCheckingHealth(true);
    if (!options.silent) {
      setNotice(null);
    }
    try {
      const response = await client.health();
      setHealth(response);
      const businessReady = await checkBusinessAccess({ silent: options.silent });
      if (!options.silent && businessReady) {
        setNotice({ tone: "success", message: "后端健康检查和业务鉴权均通过。" });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (options.silent) {
        return;
      }
      setBusinessAuthStatus("unknown");
      setBusinessAuthMessage("后端健康检查失败，尚未检查业务接口鉴权。");
      setNotice({ tone: "error", message: describeError(error, "健康检查失败") });
    } finally {
      setCheckingHealth(false);
    }
  }

  async function sendChatText(rawText: string, clearInput: () => void) {
    const text = rawText.trim();
    if (!text || streaming) {
      return;
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
    setPetInputVisible(false);
    setStreaming(true);
    setNotice(null);
    petAssistantReplyRef.current = "";
    petReplyStartedRef.current = false;
    petReplyCompleteRef.current = false;
    petReplyPagesRef.current = [];
    petReplyPageIndexRef.current = 0;
    petReplyPagingStartedRef.current = false;
    petBubblePausedRef.current = false;
    petStreamOpenedRef.current = false;
    petStreamReceivedEventRef.current = false;
    petStreamFailedRef.current = false;
    petStreamStartedAtRef.current = Date.now();
    latestContinuitySignalRef.current = null;
    clearPetBubblePageTimer();
    clearPetStreamWatchdogTimer();
    setPetReplyText("");
    showPetBubble({
      title: "正在发送",
      message: "我正在把你的话交给后端。",
      tone: "thinking",
    });
    schedulePetStreamWatchdog(
      "请求仍在处理中",
      "后端还没有返回回复流地址，可能正在启动或等待模型服务。",
      8000,
      () => failPetStream(assistantId, "请求超时", "后端长时间没有返回回复流地址，本次请求已停止。"),
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
      showPetBubble({
        title: "正在连接回复流",
        message: "后端已接收请求，我正在等待实时回复。",
        tone: "thinking",
      });
      schedulePetStreamWatchdog(
        "回复流连接较慢",
        "后端已创建会话，但回复流还没有打开，请再等一下。",
        8000,
        () => failPetStream(assistantId, "回复流超时", "后端已接收请求，但长时间没有打开回复流。"),
      );

      await fetchSseStream(
        client,
        accepted.stream_url,
        {
          onOpen: () => {
            petStreamOpenedRef.current = true;
            clearPetStreamWatchdogTimer();
            if (!petReplyStartedRef.current && !petStreamReceivedEventRef.current) {
              showPetBubble({
                title: "等待回复",
                message: "回复流已连接，我在等模型返回第一段内容。",
                tone: "thinking",
              });
              schedulePetStreamWatchdog(
                "仍在等待模型",
                "后端连接正常，但模型还没有返回第一段回复。",
                12000,
                () => failPetStream(assistantId, "模型回复超时", "回复流已连接，但模型长时间没有返回可显示内容。"),
              );
            }
          },
          onEvent: (sseEvent) => applyStreamEvent(assistantId, sseEvent),
        },
        abort.signal,
      );
      clearPetStreamWatchdogTimer();

      if (petStreamFailedRef.current) {
        return;
      }

    if (petReplyStartedRef.current) {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId && message.status === "partial"
            ? { ...message, status: "completed" }
            : message,
          ),
      );
      startPetReplyPaging();
      const signal = latestContinuitySignalForMessage(assistantId);
      if (signal) {
        const delay = Math.min(9000, Math.max(1200, petReplyPagesRef.current.length * 2600));
        window.setTimeout(() => showContinuityPresenceBubble(signal), delay);
      }
      } else {
        completePetStreamWithoutReply(assistantId);
      }
    } catch (error) {
      clearPetStreamWatchdogTimer();
      petStreamFailedRef.current = true;
      const message = describeError(error, "消息发送失败");
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? { ...message, status: "failed", content: message.content || describeError(error, "消息发送失败") }
            : message,
        ),
      );
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        showPetBubble({
          title: "交互失败",
          message,
          tone: "error",
        });
        schedulePetBubbleHide(10000);
        setNotice({ tone: "error", message });
      }
    } finally {
      clearPetStreamWatchdogTimer();
      setStreaming(false);
      streamAbort.current = null;
      petStreamStartedAtRef.current = null;
    }
  }

  async function sendPetMessage(event: FormEvent) {
    event.preventDefault();
    await sendChatText(petInput, () => setPetInput(""));
  }

  function applyStreamEvent(messageId: string, sseEvent: SseEvent) {
    markPetStreamEventReceived();
    const payload = parseJson(sseEvent.data);
    if (sseEvent.event === "done") {
      const doneText = extractSseText(sseEvent, payload);
      if (!petAssistantReplyRef.current && !doneText) {
        failPetStream(messageId, "没有收到回复", "后端发送了完成事件，但没有附带可显示回复。");
        return;
      }
      if (!petAssistantReplyRef.current && doneText) {
        petReplyStartedRef.current = true;
        petAssistantReplyRef.current = doneText;
      }
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? {
                ...message,
                content: message.content || doneText,
                status: "completed",
              }
            : message,
        ),
      );
      startPetReplyPaging();
      return;
    }

    if (sseEvent.event === "error") {
      petStreamFailedRef.current = true;
      clearPetStreamWatchdogTimer();
      const errorMessage = `流式响应失败：${typeof payload?.message === "string" ? payload.message : sseEvent.data}`;
      showPetBubble({
        title: "回复失败",
        message: errorMessage,
        tone: "error",
      });
      schedulePetBubbleHide(10000);
      setMessages((current) =>
        current.map((chatMessage) =>
          chatMessage.id === messageId
            ? { ...chatMessage, status: "failed", content: chatMessage.content || errorMessage }
            : chatMessage,
        ),
      );
      return;
    }

    if (sseEvent.event === "status") {
      const stageLabel = formatAgentStage(payload?.stage);
      const statusMessage = typeof payload?.message === "string" && payload.message ? payload.message : "智能体正在处理请求。";
      if (!petReplyStartedRef.current) {
        showPetBubble({
          title: stageLabel || "智能体状态",
          message: statusMessage,
          tone: "thinking",
        });
        schedulePetStreamWatchdog(
          "仍在等待回复",
          "后端还在处理，模型暂时没有返回第一段内容。",
          12000,
          () => failPetStream(messageId, "模型回复超时", "后端仍在处理，但模型长时间没有返回可显示内容。"),
        );
      }
      appendChatEvent(messageId, {
        label: stageLabel ? `智能体状态 · ${stageLabel}` : "智能体状态",
        detail: statusMessage,
        tone: "info",
      });
      return;
    }

    if (sseEvent.event === "continuity_signal") {
      const signal = normalizeContinuitySignal(payload);
      if (signal) {
        latestContinuitySignalRef.current = signal;
        setLatestContinuitySignal(signal);
        upsertChatContinuitySignal(messageId, signal);
      }
      appendChatEvent(messageId, {
        label: "连续性在场",
        detail: signal ? `${signal.title}：${signal.summary}` : "已收到运行时连续性提示。",
        tone: "success",
      });
      return;
    }

    const proposalId = payload?.proposal_id;
    if (sseEvent.event === "continuity_proposal") {
      const proposal = normalizeContinuityProposal(payload);
      if (proposal) {
        upsertContinuityProposal(proposal);
        upsertChatContinuityProposal(messageId, proposal);
      }
      appendChatEvent(messageId, {
        label: "连续性提案",
        detail: proposal
          ? `${formatContinuityKind(proposal.kind)}：${proposal.summary}`
          : "收到一条待确认连续性提案。",
        tone: "info",
      });
      if (!petReplyStartedRef.current) {
        showPetBubble({
          title: "收到连续性提案",
          message: proposal ? `${formatContinuityKind(proposal.kind)}：${proposal.summary}` : "有新的连续性提案等待确认。",
          tone: "tool",
        });
        schedulePetStreamWatchdog(
          "等待回复内容",
          "连续性提案已展示，正在等待模型生成最终回复。",
          12000,
          () => failPetStream(messageId, "模型回复超时", "连续性提案已展示，但模型长时间没有返回最终回复。"),
        );
      }
      return;
    }

    if (sseEvent.event === "memory_proposal" && typeof proposalId === "string") {
      setProposals((current) => [
        {
          proposal_id: proposalId,
          status: typeof payload?.status === "string" ? (payload.status as MemoryProposal["status"]) : "pending",
          type: isMemoryProposalType(payload?.type) ? payload.type : "fact",
          content:
            typeof payload?.content === "string"
              ? payload.content
              : typeof payload?.preview_markdown === "string"
                ? payload.preview_markdown
                : "",
          target_path: typeof payload?.target_path === "string" ? payload.target_path : defaultMemoryTargetPath,
          preview_markdown: typeof payload?.preview_markdown === "string" ? payload.preview_markdown : undefined,
          diff: typeof payload?.diff === "string" ? payload.diff : undefined,
          target_content_hash:
            typeof payload?.target_content_hash === "string" ? payload.target_content_hash : null,
        },
        ...current,
      ]);
      appendChatEvent(messageId, {
        label: "记忆提案",
        detail: `已创建待确认记忆：${proposalId}`,
        tone: "success",
      });
      if (!petReplyStartedRef.current) {
        showPetBubble({
          title: "正在整理记忆",
          message: "我正在根据你的输入整理长期记忆。",
          tone: "tool",
        });
        schedulePetStreamWatchdog(
          "等待回复内容",
          "记忆提案已处理，正在等待模型生成最终回复。",
          12000,
          () => failPetStream(messageId, "模型回复超时", "记忆提案已处理，但模型长时间没有返回最终回复。"),
        );
      }
      return;
    }

    if (isWikiProposalStreamEvent(sseEvent.event)) {
      const detail = formatWikiProposalEventDetail(sseEvent.event, payload, sseEvent.data);
      const proposal = normalizeChatWikiProposal(payload);
      if (proposal) {
        upsertChatWikiProposal(messageId, proposal);
      }
      appendChatEvent(messageId, {
        label: "Vault 维护提案",
        detail,
        tone: "info",
      });
      if (!petReplyStartedRef.current) {
        showPetBubble({
          title: "收到 Vault 维护提案",
          message: detail,
          tone: "tool",
        });
        schedulePetStreamWatchdog(
          "等待回复内容",
          "Vault 维护提案已展示，正在等待模型生成最终回复。",
          12000,
          () => failPetStream(messageId, "模型回复超时", "Vault 维护提案已展示，但模型长时间没有返回最终回复。"),
        );
      }
      return;
    }

    const taskId = payload?.task_id;
    if (sseEvent.event === "task" && typeof taskId === "string") {
      const title = typeof payload?.title === "string" ? payload.title : "聊天创建的任务";
      const remindAt = typeof payload?.remind_at === "string" ? payload.remind_at : undefined;
      const timezone = typeof payload?.timezone === "string" ? payload.timezone : undefined;
      const timezoneLabel =
        typeof payload?.timezone_label === "string" ? payload.timezone_label : formatTimezoneForUser(timezone);
      const reminderStatus = typeof payload?.reminder_status === "string" ? payload.reminder_status : undefined;
      setTasks((current) => [
        {
          task_id: taskId,
          reminder_id: typeof payload?.reminder_id === "string" ? payload.reminder_id : undefined,
          title,
          status: typeof payload?.status === "string" ? payload.status : "pending",
          reminder_status: reminderStatus,
          remind_at: remindAt,
          timezone,
          timezone_label: timezoneLabel,
        },
        ...current,
      ]);
      triggerLive2DTaskStage();
      appendChatEvent(messageId, {
        label: "任务",
        detail: `已创建任务：${title}${remindAt ? `；提醒时间 ${remindAt}` : ""}${timezoneLabel ? `；时区 ${timezoneLabel}` : ""}${reminderStatus ? `；提醒状态 ${formatTaskStatus(reminderStatus)}` : ""}`,
        tone: "success",
      });
      if (!petReplyStartedRef.current) {
        showPetBubble({
          title: "正在记录提醒",
          message: `${title}${remindAt ? ` · ${remindAt}` : ""}${timezoneLabel ? ` · ${timezoneLabel}` : ""}`,
          tone: "reminder",
        });
        schedulePetStreamWatchdog(
          "等待回复内容",
          "提醒已记录，正在等待模型生成最终回复。",
          12000,
          () => failPetStream(messageId, "模型回复超时", "提醒已记录，但模型长时间没有返回最终回复。"),
        );
      }
      return;
    }

    const token = extractSseText(sseEvent, payload);
    const citation =
      sseEvent.event === "citation" && isCitation(payload?.citation) ? payload.citation : undefined;
    const citations = Array.isArray(payload?.citations)
      ? payload.citations.filter(isCitation)
      : citation
        ? [citation]
        : undefined;
    if (token) {
      petReplyStartedRef.current = true;
      petAssistantReplyRef.current = `${petAssistantReplyRef.current}${token}`;
      setPetReplyPagesFromText(petAssistantReplyRef.current, { preserveCurrentPage: true });
    } else if (citations?.length && !petReplyStartedRef.current) {
      showPetBubble({
        title: "找到记忆线索",
        message: citations[0]?.relative_path ? `参考：${citations[0].relative_path}` : "我正在引用本地记忆回答。",
        tone: "tool",
      });
      schedulePetStreamWatchdog(
        "等待回复内容",
        "已经找到参考内容，正在等待模型生成最终回复。",
        12000,
        () => failPetStream(messageId, "模型回复超时", "已经找到参考内容，但模型长时间没有返回最终回复。"),
      );
    }
    setMessages((current) =>
      current.map((message) => {
        if (message.id !== messageId) {
          return message;
        }
        return {
          ...message,
          content: token ? `${message.content}${token}` : message.content,
          citations: citations ? [...(message.citations || []), ...citations] : message.citations,
        };
      }),
    );
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

  function upsertChatWikiProposal(messageId: string, proposal: ChatWikiProposal) {
    setMessages((current) =>
      current.map((message) => {
        if (message.id !== messageId) {
          return message;
        }
        const proposals = message.wiki_proposals || [];
        const existing = proposals.find((item) => item.id === proposal.id);
        const merged = mergeChatWikiProposal(existing, proposal);
        const rest = proposals.filter((item) => item.id !== proposal.id);
        return {
          ...message,
          wiki_proposals: [merged, ...rest],
        };
      }),
    );
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

  function updateChatWikiProposal(
    messageId: string,
    proposalId: string,
    updater: (proposal: ChatWikiProposal) => ChatWikiProposal,
  ) {
    setMessages((current) =>
      current.map((message) =>
        message.id === messageId
          ? {
              ...message,
              wiki_proposals: (message.wiki_proposals || []).map((proposal) =>
                proposal.id === proposalId ? updater(proposal) : proposal,
              ),
            }
          : message,
      ),
    );
  }

  function confirmChatWikiProposal(messageId: string, proposalId: string) {
    updateChatWikiProposal(messageId, proposalId, (proposal) => ({
      ...proposal,
      state: "confirmed",
      error: null,
      updated_at: new Date().toISOString(),
    }));
    setNotice({ tone: "info", message: "Vault 维护提案已本地确认；仍需点击应用才会写入 Markdown。" });
  }

  function rejectChatWikiProposal(messageId: string, proposalId: string) {
    updateChatWikiProposal(messageId, proposalId, (proposal) => ({
      ...proposal,
      state: "rejected",
      error: null,
      updated_at: new Date().toISOString(),
    }));
    setNotice({ tone: "info", message: "Vault 维护提案已拒绝，没有写入 Markdown。" });
  }

  function toggleChatWikiProposalTarget(
    messageId: string,
    proposalId: string,
    targetPath: string,
    selected: boolean,
  ) {
    updateChatWikiProposal(messageId, proposalId, (proposal) => {
      const currentTargets = new Set(proposal.selected_targets);
      if (selected) {
        currentTargets.add(targetPath);
      } else {
        currentTargets.delete(targetPath);
      }
      return {
        ...proposal,
        selected_targets: Array.from(currentTargets),
        updated_at: new Date().toISOString(),
      };
    });
  }

  async function applyChatWikiProposal(messageId: string, proposalId: string) {
    const sourceMessage = messages.find((message) => message.id === messageId);
    const proposal = sourceMessage?.wiki_proposals?.find((item) => item.id === proposalId);
    if (!proposal) {
      setNotice({ tone: "error", message: "没有在当前聊天消息中找到 Vault 维护提案状态。" });
      return;
    }
    if (!isSupportedChatWikiProposalType(proposal.proposal_type)) {
      setNotice({ tone: "error", message: `该 Vault 提案类型暂不支持从聊天中应用：${proposal.proposal_type}。` });
      return;
    }
    if (proposal.proposal_type === "ingest" && (!proposal.run_id || !proposal.review_id)) {
      setNotice({ tone: "error", message: "该 Vault 提案缺少 run_id 或 review_id，不能安全应用。" });
      return;
    }
    if (proposal.state !== "confirmed" && proposal.state !== "failed") {
      setNotice({ tone: "error", message: "请先确认该 Vault 提案，再执行应用。" });
      return;
    }

    const approvedTargets = uniqueCompactList(proposal.selected_targets);
    if (proposal.proposal_type === "ingest" && approvedTargets.length === 0) {
      setNotice({ tone: "error", message: "应用前至少选择一个目标页面。" });
      return;
    }

    updateChatWikiProposal(messageId, proposalId, (current) => ({
      ...current,
      state: "applying",
      error: null,
      updated_at: new Date().toISOString(),
    }));
    setNotice(null);
    try {
      const response = await applyConfirmedChatWikiProposal(sourceMessage, proposal, approvedTargets);
      updateChatWikiProposal(messageId, proposalId, (current) => ({
        ...current,
        state: "applied",
        error: null,
        apply_result: response,
        updated_at: new Date().toISOString(),
      }));
      if ("summary" in response && "issues" in response) {
        setWikiLintResult(response);
      } else {
        setWikiApplyResult(response);
      }
      void loadWikiCoreStatus({ silent: true });
      const indexedPage = getWikiApplyIndexedPage(response);
      if (indexedPage?.index_job_id) {
        setLastIndexRun({
          vaultId: vaultId || diagnostics?.vault.active_vault_id || "wiki",
          jobId: indexedPage.index_job_id,
          status: "status" in response ? response.status : indexedPage.status,
        });
      }
      if ("archive_id" in response && response.archive_id) {
        setLastWikiArchiveId(response.archive_id);
        await loadWikiArchiveHistory({ silent: true });
      }
      setNotice({
        tone: getChatWikiApplyNoticeTone(response),
        message: formatChatWikiApplyNotice(response),
      });
    } catch (error) {
      const message = describeError(error, "Vault 提案应用失败");
      updateChatWikiProposal(messageId, proposalId, (current) => ({
        ...current,
        state: "failed",
        error: message,
        updated_at: new Date().toISOString(),
      }));
      setNotice({ tone: "error", message });
    }
  }

  async function applyConfirmedChatWikiProposal(
    sourceMessage: ChatMessage | undefined,
    proposal: ChatWikiProposal,
    approvedTargets: string[],
  ): Promise<ChatWikiApplyResponse> {
    if (proposal.proposal_type === "ingest") {
      if (!proposal.run_id || !proposal.review_id) {
        throw new Error("该 Vault 提案缺少 run_id 或 review_id，不能安全应用。");
      }
      return api.applyWikiIngest({
        run_id: proposal.run_id,
        review_id: proposal.review_id,
        review_acknowledged: true,
        approved_targets: approvedTargets,
      });
    }

    const targetPath = approvedTargets[0] || proposal.target_paths[0] || proposal.recommended_targets[0] || null;
    if (proposal.proposal_type === "query_archive") {
      const citations = sourceMessage?.citations?.filter(isKnowledgeBaseCitation).map(toMemorySearchResultCitation) || [];
      return api.archiveWikiQuery({
        question: findQuestionForAssistantMessage(messages, sourceMessage?.id || "") || "已归档的 Wiki 查询",
        answer: sourceMessage?.content.trim() || proposal.markdown_preview || proposal.summary || proposal.title,
        citations,
        title: proposal.title,
        target_path: targetPath,
        tags: uniqueCompactList(["query-archive"]),
        agent_run_id: proposal.agent_run_id ?? sourceMessage?.agent_run_id ?? null,
        source_message_id: proposal.source_message_id || sourceMessage?.id || null,
      });
    }

    if (proposal.proposal_type === "synthesize") {
      return api.synthesizeWiki({
        title: proposal.title,
        content: proposal.markdown_preview || sourceMessage?.content || proposal.summary || proposal.title,
        source_paths: uniqueCompactList([...proposal.target_paths, ...proposal.recommended_targets]),
        target_path: targetPath,
        tags: uniqueCompactList(["synthesis"]),
      });
    }

    return api.runWikiLint({ write_report: proposal.write_report ?? true });
  }

  function getWikiApplyIndexedPage(response: ChatWikiApplyResponse): WikiPageResponse | undefined {
    if ("page_results" in response) {
      return response.page_results.find((page) => page.index_job_id);
    }
    if ("page" in response && response.page.index_job_id) {
      return response.page;
    }
    if ("report_page" in response && response.report_page?.index_job_id) {
      return response.report_page;
    }
    return undefined;
  }

  function getChatWikiApplyNoticeTone(response: ChatWikiApplyResponse): Notice["tone"] {
    if ("status" in response) {
      return response.status === "applied" ? "success" : "info";
    }
    if ("summary" in response && "issues" in response) {
      return response.summary.errors ? "info" : "success";
    }
    return "success";
  }

  function formatChatWikiApplyNotice(response: ChatWikiApplyResponse): string {
    if ("page_results" in response) {
      return `Vault 提案已应用：写入 ${response.pages_written}/${response.page_results.length} 个页面。`;
    }
    if ("lint" in response) {
      return `查询归档已写入：${response.page.relative_path}，引用 ${response.lint.normalized_citations.length} 条。`;
    }
    if ("page" in response) {
      return `Wiki 综合整理已写入：${response.page.relative_path}。`;
    }
    const issueCount = response.summary.issues ?? response.issues.length;
    return `Wiki lint 已完成：${issueCount} 个问题${response.report_page ? `，报告 ${response.report_page.relative_path}` : ""}。`;
  }

  function formatChatWikiProposalResultPaths(result: ChatWikiProposal["apply_result"]): string {
    if (!result) {
      return "";
    }
    if ("page_results" in result) {
      return result.page_results.map((page) => page.relative_path).join(", ");
    }
    if ("page" in result) {
      return result.page.relative_path;
    }
    return result.report_page?.relative_path || "";
  }

  function renderChatWikiProposal(message: ChatMessage, proposal: ChatWikiProposal) {
    const targetOptions = getWikiProposalTargetOptions(proposal);
    const selectedTargets = new Set(proposal.selected_targets);
    const canEditTargets = proposal.state === "pending" || proposal.state === "confirmed" || proposal.state === "failed";
    const canConfirm = proposal.state === "pending";
    const canReject = proposal.state !== "rejected" && proposal.state !== "applied" && proposal.state !== "applying";
    const canApply =
      isSupportedChatWikiProposalType(proposal.proposal_type) &&
      (proposal.state === "confirmed" || proposal.state === "failed") &&
      (proposal.proposal_type !== "ingest" || (Boolean(proposal.run_id && proposal.review_id) && proposal.selected_targets.length > 0));
    const resultPaths = formatChatWikiProposalResultPaths(proposal.apply_result);

    return (
      <article key={proposal.id} className={`proposal wiki-chat-proposal ${proposal.state}`}>
        <div className="wiki-chat-proposal-head">
          <div>
            <strong>{proposal.title}</strong>
            <small>
              {proposal.proposal_type} / {formatChatWikiProposalState(proposal.state)}
              {proposal.backend_status ? ` / 后端 ${formatTaskStatus(proposal.backend_status)}` : ""}
            </small>
          </div>
          <span>{proposal.review_id || proposal.run_id || proposal.id}</span>
        </div>
        {proposal.summary || proposal.review_summary ? (
          <p>{proposal.review_summary || proposal.summary}</p>
        ) : null}
        <dl className="details wiki-chat-proposal-meta">
          <div>
            <dt>run_id</dt>
            <dd>{proposal.run_id || "无"}</dd>
          </div>
          <div>
            <dt>review_id</dt>
            <dd>{proposal.review_id || "无"}</dd>
          </div>
          <div>
            <dt>审查</dt>
            <dd>{proposal.review_status ? formatTaskStatus(proposal.review_status) : "未知"}</dd>
          </div>
          <div>
            <dt>来源</dt>
            <dd>{proposal.source_hash ? proposal.source_hash.slice(0, 12) : proposal.source_id || "未知"}</dd>
          </div>
        </dl>
        <div className="wiki-chat-proposal-targets" aria-label="Wiki proposal targets">
          <strong>目标页面</strong>
          {targetOptions.length > 0 ? (
            targetOptions.map((targetPath) => (
              <label key={`${proposal.id}-${targetPath}`} className="wiki-chat-proposal-target">
                <input
                  type="checkbox"
                  checked={selectedTargets.has(targetPath)}
                  disabled={!canEditTargets}
                  onChange={(event) =>
                    toggleChatWikiProposalTarget(message.id, proposal.id, targetPath, event.target.checked)
                  }
                />
                <span>{targetPath}</span>
              </label>
            ))
          ) : (
            <span>该提案没有包含目标页面。</span>
          )}
        </div>
        {proposal.findings.length > 0 ? (
          <div className="message-events">
            {proposal.findings.slice(0, 4).map((finding, index) => (
              <span
                key={`${proposal.id}-${finding.code}-${finding.target_path || index}`}
                className={finding.severity === "error" ? "error" : undefined}
              >
                <strong>{formatIssueSeverity(finding.severity)} / {finding.code}</strong>
                {finding.target_path ? `${finding.target_path}: ` : ""}
                {finding.message}
              </span>
            ))}
          </div>
        ) : null}
        {proposal.markdown_preview ? <pre className="diff-preview">{proposal.markdown_preview}</pre> : null}
        {proposal.error ? <p className="field-note error">{proposal.error}</p> : null}
        {resultPaths ? <p className="field-note">已应用页面：{resultPaths}</p> : null}
        <div className="button-row">
          <button
            type="button"
            className="secondary"
            onClick={() => confirmChatWikiProposal(message.id, proposal.id)}
            disabled={!canConfirm}
          >
            <Check size={16} />
            确认
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => rejectChatWikiProposal(message.id, proposal.id)}
            disabled={!canReject}
          >
            <X size={16} />
            拒绝
          </button>
          <button
            type="button"
            onClick={() => void applyChatWikiProposal(message.id, proposal.id)}
            disabled={!canApply}
            title={
              canApply
                ? "将已选择目标应用到 Vault"
                : "需要先确认，并选择至少一个带 run_id 与 review_id 的目标"
            }
          >
            {proposal.state === "applying" ? <Loader2 className="spin" size={16} /> : <FileDown size={16} />}
            应用所选
          </button>
        </div>
      </article>
    );
  }

  function stopStreaming() {
    clearPetStreamWatchdogTimer();
    petStreamFailedRef.current = true;
    streamAbort.current?.abort();
    setStreaming(false);
    showPetBubble({
      title: "已停止",
      message: "本次回复已停止生成。",
      tone: "error",
    });
    schedulePetBubbleHide(5000);
    setMessages((current) =>
      current.map((message) => (message.status === "partial" ? { ...message, status: "cancelled" } : message)),
    );
  }

  async function runMemorySearch(event: FormEvent) {
    event.preventDefault();
    const query = searchQuery.trim();
    if (!query) {
      return;
    }

    setNotice(null);
    setSearchStatus("loading");
    setLastSearchQuery(query);
    try {
      const response = await api.searchMemory(query);
      setSearchResults(response.results);
      setSearchStatus(response.results.length > 0 ? "success" : "empty");
      if (response.results.length === 0) {
        setNotice({
          tone: "info",
          message: getSearchEmptyNotice(query, lastIndexRun, diagnostics),
        });
      }
    } catch (error) {
      setSearchResults([]);
      setSearchStatus("error");
      setNotice({ tone: "error", message: describeError(error, "记忆搜索失败") });
    }
  }

  async function createProposal(event: FormEvent) {
    event.preventDefault();
    if (!proposalDraft.content.trim() || !proposalDraft.target_path.trim()) {
      return;
    }

    setNotice(null);
    const optimisticId = crypto.randomUUID();
    setProposals((current) => [
      {
        ...proposalDraft,
        proposal_id: optimisticId,
        status: "pending",
        preview_markdown: proposalDraft.content,
      },
      ...current,
    ]);

    try {
      const response = await api.createMemoryProposal(proposalDraft);
      setProposals((current) =>
        current.map((proposal) =>
          proposal.proposal_id === optimisticId
            ? {
                ...proposal,
                proposal_id: response.proposal_id,
                status: response.status,
                preview_markdown: response.preview_markdown,
                target_path: response.target_path,
                diff: response.diff || undefined,
                target_content_hash: response.target_content_hash,
              }
            : proposal,
        ),
      );
      setProposalDraft({ type: "fact", content: "", target_path: defaultMemoryTargetPath });
      setNotice({ tone: "success", message: "记忆提案已创建，等待确认写入。" });
    } catch (error) {
      setProposals((current) =>
        current.map((proposal) =>
          proposal.proposal_id === optimisticId
            ? { ...proposal, status: "failed", content: describeError(error, "记忆提案创建失败") }
            : proposal,
        ),
      );
      setNotice({ tone: "error", message: describeError(error, "记忆提案创建失败") });
    }
  }

  async function actOnProposal(proposalId: string, action: "confirm" | "reject") {
    setProposalActionIds((current) => new Set(current).add(proposalId));
    setNotice(null);
    try {
      const response =
        action === "confirm"
          ? await api.confirmMemoryProposal(proposalId)
          : await api.rejectMemoryProposal(proposalId, "用户在桌面审核面板中拒绝。");
      setProposals((current) =>
        current.map((proposal) =>
          proposal.proposal_id === proposalId
            ? {
                ...proposal,
                status: response.status as MemoryProposal["status"],
                written_path: response.written_path,
              }
            : proposal,
        ),
      );
        setNotice({
        tone: "success",
        message:
          action === "confirm"
            ? `记忆提案已确认写入${response.written_path ? `：${response.written_path}` : ""}${response.index_job_id ? `；索引任务 ${response.index_job_id}` : ""}。`
            : "记忆提案已拒绝，目标 Markdown 未写入。",
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "记忆提案操作失败") });
    } finally {
      setProposalActionIds((current) => {
        const next = new Set(current);
        next.delete(proposalId);
        return next;
      });
    }
  }

  async function loadPendingProposals() {
    setLoadingProposals(true);
    setNotice(null);
    try {
      const response = await api.listMemoryProposals();
      setProposals(
        response.proposals.map((proposal) => ({
          ...proposal,
          type: isMemoryProposalType(proposal.type) ? proposal.type : "fact",
          content: proposal.content || proposal.preview_markdown || "",
          status: proposal.status || "pending",
        })),
      );
      setNotice({ tone: "success", message: `已加载 ${response.proposals.length} 条待确认记忆提案。` });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "加载待确认记忆提案失败") });
    } finally {
      setLoadingProposals(false);
    }
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
          message: `连续性状态已刷新：${state.items.length} 个已确认状态，${proposalsResponse.proposals.length} 条待确认提案。`,
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
      setNotice({
        tone: "success",
        message:
          action === "confirm"
            ? "连续性提案已确认，已进入运行时连续性状态；未写入 Vault Markdown。"
            : "连续性提案已拒绝，不会进入提示词或 Live2D 状态。",
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "连续性提案操作失败") });
    } finally {
      setContinuityActionIds((current) => {
        const next = new Set(current);
        next.delete(proposalId);
        return next;
      });
    }
  }

  async function createTask(event: FormEvent) {
    event.preventDefault();
    if (!taskDraft.title.trim()) {
      return;
    }

    setNotice(null);
    try {
      const response = await api.createTask({
        ...taskDraft,
        due_at: taskDraft.due_at || null,
        remind_at: taskDraft.remind_at || null,
      });
      setNotice({
        tone: "success",
        message: `任务 ${response.task_id} 已保存，状态：${formatTaskStatus(response.status)}。`,
      });
      triggerLive2DTaskStage();
      setTaskDraft((current) => ({ ...current, title: "", description: "", due_at: "", remind_at: "" }));
      void loadTasks();
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "任务创建失败") });
    }
  }

  async function loadTasks() {
    setLoadingTasks(true);
    try {
      const response = await api.listTasks();
      setTasks(response.tasks);
      void notifyTriggeredReminders(response.tasks);
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "任务加载失败") });
    } finally {
      setLoadingTasks(false);
    }
  }

  async function loadTasksSilently() {
    try {
      const response = await api.listTasks();
      setTasks(response.tasks);
      void notifyTriggeredReminders(response.tasks);
    } catch {
      // 后台轮询只负责捕获到期提醒；连接或鉴权错误由手动刷新和健康检查展示。
    }
  }

  async function notifyTriggeredReminders(items: TaskItem[]) {
    const notify = window.agentDesktop?.showReminderNotification;
    if (!notify) {
      if (items.some((task) => task.reminder_id?.trim() && task.reminder_status === "triggered")) {
        setLastReminderNotification({
          status: "unsupported",
          detail: "当前运行环境不支持系统通知。",
        });
      }
      return;
    }

    for (const task of items) {
      const reminderId = task.reminder_id?.trim();
      if (!reminderId || task.reminder_status !== "triggered") {
        continue;
      }
      if (triggeredReminderNotificationIds.current.has(reminderId)) {
        continue;
      }
      triggeredReminderNotificationIds.current.add(reminderId);
      const result = await notify({
        reminder_id: reminderId,
        title: task.title || "桌面记忆助手提醒",
        body: task.description || task.source_text || task.remind_at || "提醒已到期。",
      });
      setLastReminderNotification({
        status: result.status,
        detail:
          result.status === "shown"
            ? `已发送提醒：${task.title || reminderId}`
            : result.reason || `提醒 ${reminderId} 返回 ${result.status}`,
      });
      if (result.status === "unsupported" || result.status === "failed") {
        setNotice({
          tone: "error",
          message: `系统通知未送达：${result.reason || result.status}`,
        });
      }
    }
  }

  async function actOnTask(taskId: string, action: "complete" | "cancel") {
    setTaskActionIds((current) => new Set(current).add(taskId));
    setNotice(null);
    try {
      const response = action === "complete" ? await api.completeTask(taskId) : await api.cancelTask(taskId);
      setTasks((current) =>
        current.map((task) => (task.task_id === taskId ? { ...task, status: response.status } : task)),
      );
      setNotice({ tone: "success", message: `任务 ${response.task_id} 已标记为 ${formatTaskStatus(response.status)}。` });
      triggerLive2DTaskStage();
      void loadTasks();
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "任务操作失败") });
    } finally {
      setTaskActionIds((current) => {
        const next = new Set(current);
        next.delete(taskId);
        return next;
      });
    }
  }

  async function exportDiagnostics() {
    setExportingDiagnostics(true);
    setNotice(null);
    try {
      const response = await api.exportDiagnostics();
      setDiagnostics(response);
      setVaultId(response.vault.active_vault_id || null);
      setSettingsStatus((current) => ({
        model_provider: current?.model_provider || null,
        model_base_url: current?.model_base_url || null,
        chat_model: current?.chat_model || null,
        model_configured: response.model_configured,
        vault_configured: response.vault.configured,
        agent_models: current?.agent_models,
      }));
      setNotice({ tone: "success", message: `诊断信息已导出：${response.generated_at}。` });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "诊断信息导出失败") });
    } finally {
      setExportingDiagnostics(false);
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
      setPetReplyText("");
      setMessages([]);
      setSearchResults([]);
      setSearchStatus("idle");
      setLastSearchQuery("");
      setProposals([]);
      setTasks([]);
      setContinuityState(null);
      setContinuityProposals([]);
      setLatestContinuitySignal(null);
      setDiagnostics(null);
      setVaultId(null);
      setVaultPath("");
      setLastIndexRun(null);
      setWikiPreview(null);
      setWikiReviewResult(null);
      setWikiApplyResult(null);
      setWikiLintResult(null);
      setWikiSchemaStatus(null);
      setWikiIndexStatus(null);
      setWikiLogStatus(null);
      setWikiCoreStatus("idle");
      setWikiCoreError("");
      setWikiArchiveHistory([]);
      setWikiArchiveHistoryStatus("idle");
      setWikiArchiveHistoryError("");
      setWikiOpenedArchive(null);
      setLastWikiArchiveId(null);
      setAgentModelDrafts(defaultAgentModelDrafts());
      setAgentModelTestResults({});
      setSettingsStatus(null);
      setBusinessAuthStatus("ready");
      setBusinessAuthMessage("业务接口鉴权可用，本地状态已重置。");
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

  async function loadSettingsStatus(options: { silent?: boolean; signal?: AbortSignal } = {}) {
    setLoadingSettingsStatus(true);
    if (!options.silent) {
      setNotice(null);
    }
    try {
      const response = await api.getSettingsStatus(options.signal);
      applySettingsStatus(response);
      setBusinessAuthStatus("ready");
      setBusinessAuthMessage("业务接口鉴权可用。");
      if (!options.silent) {
        setNotice({ tone: "success", message: "设置状态已刷新。" });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      markBusinessAuthFailure(error);
      if (!options.silent) {
        setNotice({ tone: "error", message: describeError(error, "设置状态读取失败") });
      }
    } finally {
      setLoadingSettingsStatus(false);
    }
  }

  async function checkBusinessAccess(options: { silent?: boolean; signal?: AbortSignal } = {}): Promise<boolean> {
    setBusinessAuthStatus("checking");
    setBusinessAuthMessage("正在检查业务接口鉴权。");
    try {
      const response = await api.getSettingsStatus(options.signal);
      applySettingsStatus(response);
      setBusinessAuthStatus("ready");
      setBusinessAuthMessage("业务接口鉴权可用。");
      return true;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setBusinessAuthStatus("unknown");
        setBusinessAuthMessage("业务接口鉴权检查已取消。");
        return false;
      }
      markBusinessAuthFailure(error);
      if (error instanceof ApiError && error.status === 401) {
        setNotice({ tone: "error", message: businessAuthMismatchMessage() });
      } else if (!options.silent) {
        setNotice({ tone: "error", message: describeError(error, "业务接口鉴权检查失败") });
      }
      return false;
    }
  }

  function applySettingsStatus(response: SettingsStatusResponse) {
    setSettingsStatus(response);
    setAgentModelDrafts((current) => mergeAgentModelStatus(current, response.agent_models));
  }

  function markBusinessAuthFailure(error: unknown) {
    if (error instanceof ApiError && error.status === 401) {
      setBusinessAuthStatus("unauthorized");
      setBusinessAuthMessage("后端已启动，但业务接口鉴权失败。可能已有 8765 后端和当前桌面端会话令牌不一致。");
      return;
    }
    setBusinessAuthStatus("error");
    setBusinessAuthMessage(describeError(error, "业务接口鉴权检查失败"));
  }

  function updateAgentModelDraft(agentId: AgentModelId, patch: Partial<AgentModelDraft>) {
    setAgentModelDrafts((current) =>
      current.map((draft) => (draft.agent_id === agentId ? { ...draft, ...patch } : draft)),
    );
  }

  async function saveAgentModel(agentId: AgentModelId) {
    const draft = agentModelDrafts.find((item) => item.agent_id === agentId);
    if (!draft) {
      return;
    }
    if (!draft.provider.trim() || !draft.base_url.trim() || !draft.model.trim()) {
      setNotice({ tone: "error", message: "请填写智能体的提供方、接口地址和模型。" });
      return;
    }
    const provider = normalizeProviderDraft(draft.provider);
    if (!isSupportedProviderDraft(provider)) {
      setNotice({ tone: "error", message: "当前只支持 OpenAI 兼容接口；提供方请填写 openai-compatible。" });
      return;
    }
    if (!draft.masked && !draft.api_key.trim()) {
      setNotice({ tone: "error", message: "请填写智能体 API 密钥后再保存。" });
      return;
    }

    setSavingAgentModelIds((current) => new Set(current).add(agentId));
    setNotice(null);
    try {
      const config = await api.saveAgentModelConfig({
        agent_id: agentId,
        provider,
        base_url: draft.base_url.trim(),
        model: draft.model.trim(),
      });
      const keyStatus = draft.api_key.trim()
        ? await api.saveAgentModelKey({
            agent_id: agentId,
            provider: config.provider,
            api_key: draft.api_key.trim(),
          })
        : config;
      const masked = keyStatus.masked || config.masked || draft.masked;
      const savedDraftPatch: Partial<AgentModelDraft> = {
        provider: config.provider,
        base_url: config.base_url,
        model: config.model,
        api_key: "",
        configured: Boolean(masked),
        masked: masked || "",
        saved_provider: config.provider,
        saved_base_url: config.base_url,
        saved_model: config.model,
      };
      updateAgentModelDraft(agentId, savedDraftPatch);
      setSettingsStatus((current) =>
        current?.agent_models
          ? {
              ...current,
              agent_models: current.agent_models.map((item) =>
                item.agent_id === agentId
                  ? {
                      ...item,
                      provider: config.provider,
                      base_url: config.base_url,
                      model: config.model,
                      configured: Boolean(masked),
                      masked,
                    }
                  : item,
              ),
            }
          : current,
      );
      setAgentModelTestResults((current) => ({ ...current, [agentId]: undefined }));
      setNotice({
        tone: "success",
        message: `${agentLabel(agentId)} 模型配置已保存${masked ? `：${masked}` : "，请继续填写密钥"}。`,
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, `${agentLabel(agentId)} 模型配置保存失败`) });
    } finally {
      setSavingAgentModelIds((current) => {
        const next = new Set(current);
        next.delete(agentId);
        return next;
      });
    }
  }

  async function testAgentModelConnection(agentId: AgentModelId) {
    const draft = agentModelDrafts.find((item) => item.agent_id === agentId);
    if (draft && hasUnsavedAgentModelDraft(draft)) {
      setNotice({ tone: "error", message: `${agentLabel(agentId)} 有未保存的模型配置，请先保存后再试连。` });
      return;
    }
    if (draft && !isSupportedProviderDraft(draft.saved_provider || draft.provider)) {
      setNotice({ tone: "error", message: "当前只支持 OpenAI 兼容接口；提供方请保存为 openai-compatible 后再试连。" });
      return;
    }
    setTestingAgentModelIds((current) => new Set(current).add(agentId));
    setAgentModelTestResults((current) => ({ ...current, [agentId]: undefined }));
    setNotice(null);
    try {
      const response = await api.testAgentModelConnection(agentId);
      setAgentModelTestResults((current) => ({ ...current, [agentId]: response }));
      setNotice({
        tone: response.status === "ok" ? "success" : "error",
        message: response.message || `${agentLabel(agentId)} 模型试连${response.status === "ok" ? "成功" : "失败"}。`,
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, `${agentLabel(agentId)} 模型试连失败`) });
    } finally {
      setTestingAgentModelIds((current) => {
        const next = new Set(current);
        next.delete(agentId);
        return next;
      });
    }
  }

  async function selectVaultDirectory() {
    if (!window.agentDesktop?.selectKnowledgeBaseFolder) {
      setNotice({
        tone: "info",
        message: isElectronRuntime
          ? "当前桌面端未提供文件夹选择能力，请手动填写知识库路径。"
          : "浏览器模式无法打开系统文件夹选择器，请手动填写知识库路径。",
      });
      return;
    }

    try {
      const selectedPath = await window.agentDesktop.selectKnowledgeBaseFolder();
      if (!selectedPath) {
        return;
      }

      setVaultPath(selectedPath);
      setNotice({ tone: "info", message: "已填入知识库路径，请确认后点击初始化。" });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "文件夹选择失败") });
    }
  }

  async function bindVault(event: FormEvent) {
    event.preventDefault();
    if (!vaultPath.trim()) {
      return;
    }

    setIndexingVault(true);
    setNotice(null);
    try {
      const response = await api.initVault(vaultPath.trim(), true);
      setVaultId(response.vault_id);
      if (response.root_path) {
        setVaultPath(response.root_path);
      }
      try {
        const indexResponse = await api.indexVault(response.vault_id);
        setLastIndexRun({
          vaultId: response.vault_id,
          jobId: indexResponse.index_job_id,
          status: indexResponse.status,
          filesSeen: indexResponse.files_seen,
          filesIndexed: indexResponse.files_indexed,
        });
        setNotice({
          tone: "success",
          message: `知识库 ${response.vault_id} 已${formatVaultStatus(response.status)}；索引任务 ${indexResponse.index_job_id} 状态：${formatTaskStatus(indexResponse.status)}。`,
        });
      } catch (indexError) {
        setNotice({
          tone: "error",
          message: describeError(indexError, `知识库 ${response.vault_id} 已初始化，但自动索引失败`),
        });
      }
      await loadSettingsStatus({ silent: true });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "知识库初始化失败") });
    } finally {
      setIndexingVault(false);
    }
  }

  async function loadVaultStatus(options: { silent?: boolean; signal?: AbortSignal } = {}) {
    try {
      const response = await api.getVaultStatus(options.signal);
      setVaultId(response.active_vault_id || null);
      setVaultPath(response.root_path || "");
      if (!options.silent) {
        setNotice({
          tone: "success",
          message: response.configured
            ? `当前知识库：${response.root_path || response.active_vault_id || "已配置"}。`
            : "尚未配置知识库。",
        });
      }
      await loadSettingsStatus({ silent: true });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (!options.silent) {
        setNotice({ tone: "error", message: describeError(error, "知识库状态读取失败") });
      }
    }
  }

  async function rebuildIndex() {
    if (!vaultId) {
      setNotice({ tone: "error", message: "请先加载或初始化知识库，再启动索引任务。" });
      return;
    }

    setIndexingVault(true);
    setNotice(null);
    try {
      const response = await api.indexVault(vaultId);
      setLastIndexRun({
        vaultId,
        jobId: response.index_job_id,
        status: response.status,
        filesSeen: response.files_seen,
        filesIndexed: response.files_indexed,
      });
      setNotice({ tone: "success", message: `索引任务 ${response.index_job_id} 状态：${formatTaskStatus(response.status)}。` });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "重建索引失败") });
    } finally {
      setIndexingVault(false);
    }
  }

  async function loadWikiArchiveHistory(options: { silent?: boolean } = {}) {
    setWikiArchiveHistoryStatus("loading");
    setWikiArchiveHistoryError("");
    if (!options.silent) {
      setNotice(null);
    }

    try {
      const response = await api.listWikiQueryArchives(20);
      setWikiArchiveHistory(response.archives);
      setWikiArchiveHistoryStatus(response.archives.length > 0 ? "success" : "empty");
      if (!options.silent) {
        setNotice({
          tone: "success",
          message: `Wiki 查询归档历史已刷新：${response.archives.length} 条。`,
        });
      }
    } catch (error) {
      const message = describeError(error, "Wiki 查询归档历史刷新失败");
      setWikiArchiveHistoryStatus("error");
      setWikiArchiveHistoryError(message);
      if (!options.silent) {
        setNotice({ tone: "error", message });
      }
    }
  }

  async function loadWikiCoreStatus(options: { silent?: boolean } = {}) {
    setWikiCoreStatus("loading");
    setWikiCoreError("");
    if (!options.silent) {
      setNotice(null);
    }
    try {
      const [schema, index, log] = await Promise.all([
        api.getWikiSchema(),
        api.getWikiIndex(),
        api.getWikiLog(20),
      ]);
      setWikiSchemaStatus(schema);
      setWikiIndexStatus(index);
      setWikiLogStatus(log);
      setWikiCoreStatus("success");
      if (!options.silent) {
        setNotice({
          tone: "success",
          message: `Wiki 核心状态已刷新：${index.entries.length} 条索引，${log.entries.length} 条日志。`,
        });
      }
    } catch (error) {
      const message = describeError(error, "Wiki 核心状态刷新失败");
      setWikiCoreStatus("error");
      setWikiCoreError(message);
      if (!options.silent) {
        setNotice({ tone: "error", message });
      }
    }
  }

  async function openWikiQueryArchive(archiveId: string) {
    const normalizedArchiveId = archiveId.trim();
    if (!normalizedArchiveId) {
      setNotice({ tone: "error", message: "缺少 Wiki 查询归档 ID。" });
      return;
    }

    setWikiOpeningArchiveId(normalizedArchiveId);
    setNotice(null);
    try {
      const detail = await api.getWikiQueryArchive(normalizedArchiveId);
      const detailArchiveId = getWikiArchiveId(detail) || normalizedArchiveId;
      const citationLinks = uniqueCompactList(detail.citations.map((citation) => citation.relative_path));
      setWikiOpenedArchive(detail);
      setLastWikiArchiveId(detailArchiveId);
      setWikiDraft((current) => ({
        ...current,
        title: detail.title,
        content: detail.answer,
        source_type: "query_archive",
        source_uri: detail.page.relative_path,
        target_path: detail.target_path || detail.page.relative_path,
        section: detail.section || "",
        tags: detail.tags,
        links: citationLinks,
        archive_id: detailArchiveId,
        archive_question: detail.question,
        archive_answer: detail.answer,
        archive_citations: detail.citations,
      }));
      setWikiTagInput(detail.tags.join(", "));
      setWikiLinkInput(citationLinks.join(", "));
      setWikiPreview(null);
      setWikiReviewResult(null);
      setWikiApprovedTargetsInput("");
      setNotice({
        tone: "success",
        message: `已打开 Wiki 查询归档：${detailArchiveId}。`,
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "Wiki 查询归档打开失败") });
    } finally {
      setWikiOpeningArchiveId(null);
    }
  }

  function buildWikiIngestRequest(): WikiIngestRequest | null {
    const title = wikiDraft.title.trim();
    const content = wikiDraft.content.trim();
    if (!title || !content) {
      setNotice({ tone: "error", message: "写入 Wiki 前需要同时填写标题和内容。" });
      return null;
    }

    return {
      title,
      content,
      source_type: wikiDraft.source_type?.trim() || "manual",
      source_uri: emptyToNull(wikiDraft.source_uri),
      tags: parseCompactList(wikiTagInput),
      links: parseCompactList(wikiLinkInput),
      max_pages: clampWikiMaxPages(wikiDraft.max_pages),
    };
  }

  async function previewWikiIngest(event: FormEvent) {
    event.preventDefault();
    const request = buildWikiIngestRequest();
    if (!request) {
      return;
    }

    setWikiWorkflowAction("preview");
    setNotice(null);
    try {
      const response = await api.previewWikiIngest(request);
      setWikiPreview(response);
      setWikiReviewResult(null);
      setWikiApprovedTargetsInput("");
      setWikiApplyResult(null);
      setNotice({
        tone: "success",
        message: `Wiki 写入预览 ${formatTaskStatus(response.status)}：计划更新 ${response.page_plans.length} 个页面。`,
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "Wiki 写入预览失败") });
    } finally {
      setWikiWorkflowAction(null);
    }
  }

  async function applyWikiIngest() {
    if (!wikiPreview) {
      setNotice({ tone: "error", message: "请先运行 Wiki 写入预览，再应用页面更新。" });
      return;
    }

    const approvedTargets = parseCompactList(wikiApprovedTargetsInput);
    setWikiWorkflowAction("apply");
    setNotice(null);
    try {
      const response = await api.applyWikiIngest({
        run_id: wikiPreview.run_id,
        approved_targets: approvedTargets.length > 0 ? approvedTargets : wikiPreview.page_plans.map((plan) => plan.target_path),
        review_id: wikiReviewResult?.review_id ?? null,
        review_acknowledged: Boolean(wikiReviewResult),
      });
      setWikiApplyResult(response);
      void loadWikiCoreStatus({ silent: true });
      const firstIndexedPage = response.page_results.find((page) => page.index_job_id);
      setNotice({
        tone: response.status === "applied" ? "success" : "info",
        message: `Wiki 写入${formatTaskStatus(response.status)}：已写入 ${response.pages_written}/${response.page_results.length} 个页面。`,
      });
      if (firstIndexedPage?.index_job_id) {
        setLastIndexRun({
          vaultId: vaultId || diagnostics?.vault.active_vault_id || "wiki",
          jobId: firstIndexedPage.index_job_id,
          status: response.status,
        });
      }
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "Wiki 写入应用失败") });
    } finally {
      setWikiWorkflowAction(null);
    }
  }

  async function reviewWikiIngest() {
    if (!wikiPreview) {
      setNotice({ tone: "error", message: "请先运行 Wiki 写入预览，再运行审查。" });
      return;
    }

    setWikiWorkflowAction("review");
    setNotice(null);
    try {
      const response = await api.reviewWikiIngest({
        run_id: wikiPreview.run_id,
        reviewer_agent_id: "wiki_manager_agent",
        force_refresh: wikiReviewForceRefresh,
      });
      setWikiReviewResult(response);
      setNotice({
        tone: response.status === "failed" ? "error" : response.status === "model_not_configured" ? "info" : "success",
        message: `Wiki 审查${formatTaskStatus(response.status)}：${response.findings.length} 个发现，${response.recommended_targets.length} 个推荐目标。`,
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "Wiki 写入审查失败") });
    } finally {
      setWikiWorkflowAction(null);
    }
  }

  function useWikiReviewRecommendedTargets() {
    if (!wikiReviewResult?.recommended_targets.length) {
      setNotice({ tone: "error", message: "当前审查结果没有推荐目标。" });
      return;
    }
    setWikiApprovedTargetsInput(wikiReviewResult.recommended_targets.join(", "));
    setNotice({
      tone: "info",
      message: `已填入 ${wikiReviewResult.recommended_targets.length} 个推荐应用目标；应用前仍可手动调整。`,
    });
  }

  async function archiveLatestWikiQuery() {
    const localMessage = findLatestArchivableAssistantMessage(messages);
    const candidate = localMessage
      ? {
          conversation_id: conversationId,
          message: localMessage,
          question: findQuestionForAssistantMessage(messages, localMessage.id),
        }
      : wikiArchiveCandidate;
    const message = candidate?.message;
    const citations = message?.citations?.filter(isKnowledgeBaseCitation) || [];
    if (!message || citations.length === 0) {
      setNotice({
        tone: "error",
        message: "当前没有可归档的已完成助手回复；需要回复中包含知识库引用。",
      });
      return;
    }

    setWikiWorkflowAction("archive");
    setNotice(null);
    try {
      const archiveCitations = citations.map(toMemorySearchResultCitation);
      const response = await api.archiveWikiQuery({
        question:
          candidate?.question ||
          findQuestionForAssistantMessage(messages, message.id) ||
          "已归档的 Wiki 查询",
        answer: message.content,
        citations: archiveCitations,
        title: wikiDraft.title.trim() || buildWikiArchiveTitle(citations),
        target_path: emptyToNull(wikiDraft.target_path),
        section: emptyToNull(wikiDraft.section),
        tags: parseCompactList(wikiTagInput),
        agent_run_id: message.agent_run_id ?? null,
        source_message_id: message.id,
        allow_mixed_sources: wikiDraft.allow_mixed_sources,
      });
      setWikiApplyResult(response);
      if (response.archive_id) {
        setLastWikiArchiveId(response.archive_id);
      }
      void loadWikiCoreStatus({ silent: true });
      setNotice({
        tone: "success",
        message: `查询已归档${response.archive_id ? `：${response.archive_id}` : ""}，页面 ${response.page.relative_path}，引用 ${response.lint.normalized_citations.length} 条。`,
      });
      if (response.page.index_job_id) {
        setLastIndexRun({
          vaultId: vaultId || diagnostics?.vault.active_vault_id || "wiki",
          jobId: response.page.index_job_id,
          status: response.page.status,
        });
      }
      await loadWikiArchiveHistory({ silent: true });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "Wiki 查询归档失败") });
    } finally {
      setWikiWorkflowAction(null);
    }
  }

  async function synthesizeWiki() {
    const title = wikiDraft.title.trim();
    const content = wikiDraft.content.trim();
    if (!title || !content) {
      setNotice({ tone: "error", message: "综合整理 Wiki 前需要同时填写标题和内容。" });
      return;
    }

    const sourcePaths = parseCompactList(wikiLinkInput);
    setWikiWorkflowAction("synthesize");
    setNotice(null);
    try {
      const response = await api.synthesizeWiki({
        title,
        content,
        source_paths: sourcePaths,
        target_path: emptyToNull(wikiDraft.target_path),
        tags: parseCompactList(wikiTagInput),
        links: sourcePaths,
      });
      setWikiApplyResult(response);
      setWikiPreview(null);
      void loadWikiCoreStatus({ silent: true });
      setNotice({
        tone: "success",
        message: `Wiki 综合整理已写入：${response.page.relative_path}。`,
      });
      if (response.page.index_job_id) {
        setLastIndexRun({
          vaultId: vaultId || diagnostics?.vault.active_vault_id || "wiki",
          jobId: response.page.index_job_id,
          status: response.page.status,
        });
      }
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "Wiki 综合整理失败") });
    } finally {
      setWikiWorkflowAction(null);
    }
  }

  async function runWikiLint() {
    setWikiWorkflowAction("lint");
    setNotice(null);
    try {
      const response = await api.runWikiLint({ write_report: wikiDraft.write_report });
      setWikiLintResult(response);
      void loadWikiCoreStatus({ silent: true });
      setNotice({
        tone: response.issues.length > 0 ? "info" : "success",
        message: `Wiki 检查完成：${response.summary.pages ?? 0} 个页面，${response.issues.length} 个问题。`,
      });
    } catch (error) {
      setNotice({ tone: "error", message: describeError(error, "Wiki 检查运行失败") });
    } finally {
      setWikiWorkflowAction(null);
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

  function openControlFromPet(targetId?: string) {
    endPetDrag();
    void window.agentDesktop?.openControlWindow?.(targetId);
  }

  function scrollToWorkflowTarget(targetId?: string) {
    if (!targetId) {
      return;
    }
    document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const hasConnection = sidecarStatus?.state === "ready" || health?.status === "ok";
  const hasBusinessAuth = businessAuthStatus === "ready";
  const hasAllAgentModelsConfigured = agentModelDrafts.every((draft) => draft.configured);
  const hasAllAgentModelsTested = agentModelDrafts.every(
    (draft) => agentModelTestResults[draft.agent_id]?.status === "ok",
  );
  const hasVaultSelection = Boolean(vaultPath.trim() || vaultId || diagnostics?.vault.active_vault_id);
  const hasVaultInitialized = Boolean(vaultId || diagnostics?.vault.configured);
  const hasIndexSignal = Boolean(
    lastIndexRun ||
      searchResults.length > 0 ||
      diagnostics?.recent_index_jobs.some((job) =>
        ["completed", "done", "indexed", "success"].includes(job.status.toLowerCase()),
      ),
  );
  const hasSearchRun = searchStatus === "success" || searchStatus === "empty";
  const hasMemoryCreated = proposals.length > 0;
  const hasMemoryConfirmed = proposals.some((proposal) => proposal.status === "confirmed" || Boolean(proposal.written_path));
  const pendingContinuityCount = continuityProposals.filter((proposal) => proposal.status === "pending").length;
  const hasContinuityState = Boolean(continuityState?.items.length);
  const latestContinuityProposal = continuityProposals[0];
  const hasTaskCreated = tasks.length > 0;
  const hasDiagnosticsExport = Boolean(diagnostics);
  const hasAgentEventSignal = messages.some((message) => (message.events || []).length > 0 || (message.citations || []).length > 0);
  const pendingProposalCount = proposals.filter((proposal) => proposal.status === "pending").length;
  const latestAssistantMessage = messages.filter((message) => message.role === "assistant").slice(-1)[0];
  const latestLocalArchivableAssistantMessage = findLatestArchivableAssistantMessage(messages);
  const latestArchiveMessage = latestLocalArchivableAssistantMessage || wikiArchiveCandidate?.message;
  const latestKnowledgeCitations = latestArchiveMessage?.citations?.filter(isKnowledgeBaseCitation) || [];
  const latestChatEvent = latestAssistantMessage?.events?.slice(-1)[0];
  const activeContinuitySignal = latestAssistantMessage?.continuity_signal || latestContinuitySignal;
  const latestCitation = latestAssistantMessage?.citations?.slice(-1)[0];
  const latestProposal = proposals[0];
  const latestTask = tasks[0];
  const triggeredReminderCount = tasks.filter((task) => task.reminder_status === "triggered").length;
  const latestCitationTargetId = latestCitation ? findCitationTargetId(latestCitation, searchResults) : undefined;
  const recentControlMessages = messages.slice(-6);
  const wikiWorkflowBusy = wikiWorkflowAction !== null;
  const wikiLintIssueCount = wikiLintResult?.summary.issues ?? wikiLintResult?.issues.length ?? 0;
  const wikiArchiveHistoryLoading = wikiArchiveHistoryStatus === "loading";
  const wikiArchiveHistorySummary =
    wikiArchiveHistoryStatus === "error"
      ? wikiArchiveHistoryError
      : wikiArchiveHistoryLoading
        ? "加载中"
        : wikiArchiveHistory.length > 0
          ? `${wikiArchiveHistory.length} 条近期归档`
          : "暂无归档";
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
      label: "Agent 对话事件",
      status: hasAgentEventSignal ? "done" : streaming ? "active" : "blocked",
      detail: latestChatEvent
        ? `${latestChatEvent.label}：${latestChatEvent.detail}`
        : latestCitation
          ? `引用：${latestCitation.relative_path}`
          : streaming
            ? "正在等待 SSE 工具事件。"
            : "向 Agent 提问后显示检索、记忆、任务或引用事件。",
      targetId: latestCitationTargetId,
    },
    {
      label: "记忆提案",
      status: pendingProposalCount > 0 || hasMemoryCreated ? "active" : hasMemoryConfirmed ? "done" : "blocked",
      detail:
        pendingProposalCount > 0
          ? `${pendingProposalCount} 条待确认记忆；确认后才会写入目标 Markdown 并进入长期记忆检索。`
          : hasMemoryConfirmed
            ? "已有记忆提案确认写入长期记忆。"
            : "不确定或需审核的内容会先进入待确认记忆。",
      targetId: latestProposal ? `memory-proposal-${latestProposal.proposal_id}` : undefined,
    },
    {
      label: "连续性状态",
      status: hasContinuityState ? "done" : pendingContinuityCount > 0 ? "active" : "blocked",
      detail:
        pendingContinuityCount > 0
          ? `${pendingContinuityCount} 条连续性提案待确认；确认后只进入运行时 SQLite 状态。`
          : hasContinuityState
            ? `已确认 ${continuityState?.items.length ?? 0} 个连续性状态。`
            : "情绪、关系、身份连续性会先进入审核队列。",
      targetId: latestContinuityProposal ? `continuity-proposal-${latestContinuityProposal.proposal_id}` : "continuity-panel",
    },
    {
      label: "任务 / 提醒",
      status: triggeredReminderCount > 0 || hasTaskCreated ? "done" : "blocked",
      detail: hasTaskCreated
        ? `${tasks.length} 条任务；通知：${formatReminderNotificationStatus(lastReminderNotification)}`
        : "通过聊天或表单创建任务/提醒。",
      targetId: latestTask ? `task-${latestTask.task_id}` : undefined,
    },
  ];
  const live2dStage = getLive2DStageView({
    connected: hasConnection,
    streaming,
    searchResultCount: searchResults.length,
    pendingProposalCount,
    taskCount: recentTaskStageActive ? Math.max(tasks.length, 1) : 0,
    diagnosticsReady: hasDiagnosticsExport,
    continuityState,
    continuitySignal: activeContinuitySignal,
  });
  const live2dRuntime = createLive2DRuntimeBoundary(live2dAsset);
  const petHitboxDebug =
    windowMode === "pet" && new URLSearchParams(window.location.search).get("hitbox") === "1";
  if (windowMode === "pet") {
    return (
      <main
        className={`pet-shell${petHitboxDebug ? " pet-debug-hitbox" : ""}`}
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
            onContextMenu: () => {
              endPetDrag();
            },
            onDoubleClick: () => {
              endPetDrag();
              showPetInput();
            },
          }}
        />
        {petBubble.visible ? (
          <div
            className={`pet-agent-bubble ${petBubble.tone}`}
            role="status"
            aria-live="polite"
            onPointerDown={(event) => event.stopPropagation()}
            onPointerMove={(event) => event.stopPropagation()}
            onPointerUp={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              advancePetBubblePageManually();
            }}
            onDoubleClick={(event) => event.stopPropagation()}
          >
            <strong>
              {petBubble.title}
              {petBubble.continueHint ? <span className="pet-agent-bubble-page">{petBubble.continueHint}</span> : null}
            </strong>
            <div
              className="pet-agent-bubble-text"
              tabIndex={petBubble.tone === "reply" ? 0 : undefined}
              onPointerEnter={() => pausePetBubblePaging()}
              onPointerLeave={() => resumePetBubblePaging()}
              onFocus={() => pausePetBubblePaging()}
              onBlur={() => resumePetBubblePaging()}
              onWheel={() => {
                pausePetBubblePaging();
              }}
            >
              {petBubble.message}
            </div>
          </div>
        ) : null}
        {petInputVisible ? (
          <form
            className="pet-input-dock"
            aria-label="桌宠输入框"
            onSubmit={sendPetMessage}
            onPointerDown={(event) => event.stopPropagation()}
            onPointerMove={(event) => event.stopPropagation()}
            onPointerUp={(event) => event.stopPropagation()}
            onDoubleClick={(event) => event.stopPropagation()}
          >
            <input
              ref={petInputRef}
              value={petInput}
              onChange={(event) => setPetInput(event.target.value)}
              placeholder={hasConnection ? "和桌宠聊天..." : "等待本地后端连接..."}
              disabled={streaming}
              onKeyDown={(event) => {
                if (event.key === "Escape" && !streaming) {
                  setPetInputVisible(false);
                }
              }}
            />
            {streaming ? (
              <button type="button" className="danger" onClick={stopStreaming} title="停止生成">
                <X size={14} />
              </button>
            ) : (
              <button type="submit" title="发送给桌宠" disabled={!petInput.trim()}>
                <Send size={14} />
              </button>
            )}
          </form>
        ) : null}
      </main>
    );
  }

  const trialGuideItems = [
    {
      label: "后端可达",
      done: hasConnection,
      detail: hasConnection ? formatSidecarStatus(sidecarStatus, health) : "先连接本地 Agent sidecar",
    },
    {
      label: "业务鉴权",
      done: hasBusinessAuth,
      detail: businessAuthMessage,
    },
    {
      label: "智能体模型",
      done: hasAllAgentModelsConfigured,
      detail: hasAllAgentModelsTested
        ? `${agentModelCountLabel} 模型均已试连成功`
        : hasAllAgentModelsConfigured
          ? `${agentModelCountLabel} 模型已保存，建议逐个试连`
          : `保存 ${agentModelCountLabel} 的模型配置和密钥`,
    },
    {
      label: "绑定 Obsidian",
      done: hasVaultSelection,
      detail: vaultPath || vaultId || diagnostics?.vault.active_vault_id || "选择或填写 Obsidian/Markdown Vault 路径",
    },
    {
      label: "索引 Vault",
      done: hasVaultInitialized && hasIndexSignal,
      detail: hasIndexSignal ? "已有搜索结果或诊断索引记录" : "初始化 Vault 后运行索引",
    },
    {
      label: "Agent 检索",
      done: hasSearchRun,
      detail:
        searchStatus === "empty"
          ? `已搜索“${lastSearchQuery}”，没有命中结果`
          : hasSearchRun
            ? `已显示 ${searchResults.length} 条搜索结果`
            : "执行一次记忆或 Vault 检索",
    },
    {
      label: "创建/确认记忆",
      done: hasMemoryConfirmed,
      detail: hasMemoryConfirmed
        ? "已有确认写入的记忆提案"
        : hasMemoryCreated
          ? "已有提案，继续确认写入"
          : "创建一条记忆提案并确认",
    },
    {
      label: "创建任务",
      done: hasTaskCreated,
      detail: hasTaskCreated ? `已加载或创建 ${tasks.length} 条任务` : "创建一条任务并检查列表",
    },
    {
      label: "Agent 事件",
      done: hasAgentEventSignal,
      detail: hasAgentEventSignal ? "聊天中已收到状态、引用或工具事件" : "向 Agent 发送搜索、记忆或任务类请求",
    },
    {
      label: "导出诊断",
      done: hasDiagnosticsExport,
      detail: diagnostics?.generated_at || "导出一次诊断快照",
    },
  ];
  const completedTrialGuideCount = trialGuideItems.filter((item) => item.done).length;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Agent + Obsidian</p>
          <h1>本地 Agent 工作台</h1>
        </div>
        <div className="status-strip" aria-live="polite">
          <span className={sidecarStatus?.state === "ready" || health?.status === "ok" ? "status-dot online" : "status-dot"} />
          <span>{formatSidecarStatus(sidecarStatus, health)}</span>
        </div>
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

        <Panel id="agent-workspace-panel" icon={<MessageSquareText size={18} />} title="Agent + Obsidian" className="chat-panel">
          <section className="stack" aria-label="Agent 对话和 Obsidian 记忆工作流">
            <div className="section-heading">
              <strong>和 Agent 对话</strong>
              <span>主流程是让 Agent 检索、整理并生成确认写入计划；高级 Vault 维护默认折叠，只保留给手工维护。</span>
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
                placeholder={hasConnection ? "询问 Agent，让它引用 Vault、整理记忆或创建任务..." : "等待本地 Agent sidecar 连接..."}
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
            <div className="message-list" aria-label="Agent 对话记录">
              {recentControlMessages.length > 0 ? (
                recentControlMessages.map((message) => (
                  <article key={message.id} className={`message ${message.role}`}>
                    <div className="message-meta">
                      <strong>{formatMessageRole(message.role)}</strong>
                      {message.status ? <span>{formatRunStatus(message.status)}</span> : null}
                    </div>
                    <p>{message.content || (message.status === "partial" ? "Agent 正在生成回复..." : "无内容")}</p>
                    {message.citations?.length ? (
                      <div className="message-events">
                        {message.citations.slice(0, 4).map((citation) => (
                          <span key={`${message.id}-${citation.relative_path}-${citation.chunk_id || citation.note_id || citation.heading || ""}`}>
                            <strong>{formatCitationSourceLabel([citation])}</strong>
                            {citation.relative_path}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {message.events?.length ? (
                      <div className="message-events">
                        {message.events.slice(-4).map((toolEvent) => (
                          <span key={toolEvent.id} className={toolEvent.tone === "error" ? "error" : undefined}>
                            <strong>{toolEvent.label}</strong>
                            {toolEvent.detail}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {message.continuity_signal ? (
                      <div className="continuity-presence-hint">
                        <strong>{message.continuity_signal.title}</strong>
                        <span>{message.continuity_signal.summary}</span>
                        <small>{message.continuity_signal.display_hint}</small>
                      </div>
                    ) : null}
                    {message.continuity_proposals?.length ? (
                      <div className="proposal-list continuity-chat-proposal-list">
                        {message.continuity_proposals.map((proposal) => (
                          <article key={proposal.proposal_id} className="proposal continuity-proposal compact">
                            <div className="continuity-proposal-head">
                              <strong>{formatContinuityKind(proposal.kind)}</strong>
                              <span>{formatContinuityStatus(proposal.status)}</span>
                            </div>
                            <p>{proposal.summary}</p>
                            <small>{proposal.evidence}</small>
                          </article>
                        ))}
                      </div>
                    ) : null}
                    {message.wiki_proposals?.length ? (
                      <div className="proposal-list wiki-chat-proposal-list">
                        {message.wiki_proposals.map((proposal) => renderChatWikiProposal(message, proposal))}
                      </div>
                    ) : null}
                  </article>
                ))
              ) : (
                <EmptyState text="还没有对话。先绑定 Obsidian/Markdown Vault，然后向 Agent 提问。" />
              )}
            </div>
            <div className="workflow-grid" aria-label="Agent + Obsidian 工作流状态">
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
            </div>
          </section>
        </Panel>

        <Panel id="live2d-panel" icon={<Bot size={18} />} title="Live2D 模型">
          <section className="stack" aria-label="Live2D 模型选择">
            <div className="section-heading">
              <strong>当前桌宠模型</strong>
              <span>这里会立即影响桌宠窗口加载的 Cubism 模型。</span>
            </div>
            <label>
              <span>选择模型</span>
              <select
                value={selectedLive2dModelId}
                onChange={(event) => selectLive2DModel(event.target.value)}
              >
                {live2dModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.label}
                  </option>
                ))}
              </select>
            </label>
            <dl className="details single">
              <div>
                <dt>Manifest</dt>
                <dd>{live2dAsset.manifestPath}</dd>
              </div>
              <div>
                <dt>状态</dt>
                <dd>{getLive2DAssetStatusText(live2dAsset).title}</dd>
              </div>
            </dl>
          </section>
        </Panel>

        <Panel id="connection-panel" icon={<Settings size={18} />} title="连接">
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              persistSettings(settings);
            }}
          >
            <label>
              <span>后端地址</span>
              <input
                value={settings.baseUrl}
                onChange={(event) => setSettings((current) => ({ ...current, baseUrl: event.target.value }))}
                placeholder="http://127.0.0.1:8765"
              />
            </label>
            <label>
              <span>{isElectronRuntime ? "会话令牌（桌面端自动注入）" : "会话令牌（浏览器手动填写）"}</span>
              <input
                value={settings.sessionToken}
                onChange={(event) => setSettings((current) => ({ ...current, sessionToken: event.target.value }))}
                placeholder={isElectronRuntime ? "已从桌面端启动信息读取" : "粘贴当前启动令牌"}
                type="password"
              />
            </label>
            <p className="field-note">
              {isElectronRuntime
                ? "桌面端会自动注入托管后端的启动令牌。只有需要覆盖时才手动保存。"
                : "浏览器模式无法读取桌面端启动令牌，请粘贴后端输出的令牌。"}
            </p>
            <div className="button-row">
              <button type="submit">
                <Check size={16} />
                保存
              </button>
              <button type="button" className="secondary" onClick={() => void checkHealth()} disabled={checkingHealth}>
                {checkingHealth ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                健康检查
              </button>
            </div>
            <dl className="details">
              <div>
                <dt>版本</dt>
                <dd>{health?.version || "未知"}</dd>
              </div>
              <div>
                <dt>数据库</dt>
                <dd>{formatDatabaseStatus(health?.database)}</dd>
              </div>
              <div>
                <dt>业务鉴权</dt>
                <dd>{formatBusinessAuthStatus(businessAuthStatus)}</dd>
              </div>
            </dl>
            <p className="field-note">{businessAuthMessage}</p>
          </form>
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

        <Panel id="continuity-panel" icon={<HeartPulse size={18} />} title="连续性审核">
          <section className="stack" aria-label="连续性状态与提案审核">
            <div className="section-heading">
              <strong>运行时连续性</strong>
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
            <div className="proposal-list continuity-proposal-list">
              {continuityProposals.length > 0 ? (
                continuityProposals.map((proposal) => {
                  const busy = continuityActionIds.has(proposal.proposal_id);
                  return (
                    <article
                      key={proposal.proposal_id}
                      id={`continuity-proposal-${proposal.proposal_id}`}
                      className={`proposal continuity-proposal ${proposal.status}`}
                    >
                      <div className="continuity-proposal-head">
                        <div>
                          <strong>{formatContinuityKind(proposal.kind)}</strong>
                          <small>{formatContinuityStatus(proposal.status)} / 置信度 {formatConfidence(proposal.confidence)}</small>
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
                })
              ) : (
                <EmptyState text="没有待确认的连续性提案。" />
              )}
            </div>
          </section>
        </Panel>

        <Panel id="wiki-workflow-panel" icon={<FileDown size={18} />} title="高级 Vault 维护">
          <details className="stack advanced-vault-maintenance" aria-label="高级 Vault 维护工具">
            <summary>
              <strong>展开 Vault 页面维护工具</strong>
              <span>这些按钮调用现有 Wiki API（内部/历史命名），保留给手工预览、审查、归档、综合整理和检查；主流程优先使用上方 Agent 对话。</span>
            </summary>
          <form className="stack" onSubmit={previewWikiIngest}>
            <div className="section-heading">
              <strong>维护 Obsidian Vault 里的长期记忆</strong>
              <span>这是高级维护入口，不作为日常主流程；Agent chat 产生计划和确认后再写入 Vault。</span>
            </div>
            <label>
              <span>审查/应用目标</span>
              <input
                value={wikiApprovedTargetsInput}
                onChange={(event) => setWikiApprovedTargetsInput(event.target.value)}
                placeholder="留空=应用预览全部页面；可用审查推荐填充"
              />
            </label>
            <div className="split">
              <label>
                <span>标题</span>
                <input
                  value={wikiDraft.title}
                  onChange={(event) => setWikiDraft((current) => ({ ...current, title: event.target.value }))}
                  placeholder="运行时笔记"
                />
              </label>
              <label>
                <span>来源类型</span>
                <input
                  value={wikiDraft.source_type || ""}
                  onChange={(event) => setWikiDraft((current) => ({ ...current, source_type: event.target.value }))}
                  placeholder="manual"
                />
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={wikiReviewForceRefresh}
                  onChange={(event) => setWikiReviewForceRefresh(event.target.checked)}
                />
                <span>审查强制刷新</span>
              </label>
            </div>
            <div className="split">
              <label>
                <span>来源地址</span>
                <input
                  value={wikiDraft.source_uri || ""}
                  onChange={(event) => setWikiDraft((current) => ({ ...current, source_uri: event.target.value }))}
                  placeholder="可选：来源 URL 或本地引用"
                />
              </label>
              <label>
                <span>最多页面数</span>
                <input
                  type="number"
                  min={1}
                  max={15}
                  value={wikiDraft.max_pages ?? 15}
                  onChange={(event) =>
                    setWikiDraft((current) => ({ ...current, max_pages: Number(event.target.value) }))
                  }
                />
              </label>
            </div>
            <div className="split">
              <label>
                <span>归档目标</span>
                <input
                  value={wikiDraft.target_path || ""}
                  onChange={(event) => setWikiDraft((current) => ({ ...current, target_path: event.target.value }))}
                  placeholder={defaultWikiArchiveTargetPath}
                />
              </label>
              <label>
                <span>归档章节</span>
                <input
                  value={wikiDraft.section || ""}
                  onChange={(event) => setWikiDraft((current) => ({ ...current, section: event.target.value }))}
                  placeholder="可选"
                />
              </label>
            </div>
            <label>
              <span>内容</span>
              <textarea
                value={wikiDraft.content}
                onChange={(event) => setWikiDraft((current) => ({ ...current, content: event.target.value }))}
                placeholder="要写入 Vault/Wiki/... 的 Markdown 内容"
              />
            </label>
            <div className="split">
              <label>
                <span>标签</span>
                <input
                  value={wikiTagInput}
                  onChange={(event) => setWikiTagInput(event.target.value)}
                  placeholder="desktop,wiki"
                />
              </label>
              <label>
                <span>关联链接</span>
                <input
                  value={wikiLinkInput}
                  onChange={(event) => setWikiLinkInput(event.target.value)}
                placeholder="Wiki/Runtime.md, Wiki/API.md"
              />
            </label>
            </div>
            <div className="split">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={wikiDraft.write_report}
                  onChange={(event) => setWikiDraft((current) => ({ ...current, write_report: event.target.checked }))}
                />
                <span>写入检查报告</span>
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={wikiDraft.allow_mixed_sources}
                  onChange={(event) =>
                    setWikiDraft((current) => ({ ...current, allow_mixed_sources: event.target.checked }))
                  }
                />
                <span>允许混合来源归档</span>
              </label>
            </div>
            <div className="button-row">
              <button type="submit" disabled={wikiWorkflowBusy}>
                {wikiWorkflowAction === "preview" ? <Loader2 className="spin" size={16} /> : <Search size={16} />}
                预览
              </button>
              <button type="button" className="secondary" onClick={() => void reviewWikiIngest()} disabled={wikiWorkflowBusy || !wikiPreview}>
                {wikiWorkflowAction === "review" ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />}
                审查
              </button>
              <button type="button" className="secondary" onClick={() => void applyWikiIngest()} disabled={wikiWorkflowBusy}>
                {wikiWorkflowAction === "apply" ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
                应用
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => void archiveLatestWikiQuery()}
                disabled={wikiWorkflowBusy || latestKnowledgeCitations.length === 0}
                title={
                  latestKnowledgeCitations.length > 0
                    ? "归档最近一条带 Vault 引用的已完成助手回复"
                    : "没有可归档的知识库引用回复"
                }
              >
                {wikiWorkflowAction === "archive" ? <Loader2 className="spin" size={16} /> : <MessageSquareText size={16} />}
                归档查询
              </button>
              <button type="button" className="secondary" onClick={() => void synthesizeWiki()} disabled={wikiWorkflowBusy}>
                {wikiWorkflowAction === "synthesize" ? <Loader2 className="spin" size={16} /> : <FileDown size={16} />}
                综合整理
              </button>
              <button type="button" className="secondary" onClick={() => void runWikiLint()} disabled={wikiWorkflowBusy}>
                {wikiWorkflowAction === "lint" ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
                运行检查
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => void loadWikiArchiveHistory()}
                disabled={wikiWorkflowBusy || wikiArchiveHistoryLoading}
              >
                {wikiArchiveHistoryLoading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                刷新归档
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => void loadWikiCoreStatus()}
                disabled={wikiWorkflowBusy || wikiCoreStatus === "loading"}
              >
                {wikiCoreStatus === "loading" ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                刷新核心状态
              </button>
            </div>
            <dl className="details">
              <div>
                <dt>预览</dt>
                <dd>{wikiPreview ? `${formatTaskStatus(wikiPreview.status)} / ${wikiPreview.page_plans.length} 页 / ${wikiPreview.source_hash.slice(0, 12)}` : "无"}</dd>
              </div>
              <div>
                <dt>最近应用</dt>
                <dd>{formatWikiWorkflowResult(wikiApplyResult)}</dd>
              </div>
              <div>
                <dt>审查</dt>
                <dd>{wikiReviewResult ? `${formatTaskStatus(wikiReviewResult.status)} / ${wikiReviewResult.findings.length} 个发现 / ${wikiReviewResult.recommended_targets.length} 个推荐` : "未运行"}</dd>
              </div>
              <div>
                <dt>Agent 引用来源</dt>
                <dd>
                  {latestArchiveMessage
                    ? `${latestArchiveMessage.id} / ${latestKnowledgeCitations.length} 条 Vault 引用`
                    : "无"}
                </dd>
              </div>
              <div>
                <dt>检查</dt>
                <dd>{wikiLintResult ? `${wikiLintResult.summary.pages ?? 0} 页 / ${wikiLintIssueCount} 个问题` : "未运行"}</dd>
              </div>
              <div>
                <dt>最新归档</dt>
                <dd>{lastWikiArchiveId || "无"}</dd>
              </div>
              <div>
                <dt>历史</dt>
                <dd>{wikiArchiveHistorySummary}</dd>
              </div>
              <div>
                <dt>结构</dt>
                <dd>{wikiSchemaStatus?.exists ? wikiSchemaStatus.path : wikiCoreStatus === "error" ? "异常" : "未加载"}</dd>
              </div>
              <div>
                <dt>索引</dt>
                <dd>{wikiIndexStatus ? `${wikiIndexStatus.entries.length} 条` : "未加载"}</dd>
              </div>
              <div>
                <dt>日志</dt>
                <dd>{wikiLogStatus ? `${wikiLogStatus.entries.length} 条` : "未加载"}</dd>
              </div>
            </dl>
            {wikiCoreError ? <p className="field-note error">{wikiCoreError}</p> : null}
            {wikiPreview ? (
              <pre className="diff-preview">{formatWikiPreview(wikiPreview)}</pre>
            ) : null}
            {wikiReviewResult ? (
              <section className="wiki-review-result" aria-label="Wiki ingest review result">
                <div className="section-heading">
                  <strong>审查结果</strong>
                  <span>{formatTaskStatus(wikiReviewResult.status)} / {wikiReviewResult.review_id}</span>
                </div>
                <p>{wikiReviewResult.summary}</p>
                {wikiReviewResult.model_error ? <p className="field-note error">{wikiReviewResult.model_error}</p> : null}
                {wikiReviewResult.recommended_targets.length > 0 ? (
                  <div className="wiki-review-targets">
                    <div>
                      <strong>推荐应用目标</strong>
                      <span>{wikiReviewResult.recommended_targets.join(", ")}</span>
                    </div>
                    <button type="button" className="secondary" onClick={useWikiReviewRecommendedTargets} disabled={wikiWorkflowBusy}>
                      <Check size={16} />
                      使用推荐
                    </button>
                  </div>
                ) : null}
                {wikiReviewResult.findings.length > 0 ? (
                  <div className="message-events">
                    {wikiReviewResult.findings.map((finding, index) => (
                      <span key={`${finding.code}-${finding.target_path || index}`} className={finding.severity === "error" ? "error" : undefined}>
                        <strong>{formatIssueSeverity(finding.severity)} / {finding.code}</strong>
                        {finding.target_path ? `${finding.target_path}: ` : ""}
                        {finding.message}
                      </span>
                    ))}
                  </div>
                ) : null}
              </section>
            ) : null}
            {wikiLintResult?.issues.length ? (
              <div className="message-events" aria-label="Wiki 检查问题">
                {wikiLintResult.issues.slice(0, 6).map((issue, index) => (
                  <span key={`${issue.code}-${issue.path || "wiki"}-${issue.target || index}`} className={issue.severity === "error" ? "error" : undefined}>
                    <strong>{formatIssueSeverity(issue.severity)}</strong>
                    {issue.path ? `${issue.path}${issue.target ? ` -> ${issue.target}` : ""}：` : ""}
                    {issue.message}
                  </span>
                ))}
              </div>
            ) : null}
            {wikiOpenedArchive ? (
              <pre className="diff-preview wiki-opened-archive">{formatWikiArchiveDetail(wikiOpenedArchive)}</pre>
            ) : null}
            <section className="wiki-archive-history" aria-label="Wiki 查询归档历史">
              <div className="section-heading">
                <strong>查询归档历史</strong>
                <span>{wikiArchiveHistorySummary}</span>
              </div>
              {wikiArchiveHistoryError ? <p className="field-note error">{wikiArchiveHistoryError}</p> : null}
              {wikiArchiveHistory.length > 0 ? (
                <div className="wiki-archive-history-list">
                  {wikiArchiveHistory.slice(0, 8).map((archive, index) => {
                    const archiveId = getWikiArchiveId(archive);
                    const opening = Boolean(archiveId && wikiOpeningArchiveId === archiveId);
                    return (
                      <article
                        key={archiveId || `${archive.target_path}-${archive.created_at}-${index}`}
                        className={`wiki-archive-history-item${archiveId && archiveId === lastWikiArchiveId ? " active" : ""}`}
                      >
                        <div className="wiki-archive-history-main">
                          <strong>{archive.title || archive.page?.title || archive.target_path}</strong>
                          <span>{archive.question}</span>
                          <small>{formatWikiArchiveHistoryMeta(archive)}</small>
                        </div>
                        <p>{archive.answer_preview}</p>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => void openWikiQueryArchive(archiveId)}
                          disabled={wikiWorkflowBusy || !archiveId || Boolean(wikiOpeningArchiveId)}
                        >
                          {opening ? <Loader2 className="spin" size={16} /> : <FolderOpen size={16} />}
                          打开
                        </button>
                      </article>
                    );
                  })}
                </div>
              ) : wikiArchiveHistoryStatus === "empty" ? (
                <p className="field-note">还没有查询归档。</p>
              ) : null}
            </section>
          </form>
          </details>
        </Panel>

        <Panel id="settings-panel" icon={<KeyRound size={18} />} title="Agent / Obsidian 设置">
          <section className="agent-model-section" aria-label="智能体模型配置">
            <div className="section-heading">
              <strong>智能体独立模型</strong>
              <span>{agentModelCountLabel} 分别保存提供方、接口地址、模型和密钥，并分别试连。</span>
            </div>
            <button type="button" className="secondary" onClick={() => void loadSettingsStatus()} disabled={loadingSettingsStatus}>
              {loadingSettingsStatus ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
              刷新状态
            </button>
            <div className="agent-model-list">
              {agentModelDrafts.map((draft) => {
                const definition = agentModelDefinitions.find((agent) => agent.id === draft.agent_id);
                const testResult = agentModelTestResults[draft.agent_id];
                const saving = savingAgentModelIds.has(draft.agent_id);
                const testing = testingAgentModelIds.has(draft.agent_id);
                const hasUnsavedDraft = hasUnsavedAgentModelDraft(draft);
                const providerUnsupported = Boolean(draft.provider.trim()) && !isSupportedProviderDraft(draft.provider);
                return (
                  <article key={draft.agent_id} className="agent-model-row">
                    <div className="agent-model-title">
                      <strong>{definition?.label || draft.agent_id}</strong>
                      <span>{definition?.description}</span>
                    </div>
                    <label>
                      <span>提供方</span>
                      <input
                        value={draft.provider}
                        onChange={(event) => updateAgentModelDraft(draft.agent_id, { provider: event.target.value })}
                        placeholder="openai-compatible"
                      />
                    </label>
                    <label>
                      <span>接口地址</span>
                      <input
                        value={draft.base_url}
                        onChange={(event) => updateAgentModelDraft(draft.agent_id, { base_url: event.target.value })}
                      />
                    </label>
                    <label>
                      <span>模型</span>
                      <input
                        value={draft.model}
                        onChange={(event) => updateAgentModelDraft(draft.agent_id, { model: event.target.value })}
                      />
                    </label>
                    <label>
                      <span>密钥</span>
                      <input
                        value={draft.api_key}
                        onChange={(event) => updateAgentModelDraft(draft.agent_id, { api_key: event.target.value })}
                        placeholder={draft.masked || "请输入 API 密钥"}
                        type="password"
                      />
                    </label>
                    <div className="agent-model-actions">
                      <button type="button" onClick={() => void saveAgentModel(draft.agent_id)} disabled={saving}>
                        {saving ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />}
                        保存
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => void testAgentModelConnection(draft.agent_id)}
                        disabled={testing || hasUnsavedDraft || providerUnsupported}
                      >
                        {testing ? <Loader2 className="spin" size={16} /> : <Bot size={16} />}
                        试连
                      </button>
                    </div>
                    <dl className="agent-model-status">
                      <div>
                        <dt>配置状态</dt>
                        <dd>{formatBooleanStatus(draft.configured)}</dd>
                      </div>
                      <div>
                        <dt>密钥状态</dt>
                        <dd>{draft.masked || "未配置"}</dd>
                      </div>
                      <div>
                        <dt>试连结果</dt>
                        <dd>
                          {providerUnsupported
                            ? "提供方只支持 openai-compatible。"
                            : hasUnsavedDraft
                              ? "有未保存改动，请先保存。"
                              : testResult
                                ? formatModelTestResult(testResult)
                                : "尚未试连"}
                        </dd>
                      </div>
                    </dl>
                  </article>
                );
              })}
            </div>
          </section>
          <form className="stack separated" onSubmit={bindVault}>
            <label>
              <span>Obsidian/Markdown Vault 路径</span>
              <div className="path-picker">
                <input
                  value={vaultPath}
                  onChange={(event) => setVaultPath(event.target.value)}
                  placeholder="例如：E:\\AgentMemory 或 D:\\Obsidian\\副本"
                  aria-describedby="vault-path-help"
                />
                <button
                  type="button"
                  className="secondary"
                  onClick={selectVaultDirectory}
                  disabled={!canSelectVaultDirectory}
                  title={canSelectVaultDirectory ? "选择 Vault 文件夹" : "浏览器模式请手动填写路径"}
                >
                  <FolderOpen size={16} />
                  选择文件夹
                </button>
              </div>
              <p id="vault-path-help" className="field-note">
                {canSelectVaultDirectory
                  ? "选择后只会填入路径，仍需点击初始化；不要选择 .tmp 或 smoke 工作目录。"
                  : "浏览器模式无法打开系统文件夹选择器，请手动填写路径后点击初始化。"}
              </p>
            </label>
            <div className="button-row">
              <button type="submit" disabled={indexingVault}>
                {indexingVault ? <Loader2 className="spin" size={16} /> : <Database size={16} />}
                {indexingVault ? "处理中" : "初始化"}
              </button>
              <button type="button" className="secondary" onClick={() => void loadVaultStatus()}>
                <ShieldCheck size={16} />
                状态
              </button>
              <button type="button" className="secondary" onClick={rebuildIndex} disabled={indexingVault}>
                {indexingVault ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                索引
              </button>
            </div>
            <dl className="details single">
              <div>
                <dt>当前 Vault</dt>
                <dd>{vaultId || "未知"}</dd>
              </div>
              <div>
                <dt>最近索引</dt>
                <dd>
                  {lastIndexRun
                    ? `${lastIndexRun.vaultId} / ${lastIndexRun.jobId} / ${formatTaskStatus(lastIndexRun.status)} / 已索引 ${lastIndexRun.filesIndexed ?? 0}/${lastIndexRun.filesSeen ?? 0} 个文件`
                    : "尚未在本页启动索引"}
                </dd>
              </div>
            </dl>
          </form>
        </Panel>

      </section>
    </main>
  );
}

function Panel({
  id,
  title,
  icon,
  className = "",
  children,
}: {
  id?: string;
  title: string;
  icon: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className={`panel ${className}`}>
      <div className="panel-title">
        {icon}
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="empty-state">{text}</p>;
}

function Live2DStage({
  stage,
  asset,
  runtime,
  canvasRef,
  variant = "panel",
  petInteractions,
}: {
  stage: Live2DStageView;
  asset: Live2DAssetInfo;
  runtime: Live2DRuntimeBoundary;
  canvasRef: RefObject<HTMLCanvasElement>;
  variant?: "panel" | "pet";
  petInteractions?: {
    onPointerDown: (event: PointerEvent<HTMLElement>) => void;
    onPointerMove: (event: PointerEvent<HTMLElement>) => void;
    onPointerUp: (event: PointerEvent<HTMLElement>) => void;
    onPointerCancel: (event: PointerEvent<HTMLElement>) => void;
    onLostPointerCapture: (event: PointerEvent<HTMLElement>) => void;
    onContextMenu: () => void;
    onDoubleClick: () => void;
  };
}) {
  const assetStatusText = getLive2DAssetStatusText(asset);
  const resourceCountText = formatLive2DResourceCount(asset);
  const coverStatusText = getLive2DCoverStatusText(asset);
  const shouldMountRenderer = variant === "pet" && runtime.canMountRenderer;
  const [renderLifecycle, setRenderLifecycle] = useState<{
    status: Live2DRenderLifecycleStatus;
    message: string;
    renderMode?: Live2DRendererMode;
  }>(() => ({
    status: getInitialLive2DRenderStatus(variant, shouldMountRenderer),
    renderMode: "failed",
    message: shouldMountRenderer ? "正在启动桌宠模型渲染。" : getLive2DStaticPreviewMessage(variant, runtime.detail),
  }));
  const [layoutWarning, setLayoutWarning] = useState<string | null>(null);
  const [runtimeCommand, setRuntimeCommand] = useState<Live2DStageRuntimeDirective>(() =>
    getLive2DStageRuntimeDirective(stage.state, asset.defaultMotionGroup, asset.defaultMotionIndex),
  );
  const [runtimeDiagnostics, setRuntimeDiagnostics] = useState<Live2DRendererDiagnostics | null>(null);
  const live2dRuntimeHandleRef = useRef<Live2DRuntimeHandle | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const mountContext = createRendererMountContext(canvas, asset);
    let activeHandle: Live2DRuntimeHandle | null = null;
    let disposed = false;
    let invisibleSampleMissCount = 0;

    if (!shouldMountRenderer || !mountContext) {
      setRenderLifecycle({
        status: getInactiveLive2DRenderStatus(variant, runtime.status),
        renderMode: "failed",
        message: getLive2DStaticPreviewMessage(variant, runtime.detail),
      });
      setRuntimeDiagnostics(null);
      return;
    }

    setRenderLifecycle({ status: "loading", message: "正在启动桌宠模型渲染。" });

    const canvasElement = mountContext.canvas;
    const resizeRuntime = () => {
      const bounds = canvasElement.getBoundingClientRect();
      const pixelRatio = window.devicePixelRatio || 1;
      const width = Math.max(1, Math.round(bounds.width * pixelRatio));
      const height = Math.max(1, Math.round(bounds.height * pixelRatio));

      if (canvasElement.width !== width) {
        canvasElement.width = width;
      }
      if (canvasElement.height !== height) {
        canvasElement.height = height;
      }

      activeHandle?.resize?.({ width, height, pixelRatio });
    };

    const resizeObserver = new ResizeObserver(resizeRuntime);
    resizeObserver.observe(canvasElement);
    window.addEventListener("resize", resizeRuntime);

    const mountRenderer = () => {
      resizeRuntime();
      activeHandle?.dispose?.();
      activeHandle = null;
      live2dRuntimeHandleRef.current = null;
      void mountLive2DRendererBoundary(mountContext).then((mountResult) => {
        if (disposed) {
          mountResult.handle?.dispose();
          return;
        }

        activeHandle = mountResult.handle || null;
        live2dRuntimeHandleRef.current = activeHandle;
        resizeRuntime();
        setRuntimeDiagnostics(mountResult.diagnostics || activeHandle?.getDiagnostics?.() || null);
        setRenderLifecycle({
          status: mountResult.status,
          renderMode: mountResult.renderMode,
          message: mountResult.message,
        });
      });
    };

    const handleContextLost = (event: Event) => {
      event.preventDefault();
      activeHandle?.dispose?.();
      activeHandle = null;
      live2dRuntimeHandleRef.current = null;
      setRuntimeDiagnostics(null);
      setRenderLifecycle({
        status: "failed",
        renderMode: "failed",
        message: "WebGL 上下文已丢失，正在等待系统恢复桌宠画布。",
      });
    };

    const handleContextRestored = () => {
      if (disposed) {
        return;
      }
      setRenderLifecycle({
        status: "loading",
        renderMode: "failed",
        message: "WebGL 上下文已恢复，正在重新挂载 Live2D 渲染器。",
      });
      mountRenderer();
    };

    const inspectRenderMode = () => {
      if (!activeHandle) {
        return;
      }
      const renderMode = activeHandle.getRenderMode?.();
      setRuntimeDiagnostics(activeHandle.getDiagnostics?.() || null);
      if (renderMode) {
        setRenderLifecycle((current) => (
          current.status === "mounted" && current.renderMode !== renderMode
            ? { ...current, renderMode, message: getLive2DRenderModeText(renderMode) }
            : current
        ));
      }
      if (activeHandle.hasVisiblePixels && !activeHandle.hasVisiblePixels()) {
        invisibleSampleMissCount += 1;
        if (invisibleSampleMissCount === 1 || invisibleSampleMissCount % 5 === 0) {
          console.info(
            "[Live2D] 画布像素采样暂未命中可见区域，保留已挂载状态；这通常是透明画布、模型位置或 WebGL 后缓冲采样导致的诊断噪声。",
          );
        }
        setLayoutWarning((current) => (
          current === "Live2D 已挂载，但当前画布没有检测到可见像素。" ? null : current
        ));
        return;
      }
      invisibleSampleMissCount = 0;
      setLayoutWarning((current) => (
        current === "Live2D 已挂载，但当前画布没有检测到可见像素。" ? null : current
      ));
    };

    canvasElement.addEventListener("webglcontextlost", handleContextLost);
    canvasElement.addEventListener("webglcontextrestored", handleContextRestored);
    const renderInspectTimer = window.setInterval(inspectRenderMode, 2000);

    mountRenderer();

    return () => {
      disposed = true;
      resizeObserver.disconnect();
      window.removeEventListener("resize", resizeRuntime);
      canvasElement.removeEventListener("webglcontextlost", handleContextLost);
      canvasElement.removeEventListener("webglcontextrestored", handleContextRestored);
      window.clearInterval(renderInspectTimer);
      activeHandle?.cleanup?.();
      activeHandle?.destroy?.();
      activeHandle?.dispose?.();
      activeHandle?.unmount?.();
      activeHandle = null;
      live2dRuntimeHandleRef.current = null;
      setRuntimeDiagnostics(null);
    };
  }, [asset, canvasRef, runtime.detail, runtime.status, shouldMountRenderer, variant]);

  useEffect(() => {
    const command = getLive2DStageRuntimeDirective(stage.state, asset.defaultMotionGroup, asset.defaultMotionIndex);
    setRuntimeCommand(command);

    const handle = live2dRuntimeHandleRef.current;
    if (!handle || renderLifecycle.status !== "mounted") {
      return;
    }

    try {
      handle.setExpression(command.expression);
      if (command.motionGroup && command.motionIndex >= 0) {
        handle.startMotion(command.motionGroup, command.motionIndex);
      }
      setRuntimeDiagnostics(handle.getDiagnostics?.() || null);
    } catch (error) {
      console.warn("[Live2D] 状态指令发送失败。", {
        state: stage.state,
        expression: command.expression,
        motionGroup: command.motionGroup,
        motionIndex: command.motionIndex,
        error,
      });
    }
  }, [asset.defaultMotionGroup, asset.defaultMotionIndex, renderLifecycle.status, stage.state]);

  useEffect(() => {
    if (renderLifecycle.status !== "mounted") {
      setLayoutWarning(null);
      return;
    }

    const canvas = canvasRef.current;
    if (!canvas) {
      setLayoutWarning("Live2D 已报告挂载，但未找到 canvas 节点。");
      return;
    }

    const inspectCanvasLayout = () => {
      const bounds = canvas.getBoundingClientRect();
      const styles = window.getComputedStyle(canvas);
      const hostStyles = canvas.parentElement ? window.getComputedStyle(canvas.parentElement) : null;
      const width = Math.round(bounds.width);
      const height = Math.round(bounds.height);
      const opacity = Number.parseFloat(styles.opacity || "1");
      const hidden =
        styles.display === "none" ||
        styles.visibility === "hidden" ||
        (hostStyles ? hostStyles.display === "none" || hostStyles.visibility === "hidden" : false);

      if (hidden) {
        setLayoutWarning("Live2D 已挂载，但 canvas 或宿主节点被 CSS 隐藏。");
        return;
      }

      if (width < 24 || height < 24) {
        setLayoutWarning(`Live2D 已挂载，但 canvas 可视尺寸过小：${width}x${height}px。`);
        return;
      }

      if (opacity < 0.95) {
        setLayoutWarning(`Live2D 已挂载，但 canvas 透明度为 ${styles.opacity}。`);
        return;
      }

      setLayoutWarning(null);
    };

    const frame = window.requestAnimationFrame(inspectCanvasLayout);
    const resizeObserver = new ResizeObserver(inspectCanvasLayout);
    resizeObserver.observe(canvas);
    window.addEventListener("resize", inspectCanvasLayout);

    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      window.removeEventListener("resize", inspectCanvasLayout);
    };
  }, [canvasRef, renderLifecycle.status]);

  const lifecycleText = getLive2DRenderLifecycleText(renderLifecycle.status);
  const renderModeText = getLive2DRenderModeText(renderLifecycle.renderMode || "failed");
  const diagnosticRows = getLive2DRuntimeDiagnosticRows({
    asset,
    runtime,
    renderLifecycle,
    lifecycleText,
    renderModeText,
    runtimeCommand,
    runtimeDiagnostics,
    resourceCountText,
    layoutWarning,
  });
  if (variant === "pet") {
    return (
      <section
        className={`panel live2d-panel live2d-panel-pet live2d-${stage.state} live2d-runtime-${runtime.status} live2d-render-${renderLifecycle.status} live2d-render-mode-${renderLifecycle.renderMode || "unknown"}`}
        aria-label="桌宠模型"
      >
        <div
          className="live2d-pet-stage"
          role="img"
          aria-label={`桌宠模型状态：${stage.label}`}
          data-live2d-render={renderLifecycle.status}
          data-live2d-render-mode={renderLifecycle.renderMode || "unknown"}
        >
          <div className="live2d-runtime-host" aria-label="Live2D runtime canvas 宿主区域">
            <canvas
              ref={canvasRef}
              id={runtime.mountTargetId}
              className="live2d-runtime-canvas"
              width={300}
              height={390}
            />
          </div>

          <div className="live2d-pet-composition">
          {asset.hasIcon ? (
            <div
              className="live2d-cover live2d-cover-image"
              aria-label="Live2D 静态回退封面"
              style={{ backgroundImage: `url("${asset.iconPath}")` }}
            />
          ) : (
            <div className="live2d-model" aria-label="CSS 回退展示壳">
              <div className="live2d-hair back" />
              <div className="live2d-head">
                <div className="live2d-bangs">
                  <span />
                  <span />
                  <span />
                </div>
                <div className="live2d-eye left" />
                <div className="live2d-eye right" />
                <div className="live2d-blush left" />
                <div className="live2d-blush right" />
                <div className="live2d-mouth" />
              </div>
              <div className="live2d-neck" />
              <div className="live2d-body">
                <div className="live2d-collar" />
                <div className="live2d-ribbon" />
              </div>
              <div className="live2d-arm left" />
              <div className="live2d-arm right" />
            </div>
          )}

          {renderLifecycle.status !== "mounted" ? (
            <div className="live2d-runtime-placeholder">
              <strong>{lifecycleText}</strong>
              <span>{renderLifecycle.message}</span>
            </div>
          ) : null}

          {layoutWarning ? (
            <div className="live2d-layout-warning" role="status" aria-live="polite">
              <strong>Live2D 布局提示</strong>
              <span>{layoutWarning}</span>
            </div>
          ) : null}
          </div>
          {petInteractions ? (
            <>
              <div
                className="pet-hit-region pet-hit-model"
                aria-label="桌宠模型交互区"
                {...petInteractions}
              />
              <div
                className="pet-hit-region pet-hit-bubble"
                aria-label="桌宠底部输入交互区"
                {...petInteractions}
              />
            </>
          ) : null}
        </div>
      </section>
    );
  }

  return (
    <section
      className={`panel live2d-panel live2d-panel-${variant} live2d-${stage.state} live2d-runtime-${runtime.status} live2d-render-${renderLifecycle.status} live2d-render-mode-${renderLifecycle.renderMode || "unknown"}`}
      aria-label="桌宠模型展示区"
    >
      <div className="live2d-copy">
        <p className="eyebrow">桌宠模型</p>
        <h2>{stage.label}</h2>
        <p>{stage.message}</p>
        <div className={`live2d-resource-summary live2d-resource-${asset.status}`}>
          <strong>{assetStatusText.title}</strong>
          <span>{assetStatusText.detail}</span>
        </div>
        <div className="live2d-status-grid" aria-label="Live2D 资源识别与渲染接入状态">
          <div>
            <span>Manifest URL</span>
            <strong>{asset.manifestPath}</strong>
          </div>
          <div>
            <span>封面加载状态</span>
            <strong>{coverStatusText}</strong>
          </div>
          <div>
            <span>资源计数</span>
            <strong>{resourceCountText}</strong>
          </div>
          <div className="live2d-renderer-pending">
            <span>Runtime 状态</span>
            <strong>{runtime.title}</strong>
          </div>
        </div>
      </div>
      <div
        className="live2d-stage"
        role="img"
        aria-label={`桌宠模型状态：${stage.label}`}
        data-live2d-render={renderLifecycle.status}
      >
        <div className="live2d-runtime-host" aria-label="Live2D runtime canvas 宿主区域">
          <canvas
            ref={canvasRef}
            id={runtime.mountTargetId}
            className="live2d-runtime-canvas"
            width={420}
            height={520}
          />
          <div className="live2d-runtime-placeholder">
            <strong>{lifecycleText}</strong>
            <span>{renderLifecycle.message}</span>
          </div>
        </div>
        <div className="live2d-scanline" />
        <div className="live2d-meter" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        {asset.hasIcon ? (
          <figure className="live2d-cover">
            <img src={asset.iconPath} alt={`${asset.modelLabel} 桌宠模型资源封面`} />
            <figcaption>静态封面，非 Live2D 渲染</figcaption>
          </figure>
        ) : (
          <div className="live2d-model" aria-label="CSS 回退展示壳">
          <div className="live2d-hair back" />
          <div className="live2d-head">
            <div className="live2d-bangs">
              <span />
              <span />
              <span />
            </div>
            <div className="live2d-eye left" />
            <div className="live2d-eye right" />
            <div className="live2d-blush left" />
            <div className="live2d-blush right" />
            <div className="live2d-mouth" />
          </div>
          <div className="live2d-neck" />
          <div className="live2d-body">
            <div className="live2d-collar" />
            <div className="live2d-ribbon" />
          </div>
          <div className="live2d-arm left" />
          <div className="live2d-arm right" />
          </div>
        )}
        <div className="live2d-status-card">
          <strong>{stage.mood}</strong>
          <span>{stage.hint} · {lifecycleText}</span>
        </div>
      </div>
      {layoutWarning ? (
        <div className="live2d-layout-warning" role="status" aria-live="polite">
          <strong>Live2D 布局提示</strong>
          <span>{layoutWarning}</span>
        </div>
      ) : null}
      <div className="live2d-runtime-card" aria-label="Live2D runtime 边界状态">
        <div>
          <span>挂载入口</span>
          <strong>#{runtime.mountTargetId}</strong>
        </div>
        <div>
          <span>挂载条件</span>
          <strong>{runtime.canMountRenderer ? "资源已就绪，等待真实渲染器接管" : "资源未就绪，保持边界预留"}</strong>
        </div>
        <div>
          <span>当前探测</span>
          <strong>{renderLifecycle.message}</strong>
        </div>
      </div>
      <dl className="live2d-diagnostic-summary" aria-label="Live2D runtime 诊断摘要">
        {diagnosticRows.map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      <dl className="live2d-resource-list" aria-label="模型资源状态">
        <div>
          <dt>Manifest</dt>
          <dd>{asset.manifestPath}</dd>
        </div>
        <div>
          <dt>构建产物</dt>
          <dd>运行 `npm run build` 后校验 dist</dd>
        </div>
        <div>
          <dt>Runtime</dt>
          <dd>{runtime.title}：{renderLifecycle.message}</dd>
        </div>
        <div>
          <dt>封面</dt>
          <dd>{coverStatusText}</dd>
        </div>
        <div>
          <dt>MOC</dt>
          <dd>{asset.moc || "待识别"}</dd>
        </div>
        <div>
          <dt>贴图</dt>
          <dd>{asset.textureCount} 个</dd>
        </div>
        <div>
          <dt>表情</dt>
          <dd>{asset.expressionCount} 个</dd>
        </div>
        <div>
          <dt>动作</dt>
          <dd>{asset.motionCount} 个</dd>
        </div>
        <div>
          <dt>物理/显示</dt>
          <dd>
            {asset.hasPhysics ? "物理已识别" : "无物理"} / {asset.hasDisplayInfo ? "显示信息已识别" : "无显示信息"}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function getLive2DRenderLifecycleText(status: Live2DRenderLifecycleStatus): string {
  const labels: Record<Live2DRenderLifecycleStatus, string> = {
    loading: "\u6a21\u578b\u6e32\u67d3\u542f\u52a8\u4e2d",
    mounted: "\u6a21\u578b\u6e32\u67d3\u5df2\u542f\u52a8",
    preview: "控制台静态预览",
    failed: "\u6a21\u578b\u6e32\u67d3\u4e0d\u53ef\u7528",
  };
  return labels[status];
}

function getInitialLive2DRenderStatus(
  variant: "panel" | "pet" | undefined,
  shouldMountRenderer: boolean,
): Live2DRenderLifecycleStatus {
  if (shouldMountRenderer) {
    return "loading";
  }
  return variant === "panel" ? "preview" : "failed";
}

function getInactiveLive2DRenderStatus(
  variant: "panel" | "pet" | undefined,
  runtimeStatus: Live2DRuntimeBoundary["status"],
): Live2DRenderLifecycleStatus {
  if (runtimeStatus === "loading-assets") {
    return "loading";
  }
  return variant === "panel" ? "preview" : "failed";
}

function getLive2DRenderModeText(mode: Live2DRendererMode): string {
  const labels: Record<Live2DRendererMode, string> = {
    official: "\u5b98\u65b9\u6e32\u67d3\u5668",
    fallback: "\u57fa\u7840\u56de\u9000\u6e32\u67d3",
    failed: "\u9759\u6001\u56de\u9000\u663e\u793a",
  };
  return labels[mode];
}

function getLive2DStaticPreviewMessage(variant: "panel" | "pet" | undefined, fallback: string): string {
  if (variant === "panel") {
    return "\u63a7\u5236\u53f0\u4f7f\u7528\u9759\u6001\u9884\u89c8\uff1b\u771f\u5b9e\u6a21\u578b\u6e32\u67d3\u53ea\u5728\u684c\u5ba0\u7a97\u53e3\u8fd0\u884c\u3002";
  }
  return fallback || "\u6a21\u578b\u8d44\u6e90\u6682\u672a\u5c31\u7eea\u3002";
}

function getLive2DStageRuntimeDirective(
  state: Live2DStageState,
  defaultMotionGroup = "",
  defaultMotionIndex = 0,
): Live2DStageRuntimeDirective {
  const sharedMotion = { motionGroup: defaultMotionGroup, motionIndex: defaultMotionGroup ? defaultMotionIndex : -1 };
  const directives: Record<Live2DStageState, Live2DStageRuntimeDirective> = {
    disconnected: { ...sharedMotion, expression: "5QAQ", petHint: "\u79bb\u7ebf\u5f85\u547d\uff0c\u53cc\u51fb\u6253\u5f00\u63a7\u5236\u53f0\u68c0\u67e5\u8fde\u63a5\u3002", controlSummary: "\u79bb\u7ebf\u8868\u60c5 5QAQ\uff0c\u4fdd\u6301\u9ed8\u8ba4\u5f85\u673a\u52a8\u4f5c\u3002" },
    idle: { ...sharedMotion, expression: "1desk", petHint: "\u5728\u7ebf\u966a\u4f34\u4e2d\uff0c\u53cc\u51fb\u6253\u5f00\u63a7\u5236\u53f0\u3002", controlSummary: "\u5f85\u673a\u8868\u60c5 1desk\uff0c\u64ad\u653e\u9ed8\u8ba4\u5faa\u73af\u52a8\u4f5c\u3002" },
    presence: { ...sharedMotion, expression: "2mic", petHint: "\u6211\u8fd8\u8bb0\u7740\u672a\u5b8c\u8bdd\u9898\uff0c\u53cc\u51fb\u6253\u5f00\u63a7\u5236\u53f0\u7ee7\u7eed\u3002", controlSummary: "\u8fde\u7eed\u6027\u8f7b\u63d0\u9192\u8868\u60c5 2mic\uff0c\u4ec5\u4f5c\u8fd0\u884c\u65f6\u663e\u793a\u3002" },
    reflective: { ...sharedMotion, expression: "6i gi a ri", petHint: "\u6211\u6b63\u5e26\u7740\u5df2\u786e\u8ba4\u7684\u60c5\u7eea\u8fde\u7eed\u6027\u966a\u4f34\u3002", controlSummary: "\u60c5\u7eea\u8fde\u7eed\u6027\u8868\u60c5 6i gi a ri\uff0c\u4e0d\u5199\u5165 Vault\u3002" },
    thinking: { ...sharedMotion, expression: "3clever", petHint: "\u6b63\u5728\u601d\u8003\uff0c\u56de\u590d\u751f\u6210\u4e2d\u3002", controlSummary: "\u601d\u8003\u8868\u60c5 3clever\uff0c\u7ef4\u6301\u9ed8\u8ba4\u5faa\u73af\u52a8\u4f5c\u3002" },
    memory: { ...sharedMotion, expression: "7keyboard", petHint: "\u5df2\u627e\u5230\u8bb0\u5fc6\u7ebf\u7d22\uff0c\u6253\u5f00\u63a7\u5236\u53f0\u67e5\u770b\u3002", controlSummary: "\u68c0\u7d22\u8868\u60c5 7keyboard\uff0c\u63d0\u793a\u8bb0\u5fc6\u641c\u7d22\u7ed3\u679c\u3002" },
    confirming: { ...sharedMotion, expression: "4OAO", petHint: "\u6709\u8bb0\u5fc6\u5f85\u786e\u8ba4\uff0c\u53cc\u51fb\u5904\u7406\u3002", controlSummary: "\u786e\u8ba4\u8868\u60c5 4OAO\uff0c\u63d0\u793a\u5f85\u786e\u8ba4\u8bb0\u5fc6\u63d0\u6848\u3002" },
    tasking: { ...sharedMotion, expression: "1desk", petHint: "\u4efb\u52a1\u5df2\u8bb0\u5f55\uff0c\u6253\u5f00\u63a7\u5236\u53f0\u7ba1\u7406\u3002", controlSummary: "\u4efb\u52a1\u8868\u60c5 1desk\uff0c\u63d0\u793a\u4efb\u52a1\u5217\u8868\u72b6\u6001\u3002" },
    diagnosed: { ...sharedMotion, expression: "9", petHint: "\u8bca\u65ad\u5df2\u5b8c\u6210\uff0c\u53ef\u56de\u63a7\u5236\u53f0\u67e5\u770b\u3002", controlSummary: "\u8bca\u65ad\u8868\u60c5 9\uff0c\u63d0\u793a\u8bca\u65ad\u5feb\u7167\u5df2\u5f52\u6863\u3002" },
  };
  return directives[state];
}

function getLive2DRuntimeDiagnosticRows({
  asset,
  runtime,
  renderLifecycle,
  lifecycleText,
  renderModeText,
  runtimeCommand,
  runtimeDiagnostics,
  resourceCountText,
  layoutWarning,
}: {
  asset: Live2DAssetInfo;
  runtime: Live2DRuntimeBoundary;
  renderLifecycle: { status: Live2DRenderLifecycleStatus; message: string; renderMode?: Live2DRendererMode };
  lifecycleText: string;
  renderModeText: string;
  runtimeCommand: Live2DStageRuntimeDirective;
  runtimeDiagnostics: Live2DRendererDiagnostics | null;
  resourceCountText: string;
  layoutWarning: string | null;
}): Array<{ label: string; value: string }> {
  const motionText = runtimeDiagnostics?.currentMotion ? (runtimeDiagnostics.currentMotion.group || "\u9ed8\u8ba4\u52a8\u4f5c") + "[" + runtimeDiagnostics.currentMotion.index + "]" : "\u672a\u64ad\u653e";
  const expressionText = runtimeDiagnostics?.currentExpression || "\u672a\u5207\u6362";
  const visibleText = runtimeDiagnostics?.visiblePixels === null || !runtimeDiagnostics ? "\u672a\u68c0\u6d4b" : runtimeDiagnostics.visiblePixels ? "\u53ef\u89c1" : "\u672a\u68c0\u6d4b\u5230\u53ef\u89c1\u5185\u5bb9";
  const renderPathText = runtimeDiagnostics ? getLive2DRenderModeText(runtimeDiagnostics.renderMode) : "\u7b49\u5f85\u6e32\u67d3\u5668";
  const effectText = runtimeDiagnostics ? "\u52a8\u4f5c " + runtimeDiagnostics.motionCount + " \u4e2a\uff0c\u8868\u60c5 " + runtimeDiagnostics.expressionCount + " \u4e2a\uff0c\u7728\u773c" + (runtimeDiagnostics.eyeBlinkEnabled ? "\u5df2\u542f\u7528" : "\u672a\u542f\u7528") + "\uff0c\u547c\u5438" + (runtimeDiagnostics.breathEnabled ? "\u5df2\u542f\u7528" : "\u672a\u542f\u7528") + "\uff0c\u7269\u7406\u6446\u52a8" + (runtimeDiagnostics.physicsEnabled ? "\u5df2\u542f\u7528" : "\u672a\u542f\u7528") : "\u7b49\u5f85\u6a21\u578b\u8d44\u6e90";
  const latestIssue = runtimeDiagnostics?.lastOfficialRenderError || runtimeDiagnostics?.lastFallbackRenderError || runtimeDiagnostics?.lastMotionError || runtimeDiagnostics?.lastExpressionError || runtimeDiagnostics?.lastEffectError || "\u6682\u65e0\u95ee\u9898";
  return [
    { label: "\u6e32\u67d3\u72b6\u6001", value: lifecycleText + " / " + renderModeText },
    { label: "\u5f53\u524d\u6307\u4ee4", value: runtimeCommand.controlSummary + " \u5f53\u524d\u8868\u60c5\uff1a" + runtimeCommand.expression + "\uff1b\u5f53\u524d\u52a8\u4f5c\uff1a" + (runtimeCommand.motionGroup || "\u672a\u6307\u5b9a") + (runtimeCommand.motionIndex >= 0 ? "[" + runtimeCommand.motionIndex + "]" : "") },
    { label: "\u6e32\u67d3\u8def\u5f84", value: runtimeDiagnostics ? renderPathText + "\uff1b\u5f53\u524d\u52a8\u4f5c\uff1a" + motionText + "\uff1b\u5f53\u524d\u8868\u60c5\uff1a" + expressionText + "\uff1b\u753b\u5e03\u72b6\u6001\uff1a" + visibleText : "\u7b49\u5f85\u684c\u5ba0\u6e32\u67d3\u5668\u542f\u52a8" },
    { label: "\u52a8\u4f5c\u4e0e\u6548\u679c", value: effectText },
    { label: "\u6700\u8fd1\u95ee\u9898", value: latestIssue },
    { label: "\u6a21\u578b\u8d44\u6e90", value: asset.status === "recognized" ? resourceCountText + "\uff0c\u6a21\u578b\u6587\u4ef6\uff1a" + (asset.moc || "\u672a\u8bc6\u522b") : asset.status + "\uff0c" + (asset.error || runtime.detail) },
    { label: "\u753b\u5e03\u8bca\u65ad", value: layoutWarning || (renderLifecycle.status === "mounted" ? "\u753b\u5e03\u5df2\u6302\u8f7d\uff0c\u50cf\u7d20\u68c0\u6d4b\u4ec5\u4f5c\u8bca\u65ad" : renderLifecycle.message) },
  ];
}
function checkImageExists(src: string): Promise<boolean> {
  if (!src) {
    return Promise.resolve(false);
  }
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve(true);
    image.onerror = () => resolve(false);
    image.src = src;
  });
}

function normalizeLive2DModelCatalog(catalog: Live2DModelCatalog): Live2DModelOption[] {
  const models = Array.isArray(catalog.models) ? catalog.models : [];
  const normalized = models
    .filter((model) => model.id && model.label && model.directory && model.model)
    .map((model) => ({
      ...model,
      directory: model.directory.trim().replace(/\\/g, "/").replace(/\/?$/, "/"),
    }));
  return normalized.length > 0 ? normalized : [defaultLive2DModelOption];
}

function loadLive2DModelSelection(): string {
  return readRendererUiState(live2dModelSelectionStorageKey) || defaultLive2DModelOption.id;
}

function saveLive2DModelSelection(modelId: string): void {
  writeRendererUiState(live2dModelSelectionStorageKey, modelId);
}

function formatLive2DResourceCount(asset: Live2DAssetInfo): string {
  if (asset.status === "loading") {
    return "识别中";
  }

  if (asset.status === "missing" || asset.status === "error") {
    return "待识别";
  }

  return `${asset.textureCount} 张贴图 / ${asset.expressionCount} 个表情 / ${asset.motionCount} 个动作`;
}

function getLive2DCoverStatusText(asset: Live2DAssetInfo): string {
  if (asset.status === "loading") {
    return "校验中";
  }

  if (asset.hasIcon) {
    return `已加载：${asset.iconPath}`;
  }

  if (asset.status === "recognized") {
    return "未找到封面，当前显示 CSS 占位";
  }

  return "待识别";
}

function getLive2DAssetStatusText(asset: Live2DAssetInfo): { title: string; detail: string } {
  if (asset.status === "recognized") {
    return {
      title: "模型资源已识别",
      detail: `已读取 Live2D 模型清单，Cubism runtime 会尝试挂载 WebGL canvas；失败时回退到${asset.hasIcon ? "静态封面" : "CSS 占位"}。`,
    };
  }

  if (asset.status === "missing") {
    return {
      title: "模型资源未识别",
      detail: `未读取到 ${asset.manifestPath}；Cubism runtime 暂不能挂载。`,
    };
  }

  if (asset.status === "error") {
    return {
      title: "模型资源读取失败",
      detail: `${asset.error || "读取清单时发生异常"}；Cubism runtime 暂不能挂载。`,
    };
  }

  return {
    title: "正在识别模型资源",
    detail: "正在读取 Live2D 模型清单；资源就绪后会挂载 Cubism WebGL 渲染器。",
  };
}

function getLive2DStageView({
  connected,
  streaming,
  searchResultCount,
  pendingProposalCount,
  taskCount,
  diagnosticsReady,
  continuityState,
  continuitySignal,
}: {
  connected: boolean;
  streaming: boolean;
  searchResultCount: number;
  pendingProposalCount: number;
  taskCount: number;
  diagnosticsReady: boolean;
  continuityState: ContinuityStateResponse | null;
  continuitySignal: ChatContinuitySignal | null;
}): Live2DStageView {
  if (!connected) {
    return {
      state: "disconnected",
      label: "未连接",
      mood: "离线待命",
      message: "模型壳已经就位，正在等待本地后端连接。",
      hint: "请先检查连接状态",
    };
  }
  if (streaming) {
    return {
      state: "thinking",
      label: "思考中",
      mood: "正在生成",
      message: "桌宠正在根据你的输入组织回复。",
      hint: "流式回复进行中",
    };
  }
  if (pendingProposalCount > 0) {
    return {
      state: "confirming",
      label: "等待确认",
      mood: "等待用户确认",
      message: `有 ${pendingProposalCount} 条记忆提案等待确认；确认后才进入长期记忆。`,
      hint: "查看记忆提案面板",
    };
  }
  if (diagnosticsReady) {
    return {
      state: "diagnosed",
      label: "诊断完成",
      mood: "状态已归档",
      message: "诊断快照已导出，可以用于排查本地环境。",
      hint: "查看诊断信息面板",
    };
  }
  if (searchResultCount > 0) {
    return {
      state: "memory",
      label: "检索记忆",
      mood: "找到线索",
      message: `已展示 ${searchResultCount} 条记忆搜索结果。`,
      hint: "可继续追问或引用",
    };
  }
  if (taskCount > 0) {
    return {
      state: "tasking",
      label: "记录任务",
      mood: "任务已记录",
      message: `当前列表中有 ${taskCount} 条任务。`,
      hint: "可完成或取消任务",
    };
  }
  if (continuitySignal?.kind === "open_thread") {
    return {
      state: "presence",
      label: "轻提醒",
      mood: "记着未完话题",
      message: continuitySignal.summary,
      hint: continuitySignal.display_hint || "运行时轻提醒，不会创建系统通知。",
    };
  }
  if (continuitySignal) {
    return {
      state: "presence",
      label: "连续在场",
      mood: continuitySignal.title || "连续性在场",
      message: continuitySignal.summary,
      hint: continuitySignal.display_hint || "已确认连续性正在影响陪伴表现。",
    };
  }
  if (continuityState?.unresolved_threads) {
    return {
      state: "presence",
      label: "轻提醒",
      mood: "记着未完话题",
      message: `我还记着：${continuityState.unresolved_threads}`,
      hint: "只在运行时显示，不发系统通知。",
    };
  }
  if (continuityState?.current_mood || continuityState?.energy_level) {
    const mood = continuityState.current_mood || "情绪已确认";
    const energy = continuityState.energy_level ? `；${continuityState.energy_level}` : "";
    return {
      state: "reflective",
      label: "连续待机",
      mood,
      message: `桌宠沿用已确认的情绪连续性${energy}。`,
      hint: continuityState.mood_momentum || "已确认连续性状态",
    };
  }
  return {
    state: "idle",
    label: "待机",
    mood: "在线陪伴",
    message: "桌宠正在待机，准备接收聊天、记忆和任务操作。",
    hint: "可以开始对话",
  };
}

function formatSidecarStatus(
  sidecarStatus: DesktopSidecarStatus | null,
  health: HealthResponse | null,
): string {
  if (sidecarStatus?.state === "ready" && sidecarStatus.error?.code === "PORT_IN_USE_EXISTING_BACKEND") {
    return "后端已就绪（复用已有进程）";
  }
  if (sidecarStatus?.state === "error") {
    return sidecarStatus.error?.code ? `后端异常：${formatSidecarErrorCode(sidecarStatus.error.code)}` : "后端异常";
  }
  if (sidecarStatus?.state) {
    return `后端${formatSidecarState(sidecarStatus.state)}`;
  }
  return health ? `后端${formatHealthStatus(health.status)}` : "后端未检查";
}

function getSidecarActionMessage(sidecarStatus: DesktopSidecarStatus): string {
  const fallback = sidecarStatus.error?.message || formatSidecarStatus(sidecarStatus, sidecarStatus.health);
  switch (sidecarStatus.error?.code) {
    case "PORT_IN_USE_EXISTING_BACKEND":
      return "8765 端口已有后端响应，桌面端已先复用它。若聊天、知识库或任务请求返回 401，请关闭占用 8765 的进程后重启，或用相同 AGENT_PET_SESSION_TOKEN 启动后端。";
    case "PORT_IN_USE":
      return "8765 端口被其他程序占用且不是可用后端。请关闭占用进程后重启 npm run electron:dev。";
    case "BACKEND_NOT_FOUND":
      return "未找到后端目录。请确认 apps/backend/app/main.py 存在，或设置 AGENT_PET_BACKEND_DIR 后重启。";
    case "READINESS_FAILED":
      return "后端进程启动后没有通过健康检查。请查看终端日志，优先检查 Python 依赖、数据库配置和端口 8765。";
    case "SPAWN_FAILED":
      return "无法启动后端进程。请确认 Python 和 uvicorn 可用，或设置 AGENT_PET_PYTHON 指向可用解释器。";
    case "PROCESS_EXITED":
      return "后端进程已退出。请查看终端日志中的 Python/FastAPI 报错后再重启桌面端。";
    case "PORT_CHECK_FAILED":
      return "桌面端无法检查 8765 端口。请确认本机网络栈正常后重启。";
    default:
      return fallback;
  }
}

function parseJson(data: string): Record<string, unknown> | null {
  if (!data) {
    return null;
  }
  try {
    return JSON.parse(data) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function extractSseText(sseEvent: SseEvent, payload: Record<string, unknown> | null): string {
  if (payload) {
    for (const key of ["text", "token", "content", "message", "data"]) {
      const value = payload[key];
      if (typeof value === "string" && value) {
        return value;
      }
    }
  }
  if ((sseEvent.event === "token" || sseEvent.event === "message") && !payload) {
    return sseEvent.data;
  }
  return "";
}

function isCitation(value: unknown): value is MemorySearchResult {
  return Boolean(
    value &&
      typeof value === "object" &&
      "relative_path" in value &&
      typeof (value as { relative_path?: unknown }).relative_path === "string",
  );
}

function emptyToNull(value?: string | null): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function parseCompactList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function uniqueCompactList(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  values.forEach((value) => {
    const trimmed = value?.trim();
    if (!trimmed || seen.has(trimmed)) {
      return;
    }
    seen.add(trimmed);
    normalized.push(trimmed);
  });
  return normalized;
}

function loadWikiArchiveCandidate(): WikiArchiveCandidate | null {
  try {
    return normalizeWikiArchiveCandidate(readRendererUiState(wikiArchiveCandidateStorageKey));
  } catch {
    return null;
  }
}

function saveWikiArchiveCandidate(candidate: WikiArchiveCandidate): void {
  try {
    writeRendererUiState(wikiArchiveCandidateStorageKey, JSON.stringify(candidate));
    if ("BroadcastChannel" in window) {
      const channel = new BroadcastChannel(wikiArchiveCandidateChannelName);
      channel.postMessage(candidate);
      channel.close();
    }
  } catch {
    // Local persistence is best-effort; the in-memory control window state still remains usable.
  }
}

function readRendererUiState(key: string): string | null {
  try {
    const electronValue = window.agentDesktop?.getUiState?.(key);
    if (typeof electronValue === "string") {
      return electronValue;
    }
  } catch {
    // Fall through to browser session storage.
  }
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeRendererUiState(key: string, value: string | null): void {
  try {
    window.agentDesktop?.setUiState?.(key, value);
  } catch {
    // Browser fallback below still keeps non-Electron development usable.
  }
  try {
    if (value === null) {
      sessionStorage.removeItem(key);
    } else {
      sessionStorage.setItem(key, value);
    }
  } catch {
    // Best-effort UI state only.
  }
}

function clearRendererResettableState(): void {
  for (const key of [
    "agent-pet.base-url",
    "agent-pet.session-token",
    live2dModelSelectionStorageKey,
    wikiArchiveCandidateStorageKey,
  ]) {
    writeRendererUiState(key, null);
  }
}

function normalizeWikiArchiveCandidate(value: unknown): WikiArchiveCandidate | null {
  const parsed = typeof value === "string" ? parseJson(value) : value;
  if (!parsed || typeof parsed !== "object") {
    return null;
  }
  const candidate = parsed as Partial<WikiArchiveCandidate>;
  const message = candidate.message;
  if (
    !message ||
    message.role !== "assistant" ||
    message.status !== "completed" ||
    typeof message.content !== "string" ||
    !message.content.trim()
  ) {
    return null;
  }
  const citations = Array.isArray(message.citations) ? message.citations.filter(isCitation) : [];
  if (!citations.some(isKnowledgeBaseCitation)) {
    return null;
  }
  return {
    conversation_id: typeof candidate.conversation_id === "string" ? candidate.conversation_id : null,
    message: { ...message, citations },
    question: typeof candidate.question === "string" ? candidate.question : null,
    updated_at: typeof candidate.updated_at === "string" ? candidate.updated_at : new Date().toISOString(),
  };
}

function clampWikiMaxPages(value: number | undefined): number {
  if (!Number.isFinite(value)) {
    return 15;
  }
  return Math.max(1, Math.min(15, Math.trunc(value || 15)));
}

function isKnowledgeBaseCitation(citation: Citation): boolean {
  return citation.source_scope === "knowledge_base" || citation.relative_path.startsWith("Wiki/");
}

function toMemorySearchResultCitation(citation: Citation): MemorySearchResult {
  const relativePath = citation.relative_path;
  const title = citation.title?.trim() || titleFromRelativePath(relativePath);
  const heading = citation.heading ?? null;
  const snippet = citation.snippet?.trim() || relativePath;
  const sourceScope =
    citation.source_scope === "knowledge_base" || relativePath.startsWith("Wiki/")
      ? "knowledge_base"
      : citation.source_scope || "knowledge_base";
  return {
    note_id: citation.note_id || relativePath,
    chunk_id: citation.chunk_id || `${relativePath}:${heading || ""}:${snippet.slice(0, 32)}`,
    relative_path: relativePath,
    title,
    heading,
    snippet,
    score: typeof citation.score === "number" ? citation.score : 1,
    source_scope: sourceScope,
    retrieval_mode: citation.retrieval_mode || "fts",
  };
}

function findLatestArchivableAssistantMessage(messages: ChatMessage[]): ChatMessage | undefined {
  return [...messages]
    .reverse()
    .find(
      (message) =>
        message.role === "assistant" &&
        message.status === "completed" &&
        Boolean(message.content.trim()) &&
        Boolean(message.citations?.some(isKnowledgeBaseCitation)),
    );
}

function findQuestionForAssistantMessage(messages: ChatMessage[], assistantMessageId: string): string | null {
  const assistantIndex = messages.findIndex((message) => message.id === assistantMessageId);
  if (assistantIndex <= 0) {
    return null;
  }
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "user" && message.content.trim()) {
      return message.content.trim();
    }
  }
  return null;
}

function buildWikiArchiveTitle(citations: Citation[]): string {
  const first = citations[0];
  if (first?.title?.trim()) {
    return `查询归档 - ${first.title.trim()}`;
  }
  if (first?.heading?.trim()) {
    return `查询归档 - ${first.heading.trim()}`;
  }
  if (first?.relative_path) {
    return `查询归档 - ${first.relative_path.replace(/^Wiki\//, "").replace(/\.md$/i, "")}`;
  }
  return "查询归档";
}

function getWikiArchiveId(archive: Pick<WikiQueryArchiveHistoryItem, "archive_id" | "id">): string {
  return archive.archive_id || archive.id || "";
}

function formatWikiArchiveHistoryMeta(archive: WikiQueryArchiveHistoryItem): string {
  const id = getWikiArchiveId(archive);
  const pageStatus = archive.page?.status || archive.page_status;
  return uniqueCompactList([
    id ? `ID ${id.slice(0, 12)}` : null,
    archive.page?.relative_path || archive.target_path,
    `${archive.citation_count ?? 0} 条引用`,
    pageStatus ? formatTaskStatus(pageStatus) : null,
    formatCompactDateTime(archive.created_at),
  ]).join(" / ");
}

function formatWikiArchiveDetail(detail: WikiQueryArchiveDetailResponse): string {
  const citations = detail.citations.map((citation, index) => {
    const heading = citation.heading ? ` # ${citation.heading}` : "";
    return `${index + 1}. ${citation.relative_path}${heading}`;
  });
  return [
    `归档：${getWikiArchiveId(detail) || detail.id}`,
    `问题：${detail.question}`,
    `标题：${detail.title}`,
    `目标：${detail.target_path}${detail.section ? ` / ${detail.section}` : ""}`,
    `标签：${detail.tags.length > 0 ? detail.tags.join(", ") : "无"}`,
    "",
    "回答：",
    detail.answer,
    "",
    "引用：",
    citations.length > 0 ? citations.join("\n") : "无",
  ].join("\n");
}

function formatCompactDateTime(value?: string | null): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatWikiWorkflowResult(
  result: WikiIngestApplyResponse | WikiQueryArchiveResponse | WikiSynthesizeResponse | null,
): string {
  if (!result) {
    return "无";
  }
  if ("page_results" in result) {
    const core = uniqueCompactList([
      result.index_updated ? "索引已更新" : null,
      result.log_appended ? "日志已追加" : null,
      result.lint_summary && typeof result.lint_summary.issues === "number" ? `${result.lint_summary.issues} 个检查问题` : null,
    ]).join(" / ");
    return `${formatTaskStatus(result.status)} / ${result.pages_written}/${result.page_results.length} 页${core ? ` / ${core}` : ""}`;
  }
  if ("lint" in result) {
    return `${result.archive_id ? `${result.archive_id} / ` : ""}${result.page.relative_path} / ${formatTaskStatus(result.page.status)}`;
  }
  const core = uniqueCompactList([
    result.index_updated ? "索引已更新" : null,
    result.log_appended ? "日志已追加" : null,
  ]).join(" / ");
  return `${result.page.relative_path} / ${formatTaskStatus(result.page.status)}${core ? ` / ${core}` : ""}`;
}

function formatWikiPreview(preview: WikiIngestPreviewResponse): string {
  const lines = [
    `运行：${preview.run_id}`,
    `来源：${preview.source_id}`,
    `哈希：${preview.source_hash}`,
    "",
    preview.summary,
    "",
    "计划页面：",
  ];
  preview.page_plans.forEach((plan, index) => {
    lines.push(`${index + 1}. ${plan.target_path} (${plan.operation}${plan.section ? ` / ${plan.section}` : ""})`);
  });
  return lines.join("\n");
}

function titleFromRelativePath(relativePath: string): string {
  const filename = relativePath.split(/[\\/]/).pop() || relativePath;
  return filename.replace(/\.md$/i, "") || "Wiki 来源";
}

function isMemoryProposalType(value: unknown): value is MemoryProposalType {
  return typeof value === "string" && memoryTypes.includes(value as MemoryProposalType);
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

function formatCitationSourceLabel(citations: Citation[]): string {
  const sourceScope = citations[0]?.source_scope;
  if (sourceScope === "personal_memory") {
    return "记忆";
  }
  if (sourceScope === "daily_chat") {
    return "聊天日记";
  }
  if (sourceScope === "knowledge_base") {
    return "资料";
  }
  return "记忆/资料";
}

function formatWorkflowStatus(status: CoreWorkflowItem["status"]): string {
  const labels: Record<CoreWorkflowItem["status"], string> = {
    done: "已就绪",
    active: "进行中",
    blocked: "待处理",
  };
  return labels[status];
}

function formatReminderNotificationStatus(summary: ReminderNotificationSummary): string {
  const labels: Record<ReminderNotificationSummary["status"], string> = {
    idle: "未触发",
    shown: "已送达",
    duplicate: "已去重",
    unsupported: "不支持",
    failed: "失败",
  };
  return `${labels[summary.status]}，${summary.detail}`;
}

function formatRunStatus(status: NonNullable<ChatMessage["status"]>): string {
  const labels: Record<NonNullable<ChatMessage["status"]>, string> = {
    partial: "生成中",
    completed: "已完成",
    failed: "失败，请查看消息",
    cancelled: "已取消",
  };
  return labels[status];
}

function formatProposalStatus(status: MemoryProposal["status"]): string {
  const labels: Record<MemoryProposal["status"], string> = {
    pending: "待确认",
    confirmed: "已确认",
    rejected: "已拒绝",
    failed: "失败，未写入",
  };
  return labels[status] || status;
}

function formatIssueSeverity(severity: string): string {
  const labels: Record<string, string> = {
    error: "错误",
    warning: "警告",
    info: "提示",
  };
  return labels[severity] || severity;
}

function formatTaskStatus(status: string): string {
  if (status === "reviewed") {
    return "已审查";
  }
  if (status === "model_not_configured") {
    return "模型未配置";
  }
  const labels: Record<string, string> = {
    pending: "待处理",
    done: "已完成",
    cancelled: "已取消",
    failed: "失败，需处理",
    scheduled: "已安排",
    unscheduled: "未安排",
    completed: "已完成",
    indexed: "已索引",
    bound: "已绑定",
  };
  return labels[status] || status;
}

function formatOptional(value?: string | null): string {
  return value && value.trim() ? formatTaskStatus(value) : "无";
}

function formatTimezoneForUser(value?: string | null): string {
  if (!value) {
    return "";
  }
  const normalized = value.trim();
  if (["Asia/Shanghai", "Asia/Beijing", "Beijing", "北京", "北京时间"].includes(normalized)) {
    return "北京时间";
  }
  return normalized;
}

function formatBooleanStatus(value?: boolean): string {
  if (typeof value !== "boolean") {
    return "未加载";
  }
  return value ? "是" : "否";
}

function formatBusinessAuthStatus(status: "unknown" | "checking" | "ready" | "unauthorized" | "error"): string {
  const labels: Record<typeof status, string> = {
    unknown: "未检查",
    checking: "检查中",
    ready: "可用",
    unauthorized: "令牌不一致",
    error: "异常",
  };
  return labels[status];
}

function businessAuthMismatchMessage(): string {
  return "后端健康检查通过，但业务接口鉴权失败。可能已有 8765 后端和当前桌面端会话令牌不一致，请关闭旧后端后重新运行 npm run electron:dev。";
}

function formatModelTestResult(result: ModelTestResponse): string {
  const latency = typeof result.latency_ms === "number" ? `，耗时 ${result.latency_ms}ms` : "";
  if (result.status === "ok") {
    return `成功：${result.model || "当前模型"}${latency}`;
  }
  const code = result.error_code ? `（${result.error_code}）` : "";
  return `失败${code}：${result.message}${latency}`;
}

function formatHash(value?: string | null): string {
  if (!value) {
    return "无";
  }
  return value.length > 12 ? `${value.slice(0, 12)}...` : value;
}

function formatDiffSummary(diff?: string | null): string {
  if (!diff) {
    return "无";
  }
  const added = (diff.match(/^\+/gm) || []).length;
  const removed = (diff.match(/^-/gm) || []).length;
  return `+${added} / -${removed}`;
}

function formatTableCounts(counts: Record<string, number>): string {
  const entries = Object.entries(counts);
  if (!entries.length) {
    return "无";
  }
  return entries.map(([name, count]) => `${name} ${count}`).join(", ");
}

function formatMessageRole(role: ChatMessage["role"]): string {
  const labels: Record<ChatMessage["role"], string> = {
    user: "用户",
    assistant: "助手",
    system: "系统",
  };
  return labels[role];
}

function formatSidecarState(state: DesktopSidecarStatus["state"]): string {
  const labels: Record<DesktopSidecarStatus["state"], string> = {
    stopped: "已停止",
    "checking-port": "正在检查端口",
    starting: "正在启动",
    ready: "已就绪",
    error: "异常",
    stopping: "正在停止",
  };
  return labels[state];
}

function formatSidecarErrorCode(code: string): string {
  const labels: Record<string, string> = {
    PORT_CHECK_FAILED: "端口检查失败",
    PORT_IN_USE: "端口被占用",
    PORT_IN_USE_EXISTING_BACKEND: "复用已有后端",
    BACKEND_NOT_FOUND: "未找到后端目录",
    READINESS_FAILED: "健康检查未通过",
    SPAWN_FAILED: "启动后端失败",
    PROCESS_EXITED: "后端进程退出",
  };
  return labels[code] || code;
}

function formatHealthStatus(status: string): string {
  return status === "ok" ? "正常" : status;
}

function formatDatabaseStatus(status?: string | null): string {
  if (!status) {
    return "未知";
  }
  const labels: Record<string, string> = {
    connected: "已连接",
    not_configured: "未配置",
    reachable: "可访问",
    ok: "正常",
  };
  return labels[status] || status;
}

function formatVaultStatus(status: string): string {
  const labels: Record<string, string> = {
    bound: "绑定",
    created: "创建",
    initialized: "初始化",
  };
  return labels[status] || status;
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

function describeError(error: unknown, prefix?: string): string {
  const lead = prefix ? `${prefix}: ` : "";
  if (error instanceof ApiError) {
    const code = error.code ? `${error.code}: ` : "";
    const request = error.requestId ? ` (request ${error.requestId})` : "";
    return `${lead}${code}${error.message}${request}`;
  }
  if (error instanceof Error) {
    if (error.name === "TypeError" && /fetch|network/i.test(error.message)) {
      return `${lead}无法连接后端。请确认桌面端已启动托管后端，或检查后端地址和端口 8765。`;
    }
    return `${lead}${error.message}`;
  }
  return `${lead}发生未知桌面客户端错误。`;
}

export default App;
