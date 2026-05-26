import type { MemoryProposal, MemoryProposalDraft, MemorySearchResult } from "../../types";
import { defaultMemoryTargetPath } from "./memoryConstants";

export type MemoryAsyncStatus = "idle" | "loading" | "success" | "empty" | "error";

export type MemoryState = {
  searchQuery: string;
  searchResults: MemorySearchResult[];
  searchStatus: MemoryAsyncStatus;
  lastSearchQuery: string;
  proposalDraft: MemoryProposalDraft;
  proposals: MemoryProposal[];
  loadingProposals: boolean;
  proposalActionIds: Set<string>;
};

export type MemoryAction =
  | { type: "setSearchQuery"; searchQuery: string }
  | { type: "startSearch"; query: string }
  | { type: "searchSuccess"; results: MemorySearchResult[] }
  | { type: "searchError" }
  | { type: "updateProposalDraft"; patch: Partial<MemoryProposalDraft> }
  | { type: "createProposalOptimistic"; proposal: MemoryProposal }
  | { type: "createProposalSuccess"; optimisticId: string; proposal: MemoryProposal }
  | { type: "createProposalError"; optimisticId: string; error: string }
  | { type: "setProposals"; proposals: MemoryProposal[] }
  | { type: "upsertProposal"; proposal: MemoryProposal }
  | { type: "updateProposalStatus"; proposalId: string; status: MemoryProposal["status"]; writtenPath?: string | null }
  | { type: "setLoadingProposals"; loading: boolean }
  | { type: "startProposalAction"; proposalId: string }
  | { type: "finishProposalAction"; proposalId: string }
  | { type: "reset" };

export function createInitialMemoryState(): MemoryState {
  return {
    searchQuery: "",
    searchResults: [],
    searchStatus: "idle",
    lastSearchQuery: "",
    proposalDraft: {
      type: "fact",
      content: "",
      target_path: defaultMemoryTargetPath,
    },
    proposals: [],
    loadingProposals: false,
    proposalActionIds: new Set(),
  };
}

export function memoryReducer(state: MemoryState, action: MemoryAction): MemoryState {
  switch (action.type) {
    case "setSearchQuery":
      return { ...state, searchQuery: action.searchQuery };
    case "startSearch":
      return { ...state, searchStatus: "loading", lastSearchQuery: action.query };
    case "searchSuccess":
      return {
        ...state,
        searchResults: action.results,
        searchStatus: action.results.length > 0 ? "success" : "empty",
      };
    case "searchError":
      return { ...state, searchResults: [], searchStatus: "error" };
    case "updateProposalDraft":
      return { ...state, proposalDraft: { ...state.proposalDraft, ...action.patch } };
    case "createProposalOptimistic":
      return { ...state, proposals: [action.proposal, ...state.proposals] };
    case "createProposalSuccess":
      return {
        ...state,
        proposals: state.proposals.map((proposal) =>
          proposal.proposal_id === action.optimisticId ? action.proposal : proposal,
        ),
        proposalDraft: { type: "fact", content: "", target_path: defaultMemoryTargetPath },
      };
    case "createProposalError":
      return {
        ...state,
        proposals: state.proposals.map((proposal) =>
          proposal.proposal_id === action.optimisticId
            ? { ...proposal, status: "failed", content: action.error }
            : proposal,
        ),
      };
    case "setProposals":
      return { ...state, proposals: action.proposals };
    case "upsertProposal": {
      const rest = state.proposals.filter((proposal) => proposal.proposal_id !== action.proposal.proposal_id);
      return { ...state, proposals: [action.proposal, ...rest] };
    }
    case "updateProposalStatus":
      return {
        ...state,
        proposals: state.proposals.map((proposal) =>
          proposal.proposal_id === action.proposalId
            ? { ...proposal, status: action.status, written_path: action.writtenPath }
            : proposal,
        ),
      };
    case "setLoadingProposals":
      return { ...state, loadingProposals: action.loading };
    case "startProposalAction": {
      const next = new Set(state.proposalActionIds);
      next.add(action.proposalId);
      return { ...state, proposalActionIds: next };
    }
    case "finishProposalAction": {
      const next = new Set(state.proposalActionIds);
      next.delete(action.proposalId);
      return { ...state, proposalActionIds: next };
    }
    case "reset":
      return createInitialMemoryState();
    default:
      return state;
  }
}
