const cubismCoreScriptId = "live2d-cubism-core-script";
const cubismCoreUrl = "/live2d/CubismSdkForWeb-5-r.5/Core/live2dcubismcore.min.js";

let cubismCorePromise: Promise<void> | null = null;

type CubismCoreGlobal = typeof globalThis & {
  Live2DCubismCore?: unknown;
};

export function loadCubismCore(): Promise<void> {
  if (isCubismCoreReady()) {
    return Promise.resolve();
  }

  if (cubismCorePromise) {
    return cubismCorePromise;
  }

  cubismCorePromise = new Promise((resolve, reject) => {
    const existingScript = document.getElementById(cubismCoreScriptId) as HTMLScriptElement | null;
    if (existingScript) {
      existingScript.addEventListener("load", () => settleCubismCore(resolve, reject), { once: true });
      existingScript.addEventListener("error", () => reject(new Error("Cubism Core 脚本加载失败。")), { once: true });
      settleCubismCore(resolve, reject);
      return;
    }

    const script = document.createElement("script");
    script.id = cubismCoreScriptId;
    script.src = cubismCoreUrl;
    script.async = true;
    script.onload = () => settleCubismCore(resolve, reject);
    script.onerror = () => reject(new Error(`Cubism Core 脚本加载失败：${cubismCoreUrl}`));
    document.head.appendChild(script);
  });

  return cubismCorePromise;
}

export function isCubismCoreReady(): boolean {
  return Boolean((globalThis as CubismCoreGlobal).Live2DCubismCore);
}

function settleCubismCore(resolve: () => void, reject: (error: Error) => void) {
  if (isCubismCoreReady()) {
    resolve();
    return;
  }

  window.setTimeout(() => {
    if (isCubismCoreReady()) {
      resolve();
      return;
    }
    reject(new Error("Cubism Core 已加载，但未注册 Live2DCubismCore 全局对象。"));
  }, 0);
}
