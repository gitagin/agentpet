# Dual-Track Memory System Task Set

This task set is for implementing a dual-track memory system in Agent Pet.
The immediate track makes the pet adapt quickly inside the current conversation.
The slow consolidation track turns only safe, scoped, explainable, and reversible signals into durable memory.

## Execution Rules

1. Protect against memory pollution before expanding automatic memory.
2. Immediate understanding may influence the current reply, but must not directly write long-term memory.
3. Slow consolidation must keep source, scope, lifecycle, risk, recall permissions, and audit evidence.
4. Long-term does not mean permanent. Durable memory must support active, stale, archived, forgotten, and superseded states.
5. Model inference must not become a user personality fact. Inference may only become a candidate or short-lived state unless confirmed by strong evidence.
6. High-risk, sensitive, conflicting, and low-confidence promotion must require confirmation or downgrade.
7. Schema changes require a new migration, model/service updates, pytest coverage, and backend verification.
8. Do not edit generated or local-state paths: `node_modules/`, `dist/`, `release/`, `*.db`, `logs/`, `.tmp/`, `.idea/`, `.codex/`.
9. Do not mark any acceptance row as `Covered` until implementation evidence or tests support it.
10. Renderer capabilities must still go through contextBridge IPC. Backend work comes first unless a task explicitly enters desktop UI.

## TASK-001: Baseline Memory Audit

Goal: Establish the current memory-system baseline before adding new behavior.

Read these files first:

- `apps/backend/app/services/memory_policy.py`
- `apps/backend/app/services/memory.py`
- `apps/backend/app/services/long_term_memory.py`
- `apps/backend/app/services/memory_graph.py`
- `apps/backend/app/services/diary_memory.py`
- `apps/backend/app/services/chat_auto_memory.py`
- `apps/backend/app/services/companion_retrieval.py`
- `apps/backend/app/services/continuity.py`
- `apps/backend/app/services/agent_actions.py`
- `apps/backend/app/agents/memory_router.py`
- `apps/backend/app/agents/nodes/memory.py`
- `apps/backend/app/agents/nodes/chat.py`
- `apps/backend/app/agents/graph_runtime.py`
- `apps/backend/migrations/003_vector_index_and_memory_graph.sql`
- `apps/backend/migrations/009_continuity_kernel.sql`
- `apps/backend/migrations/010_diary_memory_objects.sql`
- `apps/backend/migrations/012_agent_actions_autonomy.sql`
- `apps/backend/migrations/014_service_schema_cleanup.sql`

Steps:

1. List all current memory inputs: explicit remember requests, post-chat diary, structured diary, long-term memory, continuity state, and Wiki summaries.
2. List all current storage surfaces: `memory_graph_facts`, `diary_memory_objects`, `continuity_state`, `continuity_proposals`, `agent_actions`, and `daily_chat_memory_entries`.
3. List existing safety mechanisms: sensitive-content rejection, automation risk decisions, reversible Markdown snapshots, and the activity ledger.
4. Decide what can be reused and what must be added.

Acceptance:

- No behavior changes.
- The audit names where the immediate track and slow consolidation track will plug into the existing code.
- Run at least:
  - `Push-Location apps\backend; python -m pytest -q tests/test_memory_services.py tests/test_long_term_memory_services.py tests/test_chat_auto_memory_services.py tests/test_agent_actions.py; Pop-Location`

## TASK-002: Define Memory Taxonomy And Recall Permissions

Goal: Create a shared contract for safe, natural, scoped memory.

Suggested files:

- Add `apps/backend/app/services/memory_taxonomy.py`
- Update `apps/backend/app/models/memory.py` if API models need the contract
- Update `apps/backend/tests/test_contracts_api_models.py` if API schema changes

Define these fields:

- `memory_kind`: fact, preference, recent_state, boundary, project_context, historical, inference
- `memory_scope`: global, project, topic, relationship, temporary, sensitive
- `lifecycle_status`: candidate, active, stale, archived, forgotten, rejected, superseded
- `source_track`: immediate, slow_consolidation, explicit_user, model_extracted, diary, continuity
- `risk_tier`: low, medium, high
- `confidence`
- `importance`
- `evidence_count`
- `expires_at`
- `last_confirmed_at`
- `superseded_by`

Split recall permissions into separate booleans:

- `can_style_response`
- `can_answer_context`
- `can_proactively_mention`
- `can_suggest_action`
- `can_persist`

Rules:

1. Emotion, relationship, and personality inference must not default to `can_persist=True`.
2. User boundaries are durable and high priority, but can be changed by explicit user correction.
3. Low-confidence candidates cannot be proactively mentioned.
4. Sensitive content cannot be written to ordinary memory or Vault Markdown.
5. Current tasks and projects need lifecycle state; they must not remain current forever.

Acceptance:

- Unit tests cover default permissions for each kind and scope.
- Unit tests cover sensitive, conflicting, low-confidence, and explicit-user memory priority.

## TASK-003: Add Slow Memory Schema

Goal: Add queryable and auditable storage for the slow consolidation track.

Important: This is a SQLite schema change. Follow the project rule: add a migration, update models/services, add pytest coverage, and do not edit local database files.

Suggested migration:

- `apps/backend/migrations/017_dual_track_memory.sql`

Suggested tables:

1. `memory_candidates`
   - Stores extracted candidate memories.
   - Include kind, scope, summary, normalized_value, source_text, risk_tier, confidence, importance, status, expires_at, and metadata_json.
2. `memory_evidence`
   - Stores evidence for candidates or durable facts.
   - Link conversation_id, message_id, agent_run_id, diary_object_id, and fact_id when available.
3. `memory_lifecycle_events`
   - Stores candidate to active to stale to archived to forgotten transitions.
4. `memory_activation_events`
   - Stores each memory recall or response influence event.
5. `memory_feedback_events`
   - Stores user correction, keep, forget, rewrite, make-temporary, and mark-completed feedback.

Reuse requirements:

- Reuse `memory_graph_facts` for durable facts where possible.
- Reuse `agent_actions` for user-visible activity and revert records where possible.
- Use `metadata_json` for secondary fields only; frequently queried fields should be real columns.

Acceptance:

- Migration is idempotent.
- Add schema tests for tables, indexes, foreign keys, and defaults.
- Run:
  - `Push-Location apps\backend; python -m pytest -q tests/test_persistence_mvp.py tests/test_api_wiring_mvp.py; Pop-Location`

## TASK-004: Implement Immediate Understanding Layer

Goal: Let the pet adapt quickly inside the current conversation without polluting long-term memory.

Suggested files:

- Add `apps/backend/app/agents/immediate_understanding.py`
- Update `apps/backend/app/agents/state.py`
- Update `apps/backend/app/agents/nodes/chat.py`
- Update `apps/backend/app/agents/prompts/system.py`

Behavior:

1. Extract temporary understanding from the current user message and conversation state:
   - current task
   - desired tone
   - direct, detailed, gentle, sharp, or concise interaction style
   - current topic/domain
   - explicit temporary constraints
2. Store this only in agent state and prompt context.
3. Do not write it to `memory_graph_facts`, Vault Markdown, or long-term memory.
4. Allow it to immediately affect the current reply.
5. Make it internally traceable without exposing sensitive raw text.

Acceptance scenarios:

- After the user asks for blunt critique, the current reply becomes direct.
- A current-session tone request is not saved as a global preference.
- If the user says the request only applies this time, later turns do not keep it.

Tests:

- Add `apps/backend/tests/test_immediate_understanding.py`
- Update `apps/backend/tests/test_agent_runtime_chat.py`

## TASK-005: Implement Slow Consolidation Extractor

Goal: Extract candidate memory after chat without directly creating a long-term user profile.

Suggested files:

- Add `apps/backend/app/services/memory_consolidation.py`
- Refactor or reuse `apps/backend/app/services/long_term_memory.py`
- Reuse `apps/backend/app/services/diary_memory_extractor.py`
- Integrate with `apps/backend/app/services/chat_auto_memory.py`

Candidate classes:

1. Low-risk facts: project names, tool stacks, stable preferences. These may enter candidate or active state automatically.
2. Temporary states: emotion, current pressure, and short-term plans. These must be `recent_state` and require `expires_at`.
3. Inference: candidate only by default; `can_persist=False` unless supported by repeated evidence or confirmation.
4. Boundaries: "do not nag me", "do not save this", and similar constraints. These have highest priority.
5. Sensitive content: reject or store only as a non-recallable safety event. Do not write to ordinary memory or Vault.

Acceptance:

- One-off emotion does not become a durable personality fact.
- Repeated stable interaction preference can become a candidate and gain confidence.
- Model output like "the user is an anxious person" is rejected or downgraded to short-lived state.
- Explicit "remember this" remains the highest-confidence path, but not the only path.

Tests:

- Add `apps/backend/tests/test_memory_consolidation.py`
- Update `apps/backend/tests/test_long_term_memory_services.py`
- Update `apps/backend/tests/test_diary_memory_extractor.py`

## TASK-006: Add Lifecycle State Machine

Goal: Prevent completed projects, old goals, stale preferences, and superseded facts from acting like current truth.

Suggested files:

- Add `apps/backend/app/services/memory_lifecycle.py`
- Update `apps/backend/app/services/memory_graph.py`
- Update `apps/backend/app/models/memory.py`

Required transitions:

- candidate -> active
- candidate -> rejected
- active -> stale
- stale -> active
- stale -> archived
- active -> archived
- active -> forgotten
- active -> superseded

Transition triggers:

1. User explicitly says completed, cancelled, forget, or do not do this anymore.
2. New memory conflicts with old memory.
3. Old project has not appeared for a configured period.
4. New project or new preference appears repeatedly.
5. User review chooses keep, edit, forget, make temporary, or mark completed.

Acceptance:

- Completed projects stop being recalled as current tasks.
- Completed projects may remain as historical background.
- New related projects supersede current context without deleting old history.
- User boundaries are not overwritten by ordinary preferences.

Tests:

- Add `apps/backend/tests/test_memory_lifecycle.py`

## TASK-007: Implement Activation Scoring

Goal: Make recall fast and natural while staying controlled.

Suggested files:

- Add `apps/backend/app/services/memory_activation.py`
- Update `apps/backend/app/services/companion_retrieval.py`
- Update `apps/backend/app/agents/memory_router.py`

The score decides whether a memory can influence this turn. It does not decide whether the memory is true.

Suggested factors:

- query relevance
- scope match
- lifecycle status
- confidence
- importance
- evidence_count
- recency
- last_confirmed_at
- user_feedback
- conflict_penalty
- expired_penalty
- sensitive_penalty

Hard gates:

1. `forgotten` is never recalled.
2. `rejected` is never recalled.
3. Expired `recent_state` cannot be used as current fact.
4. Sensitive memory cannot be proactively mentioned.
5. Low-confidence inference cannot be proactively mentioned.

Acceptance:

- Current-session style can affect the reply quickly.
- Old state naturally loses influence.
- User boundaries win in relevant contexts.
- Corrected memories are immediately downgraded or disabled.

Tests:

- Add `apps/backend/tests/test_memory_activation.py`
- Update `apps/backend/tests/test_companion_retrieval_services.py`
- Update `apps/backend/tests/test_memory_router.py`

## TASK-008: Add Recall Permission Gate

Goal: Separate "can be saved" from "can be used in this reply".

Suggested files:

- Add `apps/backend/app/services/memory_permissions.py`
- Update `apps/backend/app/services/companion_retrieval.py`
- Update `apps/backend/app/agents/nodes/chat.py`

Implementation requirements:

1. Every recalled item must carry permissions.
2. Prompt construction must split memory into:
   - style memory: affects tone only, no raw source exposure
   - answer context: can be used as answer context
   - proactive mention: can be directly mentioned first
   - action suggestion: can support suggestions
3. Memory without the required permission cannot enter that prompt section.
4. Write `memory_activation_events` for actual usage and permissions.

Acceptance:

- "The user has been under pressure recently" may soften tone but must not be randomly brought up.
- "The user dislikes preachy answers" may influence tone long term.
- "The user is working on project X" is used only in relevant project contexts.

Tests:

- Add `apps/backend/tests/test_memory_permissions.py`
- Update `apps/backend/tests/test_agent_runtime_retrieval.py`

## TASK-009: Integrate User Correction

Goal: User correction must take effect immediately and prevent self-reinforcing wrong memory.

Suggested files:

- Update `apps/backend/app/api/memory.py`
- Update `apps/backend/app/services/memory_lifecycle.py`
- Update `apps/backend/app/services/agent_actions.py`
- Update desktop API client only if UI calls are added

Minimum operations:

- keep
- edit
- forget
- make_temporary
- mark_completed
- mark_stale
- reject_candidate

Rules:

1. User correction must write lifecycle or feedback events.
2. After forget, the memory must not be recalled.
3. After edit, the old memory must be superseded.
4. `make_temporary` must set `expires_at`.
5. `mark_completed` must move active project context into historical/archived state.

Acceptance:

- After the user says "that is not what I meant", related memory stops influencing the next turn.
- After the user says "this is only for today", the system creates a temporary state.
- After the user says "this project is done", it stops being active context.

Tests:

- Add `apps/backend/tests/test_memory_feedback_api.py`
- Update `apps/backend/tests/test_security_contracts_api.py`

## TASK-010: Add Memory Hygiene Job

Goal: Keep the candidate pool and short-lived state from growing into memory clutter.

Suggested files:

- Add `apps/backend/app/services/memory_hygiene.py`
- Integrate with startup or scheduler only after tests prove the service behavior

Cleanup rules:

1. Expired `recent_state` becomes archived or forgotten.
2. Long-unused, low-confidence, unconfirmed candidates become rejected or archived.
3. Old facts conflicting with stronger new facts become stale or superseded.
4. Duplicate candidates merge evidence.
5. Sensitive or policy-violating candidates are rejected.

Acceptance:

- Cleanup actions are recorded through lifecycle events or `agent_actions`.
- Raw chat logs are not deleted.
- User Vault originals are not overwritten.

Tests:

- Add `apps/backend/tests/test_memory_hygiene.py`

## TASK-011: Add Explainability Report

Goal: Explain why memory affected a reply without leaking credentials or sensitive headers.

Suggested files:

- Update `apps/backend/app/services/companion_retrieval.py`
- Update `apps/backend/app/models/memory.py`
- Update `apps/backend/app/api/memory.py`

Report fields:

- number of candidate recalls
- memory IDs that entered the prompt
- permissions used
- activation score breakdown
- filtered item reasons
- expired, conflict, or sensitive gates

Acceptance:

- Diagnostics never expose API keys, tokens, full Authorization headers, or private-key blocks.
- A user can understand why the pet remembered or avoided mentioning something.
- Redaction is tested.

Tests:

- Update `apps/backend/tests/test_companion_retrieval_services.py`
- Update `apps/backend/tests/test_audit_logs.py`

## TASK-012: Add Weekly Memory Review Surface

Goal: Give the user lightweight memory control without turning them into a memory administrator.

Suggested files:

- Backend: `apps/backend/app/api/memory.py`
- Desktop API: `apps/desktop/src/services/desktopApi.ts`
- UI: `apps/desktop/src/App.tsx` or the existing settings/memory panel

Product behavior:

1. Do not interrupt every chat with confirmation prompts.
2. Offer a short daily or weekly review:
   - what was kept
   - what is temporary
   - what was ignored
3. Let the user choose:
   - keep
   - edit
   - forget
   - only this week
   - mark completed

Acceptance:

- UI does not expose tokens.
- Renderer does not directly access Node or FS.
- Desktop capabilities still go through contextBridge IPC.
- High-risk confirmation remains mandatory.

Tests:

- Backend API tests.
- `Push-Location apps\desktop; npm run typecheck; Pop-Location`
- If Electron main/preload changes, also run migration validation.

## TASK-013: Wire Into Chat Runtime

Goal: Make the dual-track system part of the main chat path.

Suggested files:

- `apps/backend/app/api/chat.py`
- `apps/backend/app/agents/graph_runtime.py`
- `apps/backend/app/agents/nodes/chat.py`
- `apps/backend/app/agents/nodes/retrieval.py`
- `apps/backend/app/agents/state.py`

Execution order:

1. Run immediate understanding on the user message.
2. Retrieve memory through memory route plus activation scoring.
3. Split results through the permission gate.
4. Build chat prompt with separated style, context, proactive, and action memory.
5. After reply completion, run slow consolidation.
6. Slow consolidation writes only compliant candidates or active facts and records lifecycle/action events.

Acceptance:

- Current conversation adapts quickly.
- Durable writes stay conservative.
- User correction affects the next turn.
- Recall is explainable.
- Old projects do not pretend to be current projects.

Tests:

- Update `apps/backend/tests/test_agent_runtime_chat.py`
- Update `apps/backend/tests/test_agent_runtime_memory_task.py`
- Update `apps/backend/tests/test_agent_runtime_retrieval.py`
- Update `apps/backend/tests/test_api_wiring_mvp.py`

## TASK-014: Pollution Regression Suite

Goal: Add explicit regression tests for memory pollution.

New test file:

- `apps/backend/tests/test_memory_pollution_regression.py`

Must cover:

1. One-off emotion does not become durable personality memory.
2. Jokes do not become facts.
3. Model summaries do not directly become long-term memory.
4. Frequent complaining does not become a durable personality label.
5. Low-frequency but explicit boundaries remain protected.
6. Completed projects are archived.
7. Related new projects do not get polluted by old active context.
8. User correction prevents future recall.
9. Sensitive content does not write to Vault or ordinary memory.
10. `agent_actions` can trace automatic memory activity.

Acceptance:

- This regression suite passes in backend pytest.
- Future memory-strategy changes must run this test file.

## TASK-015: Acceptance And Documentation Update

Goal: Update docs only after implementation evidence exists.

Reference files:

- `docs/mvp-acceptance-coverage.md`
- `docs/runbook.md`
- `docs/v0.1-validation.md`
- `progress.md` is Coordinator-owned; do not write it unless acting as Coordinator.

Requirements:

1. Record new verification commands and results.
2. Mark acceptance rows as `Covered` only after tests or manual validation support the claim.
3. If the desktop memory review UI is incomplete, keep the relevant status Partial or Gap.
4. If the live provider gate was not run, record the missing `LIVE_*` environment variables.
5. If desktop visual validation was not run, record the residual risk.

Recommended final verification:

```powershell
Push-Location apps\backend; python -m pytest -q; Pop-Location
Push-Location apps\desktop; npm run typecheck; Pop-Location
Push-Location apps\desktop; node scripts/validate-electron-migration.mjs; Pop-Location
.\scripts\check-mvp-acceptance-gap.ps1
```

Completion standard:

- Dual-track memory affects the main chat path.
- Memory write, lifecycle, recall permissions, user correction, and audit records all have tests.
- Memory pollution regression tests pass.
- The user does not need frequent confirmation prompts.
- Wrong long-term user profiles cannot keep controlling current replies.
- The final delivery response lists every command actually run and its result.
