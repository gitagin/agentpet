# Claim Evidence Index

Status: current repository claims with direct code or test evidence.

The simple social chat may use a fast path. SQLite and Markdown are authoritative;
vector indexes are optional derived acceleration.

| Public claim | Qualification | Repository evidence |
| --- | --- | --- |
| Local-first Windows companion | Local sidecar and authoritative local stores; configured remote models may receive policy-approved non-private requests | `apps/backend/app/sidecar_entry.py`; `apps/backend/app/storage/database.py`; `apps/desktop/electron/sidecar.js` |
| Bounded model-backed workflow | Model-backed roles are bounded; routing, policy, execution, budgets, and terminal ownership are deterministic | `apps/backend/app/agents/graph_runtime.py`; `apps/backend/app/agents/contracts.py`; `apps/backend/tests/test_agent_runtime_negotiation.py` |
| Evidence-gated local retrieval | FTS is the production default; accepted evidence is filtered before prompt use and rendered citations are validated | `apps/backend/app/agents/retrieval/compression.py`; `apps/backend/tests/test_retrieval_grounding.py` |
| Persistent high-risk decision resume | Deterministic pending-action checkpoint gate; not a second native LangGraph saver | `apps/backend/app/agents/checkpointer.py`; `apps/backend/tests/test_agent_checkpoint_integration.py`; `apps/backend/tests/test_agent_interrupt_resume.py` |
| Deterministic action safety | Policy Guard, Executor, ledger, idempotency, and Verifier are deterministic boundaries | `apps/backend/app/agents/nodes/policy_guard.py`; `apps/backend/app/agents/nodes/executor.py`; `apps/backend/tests/test_agent_action_lifecycle.py` |
| Reproducible retrieval evaluation | Fixed synthetic corpus and executable evaluator; generated measurements are not general product-accuracy claims | `apps/backend/tests/evals/retrieval/retrieval-corpus-v1.json`; `apps/backend/app/evals/retrieval_eval.py`; `apps/backend/tests/test_retrieval_quality_eval.py` |
| Qdrant query scaling | Localhost p95 performance only; excludes embedding, collection construction, optimizer time, answer quality, and network latency | `output/evals/fix-backlog-16/vector-query-scaling.json`; `apps/backend/app/evals/vector_query_scaling.py`; `apps/backend/tests/test_vector_query_scaling.py` |

## Retrieval evidence boundary

- The corpus is synthetic and versioned in the repository.
- FTS is the production default.
- The deterministic local feature-hash vector and identity reranker are
  diagnostic controls, not semantic or learned models.
- Citation tests prove deterministic acceptance and rejection behavior; they do
  not establish live-model answer quality.
- Quantitative retrieval results may be reported only from a retained evaluator
  output whose configuration hash, corpus version, and command are available.
- Live-provider quality, packaged usability, viewport/DPI behavior, and optional
  hybrid promotion remain outside public claims until their acceptance evidence
  exists.
