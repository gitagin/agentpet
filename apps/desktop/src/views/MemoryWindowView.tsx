import { AlertCircle, Database, RefreshCw, Search } from "lucide-react";
import type { FormEvent, ReactNode } from "react";
import { useMemo, useState } from "react";
import type { AgentActivityLogEntry } from "../services/agentActivity";
import type { DesktopApi } from "../services/desktopApi";
import type {
  MemoryProposal,
  MemoryProposalDraft,
  MemorySearchResult,
} from "../types";
import { FeatureWindowShell } from "./FeatureWindowShell";
import { MemoryEvidenceRail } from "../features/memory/MemoryEvidenceRail";
import { MemoryGraphWorkspace } from "../features/memory/MemoryGraphWorkspace";
import { MemorySourcesWorkspace } from "../features/memory/MemorySourcesWorkspace";
import { MemoryTimelineWorkspace } from "../features/memory/MemoryTimelineWorkspace";
import { useMemoryGraphWorkspace } from "../features/memory/useMemoryGraphWorkspace";

type MemoryWorkspaceTab = "graph" | "timeline" | "sources";

type MemoryWindowViewProps = {
  api: DesktopApi;
  loading: boolean;
  error: string;
  entries: AgentActivityLogEntry[];
  memorySearchQuery: string;
  memorySearchStatus: "idle" | "loading" | "success" | "empty" | "error" | string;
  memorySearchResults: MemorySearchResult[];
  memoryLastSearchQuery: string;
  onMemorySearchQueryChange: (query: string) => void;
  onRunMemorySearch: (event: FormEvent) => void;
  memoryProposalDraft: MemoryProposalDraft;
  memoryProposals: MemoryProposal[];
  memoryProposalActionIds: Set<string>;
  loadingMemoryProposals: boolean;
  onMemoryProposalDraftChange: (patch: Partial<MemoryProposalDraft>) => void;
  onCreateMemoryProposal: (event: FormEvent) => void;
  onActOnMemoryProposal: (proposalId: string, action: "confirm" | "reject") => void;
  onLoadMemoryProposals: () => void;
  onRefresh: () => void;
  renderEntry: (entry: AgentActivityLogEntry) => ReactNode;
};

const tabs: Array<{ key: MemoryWorkspaceTab; label: string; short: string }> = [
  { key: "graph", label: "图谱", short: "关系与实体" },
  { key: "timeline", label: "时间线", short: "生命周期" },
  { key: "sources", label: "来源", short: "原始材料" },
];

function defaultWorkspaceTab(): MemoryWorkspaceTab {
  if (typeof window !== "undefined" && window.innerWidth <= 600) {
    return "timeline";
  }
  return "graph";
}

function safeErrorMessage(value: string): string {
  if (!value.trim()) {
    return "";
  }
  if (/8765|127\.0\.0\.1|localhost|agent_run_id|token|authorization|[A-Za-z]:[\\/]/i.test(value)) {
    return "本机助手暂时不可用，请稍后重试。诊断详情保留在设置页。";
  }
  return value;
}

function createSourceOpener(): (relativePath: string) => void {
  return (relativePath: string) => {
    if (!relativePath.trim()) {
      return;
    }
    if (window.agentDesktop?.revealVaultPath) {
      void window.agentDesktop.revealVaultPath(relativePath, "open");
      return;
    }
    window.location.hash = "#world";
  };
}

function WorkspaceTabs({ active, onChange }: { active: MemoryWorkspaceTab; onChange: (tab: MemoryWorkspaceTab) => void }) {
  function moveTab(index: number, key: string) {
    if (key !== "ArrowLeft" && key !== "ArrowRight" && key !== "Home" && key !== "End") {
      return;
    }
    const current = tabs.findIndex((tab) => tab.key === active);
    const nextIndex = key === "Home" ? 0 : key === "End" ? tabs.length - 1 : (current + (key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    const next = tabs[nextIndex];
    onChange(next.key);
    requestAnimationFrame(() => document.getElementById(`llmwiki-memory-tab-${next.key}`)?.focus());
    void index;
  }

  return (
    <nav className="llmwiki-workspace-tabs" role="tablist" aria-label="记忆工作区视图">
      {tabs.map((tab, index) => <button key={tab.key} id={`llmwiki-memory-tab-${tab.key}`} type="button" role="tab" aria-selected={active === tab.key} aria-controls={`llmwiki-memory-panel-${tab.key}`} tabIndex={active === tab.key ? 0 : -1} className={`llmwiki-workspace-tab ${active === tab.key ? "is-active" : ""}`} onClick={() => onChange(tab.key)} onKeyDown={(event) => { moveTab(index, event.key); if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) event.preventDefault(); }}><strong>{tab.label}</strong><span>{tab.short}</span></button>)}
    </nav>
  );
}

function GlobalSearch({ query, status, resultCount, onChange, onSubmit }: { query: string; status: string; resultCount: number; onChange: (query: string) => void; onSubmit: (event: FormEvent) => void }) {
  return (
    <form className="llmwiki-global-search" onSubmit={onSubmit} role="search">
      <Search size={17} aria-hidden="true" />
      <label><span className="sr-only">搜索记忆、来源和 Wiki</span><input type="search" value={query} onChange={(event) => onChange(event.target.value)} placeholder="搜索记忆、来源和 Wiki" /></label>
      <span className="llmwiki-search-state">{status === "loading" ? "搜索中…" : resultCount ? `${resultCount} 条结果` : "本机搜索"}</span>
      <button type="submit" className="primary" disabled={!query.trim() || status === "loading"}>搜索</button>
    </form>
  );
}

function SearchResultStrip({ results, query, onOpenSource }: { results: MemorySearchResult[]; query: string; onOpenSource: (path: string) => void }) {
  if (!query.trim() || !results.length) {
    return null;
  }
  return <div className="llmwiki-global-results" aria-label="全局搜索结果">{results.slice(0, 4).map((result) => <button key={`${result.note_id}:${result.chunk_id}`} type="button" onClick={() => onOpenSource(result.relative_path)}><span>{result.title || "本地来源"}</span><small>{result.snippet || "没有可展示的摘要"}</small></button>)}</div>;
}

export default function MemoryWindowView({
  api,
  loading: _loading,
  error,
  entries,
  memorySearchQuery,
  memorySearchStatus,
  memorySearchResults,
  memoryLastSearchQuery,
  onMemorySearchQueryChange,
  onRunMemorySearch,
  memoryProposalDraft: _memoryProposalDraft,
  memoryProposals,
  memoryProposalActionIds,
  loadingMemoryProposals,
  onMemoryProposalDraftChange: _onMemoryProposalDraftChange,
  onCreateMemoryProposal: _onCreateMemoryProposal,
  onActOnMemoryProposal,
  onLoadMemoryProposals,
  onRefresh,
  renderEntry,
}: MemoryWindowViewProps) {
  const [activeTab, setActiveTab] = useState<MemoryWorkspaceTab>(() => defaultWorkspaceTab());
  const graphState = useMemoryGraphWorkspace(api, onRefresh);
  const selectedNode = useMemo(() => graphState.graph?.nodes?.find((node) => node.node_id === graphState.selection.nodeId) || null, [graphState.graph?.nodes, graphState.selection.nodeId]);
  const selectedEdge = useMemo(() => graphState.graph?.edges?.find((edge) => edge.edge_id === graphState.selection.edgeId) || null, [graphState.graph?.edges, graphState.selection.edgeId]);
  const openSource = useMemo(() => createSourceOpener(), []);

  function openChat() {
    window.location.hash = "#chat";
    requestAnimationFrame(() => document.querySelector<HTMLInputElement>("textarea, input[type='text']")?.focus());
  }

  function openSources() {
    window.location.hash = "#world";
  }

  const summary = graphState.graph?.summary || { total_nodes: 0, pending_count: 0, cleanup_count: 0, hidden_count: 0 };
  const globalError = safeErrorMessage(error);
  const activeTabLabel = tabs.find((tab) => tab.key === activeTab)?.label || "图谱";

  return (
    <FeatureWindowShell eyebrow="记忆档案室" title="本地个人 LLM Wiki 与记忆图谱" description="查看记忆从实体关系到来源和生命周期的证据链。" activeTab="记忆" showHeader={false} surface="graphite">
      <main className="llmwiki-memory-shell" data-workspace={activeTab}>
        <header className="llmwiki-memory-header">
          <div className="llmwiki-memory-title"><p className="llmwiki-eyebrow">个人记忆档案室</p><h1>记忆图谱</h1><p>每一条可召回记忆都应该能回到来源，也能被你纠正或忘记。</p></div>
          <div className="llmwiki-memory-header-status"><span><Database size={14} aria-hidden="true" />{summary.total_nodes} 个节点</span><span className={summary.pending_count ? "is-amber" : ""}><AlertCircle size={14} aria-hidden="true" />{summary.pending_count} 待确认</span><button type="button" className="icon-button" onClick={graphState.refresh} disabled={graphState.loading} aria-label="刷新记忆工作区" title="刷新"><RefreshCw size={16} className={graphState.loading ? "is-spinning" : ""} /></button></div>
        </header>
        <GlobalSearch query={memorySearchQuery} status={memorySearchStatus} resultCount={memorySearchResults.length} onChange={onMemorySearchQueryChange} onSubmit={onRunMemorySearch} />
        {memoryLastSearchQuery && memorySearchStatus === "empty" ? <p className="llmwiki-search-empty" role="status">没有找到“{memoryLastSearchQuery}”的本地来源。</p> : null}
        <SearchResultStrip results={memorySearchResults} query={memorySearchQuery || memoryLastSearchQuery} onOpenSource={openSource} />
        <WorkspaceTabs active={activeTab} onChange={setActiveTab} />
        {globalError ? <div className="llmwiki-global-error" role="alert"><AlertCircle size={16} />{globalError}<button type="button" className="icon-button" onClick={onRefresh} aria-label="重新加载活动" title="重新加载"><RefreshCw size={14} /></button></div> : null}
        <section id={`llmwiki-memory-panel-${activeTab}`} className="llmwiki-memory-panel" role="tabpanel" aria-label={`记忆工作区：${activeTabLabel}`}>
          {activeTab === "graph" ? <div className="llmwiki-graph-layout"><MemoryGraphWorkspace graph={graphState.graph} loading={graphState.loading} error={graphState.error} query={memorySearchQuery} selectedNodeId={graphState.selection.nodeId} selectedEdgeId={graphState.selection.edgeId} onQueryChange={onMemorySearchQueryChange} onSelectNode={graphState.selectNode} onSelectEdge={graphState.selectEdge} onClearSelection={graphState.clearSelection} onRefresh={graphState.refresh} onOpenChat={openChat} onOpenSources={openSources} /><MemoryEvidenceRail node={selectedNode} edge={selectedEdge} nodeDetail={graphState.nodeDetail} edgeDetail={graphState.edgeDetail} claimDetail={graphState.claimDetail} endpointDetails={graphState.endpointDetails} loading={graphState.detailLoading} error={graphState.detailError} actionBusy={graphState.actionBusy} actionError={graphState.actionError} actionMessage={graphState.actionMessage} onClose={graphState.clearSelection} onApplyAction={graphState.applyAction} onOpenSource={openSource} /></div> : null}
          {activeTab === "timeline" ? <div className="llmwiki-single-layout"><MemoryTimelineWorkspace graph={graphState.graph} entries={entries} proposals={memoryProposals} loading={graphState.loading} error={graphState.error} loadingProposals={loadingMemoryProposals} query={memorySearchQuery} proposalActionIds={memoryProposalActionIds} onSelectNode={graphState.selectNode} onSelectEdge={graphState.selectEdge} onRefresh={graphState.refresh} onLoadProposals={onLoadMemoryProposals} onProposalAction={onActOnMemoryProposal} onOpenChat={openChat} onOpenSources={openSources} renderEntry={renderEntry} /><MemoryEvidenceRail node={selectedNode} edge={selectedEdge} nodeDetail={graphState.nodeDetail} edgeDetail={graphState.edgeDetail} claimDetail={graphState.claimDetail} endpointDetails={graphState.endpointDetails} loading={graphState.detailLoading} error={graphState.detailError} actionBusy={graphState.actionBusy} actionError={graphState.actionError} actionMessage={graphState.actionMessage} onClose={graphState.clearSelection} onApplyAction={graphState.applyAction} onOpenSource={openSource} /></div> : null}
          {activeTab === "sources" ? <div className="llmwiki-single-layout"><MemorySourcesWorkspace graph={graphState.graph} searchQuery={memorySearchQuery} searchStatus={memorySearchStatus} searchResults={memorySearchResults} onSearchQueryChange={onMemorySearchQueryChange} onSearch={onRunMemorySearch} onSelectNode={graphState.selectNode} onOpenImport={openSources} onOpenSource={openSource} onRebuild={graphState.rebuild} rebuildBusy={graphState.rebuildBusy} rebuildMessage={graphState.rebuildMessage} onRefresh={graphState.refresh} loading={graphState.loading} error={graphState.error} /><MemoryEvidenceRail node={selectedNode} edge={selectedEdge} nodeDetail={graphState.nodeDetail} edgeDetail={graphState.edgeDetail} claimDetail={graphState.claimDetail} endpointDetails={graphState.endpointDetails} loading={graphState.detailLoading} error={graphState.detailError} actionBusy={graphState.actionBusy} actionError={graphState.actionError} actionMessage={graphState.actionMessage} onClose={graphState.clearSelection} onApplyAction={graphState.applyAction} onOpenSource={openSource} /></div> : null}
        </section>
      </main>
    </FeatureWindowShell>
  );
}
