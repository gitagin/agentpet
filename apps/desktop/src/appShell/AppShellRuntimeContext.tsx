import { createContext, useContext, type ReactNode } from "react";
import type { useWiki } from "../features/wiki/useWiki";
import type { AppState } from "./useAppState";
import type { ConnectionSettingsDomain } from "./useConnectionSettingsDomain";
import type { AgentActivityDomain } from "./useAgentActivityDomain";
import type { TaskDomain } from "./useTaskDomain";
import type { MemoryDomain } from "./useMemoryDomain";
import type { ContinuityDomain } from "./useContinuityDomain";
import type { ReflectionDomain } from "./useReflectionDomain";
import type { PetDomain } from "./usePetDomain";
import type { ChatStreamingDomain } from "./useChatStreamingDomain";
import type { ResetDomain } from "./useResetDomain";

export type AppShellRuntime = {
  app: AppState;
  connection: ConnectionSettingsDomain;
  activity: AgentActivityDomain;
  tasks: TaskDomain;
  memory: MemoryDomain;
  continuity: ContinuityDomain;
  reflection: ReflectionDomain;
  wiki: ReturnType<typeof useWiki>;
  pet: PetDomain;
  chat: ChatStreamingDomain;
  reset: ResetDomain;
  onboardingPanel: ReactNode;
};

const AppShellRuntimeContext = createContext<AppShellRuntime | null>(null);

export function AppShellRuntimeProvider({
  runtime,
  children,
}: {
  runtime: AppShellRuntime;
  children: ReactNode;
}) {
  return <AppShellRuntimeContext.Provider value={runtime}>{children}</AppShellRuntimeContext.Provider>;
}

export function useAppShellRuntime(): AppShellRuntime {
  const runtime = useContext(AppShellRuntimeContext);
  if (!runtime) {
    throw new Error("AppShellRuntimeProvider is missing");
  }
  return runtime;
}
