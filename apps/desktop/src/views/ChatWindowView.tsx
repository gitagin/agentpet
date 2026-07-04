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
import { useEffect, useRef } from "react";
import type { FormEvent } from "react";
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

export const demoMemoryTrialPrompt = {
  label: "30 秒试走：记住演示内容",
  mode: "note" as const,
  text: "记住：这是一次演示，我正在准备 30 秒产品走查。",
};

function scheduleFrame(callback: FrameRequestCallback): number {
  if (typeof window.requestAnimationFrame === "function") {
    return window.requestAnimationFrame(callback);
  }
  return window.setTimeout(() => callback(Date.now()), 0);
}

function cancelScheduledFrame(frame: number) {
  if (typeof window.cancelAnimationFrame === "function") {
    window.cancelAnimationFrame(frame);
    return;
  }
  window.clearTimeout(frame);
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
  onOpenTask,
  onOpenMemory,
  onOpenWiki,
  onOpenReport,
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
  mode?: PetInputMode;
  modes?: PetInputModeOption[];
  onModeChange?: (mode: PetInputMode) => void;
}) {
  const visibleMessages = messages.filter((message) => message.role !== "system");
  const activeMode = modes.find((option) => option.id === mode) ?? defaultPetInputModes[0];
  const primaryModes = modes.filter((option) => primaryModeIds.has(option.id));
  const secondaryModes = modes.filter((option) => !primaryModeIds.has(option.id));
  const messageListRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const latestMessage = visibleMessages[visibleMessages.length - 1];
  const canSend = connected && !streaming && (input.trim().length > 0 || activeMode.id === "review");

  useEffect(() => {
    const messageList = messageListRef.current;
    if (!messageList) {
      return undefined;
    }

    const scrollToLatest = () => {
      messageList.scrollTop = messageList.scrollHeight;
    };

    scrollToLatest();
    const frame = scheduleFrame(scrollToLatest);
    return () => cancelScheduledFrame(frame);
  }, [latestMessage?.content, latestMessage?.id, latestMessage?.status, streaming, visibleMessages.length]);

  useEffect(() => {
    if (!streaming) {
      inputRef.current?.focus({ preventScroll: true });
    }
  }, [streaming]);

  function fillTrialPrompt(mode: PetInputMode, text: string) {
    onModeChange(mode);
    onInputChange(text);
    scheduleFrame(() => inputRef.current?.focus({ preventScroll: true }));
  }

  return (
    <FeatureWindowShell
      eyebrow="和我说话"
      title={productCopy.chatPage.title}
      description={productCopy.chatPage.description}
      activeTab="对话"
    >
      <Panel icon={<MessageSquareText size={18} />} title="和我说说" className="feature-window-panel chat-panel">
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
          <button
            type="button"
            className="secondary chat-demo-trial"
            onClick={() => fillTrialPrompt(demoMemoryTrialPrompt.mode, demoMemoryTrialPrompt.text)}
            disabled={streaming}
          >
            <Sparkles size={16} />
            {demoMemoryTrialPrompt.label}
          </button>
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
        <ChatMessageList
          messages={visibleMessages}
          revertingActionIds={revertingActionIds}
          onRevertAgentAction={onRevertAgentAction}
          onOpenTask={onOpenTask}
          onOpenMemory={onOpenMemory}
          onOpenWiki={onOpenWiki}
          onOpenReport={onOpenReport}
          listRef={messageListRef}
        />
        <form className="chat-form" onSubmit={onSend}>
          <input
            ref={inputRef}
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            placeholder={connected ? activeMode.placeholder : "正在等待本地助手连接..."}
            disabled={streaming}
            autoFocus
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
      </Panel>
    </FeatureWindowShell>
  );
}
