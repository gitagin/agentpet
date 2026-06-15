import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  live2dDefaultModelMigrationStorageKey,
  live2dDefaultModelMigrationValue,
  live2dModelSelectionStorageKey,
} from "./live2dConstants";

const rendererUiState = vi.hoisted(() => new Map<string, string>());
const mockReadRendererUiState = vi.hoisted(() => vi.fn((key: string) => rendererUiState.get(key) || null));
const mockWriteRendererUiState = vi.hoisted(() =>
  vi.fn(async (key: string, value: string | null) => {
    if (value === null) {
      rendererUiState.delete(key);
    } else {
      rendererUiState.set(key, value);
    }
  }),
);

vi.mock("../../services/cubismRenderer", () => ({
  createCubismRenderer: vi.fn(),
}));

vi.mock("../../services/rendererUiState", () => ({
  readRendererUiState: mockReadRendererUiState,
  writeRendererUiState: mockWriteRendererUiState,
}));

import { loadLive2DModelSelection } from "./live2dStorage";

describe("live2dStorage", () => {
  beforeEach(() => {
    rendererUiState.clear();
    vi.clearAllMocks();
  });

  it("migrates a previously cached default selection to the gentle girl default", () => {
    rendererUiState.set(live2dModelSelectionStorageKey, "UG");
    rendererUiState.set(live2dDefaultModelMigrationStorageKey, "agent-pet-companion-v1");

    expect(loadLive2DModelSelection()).toBe("gentle_girl");
    expect(mockWriteRendererUiState).toHaveBeenCalledWith(live2dModelSelectionStorageKey, "gentle_girl");
    expect(mockWriteRendererUiState).toHaveBeenCalledWith(
      live2dDefaultModelMigrationStorageKey,
      live2dDefaultModelMigrationValue,
    );
  });
});
