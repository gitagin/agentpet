import { describe, expect, it } from "vitest";

import type {
  CompanionRetrievalReport,
  MemorySearchResult,
  WikiDiagnosticQueueResponse,
  WikiIndexResponse,
  WikiIngestPreviewResponse,
  WikiIngestReviewResponse,
  WikiLogResponse,
  WikiQueryArchiveDetailResponse,
  WikiQueryArchiveHistoryItem,
  WikiQueryArchiveResponse,
  WikiSchemaStatus,
  WikiSynthesizeResponse,
} from "../../types";
import { createInitialWikiState, wikiReducer } from "./wikiReducer";

function preview(overrides: Partial<WikiIngestPreviewResponse> = {}): WikiIngestPreviewResponse {
  return {
    run_id: "run-1",
    source_id: "source-1",
    source_hash: "hash-1",
    status: "planned",
    page_plans: [
      {
        title: "页面",
        target_path: "Inbox/Page.md",
        operation: "create",
        content: "内容",
        tags: ["wiki"],
        links: [],
      },
    ],
    summary: "预览完成",
    preview_token: "token-1",
    ...overrides,
  };
}

function review(overrides: Partial<WikiIngestReviewResponse> = {}): WikiIngestReviewResponse {
  return {
    review_id: "review-1",
    run_id: "run-1",
    status: "reviewed",
    summary: "审查完成",
    findings: [],
    recommended_targets: ["Inbox/Page.md"],
    ...overrides,
  };
}

function citation(overrides: Partial<MemorySearchResult> = {}): MemorySearchResult {
  return {
    note_id: "note-1",
    chunk_id: "chunk-1",
    relative_path: "Memories/Source.md",
    title: "来源",
    snippet: "引用内容",
    score: 0.8,
    source_scope: "knowledge_base",
    ...overrides,
  };
}

function archiveDetail(overrides: Partial<WikiQueryArchiveDetailResponse> = {}): WikiQueryArchiveDetailResponse {
  return {
    id: "archive-1",
    archive_id: "archive-1",
    question: "问题？",
    answer: "答案。",
    answer_preview: "答案。",
    title: "归档标题",
    target_path: "Archive/Answer.md",
    section: "问答",
    tags: ["query-archive"],
    citation_count: 1,
    citations: [citation()],
    created_at: "2026-05-25T00:00:00Z",
    updated_at: "2026-05-25T00:00:00Z",
    page: {
      title: "归档标题",
      relative_path: "Archive/Answer.md",
      operation: "append",
      status: "indexed",
    },
    ...overrides,
  };
}

function archiveResponse(overrides: Partial<WikiQueryArchiveResponse> = {}): WikiQueryArchiveResponse {
  return {
    archive_id: "archive-1",
    page: {
      title: "归档标题",
      relative_path: "Archive/Answer.md",
      operation: "append",
      status: "indexed",
    },
    lint: {
      passed: true,
      errors: [],
      warnings: [],
      normalized_citations: [citation()],
      markdown_preview: "归档内容",
    },
    ...overrides,
  };
}

function schemaStatus(): WikiSchemaStatus {
  return { path: "Wiki/Schema.md", exists: true, content: "schema" };
}

function indexStatus(): WikiIndexResponse {
  return { path: "Wiki/Index.md", entries: [], content: "index" };
}

function logStatus(): WikiLogResponse {
  return { path: "Wiki/Log.md", entries: [], content: "log" };
}

function historyItem(overrides: Partial<WikiQueryArchiveHistoryItem> = {}): WikiQueryArchiveHistoryItem {
  return {
    archive_id: "archive-1",
    question: "问题？",
    answer_preview: "答案。",
    title: "归档标题",
    target_path: "Archive/Answer.md",
    tags: [],
    citation_count: 1,
    created_at: "2026-05-25T00:00:00Z",
    updated_at: "2026-05-25T00:00:00Z",
    ...overrides,
  };
}

function diagnosticsQueue(): WikiDiagnosticQueueResponse {
  return { generated_at: "2026-05-25T00:00:00Z", summary: { total: 1 }, items: [] };
}

function companionReport(): CompanionRetrievalReport {
  return {
    id: "report-1",
    agent_run_id: "run-1",
    strategy: "hybrid",
    candidate_count: 3,
    selected_count: 1,
    duplicate_drop_count: 0,
    per_scope_drop_count: 0,
    budget_drop_count: 0,
    item_budget: 5,
    per_scope_limit: 3,
    char_budget: 2000,
    used_chars: 100,
    source_counts: { knowledge_base: 1 },
    selected_scopes: ["knowledge_base"],
    created_at: "2026-05-25T00:00:00Z",
  };
}

describe("wikiReducer", () => {
  it("creates the initial Wiki state", () => {
    const state = createInitialWikiState();

    expect(state.draft).toMatchObject({ title: "", content: "", source_type: "manual", max_pages: 15 });
    expect(state.tagInput).toBe("desktop,wiki");
    expect(state.coreStatus).toBe("idle");
    expect(state.archiveHistory).toEqual([]);
    expect(state.workflowAction).toBeNull();
  });

  it("updates draft and form inputs", () => {
    const state = wikiReducer(createInitialWikiState(), {
      type: "updateDraft",
      patch: { title: "标题", content: "正文" },
    });
    const withTags = wikiReducer(state, { type: "setTagInput", value: "wiki, test" });

    expect(withTags.draft.title).toBe("标题");
    expect(withTags.draft.content).toBe("正文");
    expect(withTags.tagInput).toBe("wiki, test");
  });

  it("loads core status and records errors", () => {
    const loading = wikiReducer(createInitialWikiState(), { type: "coreStatusStart" });
    const successful = wikiReducer(loading, {
      type: "coreStatusSuccess",
      schema: schemaStatus(),
      index: indexStatus(),
      log: logStatus(),
    });
    const failed = wikiReducer(successful, { type: "coreStatusError", message: "刷新失败" });

    expect(loading.coreStatus).toBe("loading");
    expect(successful.coreStatus).toBe("success");
    expect(successful.schemaStatus?.path).toBe("Wiki/Schema.md");
    expect(failed.coreStatus).toBe("error");
    expect(failed.coreError).toBe("刷新失败");
  });

  it("loads archive history with success, empty, and error states", () => {
    const loading = wikiReducer(createInitialWikiState(), { type: "archiveHistoryStart" });
    const successful = wikiReducer(loading, { type: "archiveHistorySuccess", archives: [historyItem()] });
    const empty = wikiReducer(successful, { type: "archiveHistorySuccess", archives: [] });
    const failed = wikiReducer(empty, { type: "archiveHistoryError", message: "历史失败" });

    expect(loading.archiveHistoryStatus).toBe("loading");
    expect(successful.archiveHistoryStatus).toBe("success");
    expect(successful.archiveHistory[0].archive_id).toBe("archive-1");
    expect(empty.archiveHistoryStatus).toBe("empty");
    expect(failed.archiveHistoryError).toBe("历史失败");
  });

  it("stores preview, review, archive, synthesize, and lint workflow results", () => {
    const previewed = wikiReducer(createInitialWikiState(), { type: "previewIngestSuccess", preview: preview() });
    const reviewed = wikiReducer(previewed, { type: "reviewIngestSuccess", preview: preview({ run_id: "run-2" }), response: review() });
    const archived = wikiReducer(reviewed, { type: "archiveLatestQuerySuccess", response: archiveResponse() });
    const synthesized = wikiReducer(archived, {
      type: "synthesizeSuccess",
      response: {
        page: { title: "综合", relative_path: "Wiki/Summary.md", operation: "create", status: "indexed" },
      } satisfies WikiSynthesizeResponse,
    });
    const linted = wikiReducer(synthesized, {
      type: "lintSuccess",
      response: { generated_at: "2026-05-25T00:00:00Z", summary: { issues: 0 }, issues: [], research_questions: [] },
    });

    expect(previewed.preview?.run_id).toBe("run-1");
    expect(previewed.reviewResult).toBeNull();
    expect(reviewed.preview?.run_id).toBe("run-2");
    expect(reviewed.reviewResult?.review_id).toBe("review-1");
    expect(archived.lastWikiArchiveId).toBe("archive-1");
    expect(synthesized.preview).toBeNull();
    expect(linted.lintResult?.summary.issues).toBe(0);
  });

  it("opens archives and updates draft fields atomically", () => {
    const state = wikiReducer(createInitialWikiState(), {
      type: "openArchiveSuccess",
      detail: archiveDetail(),
      archiveId: "archive-1",
      citationLinks: ["Memories/Source.md"],
    });

    expect(state.openedArchive?.id).toBe("archive-1");
    expect(state.lastWikiArchiveId).toBe("archive-1");
    expect(state.draft).toMatchObject({
      title: "归档标题",
      content: "答案。",
      source_type: "query_archive",
      source_uri: "Archive/Answer.md",
      target_path: "Archive/Answer.md",
      archive_id: "archive-1",
    });
    expect(state.tagInput).toBe("query-archive");
    expect(state.linkInput).toBe("Memories/Source.md");
  });

  it("stores diagnostics reports and resets runtime state", () => {
    const successful = wikiReducer(createInitialWikiState(), {
      type: "diagnosticsSuccess",
      queue: diagnosticsQueue(),
      reports: [companionReport()],
    });
    const reset = wikiReducer(successful, { type: "reset" });

    expect(successful.diagnosticsQueue?.summary.total).toBe(1);
    expect(successful.companionContextReportStatus).toBe("success");
    expect(successful.companionContextReports[0].id).toBe("report-1");
    expect(reset.diagnosticsQueue).toBeNull();
    expect(reset.companionContextReports).toEqual([]);
  });
});
