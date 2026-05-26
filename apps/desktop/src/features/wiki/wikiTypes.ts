import type {
  ChatMessage,
  MemorySearchResult,
  WikiIngestApplyResponse,
  WikiIngestRequest,
  WikiLintRunResponse,
  WikiQueryArchiveResponse,
  WikiSynthesizeResponse,
} from "../../types";

export type WikiWorkflowAction = "preview" | "review" | "apply" | "archive" | "synthesize" | "lint" | "diagnostics";

export type ChatWikiApplyResponse =
  | WikiIngestApplyResponse
  | WikiQueryArchiveResponse
  | WikiSynthesizeResponse
  | WikiLintRunResponse;

export type WikiArchiveCandidate = {
  conversation_id: string | null;
  message: ChatMessage;
  question?: string | null;
  updated_at: string;
};

export type WikiWorkflowDraft = WikiIngestRequest & {
  target_path?: string | null;
  section?: string | null;
  write_report: boolean;
  allow_mixed_sources: boolean;
  archive_id?: string | null;
  archive_question?: string | null;
  archive_answer?: string | null;
  archive_citations?: MemorySearchResult[];
};

export type WikiAsyncStatus = "idle" | "loading" | "success" | "empty" | "error";
