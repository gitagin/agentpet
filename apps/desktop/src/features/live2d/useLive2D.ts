import { useEffect, useRef, useState } from "react";
import type { ChatContinuitySignal, ContinuityStateResponse } from "../../types";
import {
  createInitialLive2DAssetInfo,
  createLive2DAssetInfo,
  createLive2DRuntimeBoundary,
  createPreviewLive2DAssetInfo,
  defaultLive2DModelOption,
  initialLive2DAssetInfo,
  live2DActionProfilePath,
  live2DIconPath,
  live2DManifestPath,
  live2dModelCatalogPath,
} from "../../services/live2dRuntime";
import type { Live2DAssetInfo, Live2DModelCatalog, Live2DModelManifest, Live2DModelOption } from "../../services/live2dRuntime";
import { normalizeLive2DActionProfile } from "../../services/live2dActions";
import { describeError } from "../../services/apiErrorMessages";
import { live2dModelSelectionChannelName, live2dModelSelectionStorageKey } from "./live2dConstants";
import { broadcastLive2DModelSelection, loadLive2DModelSelection, saveLive2DModelSelection } from "./live2dStorage";
import { checkImageExists, getLive2DStageView, normalizeLive2DModelCatalog } from "./live2dUtils";

type UseLive2DOptions = {
  connected: boolean;
  streaming: boolean;
  searchResultCount: number;
  pendingProposalCount: number;
  taskCount: number;
  diagnosticsReady: boolean;
  continuityState: ContinuityStateResponse | null;
  continuitySignal: ChatContinuitySignal | null;
};

const live2DAssetCache = new Map<string, Live2DAssetInfo>();
type Live2DActionProfileLoadResult = Parameters<typeof createLive2DAssetInfo>[3];

type Live2DManifestPayloadResult =
  | { status: "loaded"; manifest: Live2DModelManifest }
  | { status: "missing"; error: string }
  | { status: "error"; error: string };

export function useLive2D({
  connected,
  streaming,
  searchResultCount,
  pendingProposalCount,
  taskCount,
  diagnosticsReady,
  continuityState,
  continuitySignal,
}: UseLive2DOptions) {
  const [models, setModels] = useState<Live2DModelOption[]>([defaultLive2DModelOption]);
  const [selectedModelId, setSelectedModelId] = useState<string>(() => loadLive2DModelSelection());
  const [asset, setAsset] = useState<Live2DAssetInfo>(initialLive2DAssetInfo);
  const [recentTaskStageActive, setRecentTaskStageActive] = useState(false);
  const taskStageTimeoutRef = useRef<number | null>(null);

  function triggerTaskStage() {
    setRecentTaskStageActive(true);
    if (taskStageTimeoutRef.current !== null) {
      window.clearTimeout(taskStageTimeoutRef.current);
    }
    taskStageTimeoutRef.current = window.setTimeout(() => {
      setRecentTaskStageActive(false);
      taskStageTimeoutRef.current = null;
    }, 12000);
  }

  function selectModel(modelId: string) {
    setSelectedModelId(modelId);
    saveLive2DModelSelection(modelId);
    broadcastLive2DModelSelection(modelId);
  }

  useEffect(() => {
    return () => {
      if (taskStageTimeoutRef.current !== null) {
        window.clearTimeout(taskStageTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    let cancelled = false;

    async function loadLive2DModels() {
      try {
        const response = await fetch(live2dModelCatalogPath, { signal: abort.signal });
        if (!response.ok) {
          return;
        }
        const catalog = (await response.json()) as Live2DModelCatalog;
        const normalizedModels = normalizeLive2DModelCatalog(catalog);
        if (!cancelled && normalizedModels.length > 0) {
          setModels(normalizedModels);
          setSelectedModelId((current) => (
            normalizedModels.some((model) => model.id === current) ? current : normalizedModels[0].id
          ));
        }
      } catch (error) {
        if (!abort.signal.aborted) {
          console.warn("[Live2D] 模型列表读取失败，使用项目默认模型。", error);
        }
      }
    }

    void loadLive2DModels();

    return () => {
      cancelled = true;
      abort.abort();
    };
  }, []);

  useEffect(() => {
    saveLive2DModelSelection(selectedModelId);
  }, [selectedModelId]);

  useEffect(() => {
    const applySelection = (modelId: string | null) => {
      if (!modelId) {
        return;
      }
      setSelectedModelId((current) => (
        current === modelId ? current : modelId
      ));
    };

    const handleStorage = (event: StorageEvent) => {
      if (event.key === live2dModelSelectionStorageKey) {
        applySelection(event.newValue);
      }
    };
    window.addEventListener("storage", handleStorage);
    const pollSelectionTimer = window.setInterval(() => {
      applySelection(loadLive2DModelSelection());
    }, 1000);

    let channel: BroadcastChannel | null = null;
    if ("BroadcastChannel" in window) {
      channel = new BroadcastChannel(live2dModelSelectionChannelName);
      channel.onmessage = (event) => {
        const modelId = typeof event.data?.modelId === "string" ? event.data.modelId : null;
        applySelection(modelId);
      };
    }

    return () => {
      window.removeEventListener("storage", handleStorage);
      window.clearInterval(pollSelectionTimer);
      channel?.close();
    };
  }, [models]);

  useEffect(() => {
    const abort = new AbortController();
    let cancelled = false;

    async function loadLive2DAsset() {
      const selectedModel = models.find((model) => model.id === selectedModelId) || models[0] || defaultLive2DModelOption;
      const initialAsset = createInitialLive2DAssetInfo(selectedModel);
      const cachedAsset = live2DAssetCache.get(selectedModel.id);
      setAsset(cachedAsset || initialAsset);
      try {
        if (selectedModel.previewOnly) {
          const [hasIcon, actionProfile] = await Promise.all([
            selectedModel.icon ? checkImageExists(live2DIconPath(selectedModel)) : Promise.resolve(false),
            loadLive2DActionProfile(selectedModel, abort.signal),
          ]);

          if (!cancelled) {
            const nextAsset = createPreviewLive2DAssetInfo(selectedModel, hasIcon, actionProfile);
            live2DAssetCache.set(selectedModel.id, nextAsset);
            setAsset(nextAsset);
          }
          return;
        }

        const [manifestResponse, hasIcon, actionProfile] = await Promise.all([
          fetch(live2DManifestPath(selectedModel), { signal: abort.signal }),
          selectedModel.icon ? checkImageExists(live2DIconPath(selectedModel)) : Promise.resolve(false),
          loadLive2DActionProfile(selectedModel, abort.signal),
        ]);

        if (!manifestResponse.ok) {
          if (!cancelled) {
            setAsset({
              ...initialAsset,
              status: "missing",
              hasIcon,
              actionProfilePath: live2DActionProfilePath(selectedModel),
              actionProfile: actionProfile?.profile || null,
              actionProfileStatus: selectedModel.actions
                ? actionProfile?.profile
                  ? "loaded"
                  : "error"
                : "none",
              actionProfileError: actionProfile?.error,
              actionCount: actionProfile?.profile ? Object.keys(actionProfile.profile.actions).length : 0,
              error: `HTTP ${manifestResponse.status}`,
            });
          }
          return;
        }

        const manifestPayload = await manifestResponse.text();
        const manifestResult = parseLive2DManifestPayload(
          manifestPayload,
          manifestResponse.headers.get("content-type"),
        );
        if (manifestResult.status !== "loaded") {
          if (!cancelled) {
            setAsset(createUnavailableLive2DAssetInfo({
              initialAsset,
              selectedModel,
              hasIcon,
              actionProfile,
              status: manifestResult.status,
              error: manifestResult.error,
            }));
          }
          return;
        }

        if (!cancelled) {
          const nextAsset = createLive2DAssetInfo(manifestResult.manifest, hasIcon, selectedModel, actionProfile);
          live2DAssetCache.set(selectedModel.id, nextAsset);
          setAsset(nextAsset);
        }
      } catch (error) {
        if (abort.signal.aborted || cancelled) {
          return;
        }

        setAsset({
          ...initialAsset,
          status: "error",
          error: describeError(error, "模型资源清单读取失败"),
        });
      }
    }

    void loadLive2DAsset();

    return () => {
      cancelled = true;
      abort.abort();
    };
  }, [models, selectedModelId]);

  const stage = getLive2DStageView({
    connected,
    streaming,
    searchResultCount,
    pendingProposalCount,
    taskCount: recentTaskStageActive ? Math.max(taskCount, 1) : 0,
    diagnosticsReady,
    continuityState,
    continuitySignal,
  });
  const runtime = createLive2DRuntimeBoundary(asset);

  return {
    asset,
    models,
    runtime,
    selectedModelId,
    selectModel,
    stage,
    triggerTaskStage,
  };
}

async function loadLive2DActionProfile(
  model: Live2DModelOption,
  signal: AbortSignal,
): Promise<Parameters<typeof createLive2DAssetInfo>[3]> {
  const profilePath = live2DActionProfilePath(model);
  if (!profilePath) {
    return { profile: null };
  }

  try {
    const response = await fetch(profilePath, { signal });
    if (!response.ok) {
      return { profile: null, error: `HTTP ${response.status}` };
    }
    const profile = normalizeLive2DActionProfile(await response.json());
    return profile ? { profile } : { profile: null, error: "动作配置格式无效" };
  } catch (error) {
    if (signal.aborted) {
      return { profile: null };
    }
    return { profile: null, error: describeError(error, "动作配置读取失败") };
  }
}

export function parseLive2DManifestPayload(
  payload: string,
  contentType?: string | null,
): Live2DManifestPayloadResult {
  const trimmedPayload = payload.trim();
  const normalizedPayload = trimmedPayload.toLowerCase();
  const normalizedContentType = (contentType || "").toLowerCase();
  if (!trimmedPayload) {
    return { status: "missing", error: "模型清单为空，可能尚未导出 Cubism model3.json。" };
  }
  if (
    normalizedContentType.includes("text/html") ||
    normalizedPayload.startsWith("<!doctype") ||
    normalizedPayload.startsWith("<html") ||
    normalizedPayload.startsWith("<")
  ) {
    return { status: "missing", error: "模型清单尚未导出，开发服务器返回了 HTML 页面。" };
  }

  try {
    const manifest = JSON.parse(trimmedPayload) as Live2DModelManifest;
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
      return { status: "error", error: "模型清单 JSON 格式无效。" };
    }
    return { status: "loaded", manifest };
  } catch (error) {
    return { status: "error", error: describeError(error, "模型清单 JSON 解析失败") };
  }
}

function createUnavailableLive2DAssetInfo({
  initialAsset,
  selectedModel,
  hasIcon,
  actionProfile,
  status,
  error,
}: {
  initialAsset: Live2DAssetInfo;
  selectedModel: Live2DModelOption;
  hasIcon: boolean;
  actionProfile?: Live2DActionProfileLoadResult;
  status: "missing" | "error";
  error: string;
}): Live2DAssetInfo {
  return {
    ...initialAsset,
    status,
    hasIcon,
    actionProfilePath: live2DActionProfilePath(selectedModel),
    actionProfile: actionProfile?.profile || null,
    actionProfileStatus: selectedModel.actions
      ? actionProfile?.profile
        ? "loaded"
        : "error"
      : "none",
    actionProfileError: actionProfile?.error,
    actionCount: actionProfile?.profile ? Object.keys(actionProfile.profile.actions).length : 0,
    error,
  };
}
