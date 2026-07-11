# Project Progress

Historical handoff logs were removed from the public document tree during
documentation consolidation. This file retains the current capability boundary
and the latest milestone summaries; older claims must be revalidated from code
and tests rather than copied from historical prose.

This file is coordinator-owned. Use it as the compact current-state ledger for
this repository. Validate current facts from code and commands, not git history.

## Current Version

- Product/version marker: `0.0.1-alpha` (backend Python package metadata: `0.0.1a0`)
- Current working phase: Phase 5 TASK-0505 habit loop completed; skipped Phase 1 human verification still not counted as completed
- Historical task instructions were superseded by `task.md` and removed during documentation consolidation.

## Current Capability Boundary

### Covered

- Backend FastAPI sidecar, SQLite migrations, FTS-backed retrieval, task/reminder services, diagnostics, settings, and protected API wiring have automated coverage.
- Desktop Electron/React shell uses contextBridge IPC for renderer capabilities and keeps token/Node/FS access outside renderer code.
- Private desktop-pet low-risk automatic organization is implemented for daily chat diary, structured diary, long-term memory, and guarded Wiki writes with `agent_actions` activity records.
- High-risk Vault/Markdown/state actions still require confirmation; unsafe memory, continuity, and disabled-auto paths do not silently write.
- Wiki workflows include reviewed ingest, query archive, synthesis, lint/report paths, index/log maintenance, Obsidian-style links, and guardrail lint coverage.
- Companion retrieval uses deterministic multi-source aggregation across personal memory, structured diary objects, and daily chat before chat generation.
- TASK-0402 version semantics are aligned with current completion: backend runtime, desktop package metadata, and desktop lockfile use `0.0.1-alpha`; backend Python package metadata uses PEP 440 compatible `0.0.1a0`; `CHANGELOG.md` is grouped by features, fixes, and known limitations.
- Phase 0 hygiene tasks completed so far: local pytest artifacts removed, gitignore hardened, root `LICENSE` added, and naming decision recorded as no rename.
- TASK-0101 desktop-pet double-click entry was user-confirmed manually on 2026-06-19; recording evidence was explicitly waived by the user.
- TASK-0301 L1-L4 verification policy is documented in `docs/verification-policy.md`.
- TASK-0401 created `docs/current-specification.md` as the only current effective specification; the superseded specification was removed during documentation consolidation.
- TASK-0501 rewrote README around memory transparency, controllability, and migration, with explicit LLM API data-flow disclosure.
- TASK-0502 implements a user-facing local privacy mode: sensitive chat input only uses local FTS/keyword retrieval, skips model-driven reply/background memory work, and has network-layer automated evidence that the configured model endpoint receives no request.
- TASK-0504 implements a read-only growth snapshot API and desktop growth record page. Growth dimensions are tied to chat diary entries, long-term memory facts, diary memory objects, reversible/skipped/feedback actions, and Wiki pages.
- TASK-0505 implements a low-friction desktop-pet habit loop with frequency-controlled proactive bubbles backed by tasks, daily chat diary, memory facts, and Wiki activity.

### Partial

- Some remaining end-to-end Electron behaviors still require manual verification before being called complete.
- TASK-0102 real Vault chat/memory/rollback validation was skipped by user request on 2026-06-19 and is not completion evidence.
- TASK-0201 scope-freeze decision was confirmed by the user on 2026-06-20.
- TASK-0202 memory controllability polish is implemented and covered by focused desktop tests, but manual export verification was skipped by user request on 2026-06-20, so it is not completion evidence.
- TASK-0503 recall wording guardrails and scoring/sample templates exist, but the task is not Completed because TASK-0102 remains skipped, no 20 real dialogue samples exist, and no human review has been performed.
- Companion rerank/compression is deterministic v1 only; no model reranker is in place.
- Companion consolidation v1 is API-triggered only; no scheduled episodic-to-semantic consolidation run exists.
- Path-safety edge cases, broad natural-language date parsing, and OS notification permission-denial behavior remain intentionally limited.
- Real personal Vault trials must be explicitly confirmed and should use isolated or backed-up Vaults by default.

### Gap

- Signed auto-update, distributable installer hardening, full Live2D lip sync, complex motion, and multi-character support remain outside the current scope.
- Phase 1 tasks after TASK-0101 are not complete, so later phases that depend on them must not be marked completed. TASK-0201 review is the only allowed Phase 2 exception marked completed by user confirmation.

## Progress Record Template

| Date | Status | Verification Level | Summary | Verification |
| --- | --- | --- | --- | --- |
| YYYY-MM-DD | Completed / In Progress / Skipped / Blocked | L1 / L2 / L3 / L4 | What changed and what boundary it affects. | Exact commands, human evidence, skipped checks, and results. |

## Latest 5 Milestones

| Date | Status | Verification Level | Summary | Verification |
| --- | --- | --- | --- | --- |
| 2026-07-11 | Completed | L2 | Repository cleanup removed 23 ignored Chromium/Playwright profiles, consolidated `docs/` from 29 Markdown files to 5 active contracts, removed superseded root task/product documents, and redirected per-task raw evidence to ignored `output/verification/`. A later explicit user instruction also physically deleted the 15 still-present staged Vault documents and 3 staged local configuration files; 3 Vault files outside that staged batch, backend SQLite/credential state, and product source were preserved. | Profile and second-batch physical-delete postchecks passed; documentation link check reported 0 missing links; backend documentation contracts passed 9 tests; Electron migration, MVP acceptance-gap, repository hygiene, cached/worktree diff checks all passed. |
| 2026-06-21 | Completed | L3 | TASK-0505: implemented low-friction daily proactive triggers with `POST /api/habit-loop/trigger`, frequency settings, daily caps, cooldown, idle/quiet guards, desktop pet polling, and Settings frequency controls. | Historical run: backend habit-loop/settings focused suite passed 4 tests; desktop/Electron focused suite passed 28 tests; typecheck and Electron proxy syntax passed. Rerun before relying on it. |
| 2026-06-21 | Completed | L3 | TASK-0504: implemented visible desktop-pet growth feedback with four real-data dimensions, `GET /api/growth/snapshot`, a `#growth` record page, stage/navigation/Electron entry points, and growth history from `agent_actions`. | Historical run: real `/api/chat` auto-archive test confirmed `memory_depth` advances; backend focused suite passed 6 tests; desktop/Electron focused suite passed 28 tests; typecheck, Electron syntax, migration, and package checks passed. Rerun before relying on it. |
| 2026-06-21 | In Progress | L2 | TASK-0503: added recall wording guardrails so no-model fallback avoids raw snippet echo, model prompt asks for natural non-verbatim recall, and a 20-sample human scoring template exists. Not Completed because TASK-0102, real samples, and human review remain missing. | Historical run: backend recall guardrail suite passed 33 tests and MVP acceptance gap passed; no 20-sample human review exists. Rerun before relying on it. |
| 2026-06-21 | Completed | L3 | TASK-0502: implemented local privacy mode for sensitive chat input, including backend guard, settings persistence, UI toggle/copy, and model-network blocking evidence. | Historical run: local fake model server received 0 requests; backend broader focused suite passed 53 tests; desktop settings tests passed 16 tests; typecheck and MVP acceptance gap passed. Rerun before relying on it. |

## Next Direction

1. Continue with TASK-0506 only if the user is ready for real seven-day retention work; it requires human testers and cannot be completed by agent-only automation.
2. Do not mark TASK-0503 Completed until TASK-0102 or a user-confirmed replacement validation path exists, at least 20 real dialogue samples are annotated, and the updated recall wording passes human review.
3. Keep TASK-0102 and TASK-0103 out of Completed status unless matching human evidence or an explicit replacement validation decision is recorded.
4. Keep high-risk real Vault writes behind explicit confirmation while preserving low-risk automatic organization and reversible activity logs.
5. Do not promote any item to `Covered` / `Completed` without a matching L1-L4 verification level and command output or human evidence.
