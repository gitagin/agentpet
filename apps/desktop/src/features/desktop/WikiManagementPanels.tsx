import { WikiBrowserPanel } from "../wiki/WikiBrowserPanel";
import { WikiWorkflowPanel } from "../wiki/WikiWorkflowPanel";
import type { useWiki } from "../wiki/useWiki";

export type WikiManagementPanelsProps = {
  wiki: ReturnType<typeof useWiki>;
  context: {
    vaultConfigured: boolean;
    indexRequired: boolean;
    formatIssueSeverity: (severity: string) => string;
    onTryKnowledgeSnippet: () => void;
  };
};

export function WikiManagementPanels({ wiki, context }: WikiManagementPanelsProps) {
  return (
    <>
      <WikiWorkflowPanel
        draft={wiki.draft}
        tagInput={wiki.tagInput}
        linkInput={wiki.linkInput}
        approvedTargetsInput={wiki.approvedTargetsInput}
        reviewForceRefresh={wiki.reviewForceRefresh}
        preview={wiki.preview}
        reviewResult={wiki.reviewResult}
        applyResult={wiki.applyResult}
        lintResult={wiki.lintResult}
        diagnosticsQueue={wiki.diagnosticsQueue}
        schemaStatus={wiki.schemaStatus}
        indexStatus={wiki.indexStatus}
        logStatus={wiki.logStatus}
        coreStatus={wiki.coreStatus}
        coreError={wiki.coreError}
        archiveHistory={wiki.archiveHistory}
        archiveHistoryStatus={wiki.archiveHistoryStatus}
        archiveHistoryError={wiki.archiveHistoryError}
        openedArchive={wiki.openedArchive}
        openingArchiveId={wiki.openingArchiveId}
        companionContextReports={wiki.companionContextReports}
        companionContextReportStatus={wiki.companionContextReportStatus}
        companionContextReportError={wiki.companionContextReportError}
        lastWikiArchiveId={wiki.lastWikiArchiveId}
        workflowAction={wiki.workflowAction}
        latestArchiveMessage={wiki.latestArchiveMessage}
        latestKnowledgeCitationCount={wiki.latestKnowledgeCitationCount}
        archiveHistorySummary={wiki.archiveHistorySummary}
        archiveHistoryLoading={wiki.archiveHistoryLoading}
        lintIssueCount={wiki.lintIssueCount}
        formatIssueSeverity={context.formatIssueSeverity}
        onDraftChange={wiki.onDraftChange}
        onTagInputChange={wiki.setTagInput}
        onLinkInputChange={wiki.setLinkInput}
        onApprovedTargetsInputChange={wiki.setApprovedTargetsInput}
        onReviewForceRefreshChange={wiki.setReviewForceRefresh}
        onPreview={(event) => void wiki.previewIngest(event)}
        onReview={() => void wiki.reviewIngest()}
        onApply={() => void wiki.applyIngest()}
        onArchiveLatestQuery={() => void wiki.archiveLatestQuery()}
        onSynthesize={() => void wiki.synthesize()}
        onRunLint={() => void wiki.runLint()}
        onLoadDiagnosticsQueue={() => void wiki.loadDiagnosticsQueue()}
        onLoadArchiveHistory={() => void wiki.loadArchiveHistory()}
        onLoadCoreStatus={() => void wiki.loadCoreStatus()}
        onUseReviewRecommendedTargets={wiki.useReviewRecommendedTargets}
        onOpenArchive={(archiveId) => void wiki.openArchive(archiveId)}
      />
      <WikiBrowserPanel
        vaultConfigured={context.vaultConfigured}
        indexRequired={context.indexRequired}
        schemaStatus={wiki.schemaStatus}
        indexStatus={wiki.indexStatus}
        logStatus={wiki.logStatus}
        lintResult={wiki.lintResult}
        diagnosticsQueue={wiki.diagnosticsQueue}
        archiveHistory={wiki.archiveHistory}
        archiveHistoryStatus={wiki.archiveHistoryStatus}
        archiveHistoryError={wiki.archiveHistoryError}
        archiveHistoryLoading={wiki.archiveHistoryLoading}
        coreStatus={wiki.coreStatus}
        coreError={wiki.coreError}
        workflowAction={wiki.workflowAction}
        openingArchiveId={wiki.openingArchiveId}
        formatIssueSeverity={context.formatIssueSeverity}
        onLoadCoreStatus={() => void wiki.loadCoreStatus()}
        onLoadArchiveHistory={() => void wiki.loadArchiveHistory()}
        onLoadDiagnosticsQueue={() => void wiki.loadDiagnosticsQueue()}
        onOpenArchive={(archiveId) => void wiki.openArchive(archiveId)}
        onTryKnowledgeSnippet={context.onTryKnowledgeSnippet}
      />
    </>
  );
}
