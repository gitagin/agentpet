import type { FormEvent } from "react";
import { useCallback, useReducer } from "react";
import type { AgentModelId, SettingsStatusResponse } from "../../types";
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
import type { LastIndexRun } from "./settingsTypes";

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

  const updateAgentModelDraft = useCallback((agentId: AgentModelId, patch: Partial<AgentModelDraft>) => {
    dispatch({ type: "updateAgentModelDraft", agentId, patch });
  }, []);

  const saveAgentModel = useCallback(async (agentId: AgentModelId) => {
    const draft = state.agentModelDrafts.find((item) => item.agent_id === agentId);
    if (!draft) {
      return;
    }
    if (!draft.provider.trim() || !draft.base_url.trim() || !draft.model.trim()) {
      onNotice({ tone: "error", message: "请填写智能体的提供方、接口地址和模型。" });
      return;
    }
    const provider = normalizeProviderDraft(draft.provider);
    if (!isSupportedProviderDraft(provider)) {
      onNotice({ tone: "error", message: "当前只支持 OpenAI 兼容接口；提供方请填写 openai-compatible。" });
      return;
    }
    if (!draft.masked && !draft.api_key.trim()) {
      onNotice({ tone: "error", message: "请填写智能体 API 密钥后再保存。" });
      return;
    }

    dispatch({ type: "startSavingAgentModel", agentId });
    onNotice(null);
    try {
      const config = await api.saveAgentModelConfig({
        agent_id: agentId,
        provider,
        base_url: draft.base_url.trim(),
        model: draft.model.trim(),
      });
      const keyStatus = draft.api_key.trim()
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
        message: `${agentLabel(agentId)} 模型配置已保存${masked ? `：${masked}` : "，请继续填写密钥"}。`,
      });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, `${agentLabel(agentId)} 模型配置保存失败`) });
    } finally {
      dispatch({ type: "finishSavingAgentModel", agentId });
    }
  }, [api, onNotice, state.agentModelDrafts]);

  const testAgentModelConnection = useCallback(async (agentId: AgentModelId) => {
    const draft = state.agentModelDrafts.find((item) => item.agent_id === agentId);
    if (draft && hasUnsavedAgentModelDraft(draft)) {
      onNotice({ tone: "error", message: `${agentLabel(agentId)} 有未保存的模型配置，请先保存后再试连。` });
      return;
    }
    if (draft && !isSupportedProviderDraft(draft.saved_provider || draft.provider)) {
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
          ? "当前桌面端未提供文件夹选择能力，请手动填写知识库路径。"
          : "浏览器模式无法打开系统文件夹选择器，请手动填写知识库路径。",
      });
      return;
    }

    try {
      const selectedPath = await window.agentDesktop.selectKnowledgeBaseFolder();
      if (!selectedPath) {
        return;
      }

      dispatch({ type: "setVaultPath", vaultPath: selectedPath });
      onNotice({ tone: "info", message: "已填入知识库路径，请确认后点击初始化。" });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "文件夹选择失败") });
    }
  }, [isElectronRuntime, onNotice]);

  const loadVaultStatus = useCallback(async (options: { silent?: boolean; signal?: AbortSignal } = {}) => {
    try {
      const response = await api.getVaultStatus(options.signal);
      dispatch({ type: "setVaultStatus", vaultId: response.active_vault_id || null, vaultPath: response.root_path || "" });
      if (!options.silent) {
        onNotice({
          tone: "success",
          message: response.configured
            ? `当前知识库：${response.root_path || response.active_vault_id || "已配置"}。`
            : "尚未配置知识库。",
        });
      }
      await loadSettingsStatus({ silent: true });
      return response;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return null;
      }
      if (!options.silent) {
        onNotice({ tone: "error", message: describeError(error, "知识库状态读取失败") });
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
          message: `知识库 ${response.vault_id} 已${formatVaultStatus(response.status)}；索引任务 ${indexResponse.index_job_id} 状态：${formatTaskStatus(indexResponse.status)}。`,
        });
      } catch (indexError) {
        onNotice({
          tone: "error",
          message: describeError(indexError, `知识库 ${response.vault_id} 已初始化，但自动索引失败`),
        });
      }
      await loadSettingsStatus({ silent: true });
    } catch (error) {
      onNotice({ tone: "error", message: describeError(error, "知识库初始化失败") });
    } finally {
      dispatch({ type: "setIndexingVault", indexingVault: false });
    }
  }, [api, loadSettingsStatus, onNotice, state.vaultPath]);

  const rebuildIndex = useCallback(async () => {
    if (!state.vaultId) {
      onNotice({ tone: "error", message: "请先加载或初始化知识库，再启动索引任务。" });
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
      onNotice({ tone: "success", message: `索引任务 ${response.index_job_id} 状态：${formatTaskStatus(response.status)}。` });
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
    bindVault,
    indexingVault: state.indexingVault,
    lastIndexRun: state.lastIndexRun,
    loadingSettingsStatus: state.loadingSettingsStatus,
    loadSettingsStatus,
    loadVaultStatus,
    rebuildIndex,
    resetSettingsState,
    saveAgentModel,
    savingAgentModelIds: state.savingAgentModelIds,
    selectVaultDirectory,
    setLastIndexRun,
    setVaultPath,
    settingsStatus: state.settingsStatus,
    testAgentModelConnection,
    testingAgentModelIds: state.testingAgentModelIds,
    updateAgentModelDraft,
    vaultId: state.vaultId,
    vaultPath: state.vaultPath,
  };
}
