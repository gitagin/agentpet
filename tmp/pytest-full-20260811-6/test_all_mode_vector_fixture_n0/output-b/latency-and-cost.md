# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0497 | 0.0892 | 0.1557 |
| `fts` | `fts_search` | 60 | 0.5873 | 1.0032 | 1.8067 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 3.9977 | 5.0157 | 5.3880 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.1229 | 0.2726 | 0.3057 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.0966 | 0.4056 | 0.4139 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.5068 | 0.8226 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 12.0099 | 13.6866 | 14.2145 |
| `vector` | `vector_adapter_residual` | 60 | 1.6465 | 2.3606 | 2.5147 |
| `vector` | `vector_local_search` | 60 | 6.1229 | 6.9506 | 8.0059 |
| `hybrid_rrf` | `embedding` | 60 | 0.1332 | 0.2618 | 0.5832 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.1078 | 0.2588 | 0.3323 |
| `hybrid_rrf` | `fts_search` | 60 | 0.6169 | 1.1959 | 1.7724 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 12.8983 | 16.8106 | 18.7874 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 1.6798 | 2.3418 | 2.6782 |
| `hybrid_rrf` | `vector_local_search` | 60 | 6.2149 | 8.0894 | 9.5159 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.1341 | 0.2516 | 0.2685 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.1052 | 0.2655 | 0.3677 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.6241 | 1.1551 | 1.8577 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0213 | 0.0299 | 0.0378 |
| `hybrid_rrf_identity_control` | `total` | 60 | 12.9060 | 15.1470 | 16.0877 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 1.6766 | 2.2993 | 2.5208 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 6.1941 | 7.4697 | 8.0000 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
