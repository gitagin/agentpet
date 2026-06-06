import { useEffect, useState } from "react";
import type { ModelHealthResponse } from "../../types";
import type { DesktopApi } from "../../services/desktopApi";
import { agentModelDefinitions } from "../../services/agentModelDrafts";

type ModelHealthBannerProps = {
  api: DesktopApi;
};

type BannerTone = "warning" | "info" | "success";

type BannerState = {
  tone: BannerTone;
  message: string;
};

export function getModelHealthBannerState(health: ModelHealthResponse): BannerState | null {
  if (!health.global_configured && health.agents_configured === 0) {
    return {
      tone: "warning",
      message: "你还没有配置任何模型，请先配置全局模型以开始使用。",
    };
  }

  const specialistCount = health.agent_details.filter((agent) => agent.source === "agent_specific").length;
  const totalOutcomes = new Set(agentModelDefinitions.map((agent) => agent.outcome)).size;
  const configuredOutcomes = new Set(
    health.agent_details.flatMap((detail) => {
      if (detail.source !== "agent_specific") {
        return [];
      }
      const definition = agentModelDefinitions.find((agent) => agent.id === detail.agent_id);
      return definition ? [definition.outcome] : [];
    }),
  ).size;

  if (health.global_configured && specialistCount === 0) {
    return {
      tone: "info",
      message: "所有结果路由正在继承全局模型；任务、记忆、知识库和回答仍会正常工作。",
    };
  }

  if (configuredOutcomes >= totalOutcomes) {
    return {
      tone: "success",
      message: "所有核心结果路由都有独立模型配置；仍会以任务、记忆、知识库和回答呈现。",
    };
  }

  if (health.global_configured && specialistCount > 0) {
    return {
      tone: "info",
      message: `${configuredOutcomes} 个结果路由有独立模型，其他结果路由继承全局模型。`,
    };
  }

  return null;
}

export function ModelHealthBanner({ api }: ModelHealthBannerProps) {
  const [health, setHealth] = useState<ModelHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setFailed(false);

    api.getModelHealth(controller.signal)
      .then((response) => {
        setHealth(response);
        setFailed(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setFailed(true);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [api]);

  if (loading) {
    return <div className="model-health-banner model-health-skeleton" aria-label="模型健康状态加载中" />;
  }

  if (failed || !health) {
    return null;
  }

  const banner = getModelHealthBannerState(health);
  if (!banner) {
    return null;
  }

  return <div className={`model-health-banner ${banner.tone}`}>{banner.message}</div>;
}
