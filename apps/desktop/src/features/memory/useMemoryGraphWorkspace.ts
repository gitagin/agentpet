import { useCallback, useEffect, useRef, useState } from "react";
import type { DesktopApi } from "../../services/desktopApi";
import { ApiError } from "../../services/apiClient";
import type {
  MemoryGraphActionRequest,
  MemoryGraphActionResponse,
  MemoryGraphClaimDetail,
  MemoryGraphEdgeDetail,
  MemoryGraphNodeDetail,
  MemoryGraphResponse,
} from "../../types";

export type MemoryGraphNodeItem = NonNullable<MemoryGraphResponse["nodes"]>[number];
export type MemoryGraphEdgeItem = NonNullable<MemoryGraphResponse["edges"]>[number];

export type MemoryGraphSelection = {
  nodeId: string | null;
  edgeId: string | null;
};

export type MemoryGraphWorkspaceState = {
  graph: MemoryGraphResponse | null;
  loading: boolean;
  error: string;
  selection: MemoryGraphSelection;
  nodeDetail: MemoryGraphNodeDetail | null;
  edgeDetail: MemoryGraphEdgeDetail | null;
  claimDetail: MemoryGraphClaimDetail | null;
  endpointDetails: Record<string, MemoryGraphNodeDetail>;
  detailLoading: boolean;
  detailError: string;
  actionBusy: boolean;
  actionError: string;
  actionMessage: string;
  rebuildBusy: boolean;
  rebuildMessage: string;
};

export function createMemoryIdempotencyKey(): string {
  const bytes = new Uint8Array(32);
  const cryptoApi = globalThis.crypto;
  if (cryptoApi?.getRandomValues) {
    cryptoApi.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function describeMemoryGraphError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "vault_not_bound") {
      return "还没有绑定本地资料库。先打开资料库完成绑定，再回来查看记忆图谱。";
    }
    if (error.code === "kuzu_unavailable" || error.code === "graph_projection_degraded") {
      return "关系图的加速投影暂不可用，已切换到本机可重建的基础数据。";
    }
    if (error.status === 503) {
      return "本机助手正在恢复。已有内容不会被删除，稍后可以重试。";
    }
    if (error.status === 409) {
      return "这条记忆刚被其他操作改变。请刷新后重新确认当前状态。";
    }
  }
  if (error instanceof TypeError || (error instanceof Error && /fetch|network|failed to fetch/i.test(error.message))) {
    return "本机助手暂时不可用。已加载的内容仍可查看，请稍后重试。";
  }
  return "记忆图谱暂时不可用。请重试；诊断信息保留在设置页。";
}

export function useMemoryGraphWorkspace(api: DesktopApi, onRefresh?: () => void): MemoryGraphWorkspaceState & {
  refresh: () => void;
  selectNode: (nodeId: string) => void;
  selectEdge: (edgeId: string) => void;
  clearSelection: () => void;
  applyAction: (request: MemoryGraphActionRequest) => Promise<MemoryGraphActionResponse | null>;
  rebuild: () => Promise<void>;
} {
  const [graph, setGraph] = useState<MemoryGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState<MemoryGraphSelection>({ nodeId: null, edgeId: null });
  const [nodeDetail, setNodeDetail] = useState<MemoryGraphNodeDetail | null>(null);
  const [edgeDetail, setEdgeDetail] = useState<MemoryGraphEdgeDetail | null>(null);
  const [claimDetail, setClaimDetail] = useState<MemoryGraphClaimDetail | null>(null);
  const [endpointDetails, setEndpointDetails] = useState<Record<string, MemoryGraphNodeDetail>>({});
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [rebuildBusy, setRebuildBusy] = useState(false);
  const [rebuildMessage, setRebuildMessage] = useState("");
  const selectionRequest = useRef(0);
  const graphRequest = useRef(0);

  const loadGraph = useCallback(
    async (signal?: AbortSignal) => {
      const requestId = graphRequest.current + 1;
      graphRequest.current = requestId;
      setLoading(true);
      setError("");
      try {
        const response = await api.getMemoryGraph(signal);
        if (graphRequest.current === requestId) {
          setGraph(response);
        }
      } catch (requestError) {
        if (!isAbortError(requestError) && graphRequest.current === requestId) {
          setError(describeMemoryGraphError(requestError));
        }
      } finally {
        if (graphRequest.current === requestId) {
          setLoading(false);
        }
      }
    },
    [api],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadGraph(controller.signal);
    return () => controller.abort();
  }, [loadGraph]);

  const clearDetails = useCallback(() => {
    setNodeDetail(null);
    setEdgeDetail(null);
    setClaimDetail(null);
    setEndpointDetails({});
    setDetailError("");
  }, []);

  const selectNode = useCallback(
    (nodeId: string) => {
      const requestId = selectionRequest.current + 1;
      selectionRequest.current = requestId;
      setSelection({ nodeId, edgeId: null });
      clearDetails();
      setDetailLoading(true);
      void (async () => {
        try {
          const detail = await api.getMemoryGraphNode(nodeId);
          if (selectionRequest.current !== requestId) {
            return;
          }
          setNodeDetail(detail);
          const claimId = detail.kind === "claim" ? detail.node_id : null;
          if (claimId) {
            try {
              setClaimDetail(await api.getMemoryGraphClaim(claimId));
            } catch (claimError) {
              if (selectionRequest.current === requestId) {
                setClaimDetail(null);
                setDetailError(`实体已加载，但事实详情暂不可用。${describeMemoryGraphError(claimError)}`);
              }
            }
          }
        } catch (requestError) {
          if (selectionRequest.current === requestId) {
            setDetailError(describeMemoryGraphError(requestError));
          }
        } finally {
          if (selectionRequest.current === requestId) {
            setDetailLoading(false);
          }
        }
      })();
    },
    [api, clearDetails],
  );

  const selectEdge = useCallback(
    (edgeId: string) => {
      const requestId = selectionRequest.current + 1;
      selectionRequest.current = requestId;
      const edge = graph?.edges?.find((item) => item.edge_id === edgeId);
      setSelection({ nodeId: null, edgeId });
      clearDetails();
      setDetailLoading(true);
      void (async () => {
        try {
          const detail = await api.getMemoryGraphEdge(edgeId);
          if (selectionRequest.current !== requestId) {
            return;
          }
          setEdgeDetail(detail);
          const endpoints = edge
            ? [edge.source_node_id, edge.target_node_id]
            : [detail.source_node_id, detail.target_node_id];
          const loaded = await Promise.all(
            endpoints.map(async (endpoint) => {
              try {
                return { endpoint, detail: await api.getMemoryGraphNode(endpoint), error: null };
              } catch (endpointError) {
                return { endpoint, detail: null, error: endpointError };
              }
            }),
          );
          if (selectionRequest.current === requestId) {
            setEndpointDetails(
              loaded.reduce<Record<string, MemoryGraphNodeDetail>>((result, item) => {
                if (item.detail) {
                  result[item.detail.node_id] = item.detail;
                }
                return result;
              }, {}),
            );
            if (loaded.some((item) => item.error)) {
              setDetailError("关系已加载，但至少一个端点详情暂不可用；证据链只展示已返回的部分。请重试。");
            }
          }
        } catch (requestError) {
          if (selectionRequest.current === requestId) {
            setDetailError(describeMemoryGraphError(requestError));
          }
        } finally {
          if (selectionRequest.current === requestId) {
            setDetailLoading(false);
          }
        }
      })();
    },
    [api, clearDetails, graph?.edges],
  );

  const clearSelection = useCallback(() => {
    selectionRequest.current += 1;
    setSelection({ nodeId: null, edgeId: null });
    clearDetails();
    setDetailLoading(false);
  }, [clearDetails]);

  const refresh = useCallback(() => {
    setActionError("");
    setActionMessage("");
    void loadGraph();
  }, [loadGraph]);

  const applyAction = useCallback(
    async (request: MemoryGraphActionRequest): Promise<MemoryGraphActionResponse | null> => {
      const targetId = selection.edgeId || selection.nodeId;
      if (!targetId) {
        return null;
      }
      setActionBusy(true);
      setActionError("");
      setActionMessage("");
      try {
        const idempotencyKey = createMemoryIdempotencyKey();
        let response: MemoryGraphActionResponse;
        if (selection.edgeId) {
          response = await api.applyMemoryGraphEdgeAction(selection.edgeId, request, idempotencyKey);
        } else if (nodeDetail?.kind === "claim") {
          const claimId = claimDetail?.claim_id ?? nodeDetail.node_id;
          if (!claimId) {
            throw new Error("记忆声明详情缺失，无法执行操作。");
          }
          response = await api.applyMemoryGraphClaimAction(
            claimId,
            request,
            idempotencyKey,
          );
        } else {
          response = await api.applyMemoryGraphNodeAction(selection.nodeId as string, request, idempotencyKey);
        }
        setActionMessage(response.replayed ? "已读取原操作回执，没有重复写入。" : response.message || "操作已记录。 ");
        await loadGraph();
        if (selection.edgeId) {
          selectEdge(selection.edgeId);
        } else if (selection.nodeId) {
          selectNode(selection.nodeId);
        }
        onRefresh?.();
        return response;
      } catch (requestError) {
        setActionError(describeMemoryGraphError(requestError));
        return null;
      } finally {
        setActionBusy(false);
      }
    },
    [api, claimDetail, loadGraph, nodeDetail, onRefresh, selectEdge, selectNode, selection.edgeId, selection.nodeId],
  );

  const rebuild = useCallback(async () => {
    setRebuildBusy(true);
    setRebuildMessage("");
    try {
      const response = await api.rebuildMemoryGraph(createMemoryIdempotencyKey());
      setRebuildMessage(
        response.degraded
          ? "派生图暂时降级，基础数据仍可用；稍后可以再次重建。"
          : `派生图已重建，${response.node_count} 个节点、${response.edge_count} 条关系。`,
      );
      await loadGraph();
    } catch (requestError) {
      setRebuildMessage(describeMemoryGraphError(requestError));
    } finally {
      setRebuildBusy(false);
    }
  }, [api, loadGraph]);

  return {
    graph,
    loading,
    error,
    selection,
    nodeDetail,
    edgeDetail,
    claimDetail,
    endpointDetails,
    detailLoading,
    detailError,
    actionBusy,
    actionError,
    actionMessage,
    rebuildBusy,
    rebuildMessage,
    refresh,
    selectNode,
    selectEdge,
    clearSelection,
    applyAction,
    rebuild,
  };
}
