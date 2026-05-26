import { Database, FolderOpen, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import type { FormEvent } from "react";
import { formatTaskStatus } from "../tasks/taskReducer";
import type { LastIndexRun } from "./settingsTypes";

type VaultBindingSectionProps = {
  vaultId: string | null;
  vaultPath: string;
  lastIndexRun: LastIndexRun | null;
  indexingVault: boolean;
  canSelectVaultDirectory: boolean;
  onVaultPathChange: (vaultPath: string) => void;
  onSelectVaultDirectory: () => void;
  onBindVault: (event: FormEvent) => void;
  onLoadVaultStatus: () => void;
  onRebuildIndex: () => void;
};

export function VaultBindingSection({
  vaultId,
  vaultPath,
  lastIndexRun,
  indexingVault,
  canSelectVaultDirectory,
  onVaultPathChange,
  onSelectVaultDirectory,
  onBindVault,
  onLoadVaultStatus,
  onRebuildIndex,
}: VaultBindingSectionProps) {
  return (
    <form className="stack separated" onSubmit={onBindVault}>
      <label>
        <span>Obsidian/Markdown Vault 路径</span>
        <div className="path-picker">
          <input
            value={vaultPath}
            onChange={(event) => onVaultPathChange(event.target.value)}
            placeholder="例如：E:\\AgentMemory 或 D:\\Obsidian\\副本"
            aria-describedby="vault-path-help"
          />
          <button
            type="button"
            className="secondary"
            onClick={onSelectVaultDirectory}
            disabled={!canSelectVaultDirectory}
            title={canSelectVaultDirectory ? "选择 Vault 文件夹" : "浏览器模式请手动填写路径"}
          >
            <FolderOpen size={16} />
            选择文件夹
          </button>
        </div>
        <p id="vault-path-help" className="field-note">
          {canSelectVaultDirectory
            ? "选择后只会填入路径，仍需点击初始化；不要选择 .tmp 或 smoke 工作目录。"
            : "浏览器模式无法打开系统文件夹选择器，请手动填写路径后点击初始化。"}
        </p>
      </label>
      <div className="button-row">
        <button type="submit" disabled={indexingVault}>
          {indexingVault ? <Loader2 className="spin" size={16} /> : <Database size={16} />}
          {indexingVault ? "处理中" : "初始化"}
        </button>
        <button type="button" className="secondary" onClick={onLoadVaultStatus}>
          <ShieldCheck size={16} />
          状态
        </button>
        <button type="button" className="secondary" onClick={onRebuildIndex} disabled={indexingVault}>
          {indexingVault ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          索引
        </button>
      </div>
      <dl className="details single">
        <div>
          <dt>当前 Vault</dt>
          <dd>{vaultId || "未知"}</dd>
        </div>
        <div>
          <dt>最近索引</dt>
          <dd>
            {lastIndexRun
              ? `${lastIndexRun.vaultId} / ${lastIndexRun.jobId} / ${formatTaskStatus(lastIndexRun.status)} / 已索引 ${lastIndexRun.filesIndexed ?? 0}/${lastIndexRun.filesSeen ?? 0} 个文件`
              : "尚未在本页启动索引"}
          </dd>
        </div>
      </dl>
    </form>
  );
}
