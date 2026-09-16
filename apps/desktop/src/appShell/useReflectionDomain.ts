import { useEffect, useRef, useState } from "react";
import type { ReflectionProposal } from "../types";
import type { DesktopApi } from "../services/desktopApi";
import { describeError } from "../services/apiErrorMessages";
import { useLatestCallback } from "../hooks/useLatestCallback";
import type { Notice } from "./types";

// 建议由后台任务在回复之后异步产生,没有推送通道,所以用低速轮询兜住时序:
// 只靠"回复完成"那一刻拉一次,很可能刚好早于建议落库。
const REFLECTION_POLL_INTERVAL_MS = 20000;

type UseReflectionDomainOptions = {
  api: DesktopApi;
  enabled: boolean;
  onNotice: (notice: Notice | null) => void;
  onAgentActionsRefresh: () => void;
};

/**
 * Review queue for background reflection suggestions.
 *
 * Suggestions are proposals, not effects: they sit in the queue until the user
 * accepts or dismisses them. Accepting is what writes memory, so the panel
 * never claims anything was remembered before the request succeeded.
 *
 * A failed load is surfaced as `error` even when the poll is silent: an empty
 * queue and a broken queue must not look the same.
 */
export function useReflectionDomain({
  api,
  enabled,
  onNotice,
  onAgentActionsRefresh,
}: UseReflectionDomainOptions) {
  const [proposals, setProposals] = useState<ReflectionProposal[]>([]);
  // 初始即为 true:第一次结果回来之前不能显示"没有建议",否则空态会撒谎。
  // 轮询与刷新不再改动它,因此空队列也不会每次轮询都闪一下加载文案。
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionIds, setActionIds] = useState<Set<string>>(() => new Set());
  // 轮询与用户操作会并发发请求:只让最后发起的那次写状态,否则一个更早的轮询响应
  // 会把刚被采纳/忽略的卡片写回面板(点一下"已处理"又回来,再点就撞后端状态机)。
  const loadSequenceRef = useRef(0);

  async function load(options: { silent?: boolean; signal?: AbortSignal } = {}) {
    const sequence = loadSequenceRef.current + 1;
    loadSequenceRef.current = sequence;
    try {
      // "attention" = 还需要用户处理的建议(待决定 + 系统没做成、还能重试的)。
      // 只查 pending 会让一次暂态失败的建议从面板上永久消失。
      const response = await api.listReflectionProposals("attention", options.signal);
      if (sequence !== loadSequenceRef.current) {
        return;
      }
      setProposals(response.proposals);
      setError(null);
    } catch (loadError) {
      if (loadError instanceof DOMException && loadError.name === "AbortError") {
        return;
      }
      if (sequence !== loadSequenceRef.current) {
        return;
      }
      const message = describeError(loadError, "建议加载失败");
      setError(message);
      if (!options.silent) {
        onNotice({ tone: "error", message });
      }
    } finally {
      if (sequence === loadSequenceRef.current) {
        setLoading(false);
      }
    }
  }

  async function accept(proposalId: string) {
    const acceptedProposal = proposals.find((item) => item.proposal_id === proposalId);
    const isWikiSummary = acceptedProposal?.proposal_kind === "wiki_summary"
      && acceptedProposal?.action_type === "wiki.answer_summary.write";
    setActionIds((current) => new Set(current).add(proposalId));
    onNotice(null);
    try {
      await api.confirmReflectionProposal(proposalId);
      setProposals((current) => current.filter((item) => item.proposal_id !== proposalId));
      await load({ silent: true });
      onAgentActionsRefresh();
      onNotice({
        tone: "success",
        message: isWikiSummary
          ? "已写入 Wiki 摘要。"
          : "已记下这条内容，并写入待整理的记忆。",
      });
    } catch (actionError) {
      onNotice({ tone: "error", message: describeError(actionError, "采纳建议失败") });
    } finally {
      setActionIds((current) => {
        const next = new Set(current);
        next.delete(proposalId);
        return next;
      });
    }
  }

  async function dismiss(proposalId: string) {
    setActionIds((current) => new Set(current).add(proposalId));
    onNotice(null);
    try {
      await api.rejectReflectionProposal(proposalId, "用户在建议面板中忽略。");
      setProposals((current) => current.filter((item) => item.proposal_id !== proposalId));
      await load({ silent: true });
      // 不要说成"不会再提这个话题":这个队列不参与生成,能做到的只是不再建议记录它。
      onNotice({ tone: "success", message: "已标记为不用记，之后不会再建议记录这条内容。" });
    } catch (actionError) {
      onNotice({ tone: "error", message: describeError(actionError, "忽略建议失败") });
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
    if (!enabled) {
      // 未连接时不存在"加载中":不把 loading 落下来,面板会永远停在加载文案上。
      // 同时作废在途请求,免得断开前的响应回来后重新填满列表。
      loadSequenceRef.current += 1;
      setLoading(false);
      return;
    }
    // 首次结果回来之前显示加载中,避免空态用"没有建议"撒谎。
    setLoading(true);
    const abort = new AbortController();
    void loadEvent({ silent: true, signal: abort.signal });
    const intervalId = window.setInterval(() => {
      void loadEvent({ silent: true });
    }, REFLECTION_POLL_INTERVAL_MS);
    return () => {
      abort.abort();
      window.clearInterval(intervalId);
    };
  }, [loadEvent, enabled]);

  function reset() {
    // 作废在途请求,否则重置后回来的旧响应会把列表重新填上。
    loadSequenceRef.current += 1;
    setProposals([]);
    setActionIds(new Set());
    setError(null);
  }

  return {
    proposals,
    loading,
    error,
    actionIds,
    load,
    accept,
    dismiss,
    reset,
  };
}

export type ReflectionDomain = ReturnType<typeof useReflectionDomain>;
