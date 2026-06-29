import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WikiIngestPreviewResponse } from "../../types";
import { initialWikiDraft } from "./wikiReducer";
import { WikiWorkflowPanel } from "./WikiWorkflowPanel";

const noop = vi.fn();

function preview(overrides: Partial<WikiIngestPreviewResponse> = {}): WikiIngestPreviewResponse {
  return {
    run_id: "run-1",
    source_id: "source-1",
    source_hash: "hash-1",
    status: "planned",
    summary: "Preview ready",
    preview_token: "token-1",
    page_plans: [
      {
        title: "Decision Memory",
        target_path: "Wiki/Concepts/Decision-Memory.md",
        operation: "create",
        section: "Source: Launch notes",
        content: "content",
        tags: ["concept"],
        links: [],
      },
    ],
    ...overrides,
  };
}

function renderWorkflowPanel(props: Partial<Parameters<typeof WikiWorkflowPanel>[0]> = {}) {
  return render(
    <WikiWorkflowPanel
      draft={initialWikiDraft}
      tagInput="desktop, wiki"
      linkInput=""
      approvedTargetsInput=""
      reviewForceRefresh={false}
      preview={null}
      reviewResult={null}
      applyResult={null}
      lintResult={null}
      diagnosticsQueue={null}
      schemaStatus={null}
      indexStatus={null}
      logStatus={null}
      coreStatus="idle"
      coreError=""
      archiveHistory={[]}
      archiveHistoryStatus="idle"
      archiveHistoryError=""
      openedArchive={null}
      openingArchiveId={null}
      companionContextReports={[]}
      companionContextReportStatus="idle"
      companionContextReportError=""
      lastWikiArchiveId={null}
      workflowAction={null}
      latestKnowledgeCitationCount={0}
      archiveHistorySummary="还没有查询历史"
      archiveHistoryLoading={false}
      lintIssueCount={0}
      formatIssueSeverity={(severity) => severity}
      onDraftChange={noop}
      onTagInputChange={noop}
      onLinkInputChange={noop}
      onApprovedTargetsInputChange={noop}
      onReviewForceRefreshChange={noop}
      onPreview={(event) => event.preventDefault()}
      onReview={noop}
      onApply={noop}
      onArchiveLatestQuery={noop}
      onSynthesize={noop}
      onRunLint={noop}
      onLoadDiagnosticsQueue={noop}
      onLoadArchiveHistory={noop}
      onLoadCoreStatus={noop}
      onUseReviewRecommendedTargets={noop}
      onOpenArchive={noop}
      {...props}
    />,
  );
}

describe("WikiWorkflowPanel", () => {
  it("exposes the daily organizer before advanced maintenance", () => {
    const onPreview = vi.fn((event) => event.preventDefault());
    const onApply = vi.fn();

    const { rerender } = renderWorkflowPanel({ onPreview, onApply });

    const organizer = screen.getByLabelText("日常资料整理");
    const advancedTools = screen.getByLabelText("高级知识库维护工具");

    expect(organizer.compareDocumentPosition(advancedTools) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(organizer).getByLabelText("创建或更新资料页")).toBeInTheDocument();
    expect(within(organizer).getByLabelText("标题")).toBeInTheDocument();
    expect(within(organizer).getByLabelText("来源内容")).toBeInTheDocument();
    expect(within(organizer).getByLabelText("目标类型")).toBeInTheDocument();
    expect(within(organizer).getByRole("button", { name: "应用" })).toBeDisabled();
    expect(advancedTools).not.toHaveAttribute("open");

    fireEvent.click(within(organizer).getByRole("button", { name: "预览" }));
    expect(onPreview).toHaveBeenCalledTimes(1);

    rerender(
      <WikiWorkflowPanel
        draft={initialWikiDraft}
        tagInput="desktop, wiki"
        linkInput=""
        approvedTargetsInput=""
        reviewForceRefresh={false}
        preview={preview()}
        reviewResult={null}
        applyResult={null}
        lintResult={null}
        diagnosticsQueue={null}
        schemaStatus={null}
        indexStatus={null}
        logStatus={null}
        coreStatus="idle"
        coreError=""
        archiveHistory={[]}
        archiveHistoryStatus="idle"
        archiveHistoryError=""
        openedArchive={null}
        openingArchiveId={null}
        companionContextReports={[]}
        companionContextReportStatus="idle"
        companionContextReportError=""
        lastWikiArchiveId={null}
        workflowAction={null}
        latestKnowledgeCitationCount={0}
        archiveHistorySummary="还没有查询历史"
        archiveHistoryLoading={false}
        lintIssueCount={0}
        formatIssueSeverity={(severity) => severity}
        onDraftChange={noop}
        onTagInputChange={noop}
        onLinkInputChange={noop}
        onApprovedTargetsInputChange={noop}
        onReviewForceRefreshChange={noop}
        onPreview={onPreview}
        onReview={noop}
        onApply={onApply}
        onArchiveLatestQuery={noop}
        onSynthesize={noop}
        onRunLint={noop}
        onLoadDiagnosticsQueue={noop}
        onLoadArchiveHistory={noop}
        onLoadCoreStatus={noop}
        onUseReviewRecommendedTargets={noop}
        onOpenArchive={noop}
      />,
    );

    expect(screen.getByLabelText("资料页预览结果")).toHaveTextContent("Wiki/Concepts/Decision-Memory.md");
    fireEvent.click(within(screen.getByLabelText("日常资料整理")).getByRole("button", { name: "应用" }));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("keeps advanced maintenance and system-style details hidden by default", () => {
    renderWorkflowPanel();

    expect(screen.getByLabelText("日常资料整理")).toBeInTheDocument();
    expect(screen.getByLabelText("高级知识库维护工具")).not.toHaveAttribute("open");
    expect(screen.getByText("审查/应用目标")).not.toBeVisible();
    expect(screen.queryByText("运行状态")).not.toBeInTheDocument();
    expect(screen.queryByText(/source_hash|preview_token|schema_migrations/i)).not.toBeInTheDocument();
  });
});
