import { Bot, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import type { AgentModelId, ModelTestResponse } from "../../types";
import {
  agentModelDefinitions,
  hasUnsavedAgentModelDraft,
  isSupportedProviderDraft,
  type AgentModelDraft,
} from "../../services/agentModelDrafts";
import { formatBooleanStatus, formatModelTestResult } from "./settingsFormatters";
import type { GlobalModelDraft } from "./settingsTypes";

type AgentConfigFormProps = {
  drafts: AgentModelDraft[];
  globalModelDraft: GlobalModelDraft;
  testResults: Record<string, ModelTestResponse | undefined>;
  savingIds: Set<string>;
  testingIds: Set<string>;
  loadingSettingsStatus: boolean;
  onRefreshSettings: () => void;
  onUpdateDraft: (agentId: AgentModelId, patch: Partial<AgentModelDraft>) => void;
  onSaveAgentModel: (agentId: AgentModelId) => void;
  onTestAgentModel: (agentId: AgentModelId) => void;
};

export function AgentConfigForm({
  drafts,
  globalModelDraft,
  testResults,
  savingIds,
  testingIds,
  loadingSettingsStatus,
  onRefreshSettings,
  onUpdateDraft,
  onSaveAgentModel,
  onTestAgentModel,
}: AgentConfigFormProps) {
  return (
    <section className="agent-model-section" aria-label="高级 Agent 模型路由">
      <div className="section-heading">
        <strong>5 个核心 Agent</strong>
        <span>默认继承全局模型；只有某个职责需要单独优化时再覆盖。</span>
      </div>
      <button type="button" className="secondary" onClick={onRefreshSettings} disabled={loadingSettingsStatus}>
        {loadingSettingsStatus ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
        刷新状态
      </button>
      <div className="agent-model-list">
        {drafts.map((draft) => {
          const definition = agentModelDefinitions.find((agent) => agent.id === draft.agent_id);
          const testResult = testResults[draft.agent_id];
          const saving = savingIds.has(draft.agent_id);
          const testing = testingIds.has(draft.agent_id);
          const hasUnsavedDraft = hasUnsavedAgentModelDraft(draft);
          const usingGlobalModel = !draft.enabled;
          const providerUnsupported = !usingGlobalModel && Boolean(draft.provider.trim()) && !isSupportedProviderDraft(draft.provider);
          return (
            <article key={draft.agent_id} className="agent-model-row">
              <div className="agent-model-title">
                <strong>{definition?.label || draft.agent_id}</strong>
                {definition?.outcomeLabel ? <em>{definition.outcomeLabel}</em> : null}
                <span>{definition?.description}</span>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={usingGlobalModel}
                    onChange={(event) => onUpdateDraft(draft.agent_id, { enabled: !event.target.checked })}
                  />
                  使用全局模型
                </label>
                {usingGlobalModel ? (
                  <span className="agent-model-inherited">
                    继承：{globalModelDraft.provider || "未配置提供方"} / {globalModelDraft.base_url || "未配置接口地址"} / {globalModelDraft.model || "未配置模型"}
                  </span>
                ) : null}
              </div>
              <label>
                <span>提供方</span>
                <input
                  value={draft.provider}
                  onChange={(event) => onUpdateDraft(draft.agent_id, { provider: event.target.value })}
                  placeholder="openai-compatible"
                  disabled={usingGlobalModel}
                />
              </label>
              <label>
                <span>接口地址</span>
                <input
                  value={draft.base_url}
                  onChange={(event) => onUpdateDraft(draft.agent_id, { base_url: event.target.value })}
                  disabled={usingGlobalModel}
                />
              </label>
              <label>
                <span>模型</span>
                <input
                  value={draft.model}
                  onChange={(event) => onUpdateDraft(draft.agent_id, { model: event.target.value })}
                  disabled={usingGlobalModel}
                />
              </label>
              <label>
                <span>密钥</span>
                <input
                  value={draft.api_key}
                  onChange={(event) => onUpdateDraft(draft.agent_id, { api_key: event.target.value })}
                  placeholder={draft.masked || "请输入密钥"}
                  type="password"
                  disabled={usingGlobalModel}
                />
              </label>
              <div className="agent-model-actions">
                <button type="button" onClick={() => onSaveAgentModel(draft.agent_id)} disabled={saving}>
                  {saving ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />}
                  保存
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onTestAgentModel(draft.agent_id)}
                  disabled={testing || hasUnsavedDraft || providerUnsupported}
                >
                  {testing ? <Loader2 className="spin" size={16} /> : <Bot size={16} />}
                  试连
                </button>
              </div>
              <dl className="agent-model-status">
                <div>
                  <dt>配置状态</dt>
                  <dd>{usingGlobalModel ? "使用全局模型" : formatBooleanStatus(draft.configured)}</dd>
                </div>
                <div>
                  <dt>密钥状态</dt>
                  <dd>{usingGlobalModel ? "继承全局密钥" : draft.masked || "未配置"}</dd>
                </div>
                <div>
                  <dt>试连结果</dt>
                  <dd>
                    {providerUnsupported
                      ? "提供方只支持 openai-compatible。"
                      : hasUnsavedDraft
                        ? "有未保存改动，请先保存。"
                        : testResult
                          ? formatModelTestResult(testResult)
                          : "尚未试连"}
                  </dd>
                </div>
              </dl>
            </article>
          );
        })}
      </div>
    </section>
  );
}
