# TASK-1204 FTS Slice Results

FTS-only baseline. A failed final gate is recorded and is not tuned away.

| Primary slice | Cases | Recall@5 | Recall@10 | Precision@5 | MRR@10 | nDCG@10 | No-evidence accuracy | Failed cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `exact_keyword_identifier` | 10 | 0.9200 | 1.0000 | 0.9200 | 1.0000 | 0.9759 | n/a | 0 |
| `no_ascii_keyword_overlap` | 15 | 0.0133 | 0.0133 | 0.0133 | 0.0667 | 0.0226 | n/a | 15 |
| `chinese_conversational` | 8 | 0.3750 | 0.3750 | 0.3750 | 0.3750 | 0.3750 | n/a | 5 |
| `cross_expression_zh_en` | 5 | 0.2000 | 0.2000 | 0.2000 | 0.2000 | 0.2000 | n/a | 4 |
| `temporal_date_entity` | 7 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | n/a | 0 |
| `contradictory_stale_superseded` | 5 | 0.7200 | 0.7200 | 0.7200 | 0.8000 | 0.7445 | n/a | 2 |
| `permission_inactive_sensitive` | 5 | n/a | n/a | n/a | n/a | n/a | 1.0000 | 0 |
| `empty_adversarial_unanswerable` | 5 | n/a | n/a | n/a | n/a | n/a | 0.6000 | 2 |

## Overall

- Recall@5: 0.4800
- Recall@10: 0.4960
- Precision@5: 0.4800
- MRR@10: 0.5200
- nDCG@10: 0.4964
- No-evidence accuracy: 0.8000
- FTS p50/p95/hard max: 8.2399 / 26.2747 / 63.3574 ms
- Final gates passed: false
- Citation precision and grounded-answer faithfulness: not evaluated; frozen hooks exist for TASK-1207.
