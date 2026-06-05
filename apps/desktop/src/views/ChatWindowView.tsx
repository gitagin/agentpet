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
import type { AgentAction, ChatMessage } from "../types";
import { FeatureWindowShell } from "./FeatureWindowShell";

const modeDescriptions: Record<PetInputMode, string> = {
  chat: "直接问答",
  note: "沉淀片段",
  task: "设定提醒",
  wiki: "整理知识",
  review: "复盘今天",
};

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
  onOpenMemory,
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
  onOpenMemory?: () => void;
  onboardingPanel?: ReactNode;
  hasVaultInitialized?: boolean;
  mode?: PetInputMode;
  modes?: PetInputModeOption[];
  onModeChange?: (mode: PetInputMode) => void;
}) {
  const visibleMessages = messages.filter((message) => message.role !== "system");
  const activeMode = modes.find((option) => option.id === mode) ?? defaultPetInputModes[0];
  const canSend = connected && !streaming && (input.trim().length > 0 || activeMode.id === "review");
  const shouldDeferOnboarding = Boolean(onboardingPanel) && (hasVaultInitialized || visibleMessages.length > 0);
  const deferredOnboarding = shouldDeferOnboarding ? (
    <details className="chat-onboarding-drawer">
      <summary>补充首次偏好</summary>
      {onboardingPanel}
    </details>
  ) : null;

  return (
    <FeatureWindowShell
      eyebrow="本地助手"
      title="聊天"
      description="和桌宠聊天、检索记忆库和知识库，并把高价值内容交给自动整理。"
      activeTab="聊天"
    >
      <Panel icon={<MessageSquareText size={18} />} title="聊天与检索" className="feature-window-panel chat-panel">
        {shouldDeferOnboarding ? null : onboardingPanel}
        <div className="chat-action-board" role="tablist" aria-label="聊天能力">
          {modes.map((option) => (
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
              {activeMode.id === "review" && !input.trim() ? "复盘" : "发送"}
            </button>
          )}
        </form>
        {streaming ? (
          <p className="field-note">
            <Loader2 className="spin" size={14} /> 正在想...
          </p>
        ) : null}
        <ChatMessageList
          messages={visibleMessages}
          revertingActionIds={revertingActionIds}
          onRevertAgentAction={onRevertAgentAction}
          onOpenMemory={onOpenMemory}
        />
        {deferredOnboarding}
      </Panel>
    </FeatureWindowShell>
  );
}
