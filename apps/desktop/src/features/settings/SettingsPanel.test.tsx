import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DesktopApi } from "../../services/desktopApi";
import { defaultAgentModelDrafts } from "../../services/agentModelDrafts";
import type { TtsSettingsResponse } from "../../types";
import { SettingsPanel } from "./SettingsPanel";
import type {
  AutomationSettingsDraft,
  GlobalModelDraft,
  NegotiationSettingsDraft,
  TtsSettingsDraft,
} from "./settingsTypes";

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
  use_negotiation: true,
  max_rounds: 5,
  high_risk_confirmation_required: true,
  updated_at: null,
};

const negotiationSettingsDraft: NegotiationSettingsDraft = {
  use_negotiation: true,
  max_rounds: 5,
};

const ttsSettingsDraft: TtsSettingsDraft = {
  enabled: false,
  auto_play_assistant_reply: false,
  auto_play_reminders: false,
  provider: "system",
  voice: null,
  speed: 1,
  volume: 1,
  response_format: "mp3",
  requires_api_key: false,
  api_style: "generic",
  auth_header_name: null,
  request_template: null,
  audio_json_path: null,
  audio_encoding: "base64",
  mime_type: null,
  cache_enabled: false,
  night_quiet_mode: true,
};

function ttsSettingsStatus(overrides: Partial<TtsSettingsResponse> = {}): TtsSettingsResponse {
  return {
    ...ttsSettingsDraft,
    configured: false,
    status: "disabled",
    key_configured: false,
    key_masked: null,
    updated_at: null,
    ...overrides,
  };
}

function renderSettingsPanel(
  overrides: Partial<TtsSettingsDraft> = {},
  status: TtsSettingsResponse | null = null,
) {
  const onUpdateTtsSettingsDraft = vi.fn();
  const onSaveTtsSettings = vi.fn();
  const onRefreshSettings = vi.fn();
  const onTestGlobalModel = vi.fn();
  const onSelectVaultDirectory = vi.fn();

  const rendered = render(
    <SettingsPanel
      api={{} as DesktopApi}
      agentModelDrafts={defaultAgentModelDrafts()}
      agentModelTestResults={{}}
      globalModelDraft={globalModelDraft}
      globalModelSaveStatus="idle"
      globalModelTestStatus="idle"
      automationSettingsDraft={automationSettingsDraft}
      automationSettingsSaveStatus="idle"
      ttsSettingsDraft={{ ...ttsSettingsDraft, ...overrides }}
      ttsSettingsSaveStatus="idle"
      ttsSettingsStatus={status}
      negotiationSettingsDraft={negotiationSettingsDraft}
      negotiationSettingsSaveStatus="idle"
      savingAgentModelIds={new Set()}
      testingAgentModelIds={new Set()}
      loadingSettingsStatus={false}
      vaultId={null}
      vaultPath=""
      vaultStatus={null}
      lastIndexRun={null}
      indexingVault={false}
      canSelectVaultDirectory
      onRefreshSettings={onRefreshSettings}
      onUpdateGlobalModelDraft={vi.fn()}
      onSaveGlobalModel={vi.fn()}
      onTestGlobalModel={onTestGlobalModel}
      onUpdateAutomationSettingsDraft={vi.fn()}
      onSaveAutomationSettings={vi.fn()}
      onUpdateTtsSettingsDraft={onUpdateTtsSettingsDraft}
      onSaveTtsSettings={onSaveTtsSettings}
      onUpdateNegotiationSettingsDraft={vi.fn()}
      onSaveNegotiationSettings={vi.fn()}
      onUpdateAgentModelDraft={vi.fn()}
      onSaveAgentModel={vi.fn()}
      onTestAgentModel={vi.fn()}
      onVaultPathChange={vi.fn()}
      onSelectVaultDirectory={onSelectVaultDirectory}
      onBindVault={(event) => event.preventDefault()}
      onLoadVaultStatus={vi.fn()}
      onRebuildIndex={vi.fn()}
    />,
  );

  return {
    ...rendered,
    onUpdateTtsSettingsDraft,
    onSaveTtsSettings,
    onRefreshSettings,
    onTestGlobalModel,
    onSelectVaultDirectory,
  };
}

describe("SettingsPanel", () => {
  it("shows action-first settings trials without binding or saving automatically", () => {
    const { onRefreshSettings, onTestGlobalModel, onSelectVaultDirectory } = renderSettingsPanel();
    const guidedActions = within(screen.getByRole("region", { name: "设置引导" }));

    expect(screen.getByText("先能对话，再决定保存")).toBeInTheDocument();
    expect(screen.getByText("连接聊天模型后就能开始；保存和导出位置可以之后再设。")).toBeInTheDocument();
    fireEvent.click(guidedActions.getByRole("button", { name: "测试模型" }));
    fireEvent.click(guidedActions.getByRole("button", { name: "选择保存位置" }));
    fireEvent.click(guidedActions.getByRole("button", { name: "刷新设置" }));

    expect(onTestGlobalModel).toHaveBeenCalledTimes(1);
    expect(onSelectVaultDirectory).toHaveBeenCalledTimes(1);
    expect(onRefreshSettings).toHaveBeenCalledTimes(1);
    expect(screen.getByText("保存与导出位置")).toBeInTheDocument();
    expect(screen.getByText("可选：选择一个本机文件夹，用来保存长期记忆和复盘报告。")).toBeInTheDocument();
    expect(screen.getByText(/可直接用常见笔记软件打开/)).toBeInTheDocument();
  });

  it("keeps specialist model configuration behind advanced outcome-oriented settings", () => {
    const { container } = renderSettingsPanel();

    const advanced = screen.getByText("高级模型路由").closest("details");

    expect(advanced).not.toHaveAttribute("open");
    expect(screen.getByText("按结果覆盖模型")).toBeInTheDocument();
    expect(screen.getAllByText("任务").length).toBeGreaterThan(0);
    expect(screen.getAllByText("知识").length).toBeGreaterThan(0);
    expect(screen.getAllByText("记忆").length).toBeGreaterThan(0);
    expect(screen.getAllByText("带引用回答").length).toBeGreaterThan(0);
    expect(container.textContent).not.toMatch(/9 agents|9 个智能体|9个智能体/);
  });

  it("updates and saves TTS voice settings", () => {
    const { onUpdateTtsSettingsDraft, onSaveTtsSettings, onRefreshSettings } = renderSettingsPanel();
    const ttsRegion = within(screen.getByRole("region", { name: "语音朗读设置" }));

    fireEvent.click(ttsRegion.getByLabelText("启用语音朗读"));
    expect(onUpdateTtsSettingsDraft).toHaveBeenCalledWith({
      enabled: true,
      auto_play_assistant_reply: true,
    });

    fireEvent.change(ttsRegion.getByLabelText("声音来源"), { target: { value: "mock" } });
    expect(onUpdateTtsSettingsDraft).toHaveBeenCalledWith(expect.objectContaining({ provider: "mock", voice: null }));

    fireEvent.change(ttsRegion.getByLabelText("声音"), { target: { value: "Microsoft Huihui" } });
    expect(onUpdateTtsSettingsDraft).toHaveBeenCalledWith({
      voice: {
        id: "Microsoft Huihui",
        label: "Microsoft Huihui",
        provider: "system",
        locale: null,
        gender: null,
        description: null,
      },
    });

    fireEvent.change(ttsRegion.getByLabelText("语速"), { target: { value: "1.4" } });
    expect(onUpdateTtsSettingsDraft).toHaveBeenCalledWith({ speed: 1.4 });

    fireEvent.change(ttsRegion.getByLabelText("音量"), { target: { value: "0.6" } });
    expect(onUpdateTtsSettingsDraft).toHaveBeenCalledWith({ volume: 0.6 });

    fireEvent.click(ttsRegion.getByRole("button", { name: /保存语音/ }));
    expect(onSaveTtsSettings).toHaveBeenCalledWith("");

    fireEvent.click(ttsRegion.getByRole("button", { name: /刷新设置/ }));
    expect(onRefreshSettings).toHaveBeenCalledTimes(1);
  });

  it("applies the Xiaomi MiMo preset without requiring users to edit templates", () => {
    const { onUpdateTtsSettingsDraft } = renderSettingsPanel();
    const ttsRegion = within(screen.getByRole("region", { name: "语音朗读设置" }));

    fireEvent.change(ttsRegion.getByLabelText("声音来源"), { target: { value: "xiaomi-mimo" } });

    expect(onUpdateTtsSettingsDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: "xiaomi-mimo",
        base_url: "https://api.xiaomimimo.com/v1/chat/completions",
        model: "mimo-v2.5-tts",
        voice: expect.objectContaining({ id: "Chloe", provider: "xiaomi-mimo" }),
        response_format: "wav",
        requires_api_key: true,
        auth_header_name: "api-key",
        audio_json_path: "choices.0.message.audio.data",
        mime_type: "audio/wav",
      }),
    );
  });

  it("collects custom voice service fields without storing the key in the draft", () => {
    const { onUpdateTtsSettingsDraft, onSaveTtsSettings } = renderSettingsPanel({
      provider: "custom-http",
      base_url: "https://tts.example.test/synthesize",
      model: "voice-model",
      requires_api_key: true,
    });
    const ttsRegion = within(screen.getByRole("region", { name: "语音朗读设置" }));

    fireEvent.change(ttsRegion.getByLabelText("语音服务地址"), {
      target: { value: "https://tts.example.test/v2" },
    });
    expect(onUpdateTtsSettingsDraft).toHaveBeenCalledWith({
      base_url: "https://tts.example.test/v2",
    });

    fireEvent.change(ttsRegion.getByLabelText("TTS 模型"), { target: { value: "voice-model-2" } });
    expect(onUpdateTtsSettingsDraft).toHaveBeenCalledWith({ model: "voice-model-2" });

    fireEvent.change(ttsRegion.getByLabelText("音频格式"), { target: { value: "wav" } });
    expect(onUpdateTtsSettingsDraft).toHaveBeenCalledWith({ response_format: "wav" });

    fireEvent.click(ttsRegion.getByLabelText("语音服务需要密钥"));
    expect(onUpdateTtsSettingsDraft).toHaveBeenCalledWith({ requires_api_key: false });

    fireEvent.change(ttsRegion.getByLabelText("语音服务密钥"), { target: { value: "secret-key" } });
    expect(onUpdateTtsSettingsDraft).not.toHaveBeenCalledWith(expect.objectContaining({ api_key: "secret-key" }));

    fireEvent.click(ttsRegion.getByRole("button", { name: /保存语音/ }));
    expect(onSaveTtsSettings).toHaveBeenCalledWith("secret-key");
  });

  it("shows TTS provider readiness without exposing credentials", () => {
    renderSettingsPanel(
      {
        enabled: true,
        provider: "custom-http",
        base_url: "https://tts.example.test/synthesize",
        requires_api_key: true,
      },
      ttsSettingsStatus({
        enabled: true,
        provider: "custom-http",
        base_url: "https://tts.example.test/synthesize",
        requires_api_key: true,
        status: "credential_missing",
      }),
    );

    expect(screen.getByText("语音未配置：请保存语音服务密钥。")).toBeInTheDocument();
    expect(screen.queryByText(/secret-key/)).not.toBeInTheDocument();
  });
});
