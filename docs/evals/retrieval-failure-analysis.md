# Production FTS Failure Analysis

Status: current-checkout evidence for `LLMWIKI-011`; regenerated and reviewed on
2026-08-14. This report explains the failing baseline. It does not change the
frozen fixture, lower a threshold, or convert a failed gate into a pass.

## Evidence

The command below materializes an isolated synthetic Vault and invokes the
production evaluator:

```powershell
python scripts\verify_llmwiki_metrics.py `
  --fixture apps\backend\tests\evals\retrieval\retrieval-corpus-v1.json `
  --out output\verification\LLMWIKI-011\eval-20260814
```

The command currently exits `1` because required quality gates fail. The
authoritative artifacts are:

- `output/verification/LLMWIKI-011/eval-20260814/report.json`;
- `output/verification/LLMWIKI-011/eval-20260814/production-fts/fts-baseline.json`;
- `output/verification/LLMWIKI-011/eval-20260814/production-fts/failure-catalog.md`;
- `output/verification/LLMWIKI-011/eval-20260814/production-fts/slice-results.md`;
- `output/verification/LLMWIKI-011/eval-20260814/graph-lifecycle/graph-report.json`.

The run contains 60 cases: 50 answerable and 10 no-evidence. Recall@5 is a
macro-average numerator of `24.8/50 = 0.496`, no-evidence accuracy is
`10/10 = 1.00`, and false activation is `0/10 = 0`. Citation coverage is `0/0` because this runner retrieves
candidates but does not render or judge an answer. The separate graph fixture
passes `21/21` SQLite traversals, `21/21` Kuzu traversals and `21/21`
missing-projection SQLite fallbacks with equal logical relation sets. Its 27
lifecycle cases and 10 no-evidence cases pass, but correction propagation has
only three synthetic samples and remains below the frozen minimum of 20. LLM
extraction/synthesis is still `not_run`.

## Failure Classification

The production failure catalog records 26 cases:

| Category | Cases | Observed evidence | Root-cause clue | Owner/next gate |
| --- | ---: | --- | --- | --- |
| Semantic paraphrase with no ASCII overlap | 15 (`SEM-001`..`SEM-015`) | All 15 are in `no_ascii_keyword_overlap`; 14 have `Recall@10 = 0`, one has `0.20` | The requested channel is SQLite FTS only. The fixture intentionally replaces words such as `illumination`/`bright`, `device-bound`/`offline`, and `undo`/`rollback`; no semantic channel is invoked | Keep FTS as the honest baseline. A later semantic/vector promotion must run a separate candidate, safety, latency and cost comparison; do not call this GraphRAG evidence (`LLMWIKI-007/011`) |
| Chinese conversational retrieval | 5 (`ZH-001`, `ZH-002`, `ZH-005`, `ZH-006`, `ZH-008`) | Slice Recall@10 is `0.375`; three of eight cases pass | `FTS_TOKEN_RE` treats a contiguous Chinese run as one token. The query wording (for example `我是不是说过汇报要短一点？`) does not equal the synthetic sentence wording (`偏好简洁的状态更新`) | Add a measured Chinese segmentation/synonym candidate and rerun the frozen slice; do not alter labels to match the current tokenizer (`LLMWIKI-007/011`) |
| Cross-language expression | 4 (`CROSS-001`, `CROSS-002`, `CROSS-003`, `CROSS-005`) | Slice Recall@10 is `0.20`; only one of five passes | FTS has no translation or multilingual embedding path. Chinese `每周哪天做备份？` cannot match English `Archive replication occurs each Friday`; the one partial match is lexical overlap, not language understanding | Evaluate a bounded multilingual candidate with the same permission/citation gates; current report remains FTS-only (`LLMWIKI-007/011`) |
| Contradictory/superseded facts | 2 (`CONTRA-002`, `CONTRA-004`) | Slice Recall@10 is `0.72`; `CONTRA-002` returns only three of five current chunks and `CONTRA-004` returns none | FTS ranks lexical identifiers and does not itself apply graph lifecycle/supersedes ordering. The evaluator's expected excluded IDs are not leaked, but retrieval quality for current evidence is incomplete | The separate synthetic graph fixture now checks conflict isolation and supersession; FTS quality still fails and graph results do not replace this retrieval slice (`LLMWIKI-006/007/011`) |
| No-evidence false activation | 0 | The exact-identifier qualification gate now rejects candidates that do not contain every stable identifier from the query; both adversarial cases return an empty set | Before the fix, `prior` matched unrelated content and `invent` matched `inventory` through the broad fallback. The authoritative SQLite read now verifies required atoms before fusion | Keep this safety gate in FTS, vector and graph paths; add more adversarial identifiers to the next frozen corpus rather than loosening the threshold (`LLMWIKI-007/011`) |

Recall@5 has one additional ranking signal not listed as a top-10 failure:
`EXACT-008` finds all five KITE chunks by rank 10 but only one in the first
five (`Recall@5 = 0.20`). The aggregate `24.8/50` is a macro sum: 23 cases have
`1.0`, two have `0.2` (`EXACT-008`, `SEM-011`) and one has `0.6`
(`CONTRA-002`), with the remaining semantic/language cases at zero. It is not a
count of successful user questions.

## What Passed

The same run passes the safety gates for inaccessible-memory leakage,
expected-excluded-ID leakage, cross-Vault leakage and fabricated citations, and
measures FTS latency at p50 `6.0046 ms`, p95 `7.4155 ms`, hard maximum
`8.9293 ms`. These are synthetic fixture observations only. They do not prove
semantic recall, answer faithfulness, user efficiency, production-load graph
behavior or business improvement. Kuzu/SQLite logical-set equivalence is proven
only for the 21 synthetic graph traversal cases.

## Required Follow-up Evidence

1. Keep this baseline and its failed exit code in the evidence directory.
2. Implement or evaluate one bounded semantic/Chinese candidate without
   changing the FTS control or fixture labels.
3. Run the candidate through citation, permission, no-evidence, prompt-
   injection, latency and external-cost gates.
4. Keep the measured missing-projection fallback and separately exercise a
   corrupted Kuzu generation; neither graph result substitutes for the FTS
   quality gate.
5. Add answer observations before reporting citation coverage, and collect real
   lifecycle/7-day user denominators before reporting business metrics.

## External verification used for the boundary

- [SQLite FTS5 official documentation](https://www.sqlite.org/fts5.html), accessed
  2026-08-10. It defines FTS5 results as token-instance matches and documents that
  prefix matching requires explicit query syntax; this supports treating a stable
  identifier as an exact required atom rather than accepting a partial lexical
  fallback. The current checkout still uses the default `unicode61` tokenizer, so
  Chinese segmentation and cross-language matching remain separate promotion work.
