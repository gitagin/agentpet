# Claim Evidence Index

Status: narrowed public claims pending final user wording approval.

The simple social chat may use a fast path. SQLite and Markdown are authoritative;
vector indexes are optional derived acceleration.

| Public claim | Qualification | Evidence |
| --- | --- | --- |
| Local-first Windows companion | Local sidecar and data stores; configured remote models still receive approved non-private requests | `README.md`; `docs/current-specification.md` |
| Real bounded LangGraph multi-role workflow | Role contracts are bounded; deterministic components are not called Agents | TASK-1208, TASK-1209, TASK-1211 evidence |
| Read-only parallel specialist retrieval | Opt-in only; sequential fallback remains default | TASK-1210 measured overlap evidence |
| Local RAG with accepted citations | Production Agent default remains FTS | TASK-1207 grounding evidence |
| Persistent high-risk decision resume | Deterministic pending-action checkpoint gate; not a second native LangGraph saver | TASK-1214 checkpoint evidence |
| Deterministic action safety | Policy Guard, Executor, ledger, idempotency, and Verifier are deterministic boundaries | TASK-1212 evidence |
| Measured retrieval candidates | Synthetic corpus results, not general product accuracy | TASK-1204, TASK-1206, TASK-1215 reports |
| Narrowed desktop usability | User manually confirmed the tested FTS/action/HITL/privacy paths | TASK-1216 narrowed L4 sign-off |

## Frozen retrieval context

- Date: 2026-07-12.
- Corpus: `agent-pet-retrieval-synthetic-v1.0.0`.
- Cases: 60 synthetic labelled cases and 120 chunks.
- Run count: one deterministic local comparison per mode.
- Provider/model: no remote provider; deterministic local vector control.
- FTS: Recall@10 `0.496`, MRR@10 `0.520`, no-evidence accuracy `0.800`.
- Vector: Recall@10 `0.628`, MRR@10 `0.694762`, no-evidence accuracy `0.000`.
- Hybrid RRF: Recall@10 `0.672`, MRR@10 `0.720683`, no-evidence accuracy `0.000`.
- Keyword-free Recall@10 delta versus FTS: `+0.226667`.
- Exact-query Recall@10 regression versus FTS: `0.000`.
- Identity reranker nDCG delta: `0.000`; decision: `Defer`.

TASK-1215 did not pass its final retrieval gate. TASK-1216 is Partial (Narrowed
Scope): automated checks and narrowed manual functional paths passed, while
live-provider, packaged executable, viewport/DPI, and full hybrid claims remain
outside accepted public wording.
