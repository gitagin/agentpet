# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0626 | 0.0866 | 0.2316 |
| `fts` | `fts_search` | 60 | 0.5548 | 1.1411 | 1.7511 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 4.0935 | 5.0681 | 5.5183 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.1352 | 0.3142 | 0.3395 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.0954 | 0.4074 | 0.5025 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.4791 | 0.8357 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 11.7529 | 13.2227 | 13.6577 |
| `vector` | `vector_adapter_residual` | 60 | 1.5996 | 1.8808 | 2.1424 |
| `vector` | `vector_local_search` | 60 | 5.9714 | 7.0255 | 7.4754 |
| `hybrid_rrf` | `embedding` | 60 | 0.1483 | 0.2754 | 0.4164 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.0971 | 0.2674 | 0.3155 |
| `hybrid_rrf` | `fts_search` | 60 | 0.6146 | 1.1614 | 1.7429 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 12.6470 | 16.7581 | 17.9212 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 1.6721 | 2.0785 | 2.2798 |
| `hybrid_rrf` | `vector_local_search` | 60 | 6.0284 | 8.3655 | 8.8610 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.1284 | 0.2575 | 0.3757 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.0962 | 0.2996 | 0.3724 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.6054 | 1.1774 | 1.8163 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0192 | 0.0406 | 0.0524 |
| `hybrid_rrf_identity_control` | `total` | 60 | 12.6357 | 14.6964 | 16.9349 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 1.6477 | 1.9157 | 2.5343 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 5.9905 | 7.4665 | 8.9172 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
