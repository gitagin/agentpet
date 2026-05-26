import { describe, expect, it } from "vitest";
import type { AgentModelSettings } from "../types";
import {
  buildSavedAgentModelDraftPatch,
  defaultAgentModelDrafts,
  hasUnsavedAgentModelDraft,
  mergeAgentModelStatus,
  normalizeProviderDraft,
} from "./agentModelDrafts";

const baseStatus: AgentModelSettings = {
  agent_id: "chat_agent",
  provider: "openai-compatible",
  base_url: "https://api.example.test/v1",
  model: "model-a",
  configured: true,
  masked: "sk-***1234",
};

describe("agentModelDrafts", () => {
  it("normalizes Chinese OpenAI-compatible provider drafts", () => {
    expect(normalizeProviderDraft(" OpenAI 兼容接口 ")).toBe("openai-compatible");
  });

  it("preserves unsaved local drafts when status refreshes", () => {
    const drafts = defaultAgentModelDrafts().map((draft) =>
      draft.agent_id === "chat_agent"
        ? {
            ...draft,
            provider: "openai-compatible",
            base_url: "https://local.example.test/v1",
            model: "draft-model",
            saved_provider: "openai-compatible",
            saved_base_url: "https://saved.example.test/v1",
            saved_model: "saved-model",
          }
        : draft,
    );

    const merged = mergeAgentModelStatus(drafts, [baseStatus]);
    const chatDraft = merged.find((draft) => draft.agent_id === "chat_agent");

    expect(chatDraft?.base_url).toBe("https://local.example.test/v1");
    expect(chatDraft?.model).toBe("draft-model");
    expect(chatDraft?.masked).toBe("sk-***1234");
    expect(chatDraft?.saved_base_url).toBe(baseStatus.base_url);
  });

  it("clears plaintext keys and stores masked values after save", () => {
    const draft = {
      ...defaultAgentModelDrafts()[0],
      api_key: "sk-live-secret",
      masked: "",
    };
    const patch = buildSavedAgentModelDraftPatch(draft, baseStatus, { masked: "sk-***9999" });

    expect(patch.api_key).toBe("");
    expect(patch.configured).toBe(true);
    expect(patch.masked).toBe("sk-***9999");
    expect(patch.saved_model).toBe("model-a");
  });

  it("falls back to existing masked key when config save omits key status", () => {
    const draft = {
      ...defaultAgentModelDrafts()[0],
      masked: "existing-***key",
    };
    const patch = buildSavedAgentModelDraftPatch(draft, { ...baseStatus, masked: "" }, null);

    expect(patch.masked).toBe("existing-***key");
    expect(patch.configured).toBe(true);
    expect(hasUnsavedAgentModelDraft({ ...draft, api_key: "new-secret" })).toBe(true);
  });
});
