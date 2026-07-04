import { useEffect, useState } from "react";

let runtimeAssetVersion = Date.now();

function versionedPublicAsset(path: string, version: number) {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}v=${version}`;
}

export function useVersionedPublicAsset(path: string) {
  const [version, setVersion] = useState(runtimeAssetVersion);

  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }

    const refreshVersion = () => {
      runtimeAssetVersion = Date.now();
      setVersion(runtimeAssetVersion);
    };

    const refreshWhenVisible = () => {
      if (!document.hidden) {
        refreshVersion();
      }
    };

    window.addEventListener("focus", refreshVersion);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener("focus", refreshVersion);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, []);

  return versionedPublicAsset(path, version);
}
