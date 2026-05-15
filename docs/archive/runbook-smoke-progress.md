# Runbook Smoke Progress

Agent: E2E Smoke/Runbook Worker

Status: Completed

Implemented a one-key backend smoke path in `scripts\runbook-smoke.ps1`. It starts an isolated backend, waits for `/api/health`, initializes a temporary Vault, indexes Markdown, verifies memory search, confirms and rejects memory proposals, creates a task with reminder fields, and checks chat SSE events through `scripts\smoke-backend.ps1`. Cleanup now verifies the spawned backend exits and `/api/health` is no longer reachable.

Added read-only trial residue detection in `scripts\check-trial-processes.ps1` for leftover `uvicorn app.main:app`, workspace Electron processes, and default backend/frontend trial listeners. Windows preflight calls this checker before dependency and port checks.

Validation targets:

```powershell
Push-Location apps\backend
python -m pytest tests\test_runbook_contracts.py
Pop-Location

.\scripts\runbook-smoke.ps1

.\scripts\check-trial-processes.ps1
```

Note: root-level `progress.md` is coordinator-owned and outside this worker's allowed write scope.
