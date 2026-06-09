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

  return (
    <section className="visible-continuity-section visible-continuity-today" aria-label="今日">
      <div className="visible-continuity-section-head">
        <CalendarCheck2 size={18} aria-hidden="true" />
        <div>
          <h3>{today.title}</h3>
          <p>{today.summary}</p>
        </div>
      </div>
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
      {hasPrompts ? (
        <div className="visible-continuity-prompt-row" aria-label="继续对话建议">
          {today.continuation_prompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              className="secondary visible-continuity-prompt-button"
              onClick={() => onContinuePrompt?.(prompt)}
              disabled={!onContinuePrompt}
              title="在聊天中继续这条线索"
            >
              <MessageSquareText size={14} aria-hidden="true" />
              <span>{prompt}</span>
            </button>
          ))}
        </div>
      ) : null}
      <footer className="visible-continuity-meta">
        <span>{today.source_count} 条本地来源</span>
        {today.updated_at ? <time dateTime={today.updated_at}>更新于 {formatDateTime(today.updated_at)}</time> : null}
      </footer>
    </section>
  );
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
