import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../services/apiClient";
import type { DesktopApi } from "../../services/desktopApi";
import { VisibleContinuityPanel } from "./VisibleContinuityPanel";
import type { RetrospectiveResponse } from "../../types";
import type { VisibleContinuitySnapshotResponse } from "./visibleContinuityTypes";

function emptySnapshot(): VisibleContinuitySnapshotResponse {
  return {
    today_card: {
      title: "Today is ready when you are",
      summary: "No recent local activity yet.",
      carry_over_items: [],
      suggested_next_steps: ["Start a chat or capture one note."],
      continuation_prompts: ["Help me decide what is worth continuing today."],
      source_count: 0,
      updated_at: "2026-06-02T12:00:00Z",
    },
    recent_receipts: [],
    project_cards: [],
    playback_preview: {
      period: "weekly",
      title: "Weekly playback is warming up",
      summary: "Not enough local history yet.",
      themes: [],
      completed: [],
      stuck_points: [],
      next_focus: ["Capture a few chats, tasks, or notes first."],
      source_count: 0,
    },
  };
}

function fullSnapshot(): VisibleContinuitySnapshotResponse {
  return {
    today_card: {
      title: "Continue from the latest local context",
      summary: "Pulled together 2 recent messages, 1 open task, and 2 organization receipts.",
      carry_over_items: ["Task: Ship visible continuity", "Agent Pet: Active"],
      suggested_next_steps: ["Continue the snapshot API.", "Review the latest memory receipt."],
      continuation_prompts: ["Help me continue this task: Ship visible continuity"],
      source_count: 7,
      updated_at: "2026-06-02T13:00:00Z",
    },
    recent_receipts: [
      {
        action_id: "action-1",
        action_type: "wiki.answer_summary.write",
        title: "Saved weekly summary",
        summary: "Saved a reusable summary.",
        decision: "auto",
        risk_tier: "low",
        status: "completed",
        reversible: true,
        target_path: "Wiki/Companion/Summaries/week.md",
        created_at: "2026-06-02T12:30:00Z",
      },
      {
        action_id: "action-2",
        action_type: "memory.consolidation.safety_event",
        title: "Skipped sensitive memory",
        summary: "Blocked [REDACTED].",
        decision: "notify",
        risk_tier: "high",
        status: "completed",
        reversible: false,
        target_path: null,
        created_at: "2026-06-02T12:20:00Z",
      },
    ],
    project_cards: [
      {
        project_id: "agent-pet",
        title: "Agent Pet",
        current_state: "Active",
        recent_progress: "Open task: Ship visible continuity",
        next_step: "Continue the snapshot API.",
        blockers: [],
        last_touched_at: "2026-06-02T13:00:00Z",
        sources: ["tasks:task-1", "diary_memory_objects:diary-1"],
      },
    ],
    playback_preview: {
      period: "weekly",
      title: "Weekly local playback preview",
      summary: "Found local activity from the last 7 days.",
      themes: ["visible continuity"],
      completed: ["Baseline audit"],
      stuck_points: ["Review generated report"],
      next_focus: ["visible continuity"],
      source_count: 4,
    },
  };
}

function retrospectiveResponse(): RetrospectiveResponse {
  const baseWindow = {
    label: "window",
    start_at: "2026-05-26T00:00:00Z",
    end_at: "2026-06-02T00:00:00Z",
    summary: {
      diary_objects: 1,
      long_term_memories: 1,
      tasks: 2,
      wiki_updates: 0,
      topics: 1,
      repeated_preferences: 0,
    },
    topics: [
      {
        name: "visible continuity",
        count: 2,
        sources: [],
      },
    ],
    diary_summaries: [],
    long_term_memories: [],
    tasks: {
      total: 2,
      completed: 1,
      pending: 1,
      cancelled: 0,
      overdue: 0,
      sources: [],
    },
    wiki_updates: [],
    repeated_preferences: [],
    has_data: true,
  };
  return {
    generated_at: "2026-06-02T12:00:00Z",
    windows: [
      {
        ...baseWindow,
        days: 7,
        label: "7-day",
      },
      {
        ...baseWindow,
        days: 30,
        label: "30-day",
        end_at: "2026-06-02T00:00:00Z",
      },
    ],
  };
}

function sidecarStartingError(): ApiError {
  return new ApiError("本地后端正在启动，请稍候再试", 503, {
    error: {
      code: "sidecar_starting",
      message: "本地后端正在启动，请稍候再试",
    },
  });
}

describe("VisibleContinuityPanel", () => {
  it("renders useful empty snapshot data", () => {
    render(<VisibleContinuityPanel snapshot={emptySnapshot()} />);

    expect(screen.getByText("Today is ready when you are")).toBeInTheDocument();
    expect(screen.getByText("暂时还没有自动整理记录。")).toBeInTheDocument();
    expect(screen.getByText(/当任务、日记或记忆反复提到同一条线索后/)).toBeInTheDocument();
    expect(screen.getByText("Weekly playback is warming up")).toBeInTheDocument();
    expect(screen.getByText("Start a chat or capture one note.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Help me decide what is worth continuing today/ })).toBeDisabled();
  });

  it("renders full snapshot data with receipt status, safe target path, and project next step", () => {
    render(<VisibleContinuityPanel snapshot={fullSnapshot()} />);

    expect(screen.getByText("Continue from the latest local context")).toBeInTheDocument();
    expect(screen.getByText("已保存周摘要")).toBeInTheDocument();
    expect(screen.getByText("可在这里撤回。")).toBeInTheDocument();
    expect(screen.getByText("Wiki/Companion/Summaries/week.md")).toBeInTheDocument();
    expect(screen.getByText("已跳过敏感记忆")).toBeInTheDocument();
    expect(screen.getByText("仅支持手动确认路径。")).toBeInTheDocument();
    expect(screen.getByText("没有可展示的安全本地文件目标。")).toBeInTheDocument();
    expect(screen.queryByText("Skipped sensitive memory")).not.toBeInTheDocument();
    expect(screen.queryByText("Secrets/token.md")).not.toBeInTheDocument();
    expect(screen.getByText("Agent Pet")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getAllByText("Continue the snapshot API.").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Help me continue this task/ })).toBeDisabled();
    expect(screen.getByText("Weekly local playback preview")).toBeInTheDocument();
    expect(screen.getAllByText("visible continuity").length).toBeGreaterThan(0);
  });

  it("starts an optional continuation prompt when a handler is provided", () => {
    const onContinuePrompt = vi.fn();

    render(<VisibleContinuityPanel snapshot={fullSnapshot()} onContinuePrompt={onContinuePrompt} />);

    fireEvent.click(screen.getByRole("button", { name: /Help me continue this task/ }));

    expect(onContinuePrompt).toHaveBeenCalledWith("Help me continue this task: Ship visible continuity");
  });

  it("loads a snapshot through the desktop API when one is not provided", async () => {
    const api = {
      getVisibleContinuitySnapshot: vi.fn().mockResolvedValue(fullSnapshot()),
      revertAgentAction: vi.fn(),
      getRetrospectives: vi.fn(),
      writeRetrospectivePeriodReport: vi.fn(),
    } as unknown as DesktopApi;

    render(<VisibleContinuityPanel api={api} />);

    expect(screen.getByText("正在加载最新本地连续性快照。")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("已保存周摘要")).toBeInTheDocument());
    expect(api.getVisibleContinuitySnapshot).toHaveBeenCalledOnce();
  });

  it("retries snapshot loading while the sidecar is still starting", async () => {
    const api = {
      getVisibleContinuitySnapshot: vi
        .fn()
        .mockRejectedValueOnce(sidecarStartingError())
        .mockResolvedValueOnce(fullSnapshot()),
      revertAgentAction: vi.fn(),
      getRetrospectives: vi.fn(),
      writeRetrospectivePeriodReport: vi.fn(),
    } as unknown as DesktopApi;

    render(<VisibleContinuityPanel api={api} />);

    await waitFor(() => expect(api.getVisibleContinuitySnapshot).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/sidecar_starting/)).not.toBeInTheDocument();
    await waitFor(() => expect(api.getVisibleContinuitySnapshot).toHaveBeenCalledTimes(2), { timeout: 2000 });
    await waitFor(() => expect(screen.getByText("Continue from the latest local context")).toBeInTheDocument());
    expect(screen.queryByText(/连续性快照加载失败/)).not.toBeInTheDocument();
  });

  it("reverts a reversible receipt through the desktop API and refreshes the snapshot", async () => {
    const reverted = fullSnapshot();
    reverted.recent_receipts = [
      {
        ...reverted.recent_receipts[0],
        status: "reverted",
        reverted_by: "revert-1",
      },
    ];
    const api = {
      getVisibleContinuitySnapshot: vi
        .fn()
        .mockResolvedValueOnce(fullSnapshot())
        .mockResolvedValueOnce(reverted),
      revertAgentAction: vi.fn().mockResolvedValue({ action: {}, reverted: {} }),
      getRetrospectives: vi.fn(),
      writeRetrospectivePeriodReport: vi.fn(),
    } as unknown as DesktopApi;

    render(<VisibleContinuityPanel api={api} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "撤回" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "撤回" }));

    await waitFor(() => expect(api.revertAgentAction).toHaveBeenCalledWith("action-1"));
    await waitFor(() => expect(screen.getByText("已撤回记录：已保存周摘要。")).toBeInTheDocument());
    expect(api.getVisibleContinuitySnapshot).toHaveBeenCalledTimes(2);
    expect(screen.getByText("已撤回。")).toBeInTheDocument();
  });

  it("keeps high-risk pending receipts on the confirmation path instead of offering undo", () => {
    const snapshot = fullSnapshot();
    snapshot.recent_receipts = [
      {
        ...snapshot.recent_receipts[1],
        decision: "ask",
        status: "pending",
      },
    ];

    render(<VisibleContinuityPanel snapshot={snapshot} />);

    expect(screen.queryByRole("button", { name: "撤回" })).not.toBeInTheDocument();
    expect(screen.getByText("仅支持手动确认路径。")).toBeInTheDocument();
    expect(screen.getByText("这条高风险整理项仍需要在记忆活动队列中确认。")).toBeInTheDocument();
  });

  it("opens weekly and monthly playback details from local retrospective windows", async () => {
    const api = {
      getVisibleContinuitySnapshot: vi.fn().mockResolvedValue(fullSnapshot()),
      revertAgentAction: vi.fn(),
      getRetrospectives: vi.fn().mockResolvedValue(retrospectiveResponse()),
      writeRetrospectivePeriodReport: vi.fn(),
    } as unknown as DesktopApi;

    render(<VisibleContinuityPanel api={api} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "打开回放" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "打开回放" }));

    await waitFor(() => expect(api.getRetrospectives).toHaveBeenCalledOnce());
    expect(screen.getByText("已从本地历史加载周回放和月回放。")).toBeInTheDocument();
    expect(screen.getByText("周回放")).toBeInTheDocument();
    expect(screen.getByText("月回放")).toBeInTheDocument();
    expect(screen.getAllByText("visible continuity (2)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1 个已完成任务").length).toBeGreaterThan(0);
  });

  it("writes a reversible weekly playback report through the existing retrospective API and refreshes receipts", async () => {
    const api = {
      getVisibleContinuitySnapshot: vi
        .fn()
        .mockResolvedValueOnce(fullSnapshot())
        .mockResolvedValueOnce(fullSnapshot()),
      revertAgentAction: vi.fn(),
      getRetrospectives: vi.fn(),
      writeRetrospectivePeriodReport: vi.fn().mockResolvedValue({
        page: {
          title: "Weekly report",
          relative_path: "Wiki/Companion/Reports/2026-06-02-weekly.md",
          operation: "replace",
          status: "created",
        },
        action: {
          action_id: "action-weekly",
          action_type: "wiki.weekly_report.write",
          risk_tier: "low",
          decision: "auto",
          status: "completed",
          title: "Saved weekly report",
          summary: "Saved weekly playback.",
          target_paths: ["Wiki/Companion/Reports/2026-06-02-weekly.md"],
          reversible: true,
          source: {},
          diff_summary: "",
          metadata: {},
          created_at: "2026-06-02T12:00:00Z",
          updated_at: "2026-06-02T12:00:00Z",
        },
        markdown: "# Weekly report",
      }),
    } as unknown as DesktopApi;

    render(<VisibleContinuityPanel api={api} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "保存周报" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "保存周报" }));

    await waitFor(() => expect(api.writeRetrospectivePeriodReport).toHaveBeenCalledWith("weekly"));
    await waitFor(() => expect(screen.getByText("已保存周回放报告：Wiki/Companion/Reports/2026-06-02-weekly.md。")).toBeInTheDocument());
    expect(api.getVisibleContinuitySnapshot).toHaveBeenCalledTimes(2);
  });
});
