import { KeyRound } from "lucide-react";
import type { FormEvent } from "react";
import { Panel } from "../../components/layout";
import type { AgentModelId, ModelTestResponse } from "../../types";
import type { AgentModelDraft } from "../../services/agentModelDrafts";
import type { DesktopApi } from "../../services/desktopApi";
import { AgentConfigForm } from "./AgentConfigForm";
import { GlobalModelCard } from "./GlobalModelCard";
import { ModelHealthBanner } from "./ModelHealthBanner";
import type { AsyncStatus, GlobalModelDraft, LastIndexRun, NegotiationSettingsDraft } from "./settingsTypes";
import { VaultBindingSection } from "./VaultBindingSection";

type SettingsPanelProps = {
  api: DesktopApi;
  agentModelDrafts: AgentModelDraft[];
  agentModelTestResults: Record<string, ModelTestResponse | undefined>;
  globalModelDraft: GlobalModelDraft;
  globalModelSaveStatus: AsyncStatus;
  globalModelTestResult?: ModelTestResponse;
  globalModelTestStatus: AsyncStatus;
  negotiationSettingsDraft: NegotiationSettingsDraft;
  negotiationSettingsSaveStatus: AsyncStatus;
  savingAgentModelIds: Set<string>;
  testingAgentModelIds: Set<string>;
  loadingSettingsStatus: boolean;
  vaultId: string | null;
  vaultPath: string;
  lastIndexRun: LastIndexRun | null;
  indexingVault: boolean;
  canSelectVaultDirectory: boolean;
  onRefreshSettings: () => void;
  onUpdateGlobalModelDraft: (patch: Partial<GlobalModelDraft>) => void;
  onSaveGlobalModel: () => void;
  onTestGlobalModel: () => void;
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
  negotiationSettingsDraft,
  negotiationSettingsSaveStatus,
  savingAgentModelIds,
  testingAgentModelIds,
  loadingSettingsStatus,
  vaultId,
  vaultPath,
  lastIndexRun,
  indexingVault,
  canSelectVaultDirectory,
  onRefreshSettings,
  onUpdateGlobalModelDraft,
  onSaveGlobalModel,
  onTestGlobalModel,
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
  return (
    <Panel id="settings-panel" icon={<KeyRound size={18} />} title="Agent / Obsidian 设置">
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
      <details className="advanced-agent-model-settings">
        <summary>
          <strong>独立智能体模型配置（高级）</strong>
          <span>留空则使用全局模型。你可以为不同智能体分配不同模型以优化成本和性能。</span>
        </summary>
        <section className="stack" aria-label="多轮协商运行时设置">
          <div className="section-heading">
            <strong>多轮协商</strong>
            <span>开启后，运行时会在答复前进行多轮评审与整理；关闭后使用原始单轮路由。</span>
          </div>
          <label>
            <span>启用多轮协商</span>
            <input
              type="checkbox"
              checked={negotiationSettingsDraft.use_negotiation}
              disabled={loadingSettingsStatus || negotiationSettingsSaveStatus === "loading"}
              onChange={(event) =>
                onUpdateNegotiationSettingsDraft({ use_negotiation: event.currentTarget.checked })
              }
            />
          </label>
          <label>
            <span>最大协商轮次</span>
            <input
              type="number"
              min={2}
              max={10}
              step={1}
              value={negotiationSettingsDraft.max_rounds}
              disabled={
                loadingSettingsStatus ||
                negotiationSettingsSaveStatus === "loading" ||
                !negotiationSettingsDraft.use_negotiation
              }
              onChange={(event) =>
                onUpdateNegotiationSettingsDraft({ max_rounds: Number.parseInt(event.currentTarget.value, 10) || 2 })
              }
            />
          </label>
          <div className="button-row">
            <button
              type="button"
              onClick={onSaveNegotiationSettings}
              disabled={loadingSettingsStatus || negotiationSettingsSaveStatus === "loading"}
            >
              {negotiationSettingsSaveStatus === "loading" ? "正在保存" : "保存多轮协商设置"}
            </button>
          </div>
          {negotiationSettingsSaveStatus === "success" ? <p className="field-note">多轮协商设置已保存。</p> : null}
          {negotiationSettingsSaveStatus === "error" ? <p className="field-note error">多轮协商设置保存失败。</p> : null}
        </section>
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
