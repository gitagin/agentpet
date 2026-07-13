import type { FormEvent } from "react";
import { useCallback, useReducer } from "react";
import type { AgentModelId, AutomationSettingsUpdateRequest, SettingsStatusResponse } from "../../types";
import { describeError } from "../../services/apiErrorMessages";
import {
  agentLabel,
  hasUnsavedAgentModelDraft,
  isSupportedProviderDraft,
  normalizeProviderDraft,
  type AgentModelDraft,
} from "../../services/agentModelDrafts";
import type { DesktopApi } from "../../services/desktopApi";
import { formatTaskStatus } from "../tasks/taskReducer";
import { formatVaultStatus } from "./settingsFormatters";
import { createInitialSettingsState, settingsReducer } from "./settingsReducer";
import { broadcastTtsSettingsSaved } from "./settingsSync";
import type {
  AutomationSettingsDraft,
  GlobalModelDraft,
  LastIndexRun,
  NegotiationSettingsDraft,
  TtsSettingsDraft,
} from "./settingsTypes";

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type UseSettingsOptions = {
  api: DesktopApi;
  isElectronRuntime: boolean;
  onNotice: (notice: Notice | null) => void;
  onSettingsStatusLoaded?: (response: SettingsStatusResponse) => void;
};

const DEMO_NEGOTIATION_MAX_ROUNDS = 2;

function automationSettingsRequestFromDraft(
  draft: AutomationSettingsDraft,
): AutomationSettingsUpdateRequest {
  return {
    auto_chat_diary: draft.auto_chat_diary,
    auto_structured_memory: draft.auto_structured_memory,
    auto_long_term_memory: draft.auto_long_term_memory,
    auto_wiki_organize: draft.auto_wiki_organize,
    local_privacy_mode: draft.local_privacy_mode,
    proactive_trigger_frequency: draft.proactive_trigger_frequency,
    use_negotiation: draft.use_negotiation,
    max_rounds: DEMO_NEGOTIATION_MAX_ROUNDS,
  };
}

function clampFinite(value: number | undefined, fallback: number, min: number, max: number): number {
  const candidate = typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return Math.min(max, Math.max(min, candidate));
}

export function useSettings({ api, isElectronRuntime, onNotice, onSettingsStatusLoaded }: UseSettingsOptions) {
  const [state, dispatch] = useReducer(settingsReducer, undefined, createInitialSettingsState);

  const applySettingsStatus = useCallback((response: SettingsStatusResponse) => {
    dispatch({ type: "applySettingsStatus", response });
  }, []);

  const loadSettingsStatus = useCallback(async (options: { silent?: boolean; signal?: AbortSignal } = {}) => {
    dispatch({ type: "setLoadingSettingsStatus", loading: true });
    if (!options.silent) {
      onNotice(null);
    }
    try {
      const response = await api.getSettingsStatus(options.signal);
      applySettingsStatus(response);
      onSettingsStatusLoaded?.(response);
      if (!options.silent) {
        onNotice({ tone: "success", message: "设置状态已刷新。" });
      }
      return response;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return null;
      }
      if (!options.silent) {
        onNotice({ tone: "error", message: describeError(error, "设置状态读取失败") });
      }
      return null;
    } finally {
      dispatch({ type: "setLoadingSettingsStatus", loading: false });
    }
  }, [api, applySettingsStatus, onNotice, onSettingsStatusLoaded]);

  const updateGlobalModelDraft = useCallback((patch: Partial<GlobalModelDraft>) => {
    dispatch({ type: "updateGlobalModelDraft", patch });
  }, []);

  const saveGlobalModel = useCallback(async () => {
    const draft = state.globalModelDraft;
    if (!draft.provider.trim() || !draft.base_url.trim() || !draft.model.trim()) {
      onNotice({ tone: "error", message: "请填写默认对话能力的提供方、接口地址和模型。" });
      return;
    }
    const provider = normalizeProviderDraft(draft.provider);
    if (!isSupportedProviderDraft(provider)) {
      onNotice({ tone: "error", message: "当前只支持 OpenAI 兼容接口；提供方请填写 openai-compatible。" });
      return;
    }

    dispatch({ type: "setGlobalModelSaveStatus", status: "loading" });
    onNotice(null);
    try {
      const config = await api.updateSettings({
        provider,
        base_url: draft.base_url.trim(),
        model: draft.model.trim(),
      });
      if (draft.api_key.trim()) {
        await api.saveModelKey(config.provider, draft.api_key.trim());
      }
      dispatch({ type: "saveGlobalModelSuccess", config });
      onNotice({
        tone: "success",
        message: `默认对话能力已更新，${config.agents_using_global} 类高级能力将使用此配置。`,
      });
    } catch (error) {
      dispatch({ type: "setGlobalModelSaveStatus", status: "error" });
      onNotice({ tone: "error", message: describeError(error, "默认对话能力保存失败") });
    }
  }, [api, onNotice, state.globalModelDraft]);

  const testGlobalModelConnection = useCallback(async () => {
    const draft = state.globalModelDraft;
    if (
      draft.provider.trim() !== draft.saved_provider ||
      draft.base_url.trim() !== draft.saved_base_url ||
      draft.model.trim() !== draft.saved_model ||
      draft.api_key.trim()
    ) {
      onNotice({ tone: "error", message: "默认对话能力有未保存的配置，请先保存后再测试连接。" });
      return;
    }
    if (!isSupportedProviderDraft(draft.saved_provider || draft.provider)) {
      onNotice({ tone: "error", message: "当前只支持 OpenAI 兼容接口；提供方请保存为 openai-compatible 后再测试连接。" });
      return;
    }

    dispatch({ type: "setGlobalModelTestStatus", status: "loading" });
    onNotice(null);
    try {
      const response = await api.testModelConnection();
      dispatch({ type: "setGlobalModelTestStatus", status: response.status === "ok" ? "success" : "error", result: response });
      onNotice({
        tone: response.status === "ok" ? "success" : "error",
        message: response.message || `默认对话能力测试连接${response.status === "ok" ? "成功" : "失败"}。`,
      });
    } catch (error) {
      dispatch({ type: "setGlobalModelTestStatus", status: "error" });
      onNotice({ tone: "error", message: describeError(error, "默认对话能力测试连接失败") });
    }
  }, [api, onNotice, state.globalModelDraft]);

  const updateAutomationSettingsDraft = useCallback((patch: Partial<AutomationSettingsDraft>) => {
    dispatch({ type: "updateAutomationSettingsDraft", patch });
  }, []);

  const saveAutomationSettings = useCallback(async () => {
    const draft = state.automationSettingsDraft;

    dispatch({ type: "setAutomationSettingsSaveStatus", status: "loading" });
    onNotice(null);
    try {
      const settings = await api.saveAutomationSettings(
        automationSettingsRequestFromDraft(draft),
      );
      const refreshed = await loadSettingsStatus({ silent: true });
      dispatch({
        type: "saveAutomationSettingsSuccess",
        settings: { ...(refreshed?.automation || settings), max_rounds: DEMO_NEGOTIATION_MAX_ROUNDS },
      });
      onNotice({ tone: "success", message: "自动整理设置已保存。" });
    } catch (error) {
      dispatch({ type: "setAutomationSettingsSaveStatus", status: "error" });
      onNotice({ tone: "error", message: describeError(error, "自动整理设置保存失败") });
    }
  }, [api, loadSettingsStatus, onNotice, state.automationSettingsDraft]);

  const updateTtsSettingsDraft = useCallback((patch: Partial<TtsSettingsDraft>) => {
    dispatch({ type: "updateTtsSettingsDraft", patch });
  }, []);

  const saveTtsSettings = useCallback(async (apiKey?: string) => {
    const draft = state.ttsSettingsDraft;
    const speed = clampFinite(draft.speed, 1, 0.5, 2);
    const volume = clampFinite(draft.volume, 1, 0, 1);

    dispatch({ type: "setTtsSettingsSaveStatus", status: "loading" });
    onNotice(null);
    try {
      const settings = await api.saveTtsSettings({ ...draft, speed, volume });
      const trimmedKey = apiKey?.trim();
      if (trimmedKey) {
        await api.saveTtsKey({ provider: settings.provider, api_key: trimmedKey });
      }
      const refreshed = await loadSettingsStatus({ silent: true });
      dispatch({ type: "saveTtsSettingsSuccess", settings: refreshed?.tts_settings || settings });
      broadcastTtsSettingsSaved();
      onNotice({ tone: "success", message: "语音设置已保存。" });
    } catch (error) {
      dispatch({ type: "setTtsSettingsSaveStatus", status: "error" });
      onNotice({ tone: "error", message: describeError(error, "语音设置保存失败") });
    }
  }, [api, loadSettingsStatus, onNotice, state.ttsSettingsDraft]);

  const clearTtsCache = useCallback(async () => {
    onNotice(null);
    try {
      const response = await api.clearTtsCache();
      onNotice({
        tone: "success",
        message: `TTS cache cleared: ${response.cleared_entries} files, ${response.cleared_bytes} bytes.`,
      });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "TTS cache clear failed") });
    }
  }, [api, onNotice]);

  const updateNegotiationSettingsDraft = useCallback((patch: Partial<NegotiationSettingsDraft>) => {
    dispatch({ type: "updateNegotiationSettingsDraft", patch });
  }, []);

  const saveNegotiationSettings = useCallback(async () => {
    const draft = state.negotiationSettingsDraft;

    dispatch({ type: "setNegotiationSettingsSaveStatus", status: "loading" });
    onNotice(null);
    try {
      const settings = await api.saveAutomationSettings({
        ...automationSettingsRequestFromDraft(state.automationSettingsDraft),
        use_negotiation: draft.use_negotiation,
        max_rounds: DEMO_NEGOTIATION_MAX_ROUNDS,
      });
      const refreshed = await loadSettingsStatus({ silent: true });
      const automation = {
        ...(refreshed?.automation || settings),
        max_rounds: DEMO_NEGOTIATION_MAX_ROUNDS,
      };
      dispatch({ type: "saveAutomationSettingsSuccess", settings: automation });
      dispatch({
        type: "saveNegotiationSettingsSuccess",
        draft: { use_negotiation: automation.use_negotiation, max_rounds: automation.max_rounds },
      });
      onNotice({ tone: "success", message: "有界协作设置已保存，最多复核 2 轮。" });
    } catch (error) {
      dispatch({ type: "setNegotiationSettingsSaveStatus", status: "error" });
      onNotice({ tone: "error", message: describeError(error, "有界协作设置保存失败") });
    }
  }, [api, loadSettingsStatus, onNotice, state.automationSettingsDraft, state.negotiationSettingsDraft]);

  const updateAgentModelDraft = useCallback((agentId: AgentModelId, patch: Partial<AgentModelDraft>) => {
    dispatch({ type: "updateAgentModelDraft", agentId, patch });
  }, []);

  const saveAgentModel = useCallback(async (agentId: AgentModelId) => {
    const draft = state.agentModelDrafts.find((item) => item.agent_id === agentId);
    if (!draft) {
      return;
    }
    const provider = normalizeProviderDraft(draft.provider || draft.saved_provider || state.globalModelDraft.provider);
    const baseUrl = (draft.base_url || draft.saved_base_url || state.globalModelDraft.base_url).trim();
    const model = (draft.model || draft.saved_model || state.globalModelDraft.model).trim();

    if (draft.enabled) {
      if (!draft.provider.trim() || !draft.base_url.trim() || !draft.model.trim()) {
        onNotice({ tone: "error", message: "请填写该高级能力的提供方、接口地址和模型。" });
        return;
      }
      if (!isSupportedProviderDraft(provider)) {
        onNotice({ tone: "error", message: "当前只支持 OpenAI 兼容接口；提供方请填写 openai-compatible。" });
        return;
      }
      if (!draft.masked && !draft.api_key.trim()) {
        onNotice({ tone: "error", message: "请填写该高级能力的密钥后再保存。" });
        return;
      }
    }

    dispatch({ type: "startSavingAgentModel", agentId });
    onNotice(null);
    try {
      const config = await api.saveAgentModelConfig({
        agent_id: agentId,
        provider,
        base_url: baseUrl,
        model,
        enabled: draft.enabled,
      });
      const keyStatus = draft.enabled && draft.api_key.trim()
        ? await api.saveAgentModelKey({
            agent_id: agentId,
            provider: config.provider,
            api_key: draft.api_key.trim(),
          })
        : config;
      dispatch({ type: "saveAgentModelSuccess", agentId, draft, config, keyStatus });
      const masked = keyStatus.masked || config.masked || draft.masked || "";
      onNotice({
        tone: "success",
        message: draft.enabled
          ? `${agentLabel(agentId)} 模型配置已保存${masked ? `：${masked}` : "，请继续填写密钥"}。`
          : `${agentLabel(agentId)} 已切换为使用默认对话能力。`,
      });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, `${agentLabel(agentId)} 模型配置保存失败`) });
    } finally {
      dispatch({ type: "finishSavingAgentModel", agentId });
    }
  }, [api, onNotice, state.agentModelDrafts, state.globalModelDraft]);

  const testAgentModelConnection = useCallback(async (agentId: AgentModelId) => {
    const draft = state.agentModelDrafts.find((item) => item.agent_id === agentId);
    if (draft && hasUnsavedAgentModelDraft(draft)) {
      onNotice({ tone: "error", message: `${agentLabel(agentId)} 有未保存的模型配置，请先保存后再试连。` });
      return;
    }
    if (draft?.saved_enabled && !isSupportedProviderDraft(draft.saved_provider || draft.provider)) {
      onNotice({ tone: "error", message: "当前只支持 OpenAI 兼容接口；提供方请保存为 openai-compatible 后再试连。" });
      return;
    }
    dispatch({ type: "startTestingAgentModel", agentId });
    onNotice(null);
    try {
      const response = await api.testAgentModelConnection(agentId);
      dispatch({ type: "setAgentModelTestResult", agentId, result: response });
      onNotice({
        tone: response.status === "ok" ? "success" : "error",
        message: response.message || `${agentLabel(agentId)} 模型试连${response.status === "ok" ? "成功" : "失败"}。`,
      });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, `${agentLabel(agentId)} 模型试连失败`) });
    } finally {
      dispatch({ type: "finishTestingAgentModel", agentId });
    }
  }, [api, onNotice, state.agentModelDrafts]);

  const selectVaultDirectory = useCallback(async () => {
    if (!window.agentDesktop?.selectKnowledgeBaseFolder) {
      onNotice({
        tone: "info",
        message: isElectronRuntime
          ? "当前桌面端未提供文件夹选择能力，请手动填写保存位置。"
          : "浏览器模式无法打开系统文件夹选择器，请手动填写保存位置。",
      });
      return;
    }

    try {
      const selectedPath = await window.agentDesktop.selectKnowledgeBaseFolder();
      if (!selectedPath) {
        return;
      }

      dispatch({ type: "setVaultPath", vaultPath: selectedPath });
      onNotice({ tone: "info", message: "已填入本机文件夹路径，请确认后点击保存位置。" });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "文件夹选择失败") });
    }
  }, [isElectronRuntime, onNotice]);

  const loadVaultStatus = useCallback(async (options: { silent?: boolean; signal?: AbortSignal } = {}) => {
    try {
      const response = await api.getVaultStatus(options.signal);
      dispatch({
        type: "setVaultStatus",
        vaultId: response.active_vault_id || null,
        vaultPath: response.root_path || "",
        vaultStatus: response,
      });
      if (!options.silent) {
        onNotice({
          tone: "success",
          message: response.configured
            ? `当前保存位置：${response.root_path_label || response.active_vault_id || "已配置"}。`
            : "尚未配置保存位置。",
        });
      }
      await loadSettingsStatus({ silent: true });
      return response;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return null;
      }
      if (!options.silent) {
        onNotice({ tone: "error", message: describeError(error, "保存位置状态读取失败") });
      }
      return null;
    }
  }, [api, loadSettingsStatus, onNotice]);

  const bindVault = useCallback(async (event: FormEvent) => {
    event.preventDefault();
    if (!state.vaultPath.trim()) {
      return;
    }

    dispatch({ type: "setIndexingVault", indexingVault: true });
    onNotice(null);
    try {
      const response = await api.initVault(state.vaultPath.trim(), true);
      dispatch({ type: "setVaultStatus", vaultId: response.vault_id, vaultPath: response.root_path || state.vaultPath });
      try {
        const indexResponse = await api.indexVault(response.vault_id);
        dispatch({
          type: "setLastIndexRun",
          lastIndexRun: {
            vaultId: response.vault_id,
            jobId: indexResponse.index_job_id,
            status: indexResponse.status,
            filesSeen: indexResponse.files_seen,
            filesIndexed: indexResponse.files_indexed,
          },
        });
        onNotice({
          tone: "success",
          message: `本机文件夹 ${response.vault_id} 已${formatVaultStatus(response.status)}；整理任务 ${indexResponse.index_job_id} 状态：${formatTaskStatus(indexResponse.status)}。`,
        });
      } catch (indexError) {
        onNotice({
          tone: "error",
          message: describeError(indexError, `保存位置 ${response.vault_id} 已初始化，但自动整理失败`),
        });
      }
      await loadVaultStatus({ silent: true });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "保存位置初始化失败") });
    } finally {
      dispatch({ type: "setIndexingVault", indexingVault: false });
    }
  }, [api, loadVaultStatus, onNotice, state.vaultPath]);

  const rebuildIndex = useCallback(async () => {
    if (!state.vaultId) {
      onNotice({ tone: "error", message: "请先加载或初始化保存位置，再启动资料整理。" });
      return;
    }

    dispatch({ type: "setIndexingVault", indexingVault: true });
    onNotice(null);
    try {
      const response = await api.indexVault(state.vaultId);
      dispatch({
        type: "setLastIndexRun",
        lastIndexRun: {
          vaultId: state.vaultId,
          jobId: response.index_job_id,
          status: response.status,
          filesSeen: response.files_seen,
          filesIndexed: response.files_indexed,
        },
      });
      onNotice({ tone: "success", message: `资料整理 ${response.index_job_id} 状态：${formatTaskStatus(response.status)}。` });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "重建索引失败") });
    } finally {
      dispatch({ type: "setIndexingVault", indexingVault: false });
    }
  }, [api, onNotice, state.vaultId]);

  const setVaultPath = useCallback((vaultPath: string) => {
    dispatch({ type: "setVaultPath", vaultPath });
  }, []);

  const setLastIndexRun = useCallback((lastIndexRun: LastIndexRun | null) => {
    dispatch({ type: "setLastIndexRun", lastIndexRun });
  }, []);

  const applyDiagnosticsStatus = useCallback((modelConfigured: boolean, vaultConfigured: boolean, activeVaultId?: string | null) => {
    dispatch({ type: "applyDiagnosticsStatus", modelConfigured, vaultConfigured, activeVaultId });
  }, []);

  const resetSettingsState = useCallback(() => {
    dispatch({ type: "reset" });
  }, []);

  return {
    agentModelDrafts: state.agentModelDrafts,
    agentModelTestResults: state.agentModelTestResults,
    applyDiagnosticsStatus,
    applySettingsStatus,
    automationSettingsDraft: state.automationSettingsDraft,
    automationSettingsSaveStatus: state.automationSettingsSaveStatus,
    bindVault,
    clearTtsCache,
    globalModelDraft: state.globalModelDraft,
    globalModelSaveStatus: state.globalModelSaveStatus,
    globalModelTestResult: state.globalModelTestResult,
    globalModelTestStatus: state.globalModelTestStatus,
    indexingVault: state.indexingVault,
    lastIndexRun: state.lastIndexRun,
    loadingSettingsStatus: state.loadingSettingsStatus,
    loadSettingsStatus,
    loadVaultStatus,
    negotiationSettingsDraft: state.negotiationSettingsDraft,
    negotiationSettingsSaveStatus: state.negotiationSettingsSaveStatus,
    rebuildIndex,
    resetSettingsState,
    saveAgentModel,
    saveAutomationSettings,
    saveGlobalModel,
    saveNegotiationSettings,
    saveTtsSettings,
    savingAgentModelIds: state.savingAgentModelIds,
    selectVaultDirectory,
    setLastIndexRun,
    setVaultPath,
    settingsStatus: state.settingsStatus,
    testAgentModelConnection,
    testGlobalModelConnection,
    testingAgentModelIds: state.testingAgentModelIds,
    ttsSettingsDraft: state.ttsSettingsDraft,
    ttsSettingsSaveStatus: state.ttsSettingsSaveStatus,
    updateAgentModelDraft,
    updateAutomationSettingsDraft,
    updateGlobalModelDraft,
    updateNegotiationSettingsDraft,
    updateTtsSettingsDraft,
    vaultId: state.vaultId,
    vaultPath: state.vaultPath,
    vaultStatus: state.vaultStatus,
  };
}
