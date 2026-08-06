import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import type {
  AgentAction,
  AgentCheckpointSummary,
  ChatMessage,
  DesktopVaultRevealMode,
} from "../types";
import type { DesktopApi } from "../services/desktopApi";
import type { DesktopWindowMode } from "../features/desktop/desktopWindowModes";
import { agentActivitySortKey } from "../services/agentActivity";
import { describeError } from "../services/apiErrorMessages";
import type { ConfirmationDialogRequest } from "../components/ConfirmationDialog";
import { useLatestCallback } from "../hooks/useLatestCallback";
import type { AsyncStatus, Notice } from "./types";

const AGENT_ACTION_ACTIVITY_LIMIT = 200;

type UseAgentActivityDomainOptions = {
  api: DesktopApi;
  conversationId: string | null;
  sidecarConnected: boolean;
  streaming: boolean;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setWindowMode: (mode: DesktopWindowMode) => void;
  onNotice: (notice: Notice | null) => void;
  confirm: (request: ConfirmationDialogRequest) => Promise<boolean>;
};

export function useAgentActivityDomain({
  api,
  conversationId,
  sidecarConnected,
  streaming,
  setMessages,
  setWindowMode,
  onNotice,
  confirm,
}: UseAgentActivityDomainOptions) {
  const [actions, setActions] = useState<AgentAction[]>([]);
  const [status, setStatus] = useState<AsyncStatus>("idle");
  const [error, setError] = useState("");
  const [pendingCheckpoints, setPendingCheckpoints] = useState<AgentCheckpointSummary[]>([]);
  const [decidingCheckpointIds, setDecidingCheckpointIds] = useState<Set<string>>(() => new Set());
  const [revertingActionIds, setRevertingActionIds] = useState<Set<string>>(() => new Set());

  function upsert(action: AgentAction) {
    setActions((current) => [action, ...current.filter((item) => item.action_id !== action.action_id)]
      .sort((left, right) =>
        agentActivitySortKey(right.updated_at || right.created_at) -
        agentActivitySortKey(left.updated_at || left.created_at),
      )
      .slice(0, AGENT_ACTION_ACTIVITY_LIMIT));
  }

  async function load(options: { silent?: boolean; signal?: AbortSignal } = {}) {
    setStatus("loading");
    setError("");
    if (!options.silent) {
      onNotice(null);
    }
    try {
      const response = await api.listAgentActions(AGENT_ACTION_ACTIVITY_LIMIT, null, options.signal);
      setActions(response.actions);
      setStatus(response.actions.length > 0 ? "success" : "empty");
      if (!options.silent) {
        onNotice({ tone: "success", message: `已刷新 ${response.actions.length} 条最近自动整理活动。` });
      }
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
      const message = describeError(requestError, "最近自动整理活动加载失败");
      setStatus("error");
      setError(message);
      if (!options.silent) {
        onNotice({ tone: "error", message });
      }
    }
  }

  async function loadPendingCheckpoints(signal?: AbortSignal) {
    try {
      setPendingCheckpoints(await api.listPendingCheckpoints(conversationId ?? undefined, signal));
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
    }
  }

  async function decideCheckpoint(checkpoint: AgentCheckpointSummary, decision: "approved" | "rejected") {
    setDecidingCheckpointIds((current) => new Set(current).add(checkpoint.checkpoint_id));
    onNotice(null);
    try {
      const response = await api.decideCheckpoint(checkpoint, decision);
      setPendingCheckpoints((current) => current.filter(
        (item) => item.checkpoint_id !== checkpoint.checkpoint_id,
      ));
      onNotice({
        tone: response.status === "completed" || response.status === "rejected" ? "success" : "info",
        message: response.effect_applied
          ? "已批准并完成这次操作。"
          : response.status === "rejected"
            ? "已拒绝，这次操作没有执行。"
            : "确认结果已记录。",
      });
      void load({ silent: true });
    } catch (requestError) {
      onNotice({ tone: "error", message: describeError(requestError, "确认请求处理失败") });
    } finally {
      setDecidingCheckpointIds((current) => {
        const next = new Set(current);
        next.delete(checkpoint.checkpoint_id);
        return next;
      });
    }
  }

  async function loadMemoryReceipts(messageId: string, agentRunId: string, signal?: AbortSignal) {
    try {
      const response = await api.getMemoryReceipts(agentRunId, signal);
      if (response.items.length > 0) {
        setMessages((current) => current.map((message) =>
          message.id === messageId ? { ...message, memory_receipts: response.items } : message,
        ));
      }
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
    }
  }

  async function revert(action: AgentAction) {
    const confirmed = await confirm({
      title: `确认撤回“${action.title}”吗？`,
      message: "撤回会通过本机服务恢复这次整理前的文件快照，并留下新的活动记录。",
      details: action.target_paths.length > 0 ? [`影响文件：${action.target_paths.join("、")}`] : undefined,
      confirmLabel: "确认撤回",
    });
    if (!confirmed) {
      return;
    }

    setRevertingActionIds((current) => new Set(current).add(action.action_id));
    onNotice(null);
    try {
      const response = await api.revertAgentAction(action.action_id);
      setActions((current) => {
        const updates = new Map<string, AgentAction>([
          [response.action.action_id, response.action],
          [response.reverted.action_id, response.reverted],
        ]);
        return [...updates.values(), ...current.filter((item) => !updates.has(item.action_id))]
          .sort((left, right) =>
            agentActivitySortKey(right.updated_at || right.created_at) -
            agentActivitySortKey(left.updated_at || left.created_at),
          )
          .slice(0, AGENT_ACTION_ACTIVITY_LIMIT);
      });
      setMessages((current) => current.map((message) => {
        const existing = message.agent_actions || [];
        if (!existing.some((item) => item.action_id === response.action.action_id)) {
          return message;
        }
        const updated = existing.map((item) =>
          item.action_id === response.action.action_id ? response.action : item,
        );
        return {
          ...message,
          agent_actions: updated.some((item) => item.action_id === response.reverted.action_id)
            ? updated
            : [...updated, response.reverted],
        };
      }));
      onNotice({
        tone: "success",
        message: `已撤回：${response.action.title}。记忆页会显示新的撤回记录，关联文件已按本机快照同步。`,
      });
      void load({ silent: true });
    } catch (requestError) {
      onNotice({ tone: "error", message: describeError(requestError, "撤回自动整理活动失败") });
    } finally {
      setRevertingActionIds((current) => {
        const next = new Set(current);
        next.delete(action.action_id);
        return next;
      });
    }
  }

  async function revealTarget(relativePath: string, mode: DesktopVaultRevealMode) {
    if (!window.agentDesktop?.revealVaultPath) {
      onNotice({ tone: "info", message: "当前浏览器预览不能打开本地保存文件；请在 Electron 桌面端使用该操作。" });
      return;
    }
    try {
      const result = await window.agentDesktop.revealVaultPath(relativePath, mode);
      if (result.status === "opened" || result.status === "shown") {
        onNotice({
          tone: "success",
          message: result.status === "opened"
            ? `已打开 ${result.relative_path}。`
            : `已在文件夹中显示 ${result.relative_path}。`,
        });
        return;
      }
      onNotice({ tone: "error", message: `无法打开保存目标：${result.reason || result.status}。` });
    } catch (requestError) {
      onNotice({ tone: "error", message: describeError(requestError, "打开保存目标失败") });
    }
  }

  function openArtifact(mode: "memory" | "world", relativePath?: string) {
    setWindowMode(mode);
    if (relativePath) {
      void revealTarget(relativePath, "open");
    }
  }

  const loadEvent = useLatestCallback(load);
  const loadCheckpointsEvent = useLatestCallback(loadPendingCheckpoints);
  useEffect(() => {
    const abort = new AbortController();
    void loadEvent({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [loadEvent]);

  useEffect(() => {
    if (!sidecarConnected || streaming) {
      return;
    }
    const abort = new AbortController();
    void loadCheckpointsEvent(abort.signal);
    return () => abort.abort();
  }, [conversationId, loadCheckpointsEvent, sidecarConnected, streaming]);

  function reset(includeCheckpoints = true) {
    setActions([]);
    setStatus("idle");
    setError("");
    setRevertingActionIds(new Set());
    if (includeCheckpoints) {
      setPendingCheckpoints([]);
      setDecidingCheckpointIds(new Set());
    }
  }

  return {
    actions,
    status,
    error,
    pendingCheckpoints,
    decidingCheckpointIds,
    revertingActionIds,
    upsert,
    load,
    loadMemoryReceipts,
    decideCheckpoint,
    revert,
    revealTarget,
    openArtifact,
    reset,
  };
}

export type AgentActivityDomain = ReturnType<typeof useAgentActivityDomain>;
