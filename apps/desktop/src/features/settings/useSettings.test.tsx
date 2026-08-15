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

describe("useSettings", () => {
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

  it("keeps negotiation settings unknown until the server status is loaded", () => {
    const { result } = renderHook(() => useSettings({
      api: {} as DesktopApi,
      isElectronRuntime: true,
      onNotice: vi.fn(),
    }));

    expect(result.current.settingsStatusLoadState).toBe("unknown");
    expect(result.current.automationSettingsDraft.use_negotiation).toBeNull();
    expect(result.current.automationSettingsDraft.max_rounds).toBeNull();
  });

  it("sends the loaded round count and replaces drafts with the authoritative readback", async () => {
    const initialStatus = { automation: { ...savedAutomation, max_rounds: 7 } };
    const readbackStatus = { automation: { ...savedAutomation, use_negotiation: false, max_rounds: 8 } };
    const getSettingsStatus = vi.fn()
      .mockResolvedValueOnce(initialStatus)
      .mockResolvedValueOnce(readbackStatus);
    const saveAutomationSettings = vi.fn().mockResolvedValue(savedAutomation);
    const api = {
      saveAutomationSettings,
      getSettingsStatus,
    } as unknown as DesktopApi;
    const { result } = renderHook(() => useSettings({
      api,
      isElectronRuntime: true,
      onNotice: vi.fn(),
    }));

    await act(async () => {
      await result.current.loadSettingsStatus();
    });
    expect(result.current.automationSettingsDraft.max_rounds).toBe(7);

    act(() => result.current.updateAutomationSettingsDraft({
      local_privacy_mode: true,
      use_negotiation: false,
    }));
    await act(async () => {
      await result.current.saveAutomationSettings();
    });

    expect(saveAutomationSettings).toHaveBeenLastCalledWith(expect.objectContaining({
      local_privacy_mode: true,
      use_negotiation: false,
      max_rounds: 7,
    }));
    expect(result.current.automationSettingsDraft.use_negotiation).toBe(false);
    expect(result.current.automationSettingsDraft.max_rounds).toBe(8);
  });

  it("blocks writes after a settings refresh fails and allows a retry", async () => {
    const getSettingsStatus = vi.fn()
      .mockResolvedValueOnce({ automation: savedAutomation })
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ automation: { ...savedAutomation, max_rounds: 6 } });
    const saveAutomationSettings = vi.fn();
    const api = { getSettingsStatus, saveAutomationSettings } as unknown as DesktopApi;
    const { result } = renderHook(() => useSettings({
      api,
      isElectronRuntime: true,
      onNotice: vi.fn(),
    }));

    await act(async () => {
      await result.current.loadSettingsStatus();
    });
    expect(result.current.settingsStatusLoadState).toBe("ready");

    await act(async () => {
      await result.current.loadSettingsStatus();
    });
    expect(result.current.settingsStatusLoadState).toBe("error");

    await act(async () => {
      await result.current.saveAutomationSettings();
    });
    expect(saveAutomationSettings).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.loadSettingsStatus();
    });
    expect(result.current.settingsStatusLoadState).toBe("ready");
    expect(result.current.automationSettingsDraft.max_rounds).toBe(6);
  });
});
