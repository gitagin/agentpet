import { CalendarCheck2, CheckCircle2, MessageSquareText } from "lucide-react";
import type { VisibleContinuityTodayCard } from "./visibleContinuityTypes";

type TodayCardProps = {
  today: VisibleContinuityTodayCard;
  onContinuePrompt?: (prompt: string) => void;
};

export function TodayCard({ today, onContinuePrompt }: TodayCardProps) {
  const hasCarryOver = today.carry_over_items.length > 0;
  const hasNextSteps = today.suggested_next_steps.length > 0;
  const hasPrompts = today.continuation_prompts.length > 0;
  const primaryPrompt = today.continuation_prompts[0];
  const secondaryPrompts = today.continuation_prompts.slice(1, 3);
  const primaryCarryOver = today.carry_over_items[0];
  const primaryNextStep = today.source_count > 0 ? today.suggested_next_steps[0] : undefined;
  const primaryPromptLabel = primaryPrompt ? formatContinuationPrompt(primaryPrompt) : "";

  return (
    <section className="visible-continuity-section visible-continuity-today" aria-label="今日">
      <div className="visible-continuity-section-head">
        <CalendarCheck2 size={18} aria-hidden="true" />
        <div>
          <h3>{today.title}</h3>
          <p>{formatTodaySummary(today.summary)}</p>
        </div>
      </div>
      {hasPrompts ? (
        <div className="visible-continuity-resume" aria-label="继续最近的对话">
          <button
            type="button"
            className="visible-continuity-resume-button"
            onClick={() => onContinuePrompt?.(primaryPrompt)}
            disabled={!onContinuePrompt}
            title="在聊天中继续这条线索"
          >
            <MessageSquareText size={16} aria-hidden="true" />
            <span>{primaryPromptLabel}</span>
          </button>
          {secondaryPrompts.length > 0 ? (
            <div className="visible-continuity-prompt-row" aria-label="其他继续建议">
              {secondaryPrompts.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="secondary visible-continuity-prompt-button"
                  onClick={() => onContinuePrompt?.(prompt)}
                  disabled={!onContinuePrompt}
                  title="在聊天中继续这条线索"
                >
                  <MessageSquareText size={14} aria-hidden="true" />
                  <span>{formatContinuationPrompt(prompt)}</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="visible-continuity-muted visible-continuity-empty-resume">
          暂时没有需要续上的话题，直接开聊就好。
        </p>
      )}
      <details className="visible-continuity-source-details">
        <summary>查看依据</summary>
        <div className="visible-continuity-today-grid">
          <div>
            <span className="visible-continuity-eyebrow">延续事项</span>
            {hasCarryOver ? (
              <ul className="visible-continuity-list">
                {today.carry_over_items.map((item) => (
                  <li key={item}>
                    <CheckCircle2 size={14} aria-hidden="true" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="visible-continuity-muted">暂时没有未收尾的延续事项。</p>
            )}
          </div>
          <div>
            <span className="visible-continuity-eyebrow">下一步</span>
            {hasNextSteps ? (
              <ul className="visible-continuity-list">
                {today.suggested_next_steps.map((item) => (
                  <li key={item}>
                    <CheckCircle2 size={14} aria-hidden="true" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="visible-continuity-muted">可以先从一条笔记、任务或聊天开始。</p>
            )}
          </div>
        </div>
      </details>
      {primaryCarryOver || primaryNextStep ? (
        <div className="visible-continuity-quick-facts" aria-label="上下文摘要">
          {primaryCarryOver ? (
            <span>
              <CheckCircle2 size={13} aria-hidden="true" />
              {primaryCarryOver}
            </span>
          ) : null}
          {primaryNextStep ? (
            <span>
              <CheckCircle2 size={13} aria-hidden="true" />
              {primaryNextStep}
            </span>
          ) : null}
        </div>
      ) : null}
      <footer className="visible-continuity-meta">
        <span>{today.source_count} 条本地来源</span>
        {today.updated_at ? <time dateTime={today.updated_at}>更新于 {formatDateTime(today.updated_at)}</time> : null}
      </footer>
    </section>
  );
}

function formatTodaySummary(summary: string): string {
  const normalized = summary.trim();
  if (!normalized) {
    return "我会把值得接上的内容放在这里。";
  }
  if (normalized.length > 72) {
    return "找到一条可以接上的线索，先从最近的话题继续。";
  }
  return normalized
    .replace(/^Pulled together\s+/i, "已参考 ")
    .replace(/\s+recent messages?/i, " 条最近聊天")
    .replace(/\s+open tasks?/i, " 个待办")
    .replace(/\s+organization receipts?/i, " 条整理记录");
}

function formatContinuationPrompt(prompt: string): string {
  const normalized = prompt.trim();
  if (/^Help me decide what is worth continuing today\.?$/i.test(normalized)) {
    return "帮我看看今天该接着做什么";
  }
  const topicMatch = normalized.match(/关于[“"]([^”"]+)[”"]/);
  if (topicMatch?.[1]) {
    return `继续：${topicMatch[1]}`;
  }
  const cleaned = normalized
    .replace(/^Help me continue this task:\s*/i, "继续：")
    .replace(/^继续这条线索[:：]\s*/i, "继续：")
    .replace(/^这条最近笔记里有什么值得记住[:：]\s*/i, "")
    .trim();
  if (!cleaned) {
    return "继续最近的话题";
  }
  if (cleaned.length > 36) {
    return "继续最近的话题";
  }
  return cleaned.startsWith("继续") ? cleaned : `继续：${cleaned}`;
}

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
