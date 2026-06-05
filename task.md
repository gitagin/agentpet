# Agent Task: Harden Desktop Security Boundaries and Runtime Diagnostics

You are the coding agent taking over `E:\agentproject`.
Follow the root `AGENTS.md` first. If this task conflicts with a closer `AGENTS.md`, follow the closer file.

This task is meant to be directly executable by an agent. Read the relevant code first, make scoped changes, add tests, run verification, and report every command with full output.

## Context

The project is a Windows local-first desktop AI companion:

- Backend: Python FastAPI sidecar.
- Desktop: Electron + React + TypeScript + Vite.
- Storage: local SQLite plus an Obsidian/Markdown Vault.

Recent review found that the baseline is decent, but several promises are stronger in docs/tests than in runtime enforcement:

- Electron IPC exposes broad capabilities without enough `event.sender` authorization.
- Electron proxy auto-injects the backend bearer token for renderer-originated `/api/` requests, but does not have a route/method allowlist.
- Vault init/bind is documented as a high-risk operation requiring confirmation, but the backend API does not appear to enforce explicit confirmation.
- Runtime user-facing strings contain mojibake in several files.
- Project docs may contain stale environment facts, for example claiming the workspace is not a Git repository when the current checkout may contain `.git`.

## Goal

Harden Electron IPC and API proxy boundaries, enforce backend confirmation for high-risk Vault binding, clean runtime mojibake, and add regression tests.

Keep changes narrow. Do not refactor unrelated code.

## Hard Constraints

1. Do not modify generated or local-state paths:
   - `apps/desktop/node_modules/`
   - `apps/desktop/dist/`
   - `apps/desktop/release/`
   - `apps/backend/pytest-of-ASUS/`
   - `.tmp/`
   - `.idea/`
   - `.codex/`
   - `*.db`, `*.sqlite3`, `logs/`
2. Do not write to a real user Vault.
3. Do not delete, move, or batch rewrite Vault Markdown.
4. Do not log or expose real tokens, API keys, private keys, or complete Authorization headers.
5. Renderer code must not directly use Node, FS, or child_process.
6. Renderer code must not read or expose `AGENT_PET_SESSION_TOKEN`, `Authorization`, or `Bearer` secrets.
7. Use `contextBridge` IPC for desktop capabilities.
8. Do not mark docs as `Covered` unless the implementation is verified.
9. If user changes already exist, do not revert them. Read and work with them.

## Phase 1: Add IPC Sender Authorization

Inspect and update as needed:

- `apps/desktop/electron/ipc.js`
- `apps/desktop/electron/windows.js`
- `apps/desktop/electron/ipc.test.cjs`
- `apps/desktop/electron/windows.test.cjs`

Implement centralized sender role/permission checks.

Suggested shape:

- Add or expose a helper such as `windows.getSenderWindowRole(webContents)`.
- Add an `assertTrustedSender(event.sender, allowedRoles)` helper in `ipc.js`, or equivalent.
- Return a stable rejected result or throw a stable error for unauthorized calls.

Protect at least these IPC channels:

- `agent-pet:api-request`
- `agent-pet:sse-start`
- `agent-pet:sse-cancel`
- `agent-pet:select-knowledge-base-folder`
- `app:quit`
- `window:open-agent`
- `window:close-agent`
- `window:open-stage`
- `window:open-feature`

Suggested policy:

- `pet`: may control pet-specific UI and open safe app windows.
- `control`, `stage`, `agent`, `feature`: may use normal API/SSE capabilities.
- Knowledge-base folder selection should only be callable from control/stage/settings-like windows.
- `app:quit` should only be callable from a trusted app window that actually owns quit UI.
- Unknown senders must be denied.

Tests:

- Unknown sender calling sensitive IPC is denied.
- Valid sender calling sensitive IPC succeeds.
- Existing pet-only operations remain pet-only.

## Phase 2: Add API Proxy Allowlist

Inspect and update:

- `apps/desktop/electron/proxy.js`
- `apps/desktop/electron/ipc.js`
- `apps/desktop/electron/ipc.test.cjs`
- Optionally add `apps/desktop/electron/proxy.test.cjs`.
- If frontend paths need adjustment:
  - `apps/desktop/src/services/apiClient.ts`
  - `apps/desktop/src/services/desktopApi.ts`

Implement a path + HTTP method allowlist for renderer-originated proxy requests.

Requirements:

1. Renderer must not be able to call arbitrary `/api/...` paths through main.
2. Unknown API paths must be rejected by default.
3. The allowlist must include current UI needs.
4. Keep bearer token injection inside main/proxy only.
5. Continue stripping renderer-provided forbidden headers:
   - `Authorization`
   - `Cookie`
   - `Host`
   - `Origin`
   - `Referer`

Pay special attention to high-risk APIs:

- Vault bind/init/index.
- Wiki write/repair/archive/synthesize.
- Task state mutation.
- Settings mutations involving model endpoints, TTS providers, credentials, or external endpoints.

Tests:

- Allowed GET path succeeds.
- Unknown `/api/...` path is rejected.
- Forbidden renderer headers are stripped.
- If `auth: false` is kept, its purpose must be tested and documented in code. Otherwise remove it.

## Phase 3: Enforce Confirmation for Vault Bind

Inspect and update:

- `apps/backend/app/api/vaults.py`
- `apps/backend/app/models/api.py`
- `apps/backend/tests/test_security_contracts_api.py`
- `apps/backend/tests/test_storage_paths.py`
- Any existing Vault API tests.
- Desktop UI/API call sites that trigger Vault binding.

Backend must enforce explicit confirmation for:

- `POST /api/vaults/init`
- `POST /api/vaults/bind`

Suggested API field:

- `confirmed: true`

Alternative acceptable API:

- `confirmation_text: "BIND_VAULT"`

Requirements:

1. Missing confirmation must fail with a stable error code, for example `vault_bind_confirmation_required`.
2. Confirmation cannot be disabled by a setting.
3. Illegal paths must still fail even when confirmation is present.
4. Audit logs should distinguish:
   - denied: missing confirmation
   - denied: invalid path
   - failed: bind process exception
   - success: bind completed

Tests:

- Bind/init without confirmation fails.
- Bind/init with confirmation and legal path succeeds.
- Bind/init with confirmation and illegal path fails.
- Audit log records the correct result/reason.

## Phase 4: Clean Runtime Mojibake

Inspect at least:

- `apps/backend/app/auth.py`
- `apps/backend/app/api/vaults.py`
- `apps/desktop/electron/proxy.js`
- `apps/desktop/electron/ipc.js`
- `apps/desktop/electron/windows.js`
- `apps/desktop/src/services/sse.ts`

Fix user-facing mojibake strings in runtime code:

- Error messages.
- Dialog titles.
- Window titles.
- Status text.

Use clear Chinese if surrounding UI is Chinese. Use English only if the surrounding module is already English-facing.

Do not bulk-rewrite historical docs or vendor files.

Add a small regression guard for obvious mojibake in runtime-owned files. It can be part of an existing validation script or a focused test.

Suggested suspicious fragments:

- `閫`
- `涓`
- `鐭`
- `浼`
- `鏃`
- `鍙`
- `娴`

Do not scan `vendor/`, `node_modules/`, `dist/`, or generated output.

## Phase 5: Fix Documentation Drift

Inspect:

- `AGENTS.md`
- `docs/runbook.md`
- `docs/mvp-acceptance-coverage.md`
- `progress.md` is read-only unless you are explicitly acting as Coordinator.

Requirements:

1. If docs claim the workspace is not a Git repository, replace that with a verifiable statement, such as:
   - "Do not rely on Git being available; check the current workspace before using Git-based status."
2. Do not mark anything `Covered` without verified implementation and command output.
3. If acceptance docs are changed, run the acceptance consistency check.

## Suggested Execution Order

1. Read the relevant Electron and backend files.
2. Implement Phase 1 and add Electron IPC tests.
3. Implement Phase 2 and add proxy tests.
4. Implement Phase 3 and add backend tests.
5. Clean runtime mojibake and add a guard.
6. Fix documentation drift.
7. Run verification commands.
8. Report all command outputs.

## Required Verification

Run these when relevant to your changes:

```powershell
Push-Location apps\desktop; node --check electron\main.cjs; node --check electron\preload.cjs; node --check electron\ipc.js; node --check electron\proxy.js; Pop-Location
```

```powershell
Push-Location apps\desktop; node scripts\validate-electron-migration.mjs; Pop-Location
```

```powershell
Push-Location apps\desktop; npm run typecheck; Pop-Location
```

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_security_contracts_api.py tests/test_storage_paths.py; Pop-Location
```

If backend API routing or MVP contracts changed:

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_api_wiring_mvp.py tests/test_e2e_backend_mvp.py tests/test_security_hardening_mvp.py; Pop-Location
```

If acceptance docs changed:

```powershell
.\scripts\check-mvp-acceptance-gap.ps1
```

## Acceptance Criteria

The task is complete only when:

- Unauthorized senders cannot call sensitive IPC handlers.
- Renderer cannot call unlisted `/api/...` paths through Electron proxy.
- Vault bind/init without explicit confirmation is rejected by backend.
- Runtime-owned user-facing strings no longer contain obvious mojibake.
- Tests cover the new security behavior.
- Electron migration validation passes.
- No forbidden path was modified.
- Final response lists all commands actually run and full outputs.

## Final Response Format

Use this structure:

1. `Completed`: concise summary of changes.
2. `Verification`: every command run with full output.
3. `Risks / Follow-up`: remaining gaps or manual checks.
4. `Changed files`: key file paths.
