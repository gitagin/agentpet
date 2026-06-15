import { defaultLive2DModelOption } from "../../services/live2dRuntime";
import { readRendererUiState, writeRendererUiState } from "../../services/rendererUiState";
import {
  live2dDefaultModelMigrationStorageKey,
  live2dDefaultModelMigrationValue,
  live2dModelSelectionChannelName,
  live2dModelSelectionStorageKey,
} from "./live2dConstants";

const previousDefaultLive2DModelIds = new Set(["hiyori", "UG", "agent_pet_companion"]);

export function loadLive2DModelSelection(): string {
  const selectedModelId = readRendererUiState(live2dModelSelectionStorageKey);
  const migrationState = readRendererUiState(live2dDefaultModelMigrationStorageKey);
  if (selectedModelId && previousDefaultLive2DModelIds.has(selectedModelId) && migrationState !== live2dDefaultModelMigrationValue) {
    void writeRendererUiState(live2dModelSelectionStorageKey, defaultLive2DModelOption.id);
    void writeRendererUiState(live2dDefaultModelMigrationStorageKey, live2dDefaultModelMigrationValue);
    return defaultLive2DModelOption.id;
  }
  return selectedModelId || defaultLive2DModelOption.id;
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
