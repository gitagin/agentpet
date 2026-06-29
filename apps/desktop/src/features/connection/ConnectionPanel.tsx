import { Check, Loader2, RefreshCw } from "lucide-react";
import type { ConnectionSettings, HealthResponse } from "../../types";
import { HealthStatus } from "./HealthStatus";
import type { BusinessAuthStatus } from "./connectionStatus";

type ConnectionPanelProps = {
  settings: ConnectionSettings;
  onSettingsChange: (settings: ConnectionSettings) => void;
  onSaveSettings: (settings: ConnectionSettings) => void;
  onCheckHealth: () => void;
  checkingHealth: boolean;
  isElectronRuntime: boolean;
  health: HealthResponse | null;
  businessAuthStatus: BusinessAuthStatus;
  businessAuthMessage: string;
};

export function ConnectionPanel({
  settings,
  onSettingsChange,
  onSaveSettings,
  onCheckHealth,
  checkingHealth,
  isElectronRuntime,
  health,
  businessAuthStatus,
  businessAuthMessage,
}: ConnectionPanelProps) {
  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        onSaveSettings(settings);
      }}
    >
      <label>
        <span>本机服务地址</span>
        <input
          value={settings.baseUrl}
          onChange={(event) => onSettingsChange({ ...settings, baseUrl: event.target.value })}
          placeholder="http://127.0.0.1:8765"
        />
      </label>
      <p className="field-note">
        {isElectronRuntime
          ? "桌面端由主进程安全注入会话令牌，渲染进程不会读取或保存令牌。"
          : "浏览器模式仅支持公开健康检查；受保护接口需要通过桌面端主进程代理。"}
      </p>
      <div className="button-row">
        <button type="submit">
          <Check size={16} />
          保存
        </button>
        <button type="button" className="secondary" onClick={onCheckHealth} disabled={checkingHealth}>
          {checkingHealth ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          健康检查
        </button>
      </div>
      <HealthStatus health={health} businessAuthStatus={businessAuthStatus} />
      <p className="field-note">{businessAuthMessage}</p>
    </form>
  );
}
