# Agent Pet Product Repair Task Set

This task set is written for future coding agents working in the repository root. It is intentionally blunt: the current project has useful backend machinery, but the product experience does not yet make those capabilities obvious or lovable.

## Execution Rules

1. Follow `AGENTS.md` first. Do not edit generated folders, local state, databases, `dist/`, `release/`, or `node_modules/`.
2. Do not delete, move, or batch rewrite Markdown documents without explicit user confirmation.
3. Do not edit `progress.md` unless acting as the coordinator and recording verified evidence.
4. Do not mark anything `Covered`, `Completed`, or `Done` without the required verification output or human evidence.
5. Renderer code must stay inside the Electron contextBridge IPC boundary.
6. Every task must end with command output recorded in the final response.

## Product Diagnosis

The product currently feels more like an engineering console wrapped around a pet than a desktop companion. Hidden capability is not product value. If the user cannot see, understand, and trust the pet's memory behavior within the first minute, the memory stack might as well not exist.

Primary repair direction:

- Make the pet the first-class product surface.
- Make memory and automatic organization visible as small, reassuring receipts.
- Push admin, diagnostics, model settings, Wiki internals, and deep activity logs into secondary views.
- Fix the visual language so it feels like one companion product, not a pile of implemented modules.
- Validate with real users instead of agent-only tests.

## Phase 0 - Documentation And Truth Cleanup

### TASK-P0-001 - Keep Docs Navigable Without Changing Evidence

**Goal:** Keep documentation usable while avoiding fake cleanup that hides history.

**Scope:**

- `docs/README.md`
- `docs/current-specification.md`
- `docs/mvp-acceptance-coverage.md`
- `docs/verification-policy.md`
- `progress.md` read-only unless coordinator

**Steps:**

1. Read `docs/README.md`, `docs/current-specification.md`, `docs/mvp-acceptance-coverage.md`, and `progress.md`.
2. Identify docs that are active, historical, duplicated, or misleading.
3. Update only navigation docs unless the user confirms archival moves.
4. Do not change status claims unless tests or human evidence support the change.

**DoD:**

- `docs/README.md` clearly separates active docs, verification records, and archive material.
- No current status is inflated.
- No Markdown files are deleted or moved without confirmation.

**Suggested Verification:**

```powershell
.\scripts\check-mvp-acceptance-gap.ps1
```

### TASK-P0-002 - Fix Visible Mojibake And Encoding Risk

**Goal:** Prevent broken Chinese text from making the app and docs look untrustworthy.

**Scope:**

- `apps/desktop/src/**/*.tsx`
- `apps/desktop/src/**/*.ts`
- `apps/desktop/src/styles/**/*.css`
- `README.md`
- `docs/*.md`

**Steps:**

1. Search for mojibake markers such as `锛`, `鈥`, `绋`, `妗`, `鏂`, and replacement characters.
2. Confirm whether the issue is file encoding, console rendering, or actual source corruption.
3. Fix only actual source corruption.
4. Add or update a lightweight check script if recurring corruption is found.

**DoD:**

- User-visible Chinese in the desktop app renders correctly.
- Docs opened in a UTF-8 editor show readable text.
- No legitimate historical file is rewritten just because terminal output is garbled.

**Suggested Verification:**

```powershell
rg -n "锛|鈥|绋|妗|鏂|�" README.md docs apps/desktop/src
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

## Phase 1 - First-Minute Companion Experience

### TASK-P1-001 - Replace The Admin-Console First Impression

**Goal:** Make the first screen feel like a companion, not a control panel.

**Scope:**

- `apps/desktop/src/App.tsx`
- `apps/desktop/src/views/StageView.tsx`
- `apps/desktop/src/features/pet/PetWindow.tsx`
- `apps/desktop/src/features/desktop/ControlDashboard.tsx`
- `apps/desktop/src/styles/stage-restore.css`
- `apps/desktop/src/styles/pet.css`
- `apps/desktop/src/styles/live2d.css`
- `apps/desktop/src/styles/dashboard.css`

**Steps:**

1. Audit the current launch and pet-to-stage flow.
2. Define one primary first-minute user goal: "talk to the pet and see what it remembers or did."
3. Move diagnostics, model status, Wiki workflows, and advanced settings out of the first impression.
4. Keep only pet, chat, current companion state, and one compact recent activity area visible.
5. Preserve existing routes for power users.

**DoD:**

- A new user can identify the primary action in 5 seconds.
- The pet/character is visually dominant on the first meaningful screen.
- Advanced tools still exist but no longer compete with chat.

**Suggested Verification:**

```powershell
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

### TASK-P1-002 - Add Memory Receipts To Chat

**Goal:** Turn hidden memory work into visible, reassuring feedback.

**Scope:**

- `apps/desktop/src/features/chat/*`
- `apps/desktop/src/services/agentActivity.ts`
- `apps/desktop/src/features/desktop/AgentActivityEntryRenderer.tsx`
- `apps/backend/app/agents/events.py`
- `apps/backend/app/services/*memory*`
- `apps/backend/tests/*memory*`

**Steps:**

1. Identify the events emitted when chat creates diary, memory, Wiki, task, or reversible agent actions.
2. Design a compact receipt in chat: remembered, skipped, needs confirmation, reversible, failed.
3. Use plain user-facing language. Avoid `agent_actions`, `proposal`, `vault`, `FTS`, and internal IDs.
4. Add "view" and "undo" affordances where already supported by backend contracts.
5. Keep receipts small enough not to interrupt the conversation.

**DoD:**

- After a chat, the user can see whether anything was remembered or organized.
- Risk and reversibility are visible.
- Failed or skipped actions explain why in normal language.

**Suggested Verification:**

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_agent_runtime.py tests/test_memory_graph_services.py; Pop-Location
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

### TASK-P1-003 - Make Live2D State Changes Legible

**Goal:** Make the pet feel alive through state changes that match real system behavior.

**Scope:**

- `apps/desktop/src/components/Live2DStage.tsx`
- `apps/desktop/src/features/live2d/*`
- `apps/desktop/src/styles/live2d.css`
- `apps/desktop/public/live2d/**`

**Steps:**

1. Map real states to visible behaviors: idle, thinking, speaking, remembered, needs confirmation, task created, error.
2. Remove or hide diagnostic labels from the companion surface.
3. Keep technical diagnostics inside an advanced view.
4. Respect reduced motion.

**DoD:**

- The pet visibly reacts to chat, memory, task, and error states.
- The primary pet surface does not show developer diagnostics.
- Fallback mode still looks intentional.

**Suggested Verification:**

```powershell
Push-Location apps\desktop; npm run live2d:check:public; npm run live2d:sdk:check; npm run typecheck; Pop-Location
```

## Phase 2 - Information Architecture Diet

### TASK-P2-001 - Collapse Secondary Workflows

**Goal:** Stop exposing every implemented subsystem as a top-level product promise.

**Scope:**

- `apps/desktop/src/features/desktop/DesktopFeatureRoutes.tsx`
- `apps/desktop/src/features/desktop/controlWorkflowItems.ts`
- `apps/desktop/src/features/navigation/*`
- `apps/desktop/src/styles/navigation.css`
- `apps/desktop/src/styles/feature-windows.css`

**Steps:**

1. Inventory current top-level windows and navigation items.
2. Keep top-level user concepts: Chat, Memory, Settings.
3. Move Wiki, diagnostics, model testing, archive tools, and growth internals under secondary "More" or advanced areas.
4. Rename labels to user language.

**DoD:**

- A normal user sees no more than 3-4 primary destinations.
- Internal implementation concepts are not top-level navigation.
- Existing advanced functionality remains reachable.

**Suggested Verification:**

```powershell
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

### TASK-P2-002 - Rewrite User-Facing Product Language

**Goal:** Remove backend vocabulary from the user experience.

**Scope:**

- `apps/desktop/src/**/*.tsx`
- `apps/desktop/src/**/*.ts`
- `README.md`
- `docs/current-specification.md`

**Steps:**

1. Search visible text for internal terms: `Vault`, `Wiki`, `agent`, `runtime`, `diagnostics`, `proposal`, `archive`, `FTS`, `sidecar`.
2. Decide which terms are acceptable in advanced/debug views only.
3. Replace first-run and normal-user labels with plain Chinese.
4. Keep precise technical wording in docs and advanced settings where needed.

**DoD:**

- Primary UI reads like a companion product, not backend documentation.
- Advanced settings remain accurate and honest.
- No security or privacy claims become softer than the implementation.

**Suggested Verification:**

```powershell
rg -n "Vault|Wiki|agent_actions|runtime|diagnostics|proposal|FTS|sidecar" apps/desktop/src README.md docs/current-specification.md
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

### TASK-P2-003 - Unify The Visual System

**Goal:** Make the app look intentionally designed instead of accumulated.

**Scope:**

- `apps/desktop/src/styles/theme.css`
- `apps/desktop/src/styles/base.css`
- `apps/desktop/src/styles/glass.css`
- `apps/desktop/src/styles/pet.css`
- `apps/desktop/src/styles/live2d.css`
- `apps/desktop/src/styles/dashboard.css`
- `apps/desktop/src/styles/chat.css`

**Steps:**

1. Audit color tokens, radius, shadows, glass effects, and typography.
2. Pick one companion palette and one radius system.
3. Reduce generic glass cards where they do not communicate hierarchy.
4. Preserve contrast and focus states.
5. Avoid copying the reference video's purple overload unless the user explicitly chooses that direction.

**DoD:**

- The pet, chat, stage, memory receipts, and settings feel like one product.
- Text contrast remains WCAG AA for normal text.
- Touch targets remain usable.

**Suggested Verification:**

```powershell
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

## Phase 3 - Demonstrable Product Loop

### TASK-P3-001 - Build A 30-Second Demo Path

**Goal:** Make the product easy to explain in a short recording.

**Scope:**

- `apps/desktop/src/features/onboarding/*`
- `apps/desktop/src/features/chat/*`
- `apps/desktop/src/features/memory/*`
- `apps/backend/tests/test_agent_runtime.py`
- `docs/runbook.md`

**Steps:**

1. Define a short demo script: open pet, send one message, see reply, see memory receipt, inspect or undo.
2. Add a guided trial only if it uses real app flows, not fake screenshots.
3. Ensure demo data is isolated from real Vaults and local databases.
4. Document the demo in `docs/runbook.md`.

**DoD:**

- A reviewer can reproduce a 30-second story without developer explanation.
- The flow does not require real user secrets or a real personal Vault.
- The demo proves visible value, not just implementation breadth.

**Suggested Verification:**

```powershell
.\scripts\runbook-smoke.ps1 -Port 8766
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

### TASK-P3-002 - Real User Validation Gate

**Goal:** Stop pretending agent-only tests prove product usefulness.

**Scope:**

- `docs/verification/task-0102/`
- `docs/verification/task-0103/`
- `docs/verification/task-0506/`
- `docs/mvp-acceptance-coverage.md`

**Steps:**

1. Recruit at least one non-developer tester for the core loop.
2. Observe whether they can chat, understand memory receipts, inspect memory, and undo.
3. Record friction in plain language.
4. Convert top friction points into follow-up tasks.
5. Do not mark validation as completed without real evidence.

**DoD:**

- At least one non-developer test record exists.
- The test includes confusion points, not only success cases.
- Status docs remain honest about skipped or missing evidence.

**Suggested Verification:**

```powershell
.\scripts\check-mvp-acceptance-gap.ps1
```

### TASK-P3-003 - Decide Whether Office/Excel Is In Scope

**Goal:** Prevent comparison-driven scope creep.

**Scope:**

- `docs/decisions/scope-freeze.md`
- `docs/current-specification.md`
- future backend/desktop files only after decision

**Steps:**

1. Write a decision note comparing two directions:
   - companion memory product,
   - general desktop operator with Excel/file tools.
2. If Excel is out of scope, explicitly freeze it.
3. If Excel is in scope, define a separate threat model and permission boundary before coding.
4. Do not add file automation tools casually.

**DoD:**

- The project has a written decision on Excel/Office-style automation.
- No agent starts implementing broad desktop automation without confirmation.
- The decision matches the product's first-minute experience.

**Suggested Verification:**

```powershell
Test-Path docs/decisions/scope-freeze.md
```

## Recommended Execution Order

1. `TASK-P0-002` because broken text destroys trust immediately.
2. `TASK-P1-001` because first impression is currently the biggest product weakness.
3. `TASK-P1-002` because memory must become visible value.
4. `TASK-P1-003` because the pet needs to react like a companion.
5. `TASK-P2-001` and `TASK-P2-002` because navigation and wording are leaking implementation details.
6. `TASK-P2-003` because visual polish should follow product hierarchy, not precede it.
7. `TASK-P3-001` and `TASK-P3-002` because a product that cannot be demoed and tested is not productized.
8. `TASK-P3-003` before any Excel or broad desktop automation work.

## Non-Goals

- Do not turn the app into a generic AI coding monitor.
- Do not add Excel/Office automation just because another project demos it.
- Do not make hidden memory internals louder than the pet experience.
- Do not replace real validation with screenshots of successful tests.
- Do not make the first screen a settings dashboard.
