import { KeyRound } from "lucide-react";
import type { FormEvent } from "react";
import { Panel } from "../../components/layout";
import type { AgentModelId, ModelTestResponse } from "../../types";
import type { AgentModelDraft } from "../../services/agentModelDrafts";
import { AgentConfigForm } from "./AgentConfigForm";
import type { LastIndexRun } from "./settingsTypes";
import { VaultBindingSection } from "./VaultBindingSection";

type SettingsPanelProps = {
  agentModelDrafts: AgentModelDraft[];
  agentModelTestResults: Record<string, ModelTestResponse | undefined>;
  savingAgentModelIds: Set<string>;
  testingAgentModelIds: Set<string>;
  loadingSettingsStatus: boolean;
  vaultId: string | null;
  vaultPath: string;
  lastIndexRun: LastIndexRun | null;
  indexingVault: boolean;
  canSelectVaultDirectory: boolean;
  onRefreshSettings: () => void;
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
  agentModelDrafts,
  agentModelTestResults,
  savingAgentModelIds,
  testingAgentModelIds,
  loadingSettingsStatus,
  vaultId,
  vaultPath,
  lastIndexRun,
  indexingVault,
  canSelectVaultDirectory,
  onRefreshSettings,
  onUpdateAgentModelDraft,
  onSaveAgentModel,
  onTestAgentModel,
  onVaultPathChange,
  onSelectVaultDirectory,
  onBindVault,
  onLoadVaultStatus,
  onRebuildIndex,
}: SettingsPanelProps) {
  return (
    <Panel id="settings-panel" icon={<KeyRound size={18} />} title="Agent / Obsidian 设置">
      <AgentConfigForm
        drafts={agentModelDrafts}
        testResults={agentModelTestResults}
        savingIds={savingAgentModelIds}
        testingIds={testingAgentModelIds}
        loadingSettingsStatus={loadingSettingsStatus}
        onRefreshSettings={onRefreshSettings}
        onUpdateDraft={onUpdateAgentModelDraft}
        onSaveAgentModel={onSaveAgentModel}
        onTestAgentModel={onTestAgentModel}
      />
      <VaultBindingSection
        vaultId={vaultId}
        vaultPath={vaultPath}
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
