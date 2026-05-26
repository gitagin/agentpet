# Agent Pet

[![CI](https://github.com/gitagin/agentpet/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/gitagin/agentpet/actions/workflows/ci.yml)

Local-first desktop Agent pet with Obsidian-backed transparent memory.

The authoritative implementation spec is [`Development_Documentation.md`](Development_Documentation.md).

## MVP Modules

- `apps/backend`: Python FastAPI sidecar, SQLite, FTS5, Agent runtime, memory and task services.
- `apps/desktop`: Electron + React desktop shell and UI.
- `docs`: implementation notes and generated API artifacts.

## Progress

Implementation progress is tracked in [`progress.md`](progress.md).
