# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Agent Pet is a local-first Windows desktop agent pet with transparent long-term memory backed by an Obsidian/Vault-style Markdown folder. The current implementation is split into:

- `apps/backend`: Python FastAPI sidecar with SQLite, FTS5, LangGraph/LangChain agent runtime, memory, task, settings, diagnostics, and Vault services.
- `apps/desktop`: Electron + React + Vite desktop shell, control console, Live2D pet rendering, preload IPC, and managed backend sidecar lifecycle.
- `scripts`: Windows PowerShell development, preflight, smoke, and acceptance-gap scripts.
- `docs`: runbooks and implementation notes. `Development_Documentation.md` is the authoritative product/engineering spec, but current code and automated validation are the runtime source of truth.

## Common Commands

Run repository-level PowerShell scripts from `E:\agentproject` unless noted otherwise.

### Install

```powershell
Push-Location E:\agentproject\apps\backend
python -m pip install -e ".[dev]"
Pop-Location

Push-Location E:\agentproject\apps\desktop
npm install
Pop-Location
```

### Backend

```powershell
.\scripts\dev-backend.ps1 -Port 8765
.\scripts\test-backend.ps1
```

Equivalent direct test commands:

```powershell
Push-Location E:\agentproject\apps\backend
python -m pytest
python -m pytest tests/test_tasks_services.py::test_create_task_converts_local_times_to_utc_and_schedules_reminder
Pop-Location
```

### Desktop

```powershell
.\scripts\dev-frontend.ps1 -Port 5173

Push-Location E:\agentproject\apps\desktop
npm run electron:dev
npm run typecheck
npm run build
npm run package:check
npm run live2d:check:public
npm run live2d:sdk:check
Pop-Location
```

There is no dedicated desktop lint script in `package.json`; use `typecheck`, `build`, `package:check`, and Live2D checks as the primary desktop gates.

### Smoke and Acceptance

```powershell
.\scripts\preflight-windows.ps1
.\scripts\runbook-smoke.ps1 -Port 8766
.\scripts\check-mvp-acceptance-gap.ps1
```

The smoke script creates an isolated `.tmp\runbook-smoke-<timestamp>` trial directory, starts its own backend, validates core API flows, then stops the backend. Do not point smoke `-WorkDir` at a real Vault unless intentionally testing against a backup/copy.

## Architecture Notes

- Backend app creation happens in `apps/backend/app/main.py`. It initializes SQLite, migrations/services, reminders, request IDs, CORS, error handlers, and mounted API routes.
- Backend routes are collected under `apps/backend/app/api`. `/api/health` is public; protected `/api` routes require `Authorization: Bearer <token>`.
- SQLite storage lives behind `apps/backend/app/storage`, with migrations in `apps/backend/migrations`. The backend uses WAL and stores app state, tasks, conversations, indexed note metadata, proposals, and audit-style records.
- Agent orchestration lives in `apps/backend/app/agents/runtime.py`. The runtime routes chat, memory search, memory proposals, Vault maintenance proposals, task creation, reminders, diagnostics, and continuity events.
- The Electron main process in `apps/desktop/electron/main.cjs` manages windows, tray, notifications, mouse passthrough, the Python sidecar process, and the session token passed via environment variables.
- The React renderer starts in `apps/desktop/src/App.tsx`. API access is centralized through frontend services such as `ApiClient`/desktop IPC wrappers rather than direct ad hoc fetches.
- Live2D uses Vite/TypeScript aliases for Cubism SDK vendor code and model resources under `apps/desktop/public/live2d`. Validate both public and dist assets when touching Live2D or packaging paths.

## Product and Safety Constraints

- User-facing UI and errors are primarily Chinese. Backend chat behavior should remain natural, concise, warm, and Chinese by default.
- Long-term memory and Vault/Markdown writes must go through preview/review/confirmation flows. Do not add paths that write user Markdown files directly from chat or background automation without explicit confirmation.
- `Wiki` remains in some internal API/type names for historical reasons. User-facing text should prefer Vault maintenance, long-term memory maintenance, or archive/query wording.
- The default knowledge-base paths `Inbox/Pending Memories.md` and `Memories/` are intentionally English and should not be treated as localization defects.
- Protected API calls require the session bearer token. Development scripts may default to `dev-token`, but production sidecar token passing should stay in environment variables, not command-line arguments.
- `.tmp` is only for disposable local trial artifacts; do not treat it as the user's required knowledge-base path.
