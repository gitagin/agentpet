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
      message: "还没有连接对话能力，请先填写一个可用服务。",
    };
  }

  const specialistCount = health.agent_details.filter((agent) => agent.source === "agent_specific").length;
  const totalAgents = agentModelDefinitions.length;

  if (health.global_configured && specialistCount === 0) {
    return {
      tone: "info",
      message: "对话能力已连接；聊天、记忆整理和资料整理会使用这套默认设置。",
    };
  }

  if (specialistCount >= totalAgents) {
    return {
      tone: "success",
      message: "高级能力分工已单独设置；日常使用会继续按同一入口运行。",
    };
  }

  if (health.global_configured && specialistCount > 0) {
    return {
      tone: "info",
      message: `${specialistCount}/${totalAgents} 个高级能力已单独设置，其余继续使用默认对话能力。`,
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
