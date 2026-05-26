import type { AgentModelId, ModelTestResponse, SettingsStatusResponse } from "../../types";
import {
  buildSavedAgentModelDraftPatch,
  defaultAgentModelDrafts,
  mergeAgentModelStatus,
  type AgentModelDraft,
} from "../../services/agentModelDrafts";
import type { LastIndexRun } from "./settingsTypes";

export type SettingsState = {
  agentModelDrafts: AgentModelDraft[];
  agentModelTestResults: Record<string, ModelTestResponse | undefined>;
  savingAgentModelIds: Set<string>;
  testingAgentModelIds: Set<string>;
  settingsStatus: SettingsStatusResponse | null;
  loadingSettingsStatus: boolean;
  vaultId: string | null;
  vaultPath: string;
  lastIndexRun: LastIndexRun | null;
  indexingVault: boolean;
};

export type SettingsAction =
  | { type: "applySettingsStatus"; response: SettingsStatusResponse }
  | { type: "applyDiagnosticsStatus"; modelConfigured: boolean; vaultConfigured: boolean; activeVaultId?: string | null }
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
  | { type: "setVaultStatus"; vaultId: string | null; vaultPath: string }
  | { type: "setVaultId"; vaultId: string | null }
  | { type: "setLastIndexRun"; lastIndexRun: LastIndexRun | null }
  | { type: "setIndexingVault"; indexingVault: boolean }
  | { type: "reset" };

export function createInitialSettingsState(): SettingsState {
  return {
    agentModelDrafts: defaultAgentModelDrafts(),
    agentModelTestResults: {},
    savingAgentModelIds: new Set(),
    testingAgentModelIds: new Set(),
    settingsStatus: null,
    loadingSettingsStatus: false,
    vaultId: null,
    vaultPath: "",
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
        agentModelDrafts: mergeAgentModelStatus(state.agentModelDrafts, action.response.agent_models),
      };
    case "applyDiagnosticsStatus":
      return {
        ...state,
        vaultId: action.activeVaultId || null,
        settingsStatus: {
          model_provider: state.settingsStatus?.model_provider || null,
          model_base_url: state.settingsStatus?.model_base_url || null,
          chat_model: state.settingsStatus?.chat_model || null,
          model_configured: action.modelConfigured,
          vault_configured: action.vaultConfigured,
          agent_models: state.settingsStatus?.agent_models,
        },
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
                      configured: Boolean(masked),
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
      return { ...state, vaultId: action.vaultId, vaultPath: action.vaultPath };
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
