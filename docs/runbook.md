# Local Trial Runbook

This runbook covers the current Windows developer-machine trial for the backend sidecar, Electron desktop shell, core console workflow, smoke endpoints, and environment variables. Run commands from the repository root unless a step says otherwise.

## Current Trial Focus

The local trial is considered runnable when the core loop works:

- Backend sidecar starts locally, passes the one-key smoke chain, and stops without leaving a trial `uvicorn` process.
- Electron starts, shows the desktop-pet shell, and can open the control console.
- The control console supports health check, model configuration test, Vault initialization/status, indexing/search, memory proposal actions, task actions, Chat SSE tool-event visibility, and diagnostics export.
- `scripts\smoke-backend.ps1` covers `/api/health`, authorization, `/api/vaults/init`, `/api/memory/search`, memory proposal confirm/reject, `/api/tasks`, `/api/chat`, and `/api/diagnostics/export`.

Do not expand this gate into desktop-pet visual polish, blank-area mouse passthrough, sprite-pet animation quality, edge snapping, lip sync, voice, multiple characters, complex action queues, installer delivery, tray notification polish, or auto-update behavior. Record those as out-of-scope UI observations unless they prevent opening or using the control console.

## Core Trial Steps

Use this short path for routine QA:

```powershell
.\scripts\check-trial-processes.ps1
.\scripts\preflight-windows.ps1
.\scripts\runbook-smoke.ps1 -Port 8766
Push-Location .\apps\desktop
npm run typecheck
npm run package:check
npm run sprite-pet:check
npm run build
npm run sprite-pet:check:dist
npm run electron:dev
Pop-Location
.\scripts\check-trial-processes.ps1
```

`npm run build` is the production renderer build gate. The Codex sandbox can fail it with Vite/esbuild `spawn EPERM`; rerun the same command in normal Windows PowerShell before treating `dist` as refreshed.

## Test Directories

`.\.tmp` is only a temporary artifact folder for local trial runs. It is not the required user knowledge-base path.

| Scenario | Recommended path | Notes |
| --- | --- | --- |
| One-key runbook smoke | `.\.tmp\runbook-smoke-<timestamp>` | Created by `scripts\runbook-smoke.ps1`. |
| Manual backend smoke | `.\.tmp\manual-v0.1-smoke` | Use with `scripts\smoke-backend.ps1 -WorkDir ...`. |
| Manual Vault practice | `.\.tmp\PetMemoryVault` | Disposable local test Vault. |
| User folder trial | Any writable user directory or Obsidian Vault copy | Use a backup/copy for real notes. |

Do not point `-WorkDir` at a real Vault unless the goal is a controlled trial on a backed-up test Vault.

## Memory Paths

The customer-facing UI must be Chinese, but knowledge-base file paths are not required to be Chinese. The repository intentionally uses English default paths so the Electron UI, backend init template, chat-created memory proposals, smoke scripts, and tests stay aligned:

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

For the local trial, occupied ports are handled as follows:

- If `127.0.0.1:8765/api/health` responds, Electron can reuse the existing backend. If protected APIs return `401`, stop the existing backend and restart Electron so the session token matches.
- If `127.0.0.1:5173` is occupied, `electron/dev.mjs` can choose the next available Vite port.
- Unknown occupied ports should still be treated as trial risks.

To check only for leftover uvicorn/Electron trial processes and default trial listeners:

```powershell
.\scripts\check-trial-processes.ps1
```

The checker is read-only. It reports leftover `uvicorn app.main:app`, workspace Electron processes, and default trial listeners. Use it before and after manual Electron trial runs. The phrase `leftover uvicorn/Electron` is the expected cleanup concept for this runbook.

From `apps\desktop`, the same preflight is available through npm:

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

Equivalent direct command from `apps\backend`:

```powershell
Push-Location .\apps\backend
$env:AGENT_PET_SESSION_TOKEN = "dev-token"
$env:AGENT_PET_SQLITE_PATH = "..\..\.tmp\agent-pet-dev.sqlite3"
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
Push-Location .\apps\desktop
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

## 30-Second Companion Demo

Use this path when recording or reviewing the product loop. The setup isolates demo state from real notes and local app data; the recording itself should only show the pet/chat surface, one message, the assistant reply, the memory receipt, and either `查看记忆` or `撤回`.

Prepare isolated demo state from the repository root:

```powershell
New-Item -ItemType Directory -Force .\.tmp\PetMemoryDemoVault | Out-Null
$demoRoot = (Resolve-Path .\.tmp).Path
$env:AGENT_PET_SESSION_TOKEN = "dev-token"
$env:AGENT_PET_DATA_DIR = Join-Path $demoRoot "agent-pet-demo-data"
$env:AGENT_PET_SQLITE_PATH = Join-Path $demoRoot "agent-pet-demo.sqlite3"
```

Start Electron from the same shell so the managed sidecar inherits those variables, and keep it running:

```powershell
Push-Location .\apps\desktop
npm run electron:dev
Pop-Location
```

If the demo database has not bound a test knowledge folder yet, open a second PowerShell from the repository root and initialize only the disposable folder:

```powershell
$headers = @{ Authorization = "Bearer dev-token" }
$demoVault = (Resolve-Path .\.tmp\PetMemoryDemoVault).Path
Invoke-RestMethod http://127.0.0.1:8765/api/vaults/init `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body (@{ path = $demoVault; create_if_missing = $true; confirmed = $true } | ConvertTo-Json)
```

Do not use a real personal Vault for this demo. If `127.0.0.1:8765` is already occupied, run `.\scripts\check-trial-processes.ps1` and decide manually whether the existing backend is yours before closing anything.

Record the 30-second story:

1. Open the pet chat surface.
2. Click `30 秒试走：记住演示内容`.
3. Click `发送`.
4. Wait for the assistant reply and the `这次我做了什么` receipt.
5. Click `查看记忆` to inspect the saved memory, or click `撤回` to prove the write is reversible.

The trial is only valid if the receipt comes from the real chat response and persisted action data. Do not replace it with screenshots, seeded DOM, or a mocked demo layer.

## Manual Local Chain

Use this chain when validating the developer-machine flow by hand:

1. Run `.\scripts\check-trial-processes.ps1`.
2. Run `.\scripts\preflight-windows.ps1`.
3. Run `.\scripts\runbook-smoke.ps1 -Port 8766`.
4. From `apps\desktop`, run `npm run build`.
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
.\scripts\smoke-backend.ps1 -BaseUrl http://127.0.0.1:8765 -SessionToken dev-token -WorkDir .\.tmp\manual-v0.1-smoke
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
Push-Location .\apps\backend
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
Push-Location .\apps\desktop
npm run typecheck
npm run package:check
npm run sprite-pet:check
npm run build
npm run sprite-pet:check:dist
Pop-Location
```

## Optional Live Provider Gate

Only run this gate when a real compatible provider is available. Never paste the real key into committed files or command logs.

```powershell
$env:LIVE_MODEL_BASE_URL = "https://example-compatible-provider/v1"
$env:LIVE_CHAT_MODEL = "model-name"
$env:LIVE_MODEL_API_KEY = "provider-key"

Push-Location apps\backend
python -m pytest -q tests/test_live_model_chat_acceptance.py -m live_model
Pop-Location
```

The gate must prove model test success, at least one non-empty chat token, a citation for indexed Vault content, one final `done`, and no provider key in logs, diagnostics, responses or test output. Missing `LIVE_*` variables are a skipped external gate, not a source failure.

## Manual Memory, Export, and Revert Gate

Use an isolated test Vault or a backed-up copy. Binding a real Vault, writing Markdown and reverting state require explicit user confirmation.

1. Start the current backend and Electron app and bind the verified test Vault.
2. Send a low-risk memory-worthy chat message; confirm chat completion, daily/structured archive and an `agent_actions` entry.
3. Open memory and confirm source, reason, risk, confidence/status and linked activity are visible.
4. Capture non-sensitive database/file state before revert.
5. Revert through the second confirmation dialog; capture database/file state after revert and confirm UI feedback.
6. Download the portable Markdown and JSON memory exports and inspect that both files are readable and omit secrets.
7. Record a failure case, or explicitly state that none was observed.

Until those observations exist, TASK-0102 remains skipped and TASK-0202 remains implemented without its manual export gate.

## Manual Vault and Wiki Gate

Still using the isolated or backed-up Vault:

1. Index test Markdown and confirm grounded chat citations.
2. Confirm diary, structured memory and relevant long-term recall.
3. Confirm low-risk Wiki organization writes only under `Wiki/`, records `agent_action`, updates index/log and exposes revert.
4. Disable automatic Wiki organization and confirm the same request becomes a confirmation item rather than a write.
5. Run ingest preview, review and selected-target apply; applied files must exactly match reviewed targets.
6. Run lint against a malformed test page and confirm it reports missing template/source/trigger/log/revision/link requirements without destructive unreviewed repair.
7. Open the result in Obsidian and verify navigation; record before/after and revert evidence without personal content.

## Recall Quality Human Gate

TASK-0503 cannot complete from synthetic fixtures alone. Collect at least 20 real dialogue samples after the isolated memory chain is available. Label each as over-recall, under-recall, stiff or natural; score relevance, naturalness, privacy/boundary handling and helpfulness from 1 to 5. Passing requires zero raw path/id/score/secret leakage, at least 80% natural or acceptable after revision, a follow-up action for every unsafe or over-recall case, and human sign-off.

## Out-of-scope UI Observations

Record these separately from the local trial gate:

- Desktop-pet blank area blocks underlying apps.
- Drag sticks to cursor or drifts.
- Sprite-pet halfbody is blank, layered overlays are misaligned, or pet-window sprite animation stutters.
- Hitbox or tray behavior feels rough.
- Lip sync, voice, multi-character switching, complex action queues, edge snapping, installer UX, notification polish, and auto-update are not current local-trial requirements.
