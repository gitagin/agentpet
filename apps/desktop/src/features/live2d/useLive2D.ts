import { useEffect, useRef, useState } from "react";
import type { ChatContinuitySignal, ContinuityStateResponse } from "../../types";
import {
  createInitialLive2DAssetInfo,
  createLive2DAssetInfo,
  createLive2DRuntimeBoundary,
  defaultLive2DModelOption,
  initialLive2DAssetInfo,
  live2DIconPath,
  live2DManifestPath,
  live2dModelCatalogPath,
} from "../../services/live2dRuntime";
import type { Live2DAssetInfo, Live2DModelCatalog, Live2DModelManifest, Live2DModelOption } from "../../services/live2dRuntime";
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
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
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
          console.warn("[Live2D] 模型列表读取失败，使用默认 UG 模型。", error);
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
      setAsset(initialAsset);
      try {
        const [manifestResponse, hasIcon] = await Promise.all([
          fetch(live2DManifestPath(selectedModel), { signal: abort.signal }),
          selectedModel.icon ? checkImageExists(live2DIconPath(selectedModel)) : Promise.resolve(false),
        ]);

        if (!manifestResponse.ok) {
          if (!cancelled) {
            setAsset({
              ...initialAsset,
              status: "missing",
              hasIcon,
              error: `HTTP ${manifestResponse.status}`,
            });
          }
          return;
        }

        const manifest = (await manifestResponse.json()) as Live2DModelManifest;

        if (!cancelled) {
          setAsset(createLive2DAssetInfo(manifest, hasIcon, selectedModel));
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
    canvasRef,
    models,
    runtime,
    selectedModelId,
    selectModel,
    stage,
    triggerTaskStage,
  };
}
