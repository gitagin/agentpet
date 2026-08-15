# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0517 | 0.0977 | 0.1664 |
| `fts` | `fts_search` | 60 | 0.5977 | 1.0364 | 1.9244 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 4.0487 | 5.1011 | 6.0087 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.1347 | 0.2498 | 0.2761 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.1002 | 0.4056 | 0.5161 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.5126 | 1.0369 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 11.9610 | 12.9605 | 13.9636 |
| `vector` | `vector_adapter_residual` | 60 | 1.6741 | 1.9604 | 2.0194 |
| `vector` | `vector_local_search` | 60 | 6.0852 | 6.7885 | 8.1197 |
| `hybrid_rrf` | `embedding` | 60 | 0.1248 | 0.2533 | 0.4026 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.0933 | 0.2604 | 0.3182 |
| `hybrid_rrf` | `fts_search` | 60 | 0.6078 | 1.0337 | 1.7602 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 12.8350 | 16.2382 | 17.3466 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 1.6345 | 2.5061 | 2.8952 |
| `hybrid_rrf` | `vector_local_search` | 60 | 6.1052 | 8.1741 | 9.6733 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.1367 | 0.2634 | 0.4993 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.1067 | 0.3848 | 0.4477 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.6036 | 1.4656 | 1.9699 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0218 | 0.0371 | 0.0513 |
| `hybrid_rrf_identity_control` | `total` | 60 | 13.1064 | 16.8050 | 19.8080 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 1.6719 | 2.3145 | 3.3846 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 6.3297 | 8.0134 | 9.9022 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
