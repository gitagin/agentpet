import {
  BookOpenCheck,
  ClipboardList,
  Loader2,
  MessageCircle,
  MessageSquareText,
  NotebookPen,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import type { FormEvent, ReactNode } from "react";
import { Panel } from "../components/layout";
import { ChatMessageList } from "../features/chat/ChatMessageList";
import {
  petInputModes as defaultPetInputModes,
  type PetInputMode,
  type PetInputModeOption,
} from "../features/chat/petInputModes";
import { productCopy } from "../productCopy";
import type { AgentAction, ChatMessage, TaskItem } from "../types";
import { FeatureWindowShell } from "./FeatureWindowShell";

const modeDescriptions: Record<PetInputMode, string> = {
  chat: "直接说说",
  note: "帮你记住",
  task: "到时提醒",
  wiki: "归好资料",
  review: "回顾今天",
};

const primaryModeIds = new Set<PetInputMode>(["chat", "note"]);

function renderModeIcon(mode: PetInputMode) {
  switch (mode) {
    case "note":
      return <NotebookPen size={17} />;
    case "task":
      return <ClipboardList size={17} />;
    case "wiki":
      return <BookOpenCheck size={17} />;
    case "review":
      return <Sparkles size={17} />;
    case "chat":
    default:
      return <MessageCircle size={17} />;
  }
}

const chatTrialPrompts: Array<{ label: string; mode: PetInputMode; text: string }> = [
  {
    label: "我今天有点累",
    mode: "chat",
    text: "我今天有点累",
  },
  {
    label: "记住我最近在准备一件重要的事",
    mode: "note",
    text: "记住我最近在准备一件重要的事",
  },
  {
    label: "明天提醒我继续这件事",
    mode: "task",
    text: "明天提醒我继续这件事",
  },
  {
    label: "帮我回顾今天",
    mode: "review",
    text: "",
  },
];

export default function ChatWindowView({
  input,
  messages,
  connected,
  streaming,
  onInputChange,
  onSend,
  onStopStreaming,
  revertingActionIds,
  onRevertAgentAction,
  onOpenTask,
  onOpenMemory,
  onOpenWiki,
  onOpenReport,
  onboardingPanel,
  hasVaultInitialized = false,
  mode = "chat",
  modes = defaultPetInputModes,
  onModeChange = () => undefined,
}: {
  input: string;
  messages: ChatMessage[];
  connected: boolean;
  streaming: boolean;
  onInputChange: (value: string) => void;
  onSend: (event: FormEvent) => void;
  onStopStreaming: () => void;
  revertingActionIds?: Set<string>;
  onRevertAgentAction?: (action: AgentAction) => void;
  onOpenTask?: (task?: TaskItem) => void;
  onOpenMemory?: () => void;
  onOpenWiki?: (path?: string) => void;
  onOpenReport?: (path?: string) => void;
  onboardingPanel?: ReactNode;
  hasVaultInitialized?: boolean;
  mode?: PetInputMode;
  modes?: PetInputModeOption[];
  onModeChange?: (mode: PetInputMode) => void;
}) {
  const visibleMessages = messages.filter((message) => message.role !== "system");
  const activeMode = modes.find((option) => option.id === mode) ?? defaultPetInputModes[0];
  const primaryModes = modes.filter((option) => primaryModeIds.has(option.id));
  const secondaryModes = modes.filter((option) => !primaryModeIds.has(option.id));
  const canSend = connected && !streaming && (input.trim().length > 0 || activeMode.id === "review");
  const shouldDeferOnboarding = Boolean(onboardingPanel) && (hasVaultInitialized || visibleMessages.length > 0);
  const deferredOnboarding = shouldDeferOnboarding ? (
    <details className="chat-onboarding-drawer">
      <summary>补充首次偏好</summary>
      {onboardingPanel}
    </details>
  ) : null;
  function fillTrialPrompt(mode: PetInputMode, text: string) {
    onModeChange(mode);
    onInputChange(text);
  }

  return (
    <FeatureWindowShell
      eyebrow="和我说话"
      title={productCopy.chatPage.title}
      description={productCopy.chatPage.description}
      activeTab="陪伴"
    >
      <Panel icon={<MessageSquareText size={18} />} title="和我说说" className="feature-window-panel chat-panel">
        {shouldDeferOnboarding ? null : onboardingPanel}
        <div className="chat-action-board" role="tablist" aria-label="主要陪伴方式">
          {primaryModes.map((option) => (
            <button
              key={option.id}
              type="button"
              className={`chat-action-button ${option.id === activeMode.id ? "active" : ""}`}
              role="tab"
              aria-selected={option.id === activeMode.id}
              aria-label={option.ariaLabel}
              disabled={streaming}
              onClick={() => onModeChange(option.id)}
            >
              {renderModeIcon(option.id)}
              <span>
                <strong>{option.label}</strong>
                <small>{modeDescriptions[option.id]}</small>
              </span>
            </button>
          ))}
        </div>
        <div className="guided-trial-actions chat-secondary-modes" role="tablist" aria-label="更多陪伴方式">
          {secondaryModes.map((option) => (
            <button
              key={option.id}
              type="button"
              className={`secondary ${option.id === activeMode.id ? "active" : ""}`}
              role="tab"
              aria-selected={option.id === activeMode.id}
              aria-label={option.ariaLabel}
              disabled={streaming}
              onClick={() => onModeChange(option.id)}
            >
              {renderModeIcon(option.id)}
              {option.label}
            </button>
          ))}
        </div>
        <div className="guided-trial-actions chat-guided-trials" aria-label="可以这样说">
          {chatTrialPrompts.map((trial) => (
            <button
              key={trial.label}
              type="button"
              className="secondary"
              onClick={() => fillTrialPrompt(trial.mode, trial.text)}
              disabled={streaming}
            >
              {renderModeIcon(trial.mode)}
              {trial.label}
            </button>
          ))}
        </div>
        <form className="chat-form" onSubmit={onSend}>
          <input
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            placeholder={connected ? activeMode.placeholder : "正在等待本地助手连接..."}
            disabled={streaming}
            aria-label={`${activeMode.label}输入`}
          />
          {streaming ? (
            <button type="button" className="danger" onClick={onStopStreaming}>
              <X size={16} />
              停止
            </button>
          ) : (
            <button type="submit" disabled={!canSend}>
              <Send size={16} />
              {activeMode.id === "review" && !input.trim() ? "回顾" : "发送"}
            </button>
          )}
        </form>
        {streaming ? (
          <p className="field-note">
            <Loader2 className="spin" size={14} /> 正在整理回答...
          </p>
        ) : null}
        <ChatMessageList
          messages={visibleMessages}
          revertingActionIds={revertingActionIds}
          onRevertAgentAction={onRevertAgentAction}
          onOpenTask={onOpenTask}
          onOpenMemory={onOpenMemory}
          onOpenWiki={onOpenWiki}
          onOpenReport={onOpenReport}
        />
        {deferredOnboarding}
      </Panel>
    </FeatureWindowShell>
  );
}
