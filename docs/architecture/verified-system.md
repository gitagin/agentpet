# Verified System Architecture

Status: public claim boundary for the 2026-07-13 checkout.

## Runtime shape

```text
User request
  -> deterministic router
      -> simple chat fast path when retrieval or action is unnecessary
      -> bounded Supervisor planning path otherwise
          -> Vault Retrieval Agent (read only)
          -> Structured Memory Agent (read only)
          -> deterministic evidence merge
          -> Analyst/Planning Agent
          -> independent Reviewer Agent
          -> Synthesizer Agent

Side-effect request
  -> Action-Proposal Agent
  -> deterministic Policy Guard
      -> low-risk approved execution
      -> high-risk persisted checkpoint and human decision
  -> deterministic Executor
  -> read-only Verifier Agent

Foreground completion
  -> managed Reflection Agent job
  -> the same deterministic policy boundary before any write
```

Read branches may overlap only when the opt-in parallel gate is enabled. The
default remains sequential, and write-capable work is never parallelized.

## Agent and deterministic boundaries

| Component | Classification | Authority |
| --- | --- | --- |
| Vault Retrieval | model-backed specialist Agent | approved read tools only |
| Structured Memory | model-backed specialist Agent | approved read tools only |
| Analyst/Planning | model-backed Agent | no write authority |
| Reviewer | independent model-backed Agent | pass, one retry/replan, clarify, or reject; no confirmation authority |
| Action Proposal | model-backed Agent | typed proposal only; no adapter access |
| Verifier | model-backed/read-only role | receipt-bound verification input |
| Synthesizer | model-backed Agent | approved claims and citations only |
| Reflection | managed model-backed Agent | typed proposals only |
| Router, registry, budget manager, merger | deterministic components | routing, validation, accounting, merge |
| Policy Guard, Executor, ledger, terminal arbiter | deterministic components | side-effect authorization, execution, idempotency, terminal ownership |

## Storage and retrieval truth

SQLite and Markdown are authoritative. FTS5 is the production-safe Agent
retrieval default. Qdrant/vector generations are optional derived acceleration
and can be rebuilt or bypassed. The evaluated hybrid and reranker candidates
remain Defer after TASK-1215; they are not default product claims.

## Security boundary

Renderer code has no Node, filesystem, bearer-token, or raw checkpoint access.
Electron main injects authentication only for allowlisted loopback API routes.
High-risk actions persist a minimized decision record and execute only after an
authenticated, bound, unexpired human decision. Rejection, expiry, and replay
are fail-closed.
