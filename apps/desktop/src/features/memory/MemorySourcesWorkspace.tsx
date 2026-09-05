import { BookOpen, ExternalLink, FileText, GitBranch, RefreshCw, Search, Upload } from "lucide-react";
import type { FormEvent } from "react";
import type { MemoryGraphResponse, MemorySearchResult, MemorySearchResult as SearchResult } from "../../types";
import type { MemoryGraphNodeItem } from "./useMemoryGraphWorkspace";

type MemorySourcesWorkspaceProps = {
  graph: MemoryGraphResponse | null;
  searchQuery: string;
  searchStatus: "idle" | "loading" | "success" | "empty" | "error" | string;
  searchResults: MemorySearchResult[];
  onSearchQueryChange: (value: string) => void;
  onSearch: (event: FormEvent) => void;
  onSelectNode: (nodeId: string) => void;
  onOpenImport: () => void;
  onOpenSource: (relativePath: string) => void;
  onRebuild: () => Promise<void>;
  rebuildBusy: boolean;
  rebuildMessage: string;
  onRefresh: () => void;
  loading: boolean;
  error: string;
};

const unsafeText = /candidate|fact|evidence|source_text|source_excerpt|agent_run_id|token|authorization|fts|vector|[A-Za-z]:[\\/]|\\\\/i;

function safe(value: string | null | undefined, fallback: string): string {
  const text = value?.trim();
  return text && !unsafeText.test(text) ? text : fallback;
}

function sourceNodes(graph: MemoryGraphResponse | null): MemoryGraphNodeItem[] {
  return (graph?.nodes || []).filter((node) => node.type === "source" || node.type === "qa");
}

function SearchResults({ results, onOpenSource }: { results: SearchResult[]; onOpenSource: (path: string) => void }) {
  return <div className="llmwiki-source-search-results" aria-label="来源搜索结果">{results.slice(0, 8).map((result) => <article key={`${result.note_id}:${result.chunk_id}`}><div><FileText size={15} aria-hidden="true" /><strong>{safe(result.title, "本地来源")}</strong></div><p>{safe(result.snippet, "没有可展示的摘要")}</p><button type="button" className="text-button" onClick={() => onOpenSource(result.relative_path)}>打开来源 <ExternalLink size={13} /></button></article>)}</div>;
}

export function MemorySourcesWorkspace({
  graph,
  searchQuery,
  searchStatus,
  searchResults,
  onSearchQueryChange,
  onSearch,
  onSelectNode,
  onOpenImport,
  onOpenSource,
  onRebuild,
  rebuildBusy,
  rebuildMessage,
  onRefresh,
  loading,
  error,
}: MemorySourcesWorkspaceProps) {
  const nodes = sourceNodes(graph);
  const vaultLabel = graph?.vault ? "本地资料库已绑定" : "尚未绑定本地资料库";
  return (
    <section className="llmwiki-workspace-panel llmwiki-sources-workspace" aria-label="记忆来源工作区">
      <header className="llmwiki-panel-header">
        <div><p className="llmwiki-eyebrow">来源档案</p><h2>原始来源与 Wiki 页面</h2><p className="llmwiki-panel-description">来源是记忆的依据。没有可验证来源的内容不会被当作可靠事实。</p></div>
        <div className="llmwiki-panel-actions"><span className={`llmwiki-health-chip ${graph?.vault ? "is-ready" : "is-degraded"}`}>{graph?.vault ? <BookOpen size={14} /> : <Upload size={14} />}{vaultLabel}</span><button type="button" className="icon-button" onClick={onRefresh} disabled={loading} aria-label="刷新来源" title="刷新来源"><RefreshCw size={16} className={loading ? "is-spinning" : ""} /></button></div>
      </header>

      {error ? <div className="llmwiki-state llmwiki-state-error" role="alert"><BookOpen size={18} aria-hidden="true" /><div><strong>{error}</strong><span>来源搜索和已加载的材料仍可查看；修复本机服务后可以重试。</span></div><button type="button" className="secondary" onClick={onRefresh}>重试</button></div> : null}

      <form className="llmwiki-source-search" onSubmit={onSearch} role="search">
        <Search size={17} aria-hidden="true" /><label><span className="sr-only">搜索本地来源</span><input value={searchQuery} onChange={(event) => onSearchQueryChange(event.target.value)} placeholder="搜索来源、Wiki 页面或记忆摘要" /></label><button type="submit" className="primary" disabled={!searchQuery.trim() || searchStatus === "loading"}>{searchStatus === "loading" ? "搜索中…" : "搜索"}</button>
      </form>
      {searchStatus === "error" ? <p className="llmwiki-inline-error" role="alert">来源搜索暂时不可用；请重试或直接打开资料库。</p> : null}
      {searchQuery.trim() ? (
        searchResults.length ? <SearchResults results={searchResults} onOpenSource={onOpenSource} /> : searchStatus === "empty" ? <p className="llmwiki-muted">没有找到可引用的本地来源。</p> : null
      ) : null}

      <div className="llmwiki-source-actions" aria-label="来源操作">
        <button type="button" className="primary" onClick={onOpenImport}><Upload size={15} />导入来源</button>
        <button type="button" className="secondary" onClick={() => void onRebuild()} disabled={rebuildBusy}><GitBranch size={15} />{rebuildBusy ? "重建中…" : "重建派生图"}</button>
      </div>
      {rebuildMessage ? <p className="llmwiki-inline-success" role="status">{rebuildMessage}</p> : null}

      {nodes.length ? <div className="llmwiki-source-list" aria-label="本机来源列表">{nodes.map((node) => <button key={node.node_id} type="button" className="llmwiki-source-row" onClick={() => onSelectNode(node.node_id)}><span className="llmwiki-source-icon"><FileText size={16} /></span><span><strong>{safe(node.label, "本地来源")}</strong><small>{safe(node.subtitle, "来源")} · {node.evidence_count ?? 0} 个证据 · {node.updated_at}</small></span><ExternalLink size={15} aria-hidden="true" /></button>)}</div> : <div className="llmwiki-empty-state llmwiki-source-empty-state"><BookOpen size={19} /><strong>还没有来源节点</strong><p>使用上方“导入来源”添加本地文档，或从聊天中保存一条来源。</p></div>}
    </section>
  );
}
