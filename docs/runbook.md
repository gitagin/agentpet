# Local LLM Wiki Trial Runbook

This runbook covers a local, single-user Windows trial of the Agent Pet LLM
Wiki and memory graph: the FastAPI sidecar, Electron shell, durable source and
memory lifecycle, graph evidence views, smoke endpoints and environment
variables. Run commands from the repository root unless a step says otherwise.

The ordinary chat path may stream directly from the configured model. That path
is not the product proof. A valid trial must exercise the durable loop:
`source -> candidate -> entity/fact/relation -> Wiki -> cited recall ->
correct/forget`, and must record the corresponding failure or no-evidence state.
SQLite is authoritative for entities, facts, lifecycle and receipts; Markdown
is the portable source/Wiki body; FTS is the default retrieval path; Kuzu and
Qdrant are rebuildable optional projections.

## Current Trial Focus

The local trial is runnable when the mechanism path works:

- Backend sidecar starts locally, passes the one-key smoke chain, and stops without leaving a trial `uvicorn` process.
- Electron starts, shows the desktop-pet shell, and can open the control console.
- The control console exposes health, model configuration, Vault binding,
  source indexing, graph/timeline/source memory views, task actions, Chat SSE
  status and diagnostics. A visible control does not prove that its provider,
  notification or projection completed successfully.
- `scripts\smoke-backend.ps1` covers the legacy core endpoints. The current
  graph and lifecycle contracts additionally require the focused tests and
  migration/fault scripts listed in `修改task.md` under LLMWIKI-003 through
  LLMWIKI-013.

Do not present this mechanism gate as 24x7 availability, business uplift,
enterprise tenancy, multi-agent autonomy, universal accuracy, or a packaged
release. Desktop-pet polish, Windows DPI, OS notification permission, sleep/
wake and clean-VM launch are separate gates and must remain `Partial` until
their named evidence exists.

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

`npm run build` is the renderer release-build gate. The Codex sandbox can fail it with Vite/esbuild `spawn EPERM`; rerun the same command in normal Windows PowerShell before treating `dist` as refreshed.

## Current LLM Wiki Evidence Commands

Run these commands against isolated data and keep each output directory. A
successful command proves only its named mechanism; `Partial` rows and skipped
external gates must remain in the report.

```powershell
$ErrorActionPreference = 'Stop'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-llmwiki-migration-smoke.ps1 -OutputDir output\verification\LLMWIKI-013\migration
if ($LASTEXITCODE -ne 0) { throw 'MIGRATION_GATE_FAILED' }

python scripts\verify_llmwiki_metrics.py `
  --fixture apps\backend\tests\evals\retrieval\retrieval-corpus-v1.json `
  --out output\verification\LLMWIKI-011\eval

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-llmwiki-fault-matrix.ps1 -OutputDir output\verification\LLMWIKI-013\faults
if ($LASTEXITCODE -ne 0) { throw 'FAULT_GATE_FAILED' }
```

For the visual gate, start the development renderer with an authenticated
backend and run:

```powershell
node scripts\verify-llmwiki-visual.mjs `
  --base-url http://127.0.0.1:5173/#memory `
  --out output\verification\LLMWIKI-009\visual
```

The current visual report is automatic browser evidence only. It does not
cover packaged Electron, Windows 100/125/150% DPI, sleep/wake or OS
notification permission. Do not replace a missing manual gate with a screenshot.

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

Never pass the session token as a packaged-sidecar command-line argument. Electron passes it through environment variables and exposes only the minimal preload/IPC contract required for API calls.

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

## Windows Packaged Runtime Verification

Build the frozen backend and unpacked Windows application before running the
runtime gates:

```powershell
Push-Location .\apps\desktop
npm run package:win:dir
Pop-Location
```

Verify the packaged frozen sidecar over 20 real start/stop cycles, followed by
an occupied-port fallback cycle:

```powershell
.\scripts\verify-frozen-sidecar-lifecycle.ps1 -Cycles 20
```

The script removes Python locations from the child `PATH`, checks `/api/health`,
asserts that no Python child process is created, stops the full process tree,
and verifies that every selected port is released. It writes the latest report
to `output\verification\frozen-sidecar-lifecycle.json`.

Verify the actual packaged Electron executable with port 8765 held by an
unrelated listener:

```powershell
.\scripts\verify-packaged-app-smoke.ps1
```

This gate starts `release\win-unpacked\Agent Pet.exe`, requires the packaged
sidecar to choose another port, checks its health and persisted log path, and
then verifies that the Electron and sidecar process trees are gone. The latest
report is `output\verification\packaged-app-smoke.json`.

## Interview Demo Preparation

Use this path to prepare disposable legacy smoke data. It is not a complete LLM
Wiki graph journey: the preparation command creates an isolated SQLite database
and Vault below `.tmp\agent-pet-demo`, then preloads diary, legacy facts, a
project note, tasks and auditable seed actions. It never reads or binds a real
personal Vault. The current interview journey must additionally create and
verify typed graph evidence through the real API as specified in
`docs/portfolio/demo-script.md`.

Prepare or explicitly recreate the isolated state from the repository root:

```powershell
.\scripts\prepare-demo.ps1
# Recreate only the disposable demo directory when needed:
.\scripts\prepare-demo.ps1 -Reset
```

As its first guard, the script checks `127.0.0.1:8765`. If anything is already listening there, preparation stops before deleting or seeding Demo state. Run `.\scripts\check-trial-processes.ps1`, identify the owner, and decide manually what to do; the Demo script never reuses or stops an existing backend.

After that guard passes, the script configures `AGENT_PET_DATA_DIR` and `AGENT_PET_SQLITE_PATH` for the current PowerShell process. It reuses an existing local session token or generates one when none is set, but never prints it. It does not save or print a model API key and does not start or stop any process.

Start Electron from that same PowerShell so its managed sidecar inherits the isolated paths and hidden session token:

```powershell
Push-Location .\apps\desktop
npm run electron:dev
Pop-Location
```

Before recording, open Settings in the isolated Demo and run the model
connection test. The seed script never copies a real API key or model
configuration. A passed connection test proves provider transport only; it does
not prove recall quality, graph correctness or business value. When the provider
is unavailable, keep the run as a failure demonstration and use local Wiki/FTS
browsing instead of presenting a successful model answer.

Use `docs/portfolio/demo-script.md` as the single demo story. It requires:

1. one immutable source and one explicit low-risk memory candidate;
2. activation into typed entity/fact/relation state with visible evidence;
3. cited recall in a new conversation;
4. correction or forget followed by a second recall check;
5. a no-evidence, provider-offline or degraded-projection pair;
6. one claim/receipt action with its recovery boundary;
7. the measured baseline, sample size and current `Partial` gates.

Do not substitute the chat fast path, a seeded DOM, screenshots or a provider
connection for this durable journey.

The trial is valid only when citations, receipts, tasks, confirmations, and ledger rows come from the real API and persisted isolated data. Do not replace them with seeded DOM, mocked success responses, or screenshots presented as live evidence.

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
13. Send `提醒我明天下午三点测试 Agent Pet` or `提醒我30分钟后测试 Agent Pet` and confirm the Chat task event and task list show reminder time, `北京时间`, and reminder status.
14. For a near-term reminder, wait until it is due and reload tasks; verify the
    durable reminder transition and display-attempt state. Do not record
    `display_attempted` as proof that Windows or the user received a notification.
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
- Due reminders can transition to `triggered` in backend state. Electron may
  attempt one system notification for each observed transition; permission
  denial or an unknown OS result must remain visible and retryable.
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

Current quality reconciliation:

```powershell
Push-Location apps\backend; python -m pytest -q; Pop-Location
Push-Location apps\desktop; npm run typecheck; Pop-Location
Push-Location apps\desktop; node scripts\validate-electron-migration.mjs; Pop-Location
.\scripts\check-mvp-acceptance-gap.ps1
```

The current exhaustive backend run is retained at
`output/verification/LLMWIKI-013/quality/backend-full-20260814-sharded.json`
with four non-overlapping shard logs and metadata beside it: `1193 passed,
2 skipped, 0 failed`, Mypy covered 213 source files and Ruff passed. Sharding
uses distinct `--basetemp` directories and disables the shared pytest cache;
the aggregate includes each of the `1195` collected tests one time. These checks do
not close packaged Electron,
Windows manual/DPI, real 24-hour or 7-day evidence gates; `LLMWIKI-013` remains
`Partial`.

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

Until those observations exist, memory export and revert remain `Partial` in
the current acceptance matrix. An older task status is not current evidence.

## Manual Vault and Wiki Gate

Still using the isolated or backed-up Vault:

1. Index test Markdown and confirm grounded chat citations.
2. Confirm diary, structured memory and relevant long-term recall.
3. Confirm low-risk Wiki organization writes only under `Wiki/`, records `agent_action`, updates index/log and exposes revert.
4. Disable automatic Wiki organization and confirm the same request becomes a confirmation item rather than a write.
5. Run ingest preview, review and selected-target apply; applied files must exactly match reviewed targets.
6. Run lint against malformed pages of at least two page types and confirm it
   reports missing source/trigger/log/revision/link requirements, empty
   placeholders and invalid citations without destructive unreviewed repair.
7. Open the result in Obsidian and verify navigation; record before/after and revert evidence without personal content.

## Optional Vector Retrieval Acceptance

FTS is the complete default local path. The `vector` dependency group is
an explicit opt-in and is not required to start the backend, index Markdown,
search, chat, manage memory, or run the backend test suite. CI job
`backend-base-install` installs `apps/backend` without extras, asserts that
`qdrant_client`, `langchain_qdrant`, and `kuzu` are absent, and then runs the
full non-live-model pytest suite.

The scale gate uses an actual Qdrant Server because the embedded Qdrant client
is a brute-force test implementation and cannot demonstrate HNSW behavior. Run
the same gate as CI against an isolated server:

```powershell
Push-Location apps/backend
python -m pip install -e ".[vector]"
python -m app.evals.vector_query_scaling `
  --qdrant-url http://127.0.0.1:6333 `
  --collection-sizes 2048 32768 `
  --dimensions 64 `
  --warmup-queries 20 `
  --measured-queries 80 `
  --output ../../output/evals/fix-backlog-16/vector-query-scaling.json
Pop-Location
```

The benchmark excludes collection construction, optimizer time, and the one
full generation-integrity validation. It measures the steady-state optional
`LangChainQdrantVectorIndex.search()` path, alternates small/large query order,
and passes only when the p95 latency-growth ratio is at most 65% of the linear
collection-size ratio. CI retains the JSON report as the
`fix-backlog-16-vector-query-scaling` artifact. This is performance evidence,
not a semantic-quality or vector-promotion claim.

## Recall Quality Human Gate

Synthetic fixtures cannot complete the recall-quality gate. For the current
single-user MVP, follow the preregistered 7-day protocol in `修改task.md` and
record the real numerator, denominator, sample size and evidence status for
recall, correction, forget, repeated explanation and failure. Fewer than 20
feedback observations must be reported as `evidence insufficient`. A broader
business claim requires a separate multi-user study; a single user cannot prove
general productivity or retention uplift.

## Out-of-scope UI Observations

Record these separately from the local trial gate:

- Desktop-pet blank area blocks underlying apps.
- Drag sticks to cursor or drifts.
- Sprite-pet halfbody is blank, layered overlays are misaligned, or pet-window sprite animation stutters.
- Hitbox or tray behavior feels rough.
- Lip sync, voice, multi-character switching, complex action queues, edge snapping, installer UX, notification polish, and auto-update are not current local-trial requirements.

## Public Demo Claim Boundary

The accepted demo uses isolated `.tmp` data and presents Agent Pet as a local
personal LLM Wiki and memory graph. It shows FTS-first cited retrieval, typed
entities/facts/relations, deterministic policy and lifecycle, a rebuildable
Kuzu projection, checkpoint decisions, and API-backed receipts. It must state
that ordinary chat can take a direct fast path and that model output never owns
permissions, writes, deletion or receipt verification.

`output/verification/LLMWIKI-013/visual/visual-report.json` is the current automated
development-browser evidence for graph/timeline/sources at 390, 1280, 1366 and
1920 widths. It is not packaged Electron, Windows DPI or manual failure-state
evidence. Do not present vector/hybrid retrieval or reranking as the default,
and do not claim a live-provider campaign, 24-hour availability, 7-day uplift,
clean-VM launch or physical DPI coverage. Approved wording and measured values
are indexed in `docs/portfolio/claim-evidence-index.md`.
