import { describe, expect, it } from "vitest";
import { ApiError } from "./apiClient";
import {
  businessAuthMismatchMessage,
  describeBusinessAuthFailure,
  describeError,
  isSidecarStartingError,
} from "./apiErrorMessages";

function buildApiError(message: string, status: number, code?: string, requestId?: string): ApiError {
  return new ApiError(message, status, {
    error: {
      code,
      message,
      request_id: requestId,
    },
  });
}

describe("apiErrorMessages", () => {
  it("formats ApiError with prefix, code and request id", () => {
    const message = describeError(buildApiError("无权限", 403, "forbidden", "req-1"), "设置状态读取失败");

    expect(message).toBe("设置状态读取失败: forbidden: 无权限 (request req-1)");
  });

  it("classifies network failures with a Chinese local service hint", () => {
    const message = describeError(new TypeError("fetch failed"), "健康检查失败");

    expect(message).toContain("健康检查失败");
    expect(message).toContain("无法连接本机服务");
    expect(message).toContain("连接诊断");
    expect(message).not.toContain("8765");
  });

  it("keeps unknown errors safe and user-facing", () => {
    expect(describeError(null, "任务加载失败")).toBe("任务加载失败: 发生未知桌面客户端错误。");
  });

  it("returns a dedicated business auth failure state for 401", () => {
    const failure = describeBusinessAuthFailure(buildApiError("Unauthorized", 401));

    expect(failure.status).toBe("unauthorized");
    expect(failure.message).toContain("当前桌面会话无法访问");
    expect(failure.message).not.toContain("8765");
  });

  it("returns a reusable mismatch notice for health-success auth mismatch", () => {
    expect(businessAuthMismatchMessage()).toContain("本机服务已响应");
    expect(businessAuthMismatchMessage()).toContain("连接诊断");
    expect(businessAuthMismatchMessage()).not.toContain("8765");
  });
  it("recognizes Electron sidecar startup responses as transient", () => {
    expect(isSidecarStartingError(buildApiError("starting", 503, "sidecar_starting"))).toBe(true);
    expect(isSidecarStartingError(buildApiError("unavailable", 503, "provider_unreachable"))).toBe(false);
    expect(isSidecarStartingError(new Error("starting"))).toBe(false);
  });
});
