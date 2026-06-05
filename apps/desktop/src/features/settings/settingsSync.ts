export const settingsSyncChannelName = "agent-pet-settings-sync";

type SettingsSyncMessage = {
  type: "tts-settings-saved";
  savedAt: string;
};

export function broadcastTtsSettingsSaved(): void {
  if (!("BroadcastChannel" in window)) {
    return;
  }
  try {
    const channel = new BroadcastChannel(settingsSyncChannelName);
    const message: SettingsSyncMessage = {
      type: "tts-settings-saved",
      savedAt: new Date().toISOString(),
    };
    channel.postMessage(message);
    channel.close();
  } catch (error) {
    console.warn("Failed to broadcast TTS settings update.", error);
  }
}

export function isTtsSettingsSavedMessage(value: unknown): value is SettingsSyncMessage {
  if (!value || typeof value !== "object") {
    return false;
  }
  return (value as SettingsSyncMessage).type === "tts-settings-saved";
}
