# Claim Evidence Index

Status: current repository claims with a runtime entry, a code path and a
named verification boundary. A mechanism is not promoted to a product result
when its sample, environment or user denominator is missing.

## Product claim boundary

Agent Pet is a local personal LLM Wiki and memory graph for one Windows user.
Ordinary chat may use a fast model path; the durable product contract is the
source -> entity -> fact/relation -> Wiki -> cited recall -> correction/forget
lifecycle. SQLite and Markdown are authoritative. FTS5 is the default retrieval
path; Kuzu and Qdrant are derived/optional acceleration layers.

| Public claim | What is actually true | Runtime entry | Evidence |
| --- | --- | --- | --- |
| Local personal desktop workflow | Electron manages a loopback sidecar, tray/preload boundary and local data directory; configured providers may receive policy-approved non-private text | `apps/desktop/electron/main.cjs`; `apps/backend/app/sidecar_entry.py` | `output/verification/packaged-app-smoke.json` (local package smoke only) |
| LLM Wiki lifecycle | Sources remain immutable; typed entities, facts/relations, page bindings and lifecycle live in SQLite; Markdown holds readable pages. Migration smoke preserves the legacy fact and candidate rows (`1 -> 1` each), with zero foreign-key errors and no reapplied versions | `apps/backend/app/services/wiki/`; `apps/backend/app/services/memory_entity_graph.py` | `apps/backend/app/resources/wiki/AGENTS.md`; `output/verification/LLMWIKI-006/journey/wiki-journey-report.json`; `output/verification/LLMWIKI-013/migration/migration-report.json` |
| Bounded AI assistance | LangGraph runtime has a fast chat path and an opt-in Orchestrator -> one sequential read-only Retrieval Agent -> Synthesizer path | `apps/backend/app/agents/graph_runtime.py` | `apps/backend/tests/test_agent_runtime_routing.py`; `apps/backend/tests/test_agent_runtime_negotiation.py` |
| AI/deterministic separation | The model proposes extraction, disambiguation, retrieval plans and synthesis; deterministic code owns policy, writes, permissions, idempotency and receipts | `apps/backend/app/agents/nodes/policy_guard.py`; `apps/backend/app/agents/nodes/executor.py` | `apps/backend/tests/test_action_lifecycle_wiring.py` |
| Shared action lifecycle (covered paths) | `ActionLifecycleCoordinator` is wired into the primary task and post-reply memory/Wiki paths; focused tests and the isolated action journey prove claim-before-effect, authoritative read-back and receipt recovery. Memory feedback, profile, hygiene, retrospective and continuity-proposal writes remain direct mutation gaps | `apps/backend/app/api/services/adapters.py` (`production_action_lifecycle`) | `apps/backend/tests/test_action_lifecycle_wiring.py`; `apps/backend/tests/test_production_action_recovery.py`; `output/verification/LLMWIKI-002/action-journey-report.json` |
| High-risk approval recovery | Supported checkpoint targets preserve the original proposal and revalidate policy before executing; rejection has zero effect; a decision-committed/action-pending crash window repairs the same action row; unsupported targets fail closed | `apps/backend/app/agents/graph_runtime.py` (`resume_checkpoint`) | `apps/backend/tests/test_production_checkpoint_resume.py`; `output/verification/LLMWIKI-002/action-journey-report.json` |
| Evidence-gated graph recall | Graph details expose evidence/lifecycle/actions; one/two-hop traversal filters status, sensitivity and permission before prompt use | `apps/backend/app/api/memory/graph.py`; `apps/backend/app/services/memory_entity_graph.py` | `apps/backend/tests/test_memory_entity_graph.py`; `apps/backend/tests/test_memory_graph_services.py` |
| Rebuildable Kuzu projection | Kuzu is read-only, generation-aware and checked against fresh SQLite authorization; missing/corrupt/stale projection returns SQLite fallback with a reason | `apps/backend/app/services/memory_graph_kuzu.py` | `apps/backend/tests/test_memory_graph_kuzu.py`; `output/verification/LLMWIKI-011/eval-20260814/report.json`; `output/verification/LLMWIKI-013/faults/fault-matrix-report.md` |
| Correct and forget propagation | Correct creates a replacement claim plus `supersedes`; forget/archive revokes derived recall/artifacts | `apps/backend/app/services/memory_entity_graph.py`; `apps/backend/app/api/memory/graph.py` | `apps/backend/tests/test_memory_entity_graph.py`; `apps/desktop/src/views/MemoryWindowView.test.tsx`; `output/verification/LLMWIKI-004/journey-report.json` |
| Privacy-preserving local metrics | Events are allowlisted, idempotent, subject-hashed and aggregated with numerator/denominator/sample status | `apps/backend/app/services/product_metrics.py`; `apps/backend/app/api/metrics.py` | `apps/backend/tests/test_product_metrics.py`; `output/verification/LLMWIKI-011/eval-20260814/report.json` |
| FTS retrieval baseline | Fixed synthetic evaluator provides a reproducible control, not a live-model or general accuracy claim | `apps/backend/app/evals/retrieval_eval.py` | `output/verification/LLMWIKI-011/eval-20260814/report.json` and `docs/evals/retrieval-failure-analysis.md` (`agent-pet-retrieval-synthetic-v1.0.0`) |
| Resident recovery candidate | Login startup, bounded sidecar restart and reminder catch-up mechanisms exist; sleep/notification and real time behavior are not fully verified | `apps/desktop/electron/resident.js`; `apps/backend/app/services/reminder_delivery.py` | `output/verification/frozen-sidecar-lifecycle.json` (20-cycle smoke); `output/verification/LLMWIKI-013/faults/fault-matrix-report.md` |
| Memory workspace automatic visual gate | Graph, timeline and sources (12 states) passed nonblank, overflow, focus, contrast and reduced-motion checks at 390/1280/1366/1920 widths in authenticated Chrome against Vite | `apps/desktop/src/views/MemoryWindowView.tsx`; `scripts/verify-llmwiki-visual.mjs` | `output/verification/LLMWIKI-013/visual/visual-report.json`; development-browser evidence only, while packaged Electron, Windows DPI and manual failure states remain `Partial` |

## Measured values and interpretation

The frozen audit baseline is `57/100`. The last independently completed
whole-tier review, dated 2026-08-11, gives raw/reported `62/100`; the calculation
and missing promotion gates are recorded in
`output/verification/LLMWIKI-013/final-score-20260811.md`. New 2026-08-14 L3
journeys have not yet been independently rescored, and test count alone does
not raise the score.

The current canonical report is `output/verification/LLMWIKI-011/eval/report.json`;
the dated `eval-20260814` directory is the immutable run snapshot. Both are
generated by `scripts/verify_llmwiki_metrics.py`, which calls the production
retrieval evaluator and the deterministic graph evaluator against versioned
synthetic fixtures. FTS Recall@5 is `24.8/50 = 0.496`
(`Failed`), no-evidence accuracy is `10/10 = 1.00` (`Passed`), and false
activation is `0/10 = 0` (`Passed`). The retrieval evaluator does not generate
or judge answers, so citation coverage is `0/0` and `insufficient_sample`.

SQLite graph traversal, Kuzu traversal and missing-projection SQLite fallback
each pass `21/21`, and graph lifecycle passes `27/27`; the deterministic graph
baseline passes `37/37` with zero model calls and zero external requests. These
are L2 synthetic-fixture results, not evidence that Kuzu improves semantic
retrieval quality, production reliability or business outcomes. Correction
propagation is `3/3`, but remains
`insufficient_sample` because the minimum is `20`. LLM extraction/synthesis is
`not_run`. The combined evaluator therefore exits `1`. None of these values
proves saved minutes, retention, revenue or business uplift; business uplift
remains unproven.

The local metrics API records feedback and operational events without raw
source text. A 7-day trial must provide real denominators before any percentage
is interpreted. A real 24-hour soak must provide health samples, restart/recovery
latency, backlog, duplicate-effect count and projection lag; a 20-cycle smoke
is not a substitute.

The automatic memory-workspace report passed four widths and three tabs, but it
does not close the visual release gate. It did not validate packaged Electron,
physical 100/125/150% DPI, OS notification permission, sleep/wake or a manual
review of every conflict, offline and recovery state.

## Deliberately unclaimed

- Not claimed: hosted or enterprise availability, multi-user tenancy or RBAC;
- Not claimed: universal accuracy, zero hallucination or guaranteed refusal;
- Not claimed: unlimited/multi-agent autonomy, a Supervisor graph or parallel expert swarm;
- Not claimed: a default vector/hybrid promotion or a graph-specific business gain;
- Not claimed: notification delivery (only a display attempt can be recorded);
- Not claimed: clean-VM launch, physical DPI matrix, real sleep/wake behavior;
- Not claimed: a general business improvement percentage before the 7-day protocol.

Run `scripts/check-portfolio-claims.ps1` before copying any wording to a resume,
demo, release note or interview answer. The scanner treats a sentence that
explicitly says “not claimed”, “unverified”, “Partial”, or “evidence
insufficient” as a limitation; an unqualified promotional sentence fails.
