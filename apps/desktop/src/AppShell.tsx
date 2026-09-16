import { useFirstUseOnboarding } from "./features/onboarding/useFirstUseOnboarding";
import { useProactiveHabitLoop } from "./features/habitLoop/useProactiveHabitLoop";
import { useWiki } from "./features/wiki/useWiki";
import { useConfirmationDialog } from "./hooks/useConfirmationDialog";
import { AppShellRuntimeProvider } from "./appShell/AppShellRuntimeContext";
import { AppShellView } from "./appShell/AppShellView";
import { useAppState } from "./appShell/useAppState";
import { useConnectionSettingsDomain } from "./appShell/useConnectionSettingsDomain";
import { useTaskDomain } from "./appShell/useTaskDomain";
import { useAgentActivityDomain } from "./appShell/useAgentActivityDomain";
import { useMemoryDomain } from "./appShell/useMemoryDomain";
import { useContinuityDomain } from "./appShell/useContinuityDomain";
import { useReflectionDomain } from "./appShell/useReflectionDomain";
import { usePetDomain } from "./appShell/usePetDomain";
import { useChatStreamingDomain } from "./appShell/useChatStreamingDomain";
import { useResetDomain } from "./appShell/useResetDomain";

const PET_BUBBLE_PROACTIVE_HIDE_DELAY_MS = 11_000;

export function AppShell() {
  const { confirm, confirmationDialog } = useConfirmationDialog();
  const app = useAppState();
  const connection = useConnectionSettingsDomain({ onNotice: app.setNotice });
  const tasks = useTaskDomain({
    api: connection.connection.api,
    desktopHostMode: app.routing.desktopHostMode,
    windowMode: app.routing.windowMode,
    sidecarConnected: connection.sidecarConnected,
    onNotice: app.setNotice,
  });
  const activity = useAgentActivityDomain({
    api: connection.connection.api,
    conversationId: app.conversationId,
    sidecarConnected: connection.sidecarConnected,
    streaming: app.streaming,
    setMessages: app.setMessages,
    setWindowMode: app.routing.setWindowMode,
    onNotice: app.setNotice,
    confirm,
  });
  const memory = useMemoryDomain({
    api: connection.connection.api,
    lastIndexRun: connection.settings.lastIndexRun,
    diagnostics: app.diagnostics,
    onNotice: app.setNotice,
    onAgentActionsRefresh: () => void activity.load({ silent: true }),
  });
  const continuity = useContinuityDomain({
    api: connection.connection.api,
    setMessages: app.setMessages,
    onNotice: app.setNotice,
    onAgentActionsRefresh: () => void activity.load({ silent: true }),
  });
  const reflection = useReflectionDomain({
    api: connection.connection.api,
    enabled: connection.hasConnection,
    onNotice: app.setNotice,
    onAgentActionsRefresh: () => void activity.load({ silent: true }),
  });
  const wiki = useWiki({
    api: connection.connection.api,
    conversationId: app.conversationId,
    diagnostics: app.diagnostics,
    messages: app.messages,
    setMessages: app.setMessages,
    vaultId: connection.settings.vaultId,
    windowMode: app.routing.windowMode,
    onAgentActionsRefresh: () => void activity.load({ silent: true }),
    onLastIndexRun: connection.settings.setLastIndexRun,
    onNotice: app.setNotice,
  });
  const pet = usePetDomain({
    api: connection.connection.api,
    settings: connection.settings.settingsStatus?.tts_settings,
    windowMode: app.routing.windowMode,
    messages: app.messages,
    setMessages: app.setMessages,
    latestContinuitySignal: continuity.latestSignal,
    streamAbortRef: app.streamAbortRef,
    halfbodyPortraitRef: app.halfbodyPortraitRef,
    setPetInputMode: app.setPetInputMode,
    onNotice: app.setNotice,
  });
  const chat = useChatStreamingDomain({
    app,
    connection,
    activity,
    tasks,
    memory,
    continuity,
    reflection,
    wiki,
    pet,
  });
  const reset = useResetDomain({
    app,
    connection,
    activity,
    tasks,
    memory,
    continuity,
    reflection,
    wiki,
    pet,
    confirm,
  });

  useProactiveHabitLoop({
    api: connection.connection.api,
    enabled: app.routing.windowMode === "pet" && connection.hasConnection,
    frequency: connection.settings.automationSettingsDraft.proactive_trigger_frequency,
    blocked:
      app.streaming ||
      pet.chat.inputVisible ||
      pet.chat.bubble.visible ||
      pet.window.petShortcutsVisible ||
      pet.tts.active,
    onTrigger: (response) => {
      const candidate = response.candidate;
      if (!candidate) {
        return;
      }
      pet.chat.showBubble({
        title: candidate.title,
        message: candidate.message,
        tone: "tool",
        phase: "complete",
      });
      pet.chat.scheduleHide(PET_BUBBLE_PROACTIVE_HIDE_DELAY_MS);
    },
  });
  const onboardingPanel = useFirstUseOnboarding({
    connected: connection.hasConnection,
    streaming: app.streaming,
    windowMode: app.routing.windowMode,
    onNotice: app.setNotice,
    onSendMessage: (message, options) => chat.sendChatText(message, () => undefined, options),
  });

  return (
    <AppShellRuntimeProvider
      runtime={{ app, connection, activity, tasks, memory, continuity, reflection, wiki, pet, chat, reset, onboardingPanel }}
    >
      <AppShellView />
      {confirmationDialog}
    </AppShellRuntimeProvider>
  );
}
