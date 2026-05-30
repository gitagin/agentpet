import { Loader2, MessageSquareText, Send, X } from "lucide-react";
import type { FormEvent } from "react";
import { Panel } from "../components/layout";
import { ChatMessageList } from "../features/chat/ChatMessageList";
import type { ChatMessage } from "../types";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function ChatWindowView({
  input,
  messages,
  connected,
  streaming,
  onInputChange,
  onSend,
  onStopStreaming,
}: {
  input: string;
  messages: ChatMessage[];
  connected: boolean;
  streaming: boolean;
  onInputChange: (value: string) => void;
  onSend: (event: FormEvent) => void;
  onStopStreaming: () => void;
}) {
  return (
    <FeatureWindowShell eyebrow="本地助手" title="聊天" description="和桌宠聊天、检索记忆库和知识库，并把高价值内容交给自动整理。">
      <Panel icon={<MessageSquareText size={18} />} title="聊天与检索" className="feature-window-panel chat-panel">
        <form className="chat-form" onSubmit={onSend}>
          <input
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            placeholder={connected ? "和桌宠说点什么..." : "正在等待本地助手连接..."}
            disabled={streaming}
          />
          {streaming ? (
            <button type="button" className="danger" onClick={onStopStreaming}>
              <X size={16} />
              停止
            </button>
          ) : (
            <button type="submit" disabled={!input.trim() || !connected}>
              <Send size={16} />
              发送
            </button>
          )}
        </form>
        {streaming ? <p className="field-note"><Loader2 className="spin" size={14} /> 正在回复...</p> : null}
        <ChatMessageList messages={messages} />
      </Panel>
    </FeatureWindowShell>
  );
}
