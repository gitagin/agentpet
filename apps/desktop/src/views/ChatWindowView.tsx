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
import type { AgentAction, ChatMessage, TaskItem } from "../types";
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

const chatTrialPrompts: Array<{ label: string; mode: PetInputMode; text: string }> = [
  {
    label: "创建明天的提醒",
    mode: "task",
    text: "请在明天上午 9:00 提醒我检查发布清单。",
  },
  {
    label: "保存一个偏好",
    mode: "note",
    text: "请记住我偏好简洁的发布清单。",
  },
  {
    label: "粘贴知识片段",
    mode: "wiki",
    text: "请整理成 Wiki 页面：决策记忆会把项目选择、理由和后续任务放在一起。",
  },
  {
    label: "生成今日复盘",
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
      eyebrow="对话"
      title="聊天"
      description="在这里提问、创建提醒、保存偏好，或把片段整理成 Wiki 上下文。"
      activeTab="聊天"
    >
      <Panel icon={<MessageSquareText size={18} />} title="聊天" className="feature-window-panel chat-panel">
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
        <div className="guided-trial-actions chat-guided-trials" aria-label="聊天快捷示例">
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
              {activeMode.id === "review" && !input.trim() ? "复盘" : "发送"}
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
