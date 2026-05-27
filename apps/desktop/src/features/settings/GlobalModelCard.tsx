import { Bot, Loader2, ShieldCheck } from "lucide-react";
import type { ModelTestResponse } from "../../types";
import { isSupportedProviderDraft } from "../../services/agentModelDrafts";
import { formatBooleanStatus, formatModelTestResult } from "./settingsFormatters";
import type { AsyncStatus, GlobalModelDraft } from "./settingsTypes";

type GlobalModelCardProps = {
  draft: GlobalModelDraft;
  saveStatus: AsyncStatus;
  testStatus: AsyncStatus;
  testResult?: ModelTestResponse;
  onUpdateDraft: (patch: Partial<GlobalModelDraft>) => void;
  onSave: () => void;
  onTest: () => void;
};

function hasUnsavedGlobalModelDraft(draft: GlobalModelDraft): boolean {
  return (
    draft.provider.trim() !== draft.saved_provider ||
    draft.base_url.trim() !== draft.saved_base_url ||
    draft.model.trim() !== draft.saved_model ||
    Boolean(draft.api_key.trim())
  );
}

export function GlobalModelCard({
  draft,
  saveStatus,
  testStatus,
  testResult,
  onUpdateDraft,
  onSave,
  onTest,
}: GlobalModelCardProps) {
  const saving = saveStatus === "loading";
  const testing = testStatus === "loading";
  const providerUnsupported = Boolean(draft.provider.trim()) && !isSupportedProviderDraft(draft.provider);
  const hasUnsavedDraft = hasUnsavedGlobalModelDraft(draft);

  return (
    <section className="agent-model-section" aria-label="全局模型配置">
      <div className="section-heading">
        <strong>全局模型</strong>
        <span>未配置独立模型的智能体将使用此配置。</span>
      </div>
      <article className="agent-model-row">
        <div className="agent-model-title">
          <strong>默认模型配置</strong>
          <span>保存提供方、接口地址、模型和密钥后，可用于全局聊天与智能体回退。</span>
        </div>
        <label>
          <span>提供方</span>
          <input
            value={draft.provider}
            onChange={(event) => onUpdateDraft({ provider: event.target.value })}
            placeholder="openai-compatible"
          />
        </label>
        <label>
          <span>接口地址</span>
          <input value={draft.base_url} onChange={(event) => onUpdateDraft({ base_url: event.target.value })} />
        </label>
        <label>
          <span>模型</span>
          <input value={draft.model} onChange={(event) => onUpdateDraft({ model: event.target.value })} />
        </label>
        <label>
          <span>密钥</span>
          <input
            value={draft.api_key}
            onChange={(event) => onUpdateDraft({ api_key: event.target.value })}
            placeholder="留空则仅保存模型参数"
            type="password"
          />
        </label>
        <div className="agent-model-actions">
          <button type="button" onClick={onSave} disabled={saving}>
            {saving ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />}
            保存
          </button>
          <button
            type="button"
            className="secondary"
            onClick={onTest}
            disabled={testing || hasUnsavedDraft || providerUnsupported}
          >
            {testing ? <Loader2 className="spin" size={16} /> : <Bot size={16} />}
            测试连接
          </button>
        </div>
        <dl className="agent-model-status">
          <div>
            <dt>配置状态</dt>
            <dd>{formatBooleanStatus(draft.configured)}</dd>
          </div>
          <div>
            <dt>保存状态</dt>
            <dd>{saveStatus === "success" ? "已保存" : saveStatus === "error" ? "保存失败" : "待保存"}</dd>
          </div>
          <div>
            <dt>测试结果</dt>
            <dd>
              {providerUnsupported
                ? "提供方只支持 openai-compatible。"
                : hasUnsavedDraft
                  ? "有未保存改动，请先保存。"
                  : testStatus === "success" && testResult
                    ? formatModelTestResult(testResult)
                    : testStatus === "error" && testResult
                      ? formatModelTestResult(testResult)
                      : "尚未测试"}
            </dd>
          </div>
        </dl>
      </article>
    </section>
  );
}
