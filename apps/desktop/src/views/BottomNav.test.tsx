import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BottomNav } from "./BottomNav";
import { navigationHashForTab, primaryNavigationTabs } from "./navigation";

describe("BottomNav", () => {
  it("renders vector icons above every primary navigation label", () => {
    const activeTab = primaryNavigationTabs[2];
    const { container } = render(<BottomNav activeTab={activeTab} />);

    expect(screen.getAllByRole("button")).toHaveLength(primaryNavigationTabs.length);
    expect(container.querySelectorAll(".bottom-nav-icon")).toHaveLength(primaryNavigationTabs.length);

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
    const targetTab = primaryNavigationTabs[4];
    render(<BottomNav activeTab={primaryNavigationTabs[0]} />);

    fireEvent.click(screen.getByRole("button", { name: targetTab }));

    expect(window.location.hash).toBe(`#${navigationHashForTab(targetTab)}`);
  });
});
