import { ControlDashboard } from "../features/desktop/ControlDashboard";
import { scrollToWorkflowTarget } from "./appShellUtils";
import { buildAppShellPresentation } from "./appShellPresentation";
import { useAppShellRuntime } from "./AppShellRuntimeContext";
import { AgentActivityEntryContainer } from "./AgentActivityEntryContainer";
import { ConnectionPanelContainer, SettingsPanelContainer, WikiPanelsContainer } from "./AppShellPanels";

export function ControlRouteView() {
  const runtime = useAppShellRuntime();
  const presentation = buildAppShellPresentation(runtime);
  const { app, connection, activity, tasks, memory, continuity } = runtime;

  function refreshActivity() {
    void activity.load();
    void memory.loadPendingProposals({ silent: true });
    void continuity.load({ silent: true });
  }

  return (
    <ControlDashboard
      runtime={{
        sidecarStatus: connection.connection.sidecarStatus,
        health: connection.connection.health,
        notice: app.notice,
        ttsActive: runtime.pet.tts.active,
        api: connection.connection.api,
        halfbodyPortraitRef: app.halfbodyPortraitRef,
        firstUseOnboardingPanel: runtime.onboardingPanel,
      }}
      chat={{
        input: app.controlInput,
        connected: connection.hasConnection,
        streaming: app.streaming,
        messages: app.messages,
        messageListProps: {
          messages: app.messages.slice(-6),
          revertingActionIds: activity.revertingActionIds,
          onRevertAgentAction: (action) => void activity.revert(action),
          onOpenTask: () => app.routing.setWindowMode("agent"),
          onOpenMemory: () => app.routing.setWindowMode("memory"),
          onOpenWiki: (path) => activity.openArtifact("world", path),
          onOpenReport: (path) => activity.openArtifact("memory", path),
        },
        onInputChange: app.setControlInput,
        onSubmit: (event) => {
          event.preventDefault();
          void runtime.chat.sendChatText(app.controlInput, () => app.setControlInput(""));
        },
        onStop: runtime.chat.stopStreaming,
      }}
      activity={{
        pendingManualCount: presentation.pendingManualActivityCount,
        status: activity.status,
        hasActivity: presentation.hasAgentActivity,
        recentCount: presentation.activityEntries.length,
        loadingProposals: memory.loadingProposals,
        loadingContinuity: continuity.loading,
        error: activity.error,
        items: presentation.activityEntries.map((entry) => (
          <AgentActivityEntryContainer key={entry.id} entry={entry} />
        )),
        onRefresh: refreshActivity,
      }}
      memory={{
        entries: presentation.activityEntries,
        tasks: tasks.controller.tasks,
        taskPanelProps: {
          tasks: tasks.controller.tasks,
          lastReminderNotification: tasks.controller.lastReminderNotification,
          onLocateTask: scrollToWorkflowTarget,
        },
        continuityState: continuity.state,
        pendingContinuityCount: presentation.pendingContinuityCount,
        onLoadContinuity: () => void continuity.load(),
        onLocateWorkflowTarget: scrollToWorkflowTarget,
        workflowItems: presentation.workflowItems,
      }}
      status={{
        modelLabel: connection.settings.settingsStatus?.model_configured
          ? connection.settings.settingsStatus.chat_model || "已配置"
          : connection.hasConnection
            ? "待配置"
            : "连接中",
        knowledgeLabel: presentation.hasVaultInitialized
          ? presentation.hasIndexSignal ? "已就绪" : "待索引"
          : "未绑定",
      }}
      advancedTools={{
        connectionPanel: <ConnectionPanelContainer />,
        wikiWorkflowPanel: <WikiPanelsContainer />,
        settingsPanel: <SettingsPanelContainer />,
      }}
    />
  );
}
