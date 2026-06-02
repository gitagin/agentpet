import { KeyRound } from "lucide-react";
import type { FormEvent } from "react";
import { Panel } from "../../components/layout";
import type { AgentModelId, ModelTestResponse, VaultStatusResponse } from "../../types";
import type { AgentModelDraft } from "../../services/agentModelDrafts";
import type { DesktopApi } from "../../services/desktopApi";
import { AutomationSettingsCard } from "./AutomationSettingsCard";
import { GlobalModelCard } from "./GlobalModelCard";
import { ModelHealthBanner } from "./ModelHealthBanner";
import type { AsyncStatus, AutomationSettingsDraft, GlobalModelDraft, LastIndexRun, NegotiationSettingsDraft } from "./settingsTypes";
import { VaultBindingSection } from "./VaultBindingSection";

type SettingsPanelProps = {
  api: DesktopApi;
  agentModelDrafts: AgentModelDraft[];
  agentModelTestResults: Record<string, ModelTestResponse | undefined>;
  globalModelDraft: GlobalModelDraft;
  globalModelSaveStatus: AsyncStatus;
  globalModelTestResult?: ModelTestResponse;
  globalModelTestStatus: AsyncStatus;
  automationSettingsDraft: AutomationSettingsDraft;
  automationSettingsSaveStatus: AsyncStatus;
  negotiationSettingsDraft: NegotiationSettingsDraft;
  negotiationSettingsSaveStatus: AsyncStatus;
  savingAgentModelIds: Set<string>;
  testingAgentModelIds: Set<string>;
  loadingSettingsStatus: boolean;
  vaultId: string | null;
  vaultPath: string;
  vaultStatus: VaultStatusResponse | null;
  lastIndexRun: LastIndexRun | null;
  indexingVault: boolean;
  canSelectVaultDirectory: boolean;
  onRefreshSettings: () => void;
  onUpdateGlobalModelDraft: (patch: Partial<GlobalModelDraft>) => void;
  onSaveGlobalModel: () => void;
  onTestGlobalModel: () => void;
  onUpdateAutomationSettingsDraft: (patch: Partial<AutomationSettingsDraft>) => void;
  onSaveAutomationSettings: () => void;
  onUpdateNegotiationSettingsDraft: (patch: Partial<NegotiationSettingsDraft>) => void;
  onSaveNegotiationSettings: () => void;
  onUpdateAgentModelDraft: (agentId: AgentModelId, patch: Partial<AgentModelDraft>) => void;
  onSaveAgentModel: (agentId: AgentModelId) => void;
  onTestAgentModel: (agentId: AgentModelId) => void;
  onVaultPathChange: (vaultPath: string) => void;
  onSelectVaultDirectory: () => void;
  onBindVault: (event: FormEvent) => void;
  onLoadVaultStatus: () => void;
  onRebuildIndex: () => void;
};

export function SettingsPanel({
  api,
  agentModelDrafts,
  agentModelTestResults,
  globalModelDraft,
  globalModelSaveStatus,
  globalModelTestResult,
  globalModelTestStatus,
  automationSettingsDraft,
  automationSettingsSaveStatus,
  negotiationSettingsDraft,
  negotiationSettingsSaveStatus,
  savingAgentModelIds,
  testingAgentModelIds,
  loadingSettingsStatus,
  vaultId,
  vaultPath,
  vaultStatus,
  lastIndexRun,
  indexingVault,
  canSelectVaultDirectory,
  onRefreshSettings,
  onUpdateGlobalModelDraft,
  onSaveGlobalModel,
  onTestGlobalModel,
  onUpdateAutomationSettingsDraft,
  onSaveAutomationSettings,
  onUpdateNegotiationSettingsDraft,
  onSaveNegotiationSettings,
  onUpdateAgentModelDraft,
  onSaveAgentModel,
  onTestAgentModel,
  onVaultPathChange,
  onSelectVaultDirectory,
  onBindVault,
  onLoadVaultStatus,
  onRebuildIndex,
}: SettingsPanelProps) {
  void agentModelDrafts;
  void agentModelTestResults;
  void negotiationSettingsDraft;
  void negotiationSettingsSaveStatus;
  void savingAgentModelIds;
  void testingAgentModelIds;
  void onUpdateNegotiationSettingsDraft;
  void onSaveNegotiationSettings;
  void onUpdateAgentModelDraft;
  void onSaveAgentModel;
  void onTestAgentModel;

  return (
    <Panel id="settings-panel" icon={<KeyRound size={18} />} title="配置" className="settings-panel-compact">
      <section className="settings-intro" aria-label="配置引导">
        <div>
          <p className="eyebrow">开始使用只需要两步</p>
          <h3>先让桌宠能聊天，再选择它记忆内容的位置。</h3>
        </div>
        <ol>
          <li>配置 AI 模型</li>
          <li>绑定记忆库</li>
        </ol>
      </section>
      <ModelHealthBanner api={api} />
      <GlobalModelCard
        draft={globalModelDraft}
        saveStatus={globalModelSaveStatus}
        testResult={globalModelTestResult}
        testStatus={globalModelTestStatus}
        onUpdateDraft={onUpdateGlobalModelDraft}
        onSave={onSaveGlobalModel}
        onTest={onTestGlobalModel}
      />
      <AutomationSettingsCard
        draft={automationSettingsDraft}
        saveStatus={automationSettingsSaveStatus}
        loadingSettingsStatus={loadingSettingsStatus}
        onUpdateDraft={onUpdateAutomationSettingsDraft}
        onSave={onSaveAutomationSettings}
        onRefresh={onRefreshSettings}
      />
      <VaultBindingSection
        vaultId={vaultId}
        vaultPath={vaultPath}
        vaultStatus={vaultStatus}
        lastIndexRun={lastIndexRun}
        indexingVault={indexingVault}
        canSelectVaultDirectory={canSelectVaultDirectory}
        onVaultPathChange={onVaultPathChange}
        onSelectVaultDirectory={onSelectVaultDirectory}
        onBindVault={onBindVault}
        onLoadVaultStatus={onLoadVaultStatus}
        onRebuildIndex={onRebuildIndex}
      />
    </Panel>
  );
}
