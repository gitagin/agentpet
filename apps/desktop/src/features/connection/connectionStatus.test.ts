import { describe, expect, it } from "vitest";

import type { DesktopSidecarStatus } from "../../types";
import { getSidecarActionMessage } from "./connectionStatus";

function failedStatus(code: string): DesktopSidecarStatus {
  return {
    state: "error",
    baseUrl: "http://127.0.0.1:8765",
    host: "127.0.0.1",
    port: 8765,
    logPath: "C:\\AgentPet\\logs\\sidecar.log",
    managed: false,
    pid: null,
    updatedAt: "2026-08-04T00:00:00.000Z",
    health: null,
    error: { code, message: "raw failure" },
  };
}

describe("getSidecarActionMessage", () => {
  it.each(["SIDECAR_EXECUTABLE_NOT_FOUND", "READINESS_FAILED", "SPAWN_FAILED", "PROCESS_EXITED"])(
    "points %s failures to the persisted sidecar log",
    (code) => {
      const message = getSidecarActionMessage(failedStatus(code));

      expect(message).toContain("C:\\AgentPet\\logs\\sidecar.log");
      expect(message).not.toContain("终端日志");
      expect(message).not.toContain("Python 和 uvicorn");
    },
  );
});
