import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import type {
  ChatContinuityProposal,
  ChatContinuitySignal,
  ChatMessage,
  ContinuityProposal,
  ContinuityStateResponse,
} from "../types";
import type { DesktopApi } from "../services/desktopApi";
import { describeError } from "../services/apiErrorMessages";
import { useLatestCallback } from "../hooks/useLatestCallback";
import type { Notice } from "./types";

type UseContinuityDomainOptions = {
  api: DesktopApi;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  onNotice: (notice: Notice | null) => void;
  onAgentActionsRefresh: () => void;
};

export function useContinuityDomain({
  api,
  setMessages,
  onNotice,
  onAgentActionsRefresh,
}: UseContinuityDomainOptions) {
  const [state, setState] = useState<ContinuityStateResponse | null>(null);
  const [proposals, setProposals] = useState<ContinuityProposal[]>([]);
  const [latestSignal, setLatestSignal] = useState<ChatContinuitySignal | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionIds, setActionIds] = useState<Set<string>>(() => new Set());

  async function load(options: { silent?: boolean; signal?: AbortSignal } = {}) {
    setLoading(true);
    if (!options.silent) {
      onNotice(null);
    }
    try {
      const [nextState, proposalsResponse] = await Promise.all([
        api.getContinuityState(options.signal),
        api.listContinuityProposals(options.signal),
      ]);
      setState(nextState);
      setProposals(proposalsResponse.proposals);
      if (!options.silent) {
        onNotice({
          tone: "success",
          message: `陪伴状态已刷新：${nextState.items.length} 个已确认状态，${proposalsResponse.proposals.length} 个待确认话题。`,
        });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (!options.silent) {
        onNotice({ tone: "error", message: describeError(error, "陪伴状态加载失败") });
      }
    } finally {
      setLoading(false);
    }
  }

  function upsertProposal(proposal: ContinuityProposal) {
    setProposals((current) => [
      proposal,
      ...current.filter((item) => item.proposal_id !== proposal.proposal_id),
    ]);
  }

  function upsertChatProposal(messageId: string, proposal: ChatContinuityProposal) {
    setMessages((current) => current.map((message) => {
      if (message.id !== messageId) {
        return message;
      }
      const rest = (message.continuity_proposals || []).filter(
        (item) => item.proposal_id !== proposal.proposal_id,
      );
      return { ...message, continuity_proposals: [proposal, ...rest] };
    }));
  }

  function upsertChatSignal(messageId: string, signal: ChatContinuitySignal) {
    setMessages((current) => current.map((message) =>
      message.id === messageId ? { ...message, continuity_signal: signal } : message,
    ));
  }

  async function actOnProposal(proposalId: string, action: "confirm" | "reject") {
    setActionIds((current) => new Set(current).add(proposalId));
    onNotice(null);
    try {
      const response = action === "confirm"
        ? await api.confirmContinuityProposal(proposalId)
        : await api.rejectContinuityProposal(proposalId, "用户在连续性审核面板中拒绝。");
      setProposals((current) => current.map((proposal) =>
        proposal.proposal_id === proposalId
          ? { ...proposal, status: response.status, updated_at: new Date().toISOString() }
          : proposal,
      ));
      await load({ silent: true });
      onAgentActionsRefresh();
      onNotice({
        tone: "success",
        message: action === "confirm"
          ? "已记住，下次可以自然接着聊；只进入本机陪伴状态，未写入本地文件。"
          : "已跳过，这个话题不会进入陪伴提示或角色状态。",
      });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "下次接着聊操作失败") });
    } finally {
      setActionIds((current) => {
        const next = new Set(current);
        next.delete(proposalId);
        return next;
      });
    }
  }

  const loadEvent = useLatestCallback(load);
  useEffect(() => {
    const abort = new AbortController();
    void loadEvent({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [loadEvent]);

  function reset() {
    setState(null);
    setProposals([]);
    setLatestSignal(null);
    setActionIds(new Set());
  }

  return {
    state,
    proposals,
    latestSignal,
    setLatestSignal,
    loading,
    actionIds,
    load,
    upsertProposal,
    upsertChatProposal,
    upsertChatSignal,
    actOnProposal,
    reset,
  };
}

export type ContinuityDomain = ReturnType<typeof useContinuityDomain>;
