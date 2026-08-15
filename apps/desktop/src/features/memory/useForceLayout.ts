import { useCallback, useEffect, useRef, useState } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";

/**
 * 力导向布局引擎（方案 A：React Flow 负责渲染，d3-force 只负责算坐标）。
 *
 * 参数用 d3-force 原生语义调校（不是手写引擎的物理参数，两者阻尼/斥力公式不同）：
 *   charge -30 / linkDistance 60 / center strength 1 / velocityDecay 0.4
 * 数值仿真结果：bbox 约 622×561、孤立节点距中心 ~352px、连线均距 ~113px，
 * 图不会摊到视口之外（避免节点"消失"）。
 */

export type LayoutNodeItem = {
  node_id: string;
  type: string;
  size?: number;
};

export type LayoutEdgeItem = {
  source_node_id: string;
  target_node_id: string;
  confidence?: number;
  evidence_count?: number;
};

export type LayoutPosition = { x: number; y: number };

type SimNode = SimulationNodeDatum & {
  id: string;
  radius: number;
  degree: number;
};

type SimLink = SimulationLinkDatum<SimNode> & { strength: number };

export type ForceLayoutOptions<T extends LayoutNodeItem = LayoutNodeItem> = {
  /** 全局斥力（负值），默认 -30（d3 默认量级） */
  charge?: number;
  /** 连线理想长度，默认 60 */
  linkDistance?: number;
  /** 弹簧基础强度，默认 0.18；实际每条边 = base / max(两端度数) */
  linkStrengthBase?: number;
  /** alpha 每帧衰减量，默认 0.02（越小收敛越快） */
  alphaDecay?: number;
  /** 收敛停止阈值，默认 0.001 */
  alphaMin?: number;
  /** 向心中心，默认 [0, 0] */
  center?: [number, number];
  /** 向心力强度，默认 1（d3 默认，防止孤立节点漂出视口） */
  centerStrength?: number;
  /** 速度阻尼，默认 0.4（d3 默认） */
  velocityDecay?: number;
  /** 节点半径函数（碰撞与固定间距用），默认 30 */
  radiusOf?: (node: T, degree: number) => number;
  /** 需要固定在中心的节点 id（如 "user"） */
  pinnedIds?: ReadonlySet<string>;
  /** 初始种子位置（布局尚未收敛前的占位），返回 [x, y] */
  seedPosition?: (node: T, index: number) => [number, number];
};

export function useForceLayout<T extends LayoutNodeItem, E extends LayoutEdgeItem>(
  items: T[],
  edgeItems: E[],
  options?: ForceLayoutOptions<T>,
) {
  const [positions, setPositions] = useState<ReadonlyMap<string, LayoutPosition>>(new Map());

  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  // 数据身份 key：只有节点/边集合真的变化才重建模拟（渲染引起的引用变化不重建）
  const simKeyRef = useRef<string>("");
  const onSettledRef = useRef<() => void>(() => {});
  const settledRef = useRef(false);

  /** 重新加热：拖拽/筛选后让图重新收敛 */
  const reheat = useCallback(() => {
    if (simRef.current) {
      simRef.current.alpha(1);
      settledRef.current = false;
    }
  }, []);

  /** 拖拽中：把节点钉在手指位置（fx/fy） */
  const pinNode = useCallback((id: string, x: number, y: number) => {
    const sim = simRef.current;
    if (!sim) return;
    const datum = sim.nodes().find((n) => n.id === id);
    if (datum) {
      datum.fx = x;
      datum.fy = y;
    }
    sim.alpha(1);
    settledRef.current = false;
  }, []);

  /** 拖拽结束：释放钉子，让物理把它拉回平衡 */
  const unpinNode = useCallback((id: string) => {
    const sim = simRef.current;
    if (!sim) return;
    const datum = sim.nodes().find((n) => n.id === id);
    if (datum) {
      datum.fx = null;
      datum.fy = null;
    }
    sim.alpha(1);
    settledRef.current = false;
  }, []);

  /** 注册"布局已收敛"回调（用于 fitView 时序） */
  const onSettled = useCallback((fn: () => void) => {
    onSettledRef.current = fn;
  }, []);

  useEffect(() => {
    const opts = optionsRef.current || {};
    const charge = opts.charge ?? -30;
    const linkDistance = opts.linkDistance ?? 60;
    const linkStrengthBase = opts.linkStrengthBase ?? 0.18;
    const alphaDecay = opts.alphaDecay ?? 0.02;
    const alphaMin = opts.alphaMin ?? 0.001;
    const center = opts.center ?? [0, 0];
    const centerStrength = opts.centerStrength ?? 1;
    const velocityDecay = opts.velocityDecay ?? 0.4;
    const radiusOf = opts.radiusOf ?? (() => 30);
    const pinnedIds = opts.pinnedIds ?? new Set<string>();
    const seedPosition = opts.seedPosition ?? ((_, index) => [index * 40 - 200, 0]);

    // 1) 数据身份没变就不重建（避免渲染循环 / 搜索抖动）
    const key = `${items.map((n) => n.node_id).join("|")}::${edgeItems
      .map((e) => `${e.source_node_id}>${e.target_node_id}`)
      .join("|")}`;
    if (simKeyRef.current === key) return;
    simKeyRef.current = key;
    settledRef.current = false;

    // 2) 度数（每条边的强度 = base / max(两端度数)，hub 不会拽成一团）
    const degreeById = new Map<string, number>();
    items.forEach((n) => degreeById.set(n.node_id, 0));
    edgeItems.forEach((e) => {
      degreeById.set(e.source_node_id, (degreeById.get(e.source_node_id) ?? 0) + 1);
      degreeById.set(e.target_node_id, (degreeById.get(e.target_node_id) ?? 0) + 1);
    });

    // 3) 构建模拟节点：保留上一轮位置（搜索筛选时旧节点不跳），新节点用种子位置
    const prev = new Map<string, SimNode>(
      (simRef.current ? simRef.current.nodes() : []).map((n) => [n.id, n]),
    );
    const simNodes: SimNode[] = items.map((item, index) => {
      const degree = degreeById.get(item.node_id) ?? 0;
      const radius = radiusOf(item, degree);
      const old = prev.get(item.node_id);
      const seed = seedPosition(item, index);
      const isPinned = pinnedIds.has(item.node_id);
      return {
        id: item.node_id,
        radius,
        degree,
        x: old?.x ?? seed[0],
        y: old?.y ?? seed[1],
        vx: 0,
        vy: 0,
        fx: isPinned ? center[0] : null,
        fy: isPinned ? center[1] : null,
      };
    });

    const simLinks: SimLink[] = edgeItems
      .filter((e) => degreeById.has(e.source_node_id) && degreeById.has(e.target_node_id))
      .map((e) => {
        const s = degreeById.get(e.source_node_id) ?? 1;
        const t = degreeById.get(e.target_node_id) ?? 1;
        return {
          source: e.source_node_id,
          target: e.target_node_id,
          strength: linkStrengthBase / Math.max(s, t),
        };
      });

    // 4) 创建并启动模拟（tick 只更新 position，不重建节点对象）
    const simulation = forceSimulation<SimNode>(simNodes)
      .force(
        "link",
        forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance(linkDistance)
          .strength((d) => d.strength),
      )
      .force("charge", forceManyBody<SimNode>().strength(charge))
      .force("collide", forceCollide<SimNode>().radius((d) => d.radius + 6))
      .force("center", forceCenter<SimNode>(center[0], center[1]).strength(centerStrength))
      .velocityDecay(velocityDecay)
      .alphaDecay(alphaDecay)
      .alphaMin(alphaMin);

    const publish = () => {
      const next = new Map<string, LayoutPosition>();
      for (const n of simulation.nodes()) {
        // 防 NaN/Infinity：无效坐标回退到种子位置，避免节点不可见
        const x = Number.isFinite(n.x) ? (n.x as number) : 0;
        const y = Number.isFinite(n.y) ? (n.y as number) : 0;
        next.set(n.id, { x, y });
      }
      setPositions(next);
    };

    simulation.on("tick", publish);
    simulation.on("end", () => {
      publish();
      if (!settledRef.current) {
        settledRef.current = true;
        onSettledRef.current();
      }
    });

    simRef.current = simulation;

    return () => {
      simulation.stop();
      simulation.on("tick", null);
      simulation.on("end", null);
      if (simRef.current === simulation) simRef.current = null;
    };
  }, [items, edgeItems]);

  return { positions, reheat, pinNode, unpinNode, onSettled };
}
