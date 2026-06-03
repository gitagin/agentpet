# Electron UX Improvement Task Instructions

This file is for future coding agents working in `E:\agentproject`. It turns the 2026-06-03 real Electron user-experience walkthrough into executable tasks.

Follow `AGENTS.md` first. Do not edit generated artifacts, do not write `progress.md`, and do not reveal or log any real token/API key.

## Execution Rules

1. Reproduce each issue through the real Electron desktop UI before editing code.
2. Start from the default pet window. A new user only sees the floating pet first.
3. Model configuration and Vault/memory-library configuration already exist. Do not reset local state and do not ask the user to configure them again.
4. Do not delete, move, or bulk rewrite Vault Markdown, SQLite, migration files, or local-state/schema files without explicit user confirmation.
5. Renderer desktop capability must continue to use contextBridge IPC. Do not let renderer read tokens or call Node/FS directly.
6. Do not mark anything Covered unless the implementation was verified.
7. After Electron validation, stop the dev session started by the agent and run the leftover process check.

## Baseline Validation Flow

Run before and after Electron validation:

```powershell
.\scripts\check-trial-processes.ps1
```

Start Electron:

```powershell
Push-Location apps\desktop; npm run electron:dev; Pop-Location
```

Manual UI path:

1. Wait for the default pet window.
2. Right-click the pet model and confirm the shortcut buttons appear.
3. Open the main stage from the pet shortcuts.
4. Skip model and Vault setup.
5. Send one non-sensitive ordinary chat message.
6. Inspect Chat, Organize, Knowledge Base, and Tasks.
7. Stop the Electron dev session started for validation.
8. Run `.\scripts\check-trial-processes.ps1` again.

## UX-01 Pet Entry Discoverability And Hitbox

Observed issue:

- The default pet window can look transparent or visually weak, with the background app showing through.
- A coordinate right-click on the visible pet area once passed through to the window behind it.
- A new user has no visible clue that right-clicking the pet opens features.

Target outcome:

- The pet model is clearly visible after launch.
- The visible pet/model area matches the interactive hitbox.
- A new user can discover the shortcut entry without documentation.

Implementation guidance:

- Add a lightweight first-run hint, for example "Right-click me to open features".
- Consider allowing left-click or double-click on the model to expand shortcuts, while keeping right-click.
- Fix any mismatch between pet visual position and hitbox/pass-through logic.
- Keep click-through only for truly transparent non-interactive areas.

Acceptance criteria:

- Electron starts with a visible pet model.
- Right-clicking the model once shows shortcut buttons: Pet, Chat, Tasks, Settings, Exit.
- Right-clicking the visible model area does not hit the app behind the pet window.
- Clicking the Pet shortcut opens the main stage.

Suggested verification:

```powershell
Push-Location apps\desktop; npm run pet:bubble:check; Pop-Location
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

Manual verification must use the Electron UI and desktop screenshots.

## UX-02 Chat Page First-Screen Continuity

Observed issue:

- After a user chats on the main stage, opening the Chat page still shows the first-use onboarding card first.
- The just-sent user message and assistant reply are below the fold.
- With an active Vault already present, the onboarding card feels like incomplete setup.

Target outcome:

- If there is an active Vault or any chat history, the Chat page prioritizes recent conversation.
- The onboarding card is collapsed, secondary, or clearly optional.
- A user who just chatted can immediately see that conversation on the Chat page.

Acceptance criteria:

- After one successful chat, clicking Chat shows the latest user message and assistant reply in the first viewport.
- The onboarding card does not block the recent conversation.
- The active Vault state does not imply the user must configure Vault again.

Suggested verification:

```powershell
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

Manual verification must include one real Electron chat round.

## UX-03 Reply Bubble Pagination

Observed issue:

- The stage reply bubble auto-advanced to page `2/2`, making page 1 easy to miss.
- The "auto paging" behavior feels uncertain for short replies.

Target outcome:

- Users should not miss the first page of an assistant reply.
- Page controls should make it obvious how to go forward/back.
- Short replies should avoid pagination where possible.

Acceptance criteria:

- A short one-sentence reply displays in a single bubble page.
- Multi-page replies stay on page 1 long enough to read and support manual back/forward navigation.
- The Chat page still contains the full reply text.

Suggested verification:

```powershell
Push-Location apps\desktop; npm run pet:bubble:check; Pop-Location
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

## UX-04 Humanize Auto Organization Status

Observed issue:

- The Organize page exposes raw/English status text such as `Skipped automatic organization` and `automation_disabled`.
- A normal user cannot tell whether this is an error, a normal skip, or a setting they should change.

Target outcome:

- Main status text uses normal product language.
- If automatic organization is disabled, show a clear reason and next action.
- Keep audit details available in secondary detail text.

Acceptance criteria:

- Raw status codes are not used as primary UI copy.
- Disabled automation explains what happened and where to enable it.
- "Skipped", "nothing to save", and "needs confirmation" are visually and textually distinct.

Suggested verification:

```powershell
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

Manual Electron validation must inspect the Organize page after one chat.

## UX-05 Knowledge Page Terminology

Observed issue:

- The Knowledge Base page uses developer-facing terms such as `VAULT / WIKI`, `query archive`, and `lint`.
- These terms break the first-time user experience.

Target outcome:

- First-screen language uses product terms: Knowledge Base, knowledge pages, update log, read-only check, query history.
- Technical terms appear only in advanced maintenance or details.
- Advanced maintenance stays collapsed by default.

Acceptance criteria:

- The Knowledge Base first viewport does not use `query archive` or `lint` as primary headings.
- `VAULT / WIKI` is replaced by user-facing wording.
- Read-only checks and advanced maintenance still communicate risk clearly.

Suggested verification:

```powershell
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

## UX-06 Task Empty State And Polling

Observed issue:

- With no current task, the Tasks page still shows a green "completed" badge next to the empty state.
- Terminal logs show frequent repeated task requests, especially `GET /api/tasks`.

Target outcome:

- Empty task state does not show misleading completion status.
- Task polling is controlled and old timers/subscriptions are cleaned up when pages change.
- Empty state should not generate noisy repeated backend requests.

Acceptance criteria:

- With no current task, the UI says "idle" or simply shows an empty state, not "completed".
- Staying on Tasks for 30 seconds does not produce abnormal repeated `GET /api/tasks` logs.
- Switching between pages does not stack task polling.

Suggested verification:

```powershell
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

Manual verification:

1. Open Electron.
2. Visit Tasks and wait 30 seconds.
3. Switch to other pages and back to Tasks.
4. Inspect terminal logs for repeated polling growth.

## Final Report Requirements

The final response from the executing agent must include:

- Changed file list.
- Completion status for every UX task: Covered / Partial / Gap.
- Every command actually run and its output.
- The real Electron UI validation path.
- Any unverified item and why it remains unverified.

