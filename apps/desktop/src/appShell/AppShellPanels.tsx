import { ConnectionManagementPanel } from "../features/desktop/ConnectionManagementPanel";
import { WikiManagementPanels } from "../features/desktop/WikiManagementPanels";
import { SettingsPanel } from "../features/settings/SettingsPanel";
import StageView from "../views/StageView";
import { formatIssueSeverity } from "./appShellUtils";
import { buildAppShellPresentation } from "./appShellPresentation";
import { useAppShellRuntime } from "./AppShellRuntimeContext";

export function ConnectionPanelContainer() {
  const { connection, reset } = useAppShellRuntime();
  const state = connection.connection;
  return (
    <ConnectionManagementPanel
      settings={state.settings}
      onSettingsChange={state.setSettings}
      onSaveSettings={state.persistSettings}
      onCheckHealth={() => void state.checkHealth()}
      checkingHealth={state.checkingHealth}
      isElectronRuntime={connection.isElectronRuntime}
      health={state.health}
      businessAuthStatus={state.businessAuthStatus}
      businessAuthMessage={state.businessAuthMessage}
      resettingLocalState={reset.resettingLocalState}
      onResetLocalState={() => void reset.resetLocalState()}
    />
  );
}

export function WikiPanelsContainer() {
  const runtime = useAppShellRuntime();
  const presentation = buildAppShellPresentation(runtime);

  function fillKnowledgeSnippetTrial() {
    runtime.app.routing.setWindowMode("world");
    runtime.wiki.onDraftChange({
      title: "决策记忆",
      content: "决策记忆会把项目选择、理由和后续任务放在一起，方便之后复盘时解释为什么选择了某条路径。",
      source_type: "concept",
      source_uri: "trial:decision-memory",
      target_path: "Wiki/Concepts/Decision-Memory.md",
      tags: ["concept", "trial"],
    });
    runtime.wiki.setTagInput("concept, trial");
  }

  return (
    <WikiManagementPanels
      wiki={runtime.wiki}
      context={{
        vaultConfigured: presentation.hasVaultInitialized,
        indexRequired:
          presentation.hasVaultInitialized &&
          !presentation.hasIndexSignal &&
          !runtime.wiki.indexStatus,
        formatIssueSeverity,
        onTryKnowledgeSnippet: fillKnowledgeSnippetTrial,
      }}
    />
  );
}

export function SettingsPanelContainer() {
  const { connection, reset } = useAppShellRuntime();
  const settings = connection.settings;
  return (
    <SettingsPanel
      model={{
        api: connection.connection.api,
        globalModelDraft: settings.globalModelDraft,
        globalModelSaveStatus: settings.globalModelSaveStatus,
        globalModelTestResult: settings.globalModelTestResult,
        globalModelTestStatus: settings.globalModelTestStatus,
        embeddingDraft: settings.embeddingDraft,
        embeddingSaveStatus: settings.embeddingSaveStatus,
        embeddingTestStatus: settings.embeddingTestStatus,
        embeddingTestResult: settings.embeddingTestResult,
        onUpdateEmbeddingDraft: settings.updateEmbeddingDraft,
        onSaveEmbedding: () => void settings.saveEmbedding(),
        onTestEmbedding: () => void settings.testEmbeddingConnection(),
        automationSettingsDraft: settings.automationSettingsDraft,
        automationSettingsSaveStatus: settings.automationSettingsSaveStatus,
        ttsDraft: settings.ttsSettingsDraft,
        ttsSaveStatus: settings.ttsSettingsSaveStatus,
        ttsStatus: settings.settingsStatus?.tts_settings ?? null,
        ttsKeyMasked: settings.settingsStatus?.tts_settings?.key_masked ?? null,
        ttsKeyConfigured: settings.settingsStatus?.tts_settings?.key_configured ?? false,
        onUpdateTtsDraft: settings.updateTtsSettingsDraft,
        onSaveTts: (apiKey) => void settings.saveTtsSettings(apiKey),
        onRefreshTts: () => void settings.loadSettingsStatus(),
        onClearTtsCache: () => void settings.clearTtsCache(),
        loadingSettingsStatus: settings.loadingSettingsStatus,
        settingsStatusLoadState: settings.settingsStatusLoadState,
        vaultId: settings.vaultId,
        vaultPath: settings.vaultPath,
        vaultStatus: settings.vaultStatus,
        lastIndexRun: settings.lastIndexRun,
        indexingVault: settings.indexingVault,
        canSelectVaultDirectory: connection.canSelectVaultDirectory,
        onRefreshSettings: () => void settings.loadSettingsStatus(),
        onUpdateGlobalModelDraft: settings.updateGlobalModelDraft,
        onSaveGlobalModel: () => void settings.saveGlobalModel(),
        onTestGlobalModel: () => void settings.testGlobalModelConnection(),
        onUpdateAutomationSettingsDraft: settings.updateAutomationSettingsDraft,
        onSaveAutomationSettings: () => void settings.saveAutomationSettings(),
        onVaultPathChange: settings.setVaultPath,
        onSelectVaultDirectory: () => void settings.selectVaultDirectory(),
        onBindVault: settings.bindVault,
        onLoadVaultStatus: () => void settings.loadVaultStatus(),
        onRebuildIndex: () => void settings.rebuildIndex(),
        resettingMemoryState: reset.resettingMemoryState,
        onResetMemoryState: () => void reset.resetStoredMemoryState(),
      }}
    />
  );
}

export function StageViewContainer() {
  const runtime = useAppShellRuntime();
  const isStageHostWindow = runtime.app.routing.desktopHostMode === "stage";
  return (
    <StageView
      connected={runtime.connection.hasConnection}
      streaming={runtime.app.streaming}
      bubble={runtime.pet.chat.bubble}
      onSendChat={runtime.chat.sendChatText}
      onStopStreaming={runtime.chat.stopStreaming}
      onPreviousPage={runtime.pet.chat.retreatPageManually}
      onAdvancePage={runtime.pet.chat.advancePageManually}
      onPausePaging={runtime.pet.chat.pausePaging}
      onResumePaging={runtime.pet.chat.resumePaging}
      ttsSpeaking={runtime.pet.tts.speaking}
      active={!isStageHostWindow || runtime.app.routing.windowMode === "stage"}
      api={runtime.connection.connection.api}
    />
  );
}
