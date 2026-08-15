# Agent Pet Case Study

## One-sentence summary

Agent Pet is a local personal LLM Wiki and memory graph for one Windows user:
it turns a conversation or local source into evidence-backed, correctable
context that can be reused in a later session.

## The business problem, without technology language

A personal knowledge worker loses time in three places: repeating the same
project context, searching several note locations for the source of a decision,
and repairing a wrong assistant memory after it has already influenced a later
answer. A model that merely answers the current turn does not solve any of
these durable problems. A notes app alone does not extract or connect the
context in the language the user naturally provides.

The product therefore targets a closed decision loop:

```text
capture -> review -> activate -> recall with source -> correct/forget -> verify
```

The loop is useful even when the provider is offline because the local Vault,
SQLite authority and FTS fallback remain browsable.

## Users and workflow

The external workflow is intentionally single-user: bind an isolated Vault,
chat or import a source, review a candidate, confirm a low-risk statement, ask
the same question in a new conversation, then correct or forget it. An internal
trial uses the same path for one employee and records only anonymous event
counts. There is no team sharing, tenant administration or employee-monitoring
workflow in the product.

## Why AI, and why not let it execute

Natural language makes extraction, alias resolution, query planning and
multi-source synthesis cheaper for a human than filling a graph form. Those
steps are non-deterministic and are bounded by typed schemas and budgets.

Authorization, sensitive filtering, identity uniqueness, lifecycle transitions,
Markdown hashes, idempotency, receipt verification, deletion and fallback are
deterministic. This split is the safety argument: a model can propose “this
looks like a preference about Project X”, but it cannot grant recall permission
or write a page without the coordinator and reader agreeing.

## Architecture decisions

1. **SQLite is the graph authority.** It stores normalized entities, aliases,
   facts, controlled relations, evidence, lifecycle and recall permission.
2. **Markdown is the portable text authority.** Immutable source bytes and
   user-readable Wiki pages stay inspectable outside the app.
3. **The graph is a memory contract, not a keyword picture.** Relations are
   limited to the documented vocabulary and require evidence/confidence; shared
   words cannot create `related_to` edges.
4. **Kuzu is rebuildable.** It accelerates one/two-hop traversal only after a
   fresh SQLite authorization pass; missing or stale projection falls back to
   SQLite and reports degradation.
5. **Covered writes use one coordinator.** The primary task and post-reply
   memory/Wiki paths use `ActionLifecycleCoordinator` to claim before effect,
   read the target back and return a verified receipt. A crashed effect is
   recovered by target identity, not replayed blindly. Memory feedback, profile,
   hygiene, retrospective and continuity-proposal writes still have direct
   mutation paths and are not presented as covered.
6. **The model path is bounded.** Ordinary chat uses a fast path; evidence
   negotiation has one sequential read-only retrieval dispatch per round and a
   single synthesizer outlet.

## What each technology contributes

| Technology | Concrete problem solved | Evidence / boundary |
| --- | --- | --- |
| Electron | Keep a tray companion, manage sidecar and preload trust boundary | `apps/desktop/electron`; Windows local only |
| React/TypeScript | Keep graph, timeline, sources and failure states in one typed workspace | `apps/desktop/src`; typecheck does not prove visual completion |
| `@xyflow/react` | Reuse graph pan/zoom/selection for the evidence rail | `MemoryGraphWorkspace.tsx`; it cannot validate facts |
| FastAPI/Pydantic/Uvicorn | Local API, schema validation, auth and health boundary | `apps/backend/app/api`; not a cloud service |
| LangChain/LangGraph | Provider/tool adaptation and bounded stateful orchestration | `graph_runtime.py`; no unlimited or parallel agents |
| SQLite | One authority for graph, lifecycle, receipts and metrics | migrations 020-024; single local store |
| Markdown Vault | Human-readable, portable sources and Wiki body | `services/wiki`; hash conflicts stop writes |
| FTS5 | Reliable no-service retrieval and fallback | `services/retrieval.py`; lexical baseline only |
| Kuzu | Rebuildable graph traversal acceleration | `memory_graph_kuzu.py`; never authority |
| Qdrant | Optional candidate-scale experiment | no accepted quality promotion; not default |
| APScheduler/SQLAlchemy | Persist reminders and catch up after resident restart | local process; sleep/offline remains possible |
| SSE | Stream progress, citations and terminal status | transport UX only; not correctness proof |

## Evidence and measured baseline

The reproducible combined evaluator has a 60-case FTS fixture (50 answerable,
10 no-evidence cases) and an independent L2 synthetic graph fixture. The
retained report records:

| Metric | Result | Interpretation |
| --- | ---: | --- |
| FTS Recall@5 | `24.8/50 = 0.496` | production SQLite FTS macro average; threshold `0.80`, `Failed` |
| Citation coverage | `0/0` | evaluator retrieves candidates but does not generate/judge answers; `insufficient_sample` |
| No-evidence accuracy | `10/10 = 1.00` | threshold `1.00`, `Passed`; synthetic fixture only |
| False activation | `0/10 = 0` | threshold `0`, `Passed`; synthetic fixture only, not a user rate |
| SQLite/Kuzu/missing-projection fallback | `21/21` each | `Passed`; L2 synthetic fixture only |
| Graph lifecycle | `27/27` | `Passed`; L2 synthetic fixture only |
| Deterministic graph baseline | `37/37` | zero model calls and zero external requests; L2 synthetic fixture only |
| Correction propagation | `3/3` | value `1.00`, but `insufficient_sample` because the minimum is `20` |
| LLM extraction/synthesis | sample `0` | `not_run`; quality, latency and cost are not inferred |

The graph fixture passes do not prove that Kuzu improves semantic retrieval,
production reliability or business outcomes. FTS remains below its required
threshold, citation coverage has no usable denominator, correction propagation
is undersampled and the LLM ablation was not run, so the combined evaluator
remains failed with exit code `1`.

The runtime lifecycle wiring tests verify one shared coordinator and a
verified receipt before the covered task and post-reply memory/Wiki adapters
return. Checkpoint tests verify original-target approval, rejection with zero
effect, terminal replay and effect-before-receipt recovery. These are mechanism
and local integration results, not an estimate of time saved or revenue; the
direct mutation paths listed above remain a coverage gap.

## Failure-driven design

The demo pairs each success with a boundary:

- citation-backed recall / empty search and explicit no-evidence response;
- confirmed low-risk page / Markdown hash conflict and `failed_recovery`;
- approved Wiki checkpoint / rejected checkpoint with zero effect;
- Kuzu traversal / missing projection with SQLite fallback;
- sidecar health after a restart / Electron supervisor and sleep scenarios
  marked unverified;
- reminder trigger / OS permission denial with a manual retry state.

The latest combined fault matrix is `15 Passed`, `0 Failed`, `3 Partial`.
Four passes use real isolated sidecar/API paths and eleven use a deterministic
backend fault harness. The three Partial scenarios are packaged Electron
sidecar crash, real Windows sleep/resume and Windows notification-permission
denial; a harness pass is not packaged Electron evidence. The development-browser visual runner passed
graph/timeline/sources at four widths, with no automatic overflow, focus,
contrast or reduced-motion failure. The overall visual gate remains Partial
because packaged Electron, Windows DPI and manual failure-state review are open.

## Limits and honest project assessment

The ordinary chat path is close to a model API call. The repository becomes
more than that only when the user exercises the persistent Wiki/graph lifecycle
and the deterministic recovery boundary. It currently does not prove a
general business KPI, hosted availability, universal answer accuracy, or a
quality gain from Kuzu/Qdrant. The frozen audit is `57/100`; the last
independently audited score is `62/100` (2026-08-11). The 2026-08-14 L3 journeys
have not yet received a whole-tier rescore. A reported score above `84` requires
real 24-hour and 7-day evidence before any external claim.
