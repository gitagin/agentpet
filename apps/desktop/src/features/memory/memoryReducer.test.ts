import { describe, expect, it } from "vitest";

import type { MemoryProposal, MemorySearchResult } from "../../types";
import { defaultMemoryTargetPath } from "./memoryConstants";
import { createInitialMemoryState, memoryReducer } from "./memoryReducer";

function searchResult(overrides: Partial<MemorySearchResult> = {}): MemorySearchResult {
  return {
    note_id: "note-1",
    chunk_id: "chunk-1",
    relative_path: "Memories/Test.md",
    title: "测试记忆",
    snippet: "用户喜欢苹果。",
    score: 0.9,
    source_scope: "personal_memory",
    ...overrides,
  };
}

function proposal(overrides: Partial<MemoryProposal> = {}): MemoryProposal {
  return {
    proposal_id: "proposal-1",
    type: "fact",
    content: "用户喜欢苹果。",
    target_path: defaultMemoryTargetPath,
    status: "pending",
    ...overrides,
  };
}

describe("memoryReducer", () => {
  it("creates the initial search and proposal state", () => {
    const state = createInitialMemoryState();

    expect(state.searchQuery).toBe("");
    expect(state.searchResults).toEqual([]);
    expect(state.searchStatus).toBe("idle");
    expect(state.proposalDraft).toEqual({ type: "fact", content: "", target_path: defaultMemoryTargetPath });
    expect(state.proposals).toEqual([]);
    expect(state.proposalActionIds.size).toBe(0);
  });

  it("updates search query, starts search, and stores successful results", () => {
    const searching = memoryReducer(createInitialMemoryState(), { type: "setSearchQuery", searchQuery: "苹果" });
    const loading = memoryReducer(searching, { type: "startSearch", query: "苹果" });
    const successful = memoryReducer(loading, { type: "searchSuccess", results: [searchResult()] });

    expect(searching.searchQuery).toBe("苹果");
    expect(loading.searchStatus).toBe("loading");
    expect(loading.lastSearchQuery).toBe("苹果");
    expect(successful.searchStatus).toBe("success");
    expect(successful.searchResults[0].snippet).toBe("用户喜欢苹果。");
  });

  it("marks empty and failed searches", () => {
    const empty = memoryReducer(createInitialMemoryState(), { type: "searchSuccess", results: [] });
    const failed = memoryReducer(
      { ...empty, searchResults: [searchResult()], searchStatus: "success" },
      { type: "searchError" },
    );

    expect(empty.searchStatus).toBe("empty");
    expect(failed.searchStatus).toBe("error");
    expect(failed.searchResults).toEqual([]);
  });

  it("updates proposal draft and replaces optimistic proposals on success", () => {
    const drafted = memoryReducer(createInitialMemoryState(), {
      type: "updateProposalDraft",
      patch: { type: "preference", content: "我喜欢苹果" },
    });
    const optimistic = memoryReducer(drafted, {
      type: "createProposalOptimistic",
      proposal: proposal({ proposal_id: "optimistic-1", content: "临时提案" }),
    });
    const saved = memoryReducer(optimistic, {
      type: "createProposalSuccess",
      optimisticId: "optimistic-1",
      proposal: proposal({ proposal_id: "proposal-2", content: "正式提案" }),
    });

    expect(drafted.proposalDraft).toMatchObject({ type: "preference", content: "我喜欢苹果" });
    expect(optimistic.proposals[0].proposal_id).toBe("optimistic-1");
    expect(saved.proposals[0]).toMatchObject({ proposal_id: "proposal-2", content: "正式提案" });
    expect(saved.proposalDraft).toEqual({ type: "fact", content: "", target_path: defaultMemoryTargetPath });
  });

  it("marks optimistic proposals as failed when creation errors", () => {
    const optimistic = memoryReducer(createInitialMemoryState(), {
      type: "createProposalOptimistic",
      proposal: proposal({ proposal_id: "optimistic-1" }),
    });
    const failed = memoryReducer(optimistic, {
      type: "createProposalError",
      optimisticId: "optimistic-1",
      error: "写入失败",
    });

    expect(failed.proposals[0].status).toBe("failed");
    expect(failed.proposals[0].content).toBe("写入失败");
  });

  it("sets, upserts, updates proposals, and tracks proposal actions", () => {
    const first = proposal({ proposal_id: "proposal-1" });
    const second = proposal({ proposal_id: "proposal-2", content: "新的提案" });
    const loaded = memoryReducer(createInitialMemoryState(), { type: "setProposals", proposals: [first] });
    const upserted = memoryReducer(loaded, { type: "upsertProposal", proposal: second });
    const confirmed = memoryReducer(upserted, {
      type: "updateProposalStatus",
      proposalId: "proposal-1",
      status: "confirmed",
      writtenPath: "Memories/Test.md",
    });
    const actionStarted = memoryReducer(confirmed, { type: "startProposalAction", proposalId: "proposal-1" });
    const actionFinished = memoryReducer(actionStarted, { type: "finishProposalAction", proposalId: "proposal-1" });

    expect(upserted.proposals.map((item) => item.proposal_id)).toEqual(["proposal-2", "proposal-1"]);
    expect(confirmed.proposals.find((item) => item.proposal_id === "proposal-1")).toMatchObject({
      status: "confirmed",
      written_path: "Memories/Test.md",
    });
    expect(actionStarted.proposalActionIds.has("proposal-1")).toBe(true);
    expect(actionFinished.proposalActionIds.has("proposal-1")).toBe(false);
  });

  it("sets loading state and resets to the initial state", () => {
    const loading = memoryReducer(createInitialMemoryState(), { type: "setLoadingProposals", loading: true });
    const reset = memoryReducer({ ...loading, searchQuery: "苹果" }, { type: "reset" });

    expect(loading.loadingProposals).toBe(true);
    expect(reset).toEqual(createInitialMemoryState());
  });
});
