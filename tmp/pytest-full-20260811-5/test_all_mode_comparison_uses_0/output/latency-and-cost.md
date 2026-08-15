# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0532 | 0.1022 | 0.1594 |
| `fts` | `fts_search` | 60 | 0.6094 | 1.2546 | 2.2350 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 4.1964 | 5.3314 | 6.9654 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.1296 | 0.2570 | 0.3670 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.0947 | 0.4265 | 0.5569 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.4601 | 0.8026 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 11.3678 | 12.8206 | 14.9753 |
| `vector` | `vector_adapter_residual` | 60 | 1.5906 | 2.0628 | 2.2988 |
| `vector` | `vector_local_search` | 60 | 5.6892 | 6.4784 | 8.3643 |
| `hybrid_rrf` | `embedding` | 60 | 0.1325 | 0.2648 | 0.4167 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.0916 | 0.2486 | 0.3668 |
| `hybrid_rrf` | `fts_search` | 60 | 0.5760 | 1.2779 | 1.7902 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 12.0939 | 13.8421 | 356.5056 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 1.6192 | 1.8772 | 342.8904 |
| `hybrid_rrf` | `vector_local_search` | 60 | 5.7553 | 6.7469 | 7.8334 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.1417 | 0.2680 | 0.4605 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.0998 | 0.2630 | 0.3523 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.6121 | 1.0683 | 1.7480 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0213 | 0.0282 | 0.0356 |
| `hybrid_rrf_identity_control` | `total` | 60 | 12.4651 | 15.0695 | 15.9875 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 1.7000 | 1.9807 | 3.0334 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 5.8172 | 7.3127 | 7.6989 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
