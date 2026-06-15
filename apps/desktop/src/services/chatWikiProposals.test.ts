import { describe, expect, it, vi } from "vitest";
import {
  formatChatWikiProposalState,
  formatWikiProposalEventDetail,
  getWikiProposalTargetOptions,
  isSupportedChatWikiProposalType,
  isWikiProposalStreamEvent,
  mergeChatWikiProposal,
  normalizeChatWikiProposal,
} from "./chatWikiProposals";

vi.stubGlobal("crypto", {
  randomUUID: () => "generated-id",
});

describe("chatWikiProposals", () => {
  it("detects wiki proposal stream events", () => {
    expect(isWikiProposalStreamEvent("wiki.proposal.reviewed")).toBe(true);
    expect(isWikiProposalStreamEvent("chat.delta")).toBe(false);
  });

  it("formats stream events without leaking sensitive payload values", () => {
    const detail = formatWikiProposalEventDetail(
      "wiki.proposal.debug",
      { token: "secret-token", nested: { api_key: "secret-key" } },
      "",
    );

    expect(detail).toContain("[redacted]");
    expect(detail).not.toContain("secret-token");
    expect(detail).not.toContain("secret-key");
    expect(detail).toContain("需确认后才会写入本机知识页");
  });

  it("normalizes proposal payloads and target options", () => {
    const proposal = normalizeChatWikiProposal({
      review_id: "review-1",
      proposal_type: "ingest",
      title: " 项目摘要 ",
      target_paths: ["Wiki/A.md", "Wiki/A.md", ""],
      recommended_targets: ["Wiki/B.md"],
      findings: [{ severity: "warning", code: "stale", message: "过期", target_path: "Wiki/A.md" }],
    });

    expect(proposal?.id).toBe("review-1");
    expect(proposal?.selected_targets).toEqual(["Wiki/B.md"]);
    expect(proposal?.findings).toEqual([
      { severity: "warning", code: "stale", message: "过期", target_path: "Wiki/A.md" },
    ]);
    expect(proposal ? getWikiProposalTargetOptions(proposal) : []).toEqual(["Wiki/B.md", "Wiki/A.md"]);
  });

  it("preserves local state when merging proposal updates", () => {
    const existing = normalizeChatWikiProposal({ review_id: "review-1", title: "旧", recommended_targets: ["Wiki/A.md"] });
    const incoming = normalizeChatWikiProposal({ review_id: "review-1", title: "新", recommended_targets: ["Wiki/B.md"] });

    expect(existing).not.toBeNull();
    expect(incoming).not.toBeNull();
    if (!existing || !incoming) {
      return;
    }

    const merged = mergeChatWikiProposal(
      { ...existing, state: "confirmed", error: "本地错误", apply_result: { status: "applied" } as never },
      incoming,
    );

    expect(merged.title).toBe("新");
    expect(merged.state).toBe("confirmed");
    expect(merged.selected_targets).toEqual(["Wiki/A.md"]);
    expect(merged.error).toBe("本地错误");
  });

  it("formats supported proposal types and states", () => {
    expect(isSupportedChatWikiProposalType("lint")).toBe(true);
    expect(isSupportedChatWikiProposalType("unknown")).toBe(false);
    expect(formatChatWikiProposalState("applying")).toBe("正在应用");
  });
});
