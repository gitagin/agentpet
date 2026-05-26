import { useCallback, useEffect, useReducer } from "react";
import type { Dispatch, FormEvent, SetStateAction } from "react";
import type { DesktopApi } from "../../services/desktopApi";
import type {
  ChatMessage,
  ChatWikiProposal,
  DiagnosticsExportResponse,
  WikiIngestRequest,
} from "../../types";
import { describeError } from "../../services/apiErrorMessages";
import { mergeChatWikiProposal, isSupportedChatWikiProposalType } from "../../services/chatWikiProposals";
import type { LastIndexRun } from "../settings/settingsTypes";
import { formatTaskStatus } from "../tasks/taskReducer";
import { wikiArchiveCandidateChannelName, wikiArchiveCandidateStorageKey } from "./wikiConstants";
import { createInitialWikiState, wikiReducer } from "./wikiReducer";
import { loadWikiArchiveCandidate, saveWikiArchiveCandidate } from "./wikiStorage";
import type { ChatWikiApplyResponse, WikiArchiveCandidate, WikiWorkflowDraft } from "./wikiTypes";
import {
  buildWikiArchiveTitle,
  clampWikiMaxPages,
  emptyToNull,
  findLatestArchivableAssistantMessage,
  findQuestionForAssistantMessage,
  formatChatWikiApplyNotice,
  getChatWikiApplyNoticeTone,
  getWikiApplyIndexedPage,
  getWikiArchiveId,
  isKnowledgeBaseCitation,
  normalizeWikiArchiveCandidate,
  parseCompactList,
  toMemorySearchResultCitation,
  uniqueCompactList,
} from "./wikiUtils";

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type UseWikiOptions = {
  api: DesktopApi;
  conversationId: string | null;
  diagnostics: DiagnosticsExportResponse | null;
  messages: ChatMessage[];
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  vaultId: string | null;
  windowMode: string;
  onAgentActionsRefresh: () => void;
  onLastIndexRun: (run: LastIndexRun) => void;
  onNotice: (notice: Notice | null) => void;
};

export function useWiki({
  api,
  conversationId,
  diagnostics,
  messages,
  setMessages,
  vaultId,
  windowMode,
  onAgentActionsRefresh,
  onLastIndexRun,
  onNotice,
}: UseWikiOptions) {
  const [state, dispatch] = useReducer(wikiReducer, undefined, () => ({
    ...createInitialWikiState(),
    archiveCandidate: loadWikiArchiveCandidate(),
  }));
  const {
    approvedTargetsInput,
    applyResult,
    archiveCandidate,
    archiveHistory,
    archiveHistoryError,
    archiveHistoryStatus,
    companionContextReportError,
    companionContextReportStatus,
    companionContextReports,
    coreError,
    coreStatus,
    diagnosticsQueue,
    draft,
    indexStatus,
    lastWikiArchiveId,
    lintResult,
    linkInput,
    logStatus,
    openedArchive,
    openingArchiveId,
    preview,
    reviewForceRefresh,
    reviewResult,
    schemaStatus,
    tagInput,
    workflowAction,
  } = state;

  const loadArchiveHistory = useCallback(async (options: { silent?: boolean } = {}) => {
    dispatch({ type: "archiveHistoryStart" });
    if (!options.silent) {
      onNotice(null);
    }

    try {
      const response = await api.listWikiQueryArchives(20);
      dispatch({ type: "archiveHistorySuccess", archives: response.archives });
      if (!options.silent) {
        onNotice({
          tone: "success",
          message: `Wiki 查询归档历史已刷新：${response.archives.length} 条。`,
        });
      }
    } catch (error) {
      const message = describeError(error, "Wiki 查询归档历史刷新失败");
      dispatch({ type: "archiveHistoryError", message });
      if (!options.silent) {
        onNotice({ tone: "error", message });
      }
    }
  }, [api, onNotice]);

  const loadCoreStatus = useCallback(async (options: { silent?: boolean } = {}) => {
    dispatch({ type: "coreStatusStart" });
    if (!options.silent) {
      onNotice(null);
    }
    try {
      const [schema, index, log] = await Promise.all([
        api.getWikiSchema(),
        api.getWikiIndex(),
        api.getWikiLog(20),
      ]);
      dispatch({ type: "coreStatusSuccess", schema, index, log });
      if (!options.silent) {
        onNotice({
          tone: "success",
          message: `Wiki 核心状态已刷新：${index.entries.length} 条索引，${log.entries.length} 条日志。`,
        });
      }
    } catch (error) {
      const message = describeError(error, "Wiki 核心状态刷新失败");
      dispatch({ type: "coreStatusError", message });
      if (!options.silent) {
        onNotice({ tone: "error", message });
      }
    }
  }, [api, onNotice]);

  useEffect(() => {
    const candidateMessage = findLatestArchivableAssistantMessage(messages);
    if (!candidateMessage) {
      return;
    }
    const candidate: WikiArchiveCandidate = {
      conversation_id: conversationId,
      message: candidateMessage,
      question: findQuestionForAssistantMessage(messages, candidateMessage.id),
      updated_at: new Date().toISOString(),
    };
    dispatch({ type: "setArchiveCandidate", candidate });
    saveWikiArchiveCandidate(candidate);
  }, [conversationId, messages]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key !== wikiArchiveCandidateStorageKey) {
        return;
      }
      dispatch({ type: "setArchiveCandidate", candidate: loadWikiArchiveCandidate() });
    };
    window.addEventListener("storage", handleStorage);

    let channel: BroadcastChannel | null = null;
    if ("BroadcastChannel" in window) {
      channel = new BroadcastChannel(wikiArchiveCandidateChannelName);
      channel.onmessage = (event) => {
        const candidate = normalizeWikiArchiveCandidate(event.data);
        if (candidate) {
          dispatch({ type: "setArchiveCandidate", candidate });
        }
      };
    }

    return () => {
      window.removeEventListener("storage", handleStorage);
      channel?.close();
    };
  }, []);

  useEffect(() => {
    if (windowMode !== "control") {
      return;
    }
    void loadArchiveHistory({ silent: true });
    void loadCoreStatus({ silent: true });
  }, [loadArchiveHistory, loadCoreStatus, windowMode]);

  const setDraftPatch = useCallback((patch: Partial<WikiWorkflowDraft>) => {
    dispatch({ type: "updateDraft", patch });
  }, []);

  const upsertChatWikiProposal = useCallback((messageId: string, proposal: ChatWikiProposal) => {
    setMessages((current) =>
      current.map((message) => {
        if (message.id !== messageId) {
          return message;
        }
        const proposals = message.wiki_proposals || [];
        const existing = proposals.find((item) => item.id === proposal.id);
        const merged = mergeChatWikiProposal(existing, proposal);
        const rest = proposals.filter((item) => item.id !== proposal.id);
        return {
          ...message,
          wiki_proposals: [merged, ...rest],
        };
      }),
    );
  }, [setMessages]);

  const updateChatWikiProposal = useCallback((
    messageId: string,
    proposalId: string,
    updater: (proposal: ChatWikiProposal) => ChatWikiProposal,
  ) => {
    setMessages((current) =>
      current.map((message) =>
        message.id === messageId
          ? {
              ...message,
              wiki_proposals: (message.wiki_proposals || []).map((proposal) =>
                proposal.id === proposalId ? updater(proposal) : proposal,
              ),
            }
          : message,
      ),
    );
  }, [setMessages]);

  const confirmChatWikiProposal = useCallback((messageId: string, proposalId: string) => {
    updateChatWikiProposal(messageId, proposalId, (proposal) => ({
      ...proposal,
      state: "confirmed",
      error: null,
      updated_at: new Date().toISOString(),
    }));
    onNotice({ tone: "info", message: "Vault 维护确认项已本地确认；仍需点击写入才会修改 Markdown。" });
  }, [onNotice, updateChatWikiProposal]);

  const rejectChatWikiProposal = useCallback((messageId: string, proposalId: string) => {
    updateChatWikiProposal(messageId, proposalId, (proposal) => ({
      ...proposal,
      state: "rejected",
      error: null,
      updated_at: new Date().toISOString(),
    }));
    onNotice({ tone: "info", message: "Vault 维护确认项已拒绝，没有写入 Markdown。" });
  }, [onNotice, updateChatWikiProposal]);

  const toggleChatWikiProposalTarget = useCallback((
    messageId: string,
    proposalId: string,
    targetPath: string,
    selected: boolean,
  ) => {
    updateChatWikiProposal(messageId, proposalId, (proposal) => {
      const currentTargets = new Set(proposal.selected_targets);
      if (selected) {
        currentTargets.add(targetPath);
      } else {
        currentTargets.delete(targetPath);
      }
      return {
        ...proposal,
        selected_targets: Array.from(currentTargets),
        updated_at: new Date().toISOString(),
      };
    });
  }, [updateChatWikiProposal]);

  const applyConfirmedChatWikiProposal = useCallback(async (
    sourceMessage: ChatMessage | undefined,
    proposal: ChatWikiProposal,
    approvedTargets: string[],
  ): Promise<ChatWikiApplyResponse> => {
    if (proposal.proposal_type === "ingest") {
      if (!proposal.run_id || !proposal.review_id) {
        throw new Error("该 Vault 确认项缺少 run_id 或 review_id，不能安全写入。");
      }
      return api.applyWikiIngest({
        run_id: proposal.run_id,
        review_id: proposal.review_id,
        review_acknowledged: true,
        approved_targets: approvedTargets,
      });
    }

    const targetPath = approvedTargets[0] || proposal.target_paths[0] || proposal.recommended_targets[0] || null;
    if (proposal.proposal_type === "query_archive") {
      const citations = sourceMessage?.citations?.filter(isKnowledgeBaseCitation).map(toMemorySearchResultCitation) || [];
      return api.archiveWikiQuery({
        question: findQuestionForAssistantMessage(messages, sourceMessage?.id || "") || "已归档的 Wiki 查询",
        answer: sourceMessage?.content.trim() || proposal.markdown_preview || proposal.summary || proposal.title,
        citations,
        title: proposal.title,
        target_path: targetPath,
        tags: uniqueCompactList(["query-archive"]),
        agent_run_id: proposal.agent_run_id ?? sourceMessage?.agent_run_id ?? null,
        source_message_id: proposal.source_message_id || sourceMessage?.id || null,
      });
    }

    if (proposal.proposal_type === "synthesize") {
      return api.synthesizeWiki({
        title: proposal.title,
        content: proposal.markdown_preview || sourceMessage?.content || proposal.summary || proposal.title,
        source_paths: uniqueCompactList([...proposal.target_paths, ...proposal.recommended_targets]),
        target_path: targetPath,
        tags: uniqueCompactList(["synthesis"]),
      });
    }

    return api.runWikiLint({ write_report: proposal.write_report ?? true });
  }, [api, messages]);

  const applyChatWikiProposal = useCallback(async (messageId: string, proposalId: string) => {
    const sourceMessage = messages.find((message) => message.id === messageId);
    const proposal = sourceMessage?.wiki_proposals?.find((item) => item.id === proposalId);
    if (!proposal) {
      onNotice({ tone: "error", message: "没有在当前聊天消息中找到 Vault 维护确认项状态。" });
      return;
    }
    if (!isSupportedChatWikiProposalType(proposal.proposal_type)) {
      onNotice({ tone: "error", message: `该 Vault 确认项类型暂不支持从聊天中写入：${proposal.proposal_type}。` });
      return;
    }
    if (proposal.proposal_type === "ingest" && (!proposal.run_id || !proposal.review_id)) {
      onNotice({ tone: "error", message: "该 Vault 确认项缺少 run_id 或 review_id，不能安全写入。" });
      return;
    }
    if (proposal.state !== "confirmed" && proposal.state !== "failed") {
      onNotice({ tone: "error", message: "请先确认该 Vault 确认项，再执行写入。" });
      return;
    }

    const approvedTargets = uniqueCompactList(proposal.selected_targets);
    if (proposal.proposal_type === "ingest" && approvedTargets.length === 0) {
      onNotice({ tone: "error", message: "应用前至少选择一个目标页面。" });
      return;
    }

    updateChatWikiProposal(messageId, proposalId, (current) => ({
      ...current,
      state: "applying",
      error: null,
      updated_at: new Date().toISOString(),
    }));
    onNotice(null);
    try {
      const response = await applyConfirmedChatWikiProposal(sourceMessage, proposal, approvedTargets);
      updateChatWikiProposal(messageId, proposalId, (current) => ({
        ...current,
        state: "applied",
        error: null,
        apply_result: response,
        updated_at: new Date().toISOString(),
      }));
      dispatch({ type: "setChatWikiApplyResult", response });
      void loadCoreStatus({ silent: true });
      const indexedPage = getWikiApplyIndexedPage(response);
      if (indexedPage?.index_job_id) {
        onLastIndexRun({
          vaultId: vaultId || diagnostics?.vault.active_vault_id || "wiki",
          jobId: indexedPage.index_job_id,
          status: "status" in response ? response.status : indexedPage.status,
        });
      }
      if ("archive_id" in response && response.archive_id) {
        dispatch({ type: "setLastWikiArchiveId", archiveId: response.archive_id });
        await loadArchiveHistory({ silent: true });
      }
      onNotice({
        tone: getChatWikiApplyNoticeTone(response),
        message: formatChatWikiApplyNotice(response),
      });
      onAgentActionsRefresh();
    } catch (error) {
      const message = describeError(error, "Vault 确认项写入失败");
      updateChatWikiProposal(messageId, proposalId, (current) => ({
        ...current,
        state: "failed",
        error: message,
        updated_at: new Date().toISOString(),
      }));
      onNotice({ tone: "error", message });
    }
  }, [applyConfirmedChatWikiProposal, diagnostics, loadArchiveHistory, loadCoreStatus, messages, onAgentActionsRefresh, onLastIndexRun, onNotice, updateChatWikiProposal, vaultId]);

  const openArchive = useCallback(async (archiveId: string) => {
    const normalizedArchiveId = archiveId.trim();
    if (!normalizedArchiveId) {
      onNotice({ tone: "error", message: "缺少 Wiki 查询归档 ID。" });
      return;
    }

    dispatch({ type: "openArchiveStart", archiveId: normalizedArchiveId });
    onNotice(null);
    try {
      const detail = await api.getWikiQueryArchive(normalizedArchiveId);
      const detailArchiveId = getWikiArchiveId(detail) || normalizedArchiveId;
      const citationLinks = uniqueCompactList(detail.citations.map((citation) => citation.relative_path));
      dispatch({ type: "openArchiveSuccess", detail, archiveId: detailArchiveId, citationLinks });
      onNotice({
        tone: "success",
        message: `已打开 Wiki 查询归档：${detailArchiveId}。`,
      });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "Wiki 查询归档打开失败") });
    } finally {
      dispatch({ type: "openArchiveFinish" });
    }
  }, [api, onNotice]);

  const buildIngestRequest = useCallback((): WikiIngestRequest | null => {
    const title = draft.title.trim();
    const content = draft.content.trim();
    if (!title || !content) {
      onNotice({ tone: "error", message: "写入 Wiki 前需要同时填写标题和内容。" });
      return null;
    }

    return {
      title,
      content,
      source_type: draft.source_type?.trim() || "manual",
      source_uri: emptyToNull(draft.source_uri),
      tags: parseCompactList(tagInput),
      links: parseCompactList(linkInput),
      max_pages: clampWikiMaxPages(draft.max_pages),
    };
  }, [draft, linkInput, onNotice, tagInput]);

  const previewIngest = useCallback(async (event: FormEvent) => {
    event.preventDefault();
    const request = buildIngestRequest();
    if (!request) {
      return;
    }

    dispatch({ type: "workflowStart", action: "preview" });
    onNotice(null);
    try {
      const response = await api.previewWikiIngest(request);
      dispatch({ type: "previewIngestSuccess", preview: response });
      onNotice({
        tone: "success",
        message: `Wiki 写入预览 ${formatTaskStatus(response.status)}：计划更新 ${response.page_plans.length} 个页面。`,
      });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "Wiki 写入预览失败") });
    } finally {
      dispatch({ type: "workflowFinish" });
    }
  }, [api, buildIngestRequest, onNotice]);

  const applyIngest = useCallback(async () => {
    if (!preview) {
      onNotice({ tone: "error", message: "请先运行 Wiki 写入预览，再应用页面更新。" });
      return;
    }
    if (!preview.preview_token && preview.status !== "planned") {
      onNotice({ tone: "error", message: "当前 Wiki 预览缺少确认令牌，请重新运行预览。" });
      return;
    }

    const approvedTargets = parseCompactList(approvedTargetsInput);
    dispatch({ type: "workflowStart", action: "apply" });
    onNotice(null);
    try {
      const confirmedPreview = preview.preview_token
        ? await api.confirmWikiIngest({ preview_token: preview.preview_token, user_confirmed: true })
        : preview;
      const response = await api.applyWikiIngest({
        run_id: confirmedPreview.run_id,
        approved_targets: approvedTargets.length > 0 ? approvedTargets : confirmedPreview.page_plans.map((plan) => plan.target_path),
        review_id: reviewResult?.review_id ?? null,
        review_acknowledged: Boolean(reviewResult),
      });
      dispatch({ type: "applyIngestSuccess", preview: confirmedPreview, response });
      void loadCoreStatus({ silent: true });
      const firstIndexedPage = response.page_results.find((page) => page.index_job_id);
      onNotice({
        tone: response.status === "applied" ? "success" : "info",
        message: `Wiki 写入${formatTaskStatus(response.status)}：已写入 ${response.pages_written}/${response.page_results.length} 个页面。`,
      });
      if (firstIndexedPage?.index_job_id) {
        onLastIndexRun({
          vaultId: vaultId || diagnostics?.vault.active_vault_id || "wiki",
          jobId: firstIndexedPage.index_job_id,
          status: response.status,
        });
      }
      onAgentActionsRefresh();
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "Wiki 写入应用失败") });
    } finally {
      dispatch({ type: "workflowFinish" });
    }
  }, [api, approvedTargetsInput, diagnostics, loadCoreStatus, onAgentActionsRefresh, onLastIndexRun, onNotice, preview, reviewResult, vaultId]);

  const reviewIngest = useCallback(async () => {
    if (!preview) {
      onNotice({ tone: "error", message: "请先运行 Wiki 写入预览，再运行审查。" });
      return;
    }
    if (!preview.preview_token && preview.status !== "planned") {
      onNotice({ tone: "error", message: "当前 Wiki 预览缺少确认令牌，请重新运行预览。" });
      return;
    }

    dispatch({ type: "workflowStart", action: "review" });
    onNotice(null);
    try {
      const confirmedPreview = preview.preview_token
        ? await api.confirmWikiIngest({ preview_token: preview.preview_token, user_confirmed: true })
        : preview;
      const response = await api.reviewWikiIngest({
        run_id: confirmedPreview.run_id,
        reviewer_agent_id: "wiki_manager_agent",
        force_refresh: reviewForceRefresh,
      });
      dispatch({ type: "reviewIngestSuccess", preview: confirmedPreview, response });
      onNotice({
        tone: response.status === "failed" ? "error" : response.status === "model_not_configured" ? "info" : "success",
        message: `Wiki 审查${formatTaskStatus(response.status)}：${response.findings.length} 个发现，${response.recommended_targets.length} 个推荐目标。`,
      });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "Wiki 写入审查失败") });
    } finally {
      dispatch({ type: "workflowFinish" });
    }
  }, [api, onNotice, preview, reviewForceRefresh]);

  const useReviewRecommendedTargets = useCallback(() => {
    if (!reviewResult?.recommended_targets.length) {
      onNotice({ tone: "error", message: "当前审查结果没有推荐目标。" });
      return;
    }
    dispatch({ type: "setApprovedTargetsInput", value: reviewResult.recommended_targets.join(", ") });
    onNotice({
      tone: "info",
      message: `已填入 ${reviewResult.recommended_targets.length} 个推荐应用目标；应用前仍可手动调整。`,
    });
  }, [onNotice, reviewResult]);

  const archiveLatestQuery = useCallback(async () => {
    const localMessage = findLatestArchivableAssistantMessage(messages);
    const candidate = localMessage
      ? {
          conversation_id: conversationId,
          message: localMessage,
          question: findQuestionForAssistantMessage(messages, localMessage.id),
        }
      : archiveCandidate;
    const message = candidate?.message;
    const citations = message?.citations?.filter(isKnowledgeBaseCitation) || [];
    if (!message || citations.length === 0) {
      onNotice({
        tone: "error",
        message: "当前没有可归档的已完成助手回复；需要回复中包含知识库引用。",
      });
      return;
    }

    dispatch({ type: "workflowStart", action: "archive" });
    onNotice(null);
    try {
      const archiveCitations = citations.map(toMemorySearchResultCitation);
      const response = await api.archiveWikiQuery({
        question:
          candidate?.question ||
          findQuestionForAssistantMessage(messages, message.id) ||
          "已归档的 Wiki 查询",
        answer: message.content,
        citations: archiveCitations,
        title: draft.title.trim() || buildWikiArchiveTitle(citations),
        target_path: emptyToNull(draft.target_path),
        section: emptyToNull(draft.section),
        tags: parseCompactList(tagInput),
        agent_run_id: message.agent_run_id ?? null,
        source_message_id: message.id,
        allow_mixed_sources: draft.allow_mixed_sources,
      });
      dispatch({ type: "archiveLatestQuerySuccess", response });
      void loadCoreStatus({ silent: true });
      onNotice({
        tone: "success",
        message: `查询已归档${response.archive_id ? `：${response.archive_id}` : ""}，页面 ${response.page.relative_path}，引用 ${response.lint.normalized_citations.length} 条。`,
      });
      if (response.page.index_job_id) {
        onLastIndexRun({
          vaultId: vaultId || diagnostics?.vault.active_vault_id || "wiki",
          jobId: response.page.index_job_id,
          status: response.page.status,
        });
      }
      await loadArchiveHistory({ silent: true });
      onAgentActionsRefresh();
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "Wiki 查询归档失败") });
    } finally {
      dispatch({ type: "workflowFinish" });
    }
  }, [api, archiveCandidate, conversationId, diagnostics, draft, loadArchiveHistory, loadCoreStatus, messages, onAgentActionsRefresh, onLastIndexRun, onNotice, tagInput, vaultId]);

  const synthesize = useCallback(async () => {
    const title = draft.title.trim();
    const content = draft.content.trim();
    if (!title || !content) {
      onNotice({ tone: "error", message: "综合整理 Wiki 前需要同时填写标题和内容。" });
      return;
    }

    const sourcePaths = parseCompactList(linkInput);
    dispatch({ type: "workflowStart", action: "synthesize" });
    onNotice(null);
    try {
      const response = await api.synthesizeWiki({
        title,
        content,
        source_paths: sourcePaths,
        target_path: emptyToNull(draft.target_path),
        tags: parseCompactList(tagInput),
        links: sourcePaths,
      });
      dispatch({ type: "synthesizeSuccess", response });
      void loadCoreStatus({ silent: true });
      onNotice({
        tone: "success",
        message: `Wiki 综合整理已写入：${response.page.relative_path}。`,
      });
      if (response.page.index_job_id) {
        onLastIndexRun({
          vaultId: vaultId || diagnostics?.vault.active_vault_id || "wiki",
          jobId: response.page.index_job_id,
          status: response.page.status,
        });
      }
      onAgentActionsRefresh();
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "Wiki 综合整理失败") });
    } finally {
      dispatch({ type: "workflowFinish" });
    }
  }, [api, diagnostics, draft, linkInput, loadCoreStatus, onAgentActionsRefresh, onLastIndexRun, onNotice, tagInput, vaultId]);

  const runLint = useCallback(async () => {
    dispatch({ type: "workflowStart", action: "lint" });
    onNotice(null);
    try {
      const response = await api.runWikiLint({ write_report: draft.write_report });
      dispatch({ type: "lintSuccess", response });
      void loadCoreStatus({ silent: true });
      onNotice({
        tone: response.issues.length > 0 ? "info" : "success",
        message: `Wiki 检查完成：${response.summary.pages ?? 0} 个页面，${response.issues.length} 个问题。`,
      });
      onAgentActionsRefresh();
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "Wiki 检查运行失败") });
    } finally {
      dispatch({ type: "workflowFinish" });
    }
  }, [api, draft.write_report, loadCoreStatus, onAgentActionsRefresh, onNotice]);

  const loadDiagnosticsQueue = useCallback(async () => {
    dispatch({ type: "diagnosticsStart" });
    onNotice(null);
    try {
      const [queue, reports] = await Promise.all([
        api.getWikiDiagnosticQueue({ limit: 12, include_repair_preview: true }),
        api.listCompanionContextReports(8),
      ]);
      dispatch({ type: "diagnosticsSuccess", queue, reports: reports.reports });
      onNotice({
        tone: "success",
        message: `只读诊断已刷新：${queue.items.length} 个 Wiki 待诊断项，${reports.reports.length} 条 Companion 上下文报告。`,
      });
    } catch (error) {
      const message = describeError(error, "只读诊断刷新失败");
      dispatch({ type: "diagnosticsError", message });
      onNotice({ tone: "error", message });
    } finally {
      dispatch({ type: "workflowFinish" });
    }
  }, [api, onNotice]);

  const resetWikiState = useCallback(() => {
    dispatch({ type: "reset" });
  }, []);

  const latestLocalArchivableAssistantMessage = findLatestArchivableAssistantMessage(messages);
  const latestArchiveMessage = latestLocalArchivableAssistantMessage || archiveCandidate?.message;
  const latestKnowledgeCitations = latestArchiveMessage?.citations?.filter(isKnowledgeBaseCitation) || [];
  const lintIssueCount = lintResult?.summary.issues ?? lintResult?.issues.length ?? 0;
  const archiveHistoryLoading = archiveHistoryStatus === "loading";
  const archiveHistorySummary =
    archiveHistoryStatus === "error"
      ? archiveHistoryError
      : archiveHistoryLoading
        ? "加载中"
        : archiveHistory.length > 0
          ? `${archiveHistory.length} 条近期归档`
          : "暂无归档";

  return {
    approvedTargetsInput,
    applyChatWikiProposal,
    applyIngest,
    applyResult,
    archiveHistory,
    archiveHistoryError,
    archiveHistoryLoading,
    archiveHistoryStatus,
    archiveHistorySummary,
    archiveLatestQuery,
    companionContextReportError,
    companionContextReportStatus,
    companionContextReports,
    confirmChatWikiProposal,
    coreError,
    coreStatus,
    diagnosticsQueue,
    draft,
    indexStatus,
    lastWikiArchiveId,
    latestArchiveMessage,
    latestKnowledgeCitationCount: latestKnowledgeCitations.length,
    lintIssueCount,
    lintResult,
    linkInput,
    loadArchiveHistory,
    loadCoreStatus,
    loadDiagnosticsQueue,
    logStatus,
    onDraftChange: setDraftPatch,
    openArchive,
    openedArchive,
    openingArchiveId,
    preview,
    previewIngest,
    rejectChatWikiProposal,
    resetWikiState,
    reviewForceRefresh,
    reviewIngest,
    reviewResult,
    runLint,
    schemaStatus,
    setApprovedTargetsInput: (value: string) => dispatch({ type: "setApprovedTargetsInput", value }),
    setLinkInput: (value: string) => dispatch({ type: "setLinkInput", value }),
    setReviewForceRefresh: (value: boolean) => dispatch({ type: "setReviewForceRefresh", value }),
    setTagInput: (value: string) => dispatch({ type: "setTagInput", value }),
    synthesize,
    tagInput,
    toggleChatWikiProposalTarget,
    upsertChatWikiProposal,
    useReviewRecommendedTargets,
    workflowAction,
  };
}
