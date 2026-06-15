import { describe, expect, it, vi } from "vitest";

vi.mock("./cubismRenderer", () => ({
  createCubismRenderer: vi.fn(),
}));

import {
  createPreviewLive2DAssetInfo,
  defaultLive2DModelOption,
  live2DActionProfilePath,
  live2DDesignPath,
  live2DIconPath,
  live2DManifestPath,
} from "./live2dRuntime";

describe("live2dRuntime defaults", () => {
  it("uses the gentle girl Cubism model as the default selection", () => {
    expect(defaultLive2DModelOption).toMatchObject({
      id: "gentle_girl",
      label: "温柔少女",
      directory: "/live2d/温柔少女/girlfriend/",
      model: "girlfriend.model3.json",
      icon: "icon.png",
      actions: "gentle_girl.actions.json",
    });
    expect(live2DManifestPath(defaultLive2DModelOption)).toBe("/live2d/温柔少女/girlfriend/girlfriend.model3.json");
    expect(live2DIconPath(defaultLive2DModelOption)).toBe("/live2d/温柔少女/girlfriend/icon.png");
    expect(live2DActionProfilePath(defaultLive2DModelOption)).toBe("/live2d/温柔少女/girlfriend/gentle_girl.actions.json");
    expect(live2DDesignPath(defaultLive2DModelOption)).toBe("");
  });

  it("builds preview-only asset info without requiring a Cubism manifest", () => {
    const asset = createPreviewLive2DAssetInfo(defaultLive2DModelOption, true, {
      profile: {
        actions: {
          idle: {
            expression: "exp_idle_soft",
            motion: { group: "Idle", index: 0 },
          },
          chat_think: {
            expression: "exp_think_focus",
            motion: { group: "Chat", index: 1 },
          },
        },
      },
    });

    expect(asset).toMatchObject({
      status: "preview",
      modelId: "gentle_girl",
      hasIcon: true,
      designPath: "",
      actionProfileStatus: "loaded",
      actionCount: 2,
      expressionCount: 2,
      motionCount: 2,
      defaultMotionGroup: "Idle",
      defaultMotionIndex: 0,
    });
  });
});
