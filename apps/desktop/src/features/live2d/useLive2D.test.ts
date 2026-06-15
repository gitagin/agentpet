import { describe, expect, it, vi } from "vitest";

vi.mock("../../services/cubismRenderer", () => ({
  createCubismRenderer: vi.fn(),
}));

import { parseLive2DManifestPayload } from "./useLive2D";

describe("useLive2D manifest parsing", () => {
  it("treats an HTML fallback response as a missing pending Cubism export", () => {
    const result = parseLive2DManifestPayload("<!doctype html><html><body>Vite app</body></html>", "text/html");

    expect(result).toMatchObject({
      status: "missing",
      error: "模型清单尚未导出，开发服务器返回了 HTML 页面。",
    });
  });

  it("parses a real model3 manifest payload", () => {
    const result = parseLive2DManifestPayload(
      JSON.stringify({ Version: 3, FileReferences: { Moc: "model.moc3" } }),
      "application/json",
    );

    expect(result).toMatchObject({
      status: "loaded",
      manifest: {
        Version: 3,
        FileReferences: { Moc: "model.moc3" },
      },
    });
  });
});
