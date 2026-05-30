import { Loader2, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { EmptyState } from "../components/layout";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function MemoryWindowView({
  loading,
  error,
  entries,
  onRefresh,
}: {
  loading: boolean;
  error: string;
  entries: ReactNode[];
  onRefresh: () => void;
}) {
  return (
    <FeatureWindowShell eyebrow="自动整理" title="整理" description="查看自动写入、撤销记录，以及需要你确认的长期记忆和状态更新。">
      <section className="panel feature-window-panel" aria-label="最近整理活动">
        <div className="section-heading">
          <strong>最近整理活动</strong>
          <span>{entries.length > 0 ? `最近 ${entries.length} 条活动。` : "还没有整理活动。"}</span>
        </div>
        <div className="button-row">
          <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
            {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            刷新整理
          </button>
        </div>
        {error ? <p className="field-note error">{error}</p> : null}
        <div className="proposal-list agent-activity-log-list feature-activity-list">
          {entries.length > 0 ? entries : loading ? <EmptyState text="正在加载最近整理活动。" /> : <EmptyState text="普通自动整理完成后会出现在这里；高风险写入会在这里显示确认入口。" />}
        </div>
      </section>
    </FeatureWindowShell>
  );
}
