import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentActivityLogEntry } from "../services/agentActivity";
import type { DesktopApi } from "../services/desktopApi";
import MemoryWindowView from "./MemoryWindowView";
import type {
  MemoryGraphClaimDetail,
  MemoryGraphEdgeDetail,
  MemoryGraphNodeDetail,
  MemoryGraphResponse,
  MemoryProposalDraft,
} from "../types";

const now = "2026-08-08T08:00:00Z";

function makeGraph(overrides: Partial<MemoryGraphResponse> = {}): MemoryGraphResponse {
  return {
    generated_at: now,
    generation: { backend: "sqlite", source_revision: 1, status: "ready", generation_id: "generation-1" },
    degraded_mode: false,
    nodes: [
      {
        node_id: "entity:me",
        type: "user",
        label: "我",
        subtitle: "个人",
        status: "active",
        risk: "low",
        size: 1.4,
        confidence: 1,
        confidence_label: "明确",
        source_label: "聊天声明",
        evidence_count: 1,
        updated_at: now,
        allowed_actions: ["correct", "forget"],
      },
      {
        node_id: "entity:project",
        type: "project",
        label: "LLM Wiki",
        subtitle: "项目",
        status: "active",
        risk: "low",
        size: 1.2,
        confidence: 0.92,
        confidence_label: "有据",
        source_label: "项目笔记",
        evidence_count: 1,
        updated_at: now,
        allowed_actions: ["correct", "forget"],
      },
    ],
    edges: [
      {
        edge_id: "relation:works",
        source_node_id: "entity:me",
        target_node_id: "entity:project",
        relation_type: "works_on",
        risk: "low",
        confidence: 0.9,
        evidence_count: 1,
        status: "active",
        updated_at: now,
        allowed_actions: ["correct", "forget"],
      },
    ],
    clusters: [],
    summary: { total_nodes: 2, pending_count: 0, cleanup_count: 0, hidden_count: 0 },
    redaction_note: "敏感内容和本机路径不会显示。",
    schema_version: "llmwiki-graph-v1",
    vault: { label: "active_vault", vault_id: "vault-1" },
    ...overrides,
  };
}

function lifecycle(active = true) {
  return { active_for_recall: active, confidence: 0.9, status: active ? "active" : "candidate", updated_at: now };
}

function nodeDetail(nodeId: string, label: string, actions: MemoryGraphNodeDetail["allowed_actions"] = ["correct", "forget"]): MemoryGraphNodeDetail {
  return {
    node_id: nodeId,
    kind: "entity",
    label,
    subtitle: "项目实体",
    type: "project",
    status: "active",
    risk: "low",
    confidence: 0.9,
    evidence_count: 1,
    allowed_actions: actions,
    evidence: [{ evidence_id: "evidence-1", label: "项目笔记", excerpt: "这里记录了 LLM Wiki 的决策。", relative_path: "notes/wiki.md", confidence: 0.9, created_at: now, source_type: "markdown" }],
    lifecycle: lifecycle(),
    edge_ids: ["relation:works"],
    claim_ids: [],
    wiki_pages: [{ binding_id: "wiki-1", title: "LLM Wiki 决策", relative_path: "wiki/decision.md", revision: 1, status: "active", updated_at: now }],
    redaction_note: "原始路径按需显示。",
    updated_at: now,
  };
}

function edgeDetail(): MemoryGraphEdgeDetail {
  return {
    edge_id: "relation:works",
    source_node_id: "entity:me",
    target_node_id: "entity:project",
    relation_type: "works_on",
    confidence: 0.9,
    evidence_count: 1,
    status: "active",
    allowed_actions: ["correct", "forget"],
    risk: "low",
    evidence: [{ evidence_id: "evidence-1", label: "项目笔记", excerpt: "这里记录了 LLM Wiki 的决策。", relative_path: "notes/wiki.md", confidence: 0.9, created_at: now, source_type: "markdown" }],
    lifecycle: lifecycle(),
    updated_at: now,
    redaction_note: "原始路径按需显示。",
  };
}

function claimDetail(): MemoryGraphClaimDetail {
  return {
    claim_id: "claim-1",
    fact_type: "works_on",
    subject_label: "我",
    predicate: "works_on",
    literal_value: "LLM Wiki",
    subject_node_id: "entity:me",
    status: "active",
    confidence: 0.9,
    evidence_count: 1,
    risk: "low",
    evidence: [{ evidence_id: "evidence-1", label: "项目笔记", excerpt: "这里记录了 LLM Wiki 的决策。", relative_path: "notes/wiki.md", confidence: 0.9, created_at: now, source_type: "markdown" }],
    lifecycle: lifecycle(),
    source_type: "markdown",
    updated_at: now,
    redaction_note: "原始路径按需显示。",
  };
}

function makeApi(graph = makeGraph()): DesktopApi {
  const api = {
    getMemoryGraph: vi.fn().mockResolvedValue(graph),
    getMemoryGraphNode: vi.fn((nodeId: string) => Promise.resolve(nodeDetail(nodeId, nodeId === "entity:me" ? "我" : "LLM Wiki"))),
    getMemoryGraphEdge: vi.fn().mockResolvedValue(edgeDetail()),
    getMemoryGraphClaim: vi.fn().mockResolvedValue(claimDetail()),
    applyMemoryGraphNodeAction: vi.fn().mockResolvedValue({ action: "forget", message: "已记录", operation_id: "op-1", replayed: false, status: "forgotten", target_id: "entity:project" }),
    applyMemoryGraphEdgeAction: vi.fn().mockResolvedValue({ action: "forget", message: "已记录", operation_id: "op-1", replayed: false, status: "forgotten", target_id: "relation:works" }),
    applyMemoryGraphClaimAction: vi.fn().mockResolvedValue({ action: "forget", message: "已记录", operation_id: "op-1", replayed: false, status: "forgotten", target_id: "claim-1" }),
    rebuildMemoryGraph: vi.fn().mockResolvedValue({ backend: "sqlite", degraded: false, edge_count: 1, node_count: 2, operation_id: "op-rebuild", replayed: false, source_revision: 1, status: "rebuilt" }),
  };
  return api as unknown as DesktopApi;
}

function renderMemory(api: DesktopApi, overrides: Partial<Parameters<typeof MemoryWindowView>[0]> = {}) {
  const entries: AgentActivityLogEntry[] = [];
  const draft = {} as MemoryProposalDraft;
  return render(
    <MemoryWindowView
      api={api}
      loading={false}
      error=""
      entries={entries}
      memorySearchQuery=""
      memorySearchStatus="idle"
      memorySearchResults={[]}
      memoryLastSearchQuery=""
      onMemorySearchQueryChange={vi.fn()}
      onRunMemorySearch={vi.fn()}
      memoryProposalDraft={draft}
      memoryProposals={[]}
      memoryProposalActionIds={new Set()}
      loadingMemoryProposals={false}
      onMemoryProposalDraftChange={vi.fn()}
      onCreateMemoryProposal={vi.fn()}
      onActOnMemoryProposal={vi.fn()}
      onLoadMemoryProposals={vi.fn()}
      onRefresh={vi.fn()}
      renderEntry={vi.fn(() => null)}
      {...overrides}
    />,
  );
}

describe("MemoryWindowView", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 1280 });
  });

  it("uses the graphite surface without the illustrated shell backdrop", async () => {
    const api = makeApi();
    renderMemory(api);

    await screen.findByText("LLM Wiki");
    const shell = document.querySelector(".feature-shell");
    expect(shell).toHaveAttribute("data-surface", "graphite");
    expect(shell?.querySelector(".feature-reference-stage")).not.toBeInTheDocument();
    expect(shell?.querySelector(".feature-shell-backdrop")).not.toBeInTheDocument();
  });

  it("opens the graph workspace on desktop and shows an honest empty evidence rail", async () => {
    const api = makeApi();
    renderMemory(api);
    expect(await screen.findByRole("tab", { name: /图谱/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("LLM Wiki")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "证据链轨道" })).toHaveTextContent("选择一个节点或关系");
  });

  it("defaults to the timeline on a narrow viewport", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 390 });
    const api = makeApi();
    renderMemory(api);
    expect(await screen.findByRole("tab", { name: /时间线/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("最近变化")).toBeInTheDocument();
  });

  it("renders a next-step CTA when the graph is empty", async () => {
    const api = makeApi(makeGraph({ nodes: [], edges: [], summary: { total_nodes: 0, pending_count: 0, cleanup_count: 0, hidden_count: 0 } }));
    renderMemory(api);
    fireEvent.click(await screen.findByRole("tab", { name: /时间线/ }));
    expect(await screen.findByText("还没有生命周期记录")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加记忆" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导入来源" })).toBeInTheDocument();
  });

  it("opens the evidence rail from a node and exposes the source chain", async () => {
    const api = makeApi();
    renderMemory(api);
    fireEvent.click(await screen.findByRole("button", { name: "记忆节点：LLM Wiki" }));
    expect(await screen.findByText("证据链轨道")).toBeInTheDocument();
    expect(await screen.findByText("这里记录了 LLM Wiki 的决策。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /LLM Wiki 决策/ })).toBeInTheDocument();
    expect(api.getMemoryGraphNode).toHaveBeenCalledWith("entity:project");
  });

  it("keeps source actions tied to implemented product paths", async () => {
    const api = makeApi();
    renderMemory(api);
    fireEvent.click(await screen.findByRole("tab", { name: /来源/ }));
    expect(await screen.findByRole("button", { name: "导入来源" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重建派生图" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /导出/ })).not.toBeInTheDocument();
  });

  it("uses a fresh 64-hex idempotency key for a forget action", async () => {
    const api = makeApi();
    renderMemory(api);
    fireEvent.click(await screen.findByRole("button", { name: "记忆节点：LLM Wiki" }));
    fireEvent.click(await screen.findByRole("button", { name: "忘记" }));
    fireEvent.click(await screen.findByRole("button", { name: "再次点击忘记" }));
    await waitFor(() => expect(api.applyMemoryGraphNodeAction).toHaveBeenCalled());
    const call = (api.applyMemoryGraphNodeAction as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("entity:project");
    expect(call[1]).toEqual({ action: "forget", confirmed: true });
    expect(call[2]).toMatch(/^[0-9a-f]{64}$/);
  });

  it("keeps an entity action on the entity even when it has claims", async () => {
    const api = makeApi();
    (api.getMemoryGraphNode as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...nodeDetail("entity:project", "LLM Wiki"),
      claim_ids: ["claim-1"],
    });
    renderMemory(api);

    fireEvent.click(await screen.findByRole("button", { name: "记忆节点：LLM Wiki" }));
    await waitFor(() => expect(api.getMemoryGraphNode).toHaveBeenCalledWith("entity:project"));
    expect(api.getMemoryGraphClaim).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "忘记" }));
    fireEvent.click(await screen.findByRole("button", { name: "再次点击忘记" }));

    await waitFor(() => expect(api.applyMemoryGraphNodeAction).toHaveBeenCalled());
    expect(api.applyMemoryGraphClaimAction).not.toHaveBeenCalled();
  });

  it("does not show a supersedes receipt when correction fails", async () => {
    const api = makeApi();
    (api.applyMemoryGraphNodeAction as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("offline"));
    renderMemory(api);
    fireEvent.click(await screen.findByRole("button", { name: "记忆节点：LLM Wiki" }));
    fireEvent.click(await screen.findByRole("button", { name: "纠正" }));
    const nameInput = screen.getByLabelText("规范名称");
    fireEvent.change(nameInput, { target: { value: "LLM Wiki 修订" } });
    fireEvent.click(screen.getByRole("button", { name: "保存纠正" }));

    await waitFor(() => expect(api.applyMemoryGraphNodeAction).toHaveBeenCalled());
    expect(screen.queryByText(/supersedes 已创建/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存纠正" })).toBeInTheDocument();
  });

  it("surfaces a partial detail failure instead of silently showing an incomplete chain", async () => {
    const api = makeApi();
    (api.getMemoryGraphNode as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...nodeDetail("entity:project", "LLM Wiki"),
      kind: "claim",
      node_id: "claim:missing",
      claim_ids: ["claim:missing"],
    });
    (api.getMemoryGraphClaim as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("claim unavailable"));
    renderMemory(api);
    fireEvent.click(await screen.findByRole("button", { name: "记忆节点：LLM Wiki" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("实体已加载，但事实详情暂不可用");
  });

  it("redacts infrastructure details in the top-level failure state", async () => {
    const api = makeApi();
    renderMemory(api, { error: "fetch http://127.0.0.1:8765 failed: token=secret" });
    await screen.findByText("LLM Wiki");
    expect(screen.getByRole("alert")).toHaveTextContent("本机助手暂时不可用");
    expect(screen.getByRole("alert")).not.toHaveTextContent("8765");
  });
});
