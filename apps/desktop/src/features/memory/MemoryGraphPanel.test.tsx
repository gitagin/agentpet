import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MemoryGraphProjectionResponse } from "../../types";
import MemoryGraphPanel from "./MemoryGraphPanel";

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
      id: "mg_boundary",
      type: "boundary",
      label: "不要主动暴露隐私",
      subtitle: "边界",
      status: "active",
      risk_tier: "low",
      size: 1,
      confidence_label: "明确",
      source_label: "来自用户设定",
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
      id: "mg_episode",
      type: "episode",
      label: "讨论了新的首页排版",
      subtitle: "情景",
      status: "active",
      risk_tier: "low",
      size: 0.96,
      confidence_label: "近期",
      source_label: "来自聊天后的整理",
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
    { id: "mge_2", from: "mg_user", to: "mg_project", type: "supports", strength: 0.7 },
    { id: "mge_3", from: "mg_pref", to: "mg_pending", type: "conflicts_with", strength: 0.4 },
  ],
  clusters: [
    { id: "cluster_preferences", label: "偏好", node_ids: ["mg_pref"] },
    { id: "cluster_projects", label: "项目", node_ids: ["mg_project"] },
    { id: "cluster_pending", label: "待确认", node_ids: ["mg_pending"] },
    { id: "cluster_cleanup", label: "需要整理", node_ids: ["mg_cleanup"] },
    { id: "cluster_hidden", label: "已隐藏", node_ids: ["mg_hidden"] },
  ],
  summary: { total_nodes: 8, pending_count: 2, cleanup_count: 1, hidden_count: 1 },
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
  it("renders an interactive React Flow memory graph with summary, nodes, and edges", () => {
    const { container } = render(<MemoryGraphPanel projection={projection} loading={false} error="" onRefresh={vi.fn()} />);

    const panel = screen.getByLabelText("我的记忆图谱");
    expect(within(panel).getByText("我的记忆图谱")).toBeInTheDocument();
    expect(within(panel).getByText("偏好、边界、项目、情景和资料会在这里连成一张可理解的记忆地图。")).toBeInTheDocument();

    const summary = within(panel).getByLabelText("记忆图谱摘要");
    expect(within(summary).getByText("记忆节点")).toBeInTheDocument();
    expect(within(summary).getByText("8")).toBeInTheDocument();
    expect(within(summary).getByText("待确认")).toBeInTheDocument();
    expect(within(summary).getByText("需整理")).toBeInTheDocument();
    expect(within(summary).getByText("已隐藏")).toBeInTheDocument();

    expect(within(panel).getByLabelText("记忆知识图谱画布")).toBeInTheDocument();
    expect(container.querySelector(".memory-flow-canvas")).toBeInTheDocument();
    expect(container.querySelector(".react-flow")).toBeInTheDocument();
    expect(container.querySelector(".memory-node-center")).toBeInTheDocument();
    expect(container.querySelector(".memory-node-center-text")).toBeInTheDocument();
    expect(container.querySelector(".memory-node-dot svg")).not.toBeInTheDocument();
    expect(container.querySelector(".memory-node-pending")).toBeInTheDocument();
    expect(container.querySelector(".memory-node-archived")).toBeInTheDocument();
    expect(container.querySelector(".memory-edge-supports")).toBeInTheDocument();
    expect(container.querySelector(".memory-edge-conflicts-with")).toBeInTheDocument();
    expect(container.querySelector(".react-flow__minimap")).not.toBeInTheDocument();

    const legend = within(panel).getByLabelText("图谱颜色图例");
    expect(within(legend).getByText("偏好")).toBeInTheDocument();
    expect(within(legend).getByText("边界")).toBeInTheDocument();
    expect(within(legend).getByText("项目")).toBeInTheDocument();
    expect(within(legend).queryByText("情景")).not.toBeInTheDocument();
    expect(within(panel).getByText("拖拽画布平移")).toBeInTheDocument();
    expect(within(panel).getByText("滚轮缩放")).toBeInTheDocument();
    expect(within(panel).getByText("点击节点查看详情")).toBeInTheDocument();
    expect(within(panel).getByText("回答保持简洁")).toBeInTheDocument();
    expect(within(panel).getByText("Project Atlas 正在推进")).toBeInTheDocument();
    expect(container.querySelector(".memory-star-canvas")).not.toBeInTheDocument();
    expect(container.querySelector(".memory-star-card")).not.toBeInTheDocument();
  });

  it("opens a safe detail panel when a memory node is clicked", () => {
    render(<MemoryGraphPanel projection={projection} loading={false} error="" onRefresh={vi.fn()} />);

    fireEvent.click(screen.getByLabelText("记忆节点：回答保持简洁"));

    const detail = screen.getByLabelText("记忆节点详情");
    expect(within(detail).getByText("回答保持简洁")).toBeInTheDocument();
    expect(within(detail).getAllByText("偏好").length).toBeGreaterThan(0);
    expect(within(detail).getByText("使用中")).toBeInTheDocument();
    expect(within(detail).getAllByText("较确定").length).toBeGreaterThan(0);
    expect(within(detail).getByText("来自用户明确要求")).toBeInTheDocument();
    expect(within(detail).getByText("普通")).toBeInTheDocument();
    expect(within(detail).getByText("记忆摘要")).toBeInTheDocument();
    expect(within(detail).getByText("关联记忆")).toBeInTheDocument();
    expect(within(detail).getByText("也许偏好长篇解释")).toBeInTheDocument();
    fireEvent.click(within(detail).getByRole("button", { name: "关闭记忆详情" }));
    expect(screen.getByText("点一个节点看看")).toBeInTheDocument();
    expect(within(detail).queryByRole("button", { name: /确认|忘记|保存|编辑|改正/ })).not.toBeInTheDocument();
  });

  it("shows a gentle empty state with memory prompts", () => {
    render(<MemoryGraphPanel projection={emptyProjection} loading={false} error="" onRefresh={vi.fn()} />);

    const panel = screen.getByLabelText("我的记忆图谱");
    expect(within(panel).getByText("记忆图谱还是空的")).toBeInTheDocument();
    expect(within(panel).getByText("告诉我一些关于你的事，我会把它们连成一张记忆地图。")).toBeInTheDocument();
    expect(within(panel).getByText("告诉我一个偏好")).toBeInTheDocument();
    expect(within(panel).getByText("告诉我正在做的项目")).toBeInTheDocument();
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

  it("does not spend graph space on the redaction note", () => {
    render(<MemoryGraphPanel projection={projection} loading={false} error="" onRefresh={vi.fn()} />);

    expect(screen.queryByText("敏感内容、原始证据、授权信息和本机路径不会显示。")).not.toBeInTheDocument();
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
      edges: [{ id: "raw_edge", from: "mg_user", to: "mg_pref", type: "related_to", strength: 0.5 }],
      clusters: [{ id: "cluster_raw", label: "raw id path", node_ids: ["mg_pref"] }],
      summary: { total_nodes: 2, pending_count: 0, cleanup_count: 0, hidden_count: 0 },
      redaction_note: "source_excerpt message_id conversation_id lifecycle_status token C:\\Users\\Ada\\secret.md",
    };

    const { container } = render(<MemoryGraphPanel projection={unsafeProjection} loading={false} error="" onRefresh={vi.fn()} />);

    expect(screen.getByText("一条记忆")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("记忆节点：一条记忆"));
    expect(screen.getByText("已安全处理")).toBeInTheDocument();
    expect(screen.getByText("来自本机整理")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(forbiddenTextPattern);
  });

  it("keeps the MVP free of batch, edit, or write controls", () => {
    render(<MemoryGraphPanel projection={projection} loading={false} error="" onRefresh={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /批量|编辑|改正|写入|保存|确认|忘记/ })).not.toBeInTheDocument();
  });
});
