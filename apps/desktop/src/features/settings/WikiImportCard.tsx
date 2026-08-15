import { FolderOpen, Loader2, Upload } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { describeError } from "../../services/apiErrorMessages";
import type { DesktopApi } from "../../services/desktopApi";

type WikiImportCardProps = {
  api: DesktopApi;
};

// 复用记忆页面的深色 graphite 视觉变量（与 llmwiki-memory.css 的 --wiki-* 一致）
const GRAPHITE_VARS = {
  "--wiki-graphite": "#111214",
  "--wiki-graphite-soft": "#1B1D21",
  "--wiki-warm": "#F3F1EC",
  "--wiki-muted": "#A9A5A0",
  "--wiki-line": "rgba(243, 238, 232, 0.14)",
  "--wiki-teal": "#68B8AD",
  "--wiki-rose": "#D56F8A",
  "--wiki-amber": "#D1A44B",
} as CSSProperties;

export function WikiImportCard({ api }: WikiImportCardProps) {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error" | "info"; text: string } | null>(null);

  const canSelect = Boolean(window.agentDesktop?.selectWikiImportFolder);

  async function selectFolder() {
    const picker = window.agentDesktop?.selectWikiImportFolder;
    if (!picker) {
      setNotice({ tone: "info", text: "浏览器模式暂不支持选择文件夹，请使用桌面应用。" });
      return;
    }
    const path = await picker();
    if (!path) {
      return;
    }
    setSelectedFolder(path);
    setNotice(null);
  }

  async function importFolder() {
    if (!selectedFolder) {
      setNotice({ tone: "info", text: "请先选择一个知识库文件夹。" });
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const result = await api.importFolderBatch({
        folder_path: selectedFolder,
      });
      setSelectedFolder(null);
      setNotice({
        tone: result.status === "applied" ? "success" : "info",
        text: `已扫描 ${result.files_scanned} 个文件，写入 ${result.pages_written} 个资料页（${result.batches} 批）。`,
      });
    } catch (error) {
      setNotice({ tone: "error", text: describeError(error, "知识库导入失败") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-card settings-wiki-import-card" aria-label="导入知识库文件夹" style={GRAPHITE_VARS}>
      <div className="section-heading">
        <strong>导入知识库</strong>
        <span>选择一个 Obsidian 知识库文件夹，批量导入其中的 Markdown 文件为资料页。</span>
      </div>
      <div className="settings-wiki-import-body">
        <div className="settings-wiki-import-path" aria-label="已选择文件夹">
          <FolderOpen size={15} aria-hidden="true" />
          <span className={selectedFolder ? "" : "is-placeholder"}>
            {selectedFolder ?? "尚未选择文件夹"}
          </span>
        </div>
        {notice ? (
          <p className={`settings-wiki-import-notice is-${notice.tone}`} role="status">
            {notice.text}
          </p>
        ) : null}
        <div className="button-row">
          <button type="button" className="secondary" onClick={selectFolder} disabled={busy || !canSelect}>
            <Upload size={16} />
            选择文件夹
          </button>
          <button type="button" className="primary" onClick={importFolder} disabled={busy || !selectedFolder}>
            {busy ? <Loader2 className="spin" size={16} /> : <FolderOpen size={16} />}
            {busy ? "正在导入" : "导入"}
          </button>
        </div>
        <p className="field-note">
          原始文件保留在原位置，仅读取内容生成资料页；批量导入会扫描文件夹下的所有 Markdown 文件，敏感内容按策略处理。
        </p>
      </div>
    </section>
  );
}
