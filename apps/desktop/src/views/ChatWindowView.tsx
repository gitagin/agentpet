import {
  CheckCircle2,
  Loader2,
  MessageSquareText,
  Send,
  ShieldAlert,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";
import { useEffect, useRef } from "react";
import type { FormEvent } from "react";
import { Panel } from "../components/layout";
import { ChatMessageList } from "../features/chat/ChatMessageList";
import { productCopy } from "../productCopy";
import type { AgentAction, AgentCheckpointSummary, ChatMessage, TaskItem } from "../types";
import { FeatureWindowShell } from "./FeatureWindowShell";

export const chatTrialPrompts = [
  {
    label: "查找带来源的记忆",
    text: "我之前提过更喜欢上午还是下午开会？顺便告诉我这个结论来自哪条记录。",
  },
  {
    label: "创建提醒并记住偏好",
    text: "明天下午三点提醒我给张老师回邮件，并记住我更喜欢下午开会。",
  },
] as const;

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
  pendingCheckpoints,
  decidingCheckpointIds,
  onDecideCheckpoint,
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
  pendingCheckpoints?: AgentCheckpointSummary[];
  decidingCheckpointIds?: Set<string>;
  onDecideCheckpoint?: (checkpoint: AgentCheckpointSummary, decision: "approved" | "rejected") => void;
}) {
  const visibleMessages = messages.filter((message) => message.role !== "system");
  const messageListRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const latestMessage = visibleMessages[visibleMessages.length - 1];
  const canSend = connected && !streaming && input.trim().length > 0;

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

  function fillTrialPrompt(text: string) {
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
        <div className="guided-trial-actions chat-guided-trials" aria-label="可以这样说">
          {chatTrialPrompts.map((trial) => (
            <button
              key={trial.label}
              type="button"
              className="secondary"
              onClick={() => fillTrialPrompt(trial.text)}
              disabled={streaming}
            >
              <Sparkles size={16} />
              {trial.label}
            </button>
          ))}
        </div>
        {pendingCheckpoints && pendingCheckpoints.length > 0 ? (
          <section className="checkpoint-confirmation-list" aria-label="待确认的高风险操作">
            {pendingCheckpoints.map((checkpoint) => {
              const deciding = decidingCheckpointIds?.has(checkpoint.checkpoint_id) ?? false;
              return (
                <article key={checkpoint.checkpoint_id} className="checkpoint-confirmation-item">
                  <div className="checkpoint-confirmation-heading">
                    <ShieldAlert size={17} />
                    <strong>高风险操作等待确认</strong>
                  </div>
                  <p>{checkpoint.action_label}</p>
                  <dl>
                    <div><dt>目标</dt><dd>{checkpoint.safe_target_summary || "本地内容"}</dd></div>
                    <div><dt>风险</dt><dd>{checkpoint.risk_tier === "high" ? "高" : "中"}</dd></div>
                    <div><dt>可逆</dt><dd>{checkpoint.reversible ? "是" : "否"}</dd></div>
                  </dl>
                  <div className="checkpoint-confirmation-actions">
                    <button
                      type="button"
                      onClick={() => onDecideCheckpoint?.(checkpoint, "approved")}
                      disabled={deciding || !onDecideCheckpoint}
                    >
                      <CheckCircle2 size={16} />
                      批准
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => onDecideCheckpoint?.(checkpoint, "rejected")}
                      disabled={deciding || !onDecideCheckpoint}
                    >
                      <XCircle size={16} />
                      拒绝
                    </button>
                  </div>
                </article>
              );
            })}
          </section>
        ) : null}
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
            placeholder={connected ? productCopy.chatPage.inputPlaceholder : "正在等待本地助手连接..."}
            disabled={streaming}
            autoFocus
            aria-label="聊天输入"
          />
          {streaming ? (
            <button type="button" className="danger" onClick={onStopStreaming}>
              <X size={16} />
              停止
            </button>
          ) : (
            <button type="submit" disabled={!canSend}>
              <Send size={16} />
              发送
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
