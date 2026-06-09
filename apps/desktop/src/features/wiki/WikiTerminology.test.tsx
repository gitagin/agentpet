import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import WorldWindowView from "../../views/WorldWindowView";
import { initialWikiDraft } from "./wikiReducer";
import { WikiBrowserPanel } from "./WikiBrowserPanel";
import { WikiWorkflowPanel } from "./WikiWorkflowPanel";
import type { WikiIndexResponse, WikiIngestPreviewResponse } from "../../types";

const noop = vi.fn();
const updatedAt = "2026-06-03T12:00:00.000Z";

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

function indexResponse(entries: WikiIndexResponse["entries"] = []): WikiIndexResponse {
  return {
    path: "Wiki/index.md",
    updated_at: updatedAt,
    content: "",
    entries,
  };
}

function renderBrowserPanel(props: Partial<Parameters<typeof WikiBrowserPanel>[0]> = {}) {
  return render(
    <WikiBrowserPanel
      vaultConfigured
      indexRequired={false}
      schemaStatus={{ path: "Wiki/AGENTS.md", exists: true, updated_at: updatedAt, content: "" }}
      indexStatus={indexResponse()}
      logStatus={{ path: "Wiki/log.md", updated_at: updatedAt, entries: [], content: "" }}
      lintResult={null}
      diagnosticsQueue={null}
      archiveHistory={[]}
      archiveHistoryStatus="success"
      archiveHistoryError=""
      archiveHistoryLoading={false}
      coreStatus="success"
      coreError=""
      workflowAction={null}
      openingArchiveId={null}
      formatIssueSeverity={(severity) => severity}
      onLoadCoreStatus={noop}
      onLoadArchiveHistory={noop}
      onLoadDiagnosticsQueue={noop}
      onOpenArchive={noop}
      onTryKnowledgeSnippet={noop}
      {...props}
    />,
  );
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

describe("wiki terminology", () => {
  it("uses product language in the Knowledge Base shell", () => {
    render(
      <WorldWindowView>
        <div>content</div>
      </WorldWindowView>,
    );

    expect(screen.getByRole("heading", { name: "知识整理" })).toBeInTheDocument();
    expect(screen.queryByText(/Vault \/ Wiki|VAULT \/ WIKI/i)).not.toBeInTheDocument();
  });

  it("prioritizes recent Wiki output and collapses maintenance status", () => {
    renderBrowserPanel();

    const recentPages = screen.getByLabelText("最近 Wiki 页面");
    expect(within(recentPages).getByText("最近生成的 Wiki 页面")).toBeInTheDocument();

    const maintenance = screen.getByLabelText("知识库状态和维护记录");
    expect(maintenance).not.toHaveAttribute("open");
    expect(screen.getByText("状态、日志与只读检查")).toBeVisible();
    expect(within(maintenance).getByText("Vault")).not.toBeVisible();
    expect(within(maintenance).getByText("页面")).not.toBeVisible();
    expect(within(maintenance).getByText("日志")).not.toBeVisible();
    expect(within(maintenance).getByText("只读检查和诊断提示")).not.toBeVisible();
    expect(within(maintenance).getByText("查询历史")).not.toBeVisible();
    expect(screen.queryByText(/VAULT \/ WIKI|Vault \/ Wiki|query archive|lint \/|Wiki 首页/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Wiki\/index\.md|Wiki\/log\.md|Wiki\/AGENTS\.md/)).not.toBeInTheDocument();
  });

  it("shows recent Wiki output as cards with title, summary, path, and update time", () => {
    renderBrowserPanel({
      schemaStatus: null,
      indexStatus: indexResponse([
        {
          title: "项目总结",
          relative_path: "Wiki/Companion/Summaries/Project.md",
          page_type: "summary",
          summary: "一次自动沉淀",
          source_count: 1,
          updated_at: updatedAt,
        },
      ]),
      logStatus: null,
    });

    const recentPages = screen.getByLabelText("最近 Wiki 页面");
    const card = within(recentPages).getByText("项目总结").closest("article");
    expect(card).not.toBeNull();
    expect(card).toHaveTextContent("一次自动沉淀");
    expect(card).toHaveTextContent("路径");
    expect(card).toHaveTextContent("Wiki/Companion/Summaries/Project.md");
    expect(card).toHaveTextContent("更新时间");
    expect(card).toHaveTextContent("06/03");
  });

  it("shows no Vault, no pages, and index-required states clearly", () => {
    const { rerender } = renderBrowserPanel({
      vaultConfigured: false,
      indexStatus: null,
    });

    expect(screen.getAllByText(/未绑定 Vault/).length).toBeGreaterThan(0);
    expect(screen.getByText("未绑定")).toBeInTheDocument();

    rerender(
      <WikiBrowserPanel
        vaultConfigured
        indexRequired
        schemaStatus={null}
        indexStatus={null}
        logStatus={null}
        lintResult={null}
        diagnosticsQueue={null}
        archiveHistory={[]}
        archiveHistoryStatus="success"
        archiveHistoryError=""
        archiveHistoryLoading={false}
        coreStatus="idle"
        coreError=""
        workflowAction={null}
        openingArchiveId={null}
        formatIssueSeverity={(severity) => severity}
        onLoadCoreStatus={noop}
        onLoadArchiveHistory={noop}
        onLoadDiagnosticsQueue={noop}
        onOpenArchive={noop}
      />,
    );
    expect(screen.getAllByText(/需要索引/).length).toBeGreaterThan(0);
    expect(screen.getByText("需要刷新")).toBeInTheDocument();

    rerender(
      <WikiBrowserPanel
        vaultConfigured
        indexRequired={false}
        schemaStatus={null}
        indexStatus={indexResponse()}
        logStatus={null}
        lintResult={null}
        diagnosticsQueue={null}
        archiveHistory={[]}
        archiveHistoryStatus="success"
        archiveHistoryError=""
        archiveHistoryLoading={false}
        coreStatus="success"
        coreError=""
        workflowAction={null}
        openingArchiveId={null}
        formatIssueSeverity={(severity) => severity}
        onLoadCoreStatus={noop}
        onLoadArchiveHistory={noop}
        onLoadDiagnosticsQueue={noop}
        onOpenArchive={noop}
      />,
    );
    expect(screen.getAllByText(/还没有 Wiki 页面/).length).toBeGreaterThan(0);
  });

  it("offers a guided action for pasting a knowledge snippet", () => {
    const onTryKnowledgeSnippet = vi.fn();
    renderBrowserPanel({ onTryKnowledgeSnippet });

    fireEvent.click(screen.getByRole("button", { name: "粘贴知识片段" }));

    expect(onTryKnowledgeSnippet).toHaveBeenCalledTimes(1);
  });

  it("puts the daily organizer before advanced maintenance and supports preview/apply", () => {
    const onPreview = vi.fn((event) => event.preventDefault());
    const onApply = vi.fn();

    const { rerender } = renderWorkflowPanel({ onPreview, onApply });

    const organizer = screen.getByLabelText("日常 Wiki 整理");
    expect(within(organizer).getByLabelText("创建或更新 Wiki 页面")).toBeInTheDocument();
    expect(within(organizer).getByLabelText("标题")).toBeInTheDocument();
    expect(within(organizer).getByLabelText("来源内容")).toBeInTheDocument();
    expect(within(organizer).getByLabelText("目标类型")).toBeInTheDocument();
    expect(within(organizer).getByRole("button", { name: "应用" })).toBeDisabled();

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

    expect(screen.getByLabelText("Wiki 预览结果")).toHaveTextContent("Wiki/Concepts/Decision-Memory.md");
    fireEvent.click(within(screen.getByLabelText("日常 Wiki 整理")).getByRole("button", { name: "应用" }));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("keeps advanced maintenance collapsed and risk-aware", () => {
    renderWorkflowPanel();

    const advancedTools = screen.getByLabelText("高级知识库维护工具");
    expect(advancedTools).not.toHaveAttribute("open");
    expect(screen.getByText("展开高级维护工具")).toBeInTheDocument();
    expect(screen.getByText(/部分操作会写入 Markdown/)).toBeInTheDocument();
    expect(screen.queryByText(/高级 Vault|Vault 引用|归档最近一条带 Vault|不写入 Vault/)).not.toBeInTheDocument();
  });
});
