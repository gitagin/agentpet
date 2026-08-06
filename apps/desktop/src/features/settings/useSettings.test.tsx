import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DesktopApi } from "../../services/desktopApi";
import type { AutomationSettings } from "../../types";
import { useSettings } from "./useSettings";

const savedAutomation: AutomationSettings = {
  auto_chat_diary: false,
  auto_structured_memory: false,
  auto_long_term_memory: false,
  auto_wiki_organize: false,
  local_privacy_mode: true,
  proactive_trigger_frequency: "low",
  use_negotiation: true,
  max_rounds: 5,
  high_risk_confirmation_required: true,
  updated_at: null,
};

describe("useSettings demo negotiation cap", () => {
  it("saves the global model through the dedicated config and health endpoints", async () => {
    const saveModelConfig = vi.fn().mockResolvedValue({
      provider: "openai-compatible",
      base_url: "https://model.example.test/v1",
      model: "model-v1",
      status: "configured",
    });
    const saveModelKey = vi.fn().mockResolvedValue({
      provider: "openai-compatible",
      status: "configured",
      masked: "****",
    });
    const getModelHealth = vi.fn().mockResolvedValue({ agents_fallback_to_global: 5 });
    const onNotice = vi.fn();
    const api = {
      saveModelConfig,
      saveModelKey,
      getModelHealth,
    } as unknown as DesktopApi;
    const { result } = renderHook(() => useSettings({
      api,
      isElectronRuntime: true,
      onNotice,
    }));

    act(() => result.current.updateGlobalModelDraft({
      provider: "openai-compatible",
      base_url: "https://model.example.test/v1",
      model: "model-v1",
      api_key: "sk-test",
    }));
    await act(async () => {
      await result.current.saveGlobalModel();
    });

    expect(saveModelConfig).toHaveBeenCalledWith(
      "openai-compatible",
      "https://model.example.test/v1",
      "model-v1",
    );
    expect(saveModelKey).toHaveBeenCalledWith("openai-compatible", "sk-test");
    expect(getModelHealth).toHaveBeenCalledOnce();
    expect(onNotice).toHaveBeenLastCalledWith(expect.objectContaining({
      message: expect.stringContaining("5 类高级能力"),
    }));
  });

  it("normalizes legacy round counts to two when saving automation or negotiation settings", async () => {
    const saveAutomationSettings = vi.fn().mockResolvedValue(savedAutomation);
    const api = {
      saveAutomationSettings,
      getSettingsStatus: vi.fn().mockRejectedValue(new Error("no refresh in unit test")),
    } as unknown as DesktopApi;
    const { result } = renderHook(() => useSettings({
      api,
      isElectronRuntime: true,
      onNotice: vi.fn(),
    }));

    expect(result.current.automationSettingsDraft.max_rounds).toBe(5);

    act(() => result.current.updateAutomationSettingsDraft({ local_privacy_mode: true }));
    await act(async () => {
      await result.current.saveAutomationSettings();
    });

    expect(saveAutomationSettings).toHaveBeenLastCalledWith(expect.objectContaining({
      local_privacy_mode: true,
      max_rounds: 2,
    }));
    expect(result.current.automationSettingsDraft.max_rounds).toBe(2);

    act(() => result.current.updateNegotiationSettingsDraft({ use_negotiation: false, max_rounds: 9 }));
    await act(async () => {
      await result.current.saveNegotiationSettings();
    });

    expect(saveAutomationSettings).toHaveBeenLastCalledWith(expect.objectContaining({
      use_negotiation: false,
      max_rounds: 2,
    }));
    expect(result.current.negotiationSettingsDraft.max_rounds).toBe(2);
    expect(result.current.automationSettingsDraft.max_rounds).toBe(2);
  });
});
