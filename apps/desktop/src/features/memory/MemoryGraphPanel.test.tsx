import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import MemoryGraphPanel from "./MemoryGraphPanel";
import type { MemoryGraphProjectionResponse } from "../../types";

const projection: MemoryGraphProjectionResponse = {
  generated_at: "2026-06-02T00:00:00Z",
  nodes: [
    {
      id: "mg_user",
      type: "user",
      label: "我",
      subtitle: "记忆中心",
      status: "active",
      risk_tier: "low",
      size: 1.45,
      confidence_label: "由你掌控",
      source_label: "本机记忆图谱",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
    {
      id: "mg_pref",
      type: "preference",
      label: "回答保持简洁",
      subtitle: "偏好",
      status: "active",
      risk_tier: "low",
      size: 1.12,
      confidence_label: "较确定",
      source_label: "来自用户明确要求",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
    {
      id: "mg_project",
      type: "project",
      label: "Project Atlas 正在推进",
      subtitle: "项目",
      status: "active",
      risk_tier: "low",
      size: 1,
      confidence_label: "基本确定",
      source_label: "来自聊天日记",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
    {
      id: "mg_pending",
      type: "pending",
      label: "也许偏好长篇解释",
      subtitle: "待确认",
      status: "pending",
      risk_tier: "low",
      size: 0.9,
      confidence_label: "需要确认",
      source_label: "来自聊天后的整理",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
    {
      id: "mg_cleanup",
      type: "cleanup",
      label: "临时状态已过期",
      subtitle: "需要整理",
      status: "pending",
      risk_tier: "low",
      size: 0.8,
      confidence_label: "建议检查",
      source_label: "来自本机整理建议",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
    {
      id: "mg_hidden",
      type: "archived",
      label: "有一条已隐藏的记忆",
      subtitle: "已隐藏",
      status: "hidden",
      risk_tier: "hidden",
      size: 0.78,
      confidence_label: "细节已隐藏",
      source_label: "细节已隐藏",
      updated_at: "2026-06-02T00:00:00Z",
      available_actions: [],
    },
  ],
  edges: [
    { id: "mge_1", from: "mg_user", to: "mg_pref", type: "related_to", strength: 0.7 },
    { id: "mge_2", from: "mg_user", to: "mg_project", type: "related_to", strength: 0.7 },
  ],
  clusters: [
    { id: "cluster_preferences", label: "偏好", node_ids: ["mg_pref"] },
    { id: "cluster_projects", label: "项目", node_ids: ["mg_project"] },
    { id: "cluster_pending", label: "待确认", node_ids: ["mg_pending"] },
    { id: "cluster_cleanup", label: "需要整理", node_ids: ["mg_cleanup"] },
    { id: "cluster_hidden", label: "已隐藏", node_ids: ["mg_hidden"] },
  ],
  summary: { total_nodes: 6, pending_count: 2, cleanup_count: 1, hidden_count: 1 },
  redaction_note: "敏感内容、原始证据、授权信息和本机路径不会显示。",
};

const emptyProjection: MemoryGraphProjectionResponse = {
  ...projection,
  nodes: [projection.nodes[0]],
  edges: [],
  clusters: [],
  summary: { total_nodes: 1, pending_count: 0, cleanup_count: 0, hidden_count: 0 },
};

const forbiddenTextPattern =
  /candidate|fact|evidence|source_text|source_excerpt|agent_run_id|message_id|conversation_id|lifecycle_status|token|Authorization|FTS|vector|raw id|[A-Za-z]:[\\/]|\/Users\//i;

describe("MemoryGraphPanel", () => {
  it("renders a user-facing memory graph with summary, clusters, and nodes", () => {
    render(<MemoryGraphPanel projection={projection} loading={false} error="" onRefresh={vi.fn()} />);

    const panel = screen.getByLabelText("我的记忆图谱");
    expect(within(panel).getByText("我的记忆图谱")).toBeInTheDocument();
    expect(within(panel).getByText("把偏好、项目、事件和资料连成一张你能看懂的记忆地图。")).toBeInTheDocument();
    expect(within(panel).getByText("记忆节点数")).toBeInTheDocument();
    expect(within(panel).getByText("6")).toBeInTheDocument();
    expect(within(panel).getByText("待确认数量")).toBeInTheDocument();
    expect(within(panel).getAllByText("2").length).toBeGreaterThan(0);
    expect(within(panel).getByText("需要整理数量")).toBeInTheDocument();
    expect(within(panel).getByText("已隐藏敏感数量")).toBeInTheDocument();
    expect(within(panel).getAllByText("偏好").length).toBeGreaterThan(0);
    expect(within(panel).getByText("回答保持简洁")).toBeInTheDocument();
    expect(within(panel).getByText("Project Atlas 正在推进")).toBeInTheDocument();
    expect(within(panel).getByText("2 条关联")).toBeInTheDocument();
  });

  it("opens a safe detail panel when a node is clicked", () => {
    render(<MemoryGraphPanel projection={projection} loading={false} error="" onRefresh={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "查看记忆节点：回答保持简洁" }));

    const detail = screen.getByLabelText("记忆节点详情");
    expect(within(detail).getByText("回答保持简洁")).toBeInTheDocument();
    expect(within(detail).getAllByText("偏好").length).toBeGreaterThan(0);
    expect(within(detail).getByText("使用中")).toBeInTheDocument();
    expect(within(detail).getByText("较确定")).toBeInTheDocument();
    expect(within(detail).getByText("来自用户明确要求")).toBeInTheDocument();
    expect(within(detail).getByText("普通")).toBeInTheDocument();
  });

  it("shows a gentle empty state with three memory prompts", () => {
    render(<MemoryGraphPanel projection={emptyProjection} loading={false} error="" onRefresh={vi.fn()} />);

    const panel = screen.getByLabelText("我的记忆图谱");
    expect(within(panel).getByText("还没有形成可展示的记忆星群。")).toBeInTheDocument();
    expect(within(panel).getByText("记忆会留在本机，你可以随时确认、改正或忘记。")).toBeInTheDocument();
    expect(within(panel).getByText("告诉我一个偏好")).toBeInTheDocument();
    expect(within(panel).getByText("告诉我正在做的项目")).toBeInTheDocument();
    expect(within(panel).getByText("告诉我不希望被记住的边界")).toBeInTheDocument();
  });

  it("shows loading and safe error states without backend details", () => {
    const { rerender } = render(<MemoryGraphPanel projection={null} loading error="" onRefresh={vi.fn()} />);

    expect(screen.getByText("正在整理你的记忆图谱……")).toBeInTheDocument();

    rerender(
      <MemoryGraphPanel
        projection={null}
        loading={false}
        error="这次没能打开记忆图谱，请稍后重试。"
        onRefresh={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("这次没能打开记忆图谱，请稍后重试。");
    expect(screen.getByRole("alert")).not.toHaveTextContent(forbiddenTextPattern);
  });

  it("displays the redaction note as a soft hint", () => {
    render(<MemoryGraphPanel projection={projection} loading={false} error="" onRefresh={vi.fn()} />);

    expect(screen.getByText("敏感内容、原始证据、授权信息和本机路径不会显示。")).toBeInTheDocument();
  });

  it("filters unsafe backend text and does not expose internal terms or paths", () => {
    const unsafeProjection: MemoryGraphProjectionResponse = {
      ...projection,
      nodes: [
        projection.nodes[0],
        {
          ...projection.nodes[1],
          label: "candidate fact C:\\Users\\Ada\\secret.md",
          subtitle: "source_text",
          confidence_label: "evidence agent_run_id",
          source_label: "Authorization token FTS vector",
          updated_at: "C:\\Users\\Ada\\secret.md",
        },
      ],
      clusters: [{ id: "cluster_raw", label: "raw id path", node_ids: ["mg_pref"] }],
      summary: { total_nodes: 2, pending_count: 0, cleanup_count: 0, hidden_count: 0 },
      redaction_note: "source_excerpt message_id conversation_id lifecycle_status token C:\\Users\\Ada\\secret.md",
    };

    const { container } = render(<MemoryGraphPanel projection={unsafeProjection} loading={false} error="" onRefresh={vi.fn()} />);

    expect(screen.getByText("一条记忆")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看记忆节点：一条记忆" }));
    expect(screen.getByText("已安全处理")).toBeInTheDocument();
    expect(screen.getByText("来自本机整理")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(forbiddenTextPattern);
  });

  it("does not expose batch, edit, or write actions in the readonly MVP", () => {
    render(<MemoryGraphPanel projection={projection} loading={false} error="" onRefresh={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /批量|编辑|改正|忘记|确认/ })).not.toBeInTheDocument();
  });
});
