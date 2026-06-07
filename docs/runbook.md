# v0.1 Local Trial Runbook

This runbook covers the Windows developer-machine trial for the v0.1 backend sidecar, Electron desktop shell, core console workflow, smoke endpoints, and environment variables. Run commands from `E:\agentproject` unless a step says otherwise.

## Current v0.1 Trial Focus

v0.1 is accepted when the local core loop is runnable:

- Backend sidecar starts locally, passes the one-key smoke chain, and stops without leaving a trial `uvicorn` process.
- Electron starts, shows the desktop-pet shell, and can open the control console.
- The control console supports health check, model configuration test, Vault initialization/status, indexing/search, memory proposal actions, task actions, Chat SSE tool-event visibility, and diagnostics export.
- `scripts\smoke-backend.ps1` covers `/api/health`, authorization, `/api/vaults/init`, `/api/memory/search`, memory proposal confirm/reject, `/api/tasks`, `/api/chat`, and `/api/diagnostics/export`.

Do not expand the v0.1 gate into desktop-pet visual polish, blank-area mouse passthrough, Live2D animation quality, edge snapping, lip sync, voice, multiple characters, complex action queues, installer delivery, tray notification polish, or auto-update behavior. Record those only as post-v0.1 UI observations unless they prevent opening or using the control console.

## Core Trial Steps

Use this short path for routine QA:

```powershell
.\scripts\check-trial-processes.ps1
.\scripts\preflight-windows.ps1
.\scripts\runbook-smoke.ps1 -Port 8766
Push-Location E:\agentproject\apps\desktop
npm run typecheck
npm run package:check
npm run live2d:check:public
npm run live2d:sdk:check
npm run build
npm run live2d:check:dist
npm run live2d:sdk:check:dist
npm run electron:dev
Pop-Location
.\scripts\check-trial-processes.ps1
```

`npm run build` is the production renderer build gate. The Codex sandbox can fail it with Vite/esbuild `spawn EPERM`; rerun the same command in normal Windows PowerShell before treating `dist` as refreshed.

## Test Directories

`E:\agentproject\.tmp` is only a temporary artifact folder for local trial runs. It is not the required user knowledge-base path.

| Scenario | Recommended path | Notes |
| --- | --- | --- |
| One-key runbook smoke | `E:\agentproject\.tmp\runbook-smoke-<timestamp>` | Created by `scripts\runbook-smoke.ps1`. |
| Manual backend smoke | `E:\agentproject\.tmp\manual-v0.1-smoke` | Use with `scripts\smoke-backend.ps1 -WorkDir ...`. |
| Manual Vault practice | `E:\agentproject\.tmp\PetMemoryVault` | Disposable local test Vault. |
| User folder trial | Any writable user directory or Obsidian Vault copy | Use a backup/copy for real notes. |

Do not point `-WorkDir` at a real Vault unless the goal is a controlled trial on a backed-up test Vault.

## Memory Paths

The customer-facing UI must be Chinese, but knowledge-base file paths are not required to be Chinese. v0.1 intentionally uses English default paths so the Electron UI, backend init template, chat-created memory proposals, smoke scripts, and tests stay aligned:

```text
Inbox/Pending Memories.md
Memories/
```

Do not treat `Inbox/Pending Memories.md` as a localization defect. It is the default Markdown target path shown inside the Chinese memory proposal form.

## Windows Preflight

Run:

```powershell
.\scripts\preflight-windows.ps1
```

The preflight checks Python, backend dependencies, Node/npm, desktop dependencies, Electron runtime, Electron entrypoints, `AGENT_PET_SESSION_TOKEN` shell state, and leftover uvicorn/Electron processes.

For v0.1, occupied ports are handled as follows:

- If `127.0.0.1:8765/api/health` responds, Electron can reuse the existing backend. If protected APIs return `401`, stop the existing backend and restart Electron so the session token matches.
- If `127.0.0.1:5173` is occupied, `electron/dev.mjs` can choose the next available Vite port.
- Unknown occupied ports should still be treated as trial risks.

To check only for leftover uvicorn/Electron trial processes and default trial listeners:

```powershell
.\scripts\check-trial-processes.ps1
```

The checker is read-only. It reports leftover `uvicorn app.main:app`, workspace Electron processes, and default trial listeners. Use it before and after manual Electron trial runs. The phrase `leftover uvicorn/Electron` is the expected cleanup concept for this runbook.

From `E:\agentproject\apps\desktop`, the same preflight is available through npm:

```powershell
npm run preflight
```

## Environment Variables

| Variable | Required | Used by | Notes |
| --- | --- | --- | --- |
| `AGENT_PET_SESSION_TOKEN` | Yes for protected API calls | Backend, Electron main process, smoke scripts | Local bearer token. Development scripts may default to `dev-token`. |
| `AGENT_PET_MODEL_BASE_URL` | No | Backend | Development fallback only. Packaged apps should save the model service URL through the Settings panel. |
| `AGENT_PET_CHAT_MODEL` | No | Backend | Development fallback only. Packaged apps should save the chat model through the Settings panel. |
| `AGENT_PET_BACKEND_DIR` | No | Electron main process | Override managed sidecar directory. Must contain `app/main.py`. |
| `AGENT_PET_DATA_DIR` | No | Backend | Default app data directory when `AGENT_PET_SQLITE_PATH` is not set. |
| `AGENT_PET_SQLITE_PATH` | No | Backend | Explicit SQLite database path for isolated trials. |

Never pass the session token as a production sidecar command-line argument. Electron passes it through environment variables and exposes only the minimal preload/IPC contract required for API calls.

For packaged or customer-facing builds, configure the model from the control console Settings panel:

- `模型提供方`: usually `openai-compatible`.
- `服务地址`: for example `https://api.openai.com/v1` or a compatible provider endpoint.
- `模型名称`: for example `gpt-4o-mini` or the provider model id.
- `API 密钥`: stored by the local backend credential service.

After saving the configuration, click `试连模型`. A successful result confirms the saved service URL, model name, and local credential can produce a LangChain/OpenAI-compatible response. A failed result should show a Chinese reason such as missing key, authentication failure, unsupported model, timeout, or unreachable provider.

Environment variables remain a developer fallback and should not be the customer configuration path.

## Backend Start

Start the FastAPI sidecar:

```powershell
$env:AGENT_PET_SESSION_TOKEN = "dev-token"
$env:AGENT_PET_SQLITE_PATH = "$PWD\.tmp\agent-pet-dev.sqlite3"
.\scripts\dev-backend.ps1 -Port 8765
```

Equivalent direct command from `E:\agentproject\apps\backend`:

```powershell
Push-Location E:\agentproject\apps\backend
$env:AGENT_PET_SESSION_TOKEN = "dev-token"
$env:AGENT_PET_SQLITE_PATH = "E:\agentproject\.tmp\agent-pet-dev.sqlite3"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
Pop-Location
```

Expected:

- Uvicorn serves `http://127.0.0.1:8765`.
- `GET /api/health` returns `status: ok` without authorization.
- Protected routes require `Authorization: Bearer dev-token`.

## One-Key Backend Smoke

For an isolated backend smoke that starts and stops its own backend:

```powershell
.\scripts\runbook-smoke.ps1 -Port 8766
```

The script creates `.tmp\runbook-smoke-<timestamp>`, sets `AGENT_PET_SESSION_TOKEN`, points `AGENT_PET_SQLITE_PATH` at an isolated SQLite file, starts `uvicorn app.main:app`, waits for `/api/health`, then runs `scripts\smoke-backend.ps1`. After smoke completes, it stops the backend and verifies `/api/health` is no longer reachable.

Use `-KeepBackend` only when you intentionally want to inspect the spawned backend after smoke.

## Desktop Dev Run

Renderer-only development:

```powershell
.\scripts\dev-frontend.ps1 -Port 5173
```

Use:

- Backend URL: `http://127.0.0.1:8765`
- Session token: `dev-token`

Electron shell:

```powershell
Push-Location E:\agentproject\apps\desktop
npm run preflight
npm run electron:dev
Pop-Location
```

Expected Electron behavior:

- Desktop-pet shell appears.
- Control console can be opened from the pet menu, tray path if available, or keyboard shortcut.
- Electron starts or attaches to the loopback Python sidecar.
- Sidecar status and user-facing errors are shown in Chinese.
- Closing the control console hides it; exiting from the pet menu or tray exits the app and stops the managed sidecar.

## Manual v0.1 Chain

Use this chain when validating the developer-machine flow by hand:

1. Run `.\scripts\check-trial-processes.ps1`.
2. Run `.\scripts\preflight-windows.ps1`.
3. Run `.\scripts\runbook-smoke.ps1 -Port 8766`.
4. From `E:\agentproject\apps\desktop`, run `npm run build`.
5. Run `npm run electron:dev`.
6. Open the control console.
7. Run Health.
8. Save model provider, service URL, model name, and API key, then click `试连模型`.
9. Initialize a test Vault and trigger indexing.
10. Search known Markdown content.
11. Create, confirm, and reject memory proposals.
12. Create, complete, and cancel tasks.
13. Send `提醒我明天下午三点测试桌面记忆助手` or `提醒我30分钟后测试桌面记忆助手` and confirm the Chat task event and task list show reminder time, `北京时间`, and reminder status.
14. For a near-term reminder, wait until it is due and reload tasks; the backend should mark the reminder `triggered`, and Electron should show one system notification for that triggered reminder.
15. Send Chat messages that trigger search/memory/task behavior and confirm SSE status/tool events are visible in the UI.
16. Export diagnostics and confirm database, Vault, index jobs, tasks, and app state are visible.
17. Close Electron and run `.\scripts\check-trial-processes.ps1` again.

## Backend Smoke Test

If a backend is already running:

```powershell
.\scripts\smoke-backend.ps1 -BaseUrl http://127.0.0.1:8765 -SessionToken dev-token -WorkDir E:\agentproject\.tmp\manual-v0.1-smoke
```

The lower-level smoke verifies:

- Health endpoint is public and does not leak Vault/model state.
- Protected endpoints reject missing authorization.
- Vault init through `/api/vaults/init` and indexing through `/api/vaults/{vault_id}/index`.
- Memory search through `/api/memory/search` returns a citation for a known Markdown sentinel.
- Memory proposal confirm writes Markdown and reject leaves Markdown unchanged.
- Task create/list through `/api/tasks` works with reminder fields.
- Common Chinese reminder phrases such as `明天下午三点` and `30分钟后` are parsed into UTC reminder records.
- Beijing timezone aliases such as `北京时间`, `北京`, `Asia/Beijing`, and `Beijing` are accepted and stored internally as `Asia/Shanghai` while UI responses show `北京时间`.
- Due reminders can transition to `triggered` in backend state, and Electron sends one system notification for each triggered reminder observed by the desktop task refresh loop.
- Chat creation through `/api/chat` returns a stream URL and the SSE stream emits events.
- Diagnostics export through `/api/diagnostics/export` reports reachable database, configured Vault, recent index jobs, and smoke task counts.

## Manual Endpoint Checks

Health:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

Protected status:

```powershell
$headers = @{ Authorization = "Bearer dev-token" }
Invoke-RestMethod http://127.0.0.1:8765/api/vaults/status -Headers $headers
```

Model connection test:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/settings/model-test -Method Post -Headers $headers
```

Expected: the response never includes the API key. `status: ok` means the configured LangChain/OpenAI-compatible provider returned a usable response; `status: failed` includes a stable `error_code` and Chinese `message`.

Initialize a Vault:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/vaults/init `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body (@{ path = "$PWD\.tmp\PetMemoryVault"; create_if_missing = $true; confirmed = $true } | ConvertTo-Json)
```

## Verification Commands

Backend:

```powershell
.\scripts\test-backend.ps1
.\scripts\check-mvp-acceptance-gap.ps1
.\scripts\runbook-smoke.ps1 -Port 8766
```

Dual-track memory regression:

```powershell
Push-Location E:\agentproject\apps\backend
python -m pytest -q tests/test_memory_taxonomy.py tests/test_dual_track_memory_schema.py tests/test_immediate_understanding.py tests/test_memory_consolidation.py tests/test_memory_lifecycle.py tests/test_memory_activation.py tests/test_memory_permissions.py tests/test_memory_feedback_api.py tests/test_memory_hygiene.py tests/test_memory_pollution_regression.py tests/test_agent_runtime_chat.py tests/test_agent_runtime_retrieval.py tests/test_api_wiring_mvp.py
Pop-Location
```

Task 15 final reconciliation:

```powershell
Push-Location apps\backend; python -m pytest -q; Pop-Location
Push-Location apps\desktop; npm run typecheck; Pop-Location
Push-Location apps\desktop; node scripts\validate-electron-migration.mjs; Pop-Location
.\scripts\check-mvp-acceptance-gap.ps1
```

Desktop:

```powershell
Push-Location E:\agentproject\apps\desktop
npm run typecheck
npm run package:check
npm run live2d:check:public
npm run live2d:sdk:check
npm run build
npm run live2d:check:dist
npm run live2d:sdk:check:dist
Pop-Location
```

## Post-v0.1 UI Observations

Record these separately from the v0.1 gate:

- Desktop-pet blank area blocks underlying apps.
- Drag sticks to cursor or drifts.
- Live2D canvas is blank, static fallback appears, or animation stutters.
- Hitbox or tray behavior feels rough.
- Lip sync, voice, multi-character switching, complex action queues, edge snapping, installer UX, notification polish, and auto-update are not v0.1 requirements.
