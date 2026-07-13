import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentActivityLogEntry } from "../../services/agentActivity";
import { paginatePetBubbleReply } from "../../services/petBubblePagination";
import type { AgentAction, ChatMessage, ContinuityStateResponse, TaskItem } from "../../types";
import {
  buildMemoryDayGroups,
  buildOrbitItems,
  calculateExpandedMemoryEntryLimit,
  ControlDashboard,
  selectVisibleMemoryDaysForReview,
  type MemoryDayGroup,
} from "./ControlDashboard";

vi.mock("../../views/BottomNav", () => ({
  BottomNav: () => <nav aria-label="mock bottom nav" />,
}));

vi.mock("../chat/ChatMessageList", () => ({
  ChatMessageList: () => <section aria-label="mock chat list" />,
}));

vi.mock("../tasks/TaskPanel", () => ({
  TaskPanel: () => <section aria-label="mock task panel" />,
}));

vi.mock("../continuity", () => ({
  VisibleContinuityPanel: () => <section aria-label="mock continuity panel" />,
}));

vi.mock("../connection/HealthStatus", () => ({
  ConnectionStatusStrip: () => <section aria-label="mock connection status" />,
}));

vi.mock("./AdvancedManagementTools", () => ({
  AdvancedManagementTools: () => <section aria-label="mock advanced tools" />,
}));

const continuityState: ContinuityStateResponse = {
  current_mood: "安静",
  energy_level: "在线",
  unresolved_threads: "",
  relationship_summary: "测试关系",
  items: [],
};

function agentAction(id: string, createdAt: string, title = `记忆 ${id}`): AgentAction {
  return {
    action_id: id,
    action_type: "memory.long_term.write",
    risk_tier: "low",
    decision: "auto",
    status: "completed",
    title,
    summary: `${title} 的摘要`,
    target_paths: ["Memories/Daily.md"],
    reversible: true,
    source: {},
    diff_summary: "",
    metadata: {},
    created_at: createdAt,
    updated_at: createdAt,
    completed_at: createdAt,
  };
}

function activity(id: string, createdAt: string, title?: string): AgentActivityLogEntry {
  return {
    kind: "agent_action",
    id: `agent-action-${id}`,
    sortAt: createdAt,
    sortKey: Date.parse(createdAt),
    action: agentAction(id, createdAt, title),
  };
}

function task(id: string, dueAt: string, title = `任务 ${id}`): TaskItem {
  return {
    task_id: id,
    title,
    description: `${title} 描述`,
    status: "scheduled",
    due_at: dueAt,
    remind_at: dueAt,
    timezone: "Asia/Shanghai",
  };
}

function message(id: string, role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id,
    role,
    content,
    status: "completed",
  };
}

function richActivityEntries(): AgentActivityLogEntry[] {
  return [
    activity("today-1", "2026-07-02T11:30:00+08:00", "今天第一条"),
    activity("today-2", "2026-07-02T10:30:00+08:00", "今天第二条"),
    activity("today-3", "2026-07-02T09:30:00+08:00", "今天第三条"),
    activity("today-4", "2026-07-02T08:30:00+08:00", "今天第四条"),
    activity("today-5", "2026-07-02T07:30:00+08:00", "今天第五条"),
    activity("today-6", "2026-07-02T06:30:00+08:00", "今天第六条不应显示"),
    activity("yesterday-1", "2026-07-01T11:30:00+08:00", "昨天第一条"),
    activity("yesterday-2", "2026-07-01T10:30:00+08:00", "昨天第二条"),
    activity("yesterday-3", "2026-07-01T09:30:00+08:00", "昨天第三条"),
    activity("older-1", "2026-06-30T11:30:00+08:00", "前天第一条"),
    activity("older-2", "2026-06-30T10:30:00+08:00", "前天第二条"),
    activity("older-3", "2026-06-30T09:30:00+08:00", "前天第三条"),
    activity("older-4", "2026-06-29T11:30:00+08:00", "6月29日第一条"),
  ];
}

function createDashboardProps(
  overrides: Partial<React.ComponentProps<typeof ControlDashboard>> = {},
): React.ComponentProps<typeof ControlDashboard> {
  return {
    sidecarStatus: null,
    health: null,
    notice: null,
    ttsActive: false,
    api: {} as React.ComponentProps<typeof ControlDashboard>["api"],
    firstUseOnboardingPanel: null,
    controlInput: "",
    hasConnection: true,
    streaming: false,
    onControlInputChange: vi.fn(),
    onSubmitControlChat: vi.fn((event) => event.preventDefault()),
    onStopStreaming: vi.fn(),
    pendingManualActivityCount: 0,
    agentActionsStatus: "success",
    hasAgentActivity: true,
    recentAgentActivityCount: 0,
    loadingProposals: false,
    loadingContinuity: false,
    agentActionsError: "",
    activityItems: [],
    onRefreshActivity: vi.fn(),
    messages: [],
    agentActivityEntries: [],
    tasks: [],
    chatMessageListProps: { messages: [] },
    workflowItems: [],
    taskPanelProps: {
      tasks: [],
      lastReminderNotification: { status: "idle", detail: "等待到期提醒触发。" },
      onLocateTask: vi.fn(),
    },
    continuityState,
    pendingContinuityCount: 0,
    onLoadContinuity: vi.fn(),
    onLocateWorkflowTarget: vi.fn(),
    modelStatusLabel: "已配置",
    knowledgeStatusLabel: "已就绪",
    advancedTools: {
      connectionPanel: null,
      wikiWorkflowPanel: null,
      settingsPanel: null,
    },
    ...overrides,
  };
}

function renderDashboard(
  overrides: Partial<React.ComponentProps<typeof ControlDashboard>> = {},
) {
  return render(<ControlDashboard {...createDashboardProps(overrides)} />);
}

describe("ControlDashboard memory review", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-02T12:00:00+08:00"));
    sessionStorage.clear();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("does not show reference memories or orbit points when memory is empty", () => {
    const { container } = renderDashboard({
      agentActivityEntries: [],
      messages: [],
      tasks: [],
    });

    const memoryPanel = screen.getByLabelText("记忆回顾");
    expect(memoryPanel).toHaveTextContent("开始聊天或创建任务后，实时记忆会出现在这里。");
    expect(memoryPanel).not.toHaveTextContent("产品原型讨论");
    expect(memoryPanel).not.toHaveTextContent("午餐时间");
    expect(container.querySelectorAll(".orbit-point")).toHaveLength(0);
  });

  it("keeps every memory day with full per-day counts and entries", () => {
    const groups = buildMemoryDayGroups(richActivityEntries(), [], []);

    expect(groups.map((group) => `${group.title} ${group.subtitle}`)).toEqual([
      "7月2日 今天",
      "7月1日 昨天",
      "6月30日 周二",
      "6月29日 周一",
    ]);
    expect(groups.map((group) => group.totalCount)).toEqual([6, 3, 3, 1]);
    expect(groups.map((group) => group.entries.map((entry) => entry.title))).toEqual([
      ["今天第一条", "今天第二条", "今天第三条", "今天第四条", "今天第五条", "今天第六条不应显示"],
      ["昨天第一条", "昨天第二条", "昨天第三条"],
      ["前天第一条", "前天第二条", "前天第三条"],
      ["6月29日第一条"],
    ]);
  });

  it("keeps home goals user-created and toggles completion from the goal item", () => {
    const { container } = renderDashboard();
    const goalCard = container.querySelector(".control-goals-card") as HTMLElement;
    const modeButton = goalCard.querySelector(".control-card-title .control-mini-button") as HTMLButtonElement;
    const goalList = goalCard.querySelector(".control-goal-list") as HTMLElement;

    expect(modeButton).toHaveAttribute("aria-pressed", "false");
    expect(goalCard.querySelector(".control-goal-form input")).not.toBeInTheDocument();
    expect(goalList.querySelectorAll(".control-goal-row")).toHaveLength(0);
    expect(goalCard.querySelector(".control-goal-empty")).not.toBeInTheDocument();
    expect(goalCard.querySelector(".control-goal-pager")).not.toBeInTheDocument();
    expect(container).not.toHaveTextContent("完成产品原型评审");
    expect(container).not.toHaveTextContent("晚间散步 20 分钟");

    fireEvent.click(modeButton);

    const goalInput = goalCard.querySelector(".control-goal-form input") as HTMLInputElement;
    const goalForm = goalCard.querySelector(".control-goal-form") as HTMLFormElement;

    expect(modeButton).toHaveAttribute("aria-pressed", "true");
    expect(goalInput).toBeInTheDocument();
    expect(goalCard.querySelectorAll(".control-goal-row")).toHaveLength(0);

    fireEvent.change(goalInput, { target: { value: "Ship test goal" } });
    fireEvent.submit(goalForm);

    const goalRow = goalCard.querySelector(".control-goal-row") as HTMLElement;
    const goalToggle = within(goalRow).getByRole("button", { name: "Ship test goal" });

    expect(modeButton).toHaveAttribute("aria-pressed", "false");
    expect(goalCard.querySelector(".control-goal-form input")).not.toBeInTheDocument();
    expect(goalRow).toHaveClass("active");
    expect(goalRow).not.toHaveClass("done");
    expect(goalToggle).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(goalToggle);

    expect(goalRow).toHaveClass("done");
    expect(goalRow).not.toHaveClass("active");
    expect(goalToggle).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(goalToggle);

    expect(goalRow).toHaveClass("active");
    expect(goalRow).not.toHaveClass("done");
    expect(goalToggle).toHaveAttribute("aria-pressed", "false");

    const deleteButton = goalRow.querySelector(".control-goal-delete") as HTMLButtonElement;
    fireEvent.click(deleteButton);

    expect(goalList.querySelectorAll(".control-goal-row")).toHaveLength(0);
    expect(goalCard.querySelector(".control-goal-empty")).not.toBeInTheDocument();
  });

  it("paginates home goals only after the list exceeds the visible pane", () => {
    const { container } = renderDashboard();
    const goalCard = container.querySelector(".control-goals-card") as HTMLElement;
    const modeButton = goalCard.querySelector(".control-card-title .control-mini-button") as HTMLButtonElement;

    const createGoal = (title: string) => {
      fireEvent.click(modeButton);
      const goalInput = goalCard.querySelector(".control-goal-form input") as HTMLInputElement;
      const goalForm = goalCard.querySelector(".control-goal-form") as HTMLFormElement;
      fireEvent.change(goalInput, { target: { value: title } });
      fireEvent.submit(goalForm);
    };

    createGoal("Goal one");
    createGoal("Goal two");
    createGoal("Goal three");

    expect(goalCard.querySelector(".control-goal-pager")).not.toBeInTheDocument();
    expect(goalCard.querySelectorAll(".control-goal-row")).toHaveLength(3);

    createGoal("Goal four");

    expect(goalCard.querySelector(".control-goal-pager")).toHaveTextContent("2/2");
    expect(goalCard.querySelector(".control-goal-list-pane")).toHaveClass("has-goal-pages");
    expect(goalCard).toHaveTextContent("Goal four");
    expect(goalCard).not.toHaveTextContent("Goal one");

    fireEvent.click(screen.getByRole("button", { name: "上一页目标" }));

    expect(goalCard.querySelector(".control-goal-pager")).toHaveTextContent("1/2");
    expect(goalCard).toHaveTextContent("Goal one");
    expect(goalCard).not.toHaveTextContent("Goal four");
  });

  it("starts with the latest memory day expanded, expands only one day, and can close all days", () => {
    renderDashboard({ agentActivityEntries: richActivityEntries() });

    const memoryPanel = screen.getByLabelText("记忆回顾");
    const dayButtons = within(memoryPanel).getAllByRole("button", { name: /记忆记录/ });
    expect(dayButtons).toHaveLength(4);
    expect(dayButtons.map((button) => button.getAttribute("aria-expanded"))).toEqual([
      "true",
      "false",
      "false",
      "false",
    ]);
    expect(within(dayButtons[0]).getByText("6")).toBeInTheDocument();
    expect(within(dayButtons[1]).getByText("3")).toBeInTheDocument();
    expect(within(dayButtons[2]).getByText("3")).toBeInTheDocument();
    expect(within(dayButtons[3]).getByText("1")).toBeInTheDocument();

    expect(within(memoryPanel).getByText("今天第一条")).toBeInTheDocument();
    expect(within(memoryPanel).getByText("今天第二条")).toBeInTheDocument();
    expect(within(memoryPanel).getByText("今天第三条")).toBeInTheDocument();
    expect(within(memoryPanel).queryByText("今天第四条")).not.toBeInTheDocument();
    expect(within(memoryPanel).queryByText("昨天第一条")).not.toBeInTheDocument();
    expect(within(memoryPanel).queryByText("6月29日第一条")).not.toBeInTheDocument();

    fireEvent.click(dayButtons[1]);
    expect(dayButtons[0]).toHaveAttribute("aria-expanded", "false");
    expect(dayButtons[1]).toHaveAttribute("aria-expanded", "true");
    expect(within(memoryPanel).queryByText("今天第一条")).not.toBeInTheDocument();
    expect(within(memoryPanel).getByText("昨天第一条")).toBeInTheDocument();
    expect(within(memoryPanel).getByText("昨天第二条")).toBeInTheDocument();
    expect(within(memoryPanel).getByText("昨天第三条")).toBeInTheDocument();

    fireEvent.click(dayButtons[1]);
    expect(dayButtons.map((button) => button.getAttribute("aria-expanded"))).toEqual([
      "false",
      "false",
      "false",
      "false",
    ]);
    expect(within(memoryPanel).queryByText("昨天第一条")).not.toBeInTheDocument();
  });

  it("calculates a relaxed expanded-card limit from available panel space", () => {
    expect(calculateExpandedMemoryEntryLimit(780, 4)).toBe(5);
    expect(calculateExpandedMemoryEntryLimit(520, 4)).toBe(3);
    expect(calculateExpandedMemoryEntryLimit(390, 4)).toBe(2);
    expect(calculateExpandedMemoryEntryLimit(480, 10)).toBe(3);
    expect(calculateExpandedMemoryEntryLimit(170, 4)).toBe(1);
    expect(calculateExpandedMemoryEntryLimit(0, 4)).toBe(3);
  });

  it("keeps every date visible when a day expands", () => {
    const groups = Array.from({ length: 7 }, (_, index) => ({
      key: `day-${index}`,
      title: `day ${index}`,
      subtitle: "周一",
      totalCount: 1,
      entries: [],
    })) satisfies MemoryDayGroup[];

    expect(selectVisibleMemoryDaysForReview(groups, null).map((group) => group.key)).toEqual([
      "day-0",
      "day-1",
      "day-2",
      "day-3",
      "day-4",
      "day-5",
      "day-6",
    ]);
    expect(selectVisibleMemoryDaysForReview(groups, "day-2").map((group) => group.key)).toEqual([
      "day-0",
      "day-1",
      "day-2",
      "day-3",
      "day-4",
      "day-5",
      "day-6",
    ]);
    expect(selectVisibleMemoryDaysForReview(groups, "day-5").map((group) => group.key)).toEqual([
      "day-0",
      "day-1",
      "day-2",
      "day-3",
      "day-4",
      "day-5",
      "day-6",
    ]);
  });

  it("keeps older day counts stable when a new chat message enters the timeline", () => {
    const groups = buildMemoryDayGroups(
      richActivityEntries(),
      [message("assistant-new", "assistant", "刚刚聊完的一句话")],
      [],
    );

    const yesterday = groups.find((group) => group.subtitle === "昨天");

    expect(groups).toHaveLength(4);
    expect(yesterday?.totalCount).toBe(3);
    expect(yesterday?.entries.map((entry) => entry.title)).toEqual(["昨天第一条", "昨天第二条", "昨天第三条"]);
  });

  it("opens the memory drawer and locates the clicked memory card", () => {
    const onLocateWorkflowTarget = vi.fn();
    renderDashboard({
      agentActivityEntries: richActivityEntries(),
      activityItems: [<article key="target" id="agent-action-today-1">详情卡</article>],
      onLocateWorkflowTarget,
    });

    fireEvent.click(screen.getByRole("button", { name: "查看今天第一条" }));

    expect(screen.getByText("详情卡")).toBeInTheDocument();
    vi.advanceTimersByTime(80);
    expect(onLocateWorkflowTarget).toHaveBeenCalledWith("agent-action-today-1");
  });

  it("renders animated voice waveform and floating memory orbit points", () => {
    const { container, rerender } = renderDashboard({
      agentActivityEntries: richActivityEntries(),
      ttsActive: false,
      streaming: false,
    });

    const wave = container.querySelector(".control-voice-wave");
    expect(wave).toBeInTheDocument();
    expect(wave?.querySelectorAll("i")).toHaveLength(5);
    expect(wave).not.toHaveClass("is-active");
    expect(container.querySelectorAll(".orbit-point")).toHaveLength(4);
    expect(Array.from(container.querySelectorAll(".orbit-point")).map((node) => node.className)).toEqual([
      "orbit-point point-one",
      "orbit-point point-two",
      "orbit-point point-three",
      "orbit-point point-four",
    ]);

    rerender(
      <ControlDashboard
        sidecarStatus={null}
        health={null}
        notice={null}
        ttsActive
        api={{} as React.ComponentProps<typeof ControlDashboard>["api"]}
        firstUseOnboardingPanel={null}
        controlInput=""
        hasConnection
        streaming={false}
        onControlInputChange={vi.fn()}
        onSubmitControlChat={vi.fn((event) => event.preventDefault())}
        onStopStreaming={vi.fn()}
        pendingManualActivityCount={0}
        agentActionsStatus="success"
        hasAgentActivity
        recentAgentActivityCount={0}
        loadingProposals={false}
        loadingContinuity={false}
        agentActionsError=""
        activityItems={[]}
        onRefreshActivity={vi.fn()}
        messages={[]}
        agentActivityEntries={richActivityEntries()}
        tasks={[]}
        chatMessageListProps={{ messages: [] }}
        workflowItems={[]}
        taskPanelProps={{
          tasks: [],
          lastReminderNotification: { status: "idle", detail: "等待到期提醒触发。" },
          onLocateTask: vi.fn(),
        }}
        continuityState={continuityState}
        pendingContinuityCount={0}
        onLoadContinuity={vi.fn()}
        onLocateWorkflowTarget={vi.fn()}
        modelStatusLabel="已配置"
        knowledgeStatusLabel="已就绪"
        advancedTools={{
          connectionPanel: null,
          wikiWorkflowPanel: null,
          settingsPanel: null,
        }}
      />,
    );

    expect(container.querySelector(".control-voice-wave")).toHaveClass("is-active");
  });

  it("paginates long home speech replies without truncating them with an ellipsis", () => {
    const longReply = [
      "First I sorted the note into three practical steps, and the first step is to write down the exact trigger.",
      "Then I would keep the second step separate so it stays readable in the home bubble.",
      "Finally I would close with the next action and keep the rest available on the next page.",
    ].join(" ");
    const pages = paginatePetBubbleReply(longReply);
    expect(pages.length).toBeGreaterThan(1);

    const { container } = renderDashboard({
      messages: [message("assistant-long", "assistant", longReply)],
    });
    const bubble = container.querySelector(".control-speech-bubble") as HTMLElement;

    expect(bubble).toHaveTextContent(pages[0]);
    expect(bubble).toHaveTextContent(`1/${pages.length}`);
    expect(bubble).not.toHaveTextContent("…");

    fireEvent.click(screen.getByRole("button", { name: "下一页回复" }));

    expect(bubble).toHaveTextContent(pages[1]);
    expect(bubble).toHaveTextContent(`2/${pages.length}`);
  });

  it("resets the home speech page when a new assistant reply arrives", () => {
    const firstReply = [
      "First reply starts with a long opening sentence that needs more than one page.",
      "First reply continues with a second sentence so the next-page button can move forward.",
    ].join(" ");
    const secondReply = [
      "Second reply begins from a different first page and should reset the visible page index.",
      "Second reply continues after the reset so the pager still has another page available.",
    ].join(" ");
    const firstPages = paginatePetBubbleReply(firstReply);
    const secondPages = paginatePetBubbleReply(secondReply);
    expect(firstPages.length).toBeGreaterThan(1);
    expect(secondPages.length).toBeGreaterThan(1);

    const { container, rerender } = render(
      <ControlDashboard
        {...createDashboardProps({
          messages: [message("assistant-first", "assistant", firstReply)],
        })}
      />,
    );
    const bubble = container.querySelector(".control-speech-bubble") as HTMLElement;

    fireEvent.click(screen.getByRole("button", { name: "下一页回复" }));
    expect(bubble).toHaveTextContent(firstPages[1]);

    rerender(
      <ControlDashboard
        {...createDashboardProps({
          messages: [message("assistant-second", "assistant", secondReply)],
        })}
      />,
    );

    expect(bubble).toHaveTextContent(secondPages[0]);
    expect(bubble).toHaveTextContent(`1/${secondPages.length}`);
  });

  it("builds orbit points from the visible memory entries before clipping extras", () => {
    const groups: MemoryDayGroup[] = buildMemoryDayGroups(
      richActivityEntries(),
      [message("assistant-1", "assistant", "刚刚整理的回复")],
      [task("task-1", "2026-07-01T08:00:00+08:00", "昨天任务")],
    );

    const orbitItems = buildOrbitItems(groups);
    expect(orbitItems).toHaveLength(4);
    expect(orbitItems.map((item) => item.className)).toEqual([
      "point-one",
      "point-two",
      "point-three",
      "point-four",
    ]);
    expect(orbitItems.map((item) => item.label)).toEqual(["宠物回复", "今天第一条", "今天第二条", "今天第三条"]);
  });
});
