import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopLoginItemStatus, DesktopSidecarStatus } from "../../types";
import { ResidentRuntimeCard } from "./ResidentRuntimeCard";

const originalAgentDesktop = window.agentDesktop;

function sidecarStatus(state: DesktopSidecarStatus["state"]): DesktopSidecarStatus {
  return {
    state,
    baseUrl: "http://127.0.0.1:8765",
    host: "127.0.0.1",
    port: 8765,
    logPath: "",
    managed: true,
    pid: 123,
    updatedAt: "2026-08-09T00:00:00Z",
    health: null,
    error: null,
  };
}

function loginStatus(overrides: Partial<DesktopLoginItemStatus> = {}): DesktopLoginItemStatus {
  return { supported: true, enabled: false, ...overrides };
}

function setDesktop(overrides: Partial<NonNullable<Window["agentDesktop"]>> = {}) {
  window.agentDesktop = {
    platform: "win32",
    versions: {},
    getLoginItemStatus: vi.fn(async () => loginStatus()),
    setLoginItemEnabled: vi.fn(async () => loginStatus()),
    retrySidecar: vi.fn(async () => sidecarStatus("recovering")),
    ...overrides,
  };
}

describe("ResidentRuntimeCard", () => {
  beforeEach(() => {
    setDesktop();
  });

  afterEach(() => {
    window.agentDesktop = originalAgentDesktop;
    vi.restoreAllMocks();
  });

  it("explains and disables controls when the desktop bridge is unavailable", async () => {
    window.agentDesktop = undefined;
    render(<ResidentRuntimeCard />);

    expect(screen.getByRole("checkbox", { name: /登录后启动 Agent Pet/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /手动恢复/ })).toBeDisabled();
    await screen.findByText("当前运行环境不支持 Windows 登录项设置。");
  });

  it("keeps controls disabled while the authoritative login state is loading", async () => {
    let resolveStatus!: (status: DesktopLoginItemStatus) => void;
    const getLoginItemStatus = vi.fn(() => new Promise<DesktopLoginItemStatus>((resolve) => {
      resolveStatus = resolve;
    }));
    setDesktop({ getLoginItemStatus });
    render(<ResidentRuntimeCard />);

    expect(screen.getByRole("checkbox", { name: /登录后启动 Agent Pet/ })).toBeDisabled();
    expect(screen.getByText("正在读取 Windows 登录项状态。")).toBeInTheDocument();
    resolveStatus(loginStatus());
    await screen.findByText("已由 Windows 确认：登录后不自动启动。");
  });

  it("shows an authoritative mismatch instead of claiming the requested setting applied", async () => {
    const setLoginItemEnabled = vi.fn(async () => loginStatus());
    setDesktop({ setLoginItemEnabled });
    render(<ResidentRuntimeCard />);

    const checkbox = screen.getByRole("checkbox", { name: /登录后启动 Agent Pet/ });
    await screen.findByText("已由 Windows 确认：登录后不自动启动。");
    fireEvent.click(checkbox);

    await screen.findByText("Windows 返回的状态与请求不一致，请刷新后重试。");
    expect(checkbox).not.toBeChecked();
  });

  it("preserves the prior login state when the update fails", async () => {
    const setLoginItemEnabled = vi.fn(async () => {
      throw new Error("login item unavailable");
    });
    setDesktop({
      getLoginItemStatus: vi.fn(async () => loginStatus({ enabled: true })),
      setLoginItemEnabled,
    });
    render(<ResidentRuntimeCard />);

    const checkbox = screen.getByRole("checkbox", { name: /登录后启动 Agent Pet/ });
    await waitFor(() => expect(checkbox).toBeChecked());
    fireEvent.click(checkbox);

    await screen.findByText("登录项更新失败，原设置未被覆盖。");
    expect(checkbox).toBeChecked();
  });

  it("reports manual sidecar recovery feedback from the authoritative status", async () => {
    const retrySidecar = vi.fn(async () => sidecarStatus("manual-retry"));
    setDesktop({ retrySidecar });
    render(<ResidentRuntimeCard />);

    await screen.findByText("已由 Windows 确认：登录后不自动启动。");
    fireEvent.click(screen.getByRole("button", { name: /手动恢复/ }));

    await screen.findByText("本地助手仍未恢复，请查看诊断信息或稍后手动重试。");
    expect(retrySidecar).toHaveBeenCalledOnce();
  });
});
