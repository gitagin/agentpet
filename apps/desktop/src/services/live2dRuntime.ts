import type { Live2DActionProfile, Live2DMotionRef } from "./live2dActions";
import type {
  CubismRendererDiagnostics,
  CubismRendererHandle,
  CubismRendererResizeSize,
  CubismRenderMode,
} from "./cubismRenderer";

export type Live2DAssetStatus = "loading" | "recognized" | "preview" | "missing" | "error";

export type Live2DAssetInfo = {
  status: Live2DAssetStatus;
  modelId: string;
  modelLabel: string;
  modelDirectoryUrl: string;
  modelFileName: string;
  manifestPath: string;
  iconPath: string;
  hasIcon: boolean;
  version?: number;
  moc?: string;
  textureCount: number;
  expressionCount: number;
  expressions?: string[];
  motionCount: number;
  motions?: Live2DMotionRef[];
  defaultMotionGroup?: string;
  defaultMotionIndex?: number;
  hasPhysics: boolean;
  hasDisplayInfo: boolean;
  actionProfilePath?: string;
  actionProfile?: Live2DActionProfile | null;
  actionProfileStatus?: "none" | "loaded" | "error";
  actionProfileError?: string;
  actionCount?: number;
  previewOnly?: boolean;
  designPath?: string;
  error?: string;
};

export type Live2DModelManifest = {
  Version?: number;
  FileReferences?: {
    Moc?: string;
    Textures?: string[];
    Physics?: string;
    DisplayInfo?: string;
    Expressions?: Array<{
      Name?: string;
      File?: string;
    }>;
    Motions?: Live2DMotionGroups;
  };
};

export type Live2DMotionGroups = Record<string, Array<{ File?: string }>>;

export type Live2DRuntimeStatus = "not-connected" | "loading-assets" | "assets-ready" | "preview-only" | "mount-ready" | "failed";

export type Live2DRuntimeBoundary = {
  status: Live2DRuntimeStatus;
  title: string;
  detail: string;
  mountTargetId: string;
  rendererName: string;
  canMountRenderer: boolean;
};

export type Live2DRendererMountContext = {
  canvas: HTMLCanvasElement;
  asset: Live2DAssetInfo;
  variant: "pet" | "stage";
};

export type Live2DRuntimeHandle = CubismRendererHandle & {
  setActive?: (active: boolean) => void;
  setFocused?: (focused: boolean) => void;
  cleanup?: () => void;
  destroy?: () => void;
  unmount?: () => void;
  resize?: (size?: CubismRendererResizeSize) => void;
};

export type Live2DRendererMode = CubismRenderMode;
export type Live2DRendererDiagnostics = CubismRendererDiagnostics;

export type Live2DRendererMountResult = {
  status: "mounted" | "failed";
  message: string;
  renderMode: Live2DRendererMode;
  diagnostics?: CubismRendererDiagnostics;
  handle?: Live2DRuntimeHandle;
};

export type Live2DModelOption = {
  id: string;
  label: string;
  directory: string;
  model: string;
  icon?: string;
  actions?: string;
  previewOnly?: boolean;
  design?: string;
};

export type Live2DModelCatalog = {
  models: Live2DModelOption[];
};

export const live2dModelCatalogPath = "/live2d/models.json";
export const defaultLive2DModelOption: Live2DModelOption = {
  id: "gentle_girl",
  label: "温柔少女",
  directory: "/live2d/温柔少女/girlfriend/",
  model: "girlfriend.model3.json",
  icon: "icon.png",
  actions: "gentle_girl.actions.json",
};
export const live2dRuntimeMountTargetId = "live2d-runtime-canvas";

export const initialLive2DAssetInfo: Live2DAssetInfo = {
  status: "loading",
  modelId: defaultLive2DModelOption.id,
  modelLabel: defaultLive2DModelOption.label,
  modelDirectoryUrl: normalizeLive2DDirectory(defaultLive2DModelOption.directory),
  modelFileName: defaultLive2DModelOption.model,
  manifestPath: live2DManifestPath(defaultLive2DModelOption),
  iconPath: live2DIconPath(defaultLive2DModelOption),
  hasIcon: false,
  textureCount: 0,
  expressionCount: 0,
  motionCount: 0,
  actionProfileStatus: "none",
  actionCount: 0,
  previewOnly: defaultLive2DModelOption.previewOnly,
  designPath: live2DDesignPath(defaultLive2DModelOption),
  hasPhysics: false,
  hasDisplayInfo: false,
};

export function createLive2DAssetInfo(
  manifest: Live2DModelManifest,
  hasIcon: boolean,
  model: Live2DModelOption = defaultLive2DModelOption,
  actionProfile?: {
    profile?: Live2DActionProfile | null;
    error?: string;
  },
): Live2DAssetInfo {
  const references = manifest.FileReferences;
  const defaultMotion = getDefaultLive2DMotion(references?.Motions);
  const actionProfilePath = live2DActionProfilePath(model);
  const loadedActionProfile = actionProfile?.profile || null;
  const actionProfileStatus = actionProfilePath
    ? loadedActionProfile
      ? "loaded"
      : "error"
    : "none";

  return {
    status: "recognized",
    modelId: model.id,
    modelLabel: model.label,
    modelDirectoryUrl: normalizeLive2DDirectory(model.directory),
    modelFileName: model.model,
    manifestPath: live2DManifestPath(model),
    iconPath: live2DIconPath(model),
    hasIcon,
    version: manifest.Version,
    moc: references?.Moc,
    textureCount: references?.Textures?.length ?? 0,
    expressions: getLive2DExpressionKeys(references?.Expressions),
    expressionCount: references?.Expressions?.length ?? 0,
    motions: getLive2DMotionRefs(references?.Motions),
    motionCount: countLive2DMotions(references?.Motions),
    defaultMotionGroup: defaultMotion?.group,
    defaultMotionIndex: defaultMotion?.index,
    hasPhysics: Boolean(references?.Physics),
    hasDisplayInfo: Boolean(references?.DisplayInfo),
    actionProfilePath,
    actionProfile: loadedActionProfile,
    actionProfileStatus,
    actionProfileError: actionProfile?.error,
    actionCount: loadedActionProfile ? Object.keys(loadedActionProfile.actions).length : 0,
    previewOnly: model.previewOnly,
    designPath: live2DDesignPath(model),
  };
}

export function createPreviewLive2DAssetInfo(
  model: Live2DModelOption,
  hasIcon: boolean,
  actionProfile?: {
    profile?: Live2DActionProfile | null;
    error?: string;
  },
): Live2DAssetInfo {
  const actionProfilePath = live2DActionProfilePath(model);
  const loadedActionProfile = actionProfile?.profile || null;
  const actionProfileStatus = actionProfilePath
    ? loadedActionProfile
      ? "loaded"
      : "error"
    : "none";
  const previewExpressions = getLive2DActionProfileExpressions(loadedActionProfile);
  const previewMotions = getLive2DActionProfileMotions(loadedActionProfile);
  const defaultMotion = previewMotions[0];

  return {
    status: "preview",
    modelId: model.id,
    modelLabel: model.label,
    modelDirectoryUrl: normalizeLive2DDirectory(model.directory),
    modelFileName: model.model,
    manifestPath: live2DManifestPath(model),
    iconPath: live2DIconPath(model),
    hasIcon,
    textureCount: 0,
    expressions: previewExpressions,
    expressionCount: previewExpressions.length,
    motions: previewMotions,
    motionCount: previewMotions.length,
    defaultMotionGroup: defaultMotion?.group,
    defaultMotionIndex: defaultMotion?.index,
    hasPhysics: false,
    hasDisplayInfo: false,
    actionProfilePath,
    actionProfile: loadedActionProfile,
    actionProfileStatus,
    actionProfileError: actionProfile?.error,
    actionCount: loadedActionProfile ? Object.keys(loadedActionProfile.actions).length : 0,
    previewOnly: true,
    designPath: live2DDesignPath(model),
  };
}

export function createInitialLive2DAssetInfo(model: Live2DModelOption): Live2DAssetInfo {
  return {
    ...initialLive2DAssetInfo,
    modelId: model.id,
    modelLabel: model.label,
    modelDirectoryUrl: normalizeLive2DDirectory(model.directory),
    modelFileName: model.model,
    manifestPath: live2DManifestPath(model),
    iconPath: live2DIconPath(model),
    previewOnly: model.previewOnly,
    designPath: live2DDesignPath(model),
  };
}

export function normalizeLive2DDirectory(directory: string): string {
  const normalized = directory.trim().replace(/\\/g, "/");
  if (!normalized) {
    return normalizeLive2DDirectory(defaultLive2DModelOption.directory);
  }
  return normalized.endsWith("/") ? normalized : `${normalized}/`;
}

export function live2DManifestPath(model: Live2DModelOption): string {
  return `${normalizeLive2DDirectory(model.directory)}${model.model}`;
}

export function live2DIconPath(model: Live2DModelOption): string {
  if (!model.icon) {
    return "";
  }
  return `${normalizeLive2DDirectory(model.directory)}${model.icon}`;
}

export function live2DActionProfilePath(model: Live2DModelOption): string {
  if (!model.actions) {
    return "";
  }
  return `${normalizeLive2DDirectory(model.directory)}${model.actions}`;
}

export function live2DDesignPath(model: Live2DModelOption): string {
  if (!model.design) {
    return "";
  }
  return `${normalizeLive2DDirectory(model.directory)}${model.design}`;
}

export function countLive2DMotions(motions?: Live2DMotionGroups): number {
  if (!motions) {
    return 0;
  }

  return Object.values(motions).reduce((total, group) => total + group.length, 0);
}

function getLive2DExpressionKeys(expressions?: Array<{ Name?: string; File?: string }>): string[] {
  if (!expressions) {
    return [];
  }

  const keys = new Set<string>();
  for (const expression of expressions) {
    if (expression?.Name) {
      keys.add(expression.Name);
    }
    if (expression?.File) {
      keys.add(removeFileExtension(expression.File));
    }
  }
  return [...keys];
}

function getLive2DMotionRefs(motions?: Live2DMotionGroups): Live2DMotionRef[] {
  if (!motions) {
    return [];
  }

  const refs: Live2DMotionRef[] = [];
  for (const [group, motionList] of Object.entries(motions)) {
    motionList.forEach((motion, index) => {
      if (motion?.File) {
        refs.push({ group, index });
      }
    });
  }
  return refs;
}

function getDefaultLive2DMotion(motions?: Live2DMotionGroups): { group: string; index: number } | null {
  if (!motions) {
    return null;
  }

  for (const [group, motionList] of Object.entries(motions)) {
    const index = motionList.findIndex((motion) => Boolean(motion?.File));
    if (index >= 0) {
      return { group, index };
    }
  }

  return null;
}

function getLive2DActionProfileExpressions(profile?: Live2DActionProfile | null): string[] {
  if (!profile) {
    return [];
  }

  const expressions = new Set<string>();
  Object.values(profile.actions).forEach((action) => {
    if (action.expression) {
      expressions.add(action.expression);
    }
  });
  return [...expressions];
}

function getLive2DActionProfileMotions(profile?: Live2DActionProfile | null): Live2DMotionRef[] {
  if (!profile) {
    return [];
  }

  const motionKeys = new Set<string>();
  const motions: Live2DMotionRef[] = [];
  Object.values(profile.actions).forEach((action) => {
    const group = action.motion?.group;
    const index = action.motion?.index;
    if (!group || typeof index !== "number" || !Number.isInteger(index) || index < 0) {
      return;
    }
    const key = `${group}\u0000${index}`;
    if (motionKeys.has(key)) {
      return;
    }
    motionKeys.add(key);
    motions.push({ group, index });
  });
  return motions;
}

function removeFileExtension(fileName: string): string {
  const lastSlashIndex = fileName.lastIndexOf("/");
  const baseName = lastSlashIndex >= 0 ? fileName.slice(lastSlashIndex + 1) : fileName;
  const extensionIndex = baseName.lastIndexOf(".");
  return extensionIndex > 0 ? baseName.slice(0, extensionIndex) : baseName;
}

export function createLive2DRuntimeBoundary(asset: Live2DAssetInfo): Live2DRuntimeBoundary {
  if (asset.status === "recognized") {
    return {
      status: "assets-ready",
      title: "资源已就绪",
      detail: "模型清单、封面资源与 Cubism SDK 已识别；准备挂载真实 WebGL 渲染器。",
      mountTargetId: live2dRuntimeMountTargetId,
      rendererName: "Cubism SDK WebGL 渲染器",
      canMountRenderer: true,
    };
  }

  if (asset.status === "loading") {
    return {
      status: "loading-assets",
      title: "资源识别中",
      detail: "正在读取模型清单；资源就绪后会挂载 Cubism WebGL 渲染器。",
      mountTargetId: live2dRuntimeMountTargetId,
      rendererName: "Cubism SDK WebGL 渲染器",
      canMountRenderer: false,
    };
  }

  if (asset.status === "preview") {
    return {
      status: "preview-only",
      title: "角色预览",
      detail: "项目角色静态预览已启用；导出 Cubism model3 后会接管为真实 Live2D 渲染。",
      mountTargetId: live2dRuntimeMountTargetId,
      rendererName: "Cubism SDK WebGL 渲染器",
      canMountRenderer: false,
    };
  }

  if (asset.status === "missing") {
    return {
      status: "not-connected",
      title: "未接入",
      detail: "未读取到模型清单，渲染器挂载入口保持预留。",
      mountTargetId: live2dRuntimeMountTargetId,
      rendererName: "Cubism SDK WebGL 渲染器",
      canMountRenderer: false,
    };
  }

  return {
    status: "failed",
    title: "加载失败",
    detail: asset.error || "模型资源读取失败，Cubism WebGL 渲染器暂不能挂载。",
    mountTargetId: live2dRuntimeMountTargetId,
    rendererName: "Cubism SDK WebGL 渲染器",
    canMountRenderer: false,
  };
}

export function createRendererMountContext(
  canvas: HTMLCanvasElement | null,
  asset: Live2DAssetInfo,
  variant: "pet" | "stage",
): Live2DRendererMountContext | null {
  if (!canvas || asset.status !== "recognized") {
    return null;
  }

  return { canvas, asset, variant };
}

export async function mountLive2DRendererBoundary(
  context: Live2DRendererMountContext | null,
): Promise<Live2DRendererMountResult> {
  if (!context) {
    return {
      status: "failed",
      renderMode: "failed",
      message: "缺少 canvas 或模型资源未就绪，无法挂载 Cubism 渲染器。",
    };
  }

  try {
    const { createCubismRenderer } = await import("./cubismRenderer");
    const handle = await createCubismRenderer({
      canvas: context.canvas,
      modelDirectoryUrl: context.asset.modelDirectoryUrl,
      modelFileName: context.asset.modelFileName,
      variant: context.variant,
    });
    return {
      status: "mounted",
      renderMode: handle.getRenderMode(),
      diagnostics: handle.getDiagnostics(),
      message: `Live2D Cubism WebGL 渲染器已挂载，正在显示 ${context.asset.modelLabel} 模型。`,
      handle,
    };
  } catch (error) {
    console.warn("[Live2D] 渲染器挂载失败。", error);
    return {
      status: "failed",
      renderMode: "failed",
      message: `模型渲染不可用：${mapLive2DUserError(error)}`,
    };
  }
}

function mapLive2DUserError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || "");
  const lower = message.toLowerCase();

  if (lower.includes("webgl context")) {
    return "当前设备或显卡驱动暂不支持 WebGL 渲染。";
  }
  if (lower.includes("model3.json") || lower.includes("manifest")) {
    return "模型清单缺少必要配置。";
  }
  if (lower.includes("moc")) {
    return "核心模型文件加载或解析失败。";
  }
  if (lower.includes("texture") || lower.includes("贴图")) {
    return "模型贴图加载失败。";
  }
  if (lower.includes("shader") || lower.includes("着色器")) {
    return "渲染器着色器加载失败。";
  }
  if (lower.includes("load failed") || lower.includes("404") || lower.includes("http")) {
    return "模型资源缺失或无法读取。";
  }
  if (lower.includes("visible pixel") || lower.includes("可见") || lower.includes("像素")) {
    return "模型已加载，但当前画布没有检测到可见内容。";
  }
  if (lower.includes("null") || lower.includes("undefined")) {
    return "模型数据与渲染器状态不一致，请重新加载桌宠。";
  }

  return "Live2D 初始化失败，请在控制台诊断中查看技术细节。";
}
