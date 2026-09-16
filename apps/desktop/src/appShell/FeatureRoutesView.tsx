import { DesktopFeatureRoutes } from "../features/desktop/DesktopFeatureRoutes";
import { buildAppShellPresentation } from "./appShellPresentation";
import { useAppShellRuntime } from "./AppShellRuntimeContext";
import { AgentActivityEntryContainer } from "./AgentActivityEntryContainer";
import { SettingsPanelContainer, WikiPanelsContainer } from "./AppShellPanels";

export function FeatureRoutesView() {
  const runtime = useAppShellRuntime();
  const presentation = buildAppShellPresentation(runtime);
  const { app, connection, activity, memory, continuity } = runtime;

  function refreshActivity() {
    void activity.load();
    void memory.loadPendingProposals({ silent: true });
    void continuity.load({ silent: true });
  }

  return (
    <DesktopFeatureRoutes
      windowMode={app.routing.windowMode}
      isStageHostWindow={app.routing.desktopHostMode === "stage"}
      agentWorkspaceProps={{ api: connection.connection.api }}
      chatWindowProps={{
        input: app.controlInput,
        messages: app.messages,
        connected: connection.hasConnection,
        streaming: app.streaming,
        onInputChange: app.setControlInput,
        onSend: (event) => {
          event.preventDefault();
          void runtime.chat.sendChatText(app.controlInput, () => app.setControlInput(""));
        },
        onStopStreaming: runtime.chat.stopStreaming,
        revertingActionIds: activity.revertingActionIds,
        onRevertAgentAction: (action) => void activity.revert(action),
        onOpenTask: () => app.routing.setWindowMode("agent"),
        onOpenMemory: () => app.routing.setWindowMode("memory"),
        onOpenWiki: (path) => activity.openArtifact("world", path),
        onOpenReport: (path) => activity.openArtifact("memory", path),
        onDismissContinuitySignal: (messageId, proposalId) =>
          void runtime.continuity.dismissSignal(messageId, proposalId),
        pendingCheckpoints: activity.pendingCheckpoints,
        decidingCheckpointIds: activity.decidingCheckpointIds,
        onDecideCheckpoint: (checkpoint, decision) => void activity.decideCheckpoint(checkpoint, decision),
      }}
      memoryWindowProps={{
        api: connection.connection.api,
        loading: activity.status === "loading" || memory.loadingProposals || continuity.loading,
        error: activity.error,
        entries: presentation.activityEntries,
        memorySearchQuery: memory.searchQuery,
        memorySearchStatus: memory.searchStatus,
        memorySearchResults: memory.searchResults,
        memoryLastSearchQuery: memory.lastSearchQuery,
        onMemorySearchQueryChange: memory.setSearchQuery,
        onRunMemorySearch: (event) => void memory.runMemorySearch(event),
        memoryProposalDraft: memory.proposalDraft,
        memoryProposals: memory.proposals,
        memoryProposalActionIds: memory.proposalActionIds,
        loadingMemoryProposals: memory.loadingProposals,
        onMemoryProposalDraftChange: memory.updateProposalDraft,
        onCreateMemoryProposal: (event) => void memory.createProposal(event),
        onActOnMemoryProposal: (proposalId, action) => void memory.actOnProposal(proposalId, action),
        onLoadMemoryProposals: () => void memory.loadPendingProposals(),
        onRefresh: refreshActivity,
        renderEntry: (entry) => <AgentActivityEntryContainer key={entry.id} entry={entry} />,
      }}
      growthWindowProps={{ api: connection.connection.api }}
      wikiWorkflowPanel={<WikiPanelsContainer />}
      settingsPanel={<SettingsPanelContainer />}
    />
  );
}
