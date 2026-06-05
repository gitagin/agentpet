import type {
  AgentModelId,
  AutomationSettings,
  ModelConfigResponse,
  ModelTestResponse,
  SettingsStatusResponse,
  TtsSettingsResponse,
  VaultStatusResponse,
} from "../../types";
import {
  buildSavedAgentModelDraftPatch,
  defaultAgentModelDrafts,
  mergeAgentModelStatus,
  type AgentModelDraft,
} from "../../services/agentModelDrafts";
import type {
  AsyncStatus,
  AutomationSettingsDraft,
  GlobalModelDraft,
  LastIndexRun,
  NegotiationSettingsDraft,
  TtsSettingsDraft,
} from "./settingsTypes";

const defaultGlobalModelDraft: GlobalModelDraft = {
  provider: "openai-compatible",
  base_url: "",
  model: "",
  api_key: "",
  saved_provider: "openai-compatible",
  saved_base_url: "",
  saved_model: "",
  configured: false,
};

const defaultNegotiationSettingsDraft: NegotiationSettingsDraft = {
  use_negotiation: true,
  max_rounds: 5,
};

const defaultTtsSettingsDraft: TtsSettingsDraft = {
  enabled: false,
  auto_play_assistant_reply: false,
  auto_play_reminders: false,
  provider: "system",
  base_url: null,
  model: null,
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

function defaultAutomationSettings(): AutomationSettings {
  return {
    auto_chat_diary: false,
    auto_structured_memory: false,
    auto_long_term_memory: false,
    auto_wiki_organize: false,
    use_negotiation: true,
    max_rounds: 5,
    high_risk_confirmation_required: true,
    updated_at: null,
  };
}

function automationSettingsDraftFromStatus(response: SettingsStatusResponse): AutomationSettingsDraft {
  return { ...response.automation, high_risk_confirmation_required: true };
}

function negotiationSettingsDraftFromStatus(response: SettingsStatusResponse): NegotiationSettingsDraft {
  return {
    use_negotiation: response.automation.use_negotiation,
    max_rounds: response.automation.max_rounds,
  };
}

function ttsSettingsDraftFromStatus(response: SettingsStatusResponse): TtsSettingsDraft {
  return response.tts_settings
    ? {
        enabled: response.tts_settings.enabled,
        auto_play_assistant_reply: response.tts_settings.auto_play_assistant_reply,
        auto_play_reminders: response.tts_settings.auto_play_reminders,
        provider: response.tts_settings.provider,
        base_url: response.tts_settings.base_url,
        model: response.tts_settings.model,
        voice: response.tts_settings.voice,
        speed: response.tts_settings.speed,
        volume: response.tts_settings.volume,
        response_format: response.tts_settings.response_format,
        requires_api_key: response.tts_settings.requires_api_key,
        api_style: response.tts_settings.api_style,
        auth_header_name: response.tts_settings.auth_header_name,
        request_template: response.tts_settings.request_template,
        audio_json_path: response.tts_settings.audio_json_path,
        audio_encoding: response.tts_settings.audio_encoding,
        mime_type: response.tts_settings.mime_type,
        cache_enabled: response.tts_settings.cache_enabled,
        night_quiet_mode: response.tts_settings.night_quiet_mode,
      }
    : defaultTtsSettingsDraft;
}

function globalModelDraftFromStatus(response: SettingsStatusResponse): GlobalModelDraft {
  const provider = response.model_provider || "openai-compatible";
  const baseUrl = response.model_base_url || "";
  const model = response.chat_model || "";
  return {
    provider,
    base_url: baseUrl,
    model,
    api_key: "",
    saved_provider: provider,
    saved_base_url: baseUrl,
    saved_model: model,
    configured: response.model_configured,
  };
}

export type SettingsState = {
  agentModelDrafts: AgentModelDraft[];
  agentModelTestResults: Record<string, ModelTestResponse | undefined>;
  globalModelDraft: GlobalModelDraft;
  globalModelSaveStatus: AsyncStatus;
  globalModelTestStatus: AsyncStatus;
  globalModelTestResult?: ModelTestResponse;
  automationSettingsDraft: AutomationSettingsDraft;
  automationSettingsSaveStatus: AsyncStatus;
  ttsSettingsDraft: TtsSettingsDraft;
  ttsSettingsSaveStatus: AsyncStatus;
  negotiationSettingsDraft: NegotiationSettingsDraft;
  negotiationSettingsSaveStatus: AsyncStatus;
  savingAgentModelIds: Set<string>;
  testingAgentModelIds: Set<string>;
  settingsStatus: SettingsStatusResponse | null;
  loadingSettingsStatus: boolean;
  vaultId: string | null;
  vaultPath: string;
  vaultStatus: VaultStatusResponse | null;
  lastIndexRun: LastIndexRun | null;
  indexingVault: boolean;
};

export type SettingsAction =
  | { type: "applySettingsStatus"; response: SettingsStatusResponse }
  | { type: "applyDiagnosticsStatus"; modelConfigured: boolean; vaultConfigured: boolean; activeVaultId?: string | null }
  | { type: "updateGlobalModelDraft"; patch: Partial<GlobalModelDraft> }
  | { type: "setGlobalModelSaveStatus"; status: AsyncStatus }
  | { type: "setGlobalModelTestStatus"; status: AsyncStatus; result?: ModelTestResponse }
  | { type: "saveGlobalModelSuccess"; config: ModelConfigResponse }
  | { type: "updateAutomationSettingsDraft"; patch: Partial<AutomationSettingsDraft> }
  | { type: "setAutomationSettingsSaveStatus"; status: AsyncStatus }
  | { type: "saveAutomationSettingsSuccess"; settings: AutomationSettings }
  | { type: "updateTtsSettingsDraft"; patch: Partial<TtsSettingsDraft> }
  | { type: "setTtsSettingsSaveStatus"; status: AsyncStatus }
  | { type: "saveTtsSettingsSuccess"; settings: TtsSettingsResponse }
  | { type: "updateNegotiationSettingsDraft"; patch: Partial<NegotiationSettingsDraft> }
  | { type: "setNegotiationSettingsSaveStatus"; status: AsyncStatus }
  | { type: "saveNegotiationSettingsSuccess"; draft: NegotiationSettingsDraft }
  | { type: "updateAgentModelDraft"; agentId: AgentModelId; patch: Partial<AgentModelDraft> }
  | { type: "startSavingAgentModel"; agentId: AgentModelId }
  | { type: "finishSavingAgentModel"; agentId: AgentModelId }
  | {
      type: "saveAgentModelSuccess";
      agentId: AgentModelId;
      draft: AgentModelDraft;
      config: Parameters<typeof buildSavedAgentModelDraftPatch>[1];
      keyStatus?: Parameters<typeof buildSavedAgentModelDraftPatch>[2];
    }
  | { type: "startTestingAgentModel"; agentId: AgentModelId }
  | { type: "finishTestingAgentModel"; agentId: AgentModelId }
  | { type: "setAgentModelTestResult"; agentId: AgentModelId; result?: ModelTestResponse }
  | { type: "setLoadingSettingsStatus"; loading: boolean }
  | { type: "setVaultPath"; vaultPath: string }
  | { type: "setVaultStatus"; vaultId: string | null; vaultPath: string; vaultStatus?: VaultStatusResponse | null }
  | { type: "setVaultId"; vaultId: string | null }
  | { type: "setLastIndexRun"; lastIndexRun: LastIndexRun | null }
  | { type: "setIndexingVault"; indexingVault: boolean }
  | { type: "reset" };

export function createInitialSettingsState(): SettingsState {
  return {
    agentModelDrafts: defaultAgentModelDrafts(),
    agentModelTestResults: {},
    globalModelDraft: defaultGlobalModelDraft,
    globalModelSaveStatus: "idle",
    globalModelTestStatus: "idle",
    globalModelTestResult: undefined,
    automationSettingsDraft: defaultAutomationSettings(),
    automationSettingsSaveStatus: "idle",
    ttsSettingsDraft: defaultTtsSettingsDraft,
    ttsSettingsSaveStatus: "idle",
    negotiationSettingsDraft: defaultNegotiationSettingsDraft,
    negotiationSettingsSaveStatus: "idle",
    savingAgentModelIds: new Set(),
    testingAgentModelIds: new Set(),
    settingsStatus: null,
    loadingSettingsStatus: false,
    vaultId: null,
    vaultPath: "",
    vaultStatus: null,
    lastIndexRun: null,
    indexingVault: false,
  };
}

export function settingsReducer(state: SettingsState, action: SettingsAction): SettingsState {
  switch (action.type) {
    case "applySettingsStatus":
      return {
        ...state,
        settingsStatus: action.response,
        globalModelDraft: globalModelDraftFromStatus(action.response),
        globalModelSaveStatus: "idle",
        globalModelTestStatus: "idle",
        globalModelTestResult: undefined,
        automationSettingsDraft: automationSettingsDraftFromStatus(action.response),
        automationSettingsSaveStatus: "idle",
        ttsSettingsDraft: ttsSettingsDraftFromStatus(action.response),
        ttsSettingsSaveStatus: "idle",
        negotiationSettingsDraft: negotiationSettingsDraftFromStatus(action.response),
        negotiationSettingsSaveStatus: "idle",
        agentModelDrafts: mergeAgentModelStatus(state.agentModelDrafts, action.response.agent_models),
      };
    case "applyDiagnosticsStatus":
      return {
        ...state,
        vaultId: action.activeVaultId || null,
        globalModelDraft: { ...state.globalModelDraft, configured: action.modelConfigured },
        settingsStatus: {
          model_provider: state.settingsStatus?.model_provider || null,
          model_base_url: state.settingsStatus?.model_base_url || null,
          chat_model: state.settingsStatus?.chat_model || null,
          model_configured: action.modelConfigured,
          vault_configured: action.vaultConfigured,
          agent_models: state.settingsStatus?.agent_models,
          automation: state.settingsStatus?.automation || defaultAutomationSettings(),
          tts_settings: state.settingsStatus?.tts_settings,
        },
      };
    case "updateGlobalModelDraft":
      return {
        ...state,
        globalModelDraft: { ...state.globalModelDraft, ...action.patch },
        globalModelSaveStatus: "idle",
        globalModelTestStatus: "idle",
        globalModelTestResult: undefined,
      };
    case "setGlobalModelSaveStatus":
      return { ...state, globalModelSaveStatus: action.status };
    case "setGlobalModelTestStatus":
      return { ...state, globalModelTestStatus: action.status, globalModelTestResult: action.result };
    case "saveGlobalModelSuccess":
      return {
        ...state,
        globalModelDraft: {
          ...state.globalModelDraft,
          provider: action.config.provider,
          base_url: action.config.base_url,
          model: action.config.model,
          api_key: "",
          saved_provider: action.config.provider,
          saved_base_url: action.config.base_url,
          saved_model: action.config.model,
          configured: true,
        },
        globalModelSaveStatus: "success",
        globalModelTestStatus: "idle",
        globalModelTestResult: undefined,
        settingsStatus: state.settingsStatus
          ? {
              ...state.settingsStatus,
              model_provider: action.config.provider,
              model_base_url: action.config.base_url,
              chat_model: action.config.model,
              model_configured: true,
            }
          : state.settingsStatus,
      };
    case "updateAutomationSettingsDraft":
      return {
        ...state,
        automationSettingsDraft: {
          ...state.automationSettingsDraft,
          ...action.patch,
          high_risk_confirmation_required: true,
        },
        automationSettingsSaveStatus: "idle",
      };
    case "setAutomationSettingsSaveStatus":
      return { ...state, automationSettingsSaveStatus: action.status };
    case "saveAutomationSettingsSuccess":
      return {
        ...state,
        automationSettingsDraft: {
          ...action.settings,
          high_risk_confirmation_required: true,
        },
        automationSettingsSaveStatus: "success",
        negotiationSettingsDraft: {
          use_negotiation: action.settings.use_negotiation,
          max_rounds: action.settings.max_rounds,
        },
        settingsStatus: state.settingsStatus
          ? {
              ...state.settingsStatus,
              automation: {
                ...action.settings,
                high_risk_confirmation_required: true,
              },
            }
          : state.settingsStatus,
      };
    case "updateTtsSettingsDraft":
      return {
        ...state,
        ttsSettingsDraft: {
          ...state.ttsSettingsDraft,
          ...action.patch,
        },
        ttsSettingsSaveStatus: "idle",
      };
    case "setTtsSettingsSaveStatus":
      return { ...state, ttsSettingsSaveStatus: action.status };
    case "saveTtsSettingsSuccess":
      return {
        ...state,
        ttsSettingsDraft: {
          enabled: action.settings.enabled,
          auto_play_assistant_reply: action.settings.auto_play_assistant_reply,
          auto_play_reminders: action.settings.auto_play_reminders,
          provider: action.settings.provider,
          base_url: action.settings.base_url,
          model: action.settings.model,
          voice: action.settings.voice,
          speed: action.settings.speed,
          volume: action.settings.volume,
          response_format: action.settings.response_format,
          requires_api_key: action.settings.requires_api_key,
          api_style: action.settings.api_style,
          auth_header_name: action.settings.auth_header_name,
          request_template: action.settings.request_template,
          audio_json_path: action.settings.audio_json_path,
          audio_encoding: action.settings.audio_encoding,
          mime_type: action.settings.mime_type,
          cache_enabled: action.settings.cache_enabled,
          night_quiet_mode: action.settings.night_quiet_mode,
        },
        ttsSettingsSaveStatus: "success",
        settingsStatus: state.settingsStatus
          ? {
              ...state.settingsStatus,
              tts_settings: action.settings,
            }
          : state.settingsStatus,
      };
    case "updateNegotiationSettingsDraft":
      return {
        ...state,
        negotiationSettingsDraft: { ...state.negotiationSettingsDraft, ...action.patch },
        automationSettingsDraft: {
          ...state.automationSettingsDraft,
          use_negotiation: action.patch.use_negotiation ?? state.automationSettingsDraft.use_negotiation,
          max_rounds: action.patch.max_rounds ?? state.automationSettingsDraft.max_rounds,
          high_risk_confirmation_required: true,
        },
        negotiationSettingsSaveStatus: "idle",
      };
    case "setNegotiationSettingsSaveStatus":
      return { ...state, negotiationSettingsSaveStatus: action.status };
    case "saveNegotiationSettingsSuccess":
      return {
        ...state,
        negotiationSettingsDraft: action.draft,
        negotiationSettingsSaveStatus: "success",
        automationSettingsDraft: {
          ...state.automationSettingsDraft,
          use_negotiation: action.draft.use_negotiation,
          max_rounds: action.draft.max_rounds,
          high_risk_confirmation_required: true,
        },
        settingsStatus: state.settingsStatus
          ? {
              ...state.settingsStatus,
              automation: {
                ...state.settingsStatus.automation,
                use_negotiation: action.draft.use_negotiation,
                max_rounds: action.draft.max_rounds,
              },
            }
          : state.settingsStatus,
      };
    case "updateAgentModelDraft":
      return {
        ...state,
        agentModelDrafts: state.agentModelDrafts.map((draft) =>
          draft.agent_id === action.agentId ? { ...draft, ...action.patch } : draft,
        ),
      };
    case "startSavingAgentModel": {
      const next = new Set(state.savingAgentModelIds);
      next.add(action.agentId);
      return { ...state, savingAgentModelIds: next };
    }
    case "finishSavingAgentModel": {
      const next = new Set(state.savingAgentModelIds);
      next.delete(action.agentId);
      return { ...state, savingAgentModelIds: next };
    }
    case "saveAgentModelSuccess": {
      const savedDraftPatch = buildSavedAgentModelDraftPatch(action.draft, action.config, action.keyStatus);
      const masked = savedDraftPatch.masked || "";
      return {
        ...state,
        agentModelDrafts: state.agentModelDrafts.map((draft) =>
          draft.agent_id === action.agentId ? { ...draft, ...savedDraftPatch } : draft,
        ),
        settingsStatus: state.settingsStatus?.agent_models
          ? {
              ...state.settingsStatus,
              agent_models: state.settingsStatus.agent_models.map((item) =>
                item.agent_id === action.agentId
                  ? {
                      ...item,
                      provider: action.config.provider,
                      base_url: action.config.base_url,
                      model: action.config.model,
                      enabled: action.config.enabled ?? true,
                      configured: action.config.configured,
                      masked,
                    }
                  : item,
              ),
            }
          : state.settingsStatus,
        agentModelTestResults: { ...state.agentModelTestResults, [action.agentId]: undefined },
      };
    }
    case "startTestingAgentModel": {
      const next = new Set(state.testingAgentModelIds);
      next.add(action.agentId);
      return {
        ...state,
        testingAgentModelIds: next,
        agentModelTestResults: { ...state.agentModelTestResults, [action.agentId]: undefined },
      };
    }
    case "finishTestingAgentModel": {
      const next = new Set(state.testingAgentModelIds);
      next.delete(action.agentId);
      return { ...state, testingAgentModelIds: next };
    }
    case "setAgentModelTestResult":
      return {
        ...state,
        agentModelTestResults: { ...state.agentModelTestResults, [action.agentId]: action.result },
      };
    case "setLoadingSettingsStatus":
      return { ...state, loadingSettingsStatus: action.loading };
    case "setVaultPath":
      return { ...state, vaultPath: action.vaultPath };
    case "setVaultStatus":
      return {
        ...state,
        vaultId: action.vaultId,
        vaultPath: action.vaultPath,
        vaultStatus: action.vaultStatus === undefined ? state.vaultStatus : action.vaultStatus,
      };
    case "setVaultId":
      return { ...state, vaultId: action.vaultId };
    case "setLastIndexRun":
      return { ...state, lastIndexRun: action.lastIndexRun };
    case "setIndexingVault":
      return { ...state, indexingVault: action.indexingVault };
    case "reset":
      return createInitialSettingsState();
    default:
      return state;
  }
}

export function getSavedAgentModelMasked(state: SettingsState, agentId: AgentModelId): string {
  return state.agentModelDrafts.find((draft) => draft.agent_id === agentId)?.masked || "";
}
