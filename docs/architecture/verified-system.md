# Verified System Architecture

Status: aligned with the code after the 2026-07 dead-code removal
(fix backlog #11). This page describes only paths that execute in the
shipped product; the previously documented Supervisor/Reviewer planning
system was unreachable and has been deleted from the codebase.

## Runtime shape

```text
User request
  -> deterministic keyword router
      -> streaming chat fast path (default; no graph execution)
      -> negotiation path (opt-in via use_negotiation)
          -> Orchestrator (model-backed, bounded rounds)
          -> single read-only Retrieval Agent dispatch per round
          -> deterministic evidence merge into collected context
          -> Synthesizer (model-backed reply through the chat outlet)

Side-effect request
  -> Action-Proposal (model-backed, typed proposal only)
  -> deterministic Policy Guard
      -> low-risk approved execution
      -> high-risk persisted checkpoint and human decision
  -> deterministic Executor (idempotency, receipts)
  -> read-only Verifier role (receipt-bound verification)

Foreground completion
  -> managed Reflection role job (typed proposals only)
  -> the same deterministic policy boundary before any write
```

There is no supervisor planning graph, no independent reviewer gate, and
no parallel specialist dispatch. The negotiation orchestrator can dispatch
exactly one specialist (retrieval); any other request falls back to the
sequential path.

## Agent and deterministic boundaries

| Component | Classification | Authority |
| --- | --- | --- |
| Semantic analysis | model-backed classifier (conditional) | classification only |
| Negotiation Orchestrator | model-backed Agent | dispatch retrieval or synthesize; bounded rounds |
| Retrieval dispatch | model-backed specialist | approved read tools only |
| Chat/Synthesizer | model-backed Agent | the only natural-language outlet |
| Action Proposal | model-backed Agent | typed proposal only; no adapter access |
| Verifier | model-backed read-only role | receipt-bound verification input |
| Reflection | managed model-backed role | typed proposals only |
| Router, registry, merger | deterministic components | routing, validation, accounting |
| Policy Guard, Executor, checkpointer | deterministic components | side-effect authorization, execution, idempotency, HITL persistence |

## Storage and retrieval truth

SQLite and Markdown are authoritative. FTS5 is the production retrieval
default in code and configuration (`RetrievalService.search` defaults to
`mode="fts"`). Qdrant vector generations and the Kuzu graph mirror are an
optional derived acceleration layer behind the `vector` package extra;
every import of them is lazy and absence degrades gracefully. The
evaluated hybrid and reranker candidates remain Defer after TASK-1215.

## Security boundary

Renderer code has no Node, filesystem, bearer-token, or raw checkpoint
access. Electron main injects authentication only for allowlisted loopback
API routes, and the allowlist is enforced against the backend route table
by `tests/test_renderer_allowlist_contract.py`. High-risk actions persist
a minimized decision record and execute only after an authenticated,
bound, unexpired human decision. Rejection, expiry, and replay are
fail-closed.
