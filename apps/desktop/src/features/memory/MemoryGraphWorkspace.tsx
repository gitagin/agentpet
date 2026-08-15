import { Database, ExternalLink, RefreshCw, Search, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { MemoryGraphResponse } from "../../types";
import type { MemoryGraphEdgeItem, MemoryGraphNodeItem } from "./useMemoryGraphWorkspace";
import { useForceLayout } from "./useForceLayout";

type MemoryGraphWorkspaceProps = {
  graph: MemoryGraphResponse | null;
  loading: boolean;
  error: string;
  query: string;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  onQueryChange?: (query: string) => void;
  onSelectNode: (nodeId: string) => void;
  onSelectEdge: (edgeId: string) => void;
  onClearSelection: () => void;
  onRefresh: () => void;
  onOpenChat: () => void;
  onOpenSources: () => void;
};

type FlowNodeData = {
  item: MemoryGraphNodeItem;
  label: string;
  fullLabel: string;
  kindLabel: string;
  color: string;
  isPending: boolean;
  isConflict: boolean;
  dimmed: boolean;
  scale: number;
  dotSize: number;
} & Record<string, unknown>;

type FlowNode = Node<FlowNodeData, "memoryGraphNode">;
type FlowEdge = Edge<Record<string, never>>;

const palette = {
  rose: "#D56F8A",
  teal: "#68B8AD",
  amber: "#D1A44B",
  red: "#D75B5B",
  muted: "#89919B",
} as const;

const typeLabels: Record<string, string> = {
  user: "你",
  preference: "偏好",
  boundary: "边界",
  project: "项目",
  episode: "事件",
  mood: "状态",
  qa: "问答",
  source: "来源",
  pending: "待确认",
  archived: "已归档",
  cleanup: "待整理",
};

const relationLabels: Record<string, string> = {
  prefers: "偏好",
  avoids: "避免",
  works_on: "正在做",
  knows: "了解",
  related_to: "关联",
  occurred_in: "发生于",
  supports: "支持",
  contradicts: "冲突",
  supersedes: "替代",
  derived_from: "派生自",
  documented_in: "记录于",
};

const typeColors: Record<string, string> = {
  user: palette.rose,
  preference: palette.rose,
  boundary: "#bc83c6",
  project: "#75a6d7",
  episode: palette.teal,
  mood: "#89c995",
  qa: "#7eb6d8",
  source: palette.teal,
  pending: palette.amber,
  archived: palette.muted,
  cleanup: palette.amber,
};

const unsafeText = /candidate|fact|evidence|source_text|source_excerpt|agent_run_id|token|authorization|fts|vector|[A-Za-z]:[\\/]|\\\\|\/(?:Users|home|var|tmp)\//i;

function visibleText(value: string | null | undefined, fallback: string): string {
  const text = value?.trim();
  return text && !unsafeText.test(text) ? text : fallback;
}

function nodeLabel(node: MemoryGraphNodeItem): string {
  // 圆点下方显示后端生成的短标题 title，回退到完整 label
  return visibleText(node.title || node.label, node.status === "hidden" ? "已隐藏的记忆" : "一条记忆");
}

function nodeKind(node: MemoryGraphNodeItem): string {
  return typeLabels[node.type] || visibleText(node.subtitle, "记忆");
}

function relationLabel(edge: MemoryGraphEdgeItem): string {
  return relationLabels[edge.relation_type] || "关系";
}

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "时间未记录";
  }
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return "时间未记录";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(timestamp));
}

/* ============================================================
 * 力导向布局辅助：种子位置 + 节点半径
 * ============================================================ */

function stableUnit(seed: string): number {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967295;
}

/** 初始种子位置（布局收敛前 / 新节点占位用） */
function seedPosition(node: MemoryGraphNodeItem, index: number): [number, number] {
  if (node.type === "user") {
    return [0, 0];
  }
  const angle = stableUnit(`${node.node_id}:angle:${index}`) * Math.PI * 2;
  const radius = 155 + stableUnit(`${node.node_id}:radius`) * 175;
  return [Math.cos(angle) * radius, Math.sin(angle) * radius * 0.72];
}

/** 节点半径：度数/规模越大圆点越大（Obsidian「节点大小 = 连接数」） */
function nodeRadius(node: MemoryGraphNodeItem, degree: number): number {
  const sizeBoost = Math.min(Math.max(node.size ?? 1, 0), 2) * 3;
  return 9 + Math.min(degree, 12) * 1.8 + sizeBoost;
}

/** 卡片缩放：度数越高越大（与圆点半径叠加） */
function nodeScale(node: MemoryGraphNodeItem, degree: number): number {
  const sizeBoost = Math.min(Math.max(node.size ?? 1, 0), 2) * 0.06;
  return Math.min(0.88 + Math.min(degree, 12) * 0.035 + sizeBoost, 1.35);
}

/* ============================================================
 * 节点 / 边构建（不含 position：位置由 useForceLayout 的 tick 驱动）
 * ============================================================ */

function flowNodeData(
  nodes: MemoryGraphNodeItem[],
  selectedNodeId: string | null,
  activeId: string | null,
  neighborIds: ReadonlySet<string> | null,
  degreeById: ReadonlyMap<string, number>,
): FlowNode[] {
  const grouped = new Map<string, MemoryGraphNodeItem[]>();
  nodes.forEach((node) => grouped.set(node.type, [...(grouped.get(node.type) || []), node]));
  return nodes.map((node) => {
    const index = grouped.get(node.type)?.findIndex((item) => item.node_id === node.node_id) || 0;
    const isPending = node.status === "pending" || node.type === "pending";
    const isConflict = node.status === "hidden" || node.status === "archived";
    const degree = degreeById.get(node.node_id) ?? 0;
    const dimmed = activeId !== null && neighborIds !== null && !neighborIds.has(node.node_id);
    const seed = seedPosition(node, index);
    return {
      id: node.node_id,
      type: "memoryGraphNode",
      position: { x: seed[0], y: seed[1] },
      data: {
        item: node,
        label: nodeLabel(node),
        fullLabel: visibleText(node.label, nodeLabel(node)),
        kindLabel: nodeKind(node),
        color: isConflict ? palette.muted : isPending ? palette.amber : typeColors[node.type] || palette.teal,
        isPending,
        isConflict,
        dimmed,
        scale: nodeScale(node, degree),
        dotSize: nodeRadius(node, degree),
      },
      draggable: true,
      selectable: true,
      focusable: false,
      selected: node.node_id === selectedNodeId,
    };
  });
}

function flowEdgeData(
  edges: MemoryGraphEdgeItem[],
  selectedEdgeId: string | null,
  activeId: string | null,
  neighborIds: ReadonlySet<string> | null,
): FlowEdge[] {
  return edges.map((edge) => {
    const conflict = edge.relation_type === "contradicts" || edge.status === "conflict";
    const selected = edge.edge_id === selectedEdgeId;
    const confidence = Math.max(0, Math.min(1, edge.confidence ?? 0.6));
    const evidence = Math.min(edge.evidence_count ?? 0, 5);
    const dimmed =
      activeId !== null &&
      neighborIds !== null &&
      !(neighborIds.has(edge.source_node_id) && neighborIds.has(edge.target_node_id));
    return {
      id: edge.edge_id,
      source: edge.source_node_id,
      target: edge.target_node_id,
      label: relationLabel(edge),
      className: ["llmwiki-graph-edge", conflict ? "is-conflict" : "", selected ? "is-selected" : ""]
        .filter(Boolean)
        .join(" "),
      selectable: true,
      focusable: true,
      animated: false,
      style: {
        stroke: conflict ? palette.red : selected ? palette.teal : "rgba(243, 241, 236, 0.35)",
        strokeWidth: selected ? 2.6 : 1 + confidence * 2.2 + evidence * 0.25,
        strokeDasharray: conflict ? "5 4" : undefined,
        opacity: dimmed ? 0.04 : undefined,
      },
      labelStyle: { fill: palette.muted, fontSize: 11, fontWeight: 600 },
      labelBgStyle: { fill: "#1b1d21", fillOpacity: 0.92, color: "#1b1d21" },
    };
  });
}

function MemoryNode({ data, selected }: NodeProps<FlowNode>) {
  const { item, label, fullLabel, kindLabel, color, isPending, isConflict, dimmed, scale, dotSize } = data;
  const diameter = dotSize * 2;
  return (
    <div
      className={[
        "llmwiki-graph-node",
        isPending ? "is-pending" : "",
        isConflict ? "is-archived" : "",
        selected ? "is-selected" : "",
        dimmed ? "is-dimmed" : "",
        item.type === "user" ? "is-center" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      style={
        {
          "--node-color": color,
          "--node-size": `${diameter}px`,
          "--node-scale": String(scale),
        } as React.CSSProperties
      }
      role="button"
      tabIndex={0}
      aria-label={`记忆节点：${label}`}
      title={`${fullLabel}，${kindLabel}`}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          (event.currentTarget.closest("[data-id]") as HTMLElement | null)?.click();
        }
      }}
    >
      <Handle type="target" position={Position.Top} className="llmwiki-graph-handle" />
      <span className="llmwiki-graph-node-copy"><strong>{label}</strong></span>
      <Handle type="source" position={Position.Bottom} className="llmwiki-graph-handle" />
      <span className="sr-only">更新于 {formatDate(item.updated_at)}</span>
    </div>
  );
}

const nodeTypes: NodeTypes = { memoryGraphNode: MemoryNode };

export function MemoryGraphWorkspace({
  graph,
  loading,
  error,
  query,
  selectedNodeId,
  selectedEdgeId,
  onQueryChange,
  onSelectNode,
  onSelectEdge,
  onClearSelection,
  onRefresh,
  onOpenChat,
  onOpenSources,
}: MemoryGraphWorkspaceProps) {
  const nodes = useMemo(() => graph?.nodes || [], [graph?.nodes]);
  const edges = useMemo(() => graph?.edges || [], [graph?.edges]);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleNodes = useMemo(
    () =>
      nodes.filter((node) => {
        if (!normalizedQuery) {
          return true;
        }
        return `${node.label} ${node.subtitle} ${node.type} ${node.status}`.toLocaleLowerCase().includes(normalizedQuery);
      }),
    [nodes, normalizedQuery],
  );
  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((node) => node.node_id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => edges.filter((edge) => visibleNodeIds.has(edge.source_node_id) && visibleNodeIds.has(edge.target_node_id)),
    [edges, visibleNodeIds],
  );

  const degreeById = useMemo(() => {
    const map = new Map<string, number>();
    visibleNodes.forEach((node) => map.set(node.node_id, 0));
    visibleEdges.forEach((edge) => {
      map.set(edge.source_node_id, (map.get(edge.source_node_id) ?? 0) + 1);
      map.set(edge.target_node_id, (map.get(edge.target_node_id) ?? 0) + 1);
    });
    return map;
  }, [visibleNodes, visibleEdges]);

  // ---- 悬停高亮：activeId = 悬停 ?? 选中 ----
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const activeId = hoveredNodeId ?? selectedNodeId;
  const neighborIds = useMemo(() => {
    if (!activeId) {
      return null;
    }
    const set = new Set<string>([activeId]);
    for (const edge of visibleEdges) {
      if (edge.source_node_id === activeId) set.add(edge.target_node_id);
      if (edge.target_node_id === activeId) set.add(edge.source_node_id);
    }
    return set;
  }, [activeId, visibleEdges]);

  // ---- 力导向布局（d3-force 只算坐标，React Flow 只负责渲染） ----
  const { positions, pinNode, unpinNode, onSettled } = useForceLayout<MemoryGraphNodeItem, MemoryGraphEdgeItem>(
    visibleNodes,
    visibleEdges,
    {
      center: [0, 0],
      pinnedIds: new Set(["user"]),
      radiusOf: (node, degree) => nodeRadius(node, degree) + 10, // +10 给下方标签留空间
      seedPosition,
    },
  );

  // 布局收敛后 fit 一次（时序：先让物理摊开，再缩放窗口）
  const rfInstanceRef = useRef<ReactFlowInstance<FlowNode, FlowEdge> | null>(null);
  const fitOnceRef = useRef(false);
  const generationKey = graph?.generation?.generation_id ?? graph?.generated_at ?? "";
  useEffect(() => {
    fitOnceRef.current = false;
  }, [generationKey]);
  useEffect(() => {
    return onSettled(() => {
      if (!fitOnceRef.current && rfInstanceRef.current) {
        fitOnceRef.current = true;
        // 关键：延迟到下一帧再 fitView，等 React commit 布局收敛后的最新坐标，
        // 否则 fitView 会按旧的 seed 位置计算视口，把节点切到画布外（"消失"）
        requestAnimationFrame(() => {
          rfInstanceRef.current?.fitView({ padding: 0.2, maxZoom: 1.1, duration: 500 });
        });
      }
    });
  }, [onSettled]);

  // ---- React Flow 状态：data 变化时整体同步（保留 position），布局 tick 只更新 position ----
  const baseNodes = useMemo(
    () => flowNodeData(visibleNodes, selectedNodeId, activeId, neighborIds, degreeById),
    [visibleNodes, selectedNodeId, activeId, neighborIds, degreeById],
  );
  const baseEdges = useMemo(
    () => flowEdgeData(visibleEdges, selectedEdgeId, activeId, neighborIds),
    [visibleEdges, selectedEdgeId, activeId, neighborIds],
  );

  const [reactFlowNodes, setReactFlowNodes, onNodesChange] = useNodesState<FlowNode>(baseNodes);
  const [reactFlowEdges, setReactFlowEdges, onEdgesChange] = useEdgesState<FlowEdge>(baseEdges);

  useEffect(() => {
    setReactFlowNodes((prev) => {
      const byId = new Map(prev.map((node) => [node.id, node]));
      return baseNodes.map((node) => {
        const old = byId.get(node.id);
        if (!old) {
          return node;
        }
        // 只同步 data / selected / type，保留 position、measured 等 React Flow 运行时字段，
        // 否则 hover/点击时全量重建会丢掉 measured，触发重新测量导致节点短暂"消失"
        return { ...old, data: node.data, selected: node.selected, type: node.type };
      });
    });
  }, [baseNodes, setReactFlowNodes]);

  useEffect(() => {
    setReactFlowEdges(baseEdges);
  }, [baseEdges, setReactFlowEdges]);

  useEffect(() => {
    setReactFlowNodes((prev) =>
      prev.map((node) => {
        const next = positions.get(node.id);
        if (!next) {
          return node;
        }
        if (node.position.x === next.x && node.position.y === next.y) {
          return node;
        }
        return { ...node, position: { x: next.x, y: next.y } };
      }),
    );
  }, [positions, setReactFlowNodes]);

  const summary = graph?.summary || { total_nodes: 0, pending_count: 0, cleanup_count: 0, hidden_count: 0 };
  const hasMemory = nodes.some((node) => node.type !== "user");

  return (
    <section className="llmwiki-workspace-panel llmwiki-graph-workspace" aria-label="记忆图谱工作区">
      <header className="llmwiki-panel-header">
        <div>
          <p className="llmwiki-eyebrow">关系视图</p>
          <h2>从关系进入证据</h2>
          <p className="llmwiki-panel-description">选择节点或关系，沿着来源、Wiki 页面和生命周期检查它是否仍能被召回。</p>
        </div>
        <div className="llmwiki-panel-actions">
          <span className={`llmwiki-health-chip ${graph?.degraded_mode ? "is-degraded" : "is-ready"}`} role="status">
            <Database size={14} aria-hidden="true" />
            {graph?.degraded_mode ? "基础数据模式" : graph ? "本机图谱已就绪" : "等待本机服务"}
          </span>
          <button type="button" className="icon-button" onClick={onRefresh} disabled={loading} aria-label="刷新记忆图谱" title="刷新记忆图谱">
            <RefreshCw size={16} className={loading ? "is-spinning" : ""} aria-hidden="true" />
          </button>
        </div>
      </header>

      <dl className="llmwiki-summary-strip" aria-label="图谱摘要">
        <div><dt>节点</dt><dd>{summary.total_nodes}</dd></div>
        <div><dt>待确认</dt><dd className={summary.pending_count ? "is-amber" : ""}>{summary.pending_count}</dd></div>
        <div><dt>待整理</dt><dd>{summary.cleanup_count}</dd></div>
        <div><dt>已归档</dt><dd>{summary.hidden_count}</dd></div>
      </dl>

      {error ? (
        <div className="llmwiki-state llmwiki-state-error" role="alert">
          <TriangleAlert size={18} aria-hidden="true" />
          <div><strong>{error}</strong><span>当前没有隐藏错误细节；设置页可查看诊断。</span></div>
          <button type="button" className="secondary" onClick={onRefresh}>重试</button>
        </div>
      ) : loading ? (
        <div className="llmwiki-state" role="status" aria-live="polite"><span className="llmwiki-loading-line" />正在读取本机关系…</div>
      ) : !hasMemory ? (
        <div className="llmwiki-empty-state" role="status">
          <strong>还没有可追踪的记忆</strong>
          <p>从一条明确偏好或项目开始，系统会保留来源并等待你确认。</p>
          <div className="llmwiki-empty-actions">
            <button type="button" className="primary" onClick={onOpenChat}>添加一条记忆</button>
            <button type="button" className="secondary" onClick={onOpenSources}><ExternalLink size={15} />导入来源</button>
          </div>
        </div>
      ) : (
        <div className="llmwiki-graph-stage">
          <div className="llmwiki-graph-canvas" aria-label="记忆关系画布">
            <ReactFlow
              nodes={reactFlowNodes}
              edges={reactFlowEdges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onInit={(instance) => {
                rfInstanceRef.current = instance;
              }}
              onNodeClick={(_, node) => onSelectNode(node.id)}
              onEdgeClick={(_, edge) => onSelectEdge(edge.id)}
              onPaneClick={onClearSelection}
              onNodeMouseEnter={(_, node) => setHoveredNodeId(node.id)}
              onNodeMouseLeave={() => setHoveredNodeId(null)}
              onNodeDrag={(_, node) => pinNode(node.id, node.position.x, node.position.y)}
              onNodeDragStop={(_, node) => unpinNode(node.id)}
              fitView
              fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
              minZoom={0.3}
              maxZoom={1.8}
              nodesConnectable={false}
              elementsSelectable
              edgesFocusable
              panOnDrag
              zoomOnScroll
              zoomOnPinch
              zoomOnDoubleClick={false}
              proOptions={{ hideAttribution: true }}
              className="llmwiki-react-flow"
            >
              <Background color="rgba(243,241,236,.12)" gap={24} size={1} />
              <Controls showInteractive={false} />
            </ReactFlow>
            <div className="llmwiki-graph-canvas-search">
              <Search size={15} aria-hidden="true" />
              <label><span className="sr-only">筛选图谱</span><input value={query} onChange={(event) => onQueryChange?.(event.target.value)} placeholder="筛选节点" /></label>
            </div>
          </div>
          <div className="llmwiki-relation-list" aria-label="关系列表">
            <div className="llmwiki-list-heading"><strong>可核验关系</strong><span>{visibleEdges.length} 条</span></div>
            {visibleEdges.length ? visibleEdges.slice(0, 12).map((edge) => {
              const from = nodes.find((node) => node.node_id === edge.source_node_id);
              const to = nodes.find((node) => node.node_id === edge.target_node_id);
              const conflict = edge.relation_type === "contradicts" || edge.status === "conflict";
              return (
                <button key={edge.edge_id} type="button" className={`llmwiki-relation-row ${selectedEdgeId === edge.edge_id ? "is-selected" : ""} ${conflict ? "is-conflict" : ""}`} onClick={() => onSelectEdge(edge.edge_id)}>
                  <span className="llmwiki-relation-dot" aria-hidden="true" />
                  <span><strong>{visibleText(from?.label, "来源节点")}</strong><small>{relationLabel(edge)} → {visibleText(to?.label, "目标节点")}</small></span>
                  <span className="llmwiki-relation-evidence">{edge.evidence_count ?? 0} 源</span>
                </button>
              );
            }) : <p className="llmwiki-muted">当前筛选没有关系。</p>}
          </div>
        </div>
      )}
    </section>
  );
}
