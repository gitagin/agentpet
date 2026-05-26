# Changelog

## Unreleased

- Added desktop key-path coverage for `Live2DStage`, `App`, and Electron sidecar failure handling with shared Vitest setup, and wired the new tests into the existing desktop CI test step.
- Centralized backend test helpers in shared pytest fixtures, split agent runtime coverage by feature area, and gated live model acceptance tests behind `--run-live-model`.
- Added backend Protocol boundaries for reminder scheduling, tool-capable chat models, continuity signals, and wiki workflow planning while enabling strict mypy configuration.
- Added locking around backend write-frequency policy state and TTL cleanup for pending chat runs to prevent unbounded global mutable state growth.
- Split backend API dependency wiring into service factory, runtime adapter, and error mapper modules, replacing wildcard wiring exports with explicit imports.
- Removed the dead legacy `AgentToolRuntimeBase` runtime so backend agent execution only uses the LangGraph runtime path; shared service wiring and helper functions now live outside the deleted legacy module.
- Centralized backend SQLite schema management in migrations, removing runtime business-code table/column creation from services and direct chat/wiki flows.
- Standardized backend agent, MCP, diary extraction, and continuity service interfaces on async callbacks and removed the `_maybe_await` compatibility helpers.
- Replaced background FastAPI request shims with a shared lightweight `AppContext`, so delayed index refresh and chat memory archival no longer retain raw request objects.
- Split the Electron main process into focused window, tray, sidecar, proxy, and IPC modules while keeping `main.cjs` as the orchestration entrypoint.
