# LLM Wiki fixture metrics

- status: `failed`
- exit_code: `1`
- evaluator: `llmwiki-metrics-eval.v3`
- production evaluator: `app.evals.retrieval_eval`
- production evaluator version: `retrieval-eval.v1`
- threshold_version: `llmwiki-gates.v1`
- corpus: `agent-pet-retrieval-synthetic-v1.0.0`
- cases: `60`
- privacy: the summary contains counts, hashes and fixed labels; source text is not emitted.

| Metric | Numerator | Denominator | Value | Threshold | Status | Evidence |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| retrieval_recall_at_5 | 24.8000 | 50 | 0.4960 | gte 0.8000 | failed | sufficient |
| citation_coverage | 0 | 0 | insufficient | gte 0.9500 | insufficient_sample | insufficient_sample |
| no_evidence_accuracy | 10 | 10 | 1.0000 | gte 1.0000 | passed | sufficient |
| false_activation | 0 | 10 | 0.0000 | lte 0.0000 | passed | sufficient |

## Evidence boundaries

SQLite graph, Kuzu acceleration and a removed-projection SQLite fallback are measured on the versioned synthetic graph fixture. LLM extraction/synthesis remains `not_run`; correction propagation remains below its frozen minimum sample. Synthetic evidence is not a substitute for a 7-day trial or 24-hour soak.
