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
  const totalAgents = agentModelDefinitions.length;

  if (health.global_configured && specialistCount === 0) {
    return {
      tone: "info",
      message: "5 个核心 Agent 正在继承全局模型；聊天、分类、检索、动作和后台反思都会正常工作。",
    };
  }

  if (specialistCount >= totalAgents) {
    return {
      tone: "success",
      message: "5 个核心 Agent 都有独立模型配置；仍会统一按新架构路由运行。",
    };
  }

  if (health.global_configured && specialistCount > 0) {
    return {
      tone: "info",
      message: `${specialistCount}/${totalAgents} 个核心 Agent 有独立模型，其余继续继承全局模型。`,
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
