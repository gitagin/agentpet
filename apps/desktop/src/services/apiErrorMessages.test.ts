import { describe, expect, it } from "vitest";
import { ApiError } from "./apiClient";
import { businessAuthMismatchMessage, describeBusinessAuthFailure, describeError } from "./apiErrorMessages";

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

  it("classifies network failures with a Chinese backend hint", () => {
    const message = describeError(new TypeError("fetch failed"), "健康检查失败");

    expect(message).toContain("健康检查失败");
    expect(message).toContain("无法连接后端");
    expect(message).toContain("8765");
  });

  it("keeps unknown errors safe and user-facing", () => {
    expect(describeError(null, "任务加载失败")).toBe("任务加载失败: 发生未知桌面客户端错误。");
  });

  it("returns a dedicated business auth failure state for 401", () => {
    const failure = describeBusinessAuthFailure(buildApiError("Unauthorized", 401));

    expect(failure.status).toBe("unauthorized");
    expect(failure.message).toContain("业务接口鉴权失败");
    expect(failure.message).toContain("会话令牌不一致");
  });

  it("returns a reusable mismatch notice for health-success auth mismatch", () => {
    expect(businessAuthMismatchMessage()).toContain("后端健康检查通过");
    expect(businessAuthMismatchMessage()).toContain("npm run electron:dev");
  });
});
