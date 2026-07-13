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
