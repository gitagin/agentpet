import type { DesktopSidecarStatus, HealthResponse } from "../../types";
import { formatBusinessAuthStatus, formatDatabaseStatus, formatSidecarStatus, type BusinessAuthStatus } from "./connectionStatus";

type ConnectionStatusStripProps = {
  sidecarStatus: DesktopSidecarStatus | null;
  health: HealthResponse | null;
};

export function ConnectionStatusStrip({ sidecarStatus, health }: ConnectionStatusStripProps) {
  const online = sidecarStatus?.state === "ready" || sidecarStatus?.state === "degraded" || health?.status === "ok";

  return (
    <div className="status-strip" aria-live="polite">
      <span className={online ? "status-dot online" : "status-dot"} />
      <span>{formatSidecarStatus(sidecarStatus, health)}</span>
    </div>
  );
}

type HealthStatusProps = {
  health: HealthResponse | null;
  businessAuthStatus: BusinessAuthStatus;
};

export function HealthStatus({ health, businessAuthStatus }: HealthStatusProps) {
  return (
    <dl className="details">
      <div>
        <dt>版本</dt>
        <dd>{health?.version || "未知"}</dd>
      </div>
      <div>
        <dt>数据库</dt>
        <dd>{formatDatabaseStatus(health?.database)}</dd>
      </div>
      <div>
        <dt>业务鉴权</dt>
        <dd>{formatBusinessAuthStatus(businessAuthStatus)}</dd>
      </div>
    </dl>
  );
}
