import { Bot, Loader2, ShieldCheck } from "lucide-react";
import type { ModelTestResponse } from "../../types";
import { isSupportedProviderDraft } from "../../services/agentModelDrafts";
import { formatModelTestResult } from "./settingsFormatters";
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

  const statusText = providerUnsupported
    ? "提供方只支持 openai-compatible。"
    : hasUnsavedDraft
      ? "有未保存改动，请先保存后测试。"
      : testStatus === "success" && testResult
        ? formatModelTestResult(testResult)
        : testStatus === "error" && testResult
          ? formatModelTestResult(testResult)
          : saveStatus === "success"
            ? "已保存，可以测试连接。"
            : saveStatus === "error"
              ? "保存失败，请检查后重试。"
              : draft.configured
                ? "已配置。"
                : "未配置。";

  return (
    <section className="agent-model-section settings-card" aria-label="AI 模型配置">
      <div className="section-heading">
        <strong>AI 模型</strong>
        <span>填写一个 OpenAI 兼容接口，桌宠就能开始对话。</span>
      </div>
      <div className="settings-form-grid">
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
            placeholder="API 密钥"
            type="password"
          />
        </label>
      </div>
      <div className="settings-action-row">
        <div className="button-row">
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
        <p className={`field-note ${saveStatus === "error" || testStatus === "error" || providerUnsupported ? "error" : ""}`}>
          {statusText}
        </p>
      </div>
    </section>
  );
}
