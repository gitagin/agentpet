# Agent Pet Case Study

## Problem

Agent Pet explores a local-first desktop companion that can retain useful
context without hiding where memory came from or allowing model output to write
freely. The engineering problem is therefore not only chat quality: memory,
citations, action safety, user confirmation, recovery, and renderer isolation
must agree on one auditable contract.

## Architecture decisions

The runtime separates model-backed specialist roles from deterministic control.
Retrieval, analysis, review, proposal, verification, synthesis, and reflection
have typed role contracts. Routing validation, budgets, evidence merge, policy,
side-effect execution, idempotency, and terminal ownership remain deterministic.

SQLite and Markdown are authoritative. FTS5 remains the safe production Agent
default. Vector generations and rank fusion were implemented and measured as
derived candidates, but the final quality gate did not pass, so they were not
promoted to the default path.

High-risk actions stop before the Executor, persist a minimized checkpoint, and
require an authenticated decision bound to the checkpoint, proposal, policy,
and expiry. Renderer code sees only a safe projection.

## Measured results

The fixed 60-case synthetic retrieval evaluation recorded FTS Recall@10
`0.496`, hybrid RRF Recall@10 `0.672`, and a keyword-free delta of `+0.226667`.
Hybrid no-evidence accuracy was `0.000`, so TASK-1215 remained Defer. The
narrowed TASK-1216 run passed 87 backend scenarios, 403 desktop tests after the
checkpoint proxy repair, Electron contract checks, production build, isolated
smoke, and user-confirmed functional paths.

## Failure-driven corrections

1. Public reasoning fields reached the Renderer. TASK-1203 replaced them with
   a versioned safe trace allowlist.
2. Hybrid retrieval improved semantic recall but failed no-evidence safety.
   FTS stayed the default instead of promoting the higher average score.
3. The checkpoint backend API existed, but Electron denied it because the main
   process proxy allowlist omitted the route. Exact checkpoint routes and
   negative allowlist tests were added without exposing the session token.

## Limitations

There is no accepted live-provider five-run campaign, packaged executable
launch evidence, full viewport/DPI matrix, or final hybrid/reranker promotion.
The known Wiki fallback regression remains separately recorded. Repository
evidence describes the implementation and verification; this page does not
claim sole authorship for all code or third-party framework behavior.
