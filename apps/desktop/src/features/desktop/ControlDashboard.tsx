import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { ComponentProps, CSSProperties, FormEvent, ReactNode, Ref } from "react";
import {
  BookOpen,
  CalendarDays,
  Cat,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Database,
  ExternalLink,
  Heart,
  Image,
  ListFilter,
  Loader2,
  Mic,
  MoreVertical,
  Paperclip,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Star,
  Utensils,
  X,
} from "lucide-react";
import type {
  ChatMessage,
  ContinuityStateResponse,
  DesktopSidecarStatus,
  HealthResponse,
  TaskItem,
} from "../../types";
import type { DesktopApi } from "../../services/desktopApi";
import {
  getAgentActionDisplayFields,
  type AgentActivityLogEntry,
} from "../../services/agentActivity";
import { ConnectionStatusStrip } from "../connection/HealthStatus";
import { VisibleContinuityPanel } from "../continuity";
import { ChatMessageList } from "../chat/ChatMessageList";
import { HalfbodyPetPortrait, type HalfbodyPetPortraitHandle } from "../halfbody/HalfbodyPetPortrait";
import { TaskPanel } from "../tasks/TaskPanel";
import { formatTaskStatus } from "../tasks/taskReducer";
import { BottomNav } from "../../views/BottomNav";
import { navigationHashForTab, type PrimaryNavigationTab } from "../../views/navigation";
import { readRendererUiState, writeRendererUiState } from "../../services/rendererUiState";
import { useVersionedPublicAsset } from "../../hooks/useVersionedPublicAsset";
import { paginatePetBubbleReply } from "../../services/petBubblePagination";
import { productCopy } from "../../productCopy";
import type { AdvancedManagementToolsProps } from "./AdvancedManagementTools";

const AdvancedManagementTools = lazy(() =>
  import("./AdvancedManagementTools").then((module) => ({ default: module.AdvancedManagementTools })),
);

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type AsyncStatus = "idle" | "loading" | "success" | "empty" | "error";
type SpeechCopy = {
  title: string;
  pages: string[];
};

export type ControlWorkflowItem = {
  label: string;
  status: "done" | "active" | "blocked";
  detail: string;
  targetId?: string;
};

type ControlDashboardProps = {
  sidecarStatus: DesktopSidecarStatus | null;
  health: HealthResponse | null;
  notice: Notice | null;
  ttsActive: boolean;
  api: DesktopApi;
  halfbodyPortraitRef?: Ref<HalfbodyPetPortraitHandle>;
  firstUseOnboardingPanel: ReactNode;
  controlInput: string;
  hasConnection: boolean;
  streaming: boolean;
  onControlInputChange: (value: string) => void;
  onSubmitControlChat: (event: FormEvent) => void;
  onStopStreaming: () => void;
  pendingManualActivityCount: number;
  agentActionsStatus: AsyncStatus;
  hasAgentActivity: boolean;
  recentAgentActivityCount: number;
  loadingProposals: boolean;
  loadingContinuity: boolean;
  agentActionsError: string;
  activityItems: ReactNode[];
  onRefreshActivity: () => void;
  messages: ChatMessage[];
  agentActivityEntries: AgentActivityLogEntry[];
  tasks: TaskItem[];
  chatMessageListProps: ComponentProps<typeof ChatMessageList>;
  workflowItems: ControlWorkflowItem[];
  taskPanelProps: ComponentProps<typeof TaskPanel>;
  continuityState: ContinuityStateResponse | null;
  pendingContinuityCount: number;
  onLoadContinuity: () => void;
  onLocateWorkflowTarget: (targetId?: string) => void;
  modelStatusLabel: string;
  knowledgeStatusLabel: string;
  advancedTools: AdvancedManagementToolsProps;
};

type MemoryTone = "rose" | "green" | "blue";

export type MemoryTimelineEntry = {
  id: string;
  targetId?: string;
  sortKey: number;
  time: string;
  date: string;
  title: string;
  tag: string;
  tone: MemoryTone;
  detail: string;
};

export type MemoryDayGroup = {
  key: string;
  title: string;
  subtitle: string;
  totalCount: number;
  entries: MemoryTimelineEntry[];
};

export type OrbitItem = {
  key: string;
  className: string;
  label: string;
  date: string;
};

type HomeGoalItem = {
  id: string;
  title: string;
  done: boolean;
  createdAt: string;
};

type HomeDayRecord = {
  journal: string;
  goals: HomeGoalItem[];
};

const memoryFilterOptions = ["全部", "记忆", "任务", "聊天"] as const;
type MemoryFilter = (typeof memoryFilterOptions)[number];

const maxExpandedMemoryEntriesPerDay = 5;
const defaultExpandedMemoryEntriesPerDay = 3;
const minExpandedMemoryEntriesPerDay = 2;
const estimatedMemoryDayHeaderHeight = 44;
const estimatedMemoryDayGap = 8;
const estimatedMemoryEntryHeight = 112;
const estimatedMemoryEntryGap = 12;
const visibleCollapsedMemoryDayBudget = 1;
const homeGoalsPerPage = 3;
const homeDayRecordsStorageKey = "agent-pet.control-home-day-records.v1";
const emptyHomeDayRecord: HomeDayRecord = { journal: "", goals: [] };

const quickPromptOptions = [...productCopy.home.quickPrompts];

export function ControlDashboard({
  sidecarStatus,
  health,
  notice,
  ttsActive,
  api,
  halfbodyPortraitRef,
  firstUseOnboardingPanel,
  controlInput,
  hasConnection,
  streaming,
  onControlInputChange,
  onSubmitControlChat,
  onStopStreaming,
  pendingManualActivityCount,
  agentActionsStatus,
  hasAgentActivity,
  recentAgentActivityCount,
  loadingProposals,
  loadingContinuity,
  agentActionsError,
  activityItems,
  onRefreshActivity,
  messages,
  agentActivityEntries,
  tasks,
  chatMessageListProps,
  taskPanelProps,
  continuityState,
  pendingContinuityCount,
  onLoadContinuity,
  onLocateWorkflowTarget,
  modelStatusLabel,
  knowledgeStatusLabel,
  advancedTools,
}: ControlDashboardProps) {
  const composerInputRef = useRef<HTMLInputElement | null>(null);
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const journalInputRef = useRef<HTMLTextAreaElement | null>(null);
  const [supportToolsOpen, setSupportToolsOpen] = useState(false);
  const [secondaryToolsOpen, setSecondaryToolsOpen] = useState(false);
  const [memoriesOpen, setMemoriesOpen] = useState(false);
  const [memoryFilter, setMemoryFilter] = useState<MemoryFilter>("全部");
  const memoryDaysRef = useRef<HTMLDivElement | null>(null);
  const didAutoExpandMemoryRef = useRef(false);
  const [expandedMemoryDayKey, setExpandedMemoryDayKey] = useState<string | null>(null);
  const [expandedMemoryEntryLimit, setExpandedMemoryEntryLimit] = useState(defaultExpandedMemoryEntriesPerDay);
  const [dateOffset, setDateOffset] = useState(0);
  const [quickPromptsOpen, setQuickPromptsOpen] = useState(false);
  const [goalComposerOpen, setGoalComposerOpen] = useState(false);
  const [goalPageIndex, setGoalPageIndex] = useState(0);
  const [goalDraft, setGoalDraft] = useState("");
  const [homeDayRecords, setHomeDayRecords] = useState<Record<string, HomeDayRecord>>(() => readHomeDayRecords());
  const [speechPageIndex, setSpeechPageIndex] = useState(0);
  const activityLoading = agentActionsStatus === "loading" || loadingProposals || loadingContinuity;
  const latestAssistantMessage = useMemo(() => findLatestMessage(messages, "assistant"), [messages]);
  const memoryDays = useMemo(
    () => buildMemoryDayGroups(agentActivityEntries, messages, tasks),
    [agentActivityEntries, messages, tasks],
  );
  const visibleMemoryDays = useMemo(
    () => filterMemoryDayGroups(memoryDays, memoryFilter),
    [memoryDays, memoryFilter],
  );
  const renderedMemoryDays = useMemo(
    () => selectVisibleMemoryDaysForReview(visibleMemoryDays, expandedMemoryDayKey),
    [visibleMemoryDays, expandedMemoryDayKey],
  );
  const orbitItems = useMemo(() => buildOrbitItems(memoryDays), [memoryDays]);
  const displayedMemoryDays = renderedMemoryDays;
  const activeMemoryDayKey = expandedMemoryDayKey;
  const displayedMemoryEntryLimit = expandedMemoryEntryLimit;
  const displayedOrbitItems = orbitItems;
  const displayDate = addDays(new Date(), dateOffset);
  const displayDateKey = formatDateKey(displayDate);
  const selectedDayRecord = homeDayRecords[displayDateKey] || emptyHomeDayRecord;
  const dayGoals = selectedDayRecord.goals;
  const doneGoalCount = dayGoals.filter((item) => item.done).length;
  const goalTotal = dayGoals.length;
  const goalPageCount = Math.max(1, Math.ceil(goalTotal / homeGoalsPerPage));
  const safeGoalPageIndex = Math.min(goalPageIndex, goalPageCount - 1);
  const visibleGoals = goalComposerOpen
    ? []
    : dayGoals.slice(safeGoalPageIndex * homeGoalsPerPage, safeGoalPageIndex * homeGoalsPerPage + homeGoalsPerPage);
  const todayLabel = formatTodayLabel(displayDate);
  const connectionCopy = hasConnection ? "本地模式 · 已连接" : "本地模式 · 连接中";
  const petMood = continuityState?.current_mood?.trim() || (streaming ? "专注" : hasConnection ? "陪伴中" : "等待");
  const energyCopy =
    continuityState?.energy_level?.trim() || (streaming ? "思考中" : hasConnection ? "在线" : "待连接");
  const affinityLabel = buildAffinityLabel(messages, agentActivityEntries, tasks, continuityState);
  const moodScore = buildPetVitalScore("mood", streaming, hasConnection, continuityState);
  const energyScore = buildPetVitalScore("energy", streaming, hasConnection, continuityState);
  const speechCopy = useMemo(
    () => buildSpeechCopy(streaming, hasConnection, latestAssistantMessage),
    [hasConnection, latestAssistantMessage, streaming],
  );
  const speechPageCount = Math.max(1, speechCopy.pages.length);
  const safeSpeechPageIndex = Math.min(speechPageIndex, speechPageCount - 1);
  const speechDetail = speechCopy.pages[safeSpeechPageIndex] || "";
  const voiceWaveActive = ttsActive || streaming;
  const homeImageSrc = useVersionedPublicAsset("/images/home.png");
  const detailDrawerOpen = memoriesOpen || supportToolsOpen || secondaryToolsOpen;
  const speechResetKey = latestAssistantMessage
    ? `${latestAssistantMessage.id}:${latestAssistantMessage.content}`
    : `${streaming}:${hasConnection}`;

  useEffect(() => {
    setGoalDraft("");
    setGoalComposerOpen(false);
    setGoalPageIndex(0);
  }, [displayDateKey]);

  useEffect(() => {
    setGoalPageIndex((currentIndex) => Math.min(currentIndex, goalPageCount - 1));
  }, [goalPageCount]);

  useEffect(() => {
    setSpeechPageIndex(0);
  }, [speechResetKey]);

  useEffect(() => {
    setSpeechPageIndex((currentIndex) => Math.min(currentIndex, speechPageCount - 1));
  }, [speechPageCount]);

  useEffect(() => {
    void writeRendererUiState(homeDayRecordsStorageKey, JSON.stringify(homeDayRecords));
  }, [homeDayRecords]);

  useEffect(() => {
    setExpandedMemoryDayKey((currentKey) => {
      if (currentKey && visibleMemoryDays.some((day) => day.key === currentKey)) {
        return currentKey;
      }
      if (!didAutoExpandMemoryRef.current && visibleMemoryDays.length > 0) {
        didAutoExpandMemoryRef.current = true;
        return visibleMemoryDays[0].key;
      }
      return null;
    });
  }, [visibleMemoryDays]);

  useEffect(() => {
    const daysElement = memoryDaysRef.current;
    if (!daysElement) {
      return;
    }
    const updateEntryLimit = () => {
      setExpandedMemoryEntryLimit(
        calculateExpandedMemoryEntryLimit(daysElement.clientHeight, renderedMemoryDays.length),
      );
    };
    updateEntryLimit();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateEntryLimit);
      return () => window.removeEventListener("resize", updateEntryLimit);
    }
    const resizeObserver = new ResizeObserver(updateEntryLimit);
    resizeObserver.observe(daysElement);
    return () => resizeObserver.disconnect();
  }, [renderedMemoryDays.length]);

  useEffect(() => {
    const daysElement = memoryDaysRef.current;
    if (!daysElement || !expandedMemoryDayKey) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      const expandedDay = daysElement.querySelector<HTMLElement>(
        `[data-memory-day-key="${expandedMemoryDayKey}"]`,
      );
      if (!expandedDay) {
        return;
      }
      const dayTop = expandedDay.offsetTop - daysElement.offsetTop;
      const dayBottom = dayTop + expandedDay.offsetHeight;
      const viewportTop = daysElement.scrollTop;
      const viewportBottom = viewportTop + daysElement.clientHeight;
      const scrollPadding = 8;
      let nextTop: number | null = null;

      if (dayTop < viewportTop + scrollPadding) {
        nextTop = Math.max(0, dayTop - scrollPadding);
      } else if (dayBottom > viewportBottom - scrollPadding) {
        nextTop = Math.max(0, dayBottom - daysElement.clientHeight + scrollPadding);
      }

      if (nextTop !== null && Math.abs(nextTop - viewportTop) > 1) {
        if (typeof daysElement.scrollTo === "function") {
          daysElement.scrollTo({ top: nextTop, behavior: "auto" });
          return;
        }
        daysElement.scrollTop = nextTop;
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [expandedMemoryDayKey]);

  const updateSelectedDayRecord = (updater: (record: HomeDayRecord) => HomeDayRecord) => {
    setHomeDayRecords((currentRecords) => {
      const currentRecord = currentRecords[displayDateKey] || emptyHomeDayRecord;
      const nextRecord = normalizeHomeDayRecord(updater(currentRecord));
      return {
        ...currentRecords,
        [displayDateKey]: nextRecord,
      };
    });
  };

  const updateJournal = (value: string) => {
    updateSelectedDayRecord((record) => ({
      ...record,
      journal: value,
    }));
  };

  const createGoal = () => {
    const title = goalDraft.trim();
    if (!title) {
      return;
    }
    updateSelectedDayRecord((record) => ({
      ...record,
      goals: [
        ...record.goals,
        {
          id: createHomeGoalId(),
          title,
          done: false,
          createdAt: new Date().toISOString(),
        },
      ],
    }));
    setGoalPageIndex(Math.floor(dayGoals.length / homeGoalsPerPage));
    setGoalComposerOpen(false);
    setGoalDraft("");
  };

  const toggleGoal = (goalId: string) => {
    updateSelectedDayRecord((record) => ({
      ...record,
      goals: record.goals.map((goal) => (goal.id === goalId ? { ...goal, done: !goal.done } : goal)),
    }));
  };

  const removeGoal = (goalId: string) => {
    updateSelectedDayRecord((record) => ({
      ...record,
      goals: record.goals.filter((goal) => goal.id !== goalId),
    }));
  };

  const focusComposer = () => {
    window.setTimeout(() => composerInputRef.current?.focus(), 0);
  };

  const appendControlInput = (snippet: string) => {
    const normalizedSnippet = snippet.trim();
    if (!normalizedSnippet) {
      return;
    }
    const separator = controlInput.trim() ? " " : "";
    onControlInputChange(`${controlInput}${separator}${normalizedSnippet}`);
    focusComposer();
  };

  const openDetailDrawer = (drawer: "memories" | "support" | "advanced") => {
    setMemoriesOpen(drawer === "memories");
    setSupportToolsOpen(drawer === "support");
    setSecondaryToolsOpen(drawer === "advanced");
  };

  const toggleDetailDrawer = (drawer: "memories" | "support" | "advanced") => {
    const currentlyOpen =
      (drawer === "memories" && memoriesOpen) ||
      (drawer === "support" && supportToolsOpen) ||
      (drawer === "advanced" && secondaryToolsOpen);
    if (currentlyOpen) {
      setMemoriesOpen(false);
      setSupportToolsOpen(false);
      setSecondaryToolsOpen(false);
      return;
    }
    openDetailDrawer(drawer);
  };

  const navigateToTab = (tab: PrimaryNavigationTab) => {
    window.location.hash = navigationHashForTab(tab);
  };

  const locateWorkflowTarget = (targetId?: string) => {
    if (!targetId) {
      openDetailDrawer("advanced");
      return;
    }
    if (targetId.startsWith("task-")) {
      navigateToTab("计划");
      return;
    }
    if (targetId === "continuity-panel") {
      openDetailDrawer("support");
    } else if (targetId === "advanced-tools") {
      openDetailDrawer("advanced");
    } else {
      openDetailDrawer("memories");
    }
    window.setTimeout(() => onLocateWorkflowTarget(targetId), 80);
  };

  const handleOpenStageWindow = () => {
    const openStage = window.agentDesktop?.openStage?.("stage");
    if (openStage) {
      void openStage.catch(() => {
        navigateToTab("首页");
      });
      return;
    }
    navigateToTab("首页");
  };

  const handleFileSelection = (files: FileList | null, kind: "附件" | "图片") => {
    if (!files || files.length === 0) {
      return;
    }
    const fileNames = Array.from(files)
      .map((file) => file.name.trim())
      .filter(Boolean)
      .join("、");
    if (fileNames) {
      appendControlInput(`[${kind}：${fileNames}]`);
    }
  };

  const cycleMemoryFilter = () => {
    const currentIndex = memoryFilterOptions.indexOf(memoryFilter);
    setMemoryFilter(memoryFilterOptions[(currentIndex + 1) % memoryFilterOptions.length]);
  };

  const toggleMemoryDay = (dayKey: string) => {
    setExpandedMemoryDayKey((currentKey) => (currentKey === dayKey ? null : dayKey));
  };

  return (
    <main className="app-shell control-home-shell">
      <div className="control-home-backdrop" aria-hidden="true" />
      <header className="control-home-header">
        <div className="control-brand">
          <span className="control-brand-icon" aria-hidden="true">
            <Cat size={24} />
          </span>
          <span>
            <strong>Agent Pet</strong>
            <small>{connectionCopy}</small>
          </span>
        </div>
        <button type="button" className="control-icon-button" aria-label="打开新窗口" onClick={handleOpenStageWindow}>
          <ExternalLink size={18} />
        </button>
      </header>

      {notice ? (
        <div className={`notice ${notice.tone}`} role="status">
          {notice.tone === "error" ? <CircleAlert size={18} /> : <ShieldCheck size={18} />}
          <span>{notice.message}</span>
        </div>
      ) : null}

      <section className="control-desktop-grid" aria-label="Agent Pet 首页">
        <aside className="control-left-rail" aria-label="今日随行">
          <div className="control-date-card">
            <strong>{todayLabel.replace("星期", " 星期")}</strong>
            <span className="control-date-actions">
              <button type="button" aria-label="查看前一天" onClick={() => setDateOffset((value) => value - 1)}>
                <ChevronLeft size={18} />
              </button>
              <button
                type="button"
                aria-label="回到今天"
                onClick={() => setDateOffset(0)}
                disabled={dateOffset === 0}
              >
                <ChevronRight size={18} />
              </button>
            </span>
          </div>

          <section className="control-glass-card control-journal-card">
            <div className="control-card-title">
              <strong>今日随记</strong>
              <NotebookAction onEdit={() => journalInputRef.current?.focus()} />
            </div>
            <textarea
              ref={journalInputRef}
              value={selectedDayRecord.journal}
              onChange={(event) => updateJournal(event.target.value.slice(0, 200))}
              placeholder="今天想记录些什么呢？"
              rows={3}
            />
            <span>{dateOffset === 0 ? "这条随记只属于今天。" : "正在编辑所选日期的随记。"}</span>
            <small>{Array.from(selectedDayRecord.journal).length}/200</small>
          </section>

          <section className={`control-glass-card control-goals-card${goalComposerOpen ? " is-creating-goal" : ""}`}>
            <div className="control-card-title">
              <strong>今日目标</strong>
              <span>{Math.min(doneGoalCount, goalTotal)}/{goalTotal}</span>
              <button
                type="button"
                className="control-mini-button"
                aria-label={goalComposerOpen ? "关闭目标创建" : "创建今日目标"}
                aria-pressed={goalComposerOpen}
                onClick={() => {
                  setGoalComposerOpen((open) => !open);
                  setGoalDraft("");
                }}
              >
                {goalComposerOpen ? <X size={16} /> : <Plus size={16} />}
              </button>
            </div>
            {goalComposerOpen ? (
              <form
                className="control-goal-form control-goal-create-pane"
                onSubmit={(event) => {
                  event.preventDefault();
                  createGoal();
                }}
              >
                <input
                  autoFocus
                  value={goalDraft}
                  onChange={(event) => setGoalDraft(event.target.value)}
                  placeholder={dateOffset === 0 ? "创建今天的目标..." : "创建所选日期的目标..."}
                  maxLength={32}
                />
                <button type="submit" className="control-goal-create-submit" disabled={!goalDraft.trim()}>
                  <Check size={14} />
                  保存
                </button>
              </form>
            ) : (
              <div className={`control-goal-list-pane${goalPageCount > 1 ? " has-goal-pages" : ""}`}>
                <div className="control-goal-list" aria-label="今日目标列表">
                  {visibleGoals.map((item) => (
                    <div
                      key={item.id}
                      className={`control-goal-row ${item.done ? "done" : "active"}`}
                    >
                      <button
                        type="button"
                        className="control-goal-toggle"
                        aria-pressed={item.done}
                        onClick={() => toggleGoal(item.id)}
                      >
                        <span aria-hidden="true">{item.done ? <Check size={12} /> : null}</span>
                        <strong>{item.title}</strong>
                      </button>
                      <button
                        type="button"
                        className="control-goal-delete"
                        aria-label={`Delete goal: ${item.title}`}
                        onClick={() => removeGoal(item.id)}
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                </div>
                {goalPageCount > 1 ? (
                  <div className="control-goal-pager" aria-label="目标分页">
                    <button
                      type="button"
                      aria-label="上一页目标"
                      onClick={() => setGoalPageIndex((index) => Math.max(0, index - 1))}
                      disabled={safeGoalPageIndex <= 0}
                    >
                      <ChevronLeft size={14} />
                    </button>
                    <span>{safeGoalPageIndex + 1}/{goalPageCount}</span>
                    <button
                      type="button"
                      aria-label="下一页目标"
                      onClick={() => setGoalPageIndex((index) => Math.min(goalPageCount - 1, index + 1))}
                      disabled={safeGoalPageIndex >= goalPageCount - 1}
                    >
                      <ChevronRight size={14} />
                    </button>
                  </div>
                ) : null}
              </div>
            )}
          </section>

          <section className="control-glass-card control-pet-vitals">
            <strong>宠物状态</strong>
            <div className="control-vital-orb" aria-hidden="true">
              <Heart size={34} fill="currentColor" />
            </div>
            <dl>
              <div>
                <dt>心情</dt>
                <dd>
                  <strong>{moodScore}</strong>
                  <small>{petMood}</small>
                </dd>
              </div>
              <div>
                <dt>精力</dt>
                <dd>
                  <strong>{energyScore}</strong>
                  <small>{energyCopy}</small>
                </dd>
              </div>
              <div>
                <dt>亲密度</dt>
                <dd>
                  <strong>{affinityLabel}</strong>
                  <small>亲密</small>
                </dd>
              </div>
            </dl>
            <button type="button" className="control-wide-button" onClick={() => locateWorkflowTarget("agent-activity-log")}>
              与宠物互动
            </button>
          </section>
        </aside>

        <section className="control-center-stage" aria-label={productCopy.home.stageLabel}>
          <img className="control-stage-background" src={homeImageSrc} alt="" aria-hidden="true" />

          <div className="control-speech-bubble" role="status">
            <strong>{speechCopy.title}</strong>
            <span className="control-speech-bubble-detail">{speechDetail}</span>
            {speechPageCount > 1 ? (
              <div className="control-speech-pager" aria-label="回复分页">
                <button
                  type="button"
                  aria-label="上一页回复"
                  onClick={() => setSpeechPageIndex((index) => Math.max(0, index - 1))}
                  disabled={safeSpeechPageIndex === 0}
                >
                  <ChevronLeft size={14} />
                </button>
                <small>{safeSpeechPageIndex + 1}/{speechPageCount}</small>
                <button
                  type="button"
                  aria-label="下一页回复"
                  onClick={() => setSpeechPageIndex((index) => Math.min(speechPageCount - 1, index + 1))}
                  disabled={safeSpeechPageIndex >= speechPageCount - 1}
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            ) : null}
            <span
              className={`control-voice-wave${voiceWaveActive ? " is-active" : ""}`}
              aria-hidden="true"
            >
              <i />
              <i />
              <i />
              <i />
              <i />
            </span>
          </div>

          {displayedOrbitItems.length > 0 ? (
            <div className="control-orbit-map" aria-hidden="true">
              {displayedOrbitItems.map((item) => (
                <span key={item.key} className={`orbit-point ${item.className}`}>
                  <i />
                  {item.label}
                  <small>{item.date}</small>
                </span>
              ))}
            </div>
          ) : null}

          <HalfbodyPetPortrait
            ref={halfbodyPortraitRef}
            active
            ariaLabel="Agent Pet Neko layered portrait"
            className="control-portrait-anchor control-stage-halfbody"
          />

          <form className="control-stage-composer" onSubmit={onSubmitControlChat} aria-label="和 Agent Pet 聊天">
            <input
              ref={composerInputRef}
              value={controlInput}
              onChange={(event) => onControlInputChange(event.target.value)}
              placeholder={hasConnection ? "和 Agent Pet 聊聊..." : "正在等待本地助手连接..."}
              disabled={streaming}
            />
            <div className="control-composer-tools" aria-label="输入工具">
              <button type="button" aria-label="添加附件" onClick={() => attachmentInputRef.current?.click()}>
                <Paperclip size={18} />
              </button>
              <button type="button" aria-label="添加图片" onClick={() => imageInputRef.current?.click()}>
                <Image size={18} />
              </button>
              <button
                type="button"
                aria-label="快捷表情"
                aria-expanded={quickPromptsOpen}
                onClick={() => setQuickPromptsOpen((open) => !open)}
              >
                <Mic size={18} />
              </button>
            </div>
            {quickPromptsOpen ? (
              <div className="control-quick-prompts" role="menu" aria-label="快捷短句">
                {quickPromptOptions.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      appendControlInput(prompt);
                      setQuickPromptsOpen(false);
                    }}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            ) : null}
            <input
              ref={attachmentInputRef}
              className="control-hidden-file-input"
              type="file"
              multiple
              tabIndex={-1}
              onChange={(event) => {
                handleFileSelection(event.currentTarget.files, "附件");
                event.currentTarget.value = "";
              }}
            />
            <input
              ref={imageInputRef}
              className="control-hidden-file-input"
              type="file"
              accept="image/*"
              multiple
              tabIndex={-1}
              onChange={(event) => {
                handleFileSelection(event.currentTarget.files, "图片");
                event.currentTarget.value = "";
              }}
            />
            <button
              type={streaming ? "button" : "submit"}
              className={streaming ? "control-send-button danger" : "control-send-button"}
              onClick={streaming ? onStopStreaming : undefined}
              disabled={!streaming && (!controlInput.trim() || !hasConnection)}
              aria-label={streaming ? "停止生成" : "发送消息"}
            >
              {streaming ? <X size={20} /> : <Send size={20} />}
            </button>
          </form>
        </section>

        <aside className="control-right-rail" aria-label="记忆回顾">
          <section className="control-memory-panel">
            <div className="control-memory-head">
              <strong>记忆回顾</strong>
              <div className="control-memory-actions" aria-label="记忆工具">
                <button type="button" aria-label="搜索记忆" onClick={() => navigateToTab("记忆")}>
                  <Search size={18} />
                </button>
                <button type="button" aria-label={`筛选记忆：${memoryFilter}`} onClick={cycleMemoryFilter}>
                  <ListFilter size={17} />
                </button>
                <button type="button" aria-label="更多记忆" onClick={() => toggleDetailDrawer("memories")}>
                  <MoreVertical size={18} />
                </button>
              </div>
            </div>
            {memoryFilter !== "全部" ? <p className="control-memory-filter">正在查看：{memoryFilter}</p> : null}

            <div className="control-memory-days" aria-label="按日期排列的记忆记录" ref={memoryDaysRef}>
              {displayedMemoryDays.length > 0 ? (
                displayedMemoryDays.map((day) => (
                  <MemoryDay
                    key={day.key}
                    dayKey={day.key}
                    title={day.title}
                    subtitle={day.subtitle}
                    totalCount={day.totalCount}
                    entries={day.entries}
                    entryLimit={displayedMemoryEntryLimit}
                    isExpanded={activeMemoryDayKey === day.key}
                    onToggle={() => toggleMemoryDay(day.key)}
                    onOpenEntry={locateWorkflowTarget}
                  />
                ))
              ) : (
                <p className="empty-state control-memory-empty">开始聊天或创建任务后，实时记忆会出现在这里。</p>
              )}
            </div>

            <button type="button" className="control-memory-more" onClick={() => toggleDetailDrawer("memories")}>
              查看全部记忆
            </button>
          </section>
        </aside>

        <section className="control-status-left" aria-label="对话能力状态">
          <Settings size={20} />
          <span>
            <strong>{productCopy.home.statusModelTitle}</strong>
            <small>{modelStatusLabel}</small>
          </span>
          <i aria-hidden="true" />
        </section>

        <section className="control-status-right" aria-label="记忆保存状态">
          <Database size={20} />
          <span>
            <strong>{productCopy.home.statusKnowledgeTitle}</strong>
            <small>{knowledgeStatusLabel}</small>
          </span>
          <i aria-hidden="true" />
        </section>

        <footer className="control-bottom-dock">
          <BottomNav activeTab="首页" />
        </footer>
      </section>

      <section className={`control-below-fold${detailDrawerOpen ? " is-open" : ""}`} aria-label="工作台详情">
        <details className="control-detail-drawer" open={memoriesOpen}>
          <summary
            onClick={(event) => {
              event.preventDefault();
              toggleDetailDrawer("memories");
            }}
          >
            <span>
              <Star size={18} />
              {productCopy.home.recentActivityTitle}
            </span>
            <ChevronDown size={18} />
          </summary>
          <div id="agent-activity-log" className="control-drawer-body">
            <div className="control-drawer-toolbar">
              <p>
                {pendingManualActivityCount > 0
                  ? `${pendingManualActivityCount} 件事需要你确认；低风险整理会留下可撤回记录。`
                  : hasAgentActivity
                    ? `最近 ${recentAgentActivityCount} 条整理记录；能撤回的动作会提供入口。`
                    : "我整理过的内容会出现在这里。"}
              </p>
              <button type="button" className="secondary" onClick={onRefreshActivity} disabled={activityLoading}>
                {activityLoading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                刷新
              </button>
            </div>
            {agentActionsError ? <p className="field-note error">{agentActionsError}</p> : null}
            <div className="control-activity-list">
              {activityItems.length > 0 ? activityItems : <p className="empty-state">还没有整理记录。</p>}
            </div>
            <ChatMessageList {...chatMessageListProps} />
          </div>
        </details>

        <details className="control-detail-drawer" open={supportToolsOpen}>
          <summary
            onClick={(event) => {
              event.preventDefault();
              toggleDetailDrawer("support");
            }}
          >
            <span>
              <CalendarDays size={18} />
              计划与连续性
            </span>
            <ChevronDown size={18} />
          </summary>
          {supportToolsOpen ? (
            <div className="control-support-grid">
              <TaskPanel {...taskPanelProps} />
              <section id="continuity-panel" className="control-continuity-card">
                <div className="control-drawer-toolbar">
                  <div>
                    <strong>下次接着聊</strong>
                    <p>{continuityState?.unresolved_threads || "当前没有待确认的延续话题。"}</p>
                  </div>
                  <button type="button" className="secondary" onClick={onLoadContinuity} disabled={loadingContinuity}>
                    {loadingContinuity ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                    刷新
                  </button>
                </div>
                <dl className="control-continuity-grid">
                  <div><dt>当前情绪</dt><dd>{continuityState?.current_mood || "未确认"}</dd></div>
                  <div><dt>能量水平</dt><dd>{continuityState?.energy_level || "未确认"}</dd></div>
                  <div><dt>关系摘要</dt><dd>{continuityState?.relationship_summary || "未确认"}</dd></div>
                  <div><dt>待确认</dt><dd>{pendingContinuityCount} 个</dd></div>
                </dl>
              </section>
              <VisibleContinuityPanel api={api} className="control-continuity-panel" />
            </div>
          ) : null}
        </details>

        <details className="control-detail-drawer" open={secondaryToolsOpen}>
          <summary
            onClick={(event) => {
              event.preventDefault();
              toggleDetailDrawer("advanced");
            }}
          >
            <span>
              <Settings size={18} />
              {productCopy.home.connectionAndDataTitle}
            </span>
            <ChevronDown size={18} />
          </summary>
          {secondaryToolsOpen ? (
            <div id="advanced-tools" className="control-secondary-grid">
              {firstUseOnboardingPanel}
              <ConnectionStatusStrip sidecarStatus={sidecarStatus} health={health} />
              <Suspense fallback={null}>
                <AdvancedManagementTools {...advancedTools} />
              </Suspense>
            </div>
          ) : null}
        </details>
      </section>
    </main>
  );
}

function findLatestMessage(messages: ChatMessage[], role: ChatMessage["role"]): ChatMessage | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === role && message.content.trim()) {
      return message;
    }
  }
  return null;
}

function buildSpeechCopy(
  streaming: boolean,
  hasConnection: boolean,
  latestAssistantMessage: ChatMessage | null,
): SpeechCopy {
  if (streaming) {
    return { title: "我正在整理线索。", pages: ["稍等一下，马上给你回复。"] };
  }
  if (!hasConnection) {
    return { title: "我在等本地助手连接。", pages: ["连接完成后就可以继续聊天和整理记忆。"] };
  }
  const latestReply = latestAssistantMessage?.content.trim();
  if (latestReply) {
    const pages = paginatePetBubbleReply(latestReply);
    return { title: "我刚整理好回复。", pages: pages.length > 0 ? pages : [latestReply] };
  }
  return { title: "欢迎回来，我一直在这里。", pages: ["要和我聊聊今天发生了什么吗？"] };
}

function readHomeDayRecords(): Record<string, HomeDayRecord> {
  const rawValue = readRendererUiState(homeDayRecordsStorageKey);
  if (!rawValue) {
    return {};
  }
  try {
    const parsed = JSON.parse(rawValue) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).flatMap(([key, value]) => {
        const normalized = normalizeHomeDayRecord(value);
        return normalized.journal || normalized.goals.length > 0 ? [[key, normalized]] : [];
      }),
    );
  } catch {
    return {};
  }
}

function normalizeHomeDayRecord(value: unknown): HomeDayRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return emptyHomeDayRecord;
  }
  const record = value as Partial<HomeDayRecord>;
  return {
    journal: typeof record.journal === "string" ? record.journal.slice(0, 200) : "",
    goals: Array.isArray(record.goals)
      ? record.goals.flatMap((goal) => {
          const normalized = normalizeHomeGoal(goal);
          return normalized ? [normalized] : [];
        })
      : [],
  };
}

function normalizeHomeGoal(value: unknown): HomeGoalItem | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const goal = value as Partial<HomeGoalItem>;
  const title = typeof goal.title === "string" ? goal.title.trim().slice(0, 32) : "";
  if (!title) {
    return null;
  }
  return {
    id: typeof goal.id === "string" && goal.id.trim() ? goal.id : createHomeGoalId(),
    title,
    done: goal.done === true,
    createdAt: typeof goal.createdAt === "string" && goal.createdAt.trim() ? goal.createdAt : new Date().toISOString(),
  };
}

function createHomeGoalId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `goal-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function filterMemoryDayGroups(groups: MemoryDayGroup[], filter: MemoryFilter): MemoryDayGroup[] {
  if (filter === "全部") {
    return groups;
  }
  return groups
    .map((group) => {
      const entries = group.entries.filter((entry) => entry.tag === filter);
      return {
        ...group,
        totalCount: entries.length,
        entries,
      };
    })
    .filter((group) => group.entries.length > 0);
}

export function selectVisibleMemoryDaysForReview(
  groups: MemoryDayGroup[],
  expandedDayKey: string | null,
): MemoryDayGroup[] {
  void expandedDayKey;
  return groups;
}

export function buildMemoryDayGroups(
  agentActivityEntries: AgentActivityLogEntry[],
  messages: ChatMessage[],
  tasks: TaskItem[],
): MemoryDayGroup[] {
  const now = new Date();
  const timelineEntries = [
    ...agentActivityEntries.map((entry, index) => activityEntryToTimelineEntry(entry, index, now)),
    ...tasks.slice(0, 4).map((task, index) => taskToTimelineEntry(task, index, now)),
    ...messages
      .filter((message) => message.content.trim())
      .slice(-4)
      .reverse()
      .map((message, index) => messageToTimelineEntry(message, index, now)),
  ];
  const uniqueEntries = new Map<string, MemoryTimelineEntry>();
  timelineEntries.forEach((entry) => {
    if (!uniqueEntries.has(entry.id)) {
      uniqueEntries.set(entry.id, entry);
    }
  });
  const sortedEntries = Array.from(uniqueEntries.values()).sort((left, right) => right.sortKey - left.sortKey);
  const groups = new Map<string, MemoryDayGroup>();
  sortedEntries.forEach((entry) => {
    const date = new Date(entry.sortKey);
    const key = formatDateKey(date);
    const existing =
      groups.get(key) ||
      ({
        key,
        title: formatDayTitle(date),
        subtitle: formatDaySubtitle(date, now),
        totalCount: 0,
        entries: [],
      } satisfies MemoryDayGroup);
    existing.totalCount += 1;
    existing.entries.push(entry);
    groups.set(key, existing);
  });
  return Array.from(groups.values()).sort((left, right) => right.entries[0].sortKey - left.entries[0].sortKey);
}

export function calculateExpandedMemoryEntryLimit(containerHeight: number, dayCount: number): number {
  if (!Number.isFinite(containerHeight) || containerHeight <= 0) {
    return defaultExpandedMemoryEntriesPerDay;
  }
  const normalizedDayCount = Math.max(0, dayCount);
  if (normalizedDayCount === 0) {
    return defaultExpandedMemoryEntriesPerDay;
  }
  const collapsedDayRowsToReserve = Math.min(Math.max(0, normalizedDayCount - 1), visibleCollapsedMemoryDayBudget);
  const reservedForDateRows =
    (1 + collapsedDayRowsToReserve) * estimatedMemoryDayHeaderHeight +
    collapsedDayRowsToReserve * estimatedMemoryDayGap +
    estimatedMemoryDayGap;
  const availableForEntries = containerHeight - reservedForDateRows;
  if (availableForEntries < estimatedMemoryEntryHeight * 1.1) {
    return 1;
  }
  return Math.min(
    maxExpandedMemoryEntriesPerDay,
    Math.max(
      minExpandedMemoryEntriesPerDay,
      Math.floor((availableForEntries + estimatedMemoryEntryGap) / (estimatedMemoryEntryHeight + estimatedMemoryEntryGap)),
    ),
  );
}

function activityEntryToTimelineEntry(
  entry: AgentActivityLogEntry,
  index: number,
  now: Date,
): MemoryTimelineEntry {
  const fallbackSortKey = now.getTime() - index * 1000;
  const sortKey = normalizeSortKey(entry.sortAt, fallbackSortKey);
  if (entry.kind === "agent_action") {
    const display = getAgentActionDisplayFields(entry.action);
    const actionType = entry.action.action_type.toLocaleLowerCase();
    return {
      id: entry.id,
      targetId: entry.id,
      sortKey,
      time: formatTimelineTime(entry.sortAt, display.statusLabel),
      date: formatOrbitDate(sortKey),
      title: truncateText(display.actionName, 16),
      tag: getActionTag(actionType, display.statusLabel),
      tone: getActionTone(actionType),
      detail: truncateText(display.summary, 40),
    };
  }
  if (entry.kind === "memory_proposal") {
    return {
      id: entry.id,
      targetId: entry.id,
      sortKey,
      time: formatTimelineTime(entry.sortAt, "待确认"),
      date: formatOrbitDate(sortKey),
      title: "待确认记忆",
      tag: memoryProposalTypeLabels[entry.proposal.type] || "记忆",
      tone: "blue",
      detail: truncateText(entry.proposal.content, 40),
    };
  }
  if (entry.kind === "continuity_proposal") {
    return {
      id: entry.id,
      targetId: entry.id,
      sortKey,
      time: formatTimelineTime(entry.sortAt, "待确认"),
      date: formatOrbitDate(sortKey),
      title: "延续话题",
      tag: continuityKindLabels[entry.proposal.kind] || "陪伴",
      tone: "rose",
      detail: truncateText(entry.proposal.summary, 40),
    };
  }
  return {
    id: entry.id,
    targetId: entry.id,
    sortKey,
    time: formatTimelineTime(entry.sortAt, "待确认"),
    date: formatOrbitDate(sortKey),
    title: truncateText(entry.proposal.title || "资料整理计划", 16),
    tag: entry.proposal.state === "applied" ? "已写入" : "资料",
    tone: "blue",
    detail: truncateText(entry.proposal.summary || entry.proposal.review_summary || entry.message.content, 40),
  };
}

function taskToTimelineEntry(task: TaskItem, index: number, now: Date): MemoryTimelineEntry {
  const timestamp = pickTaskTimestamp(task);
  const sortKey = timestamp ?? now.getTime() - 300_000 - index * 60_000;
  return {
    id: `task-${task.task_id}`,
    targetId: `task-${task.task_id}`,
    sortKey,
    time: timestamp ? formatTimelineTime(new Date(timestamp).toISOString(), formatTaskStatus(task.status)) : "任务",
    date: formatOrbitDate(sortKey),
    title: truncateText(task.title, 16),
    tag: formatTaskStatus(task.status),
    tone: statusToWorkflowState(task.status) === "done" ? "green" : "rose",
    detail: truncateText(task.description || formatTaskSchedule(task), 40),
  };
}

function messageToTimelineEntry(message: ChatMessage, index: number, now: Date): MemoryTimelineEntry {
  const sortKey = now.getTime() - 600_000 - index * 60_000;
  return {
    id: `message-${message.id}`,
    targetId: `message-${message.id}`,
    sortKey,
    time: message.status === "partial" ? "生成中" : "刚刚",
    date: formatOrbitDate(sortKey),
    title: message.role === "assistant" ? "宠物回复" : "最近输入",
    tag: "聊天",
    tone: message.role === "assistant" ? "green" : "blue",
    detail: truncateText(message.content, 40),
  };
}

export function buildOrbitItems(memoryDays: MemoryDayGroup[]): OrbitItem[] {
  const classNames = ["point-one", "point-two", "point-three", "point-four"];
  return memoryDays
    .flatMap((day) => day.entries)
    .slice(0, 4)
    .map((entry, index) => ({
      key: entry.id,
      className: classNames[index],
      label: truncateText(entry.title, 8),
      date: entry.date,
    }));
}

function buildAffinityLabel(
  messages: ChatMessage[],
  agentActivityEntries: AgentActivityLogEntry[],
  tasks: TaskItem[],
  continuityState: ContinuityStateResponse | null,
): string {
  const continuitySignals = continuityState?.items.length ?? 0;
  const score =
    Math.floor(messages.filter((message) => message.role !== "system").length / 3) +
    agentActivityEntries.length +
    Math.floor(tasks.length / 2) +
    continuitySignals;
  const level = Math.min(9, Math.max(1, 1 + Math.floor(score / 3)));
  return `Lv.${level}`;
}

function buildPetVitalScore(
  kind: "mood" | "energy",
  streaming: boolean,
  hasConnection: boolean,
  continuityState: ContinuityStateResponse | null,
): number {
  if (!hasConnection) {
    return kind === "mood" ? 58 : 42;
  }
  if (streaming) {
    return kind === "mood" ? 76 : 64;
  }
  const hasContinuitySignal =
    kind === "mood" ? Boolean(continuityState?.current_mood?.trim()) : Boolean(continuityState?.energy_level?.trim());
  return hasContinuitySignal ? (kind === "mood" ? 82 : 67) : kind === "mood" ? 78 : 70;
}

function statusToWorkflowState(status: string): ControlWorkflowItem["status"] {
  if (["done", "completed", "indexed", "bound", "reviewed"].includes(status)) {
    return "done";
  }
  if (["failed", "cancelled", "rejected"].includes(status)) {
    return "blocked";
  }
  return "active";
}

function pickTaskTimestamp(task: TaskItem): number | null {
  for (const value of [task.triggered_at, task.due_at, task.remind_at]) {
    if (!value) {
      continue;
    }
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return null;
}

function formatTaskSchedule(task: TaskItem): string {
  const timestamp = pickTaskTimestamp(task);
  if (!timestamp) {
    return formatTaskStatus(task.status);
  }
  return `${formatTaskStatus(task.status)} · ${formatDayTitle(new Date(timestamp))} ${formatTimelineTime(new Date(timestamp).toISOString(), "")}`;
}

function normalizeSortKey(value: string, fallback: number): number {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? fallback : parsed;
}

function formatTimelineTime(value: string, fallback: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return fallback || "刚刚";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    hour12: false,
    minute: "2-digit",
  }).format(new Date(parsed));
}

function formatTodayLabel(date: Date): string {
  return `${formatDayTitle(date)} ${new Intl.DateTimeFormat("zh-CN", { weekday: "long" }).format(date)}`;
}

function formatDayTitle(date: Date): string {
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

function formatDaySubtitle(date: Date, now: Date): string {
  const dayOffset = startOfDay(now).getTime() - startOfDay(date).getTime();
  if (dayOffset === 0) {
    return "今天";
  }
  if (dayOffset === 86_400_000) {
    return "昨天";
  }
  return new Intl.DateTimeFormat("zh-CN", { weekday: "short" }).format(date);
}

function formatOrbitDate(timestamp: number): string {
  return new Intl.DateTimeFormat("zh-CN", {
    day: "2-digit",
    month: "2-digit",
  })
    .format(new Date(timestamp))
    .replace("/", ".");
}

function formatDateKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date: Date, offset: number): Date {
  const nextDate = new Date(date);
  nextDate.setDate(date.getDate() + offset);
  return nextDate;
}

function getActionTag(actionType: string, fallback: string): string {
  if (actionType.startsWith("task.")) {
    return "任务";
  }
  if (actionType.startsWith("wiki.")) {
    return "资料";
  }
  if (actionType.startsWith("continuity.")) {
    return "陪伴";
  }
  if (actionType.includes("memory") || actionType.includes("diary")) {
    return "记忆";
  }
  return fallback || "活动";
}

function getActionTone(actionType: string): MemoryTone {
  if (actionType.startsWith("task.")) {
    return "green";
  }
  if (actionType.startsWith("wiki.")) {
    return "blue";
  }
  return "rose";
}

function truncateText(value: string, maxLength: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  const chars = Array.from(normalized);
  if (chars.length <= maxLength) {
    return normalized;
  }
  return `${chars.slice(0, maxLength - 1).join("")}…`;
}

const memoryProposalTypeLabels: Record<string, string> = {
  event: "事件",
  fact: "事实",
  goal: "目标",
  preference: "偏好",
  rule: "规则",
};

const continuityKindLabels: Record<string, string> = {
  energy: "精力",
  identity: "身份",
  mood: "情绪",
  open_thread: "话题",
  relationship: "关系",
};

function MemoryDay({
  dayKey,
  title,
  subtitle,
  totalCount,
  entries,
  entryLimit,
  isExpanded,
  onToggle,
  onOpenEntry,
}: {
  dayKey: string;
  title: string;
  subtitle: string;
  totalCount: number;
  entries: MemoryTimelineEntry[];
  entryLimit: number;
  isExpanded: boolean;
  onToggle: () => void;
  onOpenEntry: (targetId?: string) => void;
}) {
  const visibleEntries = isExpanded ? entries.slice(0, entryLimit) : [];
  const visibleTimelineMinHeight =
    visibleEntries.length > 0 ? visibleEntries.length * 116 + Math.max(0, visibleEntries.length - 1) * 12 : 0;
  const visibleExpandedDayMinHeight = visibleTimelineMinHeight > 0 ? visibleTimelineMinHeight + 42 : 0;
  const memoryDayStyle =
    visibleTimelineMinHeight > 0
      ? ({
          "--memory-visible-timeline-min-height": `${visibleTimelineMinHeight}px`,
          "--memory-expanded-day-min-height": `${visibleExpandedDayMinHeight}px`,
        } as CSSProperties)
      : undefined;

  return (
    <section
      className={`control-memory-day${isExpanded ? " is-expanded" : " is-collapsed"}`}
      data-memory-day-key={dayKey}
      style={memoryDayStyle}
    >
      <h2>
        <button
          type="button"
          className="control-memory-day-toggle"
          aria-expanded={isExpanded}
          aria-label={`${isExpanded ? "收起" : "展开"}${title} ${subtitle}的记忆记录`}
          onClick={onToggle}
        >
          <span className="control-memory-day-label">
            {title}
            <span>{subtitle}</span>
          </span>
          <span className="control-memory-day-count">{totalCount}</span>
          <ChevronDown size={14} />
        </button>
      </h2>
      {visibleEntries.length > 0 ? (
        <div className="control-memory-timeline">
          {visibleEntries.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={`control-memory-entry memory-timeline-item ${entry.tone}`}
              onClick={() => onOpenEntry(entry.targetId)}
              aria-label={`查看${entry.title}`}
            >
              <span className="control-memory-entry-node memory-time-icon">
                <time className="memory-time">{entry.time}</time>
                <span className="control-memory-entry-dot" aria-hidden="true" />
              </span>
              <div className="control-memory-entry-card memory-card-compact">
                <div className="control-memory-entry-main memory-content">
                  <span className="control-memory-entry-title-row memory-header">
                    <strong className="memory-title">{entry.title}</strong>
                    <span className="control-memory-entry-kicker memory-chip">{entry.tag}</span>
                  </span>
                  <p className="memory-summary">{entry.detail}</p>
                </div>
                <MemoryEntryIcon tone={entry.tone} />
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function MemoryEntryIcon({ tone }: { tone: MemoryTone }) {
  const Icon = tone === "green" ? Utensils : tone === "blue" ? BookOpen : Star;
  const visualType = tone === "green" ? "life" : tone === "blue" ? "study" : "work";
  return (
    <Icon
      className="control-memory-entry-icon memory-icon"
      data-type={visualType}
      size={18}
      aria-hidden="true"
    />
  );
}

function NotebookAction({ onEdit }: { onEdit: () => void }) {
  return (
    <button type="button" className="control-mini-button" aria-label="编辑随记" onClick={onEdit}>
      <Pencil size={15} />
    </button>
  );
}
