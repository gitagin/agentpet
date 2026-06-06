# Agent Pet Productization Tasks

This task list is ordered by execution sequence.
Agents should start from `task-01` and continue downward unless the user explicitly changes priority.

Project root: `E:\agentproject`

Rules:
- Follow `AGENTS.md`.
- Do not edit generated/local-state paths such as `node_modules/`, `dist/`, `release/`, `.tmp/`, `*.db`, or logs.
- Renderer work must stay inside React/contextBridge IPC boundaries.
- Each task must include implementation, tests, and a short result report.
- Do not mark acceptance as done unless verification commands pass or the failure is clearly explained.

## task-01: Redesign Main Stage Into A Real Feature Command Center

Goal:
Make the first screen prove the app is more than chat.

Why first:
Users currently see Live2D plus a chat input. This is the biggest reason they believe the product has only one function.

Files:
- `apps/desktop/src/views/StageView.tsx`
- `apps/desktop/src/views/StageView.test.tsx`
- `apps/desktop/src/App.tsx`
- `apps/desktop/src/styles.css`
- `apps/desktop/src/views/navigation.ts`

Implementation:
- Add visible primary actions on the main stage:
  - New task
  - Remember this
  - Organize knowledge
  - Daily review
  - Search memory
- Keep chat available, but do not make it the only obvious action.
- Each action must open a concrete route, drawer, or form surface.
- Preserve clean reply bubble behavior: no pagination controls, no TTS stop button, answer text only.
- Make sure action cards do not overlap Live2D, footer, or bubble.

Acceptance:
- On `#/stage`, a user can immediately see at least five real feature entries.
- At least three entries lead to non-chat workflows.
- Stage still works in desktop and browser dev views.

Verify:
- `Push-Location apps\desktop; npm run test -- StageView App; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`
- Browser check: `http://127.0.0.1:5173/#/stage`

## task-02: Add A Standalone Task Creation And Management Flow

Goal:
Make Task a real product feature, not a chat side effect.

Why second:
Task/reminder is the easiest feature for users to understand as a standalone capability.

Files:
- `apps/desktop/src/views/AgentWorkspaceView.tsx`
- `apps/desktop/src/views/AgentWorkspaceView.test.tsx`
- `apps/desktop/src/features/tasks/useTasks.ts`
- `apps/desktop/src/features/tasks/taskReducer.ts`
- `apps/desktop/src/services/desktopApi.ts`
- `apps/backend/app/api/tasks.py`

Implementation:
- Add a task creation form at the top of the task page:
  - Title
  - Description
  - Due time
  - Reminder time
  - Timezone
- Show task cards with direct actions:
  - Complete
  - Cancel
  - Locate logs/steps
- Use existing APIs:
  - `api.createTask`
  - `api.completeTask`
  - `api.cancelTask`
- Keep approval, execution steps, and logs as secondary sections.

Acceptance:
- User can create a task without opening chat.
- User can complete/cancel a task from the task page.
- Empty state clearly invites creating the first task.

Verify:
- `Push-Location apps\desktop; npm run test -- AgentWorkspaceView TaskPanel useTasks taskReducer; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`

## task-03: Promote Wiki To A Daily Knowledge Organizer

Goal:
Make Wiki a primary knowledge feature, not an advanced maintenance panel.

Why third:
Knowledge organization is one of the strongest differentiators, but it is currently hidden under advanced workflows.

Files:
- `apps/desktop/src/views/WorldWindowView.tsx`
- `apps/desktop/src/features/wiki/WikiBrowserPanel.tsx`
- `apps/desktop/src/features/wiki/WikiWorkflowPanel.tsx`
- `apps/desktop/src/features/wiki/useWiki.ts`
- `apps/desktop/src/services/desktopApi.ts`
- `apps/backend/app/api/wiki.py`

Implementation:
- Put a daily Wiki flow in the first viewport:
  - Paste or write source content
  - Pick target type: concept, entity, comparison, report, summary
  - Preview
  - Apply
- Keep lint, diagnostics, mixed-source repair, and manual target overrides in Advanced.
- Show recent generated Wiki pages as user-facing cards.
- Add clear states for:
  - No Vault bound
  - No Wiki pages
  - Index required

Acceptance:
- User can create/update a Wiki page without using chat.
- "Advanced maintenance" no longer dominates the first screen.
- Recent Wiki output is visible as cards with title, summary, path, and update time.

Verify:
- `Push-Location apps\desktop; npm run test -- WikiWorkflowPanel WikiBrowserPanel WikiTerminology; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`

## task-04: Turn Memory Into A Workbench

Goal:
Make Memory a direct feature for search, add, review, correct, archive, and forget.

Why fourth:
Memory is a core promise of the app, but users currently experience it as background storage and activity logs.

Files:
- `apps/desktop/src/views/MemoryWindowView.tsx`
- `apps/desktop/src/views/MemoryWindowView.test.tsx`
- `apps/desktop/src/features/memory/useMemory.ts`
- `apps/desktop/src/features/memory/AgentActionActivityCard.tsx`
- `apps/desktop/src/services/desktopApi.ts`
- `apps/backend/app/api/memory.py`

Implementation:
- Add prominent memory search.
- Add "Add memory" form using memory proposal APIs.
- Split the page into:
  - Confirmed memories
  - Candidates needing review
  - Diary-derived memories
  - Recent automatic writes
- Add graph fact actions:
  - Confirm
  - Mark wrong
  - Archive
  - Sensitive block
- Move local asset dashboard below real memory actions.

Acceptance:
- User can search memory without chat.
- User can add memory without chat.
- User can review/manage memory facts directly.

Verify:
- `Push-Location apps\desktop; npm run test -- MemoryWindowView AgentActionActivityCard memoryReducer useMemory; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`

## task-05: Build Review Coach As A Standalone Feature

Goal:
Make daily/weekly/monthly review a visible feature instead of a chat prompt.

Why fifth:
Review is a user-facing outcome that can make memory and tasks feel useful.

Files:
- `apps/desktop/src/views/MemoryWindowView.tsx`
- `apps/desktop/src/views/MemoryWindowView.test.tsx`
- `apps/desktop/src/services/desktopApi.ts`
- `apps/backend/app/api/memory.py`
- `apps/backend/app/services/retrospectives.py`

Implementation:
- Add review cards/actions:
  - Today review
  - 7-day review
  - Monthly review
- Show source coverage:
  - Chat diary
  - Tasks
  - Long-term memory
  - Wiki
- Show generated Markdown report path when available.
- Provide "Open report" or "Locate report" when Vault reveal is available.

Acceptance:
- User can generate a review without chat.
- Review output appears as a visible artifact.
- User understands what data was used.

Verify:
- `Push-Location apps\desktop; npm run test -- MemoryWindowView; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`

## task-06: Add Artifact Cards To Chat Results

Goal:
Make chat produce visible outputs, not just answer text.

Why sixth:
Chat can remain the orchestration surface, but users must see concrete results when it creates tasks, memories, Wiki pages, or reviews.

Files:
- `apps/desktop/src/features/chat/ChatMessageList.tsx`
- `apps/desktop/src/features/chat/ChatAgentActionSummary.tsx`
- `apps/desktop/src/features/chat/streamDispatcher.ts`
- `apps/desktop/src/features/chat/handlers/*.ts`
- `apps/desktop/src/services/agentActivity.ts`
- `apps/desktop/src/styles.css`

Implementation:
- Render artifact cards for:
  - Task created
  - Memory written/proposed
  - Wiki page written/proposed
  - Review generated
- Each artifact card should have a primary action:
  - Open task
  - Open memory
  - Open Wiki page
  - Open report
  - Undo if reversible
- Collapse system/tool traces by default.

Acceptance:
- Chat no longer feels like plain text only.
- A user can act on generated outputs directly from chat.
- System/tool events remain hidden unless expanded.

Verify:
- `Push-Location apps\desktop; npm run test -- ChatMessageList ChatAgentActionSummary ChatCitationSummary; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`

## task-07: Replace Empty Dashboards With Guided Trial Flows

Goal:
Make first-time use action-first instead of explanation/status-first.

Why seventh:
After core surfaces exist, empty states must guide users into those surfaces.

Files:
- `apps/desktop/src/App.tsx`
- `apps/desktop/src/views/ChatWindowView.tsx`
- `apps/desktop/src/views/AgentWorkspaceView.tsx`
- `apps/desktop/src/views/MemoryWindowView.tsx`
- `apps/desktop/src/features/wiki/WikiBrowserPanel.tsx`
- `apps/desktop/src/features/settings/SettingsPanel.tsx`

Implementation:
- Add "Try this" actions:
  - Create reminder for tomorrow
  - Save a preference
  - Paste a knowledge snippet
  - Generate today's review
  - Search memory
- Example actions should fill forms or navigate to the right feature.
- Avoid long text blocks before the user acts.

Acceptance:
- New user can try at least three core features without writing a custom prompt.
- Empty states are action-first.

Verify:
- `Push-Location apps\desktop; npm run test -- App ChatWindowView AgentWorkspaceView MemoryWindowView WikiBrowserPanel; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`

## task-08: Clean Up Visual Hierarchy And Layout Density

Goal:
Make the UI feel like a polished desktop product, not a status console.

Why eighth:
After workflows exist, visual design must make them readable and attractive.

Files:
- `apps/desktop/src/styles.css`
- `apps/desktop/src/styles/theme.css`
- `apps/desktop/src/views/*.tsx`
- `apps/desktop/src/components/layout.tsx`

Implementation:
- Reduce nested panels on primary screens.
- Keep settings/diagnostics dense, but make product pages action-led.
- Use clear section hierarchy:
  - Primary action
  - Current artifacts
  - History/activity
  - Advanced details
- Ensure button/card text does not overflow.
- Avoid making every section look like the same dashboard card.
- Keep cards at 8px radius or less unless local design requires otherwise.

Acceptance:
- First viewport on each main route shows one clear primary action.
- Text and controls do not overlap.
- Pages do not feel like configuration unless they are settings pages.

Verify:
- `Push-Location apps\desktop; npm run test -- App StageView ChatWindowView AgentWorkspaceView MemoryWindowView; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`
- Browser visual checks for `#/stage`, `#/chat`, `#/agent`, `#/memory`, `#/world`, `#/settings`.

## task-09: Expand Pet Window Shortcuts Into Core Feature Access

Goal:
Make the pet window feel interactive and capable in compact mode.

Why ninth:
The pet window is a key product differentiator, but it currently exposes too few features.

Files:
- `apps/desktop/src/App.tsx`
- `apps/desktop/src/features/chat/PetChatOverlay.tsx`
- `apps/desktop/src/features/chat/petInputModes.ts`
- `apps/desktop/pet-hitbox.json`
- `apps/desktop/src/styles.css`

Implementation:
- Expand pet shortcuts to include:
  - Chat
  - Task
  - Memory
  - Wiki
  - Review
  - Settings
- Shortcut actions should open appropriate stage routes or compact inputs.
- If hitbox size changes, update `pet-hitbox.json`.
- Keep compact reply bubble text-only.

Acceptance:
- User can access core features from pet window.
- Shortcut hit areas remain reliable.
- No UI overlap in pet mode.

Verify:
- `Push-Location apps\desktop; npm run test -- App PetChatOverlay petInputModes; Pop-Location`
- `Push-Location apps\desktop; npm run pet:bubble:check; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`

## task-10: Surface Agent Collaboration As Transparency, Not Feature Count

Goal:
Stop presenting "9 agents" as product value. Present them as internal specialists behind real outcomes.

Why tenth:
Only after real user-facing features exist should agent framing be cleaned up.

Files:
- `apps/desktop/src/features/chat/ChatAgentActionSummary.tsx`
- `apps/desktop/src/services/agentActivity.ts`
- `apps/desktop/src/features/settings/ModelHealthBanner.tsx`
- `apps/desktop/src/features/settings/SettingsPanel.tsx`
- `apps/desktop/src/services/agentModelDrafts.ts`
- `apps/backend/app/models/diagnostics.py`

Implementation:
- Add an expandable "AI team activity" section only where useful.
- Map internal agents to outcomes:
  - Task agent -> task/reminder
  - Wiki manager -> knowledge page
  - Memory proposal -> memory review
  - Retrieval agents -> cited answer
  - Continuity agent -> relationship/state continuity
- Keep per-agent model config under Advanced settings.
- Do not claim "9 agents = 9 features".

Acceptance:
- Users understand agents as internal specialists.
- Product value is expressed through task/memory/wiki/review/chat outcomes.

Verify:
- `Push-Location apps\desktop; npm run test -- SettingsPanel ChatAgentActionSummary; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`

## task-11: Improve Chat Latency Perception And Answer-Only Streaming

Goal:
Reduce the feeling that chat is slow and noisy.

Why eleventh:
After core features are visible, chat should feel clean and responsive.

Files:
- `apps/desktop/src/App.tsx`
- `apps/desktop/src/features/chat/usePetChatBubble.ts`
- `apps/desktop/src/features/chat/streamDispatcher.ts`
- `apps/desktop/src/features/chat/handlers/statusHandler.ts`
- `apps/desktop/src/features/chat/ChatMessageList.tsx`

Implementation:
- Hide system/tool/status events by default.
- Show answer text first.
- Use short friendly loading states.
- Show artifact progress cards for long operations.
- Avoid repeatedly changing bubble text before final response.

Acceptance:
- User sees final answer and artifacts, not system prompts.
- Long operations show meaningful progress without noisy logs.
- Pet bubble remains clean and text-only.

Verify:
- `Push-Location apps\desktop; npm run test -- ChatMessageList PetChatOverlay usePetChatBubble; Pop-Location`
- `Push-Location apps\desktop; npm run pet:bubble:check; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`

## task-12: Add Product Acceptance Tests For "Not Just Chat"

Goal:
Prevent future regressions where the app again feels like only chat.

Why twelfth:
After feature work is implemented, lock the product behavior with tests.

Files:
- `apps/desktop/src/App.test.tsx`
- `apps/desktop/src/views/StageView.test.tsx`
- `apps/desktop/src/views/AgentWorkspaceView.test.tsx`
- `apps/desktop/src/views/MemoryWindowView.test.tsx`
- `apps/desktop/src/features/wiki/WikiTerminology.test.tsx`
- `apps/desktop/src/features/wiki/WikiWorkflowPanel.tsx`

Implementation:
- Add tests asserting:
  - Stage shows feature quick actions.
  - Task page creates task directly.
  - Memory page has direct search/add/review controls.
  - Wiki page exposes daily organize flow before advanced maintenance.
  - Review can be generated without chat.
- Add negative tests:
  - Core functions are not only reachable through chat.
  - System traces are not visible by default.

Acceptance:
- Tests fail if task/memory/wiki/review entry points are removed.
- Tests fail if system traces become default visible UI again.

Verify:
- `Push-Location apps\desktop; npm run test -- App StageView AgentWorkspaceView MemoryWindowView WikiWorkflowPanel; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`

## task-13: Final Product IA And Copy Pass

Goal:
After the core functionality exists, clean labels, hierarchy, and product framing.

Why last:
Renaming before real features exist only hides the problem. Final IA should match implemented workflows.

Files:
- `apps/desktop/src/views/navigation.ts`
- `apps/desktop/src/App.tsx`
- `apps/desktop/src/views/*.tsx`
- `apps/desktop/src/features/settings/SettingsPanel.tsx`
- `apps/desktop/src/services/agentModelDrafts.ts`

Implementation:
- Finalize navigation labels around user jobs.
- Remove or demote "9 agents" from primary marketing/product copy.
- Ensure page titles match actual features:
  - Stage / Home
  - Chat
  - Tasks
  - Memory
  - Knowledge
  - Review if split out
  - Settings
- Make empty states concise and action-oriented.

Acceptance:
- First-time users can identify at least five distinct product features from the first screen and navigation.
- Product copy describes outcomes, not implementation internals.
- Advanced technical details remain discoverable but not dominant.

Verify:
- `Push-Location apps\desktop; npm run test -- App ChatWindowView StageView; Pop-Location`
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`
- Browser visual check for all main routes.

## Global Definition Of Done

- The app no longer depends on "9 agents" as a user-facing feature claim.
- Stage, Task, Memory, Wiki, and Review each have an obvious primary action.
- Chat can still orchestrate work, but it is not the only place work can begin.
- Every core feature produces visible artifacts or manageable records.
- Focused tests and TypeScript checks pass.
- Browser visual checks confirm first viewport clarity for each main route.
