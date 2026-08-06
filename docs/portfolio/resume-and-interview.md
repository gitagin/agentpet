# Resume and Interview Wording

Status: candidate wording pending final user approval.

## Resume bullet

Built and evaluated a local-first Electron/FastAPI AI companion with a bounded
LangGraph negotiation workflow, FTS-backed cited retrieval, deterministic
side-effect policy and idempotency, and persistent human approval for high-risk
actions; kept optional hybrid/reranker candidates disabled because no accepted
promotion report proves they satisfy the repository quality and safety gates.

## Interview summary

The main design choice was to separate bounded model-backed roles from
deterministic control. The shipped negotiation path has an Orchestrator, one
read-only retrieval dispatch per round, and a Synthesizer; memory and Wiki
drafts have domain-specific review. It has no independent global Reviewer,
Supervisor graph, or parallel specialist path. Policy, execution, receipt
verification, ledger claims, budgets, and terminal ownership are deterministic.
SQLite and Markdown hold authoritative state; vector infrastructure is
rebuildable.

## Expected challenges

- Why not enable hybrid by default? No retained promotion report proves the
  optional path satisfies both retrieval-quality and no-evidence safety gates,
  so the safer FTS path remains the default.
- Is specialist work parallel? No. The shipped negotiation path dispatches at
  most one read-only retrieval specialist per round.
- Is HITL native LangGraph interrupt? The product uses a persisted,
  authenticated pending-action checkpoint boundary. Public wording must not
  claim a second native saver or raw graph-state exposure.
- What is packaged evidence? The frozen sidecar and packaged Electron app pass
  local no-Python-PATH smoke checks. A clean Windows VM and physical multi-DPI
  display matrix remain unclaimed.

The wording above describes repository evidence and should be adapted to the
actual contributor's role before external use.
