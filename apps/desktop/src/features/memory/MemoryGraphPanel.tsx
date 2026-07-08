import type { CSSProperties } from "react";
import { useMemo, useState } from "react";
import type {
  MemoryGraphCluster,
  MemoryGraphNode,
  MemoryGraphNodeStatus,
  MemoryGraphNodeType,
  MemoryGraphProjectionResponse,
  MemoryGraphRiskTier,
} from "../../types";

type MemoryGraphPanelProps = {
  projection: MemoryGraphProjectionResponse | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
};

const unsafeGraphTextPattern =
  /\b(candidate|fact|evidence|token|authorization|fts|vector|path)\b|source_text|source_excerpt|agent_run_id|message_id|conversation_id|lifecycle_status|raw[\s_-]*id|[A-Za-z]:[\\/]|\\\\|\/(?:Users|home|var|tmp|etc|opt)\//i;

const statusLabels: Record<MemoryGraphNodeStatus, string> = {
  active: "使用中",
  pending: "待确认",
  archived: "已归档",
  hidden: "已隐藏",
};

const riskLabels: Record<MemoryGraphRiskTier, string> = {
  low: "普通",
  hidden: "已隐藏",
};

const typeLabels: Record<MemoryGraphNodeType, string> = {
  user: "记忆中心",
  preference: "偏好",
  boundary: "边界",
  project: "项目",
  episode: "情景",
  mood: "心情",
  qa: "问答",
  source: "资料",
  pending: "待确认",
  archived: "已归档",
  cleanup: "需要整理",
};

function safeGraphText(value: string | null | undefined, fallback: string): string {
  const text = value?.trim();
  if (!text || unsafeGraphTextPattern.test(text)) {
    return fallback;
  }
  return text;
}

function clampGraphSize(value: number): number {
  if (!Number.isFinite(value)) {
    return 1;
  }
  return Math.max(0.78, Math.min(1.18, value));
}

function formatGraphDate(value: string): string {
  const time = Date.parse(value);
  if (Number.isNaN(time)) {
    return safeGraphText(value, "刚刚更新");
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(time));
}

function nodeTypeClass(type: MemoryGraphNodeType): string {
  return `type-${type.replace(/_/g, "-")}`;
}

function visibleNodeLabel(node: MemoryGraphNode): string {
  if (node.type === "user") {
    return "你";
  }
  return safeGraphText(node.label, node.status === "hidden" || node.risk_tier === "hidden" ? "有一条已隐藏的记忆" : "一条记忆");
}

function visibleNodeSubtitle(node: MemoryGraphNode): string {
  return safeGraphText(node.subtitle, typeLabels[node.type] || "记忆");
}

function buildFallbackCluster(nodes: MemoryGraphNode[]): Array<{ cluster: MemoryGraphCluster; nodes: MemoryGraphNode[] }> {
  if (!nodes.length) {
    return [];
  }
  return [
    {
      cluster: { id: "cluster_safe_memories", label: "记忆", node_ids: nodes.map((node) => node.id) },
      nodes,
    },
  ];
}

export function MemoryGraphPanel({ projection, loading, error, onRefresh }: MemoryGraphPanelProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const nodes = projection?.nodes || [];
  const memoryNodes = nodes.filter((node) => node.type !== "user");
  const centerNode = nodes.find((node) => node.type === "user") || null;
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) || null;
  const hasMemoryNodes = memoryNodes.length > 0;
  const summary = projection?.summary || {
    total_nodes: 0,
    pending_count: 0,
    cleanup_count: 0,
    hidden_count: 0,
  };
  const safeRedactionNote = safeGraphText(
    projection?.redaction_note,
    "敏感内容、原始细节、授权信息和本机位置不会显示。",
  );
  const clusterGroups = useMemo(() => {
    if (!projection) {
      return [];
    }
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const groups = projection.clusters
      .map((cluster) => ({
        cluster,
        nodes: cluster.node_ids
          .map((nodeId) => nodeById.get(nodeId))
          .filter((node): node is MemoryGraphNode => node !== undefined && node.type !== "user"),
      }))
      .filter((group) => group.nodes.length > 0);
    return groups.length > 0 ? groups : buildFallbackCluster(memoryNodes);
  }, [memoryNodes, nodes, projection]);

  return (
    <section className="panel feature-window-panel memory-graph-projection-panel" aria-label="我的记忆图谱">
      <div className="memory-graph-panel-head">
        <div>
          <span className="memory-graph-kicker">本机记忆地图</span>
          <strong>我的记忆图谱</strong>
          <p>把偏好、项目、事件和资料连成一张你能看懂的记忆地图。</p>
        </div>
        <button type="button" className="secondary memory-graph-refresh" onClick={onRefresh} disabled={loading}>
          刷新图谱
        </button>
      </div>

      <dl className="memory-graph-summary-grid" aria-label="记忆图谱摘要">
        <div>
          <dt>记忆节点数</dt>
          <dd>{summary.total_nodes}</dd>
        </div>
        <div>
          <dt>待确认数量</dt>
          <dd>{summary.pending_count}</dd>
        </div>
        <div>
          <dt>需要整理数量</dt>
          <dd>{summary.cleanup_count}</dd>
        </div>
        <div>
          <dt>已隐藏敏感数量</dt>
          <dd>{summary.hidden_count}</dd>
        </div>
      </dl>

      {loading ? (
        <div className="memory-graph-state" aria-live="polite">
          正在整理你的记忆图谱……
        </div>
      ) : error ? (
        <div className="memory-graph-state error" role="alert">
          <p>{error}</p>
          <button type="button" className="secondary" onClick={onRefresh}>
            稍后重试
          </button>
        </div>
      ) : hasMemoryNodes ? (
        <div className="memory-graph-content">
          <div className="memory-graph-map" aria-label="记忆星群">
            <div className="memory-graph-center-wrap">
              <button
                type="button"
                className="memory-graph-center-node"
                onClick={() => centerNode && setSelectedNodeId(centerNode.id)}
                aria-label="查看记忆节点：你"
              >
                <span>你</span>
                <small>记忆中心</small>
              </button>
              <span className="memory-graph-edge-count">{projection?.edges.length || 0} 条关联</span>
            </div>
            <div className="memory-graph-cluster-grid">
              {clusterGroups.map(({ cluster, nodes: clusterNodes }) => (
                <article key={cluster.id} className="memory-graph-cluster-card">
                  <div className="memory-graph-cluster-head">
                    <strong>{safeGraphText(cluster.label, "记忆")}</strong>
                    <span>{clusterNodes.length}</span>
                  </div>
                  <div className="memory-graph-node-list">
                    {clusterNodes.slice(0, 8).map((node) => {
                      const nodeLabel = visibleNodeLabel(node);
                      const nodeSubtitle = visibleNodeSubtitle(node);
                      const nodeStyle = {
                        "--memory-graph-node-scale": String(clampGraphSize(node.size)),
                      } as CSSProperties;
                      return (
                        <button
                          key={node.id}
                          type="button"
                          className={`memory-graph-node ${nodeTypeClass(node.type)} status-${node.status}`}
                          style={nodeStyle}
                          onClick={() => setSelectedNodeId(node.id)}
                          aria-label={`查看记忆节点：${nodeLabel}`}
                        >
                          <span className="memory-graph-node-orb" aria-hidden="true" />
                          <strong>{nodeLabel}</strong>
                          <small>{nodeSubtitle}</small>
                        </button>
                      );
                    })}
                  </div>
                </article>
              ))}
            </div>
          </div>

          <MemoryGraphNodeDetail node={selectedNode} />
        </div>
      ) : (
        <div className="memory-graph-empty-state">
          <div className="memory-graph-empty-center" aria-hidden="true">
            你
          </div>
          <div>
            <strong>还没有形成可展示的记忆星群。</strong>
            <p>记忆会留在本机，你可以随时确认、改正或忘记。</p>
          </div>
          <div className="memory-graph-empty-guides" aria-label="记忆图谱引导">
            <span>告诉我一个偏好</span>
            <span>告诉我正在做的项目</span>
            <span>告诉我不希望被记住的边界</span>
          </div>
        </div>
      )}

      {projection && !loading && !error ? <p className="memory-graph-redaction-note">{safeRedactionNote}</p> : null}
    </section>
  );
}

function MemoryGraphNodeDetail({ node }: { node: MemoryGraphNode | null }) {
  if (!node) {
    return (
      <aside className="memory-graph-detail-panel" aria-label="记忆节点详情">
        <span className="memory-graph-detail-pill">只读</span>
        <strong>点一个节点看看</strong>
        <p>这里会显示它属于哪类记忆、当前状态和安全来源说明。</p>
      </aside>
    );
  }

  const nodeLabel = visibleNodeLabel(node);
  const nodeSubtitle = visibleNodeSubtitle(node);
  return (
    <aside className={`memory-graph-detail-panel ${node.status === "hidden" ? "is-hidden" : ""}`} aria-label="记忆节点详情">
      <span className="memory-graph-detail-pill">只读</span>
      <div className="memory-graph-detail-title">
        <strong>{nodeLabel}</strong>
        <span>{nodeSubtitle}</span>
      </div>
      <dl className="memory-graph-detail-list">
        <div>
          <dt>类型</dt>
          <dd>{nodeSubtitle}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd>{statusLabels[node.status]}</dd>
        </div>
        <div>
          <dt>确定程度</dt>
          <dd>{safeGraphText(node.confidence_label, "已安全处理")}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>{safeGraphText(node.source_label, "来自本机整理")}</dd>
        </div>
        <div>
          <dt>敏感级别</dt>
          <dd>{riskLabels[node.risk_tier]}</dd>
        </div>
        <div>
          <dt>最近更新</dt>
          <dd>{formatGraphDate(node.updated_at)}</dd>
        </div>
      </dl>
      <p>这是一张只读地图，用来帮你看清我会参考哪些记忆。</p>
    </aside>
  );
}

export default MemoryGraphPanel;
