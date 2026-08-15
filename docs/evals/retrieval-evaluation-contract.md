# Retrieval Evaluation Contract

Status: active for `LLMWIKI-011` synthetic baseline evidence

Contract version: `retrieval-eval.v1`

Frozen corpus: `agent-pet-retrieval-synthetic-v1.0.0`

## Purpose and claim boundary

This contract defines the fixed synthetic retrieval benchmark and the strict
SQLite FTS baseline used by `LLMWIKI-011`. It measures the current checkout
through the current `RetrievalService` while leaving retrieval code,
tokenization, synonyms, ranking, vector search, RRF, reranking, and answer
generation unchanged.

Passing this contract is L2 evidence for the evaluator, isolated fixture, and
current-checkout FTS baseline only. It is not packaged L3 evidence, a real
Vault trial, a live-provider result, an answer-grounding acceptance result, or
L4 usability evidence. A failed final quality gate is an expected reportable
baseline result and does not by itself close `LLMWIKI-011` or prove user value.

## Frozen inputs

The labelled dataset is
`apps/backend/tests/evals/retrieval/retrieval-corpus-v1.json` with schema
`retrieval-eval-dataset.v1`. It contains exactly one visible, versioned design
set. There is no hidden test set and no claim that the baseline is an unbiased
estimate of a wider population.

The corpus contains only synthetic text. It must not contain real diary,
conversation, Vault, credential, provider, or user-profile data. Every fixture
source uses a `synthetic://` identifier. Credential-shaped strings, private-key
blocks, absolute paths, and gold labels are rejected or kept outside indexed
Markdown.

The corpus is frozen before later vector, fusion, and reranker comparisons.
Changing a query, label, source chunk, normalizer assumption, or slice requires
a new corpus version and a new dataset file. Results from different corpus
hashes must not be compared as a paired promotion result.

## Dataset schema

Every case has:

- a stable `case_id`;
- exactly one `primary_slice` and optional overlapping `tags`;
- a synthetic `fixture_source`;
- the query;
- authoritative `expected_relevant_chunk_ids`;
- `expected_excluded_chunk_ids`;
- requested and expected source scopes;
- an `answerable` or `no_evidence` label;
- a non-private rationale.

Every document declares its logical Vault, relative Markdown path, source
scope, access state, synthetic source, and ordered chunks. Chunk IDs are
stable evaluation identifiers and are never inserted into the indexed title,
heading, or body. Stable citation IDs are derived as:

```text
citation:agent-pet-retrieval-v1:<stable_chunk_id>
```

Source note and chunk IDs are UUIDs and change on every clean rebuild. The
evaluator therefore maps a runtime chunk to a stable evaluation chunk using
all of:

```text
logical Vault + relative path + chunk index + content hash
```

The indexed content hash must match the materialized fixture before scoring.
Gold relevant/excluded IDs are applied only after retrieval and are never
available to the search path.

## Required primary slices

| Primary slice | Minimum cases |
| --- | ---: |
| Exact keyword and identifier | 10 |
| Semantic paraphrase with zero meaningful lexical overlap | 15 |
| Chinese conversational variant | 8 |
| Chinese-English cross-expression | 5 |
| Temporal, date, and entity constrained | 7 |
| Contradictory, stale, or superseded memory | 5 |
| Permission, inactive-memory, and sensitive exclusion | 5 |
| Empty, adversarial, or unanswerable | 5 |

The v1 corpus contains 60 cases. The semantic slice is mechanically checked
for meaningful ASCII term overlap after case-folding, common-word removal, and
simple plural normalization.

The 50 answerable query cases intentionally reuse 22 distinct authoritative
gold evidence sets. Primary quality remains case-macro, so each labelled query
variant has equal weight even when several variants share an evidence set.
Reports disclose the distinct gold-set count per corpus and slice. This is a
clustered design benchmark for fixed query variants, not 50 statistically
independent facts; the case count must not be presented as an independent-
sample count.

## Isolated execution

The runner accepts only a `WorkDir` below repository `.tmp`. `OutputDir` must be
a named child below `output/evals` or remain inside
`output/verification/LLMWIKI-011`. It rejects overlapping directories and
existing directory or artifact reparse points. It never deletes or resets a
directory. Before overwriting a fixed report name, both PowerShell and Python
require an `LLMWIKI-011` ownership manifest and verify every recorded artifact hash.
Python writes through an exclusive temporary regular file followed by atomic
replacement rather than following an existing target. Otherwise the caller
must choose a new output directory. Each invocation creates a unique run
directory containing:

- one synthetic primary Vault;
- one synthetic foreign Vault used to test isolation;
- one newly migrated SQLite database.

The evaluator directly constructs `Database(run_dir /
"retrieval-eval.sqlite3")`; it does not use the default local database or any
environment-selected real Vault. It applies current migrations, indexes both
synthetic Vaults, and searches only the primary Vault ID.

FTS strict means the evaluator explicitly calls:

```python
RetrievalService.search(
    vault_id=primary_vault_id,
    query=case.query,
    top_k=10,
    source_scope=case.requested_source_scope,
    mode="fts",
)
```

Both response metadata and every returned result must report `fts`. The current
current `daily_chat` path also merges its deterministic date/path lookup;
that behavior is part of this current-checkout FTS product baseline and is
reported rather than bypassed.

## Metric definitions

For an answerable case `q`:

```text
Recall@K(q) = |expected relevant IDs intersect top K IDs|
              / |expected relevant IDs|

Precision@K(q) = |expected relevant IDs intersect top K IDs| / K

MRR@10(q) = reciprocal rank of the first relevant ID in top 10,
            or zero when no relevant ID is present

nDCG@10(q) = binary-relevance DCG@10 / ideal binary-relevance DCG@10
```

The denominator of Precision@5 is always five, even when fewer than five
candidates are returned. Quality metrics are macro-averaged over eligible
cases. Micro averages cannot replace a final gate.

No-evidence cases do not enter Recall, Precision, MRR, or nDCG denominators.
At this retrieval-only boundary, an empty candidate list is the explicit
no-evidence result. Any returned candidate makes that case incorrect and is
also inspected for excluded, inaccessible, scope, and cross-Vault leakage.

## Latency and reproducibility

Deterministic FTS runs every case at least once. The runner fixes and records:

- random seed and run count;
- requested/effective mode and completed channels;
- fallback state;
- model, provider, embedding, and temperature (`None`/zero for this baseline);
- normalizer/query-plan, chunker, and index-generation identifiers;
- corpus, evaluator, configuration, and current implementation hashes;
- non-identifying machine fields: operating system, release, architecture,
  logical CPU count, Python version, and SQLite version;
- external request count, transmitted bytes, and external USD cost.

Host name, user name, machine ID, raw query telemetry, and absolute private
paths are not recorded.

Exactly three warm-up queries run before measurements. They are excluded from
percentiles and listed separately. Measured p50 and p95 use the nearest-rank
method. Cold index-build time is reported separately. No measured timeout or
error may be silently discarded.

SQLite FTS has a p95 gate of 200 ms and a hard maximum of 500 ms on the frozen
machine. This local-only run must report zero external requests, zero
transmitted bytes, and USD 0 external cost.

## Citation and faithfulness hooks

`LLMWIKI-011` retrieves candidates but does not generate an answer or invoke a
human/LLM judge. Citation precision, local-fact citation coverage, and grounded
answer faithfulness therefore remain `not_evaluated` in the FTS baseline.
They must not be reported as zero violations or as passing.

The frozen `grounding-hooks.v1` scorer accepts later observations containing:

- `case_id`;
- rendered and accepted citation IDs;
- atomic claims with citation IDs plus deterministic `supported` and
  `faithful` labels.

Final-gate scoring requires exactly one observation for every frozen corpus
case. Missing cases make the result `incomplete`; duplicate or unknown case IDs
are rejected. `supported` and `faithful` must be JSON booleans rather than
truthy strings. Unknown citation IDs in rendered, accepted, or claim citations
increment the fabricated-citation safety count.

The hook implements the zero-denominator rules from the adopted ADR. An
answerable case with no atomic claim receives zero coverage and faithfulness
and is a task failure. A genuine no-evidence case with no claims or citations
is excluded from grounding denominators and remains governed by no-evidence
accuracy and safety gates.

## Final gates

The complete pre-registered retrieval/grounding gates are:

| Gate | Threshold |
| --- | ---: |
| Inaccessible-memory leakage | 0 |
| Expected-excluded-ID leakage | 0 |
| Cross-Vault leakage | 0 |
| Fabricated citations | 0 |
| Local-fact claims with empty accepted evidence | 0 |
| Retrieved prompt-injection changes to route/tool/policy/confirmation | 0 |
| Recall@5 | at least 0.80 |
| Recall@10 | at least 0.90 |
| Precision@5 | at least 0.80 |
| MRR@10 | at least 0.75 |
| nDCG@10 | at least 0.80 |
| Citation precision | at least 0.95 |
| Local-fact citation coverage | 1.00 |
| Grounded-answer faithfulness | at least 0.90 |
| No-evidence accuracy | 1.00 |
| Recall@10 for every eligible answerable primary slice | at least 0.80 |
| Keyword-free Recall@10 delta from FTS | at least +0.15 absolute |
| Exact-query Recall@10 regression from FTS | no more than 0.02 absolute |
| SQLite FTS p95 | at most 200 ms |
| SQLite FTS hard maximum | at most 500 ms |

The FTS baseline is the reference for the two comparative gates; it cannot
satisfy them by comparing itself to itself. Answer/citation and prompt-policy
gates remain not evaluated in `LLMWIKI-011`. Consequently an `LLMWIKI-011` baseline can
complete while the complete final gate remains failed.

## Exit behavior

- Report-only mode writes all artifacts and exits `0` when the evaluator and
  dataset contract execute successfully, even if final quality gates fail.
- `-RequireFinalGates` writes the same artifacts and exits `2` when any required
  gate fails or is not evaluated.
- Invalid input, unsafe paths, materialization/index mismatch, or execution
  failure exits nonzero and must not be described as a completed baseline.

Thresholds do not move after results are observed.

## Reports and failure ownership

Each output directory contains:

- `corpus-manifest.md`;
- `fts-baseline.json`;
- `slice-results.md`;
- `failure-catalog.md`;
- `artifact-hashes.json`.

The artifact hash manifest hashes every required report with SHA-256. The JSON
report includes all case results and per-slice macro metrics; an overall average
never replaces slices. Every failed case records requested/effective mode,
fallback state, reason, expected/actual stable IDs, missing and excluded IDs,
and an expected owner task:

| Failure class | Expected owner |
| --- | --- |
| Dataset, labels, evaluator, strict FTS execution, reproducibility | `LLMWIKI-011` |
| Semantic query planning and vector lifecycle | Optional promotion gate; not the default path |
| Rank fusion, deterministic tie-break, reranker | Optional promotion gate; no accepted report |
| Permission, accepted evidence, lifecycle, citation, no-evidence, prompt injection | `LLMWIKI-007` and `LLMWIKI-011` |

`LLMWIKI-011` records a baseline failure; it does not silently promote an
optional vector or reranker path.

## Reproduction

From the repository root in Windows PowerShell:

```powershell
Push-Location apps\backend
python -m pytest -q tests/test_retrieval_quality_eval.py tests/test_retrieval_fts.py
Pop-Location

.\scripts\run-retrieval-eval.ps1 -Mode Fts -WorkDir .\.tmp\llmwiki-011 -OutputDir .\output\verification\LLMWIKI-011\eval
```

To verify the failing final-gate exit contract, use a distinct work/output
directory and add `-RequireFinalGates`. The nonzero exit is the expected result
until every later retrieval and grounding gate has current evidence.
