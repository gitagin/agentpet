import { Loader2, Power, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { DesktopLoginItemStatus } from "../../types";

export function ResidentRuntimeCard() {
  const [status, setStatus] = useState<DesktopLoginItemStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("正在读取 Windows 登录项状态。");

  const refresh = useCallback(async () => {
    const getStatus = window.agentDesktop?.getLoginItemStatus;
    if (!getStatus) {
      setStatus({ supported: false, enabled: false });
      setMessage("当前运行环境不支持 Windows 登录项设置。");
      return;
    }
    setBusy(true);
    try {
      const next = await getStatus();
      setStatus(next);
      setMessage(next.supported
        ? next.enabled
          ? "已由 Windows 确认：登录后驻留托盘。"
          : "已由 Windows 确认：登录后不自动启动。"
        : "当前系统不支持登录项设置。");
    } catch {
      setMessage("无法读取 Windows 登录项状态。");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function update(enabled: boolean) {
    const setEnabled = window.agentDesktop?.setLoginItemEnabled;
    if (!setEnabled) {
      return;
    }
    setBusy(true);
    try {
      const next = await setEnabled(enabled);
      setStatus(next);
      setMessage(next.enabled === enabled
        ? enabled
          ? "登录后启动已开启。"
          : "登录后启动已关闭。"
        : "Windows 返回的状态与请求不一致，请刷新后重试。");
    } catch {
      setMessage("登录项更新失败，原设置未被覆盖。");
    } finally {
      setBusy(false);
    }
  }

  async function retrySidecar() {
    const retry = window.agentDesktop?.retrySidecar;
    if (!retry) {
      return;
    }
    setBusy(true);
    try {
      const next = await retry();
      setMessage(next.state === "ready"
        ? "本地助手已恢复。"
        : next.state === "recovering" || next.state === "starting"
          ? "已请求恢复本地助手；状态会在连接区更新。"
          : "本地助手仍未恢复，请查看诊断信息或稍后手动重试。");
    } catch {
      setMessage("本地助手仍未恢复，请查看诊断信息。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="agent-model-section settings-card automation-settings-card" aria-label="登录驻留与恢复">
      <div className="section-heading">
        <strong>登录驻留与恢复</strong>
        <span>仅在 Windows 已登录且应用运行时保持托盘驻留；睡眠和关机期间不在线。</span>
      </div>
      <label className="automation-toggle-row">
        <input
          type="checkbox"
          checked={Boolean(status?.enabled)}
          disabled={busy || !status?.supported}
          onChange={(event) => void update(event.target.checked)}
        />
        <span>
          <strong>登录后启动 Agent Pet</strong>
          <small>状态直接从 Windows 登录项读回，默认不会强制开启。</small>
        </span>
      </label>
      <div className="settings-action-row">
        <div className="button-row">
          <button type="button" className="secondary" onClick={() => void refresh()} disabled={busy}>
            {busy ? <Loader2 className="spin" size={16} /> : <Power size={16} />}
            读取系统状态
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => void retrySidecar()}
            disabled={busy || !window.agentDesktop?.retrySidecar}
          >
            <RotateCcw size={16} />
            手动恢复
          </button>
        </div>
        <p className="field-note">{message}</p>
      </div>
    </section>
  );
}
