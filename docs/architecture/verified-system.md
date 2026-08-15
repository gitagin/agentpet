# Verified System Architecture

Status: current implementation boundary for the local personal LLM Wiki and
memory graph MVP. This document describes code paths that are reachable from
the shipped local runtime and labels optional, test-only and unverified paths.
It is an evidence document, not a feature wish list.

## Product contract

The system solves one narrow problem: a Windows user can carry an auditable
piece of project context from one conversation to another without turning every
model utterance into a permanent fact. The main loop is:

```text
immutable source -> typed entity -> fact/relation -> page synthesis -> decision
       ^                                                        |
       +----------- citation, correction, supersedes, forget ---+
```

The supported user is one local user. A configured remote model may receive
policy-approved non-private input; SQLite, the Vault and the Electron trust
boundary remain local. There is no team tenancy or hosted availability contract.

## Runtime topology

```text
Electron main/preload
  -> allowlisted loopback HTTP + SSE (bearer injected in main only)
  -> FastAPI/Uvicorn sidecar
      -> deterministic request/auth/schema boundary
      -> LangGraphAgentRuntime
          -> route + semantic analysis
          -> streaming chat fast path (ordinary chat, no evidence required)
          -> bounded negotiation path (opt-in)
              -> Orchestrator
              -> at most one sequential read-only Retrieval Agent per round
              -> deterministic evidence merge and budget check
              -> Synthesizer / single chat outlet
          -> post-reply memory/Wiki proposal jobs
      -> ActionLifecycleCoordinator
          -> durable claim
          -> adapter effect
          -> authoritative reader
          -> receipt + verification
      -> SQLite authority and Markdown Vault
          -> FTS5, optional Qdrant candidates, optional Kuzu projection
```

Ordinary chat can therefore still be a direct provider call. The product is not
defined by that call; it is defined by the persistent source/evidence/lifecycle
contract around memory and Wiki operations.

## Agent versus deterministic authority

| Role/component | Kind | Allowed responsibility | Explicitly not allowed |
| --- | --- | --- | --- |
| Semantic analyzer | model-backed with deterministic fallback | classify intent and suggest parameters | authorize a write or invent evidence |
| Orchestrator | model-backed, bounded | choose an approved read tool and plan a query | arbitrary tools, parallel fan-out or policy bypass |
| Retrieval Agent | model-backed specialist | read-only search over approved scopes | mutation, memory activation or source disclosure outside scope |
| Synthesizer | model-backed | compose a response from accepted evidence | cite a rejected/expired item or create a receipt |
| Entity extractor/disambiguator | model-backed proposal | suggest typed entities, aliases and relation candidates | merge identities without deterministic validation |
| Wiki synthesizer | model-backed proposal | fill a page-type-specific outline from evidence | write directly to Markdown |
| Router, merger, budgets | deterministic | route, validate, cap rounds/context and own terminal state | generate natural-language facts |
| Policy Guard | deterministic | risk, consent, sensitive-content and confirmation decision | infer user permission from tone |
| ActionLifecycleCoordinator | deterministic, shared runtime service | claim before effect, stable idempotency, reader, receipt and recovery | execute an unclaimed adapter |
| Kuzu service | deterministic projection | rebuild and accelerate authorized traversal | become authority for status or recall permission |

The runtime factory creates one coordinator and makes it available to task,
memory, continuity, Wiki and workflow adapters. `allow_ephemeral_lifecycle` is
false in that runtime, but the current focused evidence covers the primary task
and post-reply memory/Wiki paths only. Memory feedback, profile actions, hygiene
actions, retrospective reports and continuity proposal creation still contain
direct domain writes outside the coordinator. The wiring and receipt assertions
live in `apps/backend/tests/test_action_lifecycle_wiring.py`; checkpoint approval,
replay and effect-before-receipt recovery are covered by
`test_production_checkpoint_resume.py` and `test_production_action_recovery.py`.

## Data authority and graph model

SQLite is authoritative for:

- normalized entities, aliases and the controlled entity types `self`, `person`,
  `project`, `preference`, `boundary`, `goal`, `event`, `concept`, `source`,
  `wiki_page` and `decision`;
- facts, typed relations, evidence, lifecycle state, conflict/supersession and
  recall permissions;
- Wiki bindings, action claims/receipts, reminders, post-reply jobs and
  privacy-preserving metric events;
- `graph_source_state` and Kuzu projection generations.

Markdown is authoritative for the bytes of an immutable source and for the
user-readable Wiki body. A page must retain frontmatter, source references,
revision and lint state. `apps/backend/app/resources/wiki/AGENTS.md` is the
page contract: page types are `source`, `entity`, `concept`, `synthesis`,
`comparison`, `decision` and `report`; optional sections are omitted rather
than filled with empty placeholders.

The relation vocabulary is deliberately small:
`prefers`, `avoids`, `works_on`, `knows`, `related_to`, `occurred_in`, `supports`,
`contradicts`, `supersedes`, `derived_from` and `documented_in`. Every automatic
relation carries evidence, confidence, lifecycle and recall permission.
Keyword co-occurrence is not a relation generator.

## Kuzu projection protocol

`apps/backend/app/services/memory_graph_kuzu.py` builds a complete temporary
generation from a consistent SQLite snapshot, publishes it only when the
source revision is unchanged, and opens it read-only. A traversal first runs a
fresh SQLite authorization pass. Kuzu relation IDs must match that pass before
the result can be labeled `source="kuzu"`; missing dependency, corrupt files,
stale generation or authorization mismatch returns the SQLite result with a
degradation reason. Removing Kuzu cannot remove a fact or change its lifecycle.

This is a graph acceleration mechanism, not a claim that graph traversal has
beaten FTS on business tasks. The current production FTS evaluator reports
Recall@5 `24.8/50 = 0.496`; it does not generate or judge answers, so citation
coverage is `0/0` (`insufficient_sample`). Kuzu acceleration and SQLite graph
fallback are not run by this fixture, and no accepted live or semantic vector
promotion report exists.

## Action lifecycle and recovery

For every registered and currently covered runtime side effect, the coordinator
executes this state machine:

```text
claimed -> executing -> verifying -> completed(verified receipt)
    |          |             |
    +----------+-------------+--> failed_recovery / manual_review
```

1. Validate proposal/policy binding and canonical payload hash.
2. Persist the claim and idempotency key before calling an adapter.
3. Execute the adapter once for the stable target.
4. Read the target back through its authoritative reader.
5. Persist and return the receipt only after verification.
6. On a repeated request, replay the terminal receipt; on a crash, read the
   target first. A unique match reconstructs the receipt; zero, multiple or
   ambiguous matches stop in recovery rather than replaying.

Supported high-risk checkpoints preserve the original proposal and policy.
Approval revalidates the current policy and executes the same proposal through
the coordinator. Rejection has zero side effect. Unsupported or destructive
targets fail closed as `failed_recovery`; approval is not permission to invent
a new target.

## Retrieval and prompt boundary

FTS5 is the default candidate source because it is local, deterministic and
available without another service. Optional Qdrant vectors are derived
candidates and are not enabled by default. Graph retrieval is limited to one or
two hops and an explicit character/item budget. Before prompt assembly,
candidate facts are filtered by lifecycle, sensitivity, conflict, expiry,
Vault scope and recall permission. Citations are validated against the accepted
evidence set after synthesis. No-evidence responses stay no-evidence.

## Desktop trust and resident behavior

Renderer code has no Node, filesystem, token or raw checkpoint access. Electron
main injects authentication only for generated allowlisted routes; preload
exposes a narrow IPC surface. The resident runtime can start at login, keep a
bounded sidecar restart budget, and catch up persisted tasks after recovery.
Sleep and shutdown are offline intervals. Notification delivery records a
reservation and display attempt; OS permission denial or an unknown result is
shown as retryable, not as delivered.

## Evidence status and limitations

Current evidence includes an exhaustive four-shard backend run retained at
`output/verification/LLMWIKI-013/quality/backend-full-20260814-sharded.json`
(`1193 passed, 2 skipped, 0 failed`), Mypy over 213 source files and Ruff success,
migration smoke for empty/legacy/repeat databases that preserved the legacy
fact and candidate rows (`1 -> 1` each) with zero foreign-key errors and no
reapplied migration versions, a `5/5` authenticated action journey, passed
restart memory and source-to-decision Wiki journeys, four passed real
sidecar/API fault scenarios, eleven passed deterministic backend fault-harness
scenarios, and local packaged sidecar smoke. The combined fault matrix is
`15 Passed / 0 Failed / 3 Partial`;
the three open scenarios are packaged Electron sidecar crash, real Windows
sleep/resume and Windows notification-permission denial. Backend-harness passes
do not prove packaged Electron or Windows manual behavior. The
authenticated Vite + Chrome visual runner at
`output/verification/LLMWIKI-013/visual/visual-report.json` passed graph/timeline/sources at four
widths, including overflow, focus, contrast and reduced-motion checks; packaged
Electron, Windows 100/125/150% DPI and manual failure-state review remain open.
There is no real 24-hour soak, 7-day trial, clean-VM launch record or
live-provider quality campaign. Those gaps cap public claims and the reported
score at 84 or below until they are actually measured.

Evidence paths:

- Wiring and recovery: `apps/backend/tests/test_action_lifecycle_wiring.py`,
  `apps/backend/tests/test_production_checkpoint_resume.py`,
  `apps/backend/tests/test_production_action_recovery.py`,
  `output/verification/LLMWIKI-002/action-journey-report.json`.
- Memory and Wiki journeys: `output/verification/LLMWIKI-004/journey-report.json`,
  `output/verification/LLMWIKI-006/journey/wiki-journey-report.json`.
- Graph API and projection: `apps/backend/app/api/memory/graph.py`,
  `apps/backend/app/services/memory_graph_kuzu.py`.
- Synthetic metrics: `output/verification/LLMWIKI-011/eval-20260814/report.json`.
- Backend quality: `output/verification/LLMWIKI-013/quality/backend-full-20260814-sharded.json`.
- Fault and visual status: `output/verification/LLMWIKI-013/faults/fault-matrix-report.md`,
  `output/verification/LLMWIKI-013/visual/visual-report.json`.
