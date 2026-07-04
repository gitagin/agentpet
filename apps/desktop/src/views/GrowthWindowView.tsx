import { BookOpenCheck, Brain, HeartPulse, RefreshCw, ShieldCheck, Sprout } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { EmptyState, Panel } from "../components/layout";
import type { DesktopApi } from "../services/desktopApi";
import { describeError } from "../services/apiErrorMessages";
import type { GrowthDimension, GrowthEvent, GrowthSnapshotResponse } from "../types";
import { FeatureWindowShell } from "./FeatureWindowShell";

type GrowthWindowViewProps = {
  api: DesktopApi;
};

const dimensionIcons: Record<string, typeof Brain> = {
  memory_depth: Brain,
  response_affinity: HeartPulse,
  trust_boundary: ShieldCheck,
  knowledge_links: BookOpenCheck,
};

function formatDate(value?: string | null): string {
  if (!value) {
    return "暂无记录";
  }
  const time = Date.parse(value);
  if (Number.isNaN(time)) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(time));
}

function dimensionSourceText(dimension: GrowthDimension): string {
  return dimension.data_sources.join(" / ");
}

function eventTargetText(event: GrowthEvent): string {
  if (event.target_paths.length === 0) {
    return event.source_action_type;
  }
  return event.target_paths.slice(0, 2).join(" / ");
}

function statsLine(snapshot: GrowthSnapshotResponse): string {
  const stats = snapshot.stats;
  return [
    `聊天日记 ${stats.chat_diary_entries}`,
    `长期记忆 ${stats.long_term_memory_count}`,
    `资料页 ${stats.wiki_page_count}`,
    `可撤回 ${stats.reversible_operation_count}`,
  ].join(" · ");
}

export default function GrowthWindowView({ api }: GrowthWindowViewProps) {
  const [snapshot, setSnapshot] = useState<GrowthSnapshotResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadSnapshot = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const response = await api.getGrowthSnapshot(signal);
      if (signal?.aborted) {
        return;
      }
      setSnapshot(response);
    } catch (loadError) {
      if (signal?.aborted || (loadError instanceof DOMException && loadError.name === "AbortError")) {
        return;
      }
      setError(describeError(loadError, "成长记录加载失败"));
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [api]);

  useEffect(() => {
    const controller = new AbortController();
    void loadSnapshot(controller.signal);
    return () => controller.abort();
  }, [loadSnapshot]);

  const leadingDimension = useMemo(() => {
    if (!snapshot?.dimensions.length) {
      return null;
    }
    return [...snapshot.dimensions].sort((left, right) => right.level - left.level || right.current_value - left.current_value)[0];
  }, [snapshot]);

  return (
    <FeatureWindowShell
      eyebrow="成长"
      title="成长记录"
      description="你留下的日记、记忆、边界操作和资料整理，会变成桌宠可见的成长轨迹。"
      activeTab="记忆"
    >
      <div className="feature-page-stack growth-page-stack">
        <Panel title="当前变化" icon={<Sprout size={18} />} className="feature-window-panel growth-summary-panel">
          <div className="growth-summary-row">
            <div>
              <strong>{leadingDimension ? leadingDimension.level_label : "等待第一次记录"}</strong>
              <span>{snapshot ? statsLine(snapshot) : "正在读取本机成长数据"}</span>
            </div>
            <button type="button" className="ghost-button growth-refresh-button" onClick={() => void loadSnapshot()} disabled={loading}>
              <RefreshCw size={16} className={loading ? "spin" : ""} aria-hidden="true" />
              <span>{loading ? "刷新中" : "刷新"}</span>
            </button>
          </div>
          {error ? <p className="notice error">{error}</p> : null}
          {!loading && !snapshot ? <EmptyState text="暂时没有可显示的成长记录。" /> : null}
        </Panel>

        {snapshot ? (
          <Panel title="成长维度" icon={<HeartPulse size={18} />} className="feature-window-panel growth-dimensions-panel">
            <div className="growth-dimension-grid">
              {snapshot.dimensions.map((dimension) => {
                const Icon = dimensionIcons[dimension.key] || Sprout;
                return (
                  <article key={dimension.key} className="growth-dimension-card">
                    <div className="growth-dimension-head">
                      <Icon size={18} aria-hidden="true" />
                      <div>
                        <strong>{dimension.label}</strong>
                        <span>{dimension.level_label}</span>
                      </div>
                    </div>
                    <p>{dimension.description}</p>
                    <div className="growth-progress" aria-label={`${dimension.label} 进度 ${dimension.progress}%`}>
                      <span style={{ width: `${dimension.progress}%` }} />
                    </div>
                    <dl className="growth-metrics">
                      <div>
                        <dt>当前</dt>
                        <dd>{dimension.current_value}</dd>
                      </div>
                      <div>
                        <dt>下一级</dt>
                        <dd>{dimension.next_threshold ?? "已满"}</dd>
                      </div>
                      <div>
                        <dt>来源</dt>
                        <dd>{dimensionSourceText(dimension)}</dd>
                      </div>
                    </dl>
                    <small>最近变化：{formatDate(dimension.last_changed_at)}</small>
                  </article>
                );
              })}
            </div>
          </Panel>
        ) : null}

        {snapshot ? (
          <Panel title="成长历史" icon={<BookOpenCheck size={18} />} className="feature-window-panel growth-history-panel">
            {snapshot.events.length ? (
              <ol className="growth-history-list">
                {snapshot.events.map((event) => (
                  <li key={event.event_id} className="growth-history-item">
                    <time>{formatDate(event.occurred_at)}</time>
                    <div>
                      <strong>{event.title}</strong>
                      <span>{event.summary || event.source_action_type}</span>
                      <small>{eventTargetText(event)}</small>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState text="还没有成长历史；开始聊天、整理记忆或撤回一次记录后，这里会出现变化。" />
            )}
          </Panel>
        ) : null}
      </div>
    </FeatureWindowShell>
  );
}
