import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type {
  MemoryGraphEdge,
  MemoryGraphEdgeType,
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

type MemoryFlowNodeData = {
  memory: MemoryGraphNode;
  label: string;
  subtitle: string;
  typeLabel: string;
  statusLabel: string;
  color: string;
  size: number;
  pending: boolean;
  archived: boolean;
} & Record<string, unknown>;

type MemoryFlowNode = Node<MemoryFlowNodeData, "memoryNode">;
type MemoryFlowEdge = Edge<Record<string, never>, "straight" | "smoothstep">;

type RelatedMemorySummary = {
  id: string;
  label: string;
  typeLabel: string;
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

const typeColors: Record<MemoryGraphNodeType, string> = {
  user: "#d56f8a",
  preference: "#d56f8a",
  boundary: "#b464b4",
  project: "#6e96d2",
  episode: "#6ebdb7",
  mood: "#7ccf9f",
  qa: "#70b7dc",
  source: "#78a6c9",
  pending: "#dcb464",
  archived: "#6b7280",
  cleanup: "#caa05f",
};

const typeRadii: Record<MemoryGraphNodeType, number> = {
  user: 0,
  preference: 220,
  boundary: 220,
  project: 340,
  episode: 340,
  mood: 250,
  qa: 360,
  source: 360,
  pending: 180,
  archived: 390,
  cleanup: 280,
};

const filterOptions: Array<{ value: "all" | MemoryGraphNodeType; label: string }> = [
  { value: "all", label: "全部" },
  { value: "preference", label: "偏好" },
  { value: "boundary", label: "边界" },
  { value: "project", label: "项目" },
  { value: "episode", label: "情景" },
  { value: "mood", label: "心情" },
  { value: "source", label: "资料" },
  { value: "qa", label: "问答" },
  { value: "pending", label: "待确认" },
  { value: "cleanup", label: "整理" },
];

const legendItems: Array<{ type: MemoryGraphNodeType; label: string }> = [
  { type: "preference", label: "偏好" },
  { type: "boundary", label: "边界" },
  { type: "project", label: "项目" },
];

function safeGraphText(value: string | null | undefined, fallback: string): string {
  const text = value?.trim();
  if (!text || unsafeGraphTextPattern.test(text)) {
    return fallback;
  }
  return text;
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

function visibleNodeLabel(node: MemoryGraphNode): string {
  if (node.type === "user") {
    return "你";
  }
  return safeGraphText(node.label, node.status === "hidden" || node.risk_tier === "hidden" ? "一条已隐藏的记忆" : "一条记忆");
}

function visibleNodeSubtitle(node: MemoryGraphNode): string {
  return safeGraphText(node.subtitle, typeLabels[node.type] || "记忆");
}

function nodeSearchText(node: MemoryGraphNode): string {
  return [
    node.label,
    node.subtitle,
    node.status,
    node.type,
    node.confidence_label,
    node.source_label,
  ]
    .join(" ")
    .toLocaleLowerCase();
}

function nodeVisualSize(node: MemoryGraphNode): number {
  if (node.type === "user") {
    return 48;
  }
  if (node.status === "hidden" || node.type === "archived") {
    return 16;
  }
  if (node.status === "pending" || node.type === "pending") {
    return 24;
  }
  if (node.type === "episode" || node.type === "mood" || node.type === "qa" || node.type === "source") {
    return 18;
  }
  if (node.type === "cleanup") {
    return 20;
  }
  return 24;
}

function edgeClassName(type: MemoryGraphEdgeType): string {
  return `memory-edge-${type.replace(/_/g, "-")}`;
}

function edgeColor(edge: MemoryGraphEdge, sourceNode: MemoryGraphNode | undefined, active: boolean): string {
  if (edge.type === "conflicts_with") {
    return active ? "rgba(239, 68, 68, 0.74)" : "rgba(239, 68, 68, 0.38)";
  }
  if (!active) {
    return "rgba(255, 255, 255, 0.09)";
  }
  const base = sourceNode ? typeColors[sourceNode.type] : "rgba(255, 255, 255, 0.42)";
  const opacity = Math.max(0.28, Math.min(0.56, 0.22 + edge.strength * 0.34));
  return colorWithAlpha(base, opacity);
}

function colorWithAlpha(hex: string, alpha: number): string {
  const normalized = hex.replace("#", "");
  if (normalized.length !== 6) {
    return hex;
  }
  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function limitNodesByType(nodes: MemoryGraphNode[], showAll: boolean): MemoryGraphNode[] {
  if (showAll || nodes.length <= 30) {
    return nodes;
  }
  const counts = new Map<MemoryGraphNodeType, number>();
  return nodes.filter((node) => {
    if (node.type === "user") {
      return true;
    }
    const count = counts.get(node.type) || 0;
    counts.set(node.type, count + 1);
    return count < 5;
  });
}

function stableUnit(seed: string): number {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967295;
}

function getNodePosition(node: MemoryGraphNode, index: number) {
  if (node.type === "user") {
    return { x: 400, y: 300 };
  }
  const radius = typeRadii[node.type] || 280;
  const jitter = stableUnit(`${node.id}:angle:${index}`);
  const angle = jitter * Math.PI * 2;
  const radiusJitter = 0.84 + stableUnit(`${node.id}:radius:${index}`) * 0.32;
  return {
    x: 400 + Math.cos(angle) * radius * radiusJitter,
    y: 300 + Math.sin(angle) * radius * radiusJitter,
  };
}

function buildFlowNodes(nodes: MemoryGraphNode[]): MemoryFlowNode[] {
  const groups = nodes.reduce<Map<MemoryGraphNodeType, MemoryGraphNode[]>>((map, node) => {
    const group = map.get(node.type) || [];
    group.push(node);
    map.set(node.type, group);
    return map;
  }, new Map());

  return nodes.map((node) => {
    const group = groups.get(node.type) || [node];
    const index = group.findIndex((item) => item.id === node.id);
    const position = getNodePosition(node, index);
    const pending = node.status === "pending" || node.type === "pending";
    const archived = node.status === "hidden" || node.status === "archived" || node.type === "archived";
    const color = archived ? typeColors.archived : pending ? typeColors.pending : typeColors[node.type];
    const label = visibleNodeLabel(node);
    const subtitle = visibleNodeSubtitle(node);
    return {
      id: node.id,
      type: "memoryNode",
      position,
      draggable: true,
      selectable: true,
      data: {
        memory: node,
        label,
        subtitle,
        typeLabel: typeLabels[node.type] || subtitle,
        statusLabel: statusLabels[node.status],
        color,
        size: nodeVisualSize(node),
        pending,
        archived,
      },
      ariaRole: "button",
    };
  });
}

function reduceVisualEdges(edges: MemoryGraphEdge[], nodes: MemoryGraphNode[]): MemoryGraphEdge[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const directEdges = edges.filter((edge) => {
    const source = nodeById.get(edge.from);
    const target = nodeById.get(edge.to);
    if (!source || !target) {
      return false;
    }
    return edge.type !== "related_to" || (source.type !== "user" && target.type !== "user");
  });
  return directEdges.length ? directEdges : edges.slice(0, 12);
}

function buildFlowEdges(edges: MemoryGraphEdge[], nodes: MemoryGraphNode[], activeNodeId: string | null): MemoryFlowEdge[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  return reduceVisualEdges(edges, nodes)
    .filter((edge) => nodeById.has(edge.from) && nodeById.has(edge.to))
    .map((edge) => {
      const isConflict = edge.type === "conflicts_with";
      const dashed = edge.type === "supports" || edge.type === "came_from" || edge.type === "updates";
      const active = activeNodeId ? edge.from === activeNodeId || edge.to === activeNodeId : false;
      return {
        id: edge.id,
        source: edge.from,
        target: edge.to,
        type: isConflict ? "smoothstep" : "straight",
        animated: false,
        className: `memory-flow-edge ${edgeClassName(edge.type)} ${active ? "is-active" : ""} ${dashed ? "is-dashed" : ""}`,
        focusable: false,
        selectable: false,
        style: {
          stroke: edgeColor(edge, nodeById.get(edge.from), active),
          strokeWidth: active ? 1.9 : 1.35,
          strokeDasharray: isConflict ? "5 4" : dashed ? "3 4" : undefined,
        },
      };
    });
}

function relatedMemorySummaries(node: MemoryGraphNode | null, nodes: MemoryGraphNode[], edges: MemoryGraphEdge[]): RelatedMemorySummary[] {
  if (!node) {
    return [];
  }
  const nodeById = new Map(nodes.map((item) => [item.id, item]));
  return edges
    .filter((edge) => edge.from === node.id || edge.to === node.id)
    .map((edge) => nodeById.get(edge.from === node.id ? edge.to : edge.from))
    .filter((item): item is MemoryGraphNode => item != null)
    .filter((item) => item.id !== node.id && item.type !== "user")
    .slice(0, 5)
    .map((item) => ({
      id: item.id,
      label: visibleNodeLabel(item),
      typeLabel: visibleNodeSubtitle(item),
    }));
}

function MemoryNode({ data, selected }: NodeProps<MemoryFlowNode>) {
  return (
    <div
      className={[
        "memory-node",
        `memory-node-${data.memory.type}`,
        data.memory.type === "user" ? "memory-node-center" : "",
        data.pending ? "memory-node-pending" : "",
        data.archived ? "memory-node-archived" : "",
        selected ? "is-selected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      style={
        {
          "--memory-node-color": data.color,
          "--memory-node-size": `${data.size}px`,
        } as CSSProperties
      }
      aria-label={`记忆节点：${data.label}`}
      title={`${data.label} · ${data.typeLabel}`}
    >
      <Handle type="target" position={Position.Top} className="memory-node-handle" />
      <span className="memory-node-dot" aria-hidden="true">
        {data.memory.type === "user" ? <span className="memory-node-center-text">你</span> : null}
      </span>
      <span className="memory-flow-node-label">
        <strong>{data.label}</strong>
        <small>{data.typeLabel}</small>
      </span>
      <Handle type="source" position={Position.Bottom} className="memory-node-handle" />
    </div>
  );
}

const nodeTypes: NodeTypes = {
  memoryNode: MemoryNode,
};

export function MemoryGraphPanel({ projection, loading, error, onRefresh }: MemoryGraphPanelProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | MemoryGraphNodeType>("all");
  const [showAll, setShowAll] = useState(false);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const nodes = useMemo(() => projection?.nodes || [], [projection?.nodes]);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredNodes = useMemo(
    () =>
      nodes.filter((node) => {
        if (node.type === "user") {
          return true;
        }
        const matchesType = typeFilter === "all" || node.type === typeFilter;
        const matchesQuery = !normalizedQuery || nodeSearchText(node).includes(normalizedQuery);
        return matchesType && matchesQuery;
      }),
    [nodes, normalizedQuery, typeFilter],
  );
  const visibleNodes = useMemo(() => limitNodesByType(filteredNodes, showAll), [filteredNodes, showAll]);
  const flowNodes = useMemo(() => buildFlowNodes(visibleNodes), [visibleNodes]);
  const activeNodeId = hoveredNodeId || selectedNodeId;
  const flowEdges = useMemo(() => buildFlowEdges(projection?.edges || [], visibleNodes, activeNodeId), [projection?.edges, visibleNodes, activeNodeId]);
  const [reactFlowNodes, setReactFlowNodes, onNodesChange] = useNodesState<MemoryFlowNode>(flowNodes);
  const [reactFlowEdges, setReactFlowEdges, onEdgesChange] = useEdgesState<MemoryFlowEdge>(flowEdges);
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) || null;
  const memoryNodeCount = nodes.filter((node) => node.type !== "user").length;
  const hasMemoryNodes = memoryNodeCount > 0;
  const hasVisibleMemoryNodes = visibleNodes.some((node) => node.type !== "user");
  const isLimited = filteredNodes.length > 30 && !showAll;
  const summary = projection?.summary || {
    total_nodes: 0,
    pending_count: 0,
    cleanup_count: 0,
    hidden_count: 0,
  };
  const selectedRelated = useMemo(() => relatedMemorySummaries(selectedNode, nodes, projection?.edges || []), [nodes, projection?.edges, selectedNode]);

  useEffect(() => {
    setReactFlowNodes(flowNodes);
    setReactFlowEdges(flowEdges);
  }, [flowEdges, flowNodes, setReactFlowEdges, setReactFlowNodes]);

  return (
    <section className="panel feature-window-panel memory-graph-projection-panel memory-flow-projection-panel" aria-label="我的记忆图谱">
      <div className="memory-graph-panel-head memory-flow-panel-head">
        <div>
          <span className="memory-graph-kicker">本机知识图谱</span>
          <strong>我的记忆图谱</strong>
          <p>偏好、边界、项目、情景和资料会在这里连成一张可理解的记忆地图。</p>
        </div>
        <div className="memory-flow-tools" aria-label="记忆图谱筛选">
          <label>
            <span className="sr-only">搜索记忆</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索记忆"
            />
          </label>
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as "all" | MemoryGraphNodeType)}>
            {filterOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          {filteredNodes.length > 30 ? (
            <button type="button" className="secondary memory-flow-show-all" onClick={() => setShowAll((value) => !value)}>
              {showAll ? "收起" : "显示全部"}
            </button>
          ) : null}
          <button type="button" className="secondary memory-graph-refresh" onClick={onRefresh} disabled={loading}>
            刷新图谱
          </button>
        </div>
      </div>

      <dl className="memory-graph-summary-grid memory-flow-summary-grid" aria-label="记忆图谱摘要">
        <div>
          <dt>记忆节点</dt>
          <dd>{summary.total_nodes}</dd>
        </div>
        <div>
          <dt>待确认</dt>
          <dd>{summary.pending_count}</dd>
        </div>
        <div>
          <dt>需整理</dt>
          <dd>{summary.cleanup_count}</dd>
        </div>
        <div>
          <dt>已隐藏</dt>
          <dd>{summary.hidden_count}</dd>
        </div>
      </dl>

      {loading ? (
        <div className="memory-graph-state memory-flow-state" aria-live="polite">
          正在整理你的记忆图谱……
        </div>
      ) : error ? (
        <div className="memory-graph-state memory-flow-state error" role="alert">
          <p>{error}</p>
          <button type="button" className="secondary" onClick={onRefresh}>
            稍后重试
          </button>
        </div>
      ) : hasMemoryNodes ? (
        <div className="memory-graph-content memory-flow-content">
          <div className="memory-graph-map memory-flow-canvas" aria-label="记忆知识图谱画布">
            <ReactFlow
              nodes={reactFlowNodes}
              edges={reactFlowEdges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={(_, node) => setSelectedNodeId(node.id)}
              onNodeMouseEnter={(_, node) => setHoveredNodeId(node.id)}
              onNodeMouseLeave={() => setHoveredNodeId(null)}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.22, maxZoom: 1.16 }}
              minZoom={0.28}
              maxZoom={2}
              defaultViewport={{ x: 0, y: 0, zoom: 0.86 }}
              nodesDraggable
              nodesConnectable={false}
              elementsSelectable
              panOnDrag
              zoomOnScroll
              zoomOnPinch
              zoomOnDoubleClick={false}
              proOptions={{ hideAttribution: true }}
              className="memory-flow"
            >
              <Background color="rgba(255, 255, 255, 0.22)" gap={24} size={1} />
              <Controls showInteractive={false} />
            </ReactFlow>

            <div className="memory-graph-legend" aria-label="图谱颜色图例">
              {legendItems.map((item) => (
                <span key={item.type} className="memory-graph-legend-item">
                  <span className="legend-dot" style={{ "--legend-color": typeColors[item.type] } as CSSProperties} aria-hidden="true" />
                  {item.label}
                </span>
              ))}
            </div>
            <div className="memory-flow-hint" aria-label="图谱操作提示">
              <span>拖拽画布平移</span>
              <span>滚轮缩放</span>
              <span>点击节点查看详情</span>
            </div>
            {isLimited ? <span className="memory-flow-limit-note">每类先显示 5 个节点，展开后可查看全部。</span> : null}
            {!hasVisibleMemoryNodes ? (
              <div className="memory-flow-filter-empty" role="status">
                没有匹配的记忆节点
              </div>
            ) : null}
          </div>

          <MemoryGraphNodeDetail node={selectedNode} related={selectedRelated} onClose={() => setSelectedNodeId(null)} />
        </div>
      ) : (
        <div className="memory-flow-empty">
          <div className="memory-flow-empty-orb" aria-hidden="true" />
          <strong>记忆图谱还是空的</strong>
          <p>告诉我一些关于你的事，我会把它们连成一张记忆地图。</p>
          <div className="memory-flow-empty-actions" aria-label="记忆图谱引导">
            <button type="button" className="secondary">
              告诉我一个偏好
            </button>
            <button type="button" className="secondary">
              告诉我正在做的项目
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function MemoryGraphNodeDetail({ node, related, onClose }: { node: MemoryGraphNode | null; related: RelatedMemorySummary[]; onClose: () => void }) {
  if (!node) {
    return (
      <aside className="memory-graph-detail-panel memory-flow-detail-panel is-empty" aria-label="记忆节点详情">
        <span className="memory-graph-detail-pill">只读</span>
        <strong>点一个节点看看</strong>
        <p>这里会显示它属于哪类记忆、当前状态和安全来源说明。</p>
      </aside>
    );
  }

  const nodeLabel = visibleNodeLabel(node);
  const nodeSubtitle = visibleNodeSubtitle(node);
  return (
    <aside className={`memory-graph-detail-panel memory-flow-detail-panel ${node.status === "hidden" ? "is-hidden" : ""}`} aria-label="记忆节点详情">
      <div className="memory-flow-detail-topline">
        <span className="memory-graph-detail-pill">只读</span>
        <button type="button" className="memory-flow-detail-close" onClick={onClose} aria-label="关闭记忆详情">
          关闭
        </button>
      </div>
      <div className="memory-graph-detail-title">
        <strong>{nodeLabel}</strong>
        <span>
          <b>{nodeSubtitle}</b>
          <b>{statusLabels[node.status]}</b>
        </span>
      </div>
      <div className="memory-flow-detail-section">
        <h3>记忆摘要</h3>
        <p>{safeGraphText(node.confidence_label, "这条记忆已做安全整理")}</p>
      </div>
      <div className="memory-flow-detail-section">
        <h3>关联记忆</h3>
        {related.length ? (
          <ul className="memory-flow-related-list">
            {related.map((item) => (
              <li key={item.id}>
                <span>{item.typeLabel}</span>
                <strong>{item.label}</strong>
              </li>
            ))}
          </ul>
        ) : (
          <p>暂时没有直接关联。</p>
        )}
      </div>
      <dl className="memory-graph-detail-list">
        <div>
          <dt>时间</dt>
          <dd>{formatGraphDate(node.updated_at)}</dd>
        </div>
        <div>
          <dt>确定度</dt>
          <dd>{safeGraphText(node.confidence_label, "已安全处理")}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>{safeGraphText(node.source_label, "来自本机整理")}</dd>
        </div>
        <div>
          <dt>可见性</dt>
          <dd>{riskLabels[node.risk_tier]}</dd>
        </div>
      </dl>
    </aside>
  );
}

export default MemoryGraphPanel;
