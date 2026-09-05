import { useCallback, useState } from "react";

import { describeError } from "../../services/apiErrorMessages";
import type { DesktopApi } from "../../services/desktopApi";
import type {
  CompanionConsolidationRunResponse,
  LocalAssetStatsResponse,
  MemoryFeedbackResponse,
  MemoryHygieneActionResponse,
  MemoryHygienePreviewResponse,
  MemoryReviewAction,
  MemoryReviewItem,
  MemoryReviewResponse,
} from "../../types";

export type MaintenanceLoadStatus = "idle" | "loading" | "success" | "error";

export type UseMemoryMaintenanceResult = {
  assets: LocalAssetStatsResponse | null;
  assetsStatus: MaintenanceLoadStatus;
  assetsError: string;
  hygiene: MemoryHygienePreviewResponse | null;
  hygieneStatus: MaintenanceLoadStatus;
  hygieneError: string;
  hygieneActionIds: Set<string>;
  hygieneNotice: string;
  review: MemoryReviewResponse | null;
  reviewStatus: MaintenanceLoadStatus;
  reviewError: string;
  reviewActionIds: Set<string>;
  reviewNotice: string;
  consolidation: CompanionConsolidationRunResponse | null;
  consolidationRunning: boolean;
  consolidationNotice: string;
  consolidationFailed: boolean;
  loadAssets: () => Promise<void>;
  loadHygiene: () => Promise<void>;
  applyHygiene: (suggestionId: string, confirmed: boolean) => Promise<MemoryHygieneActionResponse | null>;
  loadReview: () => Promise<void>;
  applyReviewAction: (item: MemoryReviewItem, action: MemoryReviewAction, replacementText?: string) => Promise<MemoryFeedbackResponse | null>;
  runConsolidation: () => Promise<void>;
};

function actionKey(targetType: string, targetId: string, action: string): string {
  return `${targetType}:${targetId}:${action}`;
}

export function useMemoryMaintenance(api: DesktopApi): UseMemoryMaintenanceResult {
  const [assets, setAssets] = useState<LocalAssetStatsResponse | null>(null);
  const [assetsStatus, setAssetsStatus] = useState<MaintenanceLoadStatus>("idle");
  const [assetsError, setAssetsError] = useState("");
  const [hygiene, setHygiene] = useState<MemoryHygienePreviewResponse | null>(null);
  const [hygieneStatus, setHygieneStatus] = useState<MaintenanceLoadStatus>("idle");
  const [hygieneError, setHygieneError] = useState("");
  const [hygieneActionIds, setHygieneActionIds] = useState<Set<string>>(new Set());
  const [hygieneNotice, setHygieneNotice] = useState("");
  const [review, setReview] = useState<MemoryReviewResponse | null>(null);
  const [reviewStatus, setReviewStatus] = useState<MaintenanceLoadStatus>("idle");
  const [reviewError, setReviewError] = useState("");
  const [reviewActionIds, setReviewActionIds] = useState<Set<string>>(new Set());
  const [reviewNotice, setReviewNotice] = useState("");
  const [consolidation, setConsolidation] = useState<CompanionConsolidationRunResponse | null>(null);
  const [consolidationRunning, setConsolidationRunning] = useState(false);
  const [consolidationNotice, setConsolidationNotice] = useState("");
  const [consolidationFailed, setConsolidationFailed] = useState(false);

  const loadAssets = useCallback(async () => {
    setAssetsStatus("loading");
    setAssetsError("");
    try {
      const response = await api.getLocalAssetStats();
      setAssets(response);
      setAssetsStatus("success");
    } catch (error) {
      setAssetsError(describeError(error, "本地资产统计读取失败"));
      setAssetsStatus("error");
    }
  }, [api]);

  const loadHygiene = useCallback(async () => {
    setHygieneStatus("loading");
    setHygieneError("");
    setHygieneNotice("");
    try {
      const response = await api.getMemoryHygienePreview();
      setHygiene(response);
      setHygieneStatus("success");
    } catch (error) {
      setHygieneError(describeError(error, "记忆卫生建议读取失败"));
      setHygieneStatus("error");
    }
  }, [api]);

  const applyHygiene = useCallback(
    async (suggestionId: string, confirmed: boolean) => {
      setHygieneActionIds((current) => new Set(current).add(suggestionId));
      setHygieneNotice("");
      try {
        const response = await api.applyMemoryHygieneSuggestion(suggestionId, confirmed);
        setHygiene((current) =>
          current
            ? { ...current, suggestions: current.suggestions.filter((suggestion) => suggestion.id !== suggestionId) }
            : current,
        );
        setHygieneNotice("建议已执行。");
        return response;
      } catch (error) {
        setHygieneNotice(describeError(error, "建议执行失败"));
        return null;
      } finally {
        setHygieneActionIds((current) => {
          const next = new Set(current);
          next.delete(suggestionId);
          return next;
        });
      }
    },
    [api],
  );

  const loadReview = useCallback(async () => {
    setReviewStatus("loading");
    setReviewError("");
    setReviewNotice("");
    try {
      const response = await api.getWeeklyMemoryReview();
      setReview(response);
      setReviewStatus("success");
    } catch (error) {
      setReviewError(describeError(error, "每周记忆回顾读取失败"));
      setReviewStatus("error");
    }
  }, [api]);

  const applyReviewAction = useCallback(
    async (item: MemoryReviewItem, action: MemoryReviewAction, replacementText?: string) => {
      const key = actionKey(item.target_type, item.target_id, action);
      setReviewActionIds((current) => new Set(current).add(key));
      setReviewNotice("");
      try {
        const response = await api.applyWeeklyMemoryReviewAction({
          target_type: item.target_type,
          target_id: item.target_id,
          action,
          feedback_text: replacementText !== undefined ? undefined : "",
          replacement_text: replacementText ?? null,
        });
        setReview((current) =>
          current ? { ...current, items: current.items.filter((entry) => entry.review_id !== item.review_id) } : current,
        );
        setReviewNotice("回顾操作已执行。");
        return response;
      } catch (error) {
        setReviewNotice(describeError(error, "回顾操作失败"));
        return null;
      } finally {
        setReviewActionIds((current) => {
          const next = new Set(current);
          next.delete(key);
          return next;
        });
      }
    },
    [api],
  );

  const runConsolidation = useCallback(async () => {
    setConsolidationRunning(true);
    setConsolidationNotice("");
    setConsolidationFailed(false);
    try {
      const response = await api.runCompanionConsolidation();
      setConsolidation(response);
      setConsolidationNotice(
        response.status === "completed"
          ? `整合完成：读取 ${response.source_count} 条，产出 ${response.output_count} 条，跳过 ${response.skipped_count} 条。`
          : response.reason || "整合已排队。",
      );
    } catch (error) {
      setConsolidationFailed(true);
      setConsolidationNotice(describeError(error, "整合运行失败"));
    } finally {
      setConsolidationRunning(false);
    }
  }, [api]);

  return {
    assets,
    assetsStatus,
    assetsError,
    hygiene,
    hygieneStatus,
    hygieneError,
    hygieneActionIds,
    hygieneNotice,
    review,
    reviewStatus,
    reviewError,
    reviewActionIds,
    reviewNotice,
    consolidation,
    consolidationRunning,
    consolidationNotice,
    consolidationFailed,
    loadAssets,
    loadHygiene,
    applyHygiene,
    loadReview,
    applyReviewAction,
    runConsolidation,
  };
}
