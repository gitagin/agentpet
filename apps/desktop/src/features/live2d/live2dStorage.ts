import { defaultLive2DModelOption } from "../../services/live2dRuntime";
import { readRendererUiState, writeRendererUiState } from "../../services/rendererUiState";
import { live2dModelSelectionChannelName, live2dModelSelectionStorageKey } from "./live2dConstants";

export function loadLive2DModelSelection(): string {
  return readRendererUiState(live2dModelSelectionStorageKey) || defaultLive2DModelOption.id;
}

export function saveLive2DModelSelection(modelId: string): void {
  void writeRendererUiState(live2dModelSelectionStorageKey, modelId);
}

export function broadcastLive2DModelSelection(modelId: string): void {
  if (!("BroadcastChannel" in window)) {
    return;
  }
  const channel = new BroadcastChannel(live2dModelSelectionChannelName);
  channel.postMessage({ modelId });
  channel.close();
}
