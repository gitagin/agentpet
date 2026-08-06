import { AgentActivityEntryRenderer } from "../features/desktop/AgentActivityEntryRenderer";
import type { AgentActivityLogEntry } from "../services/agentActivity";
import { formatIssueSeverity } from "./appShellUtils";
import { useAppShellRuntime } from "./AppShellRuntimeContext";

export function AgentActivityEntryContainer({ entry }: { entry: AgentActivityLogEntry }) {
  const runtime = useAppShellRuntime();
  return (
    <AgentActivityEntryRenderer
      entry={entry}
      busy={{
        revertingAgentActionIds: runtime.activity.revertingActionIds,
        memoryProposalActionIds: runtime.memory.proposalActionIds,
        continuityActionIds: runtime.continuity.actionIds,
      }}
      formatIssueSeverity={formatIssueSeverity}
      actions={{
        onRevertAgentAction: (action) => void runtime.activity.revert(action),
        onRevealAgentActionTarget: (relativePath, mode) => void runtime.activity.revealTarget(relativePath, mode),
        onActOnMemoryProposal: (proposalId, action) => void runtime.memory.actOnProposal(proposalId, action),
        onActOnContinuityProposal: (proposalId, action) => void runtime.continuity.actOnProposal(proposalId, action),
        onConfirmChatWikiProposal: runtime.wiki.confirmChatWikiProposal,
        onRejectChatWikiProposal: runtime.wiki.rejectChatWikiProposal,
        onToggleChatWikiProposalTarget: runtime.wiki.toggleChatWikiProposalTarget,
        onApplyChatWikiProposal: (messageId, proposalId) =>
          void runtime.wiki.applyChatWikiProposal(messageId, proposalId),
      }}
    />
  );
}
