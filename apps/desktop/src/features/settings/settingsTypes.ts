import type { AutomationSettings, TtsSettingsUpdateRequest } from "../../types";

export type LastIndexRun = {
  vaultId: string;
  jobId: string;
  status: string;
  filesSeen?: number;
  filesIndexed?: number;
};

export type AsyncStatus = "idle" | "loading" | "success" | "error";

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
  use_negotiation: boolean;
  max_rounds: number;
};

export type AutomationSettingsDraft = AutomationSettings;

export type TtsSettingsDraft = TtsSettingsUpdateRequest;
