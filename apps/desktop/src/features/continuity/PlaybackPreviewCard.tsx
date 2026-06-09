import { FileText, History, Loader2 } from "lucide-react";
import type { RetrospectiveReportPeriod, RetrospectiveWindow } from "../../types";
import type { VisibleContinuityPlaybackPreview } from "./visibleContinuityTypes";

type PlaybackPreviewCardProps = {
  playback: VisibleContinuityPlaybackPreview;
  windows?: RetrospectiveWindow[];
  loading?: boolean;
  writingPeriod?: RetrospectiveReportPeriod | null;
  notice?: string | null;
  error?: string | null;
  onLoadPlayback?: () => void;
  onWriteReport?: (period: RetrospectiveReportPeriod) => void;
};

export function PlaybackPreviewCard({
  playback,
  windows = [],
  loading = false,
  writingPeriod = null,
  notice = null,
  error = null,
  onLoadPlayback,
  onWriteReport,
}: PlaybackPreviewCardProps) {
  const hasThemes = playback.themes.length > 0;
  const hasCompleted = playback.completed.length > 0;
  const hasStuckPoints = playback.stuck_points.length > 0;
  const hasNextFocus = playback.next_focus.length > 0;
  const weekly = windows.find((window) => window.days === 7);
  const monthly = windows.find((window) => window.days === 30);
  const canLoad = Boolean(onLoadPlayback);

  return (
    <section className="visible-continuity-section" aria-label="回放">
      <div className="visible-continuity-section-head compact">
        <History size={18} aria-hidden="true" />
        <div>
          <h3>{playback.title}</h3>
          <p>{playback.summary}</p>
        </div>
      </div>

      <div className="visible-continuity-playback-grid">
        <PlaybackColumn title="主题" items={hasThemes ? playback.themes : ["还没有足够明确的主题。"]} />
        <PlaybackColumn title="已完成" items={hasCompleted ? playback.completed : ["这个时间窗里还没有完成事项。"]} />
        <PlaybackColumn title="关注" items={hasStuckPoints ? playback.stuck_points : ["暂未发现卡点。"]} />
        <PlaybackColumn title="下一步" items={hasNextFocus ? playback.next_focus : ["先选一个线索继续。"]} />
      </div>
      <footer className="visible-continuity-meta">
        <span>{formatPlaybackPeriod(playback.period)}</span>
        <span>{playback.source_count} 条来源</span>
      </footer>
      <div className="visible-continuity-playback-actions">
        {canLoad ? (
          <button
            type="button"
            className="secondary visible-continuity-playback-button"
            onClick={onLoadPlayback}
            disabled={loading}
          >
            {loading ? <Loader2 className="spin" size={14} aria-hidden="true" /> : <History size={14} aria-hidden="true" />}
            打开回放
          </button>
        ) : null}
        {onWriteReport ? (
          <>
            <button
              type="button"
              className="secondary visible-continuity-playback-button"
              onClick={() => onWriteReport("weekly")}
              disabled={writingPeriod !== null}
            >
              {writingPeriod === "weekly" ? <Loader2 className="spin" size={14} aria-hidden="true" /> : <FileText size={14} aria-hidden="true" />}
              保存周报
            </button>
            <button
              type="button"
              className="secondary visible-continuity-playback-button"
              onClick={() => onWriteReport("monthly")}
              disabled={writingPeriod !== null}
            >
              {writingPeriod === "monthly" ? <Loader2 className="spin" size={14} aria-hidden="true" /> : <FileText size={14} aria-hidden="true" />}
              保存月报
            </button>
          </>
        ) : null}
      </div>
      {notice ? <p className="field-note">{notice}</p> : null}
      {error ? <p className="field-note error">{error}</p> : null}
      {weekly || monthly ? (
        <div className="visible-continuity-playback-detail" aria-label="回放详情">
          {weekly ? <PlaybackWindow window={weekly} period="周回放" /> : null}
          {monthly ? <PlaybackWindow window={monthly} period="月回放" /> : null}
        </div>
      ) : null}
    </section>
  );
}

function PlaybackColumn({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="visible-continuity-playback-column">
      <span className="visible-continuity-eyebrow">{title}</span>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function PlaybackWindow({ window, period }: { window: RetrospectiveWindow; period: string }) {
  const themes = window.topics.map((topic) => `${topic.name} (${topic.count})`).slice(0, 4);
  const completed = window.tasks.completed ? [`${window.tasks.completed} 个已完成任务`] : [];
  const stuck = [
    ...(window.tasks.pending ? [`${window.tasks.pending} 个待处理任务`] : []),
    ...(window.tasks.overdue ? [`${window.tasks.overdue} 个逾期任务`] : []),
  ];
  const nextFocus = themes.length > 0 ? themes.slice(0, 2) : window.repeated_preferences.map((item) => item.name).slice(0, 2);
  const sourceCount = Object.values(window.summary).reduce((total, value) => total + value, 0);

  return (
    <article className="visible-continuity-playback-window">
      <div className="visible-continuity-item-head">
        <strong>{period}</strong>
        <span>{sourceCount} 条来源</span>
      </div>
      <div className="visible-continuity-playback-grid">
        <PlaybackColumn title="主题" items={themes.length > 0 ? themes : ["信号还不够。"]} />
        <PlaybackColumn title="已完成" items={completed.length > 0 ? completed : ["这个时间窗里还没有完成事项。"]} />
        <PlaybackColumn title="卡点" items={stuck.length > 0 ? stuck : ["暂未发现卡点。"]} />
        <PlaybackColumn title="下一步" items={nextFocus.length > 0 ? nextFocus : ["再积累几条聊天、任务或笔记。"]} />
      </div>
    </article>
  );
}

function formatPlaybackPeriod(period: string): string {
  if (period === "weekly") {
    return "本周";
  }
  if (period === "monthly") {
    return "本月";
  }
  return period;
}
