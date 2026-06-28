import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import type { DesktopApi } from "../../services/desktopApi";
import { describeError } from "../../services/apiErrorMessages";
import { EmptyState, Panel } from "../../components/layout";
import { formatReceiptTitle, MemoryReceiptList } from "./MemoryReceiptList";
import { PlaybackPreviewCard } from "./PlaybackPreviewCard";
import { ProjectCardList } from "./ProjectCardList";
import { TodayCard } from "./TodayCard";
import { useVisibleContinuity } from "./useVisibleContinuity";
import type { RetrospectiveReportPeriod, RetrospectiveWindow } from "../../types";
import type { VisibleContinuityReceipt, VisibleContinuitySnapshotResponse } from "./visibleContinuityTypes";

type VisibleContinuityPanelProps = {
  api?: DesktopApi;
  snapshot?: VisibleContinuitySnapshotResponse | null;
  autoLoad?: boolean;
  className?: string;
  onContinuePrompt?: (prompt: string) => void;
};

export function VisibleContinuityPanel({
  api,
  snapshot: providedSnapshot,
  autoLoad = true,
  className = "",
  onContinuePrompt,
}: VisibleContinuityPanelProps) {
  const [revertingReceiptIds, setRevertingReceiptIds] = useState<Set<string>>(new Set());
  const [receiptNotice, setReceiptNotice] = useState<{ tone: "success" | "error"; message: string } | null>(null);
  const [playbackWindows, setPlaybackWindows] = useState<RetrospectiveWindow[]>([]);
  const [playbackLoading, setPlaybackLoading] = useState(false);
  const [playbackWritingPeriod, setPlaybackWritingPeriod] = useState<RetrospectiveReportPeriod | null>(null);
  const [playbackNotice, setPlaybackNotice] = useState<string | null>(null);
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  const loader = useVisibleContinuity({
    api: api ?? fallbackApi,
    enabled: Boolean(api) && providedSnapshot === undefined,
    autoLoad,
  });
  const snapshot = providedSnapshot === undefined ? loader.snapshot : providedSnapshot;
  const loading = providedSnapshot === undefined && loader.status === "loading";
  const error = providedSnapshot === undefined ? loader.error : null;
  const canManageReceipts = Boolean(api) && providedSnapshot === undefined;

  async function revertReceipt(receipt: VisibleContinuityReceipt) {
    if (!api || providedSnapshot !== undefined) {
      return;
    }
    setRevertingReceiptIds((current) => new Set(current).add(receipt.action_id));
    setReceiptNotice(null);
    try {
      await api.revertAgentAction(receipt.action_id);
      await loader.refresh();
      setReceiptNotice({ tone: "success", message: `已撤回记录：${formatReceiptTitle(receipt)}。` });
    } catch (cause) {
      setReceiptNotice({
        tone: "error",
        message: describeError(cause, "记录撤回失败"),
      });
    } finally {
      setRevertingReceiptIds((current) => {
        const next = new Set(current);
        next.delete(receipt.action_id);
        return next;
      });
    }
  }

  async function loadPlayback() {
    if (!api || providedSnapshot !== undefined) {
      return;
    }
    setPlaybackLoading(true);
    setPlaybackError(null);
    try {
      const response = await api.getRetrospectives();
      setPlaybackWindows(response.windows);
      setPlaybackNotice("已从本地历史加载周回放和月回放。");
    } catch (cause) {
      setPlaybackError(describeError(cause, "回放加载失败"));
    } finally {
      setPlaybackLoading(false);
    }
  }

  async function writePlaybackReport(period: RetrospectiveReportPeriod) {
    if (!api || providedSnapshot !== undefined) {
      return;
    }
    setPlaybackWritingPeriod(period);
    setPlaybackError(null);
    setPlaybackNotice(null);
    try {
      const response = await api.writeRetrospectivePeriodReport(period);
      setPlaybackNotice(`已保存${formatPlaybackPeriod(period)}回放报告：${response.page.relative_path}。`);
      await loader.refresh();
    } catch (cause) {
      setPlaybackError(describeError(cause, `${formatPlaybackPeriod(period)}回放报告保存失败`));
    } finally {
      setPlaybackWritingPeriod(null);
    }
  }

  return (
    <Panel
      id="visible-continuity-panel"
      title="连续性概览"
      icon={<Sparkles size={18} />}
      className={`visible-continuity-panel ${className}`.trim()}
    >
      <div className="visible-continuity-shell">
        <header className="visible-continuity-header">
          <div>
            <p className="visible-continuity-kicker">今日、记录、任务、回放</p>
            <strong>你离开时发生了什么</strong>
          </div>
          {api && providedSnapshot === undefined ? (
            <button
              type="button"
              className="secondary visible-continuity-refresh"
              onClick={() => void loader.refresh()}
              disabled={loading}
              title="刷新连续性概览"
            >
              {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
              刷新
            </button>
          ) : null}
        </header>

        {error ? <p className="field-note error">{error}</p> : null}
        {receiptNotice ? (
          <p className={`field-note ${receiptNotice.tone === "error" ? "error" : ""}`}>{receiptNotice.message}</p>
        ) : null}
        {loading && !snapshot ? <EmptyState text="正在加载最新本地连续性快照。" /> : null}
        {!loading && !snapshot ? <EmptyState text="暂时还没有连续性快照。" /> : null}
        {snapshot ? (
          <div className="visible-continuity-content">
            <TodayCard today={snapshot.today_card} onContinuePrompt={onContinuePrompt} />
            <MemoryReceiptList
              receipts={snapshot.recent_receipts}
              revertingReceiptIds={revertingReceiptIds}
              onRevertReceipt={canManageReceipts ? (receipt) => void revertReceipt(receipt) : undefined}
            />
            <ProjectCardList projects={snapshot.project_cards} />
            <PlaybackPreviewCard
              playback={snapshot.playback_preview}
              windows={playbackWindows}
              loading={playbackLoading}
              writingPeriod={playbackWritingPeriod}
              notice={playbackNotice}
              error={playbackError}
              onLoadPlayback={canManageReceipts ? () => void loadPlayback() : undefined}
              onWriteReport={canManageReceipts ? (period) => void writePlaybackReport(period) : undefined}
            />
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

const fallbackApi = {
  getVisibleContinuitySnapshot: async () => {
    throw new Error("连续性概览 API 尚未配置。");
  },
  revertAgentAction: async () => {
    throw new Error("连续性概览 API 尚未配置。");
  },
  getRetrospectives: async () => {
    throw new Error("连续性概览 API 尚未配置。");
  },
  writeRetrospectivePeriodReport: async () => {
    throw new Error("连续性概览 API 尚未配置。");
  },
};

function formatPlaybackPeriod(period: RetrospectiveReportPeriod): string {
  return period === "weekly" ? "周" : "月";
}
