# Agent Pet Case Study

## Problem

Agent Pet explores a local-first desktop companion that can retain useful
context without hiding where memory came from or allowing model output to write
freely. The engineering problem is therefore not only chat quality: memory,
citations, action safety, user confirmation, recovery, and renderer isolation
must agree on one auditable contract.

## Architecture decisions

The runtime separates bounded model-backed roles from deterministic control.
Simple chat uses a fast path. The opt-in negotiation path runs an Orchestrator,
at most one read-only retrieval dispatch per round, and a Synthesizer. Memory
and Wiki drafts have domain-specific review, but there is no independent global
Reviewer, Supervisor graph, or parallel specialist dispatch. Routing, budgets,
evidence merge, policy, side-effect execution, receipt verification,
idempotency, and terminal ownership remain deterministic.

SQLite and Markdown are authoritative. FTS5 remains the safe production Agent
default. Optional Qdrant generations and rank fusion are implemented as derived
candidates. A retained local Qdrant Server scaling run covers query latency, not
semantic quality; no accepted quality report promotes vector or hybrid modes.

High-risk actions stop before the Executor, persist a minimized checkpoint, and
require an authenticated decision bound to the checkpoint, proposal, policy,
and expiry. Renderer code sees only a safe projection.

## Verification status

The repository contains a fixed synthetic retrieval corpus and an executable
evaluation pipeline for FTS and optional vector/rank-fusion controls. The local
feature-hash vectors and identity reranker are diagnostic controls, not semantic
or learned-quality evidence. Generated measurements are reported only with
their command and boundary. The retained
`output/evals/fix-backlog-16/vector-query-scaling.json` run compares 2,048 and
32,768 points against Qdrant Server 1.17.0 and passes the repository's p95
non-linear-growth gate. It does not measure embedding or answer quality. The
current production default remains FTS because no accepted promotion report
proves the optional modes meet the safety and quality gates.

## Failure-driven corrections

1. Public reasoning fields reached the Renderer. TASK-1203 replaced them with
   a versioned safe trace allowlist.
2. Optional hybrid retrieval has no accepted promotion report. FTS stayed the
   default rather than treating a diagnostic control as product evidence.
3. The checkpoint backend API existed, but Electron denied it because the main
   process proxy allowlist omitted the route. Exact checkpoint routes and
   negative allowlist tests were added without exposing the session token.

## Limitations

There is no accepted live-provider quality campaign, clean-Windows-VM launch
record, physical multi-display DPI matrix, or final hybrid/reranker promotion.
Repository evidence describes the implementation and verification; this page
does not claim sole authorship for all code or third-party framework behavior.
