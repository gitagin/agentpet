import { describe, expect, it } from "vitest";

import type { AgentModelId, AgentModelSettings, ModelTestResponse, SettingsStatusResponse } from "../../types";
import type { AgentModelDraft } from "../../services/agentModelDrafts";
import { createInitialSettingsState, getSavedAgentModelMasked, settingsReducer } from "./settingsReducer";

const agentId: AgentModelId = "chat_agent";

function modelSettings(overrides: Partial<AgentModelSettings> = {}): AgentModelSettings {
  return {
    agent_id: agentId,
    provider: "openai-compatible",
    base_url: "http://127.0.0.1:8765/v1",
    model: "test-model",
    configured: true,
    masked: "sk-***",
    ...overrides,
  };
}

function settingsStatus(overrides: Partial<SettingsStatusResponse> = {}): SettingsStatusResponse {
  return {
    model_provider: "openai-compatible",
    model_base_url: "http://127.0.0.1:8765/v1",
    chat_model: "test-model",
    model_configured: true,
    vault_configured: true,
    agent_models: [modelSettings()],
    automation: {
      auto_chat_diary: false,
      auto_structured_memory: false,
      auto_long_term_memory: false,
      auto_wiki_organize: false,
      use_negotiation: true,
      max_rounds: 5,
      high_risk_confirmation_required: true,
      updated_at: null,
    },
    ...overrides,
  };
}

function draftPatch(overrides: Partial<AgentModelDraft> = {}): Partial<AgentModelDraft> {
  return {
    provider: "openai-compatible",
    base_url: "http://127.0.0.1:8765/v1",
    model: "test-model",
    api_key: "sk-test",
    ...overrides,
  };
}

describe("settingsReducer", () => {
  it("creates the initial settings state", () => {
    const state = createInitialSettingsState();

    expect(state.agentModelDrafts.length).toBeGreaterThan(0);
    expect(state.agentModelTestResults).toEqual({});
    expect(state.savingAgentModelIds.size).toBe(0);
    expect(state.testingAgentModelIds.size).toBe(0);
    expect(state.settingsStatus).toBeNull();
    expect(state.vaultPath).toBe("");
    expect(state.indexingVault).toBe(false);
  });

  it("applies settings status and merges saved agent model settings", () => {
    const state = settingsReducer(createInitialSettingsState(), {
      type: "applySettingsStatus",
      response: settingsStatus(),
    });
    const draft = state.agentModelDrafts.find((item) => item.agent_id === agentId);

    expect(state.settingsStatus?.model_configured).toBe(true);
    expect(draft).toMatchObject({
      provider: "openai-compatible",
      base_url: "http://127.0.0.1:8765/v1",
      model: "test-model",
      configured: true,
      masked: "sk-***",
    });
  });

  it("applies diagnostics status without discarding existing model status", () => {
    const withStatus = settingsReducer(createInitialSettingsState(), {
      type: "applySettingsStatus",
      response: settingsStatus({ model_configured: false, vault_configured: false }),
    });
    const diagnosed = settingsReducer(withStatus, {
      type: "applyDiagnosticsStatus",
      modelConfigured: true,
      vaultConfigured: true,
      activeVaultId: "vault-1",
    });

    expect(diagnosed.vaultId).toBe("vault-1");
    expect(diagnosed.settingsStatus).toMatchObject({ model_configured: true, vault_configured: true });
    expect(diagnosed.settingsStatus?.agent_models?.[0].agent_id).toBe(agentId);
  });

  it("updates model drafts and saving ids immutably", () => {
    const updated = settingsReducer(createInitialSettingsState(), {
      type: "updateAgentModelDraft",
      agentId,
      patch: draftPatch({ model: "changed-model" }),
    });
    const saving = settingsReducer(updated, { type: "startSavingAgentModel", agentId });
    const finished = settingsReducer(saving, { type: "finishSavingAgentModel", agentId });

    expect(updated.agentModelDrafts.find((item) => item.agent_id === agentId)?.model).toBe("changed-model");
    expect(saving.savingAgentModelIds.has(agentId)).toBe(true);
    expect(updated.savingAgentModelIds.has(agentId)).toBe(false);
    expect(finished.savingAgentModelIds.has(agentId)).toBe(false);
  });

  it("saves agent model settings and clears stale test results", () => {
    const draft = {
      ...createInitialSettingsState().agentModelDrafts.find((item) => item.agent_id === agentId)!,
      ...draftPatch(),
    };
    const withStatus = settingsReducer(createInitialSettingsState(), {
      type: "applySettingsStatus",
      response: settingsStatus({ agent_models: [modelSettings({ configured: false, masked: "" })] }),
    });
    const withTestResult = settingsReducer(withStatus, {
      type: "setAgentModelTestResult",
      agentId,
      result: { status: "failed", message: "旧结果" },
    });
    const saved = settingsReducer(withTestResult, {
      type: "saveAgentModelSuccess",
      agentId,
      draft,
      config: modelSettings({ model: "saved-model", masked: "sk-new***" }),
    });

    const savedDraft = saved.agentModelDrafts.find((item) => item.agent_id === agentId);
    expect(savedDraft).toMatchObject({ model: "saved-model", api_key: "", masked: "sk-new***", configured: true });
    expect(saved.settingsStatus?.agent_models?.[0]).toMatchObject({ model: "saved-model", masked: "sk-new***" });
    expect(saved.agentModelTestResults[agentId]).toBeUndefined();
  });

  it("tracks test ids and stores model test results", () => {
    const result: ModelTestResponse = { status: "ok", agent_id: agentId, message: "连接成功" };
    const testing = settingsReducer(createInitialSettingsState(), { type: "startTestingAgentModel", agentId });
    const withResult = settingsReducer(testing, { type: "setAgentModelTestResult", agentId, result });
    const finished = settingsReducer(withResult, { type: "finishTestingAgentModel", agentId });

    expect(testing.testingAgentModelIds.has(agentId)).toBe(true);
    expect(testing.agentModelTestResults[agentId]).toBeUndefined();
    expect(withResult.agentModelTestResults[agentId]).toEqual(result);
    expect(finished.testingAgentModelIds.has(agentId)).toBe(false);
  });

  it("updates vault and indexing state", () => {
    const loading = settingsReducer(createInitialSettingsState(), { type: "setLoadingSettingsStatus", loading: true });
    const withPath = settingsReducer(loading, { type: "setVaultPath", vaultPath: "E:/Vault" });
    const withVault = settingsReducer(withPath, { type: "setVaultStatus", vaultId: "vault-1", vaultPath: "E:/Vault" });
    const withIndex = settingsReducer(withVault, {
      type: "setLastIndexRun",
      lastIndexRun: { vaultId: "vault-1", jobId: "job-1", status: "completed", filesSeen: 2, filesIndexed: 2 },
    });
    const indexing = settingsReducer(withIndex, { type: "setIndexingVault", indexingVault: true });

    expect(loading.loadingSettingsStatus).toBe(true);
    expect(withPath.vaultPath).toBe("E:/Vault");
    expect(withVault.vaultId).toBe("vault-1");
    expect(indexing.lastIndexRun?.jobId).toBe("job-1");
    expect(indexing.indexingVault).toBe(true);
  });

  it("resets state and returns saved masked value", () => {
    const withStatus = settingsReducer(createInitialSettingsState(), {
      type: "applySettingsStatus",
      response: settingsStatus(),
    });
    const withVaultId = settingsReducer(withStatus, { type: "setVaultId", vaultId: "vault-1" });
    const reset = settingsReducer(withVaultId, { type: "reset" });

    expect(getSavedAgentModelMasked(withStatus, agentId)).toBe("sk-***");
    expect(withVaultId.vaultId).toBe("vault-1");
    expect(reset).toEqual(createInitialSettingsState());
  });
});
