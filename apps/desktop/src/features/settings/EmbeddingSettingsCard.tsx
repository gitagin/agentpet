import { Bot, Loader2, ShieldCheck } from "lucide-react";
import type { EmbeddingTestResponse } from "../../types";
import type { AsyncStatus, EmbeddingDraft } from "./settingsTypes";

type EmbeddingSettingsCardProps = {
  draft: EmbeddingDraft;
  saveStatus: AsyncStatus;
  testStatus: AsyncStatus;
  testResult?: EmbeddingTestResponse;
  onUpdateDraft: (patch: Partial<EmbeddingDraft>) => void;
  onSave: () => void;
  onTest: () => void;
};

function hasUnsavedEmbeddingDraft(draft: EmbeddingDraft): boolean {
  return (
    draft.base_url.trim() !== draft.saved_base_url ||
    draft.model.trim() !== draft.saved_model ||
    Boolean(draft.api_key.trim())
  );
}

function formatEmbeddingTestResult(result: EmbeddingTestResponse): string {
  const detail = result.dimensions ? `（维度 ${result.dimensions}）` : "";
  return `${result.message}${detail}`;
}

export function EmbeddingSettingsCard({
  draft,
  saveStatus,
  testStatus,
  testResult,
  onUpdateDraft,
  onSave,
  onTest,
}: EmbeddingSettingsCardProps) {
  const saving = saveStatus === "loading";
  const testing = testStatus === "loading";
  const hasUnsavedDraft = hasUnsavedEmbeddingDraft(draft);

  const statusText =
    testStatus === "success" && testResult
      ? formatEmbeddingTestResult(testResult)
      : testStatus === "error" && testResult
        ? formatEmbeddingTestResult(testResult)
        : saveStatus === "success"
          ? "已保存，可以测试连接。"
          : saveStatus === "error"
            ? "保存失败，请检查后重试。"
            : hasUnsavedDraft
              ? "有未保存改动，请先保存后测试。"
              : draft.configured
                ? draft.masked
                  ? `已配置，密钥已保存（${draft.masked}）。`
                  : "已配置。"
                : "未配置向量化；配置后搜索会启用语义召回。";

  return (
    <section className="agent-model-section settings-card" aria-label="向量检索设置">
      <div className="section-heading">
        <strong>向量检索（Embedding）</strong>
        <span>配置一个 OpenAI 兼容的 Embedding 接口，用于语义搜索；未配置时使用关键词全文检索。</span>
      </div>
      <div className="settings-form-grid">
        <label>
          <span>接口地址</span>
          <input
            value={draft.base_url}
            onChange={(event) => onUpdateDraft({ base_url: event.target.value })}
            placeholder="例如 https://api.example.com/v1"
          />
        </label>
        <label>
          <span>模型</span>
          <input
            value={draft.model}
            onChange={(event) => onUpdateDraft({ model: event.target.value })}
            placeholder="例如 text-embedding-3-small"
          />
        </label>
        <label>
          <span>密钥</span>
          <input
            value={draft.api_key}
            onChange={(event) => onUpdateDraft({ api_key: event.target.value })}
            placeholder="密钥"
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
            disabled={testing || hasUnsavedDraft}
          >
            {testing ? <Loader2 className="spin" size={16} /> : <Bot size={16} />}
            测试连接
          </button>
        </div>
        <p className={`field-note ${saveStatus === "error" || testStatus === "error" ? "error" : ""}`}>
          {statusText}
        </p>
      </div>
    </section>
  );
}
