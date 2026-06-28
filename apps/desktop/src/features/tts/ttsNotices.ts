import type { TtsPlaybackError, TtsVoiceGender } from "../../types";

export function normalizeTtsVoiceGender(gender: string | null | undefined): TtsVoiceGender | undefined {
  if (gender === "female" || gender === "male" || gender === "neutral" || gender === "unknown") {
    return gender;
  }
  return gender ? "unknown" : undefined;
}

export function formatTtsPlaybackErrorNotice(error: TtsPlaybackError): string {
  if (error.code === "authentication_failed") {
    const providerLabel = error.provider === "xiaomi-mimo" ? "小米 MiMo" : error.provider || "当前 TTS 服务";
    return `语音播放失败：${providerLabel} API Key 无效，请在设置里重新保存语音服务密钥，或临时切换到系统语音。${error.message ? `（${error.message}）` : ""}`;
  }
  if (error.code === "credential_missing") {
    return "语音播放失败：尚未保存语音服务密钥，请在设置里填写并保存后再试。";
  }
  if (error.code === "provider_not_configured") {
    return "语音播放失败：语音来源尚未配置完成，请在设置里检查服务地址、声音来源和密钥。";
  }
  return `语音播放失败：${error.message}`;
}

export function formatTtsProviderFallbackNotice(
  provider: string | undefined,
  fallbackProvider: string | undefined,
  error: TtsPlaybackError,
): string {
  const providerLabel = provider === "xiaomi-mimo" ? "小米 MiMo" : provider || "当前 TTS 服务";
  const fallbackLabel = fallbackProvider === "system" ? "系统语音" : fallbackProvider || "备用语音";
  if (error.code === "authentication_failed") {
    return `${providerLabel} API Key 无效，已临时改用${fallbackLabel}。请在设置里重新保存语音服务密钥。`;
  }
  if (error.code === "credential_missing") {
    return `${providerLabel} 尚未保存密钥，已临时改用${fallbackLabel}。`;
  }
  return `${providerLabel} 暂不可用，已临时改用${fallbackLabel}。`;
}
