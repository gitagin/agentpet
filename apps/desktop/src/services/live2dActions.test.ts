import { describe, expect, it } from "vitest";
import { normalizeLive2DActionProfile, resolveLive2DActionDirective } from "./live2dActions";

describe("live2dActions", () => {
  it("normalizes a model action profile", () => {
    const profile = normalizeLive2DActionProfile({
      version: 1,
      description: "test",
      actions: {
        idle: {
          expression: "normal",
          motion: { group: "Idle", index: 0 },
          petHint: "待机",
          controlSummary: "待机动作",
        },
        empty: {},
      },
    });

    expect(profile).toMatchObject({
      version: 1,
      description: "test",
      actions: {
        idle: {
          expression: "normal",
          motion: { group: "Idle", index: 0 },
        },
      },
    });
    expect(profile?.actions.empty).toBeUndefined();
  });

  it("resolves an explicit model action with an empty Cubism motion group", () => {
    const profile = normalizeLive2DActionProfile({
      actions: {
        idle: {
          expression: "1desk",
          motion: { group: "", index: 1 },
        },
      },
    });

    const directive = resolveLive2DActionDirective({
      actionKey: "idle",
      profile,
      availableExpressions: ["1desk"],
      availableMotions: [{ group: "", index: 0 }, { group: "", index: 1 }],
      defaultMotionGroup: "",
      defaultMotionIndex: 0,
    });

    expect(directive).toMatchObject({
      actionKey: "idle",
      expression: "1desk",
      motionGroup: "",
      motionIndex: 1,
      warnings: [],
    });
  });

  it("does not apply model-specific default expressions without an action profile", () => {
    const directive = resolveLive2DActionDirective({
      actionKey: "chat_think",
      profile: null,
      availableExpressions: ["hiyori_smile"],
      availableMotions: [{ group: "Idle", index: 0 }],
      defaultMotionGroup: "Idle",
      defaultMotionIndex: 0,
    });

    expect(directive.expression).toBe("");
    expect(directive.motionGroup).toBe("Idle");
    expect(directive.motionIndex).toBe(0);
    expect(directive.petHint).toBe("正在思考，回复生成中。");
  });

  it("skips a missing configured expression and falls back to the default motion", () => {
    const profile = normalizeLive2DActionProfile({
      actions: {
        memory_search: {
          expression: "missing-expression",
          motion: { group: "Missing", index: 3 },
        },
      },
    });

    const directive = resolveLive2DActionDirective({
      actionKey: "memory_search",
      profile,
      availableExpressions: ["7keyboard"],
      availableMotions: [{ group: "Idle", index: 0 }],
      defaultMotionGroup: "Idle",
      defaultMotionIndex: 0,
    });

    expect(directive.expression).toBe("");
    expect(directive.motionGroup).toBe("Idle");
    expect(directive.motionIndex).toBe(0);
    expect(directive.warnings.join("\n")).toContain("missing-expression");
    expect(directive.warnings.join("\n")).toContain("Missing[3]");
  });
});
