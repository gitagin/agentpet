# Development Worker Plan

This document describes development-time worker ownership only. It is not the
runtime multi-Agent architecture. Runtime Agent orchestration is implemented by
the backend `LangGraphAgentRuntime`, which connects chat, knowledge retrieval,
memory proposal, and task nodes through LangGraph.

## Coordination Rules

- `progress.md` is owned by the Coordinator only.
- Workers must not edit files outside their assigned ownership unless explicitly requested by the Coordinator.
- Shared API/data contracts must be updated through `apps/backend/app/models/` first.
- MVP scope takes priority over Beta features.

## Worker Ownership

| Agent | Ownership | Do Not Modify |
| --- | --- | --- |
| Backend API Agent | `apps/backend/app/api/`, `apps/backend/app/main.py`, request/auth/error middleware | `apps/desktop/`, storage internals |
| Storage Retrieval Agent | `apps/backend/app/storage/`, `apps/backend/app/repositories/`, `apps/backend/migrations/`, retrieval tests | `apps/desktop/`, Agent prompt logic |
| Agent Runtime Agent | `apps/backend/app/agents/`, chat orchestration, SSE event mapping | migration files, Electron shell config |
| Memory Task Agent | `apps/backend/app/services/memory.py`, `apps/backend/app/services/tasks.py`, `apps/backend/app/scheduler/` | API middleware, desktop UI |
| Desktop UI Agent | `apps/desktop/` | backend internals |
| QA Security Agent | tests under `apps/backend/tests/` and documentation checklists | production implementation except test fixtures |

## Merge Order

1. Coordinator scaffolding and contracts.
2. Backend API and storage foundations.
3. Retrieval, Agent runtime, memory/task services.
4. Desktop UI.
5. QA/security tests.
6. Coordinator integration pass.
