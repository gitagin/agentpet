import type { ComponentProps } from "react";
import { Loader2, RefreshCw, Settings } from "lucide-react";
import { Panel } from "../../components/layout";
import { ConnectionPanel } from "../connection/ConnectionPanel";

export type ConnectionManagementPanelProps = ComponentProps<typeof ConnectionPanel> & {
  resettingLocalState: boolean;
  onResetLocalState: () => void;
};

export function ConnectionManagementPanel({
  resettingLocalState,
  onResetLocalState,
  ...connectionProps
}: ConnectionManagementPanelProps) {
  return (
    <Panel id="connection-panel" icon={<Settings size={18} />} title="对话能力连接">
      <ConnectionPanel {...connectionProps} />
      <section className="danger-zone" aria-label="本机状态重置">
        <div className="section-heading">
          <strong>重置桌宠初始化状态</strong>
          <span>清空本机聊天、记忆、任务、保存位置、资料整理缓存和连接配置，让应用回到首次启动状态。</span>
        </div>
        <div className="button-row">
          <button
            type="button"
            className="danger"
            onClick={onResetLocalState}
            disabled={resettingLocalState}
          >
            {resettingLocalState ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            {resettingLocalState ? "正在重置" : "重置桌宠"}
          </button>
        </div>
        <p className="field-note error">
          仅清理本机应用状态和本地凭据引用，不删除已选择的本地文件夹。请只在你确定要重新开始设置时使用。
        </p>
      </section>
    </Panel>
  );
}
