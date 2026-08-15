import type { AutomationSettings, TtsSettingsUpdateRequest } from "../../types";

export type LastIndexRun = {
  vaultId: string;
  jobId: string;
  status: string;
  filesSeen?: number;
  filesIndexed?: number;
};

export type AsyncStatus = "idle" | "loading" | "success" | "error";

export type SettingsStatusLoadState = "unknown" | "loading" | "ready" | "error";

export type GlobalModelDraft = {
  provider: string;
  base_url: string;
  model: string;
  api_key: string;
  saved_provider: string;
  saved_base_url: string;
  saved_model: string;
  configured: boolean;
};

export type NegotiationSettingsDraft = {
  use_negotiation: boolean | null;
  max_rounds: number | null;
};

export type AutomationSettingsDraft = Omit<AutomationSettings, keyof NegotiationSettingsDraft>
  & NegotiationSettingsDraft;

export type TtsSettingsDraft = TtsSettingsUpdateRequest;
