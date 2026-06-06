import { Loader2, RefreshCw, Save, Trash2, Volume2, VolumeX } from "lucide-react";
import { useEffect, useState } from "react";
import type { TtsSettingsResponse } from "../../types";
import type { AsyncStatus, TtsSettingsDraft } from "./settingsTypes";

type TtsSettingsCardProps = {
  draft: TtsSettingsDraft;
  saveStatus: AsyncStatus;
  loadingSettingsStatus: boolean;
  status?: TtsSettingsResponse | null;
  keyMasked?: string | null;
  keyConfigured?: boolean;
  onUpdateDraft: (patch: Partial<TtsSettingsDraft>) => void;
  onSave: (apiKey?: string) => void;
  onRefresh: () => void;
  onClearCache?: () => void;
};

const xiaomiMimoTemplate = {
  model: "{{model}}",
  messages: [
    { role: "user", content: "请自然朗读助手文本。" },
    { role: "assistant", content: "{{text}}" },
  ],
  audio: {
    voice: "{{voice}}",
    format: "{{format}}",
  },
};

const xiaomiMimoDefaultVoice = "Chloe";

function presetPatchForProvider(provider: string, draft: TtsSettingsDraft): Partial<TtsSettingsDraft> {
  if (provider === "xiaomi-mimo") {
    return {
      provider,
      base_url: "https://api.xiaomimimo.com/v1/chat/completions",
      model: "mimo-v2.5-tts",
      voice: {
        id: xiaomiMimoDefaultVoice,
        label: xiaomiMimoDefaultVoice,
        provider,
        locale: "en",
        gender: "female",
        description: "MiMo 内置声音",
      },
      response_format: "wav",
      requires_api_key: true,
      api_style: "chat-completions-audio",
      auth_header_name: "api-key",
      request_template: xiaomiMimoTemplate,
      audio_json_path: "choices.0.message.audio.data",
      audio_encoding: "base64",
      mime_type: "audio/wav",
    };
  }
  if (provider === "custom-http") {
    return {
      provider,
      voice: draft.voice ? { ...draft.voice, provider } : null,
      api_style: draft.api_style || "generic",
      audio_encoding: draft.audio_encoding || "base64",
    };
  }
  return {
    provider,
    base_url: null,
    model: null,
    voice: draft.voice ? { ...draft.voice, provider } : null,
    requires_api_key: false,
    api_style: "generic",
    auth_header_name: null,
    request_template: null,
    audio_json_path: null,
    audio_encoding: "base64",
    mime_type: null,
  };
}

function formatTtsSaveStatus(status: AsyncStatus, enabled: boolean): string {
  if (status === "loading") {
    return "正在保存语音设置。";
  }
  if (status === "success") {
    return "语音设置已保存。";
  }
  if (status === "error") {
    return "保存失败，请检查后重试。";
  }
  return enabled ? "回复完成后会按当前气泡页朗读。" : "语音关闭时不会播放任何回复。";
}

function formatTtsProviderStatus(status: TtsSettingsResponse | null | undefined): string | null {
  if (!status || status.status === "disabled") {
    return null;
  }
  if (status.status === "ready") {
    return status.provider === "custom-http" ? "自定义 TTS API 已就绪。" : "当前语音来源已就绪。";
  }
  if (status.status === "provider_not_configured") {
    return "语音未配置：请先填写 TTS API 地址。";
  }
  if (status.status === "credential_missing") {
    return "语音未配置：请保存 TTS API Key。";
  }
  return "语音来源暂不可用，文字回复仍会正常显示。";
}

function updateVoiceLabel(draft: TtsSettingsDraft, label: string): Partial<TtsSettingsDraft> {
  const trimmed = label.trim();
  return {
    voice: trimmed
      ? {
          id: trimmed,
          label: trimmed,
          provider: draft.provider,
          locale: draft.voice?.locale ?? null,
          gender: draft.voice?.gender ?? null,
          description: draft.voice?.description ?? null,
        }
      : null,
  };
}

export function TtsSettingsCard({
  draft,
  saveStatus,
  loadingSettingsStatus,
  status,
  keyMasked,
  keyConfigured = false,
  onUpdateDraft,
  onSave,
  onRefresh,
  onClearCache,
}: TtsSettingsCardProps) {
  const [apiKeyInput, setApiKeyInput] = useState("");
  const saving = saveStatus === "loading";
  const statusText = formatTtsSaveStatus(saveStatus, draft.enabled);
  const providerStatusText = formatTtsProviderStatus(status);
  const voiceLabel = draft.voice?.label || "";
  const cloudProvider = draft.provider === "custom-http" || draft.provider === "xiaomi-mimo";
  const requestTemplateText = draft.request_template ? JSON.stringify(draft.request_template, null, 2) : "";

  useEffect(() => {
    if (saveStatus === "success") {
      setApiKeyInput("");
    }
  }, [saveStatus]);

  return (
    <section className="agent-model-section settings-card tts-settings-card" aria-label="语音朗读设置">
      <div className="section-heading">
        <strong>语音朗读</strong>
        <span>控制桌宠是否朗读最终回复，以及朗读时的声音、速度和音量。</span>
      </div>

      <div className="tts-settings-grid">
        <label className="tts-toggle-row tts-toggle-row-primary">
          <input
            type="checkbox"
            checked={draft.enabled}
            aria-label="启用语音朗读"
            onChange={(event) => {
              const enabled = event.target.checked;
              onUpdateDraft({
                enabled,
                auto_play_assistant_reply: enabled ? true : draft.auto_play_assistant_reply,
              });
            }}
          />
          <span>
            {draft.enabled ? <Volume2 size={16} aria-hidden="true" /> : <VolumeX size={16} aria-hidden="true" />}
            <strong>启用语音朗读</strong>
            <small>开启后，桌宠会朗读当前显示的回复气泡页。</small>
          </span>
        </label>

        <label className="tts-toggle-row">
          <input
            type="checkbox"
            checked={draft.auto_play_assistant_reply}
            aria-label="自动朗读回复"
            onChange={(event) => onUpdateDraft({ auto_play_assistant_reply: event.target.checked })}
          />
          <span>
            <strong>自动朗读回复</strong>
            <small>只朗读助手最终回复，不朗读思考、工具和错误状态。</small>
          </span>
        </label>
      </div>

      <div className="tts-control-grid">
        <label>
          <span>声音来源</span>
          <select
            value={draft.provider}
            aria-label="声音来源"
            onChange={(event) => {
              const provider = event.target.value;
              onUpdateDraft(presetPatchForProvider(provider, draft));
            }}
          >
            <option value="system">系统语音</option>
            <option value="mock">静音测试</option>
            <option value="xiaomi-mimo">小米 MiMo</option>
            <option value="custom-http">自定义 TTS API</option>
          </select>
        </label>

        <label>
          <span>声音</span>
          <input
            value={voiceLabel}
            aria-label="声音"
            placeholder="默认系统声音"
            onChange={(event) => onUpdateDraft(updateVoiceLabel(draft, event.target.value))}
          />
        </label>
      </div>
      {providerStatusText ? (
        <p className={`field-note ${status && status.status !== "ready" && status.status !== "disabled" ? "error" : ""}`}>
          {providerStatusText}
        </p>
      ) : null}

      {cloudProvider ? (
        <div className="tts-custom-grid">
          <label>
            <span>API 地址</span>
            <input
              value={draft.base_url || ""}
              aria-label="TTS API 地址"
              placeholder="https://example.com/tts"
              onChange={(event) => onUpdateDraft({ base_url: event.target.value.trim() || null })}
            />
          </label>
          <label>
            <span>模型</span>
            <input
              value={draft.model || ""}
              aria-label="TTS 模型"
              placeholder="可留空"
              onChange={(event) => onUpdateDraft({ model: event.target.value.trim() || null })}
            />
          </label>
          <label>
            <span>音频格式</span>
            <select
              value={draft.response_format}
              aria-label="音频格式"
              onChange={(event) => onUpdateDraft({ response_format: event.target.value })}
            >
              <option value="mp3">MP3</option>
              <option value="wav">WAV</option>
              <option value="ogg">OGG</option>
              <option value="webm">WebM</option>
              <option value="m4a">M4A</option>
              <option value="aac">AAC</option>
              <option value="flac">FLAC</option>
            </select>
          </label>
          <label>
            <span>API Key</span>
            <input
              value={apiKeyInput}
              aria-label="TTS API Key"
              placeholder={draft.requires_api_key ? "输入后保存" : "可选"}
              type="password"
              onChange={(event) => setApiKeyInput(event.target.value)}
            />
          </label>
          <label>
            <span>鉴权 Header</span>
            <input
              value={draft.auth_header_name || ""}
              aria-label="TTS 鉴权 Header"
              placeholder={draft.provider === "xiaomi-mimo" ? "api-key" : "Authorization"}
              onChange={(event) => onUpdateDraft({ auth_header_name: event.target.value.trim() || null })}
            />
          </label>
          <label className="tts-inline-check">
            <input
              type="checkbox"
              checked={draft.requires_api_key}
              aria-label="TTS API 需要密钥"
              onChange={(event) => onUpdateDraft({ requires_api_key: event.target.checked })}
            />
            <span>需要 API Key</span>
          </label>
          <p className="field-note">
            {draft.requires_api_key
              ? keyConfigured && keyMasked
                ? `已保存密钥：${keyMasked}`
                : "尚未保存密钥。"
              : "不需要密钥时，后端不会添加 Authorization header。"}
          </p>
          <details className="settings-advanced-actions tts-advanced-template">
            <summary>高级 API 模板</summary>
            <label>
              <span>请求模板 JSON</span>
              <textarea
                value={requestTemplateText}
                aria-label="TTS 请求模板 JSON"
                rows={8}
                placeholder={'{"text":"{{text}}","voice":"{{voice}}","response_format":"{{format}}"}'}
                onChange={(event) => {
                  const value = event.target.value.trim();
                  if (!value) {
                    onUpdateDraft({ request_template: null });
                    return;
                  }
                  try {
                    onUpdateDraft({ request_template: JSON.parse(value) as Record<string, unknown> });
                  } catch {
                    onUpdateDraft({ request_template: draft.request_template || null });
                  }
                }}
              />
            </label>
            <label>
              <span>音频字段路径</span>
              <input
                value={draft.audio_json_path || ""}
                aria-label="TTS 音频字段路径"
                placeholder="audio_base64"
                onChange={(event) => onUpdateDraft({ audio_json_path: event.target.value.trim() || null })}
              />
            </label>
            <label>
              <span>MIME 类型</span>
              <input
                value={draft.mime_type || ""}
                aria-label="TTS MIME 类型"
                placeholder="audio/mpeg"
                onChange={(event) => onUpdateDraft({ mime_type: event.target.value.trim() || null })}
              />
            </label>
          </details>
        </div>
      ) : null}

      <div className="tts-slider-grid">
        <label>
          <span>语速</span>
          <input
            type="range"
            min={0.5}
            max={2}
            step={0.1}
            value={draft.speed}
            aria-label="语速"
            onChange={(event) => onUpdateDraft({ speed: Number.parseFloat(event.target.value) })}
          />
          <b>{draft.speed.toFixed(1)}x</b>
        </label>

        <label>
          <span>音量</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={draft.volume}
            aria-label="音量"
            onChange={(event) => onUpdateDraft({ volume: Number.parseFloat(event.target.value) })}
          />
          <b>{Math.round(draft.volume * 100)}%</b>
        </label>
      </div>

      <div className="tts-secondary-grid">
        <label>
          <input
            type="checkbox"
            checked={draft.auto_play_reminders}
            aria-label="朗读提醒"
            onChange={(event) => onUpdateDraft({ auto_play_reminders: event.target.checked })}
          />
          <span>朗读提醒</span>
        </label>
        <label>
          <input
            type="checkbox"
            checked={draft.night_quiet_mode}
            aria-label="夜间安静"
            onChange={(event) => onUpdateDraft({ night_quiet_mode: event.target.checked })}
          />
          <span>夜间安静</span>
        </label>
        <label>
          <input
            type="checkbox"
            checked={draft.cache_enabled}
            aria-label="缓存语音"
            onChange={(event) => onUpdateDraft({ cache_enabled: event.target.checked })}
          />
          <span>缓存语音</span>
        </label>
      </div>

      <div className="settings-action-row">
        <div className="button-row">
          <button type="button" onClick={() => onSave(apiKeyInput)} disabled={saving}>
            {saving ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
            保存语音
          </button>
          <button
            type="button"
            className="secondary"
            onClick={onRefresh}
            disabled={loadingSettingsStatus || saving}
          >
            {loadingSettingsStatus ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            刷新设置
          </button>
          {onClearCache ? (
            <button type="button" className="secondary" onClick={onClearCache} disabled={saving}>
              <Trash2 size={16} />
              清理缓存
            </button>
          ) : null}
        </div>
        <p className={`field-note ${saveStatus === "error" ? "error" : ""}`}>{statusText}</p>
      </div>
    </section>
  );
}
