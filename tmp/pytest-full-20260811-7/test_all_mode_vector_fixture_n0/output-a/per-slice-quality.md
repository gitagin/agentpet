# TASK-1206 Per-Slice Retrieval Quality

- Shared invariants SHA-256: `f89d60f4bf8639a2b832f61958d0dd65e6c5d70644ea7c10337db79ec1a97a70`
- All modes use one isolated SQLite snapshot, one local Qdrant generation, and identical cases.

| Mode | Slice | Recall@10 | MRR@10 | nDCG@10 | No-evidence accuracy | Failed cases |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `fts` | `exact_keyword_identifier` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `fts` | `no_ascii_keyword_overlap` | 0.0133 | 0.0667 | 0.0226 | n/a | 15 |
| `fts` | `chinese_conversational` | 0.3750 | 0.3750 | 0.3750 | n/a | 5 |
| `fts` | `cross_expression_zh_en` | 0.2000 | 0.2000 | 0.2000 | n/a | 4 |
| `fts` | `temporal_date_entity` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `fts` | `contradictory_stale_superseded` | 0.7200 | 0.8000 | 0.7445 | n/a | 2 |
| `fts` | `permission_inactive_sensitive` | n/a | n/a | n/a | 1.0000 | 0 |
| `fts` | `empty_adversarial_unanswerable` | n/a | n/a | n/a | 1.0000 | 0 |
| `vector` | `exact_keyword_identifier` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `vector` | `no_ascii_keyword_overlap` | 0.2667 | 0.2563 | 0.1858 | n/a | 15 |
| `vector` | `chinese_conversational` | 0.4500 | 0.8438 | 0.4833 | n/a | 8 |
| `vector` | `cross_expression_zh_en` | 0.3600 | 0.4286 | 0.3390 | n/a | 5 |
| `vector` | `temporal_date_entity` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `vector` | `contradictory_stale_superseded` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `vector` | `permission_inactive_sensitive` | n/a | n/a | n/a | 1.0000 | 0 |
| `vector` | `empty_adversarial_unanswerable` | n/a | n/a | n/a | 1.0000 | 0 |
| `hybrid_rrf` | `exact_keyword_identifier` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `hybrid_rrf` | `no_ascii_keyword_overlap` | 0.2400 | 0.2428 | 0.1695 | n/a | 15 |
| `hybrid_rrf` | `chinese_conversational` | 0.6500 | 0.9062 | 0.6432 | n/a | 5 |
| `hybrid_rrf` | `cross_expression_zh_en` | 0.5600 | 0.6286 | 0.5100 | n/a | 4 |
| `hybrid_rrf` | `temporal_date_entity` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `hybrid_rrf` | `contradictory_stale_superseded` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `hybrid_rrf` | `permission_inactive_sensitive` | n/a | n/a | n/a | 1.0000 | 0 |
| `hybrid_rrf` | `empty_adversarial_unanswerable` | n/a | n/a | n/a | 1.0000 | 0 |
| `hybrid_rrf_identity_control` | `exact_keyword_identifier` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `hybrid_rrf_identity_control` | `no_ascii_keyword_overlap` | 0.2400 | 0.2428 | 0.1695 | n/a | 15 |
| `hybrid_rrf_identity_control` | `chinese_conversational` | 0.6500 | 0.9062 | 0.6432 | n/a | 5 |
| `hybrid_rrf_identity_control` | `cross_expression_zh_en` | 0.5600 | 0.6286 | 0.5100 | n/a | 4 |
| `hybrid_rrf_identity_control` | `temporal_date_entity` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `hybrid_rrf_identity_control` | `contradictory_stale_superseded` | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `hybrid_rrf_identity_control` | `permission_inactive_sensitive` | n/a | n/a | n/a | 1.0000 | 0 |
| `hybrid_rrf_identity_control` | `empty_adversarial_unanswerable` | n/a | n/a | n/a | 1.0000 | 0 |

## Fixed promotion checks

- No-ASCII-keyword-overlap Recall@10 delta: 0.2267 (pass: true)
- Exact-query Recall@10 regression: 0.0000 (pass: true)
- Failed cases remain listed in mode-comparison.json; no query was removed from averages.
