import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const dashboardStyles = readFileSync(resolve(__dirname, "dashboard.css"), "utf8");
const electronWindows = readFileSync(resolve(__dirname, "../../electron/windows.js"), "utf8");

describe("homeboard layout contract", () => {
  it("keeps the home route locked to one viewport with drawer overflow isolated", () => {
    expect(dashboardStyles).toContain("Product Design no-scroll homeboard lock");
    expect(dashboardStyles).toMatch(
      /body\[data-window-mode="stage"\],\s*body\[data-window-mode="control"\]\s*\{[^}]*overflow:\s*hidden;/,
    );
    expect(dashboardStyles).toMatch(
      /\.control-home-shell\s*\{[^}]*height:\s*100dvh;[^}]*overflow:\s*hidden;/,
    );
    expect(dashboardStyles).toMatch(
      /\.control-below-fold\s*\{[^}]*position:\s*fixed;[^}]*margin:\s*0;/,
    );
    expect(dashboardStyles).toMatch(
      /Reference screenshot fidelity lock[\s\S]*\.control-below-fold\s*\{[^}]*width:\s*1px;[^}]*clip-path:\s*inset\(50%\);[^}]*pointer-events:\s*none;/,
    );
    expect(dashboardStyles).toMatch(
      /@media \(max-width:\s*1180px\)\s*\{[\s\S]*\.control-desktop-grid\s*\{[^}]*grid-template-columns:\s*minmax\(190px,\s*240px\)\s*minmax\(330px,\s*1fr\)\s*minmax\(210px,\s*260px\);/,
    );
    expect(dashboardStyles).toContain("@media (max-width: 820px)");
    expect(electronWindows).toMatch(/stageWindow\s*=\s*createAppWindow\(\{[\s\S]*?width:\s*1100,[\s\S]*?height:\s*720,[\s\S]*?minWidth:\s*900,[\s\S]*?minHeight:\s*600,/);
    expect(electronWindows).toMatch(/controlWindow\s*=\s*createAppWindow\(\{[\s\S]*?width:\s*1200,[\s\S]*?height:\s*820,[\s\S]*?minWidth:\s*960,[\s\S]*?minHeight:\s*640,/);
    expect(electronWindows).toMatch(/agentWindow\s*=\s*createAppWindow\(\{[\s\S]*?width:\s*980,[\s\S]*?height:\s*740,[\s\S]*?minWidth:\s*760,[\s\S]*?minHeight:\s*560,/);
    expect(electronWindows).toMatch(/featureWindow\s*=\s*createAppWindow\(\{[\s\S]*?width:\s*980,[\s\S]*?height:\s*740,[\s\S]*?minWidth:\s*760,[\s\S]*?minHeight:\s*560,/);
    expect(dashboardStyles).toContain("Default design baselines: stageWindow 1100x720; controlWindow 1200x820;");
    expect(dashboardStyles).toContain("featureWindow/agentWindow 980x740");
    expect(dashboardStyles).toContain("User-resize safety floors, not the visual baseline: stageWindow 900x600;");
    expect(dashboardStyles).toContain("@media (max-width: 1100px) and (max-height: 720px)");
    expect(dashboardStyles).toContain("@media (max-width: 960px) and (max-height: 640px)");
    expect(dashboardStyles).not.toContain("@media (max-height: 920px)");
    expect(dashboardStyles).toMatch(
      /\.control-drawer-body,\s*\.control-support-grid,\s*\.control-secondary-grid\s*\{[^}]*overflow:\s*auto;/,
    );
  });

  it("keeps left home cards compact without clipping journal or goal text", () => {
    expect(dashboardStyles).toContain("No-clip card density pass");
    expect(dashboardStyles).toMatch(
      /\.control-left-rail\s*\{[^}]*grid-template-rows:\s*auto minmax\(150px,\s*0\.98fr\) minmax\(118px,\s*0\.72fr\) minmax\(150px,\s*0\.82fr\);/,
    );
    expect(dashboardStyles).toMatch(
      /\.control-journal-card\s*\{[^}]*grid-template-rows:\s*auto minmax\(48px,\s*1fr\) auto auto;[^}]*align-content:\s*stretch;/,
    );
    expect(dashboardStyles).toMatch(
      /\.control-journal-card textarea\s*\{[^}]*min-height:\s*0;[^}]*height:\s*100%;/,
    );
    expect(dashboardStyles).toMatch(
      /\.control-goal-toggle\s*\{[^}]*width:\s*100%;[^}]*justify-self:\s*stretch;[^}]*white-space:\s*normal;/,
    );
    expect(dashboardStyles).toMatch(
      /\.control-goal-row strong\s*\{[^}]*overflow:\s*visible;[^}]*text-overflow:\s*clip;[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;/,
    );
    expect(dashboardStyles).toMatch(
      /\.control-vital-orb\s*\{[^}]*width:\s*clamp\(50px,\s*9dvh,\s*82px\);[^}]*height:\s*clamp\(50px,\s*9dvh,\s*82px\);/,
    );
    expect(dashboardStyles).toMatch(
      /\.control-memory-entry:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--focus-ring\);[^}]*outline-offset:\s*3px;/,
    );
    expect(dashboardStyles).not.toMatch(
      /\.control-journal-card textarea,\s*\.control-goal-form input\s*\{[^}]*outline:\s*none;/,
    );
  });

  it("keeps long status labels inside their fixed cards", () => {
    expect(dashboardStyles).toMatch(
      /\.control-status-left small,\s*\.control-status-right small\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis;[^}]*white-space:\s*nowrap;/,
    );
    expect(dashboardStyles).toMatch(
      /\.control-status-left > span,\s*\.control-status-right > span\s*\{[^}]*min-width:\s*0;[^}]*overflow:\s*hidden;/,
    );
  });
});
