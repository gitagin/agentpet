import type {
  CompanionRetrievalReport,
  WikiDiagnosticQueueResponse,
  WikiIndexResponse,
  WikiIngestApplyResponse,
  WikiIngestPreviewResponse,
  WikiIngestReviewResponse,
  WikiLintRunResponse,
  WikiLogResponse,
  WikiQueryArchiveDetailResponse,
  WikiQueryArchiveHistoryItem,
  WikiQueryArchiveResponse,
  WikiSchemaStatus,
  WikiSynthesizeResponse,
} from "../../types";
import type { WikiArchiveCandidate, WikiAsyncStatus, WikiWorkflowAction, WikiWorkflowDraft } from "./wikiTypes";

export const initialWikiDraft: WikiWorkflowDraft = {
  title: "",
  content: "",
  source_type: "manual",
  source_uri: "",
  max_pages: 15,
  target_path: "",
  section: "",
  tags: [],
  links: [],
  write_report: true,
  allow_mixed_sources: false,
  archive_id: null,
  archive_question: null,
  archive_answer: null,
  archive_citations: [],
};

export type WikiApplyResult = WikiIngestApplyResponse | WikiQueryArchiveResponse | WikiSynthesizeResponse;

export type WikiState = {
  draft: WikiWorkflowDraft;
  tagInput: string;
  linkInput: string;
  approvedTargetsInput: string;
  reviewForceRefresh: boolean;
  preview: WikiIngestPreviewResponse | null;
  reviewResult: WikiIngestReviewResponse | null;
  applyResult: WikiApplyResult | null;
  lintResult: WikiLintRunResponse | null;
  diagnosticsQueue: WikiDiagnosticQueueResponse | null;
  schemaStatus: WikiSchemaStatus | null;
  indexStatus: WikiIndexResponse | null;
  logStatus: WikiLogResponse | null;
  coreStatus: WikiAsyncStatus;
  coreError: string;
  archiveHistory: WikiQueryArchiveHistoryItem[];
  archiveHistoryStatus: WikiAsyncStatus;
  archiveHistoryError: string;
  openedArchive: WikiQueryArchiveDetailResponse | null;
  openingArchiveId: string | null;
  companionContextReports: CompanionRetrievalReport[];
  companionContextReportStatus: WikiAsyncStatus;
  companionContextReportError: string;
  lastWikiArchiveId: string | null;
  workflowAction: WikiWorkflowAction | null;
  archiveCandidate: WikiArchiveCandidate | null;
};

export type WikiAction =
  | { type: "updateDraft"; patch: Partial<WikiWorkflowDraft> }
  | { type: "setTagInput"; value: string }
  | { type: "setLinkInput"; value: string }
  | { type: "setApprovedTargetsInput"; value: string }
  | { type: "setReviewForceRefresh"; value: boolean }
  | { type: "setArchiveCandidate"; candidate: WikiArchiveCandidate | null }
  | { type: "archiveHistoryStart" }
  | { type: "archiveHistorySuccess"; archives: WikiQueryArchiveHistoryItem[] }
  | { type: "archiveHistoryError"; message: string }
  | { type: "coreStatusStart" }
  | { type: "coreStatusSuccess"; schema: WikiSchemaStatus; index: WikiIndexResponse; log: WikiLogResponse }
  | { type: "coreStatusError"; message: string }
  | { type: "setChatWikiApplyResult"; response: WikiApplyResult | WikiLintRunResponse }
  | { type: "setLastWikiArchiveId"; archiveId: string | null }
  | { type: "openArchiveStart"; archiveId: string }
  | { type: "openArchiveSuccess"; detail: WikiQueryArchiveDetailResponse; archiveId: string; citationLinks: string[] }
  | { type: "openArchiveFinish" }
  | { type: "workflowStart"; action: WikiWorkflowAction }
  | { type: "workflowFinish" }
  | { type: "previewIngestSuccess"; preview: WikiIngestPreviewResponse }
  | { type: "applyIngestSuccess"; preview: WikiIngestPreviewResponse; response: WikiIngestApplyResponse }
  | { type: "reviewIngestSuccess"; preview: WikiIngestPreviewResponse; response: WikiIngestReviewResponse }
  | { type: "archiveLatestQuerySuccess"; response: WikiQueryArchiveResponse }
  | { type: "synthesizeSuccess"; response: WikiSynthesizeResponse }
  | { type: "lintSuccess"; response: WikiLintRunResponse }
  | { type: "diagnosticsStart" }
  | { type: "diagnosticsSuccess"; queue: WikiDiagnosticQueueResponse; reports: CompanionRetrievalReport[] }
  | { type: "diagnosticsError"; message: string }
  | { type: "reset" };

export function createInitialWikiState(): WikiState {
  return {
    draft: initialWikiDraft,
    tagInput: "desktop,wiki",
    linkInput: "",
    approvedTargetsInput: "",
    reviewForceRefresh: false,
    preview: null,
    reviewResult: null,
    applyResult: null,
    lintResult: null,
    diagnosticsQueue: null,
    schemaStatus: null,
    indexStatus: null,
    logStatus: null,
    coreStatus: "idle",
    coreError: "",
    archiveHistory: [],
    archiveHistoryStatus: "idle",
    archiveHistoryError: "",
    openedArchive: null,
    openingArchiveId: null,
    companionContextReports: [],
    companionContextReportStatus: "idle",
    companionContextReportError: "",
    lastWikiArchiveId: null,
    workflowAction: null,
    archiveCandidate: null,
  };
}

export function wikiReducer(state: WikiState, action: WikiAction): WikiState {
  switch (action.type) {
    case "updateDraft":
      return { ...state, draft: { ...state.draft, ...action.patch } };
    case "setTagInput":
      return { ...state, tagInput: action.value };
    case "setLinkInput":
      return { ...state, linkInput: action.value };
    case "setApprovedTargetsInput":
      return { ...state, approvedTargetsInput: action.value };
    case "setReviewForceRefresh":
      return { ...state, reviewForceRefresh: action.value };
    case "setArchiveCandidate":
      return { ...state, archiveCandidate: action.candidate };
    case "archiveHistoryStart":
      return { ...state, archiveHistoryStatus: "loading", archiveHistoryError: "" };
    case "archiveHistorySuccess":
      return {
        ...state,
        archiveHistory: action.archives,
        archiveHistoryStatus: action.archives.length > 0 ? "success" : "empty",
      };
    case "archiveHistoryError":
      return { ...state, archiveHistoryStatus: "error", archiveHistoryError: action.message };
    case "coreStatusStart":
      return { ...state, coreStatus: "loading", coreError: "" };
    case "coreStatusSuccess":
      return {
        ...state,
        schemaStatus: action.schema,
        indexStatus: action.index,
        logStatus: action.log,
        coreStatus: "success",
      };
    case "coreStatusError":
      return { ...state, coreStatus: "error", coreError: action.message };
    case "setChatWikiApplyResult":
      if ("summary" in action.response && "issues" in action.response) {
        return { ...state, lintResult: action.response };
      }
      return { ...state, applyResult: action.response };
    case "setLastWikiArchiveId":
      return { ...state, lastWikiArchiveId: action.archiveId };
    case "openArchiveStart":
      return { ...state, openingArchiveId: action.archiveId };
    case "openArchiveSuccess":
      return {
        ...state,
        openedArchive: action.detail,
        lastWikiArchiveId: action.archiveId,
        draft: {
          ...state.draft,
          title: action.detail.title,
          content: action.detail.answer,
          source_type: "query_archive",
          source_uri: action.detail.page.relative_path,
          target_path: action.detail.target_path || action.detail.page.relative_path,
          section: action.detail.section || "",
          tags: action.detail.tags,
          links: action.citationLinks,
          archive_id: action.archiveId,
          archive_question: action.detail.question,
          archive_answer: action.detail.answer,
          archive_citations: action.detail.citations,
        },
        tagInput: action.detail.tags.join(", "),
        linkInput: action.citationLinks.join(", "),
        preview: null,
        reviewResult: null,
        approvedTargetsInput: "",
      };
    case "openArchiveFinish":
      return { ...state, openingArchiveId: null };
    case "workflowStart":
      return { ...state, workflowAction: action.action };
    case "workflowFinish":
      return { ...state, workflowAction: null };
    case "previewIngestSuccess":
      return {
        ...state,
        preview: action.preview,
        reviewResult: null,
        approvedTargetsInput: "",
        applyResult: null,
      };
    case "applyIngestSuccess":
      return { ...state, preview: action.preview, applyResult: action.response };
    case "reviewIngestSuccess":
      return { ...state, preview: action.preview, reviewResult: action.response };
    case "archiveLatestQuerySuccess":
      return {
        ...state,
        applyResult: action.response,
        lastWikiArchiveId: action.response.archive_id || state.lastWikiArchiveId,
      };
    case "synthesizeSuccess":
      return { ...state, applyResult: action.response, preview: null };
    case "lintSuccess":
      return { ...state, lintResult: action.response };
    case "diagnosticsStart":
      return {
        ...state,
        workflowAction: "diagnostics",
        companionContextReportStatus: "loading",
        companionContextReportError: "",
      };
    case "diagnosticsSuccess":
      return {
        ...state,
        diagnosticsQueue: action.queue,
        companionContextReports: action.reports,
        companionContextReportStatus: action.reports.length > 0 ? "success" : "empty",
        companionContextReportError: "",
      };
    case "diagnosticsError":
      return {
        ...state,
        companionContextReportStatus: "error",
        companionContextReportError: action.message,
      };
    case "reset": {
      const initialState = createInitialWikiState();
      return { ...initialState, draft: state.draft, tagInput: state.tagInput, linkInput: state.linkInput, reviewForceRefresh: state.reviewForceRefresh, archiveCandidate: state.archiveCandidate };
    }
    default:
      return state;
  }
}
