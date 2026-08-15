# LLM Wiki graph evaluation contract

## Scope

`apps/backend/tests/evals/llmwiki/graph-lifecycle-v1.json` is a versioned,
synthetic-only fixture for the SQLite memory authority, Kuzu derived projection,
projection-failure fallback, and lifecycle recall gates. It does not contain or
stand in for user conversations, a live provider run, a 7-day trial, or a
24-hour soak.

The fixture contains 27 lifecycle cases and 10 no-evidence cases. The lifecycle
set covers active one- and two-hop traversal, preferences, boundaries, projects,
goals, events, duplicate evidence, correction, forgetting, conflict isolation,
expiry, sensitivity, Vault scope, and Wiki documentation relations.

## Reproduction

```powershell
python scripts/verify_llmwiki_metrics.py `
  --fixture apps/backend/tests/evals/retrieval/retrieval-corpus-v1.json `
  --out output/verification/LLMWIKI-011/eval
```

The command writes the graph evidence under
`output/verification/LLMWIKI-011/eval/graph-lifecycle/`. The combined runner is
expected to return exit code `1` while the frozen retrieval Recall@5 gate fails;
passing graph channels must not hide that failure.

## Channel semantics

- `sqlite_graph` calls the production `MemoryEntityGraphStore` traversal and
  answerability gates.
- `kuzu_acceleration` rebuilds one derived generation and requires every
  traversal to report source `kuzu` with the same logical relation set as
  SQLite. A missing optional Kuzu dependency is `not_run`, never a pass.
- `sqlite_graph_fallback` removes the published derived projection, requires
  source `sqlite`, records the fallback reason, and compares every result with
  the authority baseline.
- Fact lifecycle cases stay on the SQLite authority because Kuzu accelerates
  graph traversal; it is not a second fact store.
- Reports contain case IDs, fixed logical keys, counts, hashes, statuses, and
  timings. They omit fixture queries and synthetic source text.

## External verification

Checked on 2026-08-10 against local `kuzu==0.11.3` and the repository constraint
`kuzu>=0.11,<1`.

- Kuzu 0.11.3 official Python source:
  <https://github.com/kuzudb/kuzu/blob/v0.11.3/tools/python_api/src_py/database.py>
  documents `database_path` as the path to database files and states that
  `read_only=True` disallows write transactions.
- Kuzu 0.11.3 official tests:
  <https://github.com/kuzudb/kuzu/blob/v0.11.3/tools/python_api/test/test_database.py>
  exercise `Path` database locations and explicit close behavior.

The evaluator therefore treats the projection location as a filesystem path,
supports either a file or directory when injecting the missing-generation
fault, closes Kuzu handles before removal, and verifies the behavior again with
local tests. These sources define storage mechanics only; authorization and
fallback correctness still come from this repository's production code and
tests.

## Current evidence boundary

The deterministic fixture currently demonstrates equivalent logical relation
sets for SQLite, Kuzu, and missing-projection fallback. It supplies three
synthetic correction observations, below the frozen minimum sample of 20, so
correction propagation remains `insufficient_sample` in the combined report.

The deterministic graph baseline records zero model calls and zero external
cost. LLM extraction/synthesis remains `not_run`; no quality, latency, cost, or
AI uplift is inferred. Lookup duration, confirmation burden, Wiki reuse, real
user benefit, and long-run stability also remain outside this synthetic gate.
