import { Loader2, RefreshCw, Search } from "lucide-react";
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { EmptyState } from "../components/layout";
import {
  getAgentActionSearchText,
  type AgentActivityLogEntry,
} from "../services/agentActivity";
import { FeatureWindowShell } from "./FeatureWindowShell";

type MemoryActivityFilter = "all" | "auto" | "pending" | "reverted" | "failed";

type MemoryWindowViewProps = {
  loading: boolean;
  error: string;
  entries: AgentActivityLogEntry[];
  onRefresh: () => void;
  renderEntry: (entry: AgentActivityLogEntry) => ReactNode;
};

const activityFilters: Array<{ key: MemoryActivityFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "auto", label: "自动写入" },
  { key: "pending", label: "待确认" },
  { key: "reverted", label: "已撤销" },
  { key: "failed", label: "失败" },
];

function isPendingStatus(status: string): boolean {
  return status === "pending" || status === "applying" || status === "running";
}

function entryMatchesFilter(entry: AgentActivityLogEntry, filter: MemoryActivityFilter): boolean {
  if (filter === "all") {
    return true;
  }

  if (entry.kind === "agent_action") {
    const action = entry.action;
    if (filter === "auto") {
      return (
        action.decision === "auto" &&
        action.status === "completed" &&
        action.target_paths.length > 0 &&
        !action.reverts_action_id &&
        !action.error
      );
    }
    if (filter === "pending") {
      return isPendingStatus(action.status) || (action.decision === "ask" && action.status !== "completed");
    }
    if (filter === "reverted") {
      return action.status === "reverted" || Boolean(action.reverts_action_id);
    }
    return action.status === "failed" || Boolean(action.error);
  }

  if (entry.kind === "memory_proposal") {
    return filter === "pending" ? entry.proposal.status === "pending" : filter === "failed" && entry.proposal.status === "failed";
  }

  if (entry.kind === "continuity_proposal") {
    return filter === "pending" ? entry.proposal.status === "pending" : false;
  }

  return filter === "pending"
    ? entry.proposal.state === "pending"
    : filter === "failed" && entry.proposal.state === "failed";
}

function entrySearchText(entry: AgentActivityLogEntry): string {
  if (entry.kind === "agent_action") {
    return getAgentActionSearchText(entry.action);
  }
  if (entry.kind === "memory_proposal") {
    const proposal = entry.proposal;
    return [proposal.target_path, proposal.written_path || "", proposal.content, proposal.preview_markdown || "", proposal.type]
      .join(" ")
      .toLocaleLowerCase();
  }
  if (entry.kind === "continuity_proposal") {
    const proposal = entry.proposal;
    return [proposal.kind, proposal.summary, proposal.evidence].join(" ").toLocaleLowerCase();
  }
  const proposal = entry.proposal;
  return [
    proposal.proposal_type,
    proposal.title,
    proposal.summary || "",
    proposal.review_summary || "",
    ...proposal.target_paths,
    ...proposal.recommended_targets,
    ...proposal.selected_targets,
  ]
    .join(" ")
    .toLocaleLowerCase();
}

export default function MemoryWindowView({
  loading,
  error,
  entries,
  onRefresh,
  renderEntry,
}: MemoryWindowViewProps) {
  const [activeFilter, setActiveFilter] = useState<MemoryActivityFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
  const filteredEntries = useMemo(
    () =>
      entries.filter(
        (entry) =>
          entryMatchesFilter(entry, activeFilter) &&
          (!normalizedQuery || entrySearchText(entry).includes(normalizedQuery)),
      ),
    [activeFilter, entries, normalizedQuery],
  );

  return (
    <FeatureWindowShell
      eyebrow="自动整理"
      title="整理"
      description="查看自动写入、撤销记录，以及需要你确认的长期记忆和状态更新。"
      activeTab="整理"
    >
      <section className="panel feature-window-panel" aria-label="最近整理活动">
        <div className="section-heading">
          <strong>最近整理活动</strong>
          <span>
            {entries.length > 0
              ? `显示 ${filteredEntries.length} / ${entries.length} 条活动。`
              : "还没有整理活动。"}
          </span>
        </div>

        <div className="memory-activity-toolbar">
          <div className="memory-activity-filters" aria-label="整理活动筛选">
            {activityFilters.map((option) => {
              const count = entries.filter((entry) => entryMatchesFilter(entry, option.key)).length;
              const active = activeFilter === option.key;
              return (
                <button
                  key={option.key}
                  type="button"
                  className={`secondary memory-activity-filter ${active ? "active" : ""}`}
                  onClick={() => setActiveFilter(option.key)}
                  aria-pressed={active}
                >
                  {option.label}
                  <span>{count}</span>
                </button>
              );
            })}
          </div>
          <label className="memory-activity-search">
            <Search size={16} />
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="搜索目标文件、摘要或动作"
            />
          </label>
        </div>

        <div className="button-row">
          <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
            {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            刷新整理
          </button>
        </div>
        {error ? <p className="field-note error">{error}</p> : null}
        <div className="proposal-list agent-activity-log-list feature-activity-list">
          {filteredEntries.length > 0 ? (
            filteredEntries.map((entry) => renderEntry(entry))
          ) : loading ? (
            <EmptyState text="正在加载最近整理活动。" />
          ) : entries.length > 0 ? (
            <EmptyState text="没有匹配的整理活动。" />
          ) : (
            <EmptyState text="普通自动整理完成后会出现在这里；高风险写入会在这里显示确认入口。" />
          )}
        </div>
      </section>
    </FeatureWindowShell>
  );
}
