import { useState } from "react";
import type { useWiki } from "../features/wiki/useWiki";
import type { ConfirmationDialogRequest } from "../components/ConfirmationDialog";
import { describeError } from "../services/apiErrorMessages";
import { clearRendererResettableState } from "./appShellUtils";
import type { AppState } from "./useAppState";
import type { ConnectionSettingsDomain } from "./useConnectionSettingsDomain";
import type { AgentActivityDomain } from "./useAgentActivityDomain";
import type { TaskDomain } from "./useTaskDomain";
import type { MemoryDomain } from "./useMemoryDomain";
import type { ContinuityDomain } from "./useContinuityDomain";
import type { PetDomain } from "./usePetDomain";

type WikiDomain = ReturnType<typeof useWiki>;

type UseResetDomainOptions = {
  app: AppState;
  connection: ConnectionSettingsDomain;
  activity: AgentActivityDomain;
  tasks: TaskDomain;
  memory: MemoryDomain;
  continuity: ContinuityDomain;
  wiki: WikiDomain;
  pet: PetDomain;
  confirm: (request: ConfirmationDialogRequest) => Promise<boolean>;
};

export function useResetDomain({
  app,
  connection,
  activity,
  tasks,
  memory,
  continuity,
  wiki,
  pet,
  confirm,
}: UseResetDomainOptions) {
  const [resettingLocalState, setResettingLocalState] = useState(false);
  const [resettingMemoryState, setResettingMemoryState] = useState(false);
  const api = connection.connection.api;

  function clearRuntimeState() {
    app.setConversationId(null);
    pet.chat.resetStreamState();
    app.setMessages([]);
    memory.resetMemoryState();
    activity.reset();
    continuity.reset();
  }

  async function resetLocalState() {
    const confirmed = await confirm({
      title: "确认重置本机状态吗？",
      message: "这会清空本机桌宠的应用状态，并让应用回到首次启动状态。",
      details: [
        "将清空聊天记录、长期记忆、陪伴状态、任务、保存位置绑定、索引缓存、模型配置和本地密钥。",
        "不会删除你选择的本地文件。",
      ],
      confirmLabel: "确认重置",
    });
    if (!confirmed) {
      return;
    }
    setResettingLocalState(true);
    app.setNotice(null);
    try {
      const response = await api.resetLocalState("RESET_AGENT_PET");
      clearRendererResettableState();
      clearRuntimeState();
      tasks.controller.clearTasks();
      app.setDiagnostics(null);
      connection.settings.resetSettingsState();
      wiki.resetWikiState();
      connection.connection.setBusinessAuthReady("业务接口鉴权可用，本地状态已重置。");
      const clearedRows = Object.values(response.cleared_tables).reduce((total, count) => total + count, 0);
      app.setNotice({
        tone: "success",
        message: `本机桌宠已重置为初始化状态，清理 ${clearedRows} 条本地状态记录。`,
      });
      await connection.settings.loadSettingsStatus({ silent: true });
      await connection.settings.loadVaultStatus({ silent: true });
    } catch (error) {
      app.setNotice({ tone: "error", message: describeError(error, "本机状态重置失败") });
    } finally {
      setResettingLocalState(false);
    }
  }

  async function resetStoredMemoryState() {
    setResettingMemoryState(true);
    app.setNotice(null);
    try {
      const response = await api.resetMemoryState("RESET_AGENT_PET_MEMORY");
      clearRuntimeState();
      const clearedRows = Object.values(response.cleared_tables).reduce((total, count) => total + count, 0);
      app.setNotice({
        tone: "success",
        message: `记忆已重置，清理 ${clearedRows} 条记忆相关记录；LLM/API 配置已保留。`,
      });
      await connection.settings.loadSettingsStatus({ silent: true });
      await connection.settings.loadVaultStatus({ silent: true });
    } catch (error) {
      app.setNotice({ tone: "error", message: describeError(error, "记忆重置失败") });
    } finally {
      setResettingMemoryState(false);
    }
  }

  return {
    resettingLocalState,
    resettingMemoryState,
    resetLocalState,
    resetStoredMemoryState,
  };
}

export type ResetDomain = ReturnType<typeof useResetDomain>;
