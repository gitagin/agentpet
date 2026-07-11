import { Bot, FolderOpen, RefreshCw, ShieldCheck, SlidersHorizontal, Volume2 } from "lucide-react";
import type { FormEvent } from "react";
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
import { productCopy } from "../../productCopy";

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
    <section id="settings-panel" className="settings-panel-compact settings-panel-grid" aria-label="设置">
      <section className="settings-intro" aria-label="设置引导">
        <div className="settings-intro-copy">
          <p className="eyebrow">{productCopy.settingsPage.eyebrow}</p>
          <h3>{productCopy.settingsPage.title}</h3>
          <p className="settings-intro-description">{productCopy.settingsPage.description}</p>
          <p className="settings-scroll-note">
            <SlidersHorizontal size={14} />
            向下滑动可以继续设置自动整理、语音和保存位置。
          </p>
        </div>
        <ol className="settings-intro-steps">
          <li>{productCopy.settingsPage.stepConnect}</li>
          <li>{productCopy.settingsPage.stepSave}</li>
          <li>{productCopy.settingsPage.stepAutomation}</li>
          <li>{productCopy.settingsPage.stepVoice}</li>
        </ol>
        <div className="guided-trial-actions settings-guided-trials" aria-label="设置快捷操作">
          <button type="button" className="secondary" onClick={onTestGlobalModel} disabled={globalModelTestStatus === "loading"}>
            <Bot size={16} />
            {productCopy.settingsPage.testConnection}
          </button>
          <button type="button" className="secondary" onClick={onSelectVaultDirectory} disabled={!canSelectVaultDirectory}>
            <FolderOpen size={16} />
            选择保存位置
          </button>
          <button type="button" className="secondary" onClick={onRefreshSettings} disabled={loadingSettingsStatus}>
            <RefreshCw size={16} />
            {productCopy.settingsPage.refresh}
          </button>
        </div>
      </section>
      <section className="settings-purpose-grid" aria-label="这页可以做什么">
        <article className="settings-purpose-card">
          <span className="settings-purpose-icon">
            <Bot size={16} />
          </span>
          <span>
            <strong>对话能力</strong>
            <small>连接模型服务，让聊天、总结和整理记忆能正常工作。</small>
          </span>
        </article>
        <article className="settings-purpose-card">
          <span className="settings-purpose-icon">
            <FolderOpen size={16} />
          </span>
          <span>
            <strong>保存位置</strong>
            <small>选择本机文件夹，决定长期记忆和资料放在哪里。</small>
          </span>
        </article>
        <article className="settings-purpose-card">
          <span className="settings-purpose-icon">
            <ShieldCheck size={16} />
          </span>
          <span>
            <strong>自动整理</strong>
            <small>控制低风险整理、主动提醒和隐私边界。</small>
          </span>
        </article>
        <article className="settings-purpose-card">
          <span className="settings-purpose-icon">
            <Volume2 size={16} />
          </span>
          <span>
            <strong>语音与高级</strong>
            <small>调整朗读、缓存和少数高级能力分工。</small>
          </span>
        </article>
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
          <strong>{productCopy.settingsPage.advancedModelTitle}</strong>
          <span>{productCopy.settingsPage.advancedModelDescription}</span>
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
    </section>
  );
}
