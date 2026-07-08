import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { forwardRef } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import StageView from "./StageView";
import type { PetBubbleState } from "../features/chat/chatTypes";

function readCssWithImports(path: string, visited = new Set<string>()): string {
  const filePath = resolve(path);
  if (visited.has(filePath)) {
    return "";
  }
  visited.add(filePath);

  const css = readFileSync(filePath, "utf8");
  const directory = dirname(filePath);
  return css.replace(/^@import\s+"([^"]+)";$/gm, (_match, importPath: string) =>
    readCssWithImports(resolve(directory, importPath), visited),
  );
}

const styles = readCssWithImports(resolve(__dirname, "../styles.css"));

vi.mock("../features/halfbody/HalfbodyPetPortrait", () => ({
  HalfbodyPetPortrait: forwardRef<HTMLElement, { active?: boolean }>(function MockHalfbodyPetPortrait(
    { active = true },
    ref,
  ) {
    return (
      <section
        ref={ref}
        aria-label="mock halfbody portrait"
        className="halfbody-pet-portrait"
        data-active={active ? "true" : "false"}
      />
    );
  }),
}));

vi.mock("./BottomNav", () => ({
  BottomNav: () => <nav aria-label="mock bottom nav" />,
}));

vi.mock("../features/continuity", () => ({
  VisibleContinuityPanel: ({ onContinuePrompt }: { onContinuePrompt?: (prompt: string) => void }) => (
    <section aria-label="mock stage visible continuity">
      Stage outcomes
      <button type="button" onClick={() => onContinuePrompt?.("Continue mocked project")}>
        Continue mocked prompt
      </button>
    </section>
  ),
}));

function renderStageView(
  bubble: PetBubbleState,
  options: {
    active?: boolean;
    ttsSpeaking?: boolean;
    api?: object;
  } = {},
) {
  const onSendChat = vi.fn();
  const rendered = render(
    <StageView
      connected
      streaming={false}
      bubble={bubble}
      onSendChat={onSendChat}
      onPreviousPage={vi.fn()}
      onAdvancePage={vi.fn()}
      onPausePaging={vi.fn()}
      onResumePaging={vi.fn()}
      ttsSpeaking={options.ttsSpeaking}
      active={options.active}
      api={options.api as never}
    />,
  );
  return { ...rendered, onSendChat };
}

describe("StageView", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("shows outcome-first primary entries and keeps advanced tools collapsed", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    });

    const commandCenter = screen.getByLabelText("陪伴入口");
    expect(commandCenter).toBeInTheDocument();
    expect(commandCenter).toHaveTextContent("我会长期记住重要的事");
    expect(commandCenter).toHaveTextContent("记忆留在本机，可查看、可撤回");
    expect(within(commandCenter).getByText("长期陪伴")).toBeInTheDocument();
    expect(within(commandCenter).getByText("本地记忆")).toBeInTheDocument();
    expect(within(commandCenter).getByText("记忆可控")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /陪我聊聊/ })).toHaveAttribute("data-stage-route", "chat");
    expect(screen.getByRole("button", { name: /看看记忆/ })).toHaveAttribute("data-stage-route", "memory");
    expect(screen.getByRole("button", { name: /设置边界/ })).toHaveAttribute("data-stage-route", "settings");
    const advanced = screen.getByText("更多和高级").closest("details");
    expect(advanced).not.toHaveAttribute("open");
    expect(screen.getByRole("button", { name: /提醒和待办/ })).toHaveAttribute("data-stage-route", "agent");
    expect(screen.getByRole("button", { name: /成长记录/ })).toHaveAttribute("data-stage-route", "growth");
    expect(screen.getByRole("button", { name: /我的资料/ })).toHaveAttribute("data-stage-route", "world");
    expect(screen.getByLabelText("聊天输入")).toBeInTheDocument();
  });

  it("does not expose support abilities as first-screen primary actions", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    });

    const commandCenter = screen.getByLabelText("陪伴入口");
    const primaryActionNames = within(commandCenter)
      .getAllByRole("button")
      .slice(0, 3)
      .map((button) => button.textContent ?? "");

    expect(primaryActionNames).toEqual([
      expect.stringContaining("陪我聊聊"),
      expect.stringContaining("看看记忆"),
      expect.stringContaining("设置边界"),
    ]);
    expect(primaryActionNames.join(" ")).not.toMatch(/任务|知识整理|高级工具|Wiki|Markdown|Agent/);
    expect(screen.queryByText("高级工具")).not.toBeInTheDocument();
  });

  it("shows visible outcomes before the stage command panel when an API is provided", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    }, { api: {} });

    expect(screen.getByLabelText("首页整理结果")).toBeInTheDocument();
    expect(screen.getByLabelText("mock stage visible continuity")).toBeInTheDocument();
    expect(screen.getByLabelText("陪伴入口")).toBeInTheDocument();
    expect(screen.getByLabelText("聊天输入")).toBeInTheDocument();
  });

  it("starts a chat from a visible continuity continuation prompt", () => {
    const { onSendChat } = renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    }, { api: {} });

    fireEvent.click(screen.getByRole("button", { name: "Continue mocked prompt" }));

    expect(onSendChat).toHaveBeenCalledWith("Continue mocked project", expect.any(Function));
  });

  it("opens concrete non-chat routes from stage feature entries", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    });

    fireEvent.click(screen.getByRole("button", { name: /提醒和待办/ }));
    expect(window.location.hash).toBe("#agent");

    fireEvent.click(screen.getByRole("button", { name: /看看记忆/ }));
    expect(window.location.hash).toBe("#memory");

    fireEvent.click(screen.getByRole("button", { name: /成长记录/ }));
    expect(window.location.hash).toBe("#growth");

    fireEvent.click(screen.getByRole("button", { name: /我的资料/ }));
    expect(window.location.hash).toBe("#world");
  });

  it("keeps primary workflow entries separate from the chat composer", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    });

    const commandCenter = screen.getByLabelText("陪伴入口");
    const actionButtons = within(commandCenter).getAllByRole("button");

    expect(actionButtons).toHaveLength(6);
    actionButtons.forEach((button) => {
      expect(button).toHaveAttribute("data-stage-route");
    });
    expect(within(commandCenter).queryByLabelText("聊天输入")).not.toBeInTheDocument();
    expect(screen.getByLabelText("舞台聊天表单")).toBeInTheDocument();
  });

  it("uses the shared pet bubble presentation for paged replies", () => {
    const { container } = renderStageView({
      visible: true,
      title: "",
      message: "分页舞台回复",
      tone: "reply",
      phase: "complete",
      continueHint: "1/3",
      canPageBackward: false,
      canPageForward: true,
    });

    const portraitZone = container.querySelector(".stage-portrait-zone");
    const petAnchor = container.querySelector(".stage-pet-anchor");
    const stageBubble = container.querySelector(".stage-agent-bubble");

    expect(stageBubble).toHaveClass("pet-agent-bubble", "no-header");
    expect(portraitZone).toContainElement(stageBubble as HTMLElement);
    expect(petAnchor).toContainElement(stageBubble as HTMLElement);
    expect(container.querySelector(".stage-bubble")).not.toBeInTheDocument();
    expect(screen.queryByText("1/3")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "上一页回复" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下一页回复" })).not.toBeInTheDocument();
    expect(screen.getByText("分页舞台回复")).toBeInTheDocument();
  });

  it("renders the halfbody portrait in the stage center by default", () => {
    const { container } = renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    });

    const petAnchor = container.querySelector(".stage-pet-anchor");
    const halfbodyPortrait = screen.getByLabelText("mock halfbody portrait");

    expect(halfbodyPortrait).toHaveClass("halfbody-pet-portrait");
    expect(petAnchor).toContainElement(halfbodyPortrait);
  });

  it("keeps the stage bubble layer above side cards with a safe width", () => {
    expect(styles).toContain("--stage-bubble-safe-max");
    expect(styles).toMatch(/\.stage-portrait-zone\s*\{[\s\S]*?z-index:\s*32;/);
    expect(styles).toMatch(/\.stage-command-panel,\s*\.stage-outcome-panel\s*\{[\s\S]*?z-index:\s*10;/);
    expect(styles).toMatch(/\.stage-pet-anchor \.stage-agent-bubble\.pet-agent-bubble\s*\{[\s\S]*?max-width:\s*max\(212px, var\(--stage-bubble-safe-max\)\);/);
    expect(styles).toMatch(/\.stage-pet-anchor \.halfbody-pet-portrait\s*\{[\s\S]*?transform:\s*translateX\(var\(--stage-portrait-visual-offset-x\)\);/);
    expect(styles).toMatch(/@keyframes halfbody-pet-breathe/);
  });

  it("does not render a manual TTS stop control in the stage footer", () => {
    renderStageView({
      visible: false,
      title: "",
      message: "",
      tone: "thinking",
      phase: "idle",
    }, { ttsSpeaking: true });

    expect(screen.queryByRole("button", { name: "停止朗读" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "语音未播放" })).not.toBeInTheDocument();
  });

});
