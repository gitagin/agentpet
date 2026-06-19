# Project Progress

Detailed historical handoff logs were archived unchanged in
[`docs/archive/progress-history.md`](docs/archive/progress-history.md).

This file is coordinator-owned. Use it as the compact current-state ledger for
this repository. Validate current facts from code and commands, not git history.

## Current Version

- Product/version marker: `0.2.0`
- Current working phase: Phase 0 repository hygiene and documentation cleanup
- Latest unreconciled local file: `agentpet-task-instructions.md` is intentionally untracked task input

## Current Capability Boundary

### Covered

- Backend FastAPI sidecar, SQLite migrations, FTS-backed retrieval, task/reminder services, diagnostics, settings, and protected API wiring have automated coverage.
- Desktop Electron/React shell uses contextBridge IPC for renderer capabilities and keeps token/Node/FS access outside renderer code.
- Private desktop-pet low-risk automatic organization is implemented for daily chat diary, structured diary, long-term memory, and guarded Wiki writes with `agent_actions` activity records.
- High-risk Vault/Markdown/state actions still require confirmation; unsafe memory, continuity, and disabled-auto paths do not silently write.
- Wiki workflows include reviewed ingest, query archive, synthesis, lint/report paths, index/log maintenance, Obsidian-style links, and guardrail lint coverage.
- Companion retrieval uses deterministic multi-source aggregation across personal memory, structured diary objects, and daily chat before chat generation.
- v0.2 release metadata is aligned across backend package metadata, backend runtime version, desktop package metadata, and desktop lockfile.
- Phase 0 hygiene tasks completed so far: local pytest artifacts removed, gitignore hardened, root `LICENSE` added, and naming decision recorded as no rename.

### Partial

- Real desktop-pet double-click entry and some end-to-end Electron behaviors still require manual visual verification before being called complete.
- Companion rerank/compression is deterministic v1 only; no model reranker is in place.
- Companion consolidation v1 is API-triggered only; no scheduled episodic-to-semantic consolidation run exists.
- Path-safety edge cases, broad natural-language date parsing, and OS notification permission-denial behavior remain intentionally limited.
- Real personal Vault trials must be explicitly confirmed and should use isolated or backed-up Vaults by default.

### Gap

- Signed auto-update, distributable installer hardening, full Live2D lip sync, complex motion, and multi-character support remain outside the current scope.
- Phase 1 human verification recordings and notes are not complete, so later phases that depend on them must not be marked completed.

## Latest 5 Milestones

| Date | Status | Summary | Verification |
| --- | --- | --- | --- |
| 2026-06-19 | Completed | TASK-0004: archived detailed progress history and simplified `progress.md`. | Archive blob matches previous `progress.md`; compact ledger is 56 lines; `scripts/check-mvp-acceptance-gap.ps1` passed. |
| 2026-06-19 | Completed | TASK-0003: accepted no-rename decision for `Agent Pet` / `agent-pet` and documented positioning. | `docs/decisions/naming.md` exists; README positioning statement added; `scripts/check-mvp-acceptance-gap.ps1` passed. |
| 2026-06-19 | Completed | TASK-0002: added root MIT `LICENSE`; GitHub About/topics are ignored per user instruction to use local root as source of truth. | `LICENSE` exists; commit `451a647 docs: add project license`. |
| 2026-06-19 | Completed | TASK-0001: removed tracked `pytest-of-ASUS/` artifacts, hardened `.gitignore`, and removed local absolute path strings. | No `pytest-of-*` directories; required ignore rules present; local path scans returned no matches; focused backend/desktop checks passed. |
| 2026-05-18 | Completed | Implemented private desktop-pet answer maintenance loop and strengthened Wiki guardrails for diary-to-Wiki summaries. | Focused backend gates, backend full pytest, desktop typecheck/package check, acceptance gap, and runbook smoke passed. |

## Next Direction

1. Start Phase 1 only after confirming Phase 0 is complete and keep human-verification tasks human-owned.
2. Collect replayable manual evidence for desktop-pet entry and memory control loops before marking them complete.
3. Keep high-risk real Vault writes behind explicit confirmation while preserving low-risk automatic organization and reversible activity logs.
4. Do not promote any item to `Covered` / `Completed` without matching command output or human evidence.
