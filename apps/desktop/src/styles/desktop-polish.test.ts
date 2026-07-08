import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const polishStyles = readFileSync(resolve(__dirname, "desktop-polish.css"), "utf8");

describe("desktop polish navigation contract", () => {
  it("keeps feature route navigation fixed to the bottom like the home route", () => {
    expect(polishStyles).toContain("Default design baselines: stageWindow 1100x720; controlWindow 1200x820;");
    expect(polishStyles).toContain("featureWindow/agentWindow 980x740");
    expect(polishStyles).toContain("User-resize safety floors, not the visual baseline: stageWindow 900x600;");
    expect(polishStyles).toContain("@media (min-width: 1360px) and (min-height: 820px)");
    expect(polishStyles).toContain("Product Design feature dock sync");
    expect(polishStyles).toMatch(
      /\.feature-shell \.bottom-nav\s*\{[^}]*position:\s*fixed;[^}]*top:\s*auto;[^}]*bottom:\s*clamp\(18px,\s*3\.6dvh,\s*38px\);[^}]*left:\s*50%;[^}]*width:\s*clamp\(760px,\s*67\.5vw,\s*1004px\);/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*1100px\) and \(max-height:\s*720px\)\s*\{[\s\S]*\.feature-shell \.bottom-nav\s*\{[^}]*bottom:\s*18px;[^}]*width:\s*min\(820px,\s*calc\(100vw - 96px\)\);/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*980px\) and \(max-height:\s*740px\)\s*\{[\s\S]*\.feature-shell \.bottom-nav\s*\{[^}]*--bottom-nav-item-width:\s*84px;[^}]*bottom:\s*16px;[^}]*width:\s*min\(820px,\s*calc\(100vw - 72px\)\);/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*960px\) and \(max-height:\s*640px\)\s*\{[\s\S]*\.feature-shell \.bottom-nav\s*\{[^}]*--bottom-nav-item-width:\s*76px;[^}]*bottom:\s*12px;[^}]*width:\s*min\(648px,\s*calc\(100vw - 252px\)\);/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*900px\)\s*\{[\s\S]*\.feature-shell \.bottom-nav\s*\{[^}]*--bottom-nav-item-width:\s*68px;[^}]*width:\s*min\(608px,\s*calc\(100vw - 264px\)\);/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*760px\) and \(max-height:\s*560px\)\s*\{[\s\S]*\.feature-shell \.bottom-nav\s*\{[^}]*--bottom-nav-item-width:\s*72px;[^}]*bottom:\s*8px;/,
    );
  });
});

describe("desktop polish detail contract", () => {
  it("keeps the home stage inside explicit safety zones instead of negative offsets", () => {
    expect(polishStyles).toContain("Product Design stage safety zones");
    expect(polishStyles).toMatch(
      /\.control-home-shell\s*\{[^}]*--home-dock-height:\s*clamp\(58px,\s*8\.2dvh,\s*78px\);[^}]*--home-stage-safe-top:\s*clamp\(12px,\s*2\.2dvh,\s*28px\);[^}]*--home-stage-safe-bottom:\s*clamp\(12px,\s*2\.2dvh,\s*26px\);[^}]*--home-composer-height:\s*clamp\(68px,\s*10\.8dvh,\s*88px\);[^}]*--home-portrait-bottom:\s*calc\(var\(--home-stage-safe-bottom\) \+ var\(--home-composer-height\) \+ var\(--home-composer-gap\)\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-center-stage\s*\{[^}]*position:\s*relative;[^}]*height:\s*100%;[^}]*margin-top:\s*0;[^}]*overflow:\s*hidden;[^}]*contain:\s*layout paint;/,
    );
    expect(polishStyles).toMatch(
      /\.control-speech-bubble\s*\{[^}]*top:\s*var\(--home-stage-safe-top\);[^}]*min-height:\s*var\(--home-speech-height\);[^}]*overflow:\s*hidden;/,
    );
    expect(polishStyles).toMatch(
      /\.control-stage-composer\s*\{[^}]*bottom:\s*var\(--home-stage-safe-bottom\);[^}]*min-height:\s*var\(--home-composer-height\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-portrait-anchor\s*\{[^}]*bottom:\s*var\(--home-portrait-bottom\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-orbit-map\s*\{[^}]*inset:[^}]*var\(--home-stage-top-clearance\)[^}]*calc\(var\(--home-stage-safe-bottom\) \+ var\(--home-composer-height\) \+ clamp\(8px,\s*1\.6dvh,\s*18px\)\)[^}]*z-index:\s*4;[^}]*overflow:\s*hidden;/,
    );
    expect(polishStyles).toMatch(
      /\.orbit-point\s*\{[^}]*max-width:\s*min\(144px,\s*32%\);[^}]*grid-template-columns:\s*13px minmax\(0,\s*1fr\);[^}]*color:\s*var\(--home-soft\);[^}]*opacity:\s*0\.9;/,
    );
    expect(polishStyles).toMatch(
      /\.orbit-point small\s*\{[^}]*display:\s*block;[^}]*grid-column:\s*2;[^}]*color:\s*var\(--home-muted\);/,
    );
    expect(polishStyles).toMatch(
      /\.point-one\s*\{[^}]*left:\s*2%;[^}]*top:\s*10%;[^}]*\}[\s\S]*\.point-two\s*\{[^}]*right:\s*3%;[^}]*top:\s*10%;/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*1100px\) and \(max-height:\s*720px\)\s*\{[\s\S]*\.orbit-point\s*\{[^}]*max-width:\s*104px;[^}]*color:\s*var\(--home-soft\);[^}]*font-size:\s*10px;/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*960px\) and \(max-height:\s*640px\)\s*\{[\s\S]*\.orbit-point\s*\{[^}]*max-width:\s*74px;[^}]*grid-template-columns:\s*10px minmax\(0,\s*1fr\);[^}]*color:\s*var\(--home-soft\);[^}]*font-size:\s*9px;/,
    );
    expect(polishStyles).toMatch(
      /\.control-status-left,\s*\.control-status-right\s*\{[^}]*bottom:\s*calc\(var\(--home-dock-bottom\) \+ var\(--home-dock-height\) \+ clamp\(8px,\s*1\.4dvh,\s*14px\)\);/,
    );
    expect(polishStyles).not.toMatch(/margin-top:\s*-/);
    expect(polishStyles).not.toMatch(/top:\s*clamp\(-/);
    expect(polishStyles).not.toMatch(/bottom:\s*clamp\(-/);
    expect(polishStyles).not.toMatch(/height:\s*calc\(100% \+/);
  });

  it("keeps the goals card readable and tightens the memory timeline gutter", () => {
    expect(polishStyles).toContain("Product Design detail fix");
    expect(polishStyles).toMatch(
      /\.control-left-rail\s*\{[^}]*grid-template-rows:\s*auto minmax\(120px,\s*0\.64fr\) minmax\(148px,\s*0\.78fr\) minmax\(154px,\s*0\.82fr\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-goals-card\s*\{[^}]*min-height:\s*clamp\(142px,\s*19dvh,\s*158px\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-goal-row\s*\{[^}]*min-height:\s*clamp\(22px,\s*3\.1dvh,\s*26px\);[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\) 22px;[^}]*align-items:\s*center;/,
    );
    expect(polishStyles).toMatch(
      /\.control-goal-toggle\s*\{[^}]*min-width:\s*0;[^}]*grid-template-columns:\s*22px minmax\(0,\s*1fr\);[^}]*align-items:\s*center;/,
    );
    expect(polishStyles).toMatch(
      /\.control-goal-delete\s*\{[^}]*justify-self:\s*end;[^}]*align-self:\s*center;/,
    );
    expect(polishStyles).toMatch(
      /\.control-pet-vitals\s*\{[^}]*min-height:\s*clamp\(148px,\s*19\.5dvh,\s*164px\);[^}]*align-content:\s*start;/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*1100px\) and \(max-height:\s*720px\)\s*\{[\s\S]*\.control-left-rail\s*\{[^}]*grid-template-rows:\s*auto minmax\(116px,\s*0\.58fr\) minmax\(138px,\s*0\.7fr\) minmax\(146px,\s*0\.76fr\);/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*1100px\) and \(max-height:\s*720px\)\s*\{[\s\S]*\.control-pet-vitals\s*\{[^}]*min-height:\s*146px;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-timeline\s*\{[^}]*--timeline-pad:\s*clamp\(18px,\s*1\.8vw,\s*24px\);[^}]*--timeline-line-x:\s*10px;[^}]*padding-left:\s*var\(--timeline-pad\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-entry\s*\{[^}]*grid-template-columns:\s*clamp\(34px,\s*3\.1vw,\s*38px\) minmax\(0,\s*1fr\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-entry::before\s*\{[^}]*left:\s*calc\(var\(--timeline-line-x\) - var\(--timeline-pad\) - 3px\);/,
    );
  });

  it("keeps the journal action clear and upgrades home scrollbars", () => {
    expect(polishStyles).toContain("Product Design journal action and scroll polish");
    expect(polishStyles).toMatch(
      /\.control-journal-card\s*\{[^}]*position:\s*relative;[^}]*isolation:\s*isolate;[^}]*min-height:\s*clamp\(136px,\s*18\.5dvh,\s*176px\);[^}]*grid-template-rows:\s*minmax\(32px,\s*auto\) minmax\(48px,\s*1fr\) minmax\(16px,\s*auto\) minmax\(18px,\s*auto\);[^}]*overflow:\s*visible;[^}]*row-gap:\s*clamp\(4px,\s*0\.85dvh,\s*8px\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-journal-card \.control-card-title \.control-mini-button\s*\{[^}]*position:\s*relative;[^}]*z-index:\s*3;[^}]*flex:\s*0 0 32px;/,
    );
    expect(polishStyles).toMatch(
      /\.control-journal-card textarea\s*\{[^}]*overflow-y:\s*auto;[^}]*scrollbar-gutter:\s*stable;[^}]*scrollbar-width:\s*thin;[^}]*scrollbar-color:\s*rgba\(245,\s*141,\s*165,\s*0\.42\) rgba\(255,\s*255,\s*255,\s*0\.045\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-journal-card textarea::-webkit-scrollbar-button\s*\{[^}]*display:\s*none;[^}]*width:\s*0;[^}]*height:\s*0;/,
    );
    expect(polishStyles).toMatch(
      /\.control-journal-card > small\s*\{[^}]*align-self:\s*center;[^}]*justify-self:\s*end;[^}]*min-height:\s*18px;[^}]*margin-top:\s*0;[^}]*line-height:\s*18px;/,
    );
    expect(polishStyles).toMatch(
      /\.control-drawer-body,\s*\.control-support-grid,\s*\.control-secondary-grid,\s*\.control-home-shell \.message-list,\s*\.control-home-shell \.agent-activity-log-list,\s*\.control-memory-panel\s*\{[^}]*scrollbar-width:\s*thin;[^}]*scrollbar-color:\s*var\(--home-scrollbar-thumb\) var\(--home-scrollbar-track\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-drawer-body::-webkit-scrollbar,[\s\S]*\.control-memory-panel::-webkit-scrollbar\s*\{[^}]*width:\s*7px;[^}]*height:\s*7px;/,
    );
    expect(polishStyles).toMatch(
      /\.control-drawer-body::-webkit-scrollbar-thumb,[\s\S]*\.control-memory-panel::-webkit-scrollbar-thumb\s*\{[^}]*min-height:\s*36px;[^}]*border:\s*1px solid var\(--home-scrollbar-border\);[^}]*border-radius:\s*999px;[^}]*background:\s*var\(--home-scrollbar-thumb\);[^}]*box-shadow:\s*none;/,
    );
    expect(polishStyles).toMatch(
      /--home-scrollbar-track:\s*transparent;[\s\S]*--home-scrollbar-thumb:\s*rgba\(235,\s*240,\s*242,\s*0\.22\);[\s\S]*--home-scrollbar-thumb-hover:\s*rgba\(235,\s*240,\s*242,\s*0\.34\);/,
    );
  });

  it("keeps collapsed memory days as a compact index and expanded cards roomy", () => {
    expect(polishStyles).toMatch(
      /\.control-right-rail\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\);[^}]*align-content:\s*stretch;[^}]*align-items:\s*stretch;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-panel\s*\{[^}]*height:\s*100%;[^}]*max-height:\s*100%;[^}]*grid-template-rows:\s*auto auto minmax\(0,\s*1fr\) auto;[^}]*overflow:\s*hidden;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-days\s*\{[^}]*height:\s*100%;[^}]*display:\s*grid;[^}]*align-content:\s*start;[^}]*grid-auto-flow:\s*row;[^}]*grid-auto-rows:\s*minmax\(min-content,\s*max-content\);[^}]*overflow:\s*auto;[^}]*overflow-x:\s*hidden;[^}]*scrollbar-gutter:\s*stable;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-day\s*\{[^}]*display:\s*grid;[^}]*grid-template-rows:\s*auto minmax\(0,\s*auto\);[^}]*height:\s*auto;[^}]*min-height:\s*0;[^}]*overflow:\s*visible;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-day\.is-collapsed \.control-memory-day-toggle\s*\{[^}]*min-height:\s*44px;[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\) 26px 16px;[^}]*border:\s*1px solid rgba\(255,\s*255,\s*255,\s*0\.075\);[^}]*border-radius:\s*10px;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-day\.is-collapsed \.control-memory-day-label\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(58px,\s*auto\) minmax\(0,\s*1fr\);[^}]*align-items:\s*center;[^}]*line-height:\s*1\.08;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-day\.is-expanded\s*\{[^}]*position:\s*relative;[^}]*z-index:\s*1;[^}]*height:\s*auto;[^}]*max-height:\s*none;[^}]*min-height:\s*0;[^}]*overflow:\s*visible;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-day\.is-expanded \.control-memory-timeline\s*\{[^}]*max-height:\s*none;[^}]*min-height:\s*0;[^}]*overflow:\s*visible;[^}]*padding-right:\s*0;/,
    );
    expect(polishStyles).not.toMatch(
      /\.control-memory-day\.is-expanded\s*\{[^}]*max-height:\s*min\(var\(--memory-expanded-day-min-height/,
    );
    expect(polishStyles).not.toMatch(
      /\.control-memory-day\.is-expanded \.control-memory-timeline\s*\{[^}]*max-height:\s*min\(var\(--memory-visible-timeline-min-height/,
    );
    expect(polishStyles).not.toMatch(
      /\.control-memory-day\.is-expanded \.control-memory-timeline\s*\{[^}]*overflow:\s*auto/,
    );
    expect(polishStyles).not.toMatch(
      /\.control-memory-timeline\s*\{[^}]*transition:[^}]*max-height/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-day\.is-collapsed \.control-memory-timeline\s*\{[^}]*max-height:\s*0;[^}]*min-height:\s*0;[^}]*overflow:\s*hidden;[^}]*opacity:\s*0;[^}]*transform:\s*translateY\(-6px\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-entry\s*\{[^}]*min-height:\s*clamp\(104px,\s*12dvh,\s*124px\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-entry::before\s*\{[^}]*top:\s*var\(--timeline-node-y\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-entry-node\s*\{[^}]*align-self:\s*start;[^}]*justify-self:\s*center;[^}]*min-width:\s*clamp\(48px,\s*4\.8vw,\s*54px\);[^}]*margin-top:\s*calc\(var\(--timeline-node-y\) - 12px\);/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-entry-node time\s*\{[^}]*display:\s*block;[^}]*font-size:\s*10px;[^}]*text-align:\s*center;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-entry-card\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\) 30px;[^}]*gap:\s*8px;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-entry strong\s*\{[^}]*display:\s*-webkit-box;[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;[^}]*-webkit-line-clamp:\s*2;/,
    );
    expect(polishStyles).toMatch(
      /\.control-memory-entry-icon\s*\{[^}]*position:\s*static;[^}]*width:\s*30px;[^}]*height:\s*30px;/,
    );
  });
});

describe("desktop polish single-scroll contract", () => {
  it("keeps secondary feature pages on one page scroller", () => {
    expect(polishStyles).toContain("Product Design single-scroll routes");
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\],\s*body\[data-window-mode="memory"\],\s*body\[data-window-mode="agent"\],\s*body\[data-window-mode="world"\],\s*body\[data-window-mode="settings"\],\s*body\[data-window-mode="growth"\]\s*\{[^}]*overflow:\s*hidden;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] #root,[\s\S]*body\[data-window-mode="growth"\] #root\s*\{[^}]*overflow:\s*hidden;/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell \.feature-window-content\s*\{[^}]*overflow-x:\s*hidden;[^}]*overflow-y:\s*auto;[^}]*overscroll-behavior:\s*contain;[^}]*scrollbar-gutter:\s*stable;/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell\s*\{[^}]*--feature-dock-bottom:\s*clamp\(18px,\s*3\.6dvh,\s*38px\);[^}]*--feature-dock-height:\s*clamp\(58px,\s*8\.2dvh,\s*78px\);[^}]*--feature-dock-clearance:\s*clamp\(30px,\s*5dvh,\s*44px\);[^}]*--feature-dock-safe-area:\s*calc\(var\(--feature-dock-bottom\) \+ var\(--feature-dock-height\) \+ var\(--feature-dock-clearance\)\);/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell \.feature-window-content\s*\{[^}]*padding-bottom:\s*calc\(var\(--feature-dock-safe-area\) \+ env\(safe-area-inset-bottom,\s*0px\)\);[^}]*scroll-padding-bottom:\s*calc\(var\(--feature-dock-safe-area\) \+ env\(safe-area-inset-bottom,\s*0px\)\);/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell \.feature-window-content::-webkit-scrollbar-thumb\s*\{[^}]*min-height:\s*42px;[^}]*border:\s*1px solid rgba\(16,\s*16,\s*20,\s*0\.38\);[^}]*border-radius:\s*999px;[^}]*background:\s*rgba\(235,\s*240,\s*242,\s*0\.22\);/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*980px\) and \(max-height:\s*740px\)\s*\{[\s\S]*\.feature-shell\s*\{[^}]*--feature-dock-bottom:\s*16px;[^}]*--feature-dock-height:\s*68px;[^}]*--feature-dock-clearance:\s*34px;/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*960px\) and \(max-height:\s*640px\)\s*\{[\s\S]*\.feature-shell\s*\{[^}]*--feature-dock-bottom:\s*12px;[^}]*--feature-dock-height:\s*62px;[^}]*--feature-dock-clearance:\s*32px;/,
    );
  });

  it("removes nested list, message, and onboarding scrollbars inside feature routes", () => {
    expect(polishStyles).toMatch(
      /\.feature-shell :where\([\s\S]*\.message-list,[\s\S]*\.task-digest-list,[\s\S]*\.wiki-browser-list,[\s\S]*\.memory-priority-list,[\s\S]*\.growth-history-list,[\s\S]*\.diff-preview[\s\S]*\)\s*\{[^}]*max-height:\s*none;[^}]*height:\s*auto;[^}]*overflow:\s*visible;[^}]*contain:\s*none;[^}]*will-change:\s*auto;/,
    );
  });

  it("keeps the chat dialogue window fitted with a visible composer and hidden scrollbar chrome", () => {
    expect(polishStyles).toContain("Product Design chat window fit");
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\],\s*body\[data-window-mode="chat"\] #root\s*\{[^}]*height:\s*100dvh;[^}]*min-height:\s*100dvh;[^}]*overflow:\s*hidden;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.feature-shell\s*\{[^}]*--chat-dock-safe-area:\s*calc\(var\(--chat-dock-bottom\) \+ var\(--chat-dock-height\) \+ var\(--chat-dock-clearance\)\);[^}]*grid-template-rows:\s*auto minmax\(0,\s*1fr\);[^}]*overflow:\s*hidden;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.feature-window-content\s*\{[^}]*height:\s*100%;[^}]*overflow:\s*hidden;[^}]*padding:\s*0 4px calc\(var\(--chat-dock-safe-area\) \+ env\(safe-area-inset-bottom,\s*0px\)\);[^}]*scrollbar-width:\s*none;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.panel\.chat-panel\s*\{[^}]*display:\s*grid;[^}]*grid-template-rows:\s*auto auto auto minmax\(0,\s*1fr\) auto auto auto;[^}]*overflow:\s*hidden;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-panel \.message-list\s*\{[^}]*min-height:\s*0;[^}]*height:\s*100%;[^}]*overflow-x:\s*hidden;[^}]*overflow-y:\s*auto;[^}]*scrollbar-width:\s*none;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-panel \.chat-form\s*\{[^}]*position:\s*relative;[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\) auto;[^}]*margin:\s*0;/,
    );
  });

  it("makes chat routes conversation-first instead of shortcut-first", () => {
    expect(polishStyles).toContain("Product Design conversation-first redesign");
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.panel\.chat-panel\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\) minmax\(280px,\s*0\.72fr\);[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\) auto auto auto;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-panel \.message-list\s*\{[^}]*grid-row:\s*1;[^}]*grid-column:\s*1 \/ -1;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-panel \.chat-form\s*\{[^}]*grid-row:\s*4;[^}]*grid-column:\s*1 \/ -1;[^}]*align-self:\s*end;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-panel \.field-note\s*\{[^}]*grid-row:\s*3;[^}]*grid-column:\s*1 \/ -1;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-action-board\s*\{[^}]*grid-row:\s*2;[^}]*grid-column:\s*1;[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);[^}]*gap:\s*6px;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-secondary-modes\s*\{[^}]*grid-row:\s*2;[^}]*grid-column:\s*2;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-panel > \.first-use-onboarding,[\s\S]*body\[data-window-mode="chat"\] \.chat-onboarding-drawer\s*\{[^}]*display:\s*none;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-action-button\s*\{[^}]*min-height:\s*32px;[^}]*padding:\s*4px 10px;/,
    );
  });

  it("unifies feature route typography and foreground tokens", () => {
    expect(polishStyles).toMatch(
      /\.feature-shell\s*\{[^}]*--feature-ink:\s*var\(--color-text\);[^}]*--feature-soft:\s*var\(--color-text-muted\);[^}]*--feature-muted:\s*var\(--color-text-faint\);[^}]*--feature-glass:\s*rgba\(18,\s*18,\s*24,\s*0\.54\);[^}]*--feature-control:\s*rgba\(255,\s*255,\s*255,\s*0\.045\);/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell :where\(input,\s*textarea,\s*select,\s*button\)\s*\{[^}]*font-family:\s*inherit;[^}]*letter-spacing:\s*0;/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell :where\(p,\s*small,\s*span,\s*label,\s*dd,\s*dt,\s*li,\s*\.field-note,\s*\.empty-state\)\s*\{[^}]*color:\s*var\(--feature-soft\);[^}]*font-weight:\s*500;/,
    );
  });

  it("keeps chat copy high contrast on dark message bubbles", () => {
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.message-list \.message-bubble\.assistant\s*\{[^}]*background:[^}]*rgba\(18,\s*17,\s*24,\s*0\.86\);/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.message-list \.message-bubble\.user\s*\{[^}]*background:[^}]*rgba\(15,\s*23,\s*21,\s*0\.88\);[^}]*color:\s*var\(--color-text\);/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.message-list \.message-bubble > p,[\s\S]*body\[data-window-mode="chat"\] \.message-list \.message-bubble \.message-pending\s*\{[^}]*color:\s*inherit;[^}]*font-weight:\s*560;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-panel \.chat-form input::placeholder\s*\{[^}]*color:\s*rgba\(234,\s*223,\s*228,\s*0\.76\);[^}]*font-weight:\s*520;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-action-button strong\s*\{[^}]*color:\s*var\(--feature-ink\);[^}]*font-weight:\s*760;/,
    );
  });

  it("keeps assistant trace and artifact cards readable inside dark chat bubbles", () => {
    expect(polishStyles).toContain("Impeccable contrast pass");
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.message-list \.message-bubble\.assistant \.message-trace > summary\s*\{[^}]*color:\s*#dff7f3;[^}]*font-weight:\s*780;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.message-list \.message-bubble\.assistant :where\([\s\S]*\.message-citations,[\s\S]*\.message-negotiation,[\s\S]*\.continuity-presence-hint,[\s\S]*\.message-agent-actions\.chat-artifacts[\s\S]*\)\s*\{[^}]*background:[^}]*rgba\(18,\s*17,\s*24,\s*0\.92\);[^}]*color:\s*var\(--feature-ink\);/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.message-list \.message-bubble\.assistant :where\([\s\S]*\.message-events span,[\s\S]*\.message-agent-action-bucket,[\s\S]*\.chat-artifact-card[\s\S]*\)\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.07\);[^}]*color:\s*var\(--feature-ink\);/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.message-list \.message-bubble\.assistant :where\([\s\S]*\.message-agent-action-bucket\.success,[\s\S]*\.chat-artifact-card\.success[\s\S]*\)\s*\{[^}]*background:\s*rgba\(80,\s*211,\s*156,\s*0\.14\);[^}]*color:\s*#ecfff6;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.message-list \.message-bubble\.assistant :where\([\s\S]*\.message-citation-empty,[\s\S]*\.continuity-presence-hint span,[\s\S]*\.chat-artifact-card p[\s\S]*\)\s*\{[^}]*color:\s*var\(--feature-soft\);/,
    );
  });

  it("keeps the world tool wiki cards readable on the dark feature shell", () => {
    expect(polishStyles).toContain("legacy wiki and vault cards");
    expect(polishStyles).toMatch(
      /body\[data-window-mode="world"\] \.wiki-page-card\s*\{[^}]*background:[\s\S]*rgba\(18,\s*17,\s*24,\s*0\.9\);[^}]*color:\s*var\(--feature-soft\);/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="world"\] \.wiki-page-card-head strong\s*\{[^}]*color:\s*var\(--feature-ink\);[^}]*font-weight:\s*780;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="world"\] \.wiki-page-card p\s*\{[^}]*color:\s*var\(--feature-soft\);[^}]*line-height:\s*1\.55;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="world"\] \.wiki-page-card-meta dt\s*\{[^}]*color:\s*#f3bac8;[^}]*font-size:\s*11px;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="world"\] \.wiki-page-card-meta dd\s*\{[^}]*color:\s*var\(--feature-ink\);[^}]*font-weight:\s*650;/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell \.wiki-browser-maintenance > summary strong\s*\{[^}]*color:\s*var\(--feature-ink\);[^}]*font-weight:\s*780;/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell \.wiki-browser-maintenance > summary span\s*\{[^}]*color:\s*var\(--feature-soft\);[^}]*font-weight:\s*560;/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell \.wiki-browser-maintenance \.wiki-browser-events span\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.07\);[^}]*color:\s*var\(--feature-soft\);[^}]*font-weight:\s*560;/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell \.wiki-browser-maintenance \.wiki-browser-events strong\s*\{[^}]*color:\s*var\(--feature-ink\);[^}]*font-weight:\s*760;/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell \.wiki-browser-maintenance \.wiki-browser-events span\.error strong\s*\{[^}]*color:\s*#fff1f5;/,
    );
  });

  it("keeps the settings vault overview readable instead of a washed-out light card", () => {
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.vault-summary-panel\s*\{[^}]*background:[\s\S]*rgba\(18,\s*17,\s*24,\s*0\.9\);[^}]*color:\s*var\(--feature-soft\);/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.vault-summary-panel \.section-heading strong,[\s\S]*body\[data-window-mode="settings"\] \.vault-backup-preview strong\s*\{[^}]*color:\s*var\(--feature-ink\);/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.vault-summary-grid div\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.065\);[^}]*color:\s*var\(--feature-soft\);/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.vault-summary-grid dt\s*\{[^}]*color:\s*#f3bac8;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.vault-summary-grid dd\s*\{[^}]*color:\s*var\(--feature-ink\);[^}]*font-weight:\s*720;/,
    );
  });

  it("keeps feature scrollbars subtle and prevents action text from clipping", () => {
    expect(polishStyles).toContain("Product Design page fit safety net");
    expect(polishStyles).toMatch(
      /\.feature-shell\s*\{[^}]*--feature-scrollbar-track:\s*transparent;[^}]*--feature-scrollbar-thumb:\s*rgba\(235,\s*240,\s*242,\s*0\.22\);[^}]*--feature-scrollbar-thumb-hover:\s*rgba\(235,\s*240,\s*242,\s*0\.34\);/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell button:not\(\.bottom-nav-button\)\s*\{[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell button:not\(\.bottom-nav-button\) svg\s*\{[^}]*flex:\s*0 0 auto;/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell :where\([\s\S]*\.chat-action-button,[\s\S]*\.workflow-card,[\s\S]*\.settings-card,[\s\S]*\.continuity-proposal-card[\s\S]*\) :where\(strong,\s*small,\s*span,\s*p\)\s*\{[^}]*overflow:\s*visible;[^}]*text-overflow:\s*clip;[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="chat"\] \.chat-secondary-modes button,[\s\S]*body\[data-window-mode="chat"\] \.chat-guided-trials button\s*\{[^}]*overflow:\s*visible;[^}]*text-overflow:\s*clip;[^}]*white-space:\s*normal;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="stage"\] \.stage-action-card :where\(strong,\s*small,\s*span\),[\s\S]*body\[data-window-mode="stage"\] \.stage-advanced-routes \.stage-action-card :where\(strong,\s*small,\s*span\)\s*\{[^}]*overflow:\s*visible;[^}]*text-overflow:\s*clip;[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;/,
    );
    expect(polishStyles).toMatch(
      /body:not\(\[data-window-mode="chat"\]\) \.feature-shell :where\([\s\S]*\.message-list,[\s\S]*\.growth-history-list,[\s\S]*\.continuity-proposal-list[\s\S]*\)\s*\{[^}]*scrollbar-width:\s*thin;[^}]*scrollbar-color:\s*var\(--feature-scrollbar-thumb\) var\(--feature-scrollbar-track\);/,
    );
    expect(polishStyles).toMatch(
      /\.feature-shell :where\([\s\S]*\.feature-window-content,[\s\S]*textarea,[\s\S]*\.diff-preview[\s\S]*\)::\-webkit-scrollbar-thumb,[\s\S]*body:not\(\[data-window-mode="chat"\]\) \.feature-shell :where\([\s\S]*\.message-list[\s\S]*\)::\-webkit-scrollbar-thumb\s*\{[^}]*min-height:\s*36px;[^}]*border:\s*1px solid var\(--feature-scrollbar-border\);[^}]*background:\s*var\(--feature-scrollbar-thumb\);/,
    );
  });

  it("keeps settings content in direct cards before falling back to one page scroll", () => {
    expect(polishStyles).toContain("Product Design settings card grid");
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.feature-window-content\s*\{[^}]*width:\s*min\(100%,\s*1240px\);/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] #settings-panel\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);[^}]*gap:\s*14px;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] #settings-panel > \.settings-intro,[\s\S]*body\[data-window-mode="settings"\] #settings-panel > \.advanced-agent-model-settings\s*\{[^}]*grid-column:\s*1 \/ -1;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.settings-form-grid,[\s\S]*body\[data-window-mode="settings"\] \.automation-toggle-grid\s*\{[^}]*grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(180px,\s*1fr\)\);/,
    );
    expect(polishStyles).toMatch(
      /@media \(max-width:\s*980px\)\s*\{[\s\S]*body\[data-window-mode="settings"\] #settings-panel\s*\{[^}]*grid-template-columns:\s*1fr;/,
    );
  });

  it("keeps nested settings controls readable on dark cards", () => {
    expect(polishStyles).toContain("Impeccable settings control contrast pass");
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.tts-toggle-row,[\s\S]*body\[data-window-mode="settings"\] \.automation-locked-row\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.045\);[^}]*color:\s*var\(--feature-soft\);/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.tts-toggle-row strong,[\s\S]*body\[data-window-mode="settings"\] \.automation-locked-row strong\s*\{[^}]*color:\s*var\(--feature-ink\);[^}]*font-weight:\s*760;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.tts-toggle-row small,[\s\S]*body\[data-window-mode="settings"\] \.automation-locked-row small\s*\{[^}]*color:\s*var\(--feature-soft\);[^}]*font-weight:\s*540;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.automation-frequency-option input:checked \+ span\s*\{[^}]*background:\s*rgba\(245,\s*141,\s*165,\s*0\.15\);[^}]*color:\s*#fff1f5;/,
    );
    expect(polishStyles).toMatch(
      /body\[data-window-mode="settings"\] \.automation-locked-row b\s*\{[^}]*background:\s*rgba\(155,\s*227,\s*111,\s*0\.16\);[^}]*color:\s*#dff8c8;/,
    );
  });
});
