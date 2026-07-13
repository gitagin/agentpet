# Full Upgrade Live Baseline

Status: accepted current-worktree baseline

Date: 2026-07-11

Owner: Coordinator / TASK-1201

Evidence level: L2

## Decision

Freeze the current dirty worktree as the only baseline for the TASK-12xx upgrade stream. Historical task status and historical test output are not completion evidence. The current worktree contains a real standard LangGraph, a real bounded negotiation LangGraph, a LangChain model/tool path, an FTS-first Agent retrieval path, deterministic action execution, and a post-reply reflection pipeline. It does not yet justify claims of independent specialist collaboration, an independent Reviewer, parallel fan-out, measured hybrid-RAG quality, persistent HITL, or a safe public Agent trace.

The public `reasoning` field is a P0 stop-line. `TASK-1203` must remove it before any broader multi-Agent or public-trace claim advances.

## Scope and worktree boundary

This record describes the checkout exactly as tested on 2026-07-11. Before TASK-1201 wrote evidence, `git status --porcelain=v1` reported 68 pre-existing entries: 57 modified files, one deleted file, and ten untracked files. Relevant ownership groups were:

- negotiation/runtime/API/tests: modified `apps/backend/app/agents/*`, `apps/backend/app/api/*`, service wiring, and focused tests;
- desktop trace/settings/demo UI: modified chat dispatcher, message list, settings, views, styles, and tests;
- demo work: untracked demo seed, demo tests, demo styles, `scripts/prepare-demo.ps1`, and `design-qa.md`;
- documentation/media: modified `docs/runbook.md` and `锐评.md`, untracked `修改建议.md` and `问题.md`, and deleted `动画.mp4`.

TASK-1201 did not reset, format, delete, or edit any of those product files. All current claims are therefore current-worktree claims, not claims about `HEAD`, a clean checkout, or a released build.

## Section 2 baseline reconciliation

| # | Planned starting statement | Result | Current worktree truth and evidence |
| ---: | --- | --- | --- |
| 1 | Standard and negotiation LangGraphs exist | Confirmed | The standard graph is built and compiled in `apps/backend/app/agents/graph_runtime.py:238`; the negotiation graph is built in `apps/backend/app/agents/negotiation_graph.py:20` and selected at runtime in `graph_runtime.py:73`. |
| 2 | ChatOpenAI, create_agent, and StructuredTool are real runtime paths | Confirmed with configuration condition | `apps/backend/app/services/chat_model.py:273` constructs `ChatOpenAI`, line 299 constructs `create_agent`, and `apps/backend/app/agents/tools.py:257` exposes real `StructuredTool` instances. These paths require a usable model configuration; deterministic fallbacks remain valid. |
| 3 | Negotiation is bounded to two rounds and a per-Agent timeout | Confirmed, with a settings mismatch | Runtime hard-caps delegation to two rounds and uses 15 seconds for the orchestrator and delegated Agent (`graph_runtime.py:41`, `graph_runtime.py:362`, `graph_runtime.py:450`). The persisted/API `max_rounds` still accepts 2 through 10 (`apps/backend/app/models/config.py:151`), but runtime overwrites it with two; the stored value is not an effective runtime budget. |
| 4 | Dynamic additional delegation is effectively retrieval-only | Confirmed, stronger than stated | Both the orchestrator and runtime explicitly reject non-retrieval delegation (`apps/backend/app/agents/nodes/orchestrator.py:78`, `graph_runtime.py:432`). No fan-out exists. |
| 5 | Simple chat has a direct streaming fast path | Confirmed | When negotiation is not selected and graph execution is unnecessary, `graph_runtime.py:134` prepares a fast path and `graph_runtime.py:163` calls `stream_complete` directly. Plain chat remains outside both compiled graphs. |
| 6 | Action execution is deterministic | Confirmed with lifecycle gap | `apps/backend/app/agents/nodes/action.py:20` builds typed Python plans and line 37 executes them; `graph_runtime.py:616` executes at finish. There is no independent policy-guard/executor graph boundary, persistent idempotency key, or interrupt/resume path. |
| 7 | Reflection is not a foreground negotiation participant | Confirmed | The foreground negotiation node list has no reflection node. `apps/backend/app/api/chat.py:365` schedules post-reply work after a successful answer. The stage runner is sequential and error-isolated, but the outer job is still a bare `asyncio.create_task` without a lifecycle registry, global timeout, cancellation handle, or idempotency key. |
| 8 | Public negotiation reasoning reaches the desktop | Confirmed — P0 stop-line | `apps/backend/app/agents/events.py:94` defines public `reasoning`; `graph_runtime.py:845` copies free-form model reasoning; `events.py:139` serializes it; `apps/desktop/src/features/chat/streamDispatcher.ts:161` stores it; `ChatMessageList.tsx:299` renders it. The focused desktop tests also preserve this field rather than reject it. |
| 9 | SQLite FTS5 and Vault retrieval are the default Agent path | Confirmed with precision | Vault Markdown is read during index rebuild, then Agent queries use SQLite `note_fts`; diary objects use a separate SQLite FTS5 table, and active structured memory can be merged before Vault results. This is FTS-first, not direct file search on every query. |
| 10 | Vector/Qdrant availability depends on supported embeddings | Confirmed, with additional prerequisites | `apps/backend/app/services/retrieval_factory.py:15` requires a key, supported OpenAI-compatible provider, a constructible embedding client, usable Qdrant dependencies, a local collection, and successful provider calls. There is no positive vector similarity-search test or full index-generation lifecycle proof. |
| 11 | Several Agent calls force FTS | Confirmed | Forced/default FTS calls exist in local-privacy, retrieval, chat fallback, tool schema, and scoped fallback paths (`graph_runtime.py:116`, `nodes/retrieval.py:96`, `nodes/chat.py:143`, `tools.py:132`). The model-facing wrapper fixes scope but does not reject an explicit `hybrid` or `vector` mode from the model. |
| 12 | Hybrid ordering is static rather than calibrated rank fusion | Confirmed with layer qualification | Vault hybrid ranking is source weight, then mode weight, then raw score (`apps/backend/app/services/retrieval.py:188`, line 272). The full Agent path adds deterministic graph/diary precedence, scope filtering, deduplication, raw-score ordering, and context budgets. No RRF exists. |
| 13 | Kuzu is a best-effort graph mirror | Confirmed | `apps/backend/app/services/memory_graph.py:409` lazily initializes Kuzu and disables it on failure. Reads come from SQLite memory graph facts; Kuzu only mirrors nodes/edges and has no vector schema or primary-query role. |
| 14 | No labelled quality benchmark proves retrieval/answer metrics | Confirmed | Current app/tests/docs/scripts contain no fixed labelled Recall@K, MRR, nDCG, citation-precision, or answer-faithfulness evaluator. Existing focused tests are contract tests, not a quality benchmark. |
| 15 | task.md status alone is not completion evidence | Confirmed | Old tasks remain `Planned` while pieces of their code exist, and several DoD items are explicit gaps. The 77-row crosswalk in the TASK-1201 evidence directory uses only current code and current command output. |
| 16 | The worktree may contain unrelated dirty files | Confirmed | The pre-task 68-entry inventory is recorded above and in `output/verification/task-1201/commands.txt`. All were preserved. |

## Runtime and role classification

| Runtime label | Current implementation | Honest classification |
| --- | --- | --- |
| Chat Agent | Separate model configuration, LangChain client, direct streaming and graph synthesis paths | Model-backed Agent when configured; also the synthesizer implementation |
| Semantic Analysis Agent | Model call with deterministic classifier fallback | Model-backed Agent when configured; deterministic fallback otherwise |
| Retrieval Agent | Scoped model/tool path with deterministic SQLite/FTS fallback | Model-backed read Agent when configured, but current negotiation only delegates this one role and can complete without a distinct model call |
| Action Agent | Registered/named as an Agent, but plan, policy decision, and execution are Python code | Deterministic planner/executor; must not be counted as an independent model-backed Agent |
| Reflection Agent | Can use a separately configured model for post-reply extraction/continuity | Background model-backed capability, not a foreground graph participant or managed independent background graph |
| Orchestrator | Pydantic decision schema and a prompt over the Chat Agent model | Model-backed coordination node that reuses the Chat model; not an independently registered role |
| Router, scope planner, evidence aggregation, dedupe, context budgeting, policy, executor, finish, SSE formatter | Python functions/nodes | Deterministic components, not Agents |

The current registry (`apps/backend/app/agents/registry.py:13`) is not yet a full capability contract. It lacks tool allowlists, privacy classes, call/token budgets, trace policy, and fallbacks. It also marks the deterministic Action role retryable. TASK-1208 must extend this registry rather than introduce a competing one.

## Current controls, budgets, and timeouts

| Control | Current value/behavior | Gap |
| --- | --- | --- |
| `use_negotiation` | Persisted automation flag; runtime also requires a memory/retrieval-shaped request | Plain social chat stays on the fast path by design |
| `max_rounds` | API/storage accepts 2–10; runtime hard-caps to 2 | UI/storage value above two is ineffective |
| Negotiation timeout | 15 seconds for orchestrator and each delegated Agent | No global elapsed-time budget |
| Model timeout | 30 seconds by default through `AGENT_PET_MODEL_TIMEOUT_SECONDS` | No aggregate model-call/token/cost budget |
| Delegated calls | At most two rounds; duplicate role + normalized query is blocked | A retrieval delegation can internally perform multiple sequential model/tool operations; no global call counter |
| Retrieval context | Default five selected items, at most two per scope, 1,200-character companion context | Other prompt sections have separate character budgets; no single total graph-token budget |
| Prompt memory sections | Character caps from 600 to 12,000 per section in `PromptMemoryBudgetConfig` | Usage is character-based, not measured provider tokens |
| Vector | No explicit feature flag; availability is derived from embedding credential/provider/client/index state | `semantic_available` metadata remains false even when a vector index may be available |
| Kuzu | No explicit feature flag; presence of graph root triggers best-effort mirror initialization | No lifecycle/status contract beyond fail-soft behavior |
| Post-reply stages | Four automation flags gate daily diary, structured diary, slow consolidation, and Wiki summary | Stages have exception isolation but no explicit per-stage timeout |
| High-risk confirmation | `high_risk_confirmation_required` is fixed true | Current high-risk foreground ends as `done` with a pending action record, not a graph `pending_confirmation` terminal |

## Public events and terminal semantics

- Runtime terminal SSE event classes are `done` and `error` (`apps/backend/app/agents/events.py:82`, line 113).
- `negotiation_done` is a non-terminal progress event emitted before `done`.
- The API emits `reply_ready` before `done`, persists the first terminal outcome, and synthesizes an `error` if the stream ends without a terminal event (`apps/backend/app/api/chat.py:329`).
- Client disconnect persists run/message status `cancelled` but emits no public `cancelled` event.
- `pending_confirmation` is an action/ledger state, not a run terminal or resumable LangGraph state.
- The target four-way terminal contract (`done`, `error`, `cancelled`, `pending_confirmation`) therefore does not yet exist.

## Retrieval truth and fallback

1. Markdown/Vault and SQLite are authoritative; SQLite FTS5 is the production Agent search base.
2. The production adapter can merge activated SQLite graph facts, diary-object FTS, daily chat, and Vault FTS. This is deterministic multi-source retrieval, not parallel multi-Agent retrieval.
3. `RetrievalService` supports `fts`, `vector`, and `hybrid`; invalid mode values silently become `hybrid`, while Agent tool defaults are FTS.
4. Vector failure records safe availability/error metadata and falls back to FTS. Vector-only mode also falls back to FTS when vector results are empty.
5. Kuzu failure disables only the derived mirror; SQLite graph facts remain readable.
6. Local-privacy sensitive input short-circuits remote model calls and forces local FTS.
7. No current RRF, reranker decision, vector lifecycle acceptance, prompt-injection evidence envelope, or fixed quality benchmark is complete.

## Current verification

TASK-1201 ran the exact focused suites against the dirty worktree:

- negotiation and integration: 14 passed;
- FTS/Agent retrieval/companion retrieval/memory activation: 33 passed;
- demo seed and golden paths: 5 passed;
- desktop TypeScript: passed;
- desktop chat/trace/settings components: 26 passed.

This is current L2 evidence for the baseline only. It is not L3 packaged-product evidence, live-provider evidence, a quality benchmark, or L4 human acceptance.

## Claim boundary

Safe now:

- a real LangGraph multi-role workflow exists;
- a bounded, retrieval-only negotiation path exists in the current worktree;
- simple chat retains a direct streaming fast path;
- Agent retrieval is FTS-first with optional derived vector infrastructure and deterministic fallback;
- action planning/execution remains deterministic and high-risk confirmation remains mandatory.

Conditional only:

- vector retrieval can run when all embedding/Qdrant prerequisites are satisfied, but lifecycle and quality are unproven;
- background reflection can call a model, but it is not a managed independent background Agent graph;
- negotiation is validated by focused L2 tests in this dirty worktree, not by live-provider or packaged L3 evidence.

Unsafe or forbidden now:

- safe public Agent trace or no-reasoning-leakage;
- independent Supervisor/Reviewer/Action-Proposal/Verifier/Synthesizer collaboration;
- parallel multi-Agent retrieval;
- calibrated hybrid RAG, RRF, reranking, or measured semantic-quality claims;
- persistent checkpointer or LangGraph interrupt/resume;
- enterprise-grade, production-grade, fully autonomous, or self-healing language.

## Next task readiness

With TASK-1201 complete, exactly these tasks may become Ready:

- TASK-1202: architecture/claims/evaluation ADR; it must stop at its Human Gate for an Adopt/Defer/Reject decision.
- TASK-1203: remove public reasoning and unsafe trace fields; this is the immediate stop-line task.
- TASK-1204: freeze a synthetic labelled retrieval corpus and FTS baseline.

No other TASK-12xx dependency is satisfied. In particular, TASK-1205 and TASK-1208 remain Planned until their stated prerequisites are completed.

## Rollback

If this baseline is rejected, remove only `docs/adr/full-upgrade-baseline.md` and `output/verification/task-1201/`, revert status-only TASK-1201 bookkeeping, and leave every pre-existing dirty file untouched.
