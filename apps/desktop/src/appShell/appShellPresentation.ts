import { buildControlWorkflowItems } from "../features/desktop/controlWorkflowItems";
import { resolvePetReplyActionKey } from "../features/pet/petReplyActions";
import { getPetStageView } from "../features/pet/petStageState";
import { buildAgentActivityEntries, isAttentionAgentAction } from "../services/agentActivity";
import { findCitationTargetId } from "./appShellUtils";
import type { AppShellRuntime } from "./AppShellRuntimeContext";

export function buildAppShellPresentation(runtime: AppShellRuntime) {
  const { app, connection, activity, tasks, memory, continuity } = runtime;
  const settings = connection.settings;
  const hasVaultInitialized = Boolean(settings.vaultId || app.diagnostics?.vault.configured);
  const hasIndexSignal = Boolean(
    settings.lastIndexRun ||
      memory.searchResults.length > 0 ||
      app.diagnostics?.recent_index_jobs.some((job) =>
        ["completed", "done", "indexed", "success"].includes(job.status.toLowerCase()),
      ),
  );
  const hasMemoryConfirmed = memory.proposals.some(
    (proposal) => proposal.status === "confirmed" || Boolean(proposal.written_path),
  );
  const pendingContinuityCount = continuity.proposals.filter((proposal) => proposal.status === "pending").length;
  const latestAssistantMessage = app.messages.filter((message) => message.role === "assistant").slice(-1)[0];
  const latestChatEvent = latestAssistantMessage?.events?.slice(-1)[0];
  const activeContinuitySignal = latestAssistantMessage?.continuity_signal || continuity.latestSignal;
  const latestCitation = latestAssistantMessage?.citations?.slice(-1)[0];
  const latestCitationTargetId = latestCitation
    ? findCitationTargetId(latestCitation, memory.searchResults)
    : undefined;
  const activityEntries = buildAgentActivityEntries(
    activity.actions,
    memory.proposals,
    continuity.proposals,
    app.messages,
  );
  const pendingManualActivityCount = activityEntries.filter((entry) => entry.kind !== "agent_action").length;
  const automaticActivityCount = activityEntries.filter(
    (entry) => entry.kind === "agent_action" && !isAttentionAgentAction(entry.action),
  ).length;
  const hasAgentActivity = activityEntries.length > 0;
  const workflowItems = buildControlWorkflowItems({
    agentModelDrafts: settings.agentModelDrafts,
    agentModelTestResults: settings.agentModelTestResults,
    hasVaultInitialized,
    hasIndexSignal,
    lastIndexRun: settings.lastIndexRun,
    hasAgentEventSignal: app.messages.some(
      (message) => (message.events || []).length > 0 || (message.citations || []).length > 0,
    ),
    streaming: app.streaming,
    latestChatEvent,
    latestCitation,
    latestCitationTargetId,
    pendingManualActivityCount,
    hasAgentActivity,
    hasMemoryConfirmed,
    automaticActivityCount,
    hasContinuityState: Boolean(continuity.state?.items.length),
    pendingContinuityCount,
    continuityStateItemCount: continuity.state?.items.length ?? 0,
  });
  const petStage = getPetStageView({
    connected: connection.hasConnection,
    streaming: app.streaming,
    searchResultCount: memory.searchResults.length,
    pendingProposalCount: memory.proposals.filter((proposal) => proposal.status === "pending").length,
    taskCount: tasks.recentTaskStageActive ? Math.max(tasks.controller.tasks.length, 1) : 0,
    diagnosticsReady: Boolean(app.diagnostics),
    continuityState: continuity.state,
    continuitySignal: activeContinuitySignal,
  });
  const petReplyActionKey = connection.hasConnection
    ? resolvePetReplyActionKey(latestAssistantMessage)
    : null;
  const petReplyActionTriggerKey = petReplyActionKey && latestAssistantMessage
    ? [
        latestAssistantMessage.id,
        latestAssistantMessage.status || "",
        (latestAssistantMessage.live2d_action_hints || []).join("|"),
      ].join(":")
    : null;

  return {
    hasVaultInitialized,
    hasIndexSignal,
    pendingContinuityCount,
    latestAssistantMessage,
    activityEntries,
    pendingManualActivityCount,
    hasAgentActivity,
    workflowItems,
    petStage,
    petReplyActionKey,
    petReplyActionTriggerKey,
  };
}

export type AppShellPresentation = ReturnType<typeof buildAppShellPresentation>;
