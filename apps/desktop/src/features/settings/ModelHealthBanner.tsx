import { useEffect, useState } from "react";
import type { ModelHealthResponse } from "../../types";
import type { DesktopApi } from "../../services/desktopApi";

type ModelHealthBannerProps = {
  api: DesktopApi;
};

type BannerTone = "warning" | "info" | "success";

type BannerState = {
  tone: BannerTone;
  message: string;
};

function getBannerState(health: ModelHealthResponse): BannerState | null {
  if (!health.global_configured && health.agents_configured === 0) {
    return {
      tone: "warning",
      message: "你还没有配置任何模型，请先配置全局模型以开始使用。",
    };
  }

  if (health.agents_configured === 9) {
    return {
      tone: "success",
      message: "所有智能体已独立配置。",
    };
  }

  if (health.global_configured && health.agents_configured < 9) {
    return {
      tone: "info",
      message: `${health.agents_fallback_to_global} 个智能体使用全局模型，${health.agents_configured} 个有独立配置。`,
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

  const banner = getBannerState(health);
  if (!banner) {
    return null;
  }

  return <div className={`model-health-banner ${banner.tone}`}>{banner.message}</div>;
}
