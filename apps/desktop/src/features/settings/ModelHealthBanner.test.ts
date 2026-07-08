import { describe, expect, it } from "vitest";
import type { AgentModelHealth, ModelHealthResponse } from "../../types";
import { agentModelDefinitions } from "../../services/agentModelDrafts";
import { getModelHealthBannerState } from "./ModelHealthBanner";

function health(details: AgentModelHealth[], globalConfigured = true): ModelHealthResponse {
  return {
    global_configured: globalConfigured,
    agents_configured: details.filter((detail) => detail.source === "agent_specific").length,
    agents_fallback_to_global: details.filter((detail) => detail.source === "global_fallback").length,
    agents_fallback_to_default: details.filter((detail) => detail.source === "hardcoded_default").length,
    agent_details: details,
  };
}

describe("ModelHealthBanner", () => {
  it("describes partial advanced capability overrides without exposing internal agent names", () => {
    const response = health(
      agentModelDefinitions.map((definition) => ({
        agent_id: definition.id,
        source: definition.id === "action_agent" || definition.id === "retrieval_agent" ? "agent_specific" : "global_fallback",
        model: "model-a",
      })),
    );

    const banner = getModelHealthBannerState(response);

    expect(banner?.message).toContain("2/5 个高级能力");
    expect(banner?.message).not.toMatch(/9 agents|9 个智能体|结果路由|task_agent|wiki_manager_agent/);
  });

  it("explains that the default conversation capability supports the product", () => {
    const response = health(
      agentModelDefinitions.map((definition) => ({
        agent_id: definition.id,
        source: "global_fallback",
        model: "model-a",
      })),
    );

    expect(getModelHealthBannerState(response)?.message).toContain("对话能力已连接");
  });
});
