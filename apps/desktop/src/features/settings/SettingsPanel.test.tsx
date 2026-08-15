import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DesktopApi } from "../../services/desktopApi";
import { SettingsPanel } from "./SettingsPanel";
import type { AutomationSettingsDraft, GlobalModelDraft } from "./settingsTypes";

vi.mock("./ModelHealthBanner", () => ({
  ModelHealthBanner: () => <div data-testid="model-health-banner" />,
}));

const globalModelDraft: GlobalModelDraft = {
  provider: "openai-compatible",
  base_url: "http://127.0.0.1:8765/v1",
  model: "test-model",
  api_key: "",
  saved_provider: "openai-compatible",
  saved_base_url: "http://127.0.0.1:8765/v1",
  saved_model: "test-model",
  configured: true,
};

const automationSettingsDraft: AutomationSettingsDraft = {
  auto_chat_diary: false,
  auto_structured_memory: false,
  auto_long_term_memory: false,
  auto_wiki_organize: false,
  local_privacy_mode: false,
  proactive_trigger_frequency: "low",
  use_negotiation: true,
  max_rounds: 7,
  high_risk_confirmation_required: true,
  updated_at: null,
};

function renderSettingsPanel(settingsStatusLoadState: "unknown" | "loading" | "ready" | "error" = "ready") {
  const onRefreshSettings = vi.fn();
  const onTestGlobalModel = vi.fn();
  const onSelectVaultDirectory = vi.fn();
  const onUpdateAutomationSettingsDraft = vi.fn();
  const onResetMemoryState = vi.fn();

  const rendered = render(
    <SettingsPanel
      model={{
        api: {} as DesktopApi,
        globalModelDraft,
        globalModelSaveStatus: "idle",
        globalModelTestStatus: "idle",
        automationSettingsDraft,
        automationSettingsSaveStatus: "idle",
        loadingSettingsStatus: false,
        settingsStatusLoadState,
        vaultId: null,
        vaultPath: "",
        vaultStatus: null,
        lastIndexRun: null,
        indexingVault: false,
        canSelectVaultDirectory: true,
        onRefreshSettings,
        onUpdateGlobalModelDraft: vi.fn(),
        onSaveGlobalModel: vi.fn(),
        onTestGlobalModel,
        onUpdateAutomationSettingsDraft,
        onSaveAutomationSettings: vi.fn(),
        onVaultPathChange: vi.fn(),
        onSelectVaultDirectory,
        onBindVault: (event) => event.preventDefault(),
        onLoadVaultStatus: vi.fn(),
        onRebuildIndex: vi.fn(),
        resettingMemoryState: false,
        onResetMemoryState,
      }}
    />,
  );

  return {
    ...rendered,
    onRefreshSettings,
    onTestGlobalModel,
    onSelectVaultDirectory,
    onUpdateAutomationSettingsDraft,
    onResetMemoryState,
  };
}

describe("SettingsPanel", () => {
  it("keeps only the demo settings cards", () => {
    const { container } = renderSettingsPanel();
    const settingsPanel = container.querySelector("#settings-panel");
    const directChildren = Array.from(settingsPanel?.children ?? []);

    expect(settingsPanel).toHaveClass("settings-panel-grid");
    expect(directChildren.some((child) => child.classList.contains("automation-settings-card"))).toBe(true);
    expect(directChildren.some((child) => child.classList.contains("separated"))).toBe(true);
    expect(container.querySelector(".advanced-agent-model-settings")).not.toBeInTheDocument();
    expect(container.querySelector(".tts-settings-card")).not.toBeInTheDocument();
    expect(screen.queryByText(/鉴权 Header|请求模板 JSON|MIME 类型|清理缓存/)).not.toBeInTheDocument();
  });

  it("offers connection testing and save-location selection without acting automatically", () => {
    const { onRefreshSettings, onTestGlobalModel, onSelectVaultDirectory } = renderSettingsPanel();
    const guide = within(screen.getByRole("region", { name: "设置引导" }));

    expect(screen.getByText("基础设置")).toBeInTheDocument();
    expect(screen.getByText("证据复核")).toBeInTheDocument();
    fireEvent.click(guide.getByRole("button", { name: "测试对话能力" }));
    fireEvent.click(guide.getByRole("button", { name: "选择保存位置" }));
    fireEvent.click(guide.getByRole("button", { name: "刷新状态" }));

    expect(onTestGlobalModel).toHaveBeenCalledTimes(1);
    expect(onSelectVaultDirectory).toHaveBeenCalledTimes(1);
    expect(onRefreshSettings).toHaveBeenCalledTimes(1);
  });

  it("edits the server-provided negotiation settings without replacing the round count", () => {
    const { onUpdateAutomationSettingsDraft } = renderSettingsPanel();
    const automation = within(screen.getByRole("region", { name: "记忆整理和主动提醒" }));

    expect(automation.getByText("本地隐私模式")).toBeInTheDocument();
    expect(automation.getByText("记忆检索有界复核")).toBeInTheDocument();
    expect(automation.getByText(/后台记录慢记忆候选和证据/)).toBeInTheDocument();
    expect(automation.getByRole("spinbutton", { name: "证据复核轮次上限" })).toHaveValue(7);

    fireEvent.click(automation.getByLabelText(/记忆检索有界复核/));
    expect(onUpdateAutomationSettingsDraft).toHaveBeenCalledWith({ use_negotiation: false });

    fireEvent.change(automation.getByRole("spinbutton", { name: "证据复核轮次上限" }), {
      target: { value: "9" },
    });
    expect(onUpdateAutomationSettingsDraft).toHaveBeenCalledWith({ max_rounds: 9 });
  });

  it("shows a retry-only state and no editable values when the authoritative read fails", () => {
    const { onRefreshSettings } = renderSettingsPanel("error");
    const automation = within(screen.getByRole("region", { name: "记忆整理和主动提醒" }));

    expect(automation.getByRole("alert")).toHaveTextContent("编辑已停用");
    expect(automation.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(automation.getByRole("button", { name: "保存设置" })).toBeDisabled();

    fireEvent.click(automation.getByRole("button", { name: "刷新设置" }));
    expect(onRefreshSettings).toHaveBeenCalledOnce();
  });

  it("uses an in-app confirmation dialog before resetting memory", () => {
    const { onResetMemoryState } = renderSettingsPanel();
    const reset = screen.getByRole("region", { name: "重置记忆" });
    const nativeConfirm = vi.spyOn(window, "confirm");

    expect(reset).toHaveTextContent("保留 LLM 与 Embedding 配置");
    expect(reset).toHaveTextContent("Vault 文件");
    fireEvent.click(within(reset).getByRole("button", { name: "重置记忆" }));

    const dialog = screen.getByRole("dialog", { name: "确认重置记忆？" });
    expect(dialog).toHaveTextContent("将清空");
    expect(dialog).toHaveTextContent("仍会保留");
    expect(within(dialog).getByRole("button", { name: "取消" })).toHaveFocus();
    expect(onResetMemoryState).not.toHaveBeenCalled();
    expect(nativeConfirm).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog", { name: "确认重置记忆？" })).not.toBeInTheDocument();

    fireEvent.click(within(reset).getByRole("button", { name: "重置记忆" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "确认重置记忆？" })).getByRole("button", { name: "确认重置记忆" }));
    expect(onResetMemoryState).toHaveBeenCalledTimes(1);
    expect(nativeConfirm).not.toHaveBeenCalled();
    nativeConfirm.mockRestore();
  });
});
