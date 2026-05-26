import type { FormEvent } from "react";
import { useCallback, useReducer } from "react";
import { describeError } from "../../services/apiErrorMessages";
import type { DesktopApi } from "../../services/desktopApi";
import type { MemoryProposal, MemoryProposalDraft } from "../../types";
import { memoryReducer, createInitialMemoryState } from "./memoryReducer";
import { defaultMemoryTargetPath } from "./memoryConstants";
import { normalizeMemoryProposalListItem, normalizeMemoryProposalPayload } from "./memoryUtils";

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type UseMemoryOptions = {
  api: DesktopApi;
  onNotice: (notice: Notice | null) => void;
  getSearchEmptyNotice: (query: string) => string;
  onAgentActionsRefresh?: () => void;
};

export function useMemory({ api, onNotice, getSearchEmptyNotice, onAgentActionsRefresh }: UseMemoryOptions) {
  const [state, dispatch] = useReducer(memoryReducer, undefined, createInitialMemoryState);

  const setSearchQuery = useCallback((searchQuery: string) => {
    dispatch({ type: "setSearchQuery", searchQuery });
  }, []);

  const updateProposalDraft = useCallback((patch: Partial<MemoryProposalDraft>) => {
    dispatch({ type: "updateProposalDraft", patch });
  }, []);

  const runMemorySearch = useCallback(async (event?: FormEvent) => {
    event?.preventDefault();
    const query = state.searchQuery.trim();
    if (!query) {
      return;
    }

    onNotice(null);
    dispatch({ type: "startSearch", query });
    try {
      const response = await api.searchMemory(query);
      dispatch({ type: "searchSuccess", results: response.results });
      if (response.results.length === 0) {
        onNotice({ tone: "info", message: getSearchEmptyNotice(query) });
      }
    } catch (error) {
      dispatch({ type: "searchError" });
      onNotice({ tone: "error", message: describeError(error, "记忆搜索失败") });
    }
  }, [api, getSearchEmptyNotice, onNotice, state.searchQuery]);

  const createProposal = useCallback(async (event?: FormEvent) => {
    event?.preventDefault();
    const draft = state.proposalDraft;
    if (!draft.content.trim() || !draft.target_path.trim()) {
      return;
    }

    onNotice(null);
    const optimisticId = crypto.randomUUID();
    dispatch({
      type: "createProposalOptimistic",
      proposal: {
        ...draft,
        proposal_id: optimisticId,
        status: "pending",
        preview_markdown: draft.content,
      },
    });

    try {
      const response = await api.createMemoryProposal(draft);
      dispatch({
        type: "createProposalSuccess",
        optimisticId,
        proposal: {
          ...draft,
          proposal_id: response.proposal_id,
          status: response.status,
          preview_markdown: response.preview_markdown,
          target_path: response.target_path,
          diff: response.diff || undefined,
          target_content_hash: response.target_content_hash,
        },
      });
      onNotice({ tone: "success", message: "记忆整理项已创建，等待确认写入。" });
      onAgentActionsRefresh?.();
    } catch (error) {
      const message = describeError(error, "记忆整理项创建失败");
      dispatch({ type: "createProposalError", optimisticId, error: message });
      onNotice({ tone: "error", message });
    }
  }, [api, onAgentActionsRefresh, onNotice, state.proposalDraft]);

  const actOnProposal = useCallback(async (proposalId: string, action: "confirm" | "reject") => {
    dispatch({ type: "startProposalAction", proposalId });
    onNotice(null);
    try {
      const response =
        action === "confirm"
          ? await api.confirmMemoryProposal(proposalId)
          : await api.rejectMemoryProposal(proposalId, "用户在桌面审核面板中拒绝。");
      dispatch({
        type: "updateProposalStatus",
        proposalId,
        status: response.status as MemoryProposal["status"],
        writtenPath: response.written_path,
      });
      onNotice({
        tone: "success",
        message:
          action === "confirm"
            ? `记忆整理项已确认写入${response.written_path ? `：${response.written_path}` : ""}${response.index_job_id ? `；索引任务 ${response.index_job_id}` : ""}。`
            : "记忆整理项已拒绝，目标 Markdown 未写入。",
      });
      onAgentActionsRefresh?.();
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "记忆整理项操作失败") });
    } finally {
      dispatch({ type: "finishProposalAction", proposalId });
    }
  }, [api, onAgentActionsRefresh, onNotice]);

  const loadPendingProposals = useCallback(async (options: { silent?: boolean; signal?: AbortSignal } = {}) => {
    dispatch({ type: "setLoadingProposals", loading: true });
    if (!options.silent) {
      onNotice(null);
    }
    try {
      const response = await api.listMemoryProposals(options.signal);
      dispatch({ type: "setProposals", proposals: response.proposals.map(normalizeMemoryProposalListItem) });
      if (!options.silent) {
        onNotice({ tone: "success", message: `已加载 ${response.proposals.length} 条待确认记忆整理项。` });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (!options.silent) {
        onNotice({ tone: "error", message: describeError(error, "加载待确认记忆整理项失败") });
      }
    } finally {
      dispatch({ type: "setLoadingProposals", loading: false });
    }
  }, [api, onNotice]);

  const upsertProposalFromPayload = useCallback((proposalId: string, payload: Record<string, unknown> | null) => {
    dispatch({ type: "upsertProposal", proposal: normalizeMemoryProposalPayload(proposalId, payload) });
  }, []);

  const resetMemoryState = useCallback(() => {
    dispatch({ type: "reset" });
  }, []);

  return {
    actOnProposal,
    createProposal,
    defaultMemoryTargetPath,
    lastSearchQuery: state.lastSearchQuery,
    loadingProposals: state.loadingProposals,
    loadPendingProposals,
    proposalActionIds: state.proposalActionIds,
    proposalDraft: state.proposalDraft,
    proposals: state.proposals,
    resetMemoryState,
    runMemorySearch,
    searchQuery: state.searchQuery,
    searchResults: state.searchResults,
    searchStatus: state.searchStatus,
    setSearchQuery,
    updateProposalDraft,
    upsertProposalFromPayload,
  };
}
