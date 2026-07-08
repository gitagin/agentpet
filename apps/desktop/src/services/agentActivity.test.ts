import { describe, expect, it } from "vitest";
import type { AgentAction, ChatMessage, ChatWikiProposal, ContinuityProposal, MemoryProposal } from "../types";
import {
  buildMemoryTrustGroups,
  buildAgentActivityEntries,
  canRevertAgentAction,
  formatAgentActionDecision,
  formatAgentActionRiskTier,
  formatAgentActionSource,
  formatAgentActionSkippedReason,
  formatAgentActionStatus,
  formatAgentActionType,
  getAgentActionDisplayFields,
  isAttentionAgentAction,
  normalizeAgentAction,
} from "./agentActivity";

function buildAction(overrides: Partial<AgentAction> = {}): AgentAction {
  return {
    action_id: "action-1",
    action_type: "memory.long_term.write",
    risk_tier: "low",
    decision: "auto",
    status: "completed",
    title: "已更新长期记忆",
    summary: "",
    target_paths: [],
    reversible: true,
    source: {},
    diff_summary: "",
    metadata: {},
    created_at: "2026-05-19T08:00:00.000Z",
    updated_at: "2026-05-19T08:00:00.000Z",
    completed_at: "2026-05-19T08:00:00.000Z",
    ...overrides,
  };
}

describe("agentActivity", () => {
  it("normalizes action payloads with safe defaults", () => {
    const action = normalizeAgentAction({
      id: "action-1",
      type: "wiki.page.write",
      requires_confirmation: true,
      risk_tier: "unexpected",
      status: "running",
      target_paths: ["Wiki/A.md", "Wiki/A.md", ""],
      source: { label: "Wiki review", source_message_id: "message-1" },
      diff_summary: "更新 1 个文件",
      metadata: { source: "test" },
      created_at: "2026-05-19T08:00:00.000Z",
    });

    expect(action).toMatchObject({
      action_id: "action-1",
      action_type: "wiki.page.write",
      risk_tier: "low",
      decision: "ask",
      status: "running",
      title: "已整理资料页",
      target_paths: ["Wiki/A.md"],
      source: { label: "Wiki review", source_message_id: "message-1" },
      diff_summary: "更新 1 个文件",
    });
  });

  it("formats activity labels", () => {
    expect(formatAgentActionType("wiki.page.write")).toBe("已整理资料页");
    expect(formatAgentActionType("custom.action")).toBe("custom / action");
    expect(formatAgentActionRiskTier("high")).toBe("高风险");
    expect(formatAgentActionDecision("ask")).toBe("需确认");
    expect(formatAgentActionStatus("reverted")).toBe("已撤回");
  });

  it("humanizes skipped automation reasons for the primary UI", () => {
    const skipped = buildAction({
      action_type: "chat.auto_memory.skip",
      status: "skipped",
      decision: "notify",
      title: "Skipped automatic organization",
      summary:
        "Skipped because automatic diary, structured memory, long-term memory, and Wiki organization are disabled; no local asset was written.",
      metadata: { skipped_reason: "automation_disabled" },
    });

    const display = getAgentActionDisplayFields(skipped);

    expect(display.actionName).toBe("已跳过自动整理");
    expect(display.summary).toContain("记忆整理设置当前关闭");
    expect(display.summary).not.toContain("Skipped");
    expect(formatAgentActionSkippedReason(skipped)).not.toContain("automation_disabled");
  });

  it("shows readable source text without exposing technical ids", () => {
    const action = buildAction({
      source_agent_run_id: "4379f293-ed73-48b7-b61a-3626e5a820c6",
      source_conversation_id: "cb043107-f07b-4d8e-b971-5b1fef35b260",
      source_message_id: "27e134ec-b30b-441f-a080-d1eef19cdf95",
      source: {
        label: "聊天日记归档",
        source_agent_run_id: "4379f293-ed73-48b7-b61a-3626e5a820c6",
        source_conversation_id: "cb043107-f07b-4d8e-b971-5b1fef35b260",
        source_message_id: "27e134ec-b30b-441f-a080-d1eef19cdf95",
      },
    });

    const source = formatAgentActionSource(action);

    expect(source).toBe("聊天日记归档 / 来自一条聊天消息 / 关联当前对话 / 由自动整理流程生成");
    expect(source).not.toContain("source_");
    expect(source).not.toContain("4379f293");
    expect(getAgentActionDisplayFields(action).sourceLabel).toBe(source);
  });

  it("distinguishes skipped reasons without exposing raw status codes", () => {
    const needsConfirmation = formatAgentActionSkippedReason(
      buildAction({
        action_type: "memory.long_term.skip",
        status: "skipped",
        summary: "Skipped because this is confirmation-only.",
        metadata: { skipped_reason: "confirmation-only" },
      }),
    );
    const nothingToSave = formatAgentActionSkippedReason(
      buildAction({
        action_type: "wiki.summary.skip",
        status: "skipped",
        summary: "Skipped because the reply did not produce saveable Wiki content.",
        metadata: { skipped_reason: "not_enough_reusable_knowledge" },
      }),
    );
    const lowValue = formatAgentActionSkippedReason(
      buildAction({
        action_type: "memory.long_term.skip",
        status: "skipped",
        summary: "Skipped because the message is too short or low-value.",
        metadata: { skipped_reason: "too short" },
      }),
    );

    expect(needsConfirmation).toContain("确认");
    expect(nothingToSave).toContain("资料页");
    expect(lowValue).toContain("长期保存");
    expect(new Set([needsConfirmation, nothingToSave, lowValue]).size).toBe(3);
    expect(`${needsConfirmation} ${nothingToSave} ${lowValue}`).not.toMatch(/confirmation-only|saveable|too short|low-value/);
  });

  it("detects reversible and attention actions", () => {
    expect(canRevertAgentAction(buildAction())).toBe(true);
    expect(canRevertAgentAction(buildAction({ reverted_by: "action-2" }))).toBe(false);
    expect(isAttentionAgentAction(buildAction({ risk_tier: "high" }))).toBe(true);
    expect(isAttentionAgentAction(buildAction({ error: "失败" }))).toBe(true);
  });

  it("builds recent activity entries with manual proposals first", () => {
    const memoryProposal: MemoryProposal = {
      proposal_id: "memory-1",
      type: "preference",
      content: "用户喜欢苹果",
      target_path: "Memories/LongTerm/Preferences.md",
      status: "pending",
    };
    const continuityProposal: ContinuityProposal = {
      proposal_id: "continuity-1",
      kind: "identity",
      summary: "身份整理",
      evidence: "原文",
      confidence: 0.8,
      status: "pending",
      created_at: "2026-05-19T08:01:00.000Z",
      updated_at: "2026-05-19T08:01:00.000Z",
    };
    const wikiProposal: ChatWikiProposal = {
      id: "wiki-1",
      proposal_type: "ingest",
      state: "pending",
      title: "Wiki",
      target_paths: ["Wiki/A.md"],
      recommended_targets: [],
      selected_targets: [],
      findings: [],
      updated_at: "2026-05-19T08:02:00.000Z",
    };
    const message: ChatMessage = {
      id: "message-1",
      role: "assistant",
      content: "需要确认",
      wiki_proposals: [wikiProposal],
    };

    const entries = buildAgentActivityEntries(
      [buildAction({ action_id: "action-old", updated_at: "2026-05-19T07:00:00.000Z" })],
      [memoryProposal],
      [continuityProposal],
      [message],
    );

    expect(entries.map((entry) => entry.kind)).toEqual([
      "memory_proposal",
      "continuity_proposal",
      "wiki_proposal",
      "agent_action",
    ]);
  });

  it("groups trustworthy memory activities by durable outcome", () => {
    const entries = buildAgentActivityEntries(
      [
        buildAction({ action_id: "daily", action_type: "chat.daily_archive" }),
        buildAction({ action_id: "structured", action_type: "diary.structured_memory" }),
        buildAction({ action_id: "wiki", action_type: "wiki.answer_summary.write" }),
        buildAction({ action_id: "skip", action_type: "wiki.answer_summary.skip", status: "skipped", decision: "notify" }),
      ],
      [],
      [],
      [],
    );

    const groups = buildMemoryTrustGroups(entries);
    const counts = Object.fromEntries(groups.map((group) => [group.key, group.entries.length]));

    expect(counts).toMatchObject({
      chat_diary: 1,
      structured_diary: 1,
      wiki_summary: 1,
      skipped: 1,
    });
  });
});
