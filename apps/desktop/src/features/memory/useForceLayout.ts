import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  forceCenter,
  forceCollide,
  forceSimulation,
  type Force,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";

/**
 * 力导向布局引擎（方案 A：React Flow 负责渲染，d3-force 只负责算坐标）。
 *
 * 关键：demo（E:\a 工作\llm-wiki-graph-demo\index.html）的弹簧力是线性的
 * f = k·(d - rest)，而 d3 内置 forceLink 会除以距离归一化成 f = k·(d - rest)/d，
 * 远距离时拉力饱和 → 拖主体时邻居拽不动、非连接点被斥力推得"越来越远"、松手大幅回弹。
 * 所以这里用自定义 forceLinearLink 复刻 demo 的线性弹簧，其余（斥力/向心/阻尼/衰减）
 * 沿用 d3 内置力，参数对齐 demo：
 *   charge 150（短程斥力，只有靠得很近才相斥，远距离不作用）/ linkDistance 100 / spring 0.18 /
 *   velocityDecay 0.55 / centerStrength 0.002 / alphaDecay 0.02
 *
 * 拖拽交互复刻 demo 的「拖主体 → 邻居跟着走」：
 *   - onNodeDragStart/onNodeDrag → pinNode：把节点钉在手指位置（fx/fy）+ 重新加热，弹簧把邻居拉过来；
 *   - onNodeDragStop → unpinNode：释放钉子 + 重新加热，让整图收敛到新平衡（节点轻微回弹属正常物理）。
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

type SimLink = SimulationLinkDatum<SimNode> & {
  strength: number;
  distance: number;
};

/**
 * 线性弹簧力：f = k·(d - rest)，方向沿两端连线。复刻 demo 手写引擎的弹簧，
 * 避免 d3 forceLink 的 /d 归一化导致远距离拉力饱和。
 */
function forceLinearLink(links: SimLink[]): Force<SimNode, SimLink> {
  const force: Force<SimNode, SimLink> = (alpha: number) => {
    for (const l of links) {
      const a = l.source as SimNode;
      const b = l.target as SimNode;
      const ax = a.x ?? 0;
      const ay = a.y ?? 0;
      const dx = (b.x ?? 0) - ax;
      const dy = (b.y ?? 0) - ay;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.001;
      const f = (d - l.distance) * l.strength * alpha;
      const fx = (dx / d) * f;
      const fy = (dy / d) * f;
      a.vx = (a.vx ?? 0) + fx;
      a.vy = (a.vy ?? 0) + fy;
      b.vx = (b.vx ?? 0) - fx;
      b.vy = (b.vy ?? 0) - fy;
    }
  };
  force.initialize = (nodes: SimNode[]) => {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    for (const l of links) {
      if (typeof l.source !== "object") l.source = byId.get(l.source as string) as SimNode;
      if (typeof l.target !== "object") l.target = byId.get(l.target as string) as SimNode;
    }
  };
  return force;
}

/**
 * 短程斥力：f = charge/d²，d² 有下限 clamp（24px，对齐 demo 的 D2_MIN）。
 * 远距离斥力随平方反比快速衰减到 0，因此"只有节点靠得很近才感受到一点斥力，否则原地不动"。
 * 这取代了 d3 forceManyBody 的长程斥力，避免拖动时把无关节点越推越远。
 */
function forceShortCharge(charge: number, distanceMin = 24): Force<SimNode, SimLink> {
  const d2Min = distanceMin * distanceMin;
  let nodes: SimNode[] = [];
  const force: Force<SimNode, SimLink> = (alpha: number) => {
    const n = nodes.length;
    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j];
        const dx = (a.x ?? 0) - (b.x ?? 0);
        const dy = (a.y ?? 0) - (b.y ?? 0);
        let d2 = dx * dx + dy * dy;
        if (d2 < d2Min) d2 = d2Min;
        const d = Math.sqrt(d2);
        const f = (charge / d2) * alpha;
        const fx = (dx / d) * f;
        const fy = (dy / d) * f;
        a.vx = (a.vx ?? 0) + fx;
        a.vy = (a.vy ?? 0) + fy;
        b.vx = (b.vx ?? 0) - fx;
        b.vy = (b.vy ?? 0) - fy;
      }
    }
  };
  force.initialize = (ns: SimNode[]) => {
    nodes = ns;
  };
  return force;
}

export type ForceLayoutOptions<T extends LayoutNodeItem = LayoutNodeItem> = {
  /** 短程斥力强度（正值 = 相斥），默认 150；反比平方衰减，只有近距离才感受到斥力 */
  charge?: number;
  /** 连线理想长度，默认 100（demo linkDist） */
  linkDistance?: number;
  /** 弹簧基础强度，默认 0.18（demo SPRING_BASE，线性弹簧无需放大）；实际每条边 = base / max(两端度数) */
  linkStrengthBase?: number;
  /** alpha 每帧衰减量，默认 0.02（demo 每帧 alpha *= 0.98） */
  alphaDecay?: number;
  /** 收敛停止阈值，默认 0.001 */
  alphaMin?: number;
  /** 向心中心，默认 [0, 0] */
  center?: [number, number];
  /** 向心力强度，默认 0.002（demo ck，过强会把邻居钉在原地且松手大幅回弹） */
  centerStrength?: number;
  /** 速度阻尼，默认 0.55（demo 每帧 0.55） */
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

  const onSettledRef = useRef<() => void>(() => {});
  const settledRef = useRef(false);
  // 重置信号：+1 强制重建模拟并回到种子布局
  const [resetSignal, setResetSignal] = useState(0);
  const resetRequestedRef = useRef(false);

  /** 拖拽中：把节点钉在手指位置（fx/fy），加热让邻居跟着弹簧走 */
  const pinNode = useCallback((id: string, x: number, y: number) => {
    const sim = simRef.current;
    if (!sim) return;
    // 拖动开始时清掉其它节点残留的钉子：防止上一次拖动/HMR 热更新残留 fx/fy，
    // 导致节点永久"固定死"（拖不动、也回不了平衡）。
    for (const n of sim.nodes()) {
      if (n.id !== id && (n.fx != null || n.fy != null)) {
        n.fx = null;
        n.fy = null;
      }
    }
    const datum = sim.nodes().find((n) => n.id === id);
    if (datum) {
      datum.fx = x;
      datum.fy = y;
    }
    sim.alpha(1).restart();
    settledRef.current = false;
  }, []);

  /** 拖拽结束：释放钉子 + 重新加热，让整图收敛到新平衡 */
  const unpinNode = useCallback((id: string) => {
    const sim = simRef.current;
    if (!sim) return;
    const datum = sim.nodes().find((n) => n.id === id);
    if (datum) {
      datum.fx = null;
      datum.fy = null;
    }
    sim.alpha(1).restart();
    settledRef.current = false;
  }, []);

  // 兜底：鼠标在画布外松开 / 窗口失焦时，React Flow 可能不触发 onNodeDragStop，
  // 若仍有节点被 fx/fy 钉住，会永久"固定死"（既拖不动也回不了平衡）。这里强制释放。
  // 注意：当前项目不再使用 pinnedIds 固定节点，因此释放所有被钉节点是安全的。
  useEffect(() => {
    const releaseAll = () => {
      const sim = simRef.current;
      if (!sim) return;
      let released = false;
      for (const n of sim.nodes()) {
        if (n.fx != null || n.fy != null) {
          n.fx = null;
          n.fy = null;
          released = true;
        }
      }
      if (released) {
        sim.alpha(1).restart();
        settledRef.current = false;
      }
    };
    window.addEventListener("pointerup", releaseAll);
    window.addEventListener("blur", releaseAll);
    return () => {
      window.removeEventListener("pointerup", releaseAll);
      window.removeEventListener("blur", releaseAll);
    };
  }, []);

  /** 重置布局：清空钉子，回到种子位置重新摊开 */
  const reset = useCallback(() => {
    resetRequestedRef.current = true;
    setResetSignal((n) => n + 1);
  }, []);

  /** 注册"布局已收敛"回调（用于 fitView 时序） */
  const onSettled = useCallback((fn: () => void) => {
    onSettledRef.current = fn;
  }, []);

  // 标量物理参数在 effect 外层解构并纳入依赖：参数变化（含 HMR 改了默认值）会触发
  // effect 重跑、sim 重建，避免"刷新后又回到旧参数/旧状态"。引用类型（center/radiusOf/
  // seedPosition/pinnedIds）每次 render 是新引用，放进依赖会无限重建，故仍在 effect 内读。
  const opts = optionsRef.current || {};
  const charge = opts.charge ?? 150;
  const linkDistance = opts.linkDistance ?? 100;
  const linkStrengthBase = opts.linkStrengthBase ?? 0.18;
  const alphaDecay = opts.alphaDecay ?? 0.02;
  const alphaMin = opts.alphaMin ?? 0.001;
  const centerStrength = opts.centerStrength ?? 0.002;
  const velocityDecay = opts.velocityDecay ?? 0.55;

  // 数据身份 key：只有节点/边集合真的变化才重建模拟。
  // 用它取代 items/edgeItems 数组引用作为 effect 依赖：刷新会让 graph 换成一个"内容相同的新数组引用"，
  // 若直接依赖数组引用，effect 会重跑——cleanup 先 stop 旧模拟，而身份没变又会提前 return，
  // 导致 simRef 一直是 null（表现为"刷新后点固定死、拖不动、邻居不跟随"）。
  const identityKey = useMemo(
    () =>
      `${items.map((n) => n.node_id).join("|")}::${edgeItems
        .map((e) => `${e.source_node_id}>${e.target_node_id}`)
        .join("|")}`,
    [items, edgeItems],
  );

  useEffect(() => {
    const center = opts.center ?? [0, 0];
    const radiusOf = opts.radiusOf ?? (() => 30);
    const pinnedIds = opts.pinnedIds ?? new Set<string>();
    const seedPosition = opts.seedPosition ?? ((_, index) => [index * 40 - 200, 0]);

    // 身份 + 物理参数 + 重置信号任一变化都会触发本 effect（见下方依赖数组），无需再在内部比对 key。
    const doReset = resetRequestedRef.current;
    resetRequestedRef.current = false;
    settledRef.current = false;

    // 2) 度数（每条边的强度 = base / max(两端度数)，hub 不会拽成一团）
    const degreeById = new Map<string, number>();
    items.forEach((n) => degreeById.set(n.node_id, 0));
    edgeItems.forEach((e) => {
      degreeById.set(e.source_node_id, (degreeById.get(e.source_node_id) ?? 0) + 1);
      degreeById.set(e.target_node_id, (degreeById.get(e.target_node_id) ?? 0) + 1);
    });

    // 3) 构建模拟节点：保留上一轮位置（搜索筛选时旧节点不跳），新节点/重置用种子位置
    const prev = doReset
      ? new Map<string, SimNode>()
      : new Map<string, SimNode>(
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
          distance: linkDistance,
        };
      });

    // 4) 创建并启动模拟（tick 只更新 position，不重建节点对象）
    const simulation = forceSimulation<SimNode>(simNodes)
      .force("link", forceLinearLink(simLinks))
      .force("charge", forceShortCharge(charge))
      .force("collide", forceCollide<SimNode>().radius((d) => d.radius + 6))
      .force("center", forceCenter<SimNode>(center[0], center[1]).strength(centerStrength))
      .velocityDecay(velocityDecay)
      .alphaDecay(alphaDecay)
      .alphaMin(alphaMin);

    const publish = () => {
      const next = new Map<string, LayoutPosition>();
      for (const n of simulation.nodes()) {
        // 防 NaN/Infinity：无效坐标回退到 0，避免节点不可见
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
      // 不置空 simRef：下一次 effect 重跑（数据真的变化）时还要读它的 nodes() 作为 prev
      // 来保留节点位置；置空会让 prev 读不到旧位置，节点在筛选/重建时跳回种子点。
    };
    // items/edgeItems 由 identityKey 等价表示，引用型 opts 有意在 effect 内读取
    // （见上方注释）；exhaustive-deps 无法从 identityKey 推导该等价性，显式豁免。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    identityKey,
    resetSignal,
    charge,
    linkDistance,
    linkStrengthBase,
    alphaDecay,
    alphaMin,
    centerStrength,
    velocityDecay,
  ]);

  return { positions, pinNode, unpinNode, reset, onSettled };
}
