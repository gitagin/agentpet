import { Bot, FolderOpen, KeyRound, RefreshCw } from "lucide-react";
import type { FormEvent } from "react";
import { Panel } from "../../components/layout";
import type { AgentModelId, ModelTestResponse, TtsSettingsResponse, VaultStatusResponse } from "../../types";
import type { AgentModelDraft } from "../../services/agentModelDrafts";
import type { DesktopApi } from "../../services/desktopApi";
import { AutomationSettingsCard } from "./AutomationSettingsCard";
import { AgentConfigForm } from "./AgentConfigForm";
import { GlobalModelCard } from "./GlobalModelCard";
import { ModelHealthBanner } from "./ModelHealthBanner";
import type {
  AsyncStatus,
  AutomationSettingsDraft,
  GlobalModelDraft,
  LastIndexRun,
  NegotiationSettingsDraft,
  TtsSettingsDraft,
} from "./settingsTypes";
import { TtsSettingsCard } from "./TtsSettingsCard";
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
  ttsSettingsDraft: TtsSettingsDraft;
  ttsSettingsSaveStatus: AsyncStatus;
  ttsSettingsStatus?: TtsSettingsResponse | null;
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
  onUpdateTtsSettingsDraft: (patch: Partial<TtsSettingsDraft>) => void;
  onSaveTtsSettings: (apiKey?: string) => void;
  onClearTtsCache?: () => void;
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
  ttsSettingsDraft,
  ttsSettingsSaveStatus,
  ttsSettingsStatus,
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
  onUpdateTtsSettingsDraft,
  onSaveTtsSettings,
  onClearTtsCache,
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
  void negotiationSettingsDraft;
  void negotiationSettingsSaveStatus;
  void onUpdateNegotiationSettingsDraft;
  void onSaveNegotiationSettings;

  return (
    <Panel id="settings-panel" icon={<KeyRound size={18} />} title="设置" className="settings-panel-compact">
      <section className="settings-intro" aria-label="设置引导">
        <div>
          <p className="eyebrow">先能对话，再决定保存</p>
          <h3>连接全局模型后就能开始；需要精调时再为 5 个核心 Agent 单独覆盖模型。</h3>
        </div>
        <ol>
          <li>配置模型</li>
          <li>选择保存位置</li>
        </ol>
        <div className="guided-trial-actions settings-guided-trials" aria-label="设置快捷操作">
          <button type="button" className="secondary" onClick={onTestGlobalModel} disabled={globalModelTestStatus === "loading"}>
            <Bot size={16} />
            测试模型
          </button>
          <button type="button" className="secondary" onClick={onSelectVaultDirectory} disabled={!canSelectVaultDirectory}>
            <FolderOpen size={16} />
            选择保存位置
          </button>
          <button type="button" className="secondary" onClick={onRefreshSettings} disabled={loadingSettingsStatus}>
            <RefreshCw size={16} />
            刷新设置
          </button>
        </div>
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
      <details className="agent-model-section settings-card advanced-agent-model-settings">
        <summary>
          <strong>高级 Agent 模型路由</strong>
          <span>可选覆盖 5 个核心 Agent；大多数情况下保持全局模型即可。</span>
        </summary>
        <AgentConfigForm
          drafts={agentModelDrafts}
          globalModelDraft={globalModelDraft}
          testResults={agentModelTestResults}
          savingIds={savingAgentModelIds}
          testingIds={testingAgentModelIds}
          loadingSettingsStatus={loadingSettingsStatus}
          onRefreshSettings={onRefreshSettings}
          onUpdateDraft={onUpdateAgentModelDraft}
          onSaveAgentModel={onSaveAgentModel}
          onTestAgentModel={onTestAgentModel}
        />
      </details>
      <AutomationSettingsCard
        draft={automationSettingsDraft}
        saveStatus={automationSettingsSaveStatus}
        loadingSettingsStatus={loadingSettingsStatus}
        onUpdateDraft={onUpdateAutomationSettingsDraft}
        onSave={onSaveAutomationSettings}
        onRefresh={onRefreshSettings}
      />
      <TtsSettingsCard
        draft={ttsSettingsDraft}
        saveStatus={ttsSettingsSaveStatus}
        loadingSettingsStatus={loadingSettingsStatus}
        status={ttsSettingsStatus}
        keyMasked={ttsSettingsStatus?.key_masked}
        keyConfigured={ttsSettingsStatus?.key_configured}
        onUpdateDraft={onUpdateTtsSettingsDraft}
        onSave={onSaveTtsSettings}
        onRefresh={onRefreshSettings}
        onClearCache={onClearTtsCache}
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
