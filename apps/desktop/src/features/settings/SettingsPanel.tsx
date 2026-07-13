import { Bot, FolderOpen, RefreshCw, ShieldCheck, SlidersHorizontal } from "lucide-react";
import type { FormEvent } from "react";
import type { ModelTestResponse, VaultStatusResponse } from "../../types";
import type { DesktopApi } from "../../services/desktopApi";
import { AutomationSettingsCard } from "./AutomationSettingsCard";
import { GlobalModelCard } from "./GlobalModelCard";
import { ModelHealthBanner } from "./ModelHealthBanner";
import { MemoryResetCard } from "./MemoryResetCard";
import type {
  AsyncStatus,
  AutomationSettingsDraft,
  GlobalModelDraft,
  LastIndexRun,
} from "./settingsTypes";
import { VaultBindingSection } from "./VaultBindingSection";
import { productCopy } from "../../productCopy";

type SettingsPanelProps = {
  api: DesktopApi;
  globalModelDraft: GlobalModelDraft;
  globalModelSaveStatus: AsyncStatus;
  globalModelTestResult?: ModelTestResponse;
  globalModelTestStatus: AsyncStatus;
  automationSettingsDraft: AutomationSettingsDraft;
  automationSettingsSaveStatus: AsyncStatus;
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
  onVaultPathChange: (vaultPath: string) => void;
  onSelectVaultDirectory: () => void;
  onBindVault: (event: FormEvent) => void;
  onLoadVaultStatus: () => void;
  onRebuildIndex: () => void;
  resettingMemoryState: boolean;
  onResetMemoryState: () => void;
};

export function SettingsPanel({
  api,
  globalModelDraft,
  globalModelSaveStatus,
  globalModelTestResult,
  globalModelTestStatus,
  automationSettingsDraft,
  automationSettingsSaveStatus,
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
  onVaultPathChange,
  onSelectVaultDirectory,
  onBindVault,
  onLoadVaultStatus,
  onRebuildIndex,
  resettingMemoryState,
  onResetMemoryState,
}: SettingsPanelProps) {
  return (
    <section id="settings-panel" className="settings-panel-compact settings-panel-grid" aria-label="设置">
      <section className="settings-intro" aria-label="设置引导">
        <div className="settings-intro-copy">
          <p className="eyebrow">{productCopy.settingsPage.eyebrow}</p>
          <h3>{productCopy.settingsPage.title}</h3>
          <p className="settings-intro-description">{productCopy.settingsPage.description}</p>
          <p className="settings-scroll-note">
            <SlidersHorizontal size={14} />
            向下滑动可以继续设置自动整理、隐私边界和保存位置。
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
            <ShieldCheck size={16} />
          </span>
          <span>
            <strong>有界协作</strong>
            <small>复杂问题最多复核两轮，失败时回退到稳定主链。</small>
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
      <MemoryResetCard resetting={resettingMemoryState} onReset={onResetMemoryState} />
    </section>
  );
}
