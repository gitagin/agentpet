import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import WorldWindowView from "../../views/WorldWindowView";
import { initialWikiDraft } from "./wikiReducer";
import { WikiBrowserPanel } from "./WikiBrowserPanel";
import { WikiWorkflowPanel } from "./WikiWorkflowPanel";

const noop = vi.fn();
const updatedAt = "2026-06-03T12:00:00.000Z";

describe("wiki terminology", () => {
  it("uses product language in the Knowledge Base shell", () => {
    render(
      <WorldWindowView>
        <div>content</div>
      </WorldWindowView>,
    );

    expect(screen.getByText("本地知识")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "知识库" })).toBeInTheDocument();
    expect(screen.queryByText(/Vault \/ Wiki|VAULT \/ WIKI/i)).not.toBeInTheDocument();
  });

  it("keeps technical wiki terms out of the browser first viewport copy", () => {
    render(
      <WikiBrowserPanel
        schemaStatus={{ path: "Wiki/AGENTS.md", exists: true, updated_at: updatedAt, content: "" }}
        indexStatus={{ path: "Wiki/index.md", updated_at: updatedAt, entries: [], content: "" }}
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
      />,
    );

    expect(screen.getByText("知识库状态")).toBeInTheDocument();
    expect(screen.getByText("维护规则")).toBeInTheDocument();
    expect(screen.getByText("知识页面")).toBeInTheDocument();
    expect(screen.getByText("更新日志")).toBeInTheDocument();
    expect(screen.getByText("只读检查和诊断提示")).toBeInTheDocument();
    expect(screen.getByText("查询历史")).toBeInTheDocument();
    expect(screen.queryByText(/VAULT \/ WIKI|Vault \/ Wiki|query archive|lint \/|Wiki 首页/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Wiki\/index\.md|Wiki\/log\.md|Wiki\/AGENTS\.md/)).not.toBeInTheDocument();
  });

  it("keeps page paths in secondary details", () => {
    render(
      <WikiBrowserPanel
        schemaStatus={null}
        indexStatus={{
          path: "Wiki/index.md",
          updated_at: updatedAt,
          content: "",
          entries: [
            {
              title: "项目总结",
              relative_path: "Wiki/Companion/Summaries/Project.md",
              page_type: "summary",
              summary: "一次自动沉淀",
              source_count: 1,
              updated_at: updatedAt,
            },
          ],
        }}
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

    const locationDetails = screen.getByText("页面位置").closest("details");
    expect(locationDetails).not.toHaveAttribute("open");
    expect(locationDetails).toHaveTextContent("Wiki/Companion/Summaries/Project.md");
  });

  it("keeps advanced maintenance collapsed and risk-aware", () => {
    render(
      <WikiWorkflowPanel
        draft={initialWikiDraft}
        tagInput=""
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
      />,
    );

    const advancedTools = screen.getByLabelText("高级知识库维护工具");
    expect(advancedTools).not.toHaveAttribute("open");
    expect(screen.getByText("展开高级维护工具")).toBeInTheDocument();
    expect(screen.getByText(/部分操作会写入 Markdown/)).toBeInTheDocument();
    expect(screen.queryByText(/高级 Vault|Vault 引用|归档最近一条带 Vault|不写入 Vault/)).not.toBeInTheDocument();
  });
});
