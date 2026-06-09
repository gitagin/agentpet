import { Database, FolderOpen, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import type { FormEvent } from "react";
import type { VaultStatusResponse } from "../../types";
import { formatTaskStatus } from "../tasks/taskReducer";
import type { LastIndexRun } from "./settingsTypes";

type VaultBindingSectionProps = {
  vaultId: string | null;
  vaultPath: string;
  vaultStatus: VaultStatusResponse | null;
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
  vaultStatus,
  lastIndexRun,
  indexingVault,
  canSelectVaultDirectory,
  onVaultPathChange,
  onSelectVaultDirectory,
  onBindVault,
  onLoadVaultStatus,
  onRebuildIndex,
}: VaultBindingSectionProps) {
  const configured = vaultStatus?.configured ?? Boolean(vaultId);
  const latestIndexedAt = vaultStatus?.latest_indexed_at || "尚未索引";
  const safeRootLabel = vaultStatus?.root_path_label || (configured ? vaultId || "已绑定" : "未绑定");
  const markdownCount = vaultStatus?.markdown_count ?? 0;
  const wikiPageCount = vaultStatus?.wiki_page_count ?? 0;
  const diaryPageCount = vaultStatus?.diary_page_count ?? 0;

  return (
    <form className="stack separated settings-card" onSubmit={onBindVault}>
      <div className="section-heading">
        <strong>保存与导出位置</strong>
        <span>可选：选择一个本机 Markdown 文件夹，用来保存长期记忆和复盘报告。</span>
      </div>
      <label>
        <span>文件夹路径</span>
        <div className="path-picker">
          <input
            value={vaultPath}
            onChange={(event) => onVaultPathChange(event.target.value)}
            placeholder="例如：E:\\AgentMemory 或 D:\\Notes\\AgentExport"
            aria-describedby="vault-path-help"
          />
          <button
            type="button"
            className="secondary"
            onClick={onSelectVaultDirectory}
            disabled={!canSelectVaultDirectory}
            title={canSelectVaultDirectory ? "选择保存文件夹" : "浏览器模式请手动填写路径"}
          >
            <FolderOpen size={16} />
            选择文件夹
          </button>
        </div>
        <p id="vault-path-help" className="field-note">
          {canSelectVaultDirectory ? "选择后点击保存位置。" : "浏览器模式无法打开系统文件夹选择器，请手动填写路径。"}
        </p>
      </label>
      <div className="button-row">
        <button type="submit" disabled={indexingVault}>
          {indexingVault ? <Loader2 className="spin" size={16} /> : <Database size={16} />}
          {indexingVault ? "处理中" : "保存位置"}
        </button>
      </div>
      <section className="vault-summary-panel" aria-label="保存位置本地数据概览">
        <div className="section-heading compact">
          <strong>本地保存概览</strong>
          <span>{configured ? "已设置，数据保存在本机 Markdown 文件夹。" : "未设置，当前只使用应用本机状态。"}</span>
        </div>
        <dl className="details vault-summary-grid">
          <div>
            <dt>绑定状态</dt>
            <dd>{configured ? "已绑定" : "未绑定"}</dd>
          </div>
          <div>
            <dt>显示路径</dt>
            <dd>{safeRootLabel}</dd>
          </div>
          <div>
            <dt>最近索引</dt>
            <dd>{latestIndexedAt}</dd>
          </div>
          <div>
            <dt>Markdown</dt>
            <dd>{markdownCount}</dd>
          </div>
          <div>
            <dt>Wiki</dt>
            <dd>{wikiPageCount}</dd>
          </div>
          <div>
            <dt>日记</dt>
            <dd>{diaryPageCount}</dd>
          </div>
        </dl>
        <div className="vault-backup-preview" aria-label="导出和备份说明">
          <strong>导出/备份预览</strong>
          <p>
            保存位置是普通 Markdown 文件夹，可直接用 Obsidian 打开。备份时复制整个文件夹即可；本页只展示说明，不执行批量复制、移动或覆盖写入。
          </p>
        </div>
      </section>
      <details className="settings-advanced-actions">
        <summary>高级操作</summary>
        <div className="button-row">
          <button type="button" className="secondary" onClick={onLoadVaultStatus}>
            <ShieldCheck size={16} />
            查看状态
          </button>
          <button type="button" className="secondary" onClick={onRebuildIndex} disabled={indexingVault}>
            {indexingVault ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            重建索引
          </button>
        </div>
        <dl className="details single">
          <div>
            <dt>当前保存位置</dt>
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
      </details>
    </form>
  );
}
