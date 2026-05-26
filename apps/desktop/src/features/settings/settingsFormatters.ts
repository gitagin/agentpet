import type { ModelTestResponse } from "../../types";

export function formatBooleanStatus(value?: boolean): string {
  if (typeof value !== "boolean") {
    return "未加载";
  }
  return value ? "是" : "否";
}

export function formatModelTestResult(result: ModelTestResponse): string {
  const latency = typeof result.latency_ms === "number" ? `，耗时 ${result.latency_ms}ms` : "";
  if (result.status === "ok") {
    return `成功：${result.model || "当前模型"}${latency}`;
  }
  const code = result.error_code ? `（${result.error_code}）` : "";
  return `失败${code}：${result.message}${latency}`;
}

export function formatVaultStatus(status: string): string {
  const labels: Record<string, string> = {
    bound: "绑定",
    created: "创建",
    initialized: "初始化",
  };
  return labels[status] || status;
}
