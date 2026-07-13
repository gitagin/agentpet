import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const themeStyles = readFileSync(resolve(__dirname, "theme.css"), "utf8");
const demoStyles = readFileSync(resolve(__dirname, "demo-scope.css"), "utf8");
const styleEntry = readFileSync(resolve(__dirname, "../styles.css"), "utf8");

describe("demo scope layout contract", () => {
  it("defines stable shell and panel tokens outside responsive media queries", () => {
    [
      "--page-padding:",
      "--page-max-width:",
      "--page-panel-gap:",
      "--feature-header-height:",
      "--bottom-nav-height:",
      "--bottom-nav-safe-area:",
      "--depth-bg:",
      "--panel-primary-bg:",
      "--panel-secondary-bg:",
      "--panel-elevated-bg:",
      "--panel-border:",
      "--shadow-panel-primary:",
      "--shadow-panel-secondary:",
    ].forEach((token) => expect(themeStyles).toContain(token));
  });

  it("imports the narrow demo overrides after the legacy polish layer", () => {
    expect(styleEntry.lastIndexOf('desktop-polish.css')).toBeLessThan(styleEntry.lastIndexOf('demo-scope.css'));
    expect(demoStyles).toContain("Demo scope lock");
    expect(demoStyles).toMatch(/\.stage-command-shell\s*\{[^}]*--text:\s*#24323a;/);
    expect(demoStyles).toMatch(/\.message-agent-action-buckets\s*\{[^}]*repeat\(4,/);
    expect(demoStyles).toMatch(/\.task-trace-disclosure\[open\]/);
  });

  it("keeps the three-column homeboard inside 861px to 980px viewports", () => {
    expect(demoStyles).toMatch(/@media \(min-width: 861px\) and \(max-width: 980px\)/);
    expect(demoStyles).toMatch(
      /\.control-home-shell \.control-desktop-grid\s*\{[^}]*grid-template-columns:\s*var\(--home-left-col\) minmax\(0, 1fr\) var\(--home-right-col\);/,
    );
    expect(demoStyles).toMatch(
      /\.control-home-shell \.control-right-rail\s*\{[^}]*width:\s*var\(--home-right-col\);[^}]*min-width:\s*0;[^}]*max-width:\s*var\(--home-right-col\);/,
    );
  });

  it("restores the compact two-column homeboard between 761px and 860px", () => {
    expect(demoStyles).toMatch(/@media \(min-width: 761px\) and \(max-width: 860px\)/);
    expect(demoStyles).toMatch(
      /\.control-home-shell \.control-desktop-grid\s*\{[^}]*grid-template-columns:\s*minmax\(220px, 260px\) minmax\(0, 1fr\);/,
    );
    expect(demoStyles).toMatch(/\.control-home-shell \.control-right-rail\s*\{[^}]*display:\s*none;/);
    expect(demoStyles).toMatch(/\.control-home-shell \.control-bottom-dock\s*\{[^}]*left:\s*calc\(/);
  });
});
