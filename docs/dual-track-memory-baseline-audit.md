# Dual-Track Memory Baseline Audit

TASK-001 records the current memory-system baseline before adding dual-track behavior. This is a documentation-only audit; it does not change runtime behavior, migrations, API models, or acceptance statuses.

## Current Memory Inputs

| Input | Current entry point | Current behavior |
| --- | --- | --- |
| Explicit remember requests | `apps/backend/app/agents/nodes/memory.py`, `apps/backend/app/services/memory.py` | The memory proposal node creates pending Markdown write proposals. Confirmation writes through `SafeMarkdownWriter`; rejection keeps the proposal out of the Vault. |
| Automatic long-term memory | `apps/backend/app/services/chat_pipeline/long_term.py`, `apps/backend/app/services/long_term_memory.py` | After chat completion, automation can call `remember_from_user_message()`. Explicit patterns may write Markdown plus a graph fact; model-extracted facts write graph facts only. Sensitive source text or sensitive subjects are skipped. |
| Post-chat daily diary | `apps/backend/app/services/chat_pipeline/diary.py`, `apps/backend/app/services/chat_auto_memory.py` | If `auto_chat_diary` is enabled, each completed chat exchange appends a daily Markdown entry and records a row in `daily_chat_memory_entries`. |
| Structured diary memory | `apps/backend/app/services/chat_pipeline/diary_memory.py`, `apps/backend/app/services/diary_memory.py`, `apps/backend/app/services/diary_memory_extractor.py` | If daily diary output exists and `auto_structured_memory` is enabled, the exchange is extracted into structured diary objects with source links back to the chat exchange and Markdown path. |
| Long-term graph facts | `apps/backend/app/services/long_term_memory.py`, `apps/backend/app/services/memory_graph.py` | Durable or candidate-like facts are normalized into `memory_graph_facts`. Existing conflict handling quarantines low-confidence or conflicting writes but does not provide the full dual-track lifecycle. |
| Continuity state | `apps/backend/app/api/chat.py`, `apps/backend/app/services/continuity.py` | After a reply, continuity proposals are generated from the exchange. Confirmed or auto-confirmed low-risk proposals update compact runtime state; pending/rejected proposals stay outside runtime context. |
| Wiki summaries | `apps/backend/app/services/chat_pipeline/wiki_summary.py`, `apps/backend/app/services/chat_answer_wiki_summary.py` | If `auto_wiki_organize` is enabled and the answer looks reusable and safe, the system can distill the answer into `Wiki/Companion/Summaries/*.md` with source links and an action ledger record. |
| Retrieval-time memory context | `apps/backend/app/agents/memory_router.py`, `apps/backend/app/agents/nodes/retrieval.py`, `apps/backend/app/services/companion_retrieval.py` | User messages are routed to memory scopes, searched across personal memory, diary objects, daily chat, knowledge base, and graph facts, then reranked into prompt context. |

## Current Storage Surfaces

| Surface | Migration | Service owner | Current role |
| --- | --- | --- | --- |
| `memory_graph_facts` | `003_vector_index_and_memory_graph.sql`, extended by `010_diary_memory_objects.sql` | `MemoryGraphStore` | Queryable fact store with status, confidence, source text, support count, conflicts, memory type, timestamps, expiry, metadata, and importance. |
| `memory_graph_events` | `003_vector_index_and_memory_graph.sql` | `MemoryGraphStore` | Minimal fact event trail for insert, support increment, and status updates. |
| `diary_memory_objects` | `010_diary_memory_objects.sql` | `DiaryMemoryStore` | Structured diary memory objects with type, summary, topic, emotion, people, keywords, importance, confidence, status, and occurrence time. |
| `diary_memory_object_sources` | `010_diary_memory_objects.sql` | `DiaryMemoryStore` | Evidence links from diary objects to chat messages, agent runs, Markdown paths, notes, and chunks. |
| `diary_memory_object_fts` | `010_diary_memory_objects.sql` | `DiaryMemoryStore` | FTS5 index for structured diary search. |
| `continuity_state` | `009_continuity_kernel.sql` | `ContinuityService` | Compact confirmed runtime continuity state keyed by identity, relationship, mood, energy, and open-thread fields. |
| `continuity_proposals` | `009_continuity_kernel.sql` | `ContinuityService` | Reviewable continuity candidates with evidence, confidence, status, and source IDs. |
| `continuity_events` | `009_continuity_kernel.sql` | `ContinuityService` | Proposal lifecycle events for creation, confirmation, and rejection. |
| `agent_actions` | `012_agent_actions_autonomy.sql` | `AgentActionService` | User-visible activity ledger with risk tier, decision, status, target paths, before/after snapshots, metadata, and revert links. |
| `automation_settings` | `012_agent_actions_autonomy.sql` | `AgentActionStore` and settings services | Feature toggles for automatic chat diary, structured memory, long-term memory, Wiki organization, and mandatory high-risk confirmation. |
| `daily_chat_memory_entries` | `014_service_schema_cleanup.sql` | `ChatAutoMemoryStore` | One row per archived chat exchange, linked to the daily Markdown diary entry. |
| `companion_retrieval_events` | `014_service_schema_cleanup.sql` | `CompanionRetrievalService` | Safe retrieval telemetry using hashes, scopes, result IDs, budgets, and counts rather than raw prompt text. |
| `companion_retrieval_reports` | Later migration, used by `CompanionRetrievalReportStore` | `CompanionRetrievalReportStore` | Context-budget telemetry for rerank/compression decisions without raw snippets. |

## Existing Safety Mechanisms

| Mechanism | Current location | Current protection |
| --- | --- | --- |
| Sensitive-content rejection | `memory_policy.py`, `write_policy.py`, `long_term_memory.py`, `diary_memory_extractor.py`, `continuity.py`, `chat_answer_wiki_summary.py`, `companion_retrieval.py` | Shared checks reject sensitive source content for memory writes, skip sensitive model-extracted facts, avoid sensitive continuity proposals, skip sensitive Wiki summaries, and filter sensitive retrieval snippets. |
| Automation risk decisions | `agent_actions.py` | `AutomationPolicy` classifies high-risk, medium-risk, notify, and low-risk actions. Sensitive, destructive, unsafe path, schema, and high-risk Vault operations require ask-level handling. |
| Reversible Markdown snapshots | `agent_actions.py`, Wiki adapters, retrospective services, Wiki summary service | Markdown-writing workflows can capture before/after snapshots through `markdown_snapshot()` and support revert actions through `AgentActionService.revert()`. |
| Activity ledger | `agent_actions.py`, `chat_pipeline/*`, `api/chat.py`, Wiki adapters | Automatic diary, structured memory, long-term memory, Wiki, continuity, negotiation, and skipped safety events can be recorded with source message/run IDs and metadata. |
| Vault path safety | `memory.py`, `storage/paths.py`, Wiki services | Markdown writes resolve relative Vault paths, reject hidden or out-of-root paths, and Wiki writes are constrained to the Wiki family by service-level path checks. |
| Conflict and confidence quarantine | `memory_graph.py` | Graph facts with active conflicts or confidence below `0.65` are stored as quarantined rather than active. |
| Continuity review gate | `continuity.py`, `api/chat.py`, `agent_actions.py` | Continuity proposals are pending by default; identity/relationship changes are medium risk and require confirmation unless policy/toggles allow lower-risk auto-application. |
| Retrieval redaction by omission | `companion_retrieval.py` | Sensitive retrieved items are skipped before context construction, and telemetry stores hashes and counts rather than raw sensitive text. |

## Reusable Pieces

- Reuse `MemoryGraphStore` and `memory_graph_facts` for durable slow-track facts, because they already have confidence, support count, conflicts, source IDs, expiry, metadata, and active/quarantine behavior.
- Reuse `DiaryMemoryStore`, `diary_memory_object_sources`, and FTS for evidence produced from daily chat archives.
- Reuse `ContinuityService` for review-gated relationship, identity, mood, energy, and open-thread signals, but keep it as compact runtime state until unified lifecycle/permission rules exist.
- Reuse `AutomationPolicy` and `agent_actions` for consolidation visibility, risk decisions, skipped safety events, and reversible Markdown write records.
- Reuse `memory_policy.evaluate_memory_content()` as the first sensitive-content gate for both immediate and slow tracks.
- Reuse `MemoryRouter`, `CompanionRetrievalService`, and `rerank_memory_context()` as the retrieval path that later activation scoring and permission gates can wrap.
- Reuse `AgentState` and `graph_state` for immediate understanding because they are per-run/per-conversation runtime state and are not persisted by default.

## Required Additions

- Add a shared memory taxonomy and recall-permission contract. Current code has categories, types, scopes, statuses, and risk decisions, but no single contract for `memory_kind`, `memory_scope`, lifecycle status, source track, risk tier, confidence, importance, evidence count, expiry, confirmation time, supersession, and recall permissions.
- Add slow-track candidate/evidence/lifecycle/activation/feedback tables. Existing `memory_graph_events` and `continuity_events` are too narrow to explain candidate promotion, user corrections, recall influence, and lifecycle transitions across all memory surfaces.
- Add immediate understanding in runtime state before prompt construction. Current `SemanticAnalysisResult.answer_style` is retrieval-oriented and persisted nowhere, but it is not rich enough for current task, temporary tone, temporary constraints, and current topic.
- Add a slow consolidation service after reply completion. The existing `chat_pipeline` already runs after a successful reply, so consolidation can plug in there without changing the streaming surface.
- Add lifecycle state machine support beyond active/quarantined/pending/confirmed/rejected. Completed projects, stale preferences, forgotten facts, and superseded memories currently need a unified state model.
- Add activation scoring and hard gates before prompt construction. Current reranking ranks by scope, score, and budget, but it does not model lifecycle, expiry, permissions, conflicts, sensitive penalties, or low-confidence inference gates.
- Add recall permission splitting. Current prompt context is one context block; it does not separate style-only memory, answer context, proactive mention, and action suggestion.
- Add user feedback operations that write lifecycle and feedback events. Existing confirm/reject paths cover memory proposals and continuity proposals, but not keep/edit/forget/make-temporary/mark-completed across all durable memory.
- Add hygiene jobs for expired recent state, stale candidates, duplicate candidates, and sensitive/policy-violating candidates.
- Add explainability reports that connect recall candidates, activation scoring, filtered reasons, and actual prompt permissions without exposing raw secrets.

## Dual-Track Plug-In Points

| Track | Plug-in point | Rationale |
| --- | --- | --- |
| Immediate understanding | `AgentState` in `apps/backend/app/agents/state.py` plus `graph_state` in `graph_runtime.py` | This state exists only for the active run and is naturally available to all agent nodes. |
| Immediate prompt influence | `_message_with_runtime_context()` and `_chat_node()` in `apps/backend/app/agents/nodes/chat.py` | Current continuity context is injected here, so temporary task/tone/topic context can be added without touching durable storage. |
| Immediate routing influence | `memory_router.py` and `nodes/retrieval.py` | Current retrieval scopes are chosen here; current topic/task signals can help choose or suppress retrieval before durable memory exists. |
| Slow consolidation extraction | `archive_chat_memory()` in `apps/backend/app/services/chat_pipeline/__init__.py` | This pipeline runs only after a successful assistant answer and already coordinates long-term memory, diary, structured memory, and Wiki summary writes. |
| Slow durable fact write | `LongTermMemoryService` and `MemoryGraphStore` | Durable writes can reuse graph facts while adding candidate/evidence/lifecycle records around them. |
| Slow evidence write | `DiaryMemoryStore`, `daily_chat_memory_entries`, and future `memory_evidence` | Chat diary and structured diary already preserve message IDs, Markdown paths, and agent run IDs that can become evidence records. |
| Slow lifecycle and correction | `MemoryGraphStore.update_status()`, `ContinuityService.confirm/reject`, and future lifecycle/feedback services | Current state changes exist but need unified transitions and feedback records. |
| Recall activation and permissions | `CompanionRetrievalService.retrieve()`, `rerank_memory_context()`, `nodes/retrieval.py`, and `nodes/chat.py` | Retrieval results currently enter a single context block; activation scoring and permission splitting should gate this path before prompt construction. |
| User-visible audit | `AgentActionService` | Automatic consolidation, skipped sensitive writes, user corrections, and reversible Markdown changes should continue to appear in the existing activity ledger. |

## Baseline Decision

The current system already has useful primitives for source-linked memory, low-risk automation, sensitive-content rejection, and auditability. The dual-track work should not replace these primitives. It should add a taxonomy, candidate/evidence schema, lifecycle state machine, activation scoring, recall permissions, and feedback/hygiene services around the existing stores.

The immediate track should be state-only and should plug into chat prompt construction before any long-term write path. The slow consolidation track should plug into the existing post-chat `chat_pipeline` and use conservative writes: candidates and evidence first, durable graph facts only when policy, confidence, lifecycle, and recall permissions allow it.

