import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BottomNav } from "./BottomNav";
import { navigationHashForTab, primaryNavigationTabs } from "./navigation";

describe("BottomNav", () => {
  it("renders vector icons above every primary navigation label", () => {
    const activeTab = primaryNavigationTabs[2];
    const { container } = render(<BottomNav activeTab={activeTab} />);

    expect(primaryNavigationTabs).toEqual(["首页", "对话", "记忆", "计划", "设置"]);
    expect(screen.getAllByRole("button")).toHaveLength(primaryNavigationTabs.length);
    expect(screen.queryByRole("button", { name: "资料" })).not.toBeInTheDocument();
    expect(container.querySelectorAll(".bottom-nav-icon")).toHaveLength(primaryNavigationTabs.length);
    expect(container.querySelector(".bottom-nav-center-avatar img")?.getAttribute("src")).toMatch(
      /^\/images\/character\.png\?v=\d+$/,
    );

    primaryNavigationTabs.forEach((tab) => {
      const button = screen.getByRole("button", { name: tab });
      const icon = button.querySelector(".bottom-nav-icon");
      const label = button.querySelector(".bottom-nav-label");

      expect(button).toBeInTheDocument();
      expect(icon).toHaveAttribute("aria-hidden", "true");
      expect(label).toHaveTextContent(tab);
    });

    const activeButton = screen.getByRole("button", { name: activeTab });
    expect(activeButton).toHaveClass("active");
    expect(activeButton).toHaveAttribute("aria-current", "page");
  });

  it("keeps navigation switching wired through the primary routes", () => {
    const targetTab = primaryNavigationTabs[3];
    render(<BottomNav activeTab={primaryNavigationTabs[0]} />);

    fireEvent.click(screen.getByRole("button", { name: targetTab }));

    expect(window.location.hash).toBe(`#${navigationHashForTab(targetTab)}`);
  });

  it("can render secondary routes without pretending a primary tab is active", () => {
    render(<BottomNav activeTab={null} />);

    expect(screen.getAllByRole("button")).toHaveLength(primaryNavigationTabs.length);
    expect(screen.queryByRole("button", { current: "page" })).not.toBeInTheDocument();
  });

  it("does not render when the host route marks the nav inactive", () => {
    render(<BottomNav activeTab={primaryNavigationTabs[0]} visible={false} />);

    expect(screen.queryByLabelText("主导航")).not.toBeInTheDocument();
  });
});
