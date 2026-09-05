import { Check, Clock3, ExternalLink, History, RefreshCw, ShieldAlert, X } from "lucide-react";
import { useMemo } from "react";
import type { ReactNode } from "react";
import type { AgentActivityLogEntry } from "../../services/agentActivity";
import { formatDate } from "../../services/dateFormatting";
import type { MemoryProposal, MemoryGraphResponse } from "../../types";
import { relationLabelOf } from "./relationTypeLabels";
import type { MemoryGraphEdgeItem, MemoryGraphNodeItem } from "./useMemoryGraphWorkspace";

type MemoryTimelineWorkspaceProps = {
  graph: MemoryGraphResponse | null;
  entries: AgentActivityLogEntry[];
  proposals: MemoryProposal[];
  loading: boolean;
  error: string;
  loadingProposals: boolean;
  query: string;
  proposalActionIds: Set<string>;
  onSelectNode: (nodeId: string) => void;
  onSelectEdge: (edgeId: string) => void;
  onRefresh: () => void;
  onLoadProposals: () => void;
  onProposalAction: (proposalId: string, action: "confirm" | "reject") => void;
  onOpenChat: () => void;
  onOpenSources: () => void;
  renderEntry: (entry: AgentActivityLogEntry) => ReactNode;
};

type TimelineItem = {
  id: string;
  at: string;
  title: string;
  detail: string;
  status: string;
  tone: "active" | "pending" | "conflict" | "archived";
  node?: MemoryGraphNodeItem;
  edge?: MemoryGraphEdgeItem;
};

const statusLabels: Record<string, string> = {
  active: "使用中",
  pending: "待确认",
  candidate: "待确认",
  archived: "已归档",
  hidden: "已隐藏",
  wrong: "已纠正",
  rejected: "已拒绝",
  sensitive_blocked: "已隔离",
};

const unsafeText = /candidate|fact|evidence|source_text|source_excerpt|agent_run_id|token|authorization|fts|vector|[A-Za-z]:[\\/]|\\\\/i;

function safe(value: string | null | undefined, fallback: string): string {
  const text = value?.trim();
  return text && !unsafeText.test(text) ? text : fallback;
}

function proposalTitle(proposal: MemoryProposal): string {
  return proposal.type === "preference" ? "一条偏好等待确认" : proposal.type === "goal" ? "一个目标等待确认" : "一条记忆等待确认";
}

export function MemoryTimelineWorkspace({
  graph,
  entries,
  proposals,
  loading,
  error,
  loadingProposals,
  query,
  proposalActionIds,
  onSelectNode,
  onSelectEdge,
  onRefresh,
  onLoadProposals,
  onProposalAction,
  onOpenChat,
  onOpenSources,
  renderEntry,
}: MemoryTimelineWorkspaceProps) {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const nodes = useMemo(() => graph?.nodes || [], [graph?.nodes]);
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.node_id, node])), [nodes]);
  const timeline = useMemo<TimelineItem[]>(() => {
    const nodeItems: TimelineItem[] = nodes.map((node) => ({
      id: `node:${node.node_id}`,
      at: node.updated_at,
      title: safe(node.label, "一条记忆"),
      detail: `${safe(node.subtitle, "记忆")} · ${node.evidence_count ?? 0} 个来源`,
      status: statusLabels[node.status] || "状态未返回",
      tone: node.status === "pending" ? "pending" : node.status === "hidden" || node.status === "archived" ? "archived" : "active",
      node,
    }));
    const edgeItems: TimelineItem[] = (graph?.edges || []).map((edge) => ({
      id: `edge:${edge.edge_id}`,
      at: edge.updated_at || new Date(0).toISOString(),
      title: `${safe(nodeById.get(edge.source_node_id)?.label, "实体")} ${relationLabelOf(edge.relation_type)} ${safe(nodeById.get(edge.target_node_id)?.label, "实体")}`,
      detail: `${edge.evidence_count ?? 0} 个来源 · 置信度 ${Math.round((edge.confidence || 0) * 100)}%`,
      status: edge.relation_type === "contradicts" || edge.status === "conflict" ? "冲突" : statusLabels[edge.status] || "使用中",
      tone: edge.relation_type === "contradicts" || edge.status === "conflict" ? "conflict" : "active",
      edge,
    }));
    return [...nodeItems, ...edgeItems]
      .filter((item) => !normalizedQuery || `${item.title} ${item.detail} ${item.status}`.toLocaleLowerCase().includes(normalizedQuery))
      .sort((left, right) => Date.parse(right.at) - Date.parse(left.at))
      .slice(0, 80);
  }, [graph?.edges, nodes, nodeById, normalizedQuery]);

  return (
    <section className="llmwiki-workspace-panel llmwiki-timeline-workspace" aria-label="记忆时间线工作区">
      <header className="llmwiki-panel-header">
        <div><p className="llmwiki-eyebrow">生命周期</p><h2>确认、纠正和追踪</h2><p className="llmwiki-panel-description">时间线只显示真实状态变化；待确认内容不会悄悄进入回答。</p></div>
        <button type="button" className="icon-button" onClick={onRefresh} disabled={loading} aria-label="刷新记忆时间线" title="刷新时间线"><RefreshCw size={16} className={loading ? "is-spinning" : ""} /></button>
      </header>

      {error ? <div className="llmwiki-state llmwiki-state-error" role="alert"><ShieldAlert size={18} aria-hidden="true" /><div><strong>{error}</strong><span>已加载的生命周期记录仍可查看；修复本机服务后可以重试。</span></div><button type="button" className="secondary" onClick={onRefresh}>重试</button></div> : null}

      {proposals.some((proposal) => proposal.status === "pending") ? (
        <section className="llmwiki-review-queue" aria-label="待确认队列">
          <div className="llmwiki-list-heading"><span><ShieldAlert size={15} aria-hidden="true" /><strong>待确认队列</strong></span><button type="button" className="icon-button" onClick={onLoadProposals} disabled={loadingProposals} aria-label="刷新待确认队列" title="刷新待确认队列"><RefreshCw size={14} /></button></div>
          <div className="llmwiki-review-list">
            {proposals.filter((proposal) => proposal.status === "pending").slice(0, 8).map((proposal) => {
              const busy = proposalActionIds.has(proposal.proposal_id);
              return <article key={proposal.proposal_id} className="llmwiki-review-row"><div><strong>{proposalTitle(proposal)}</strong><p>{safe(proposal.content, "内容暂不可显示")}</p><small>{safe(proposal.target_path, "本地 Wiki")}</small></div><div className="llmwiki-review-actions"><button type="button" className="secondary" onClick={() => onProposalAction(proposal.proposal_id, "confirm")} disabled={busy}><Check size={14} />确认</button><button type="button" className="icon-button is-danger" onClick={() => onProposalAction(proposal.proposal_id, "reject")} disabled={busy} aria-label="拒绝这条记忆" title="拒绝"><X size={14} /></button></div></article>;
            })}
          </div>
        </section>
      ) : null}

      <div className="llmwiki-timeline-heading"><span><History size={16} aria-hidden="true" /><strong>最近变化</strong></span><span>{timeline.length} 条</span></div>
      {loading ? <div className="llmwiki-state" role="status">正在读取生命周期…</div> : timeline.length ? (
        <div className="llmwiki-timeline-list">
          {timeline.map((item) => <article key={item.id} className={`llmwiki-timeline-row is-${item.tone}`}><time dateTime={item.at}>{formatDate(item.at)}</time><span className="llmwiki-timeline-marker" aria-hidden="true" /><div className="llmwiki-timeline-copy"><div><strong>{item.title}</strong><span className={`llmwiki-status-label is-${item.tone}`}>{item.status}</span></div><p>{item.detail}</p>{item.node ? <button type="button" className="text-button" onClick={() => onSelectNode(item.node!.node_id)}>打开证据链 <ExternalLink size={13} /></button> : item.edge ? <button type="button" className="text-button" onClick={() => onSelectEdge(item.edge!.edge_id)}>打开证据链 <ExternalLink size={13} /></button> : null}</div></article>)}
        </div>
      ) : (
        <div className="llmwiki-empty-state"><Clock3 size={19} /><strong>还没有生命周期记录</strong><p>添加一条明确记忆或导入来源后，确认和纠正会出现在这里。</p><div className="llmwiki-empty-actions"><button type="button" className="primary" onClick={onOpenChat}>添加记忆</button><button type="button" className="secondary" onClick={onOpenSources}>导入来源</button></div></div>
      )}

      <details className="llmwiki-activity-drawer">
        <summary><span>活动账本</span><span>{entries.length} 条</span></summary>
        {entries.length ? <div className="llmwiki-activity-list">{entries.slice(0, 40).map((entry) => <div key={entry.id} className="llmwiki-activity-item">{renderEntry(entry)}</div>)}</div> : <p className="llmwiki-muted">普通整理和失败记录会出现在这里。</p>}
      </details>
    </section>
  );
}
