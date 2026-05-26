export function readRendererUiState(key: string): string | null {
  try {
    const electronValue = window.agentDesktop?.getUiState?.(key);
    if (typeof electronValue === "string") {
      return electronValue;
    }
  } catch (error) {
    console.warn("读取桌面 UI 状态失败，改用 sessionStorage。", error);
  }
  try {
    return sessionStorage.getItem(key);
  } catch (error) {
    console.warn("读取 sessionStorage 中的桌面 UI 状态失败。", error);
    return null;
  }
}

export function writeRendererUiState(key: string, value: string | null): void {
  try {
    window.agentDesktop?.setUiState?.(key, value);
  } catch (error) {
    console.warn("写入桌面 UI 状态失败，改用 sessionStorage。", error);
  }
  try {
    if (value === null) {
      sessionStorage.removeItem(key);
    } else {
      sessionStorage.setItem(key, value);
    }
  } catch (error) {
    console.warn("写入 sessionStorage 中的桌面 UI 状态失败。", error);
  }
}
